const { app, BrowserWindow, ipcMain, dialog, shell, safeStorage, Notification, Menu } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { rpc } = require('./rpc.cjs');

app.setName('Soulseek Studio');
const stateDir = process.env.SLSK_STATE_DIR || path.join(app.getPath('appData'), 'Soulseek Studio');
app.setPath('userData', stateDir);
const socketPath = process.env.SLSK_SOCKET || path.join(stateDir, 'soulseek.sock');
const credentialsPath = path.join(stateDir, 'credentials.enc');
const root = path.resolve(__dirname, '..');
const rendererPath = path.join(root, 'dist/renderer/index.html');
const rendererURL = pathToFileURL(rendererPath).href;
let window;
let backend;
let backendReady = false;
let startupError = '';
let quitting = false;
let notificationTimer;
const completed = new Set();
const notifiedWishes = new Set();
let observedInitialState = false;

const allowedMethods = new Set([
  'status', 'snapshot', 'settings_get', 'configure', 'connect', 'disconnect',
  'search', 'results', 'stop_search', 'download', 'download_folder', 'transfers',
  'pause_transfer', 'resume_transfer', 'retry_transfer', 'remove_transfer',
  'shares', 'share_add', 'share_remove', 'shares_rescan', 'browse_user',
  'wishlist', 'wishlist_add', 'wishlist_update', 'wishlist_remove', 'wishlist_run',
]);

function trusted(event) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame || event.senderFrame.url.split('#')[0] !== rendererURL) {
    throw new Error('Request denied: unknown application frame.');
  }
}

async function request(method, params = {}) {
  if (!backendReady) throw new Error(startupError || 'The backend is starting. Try again in a moment.');
  return rpc(socketPath, method, params);
}

async function readCredentials() {
  try { return JSON.parse(await fs.readFile(credentialsPath, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw new Error('Stored credentials could not be read. Save them again in Settings.'); }
}

async function decryptCredential(record) {
  if (!record?.secret) return '';
  return safeStorage.decryptStringAsync(Buffer.from(record.secret, 'base64'));
}

async function startBackend() {
  await fs.mkdir(stateDir, { recursive: true, mode: 0o700 });
  await fs.chmod(stateDir, 0o700);
  try {
    await rpc(socketPath, 'status', {}, 1000);
    backendReady = true;
    return;
  } catch { /* The backend owns stale-socket recovery and singleton locking. */ }
  const executable = app.isPackaged
    ? path.join(process.resourcesPath, 'backend', 'soulseek-backend')
    : path.join(root, '.venv/bin/python');
  const args = app.isPackaged ? [] : ['-m', 'soulseek_mcp.daemon'];
  backend = spawn(executable, args, {
    cwd: app.isPackaged ? stateDir : root,
    env: { ...process.env, PYTHONUNBUFFERED: '1', SLSK_STATE_DIR: stateDir, SLSK_SOCKET: socketPath },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  // Do not relay arbitrary dependency diagnostics into the renderer or persist
  // protocol messages. Python applies credential-aware logging separately.
  backend.stderr.on('data', () => {});
  backend.on('error', () => { startupError = 'Could not start the bundled backend. Rebuild the application and try again.'; });
  backend.on('exit', (code) => {
    backendReady = false;
    if (!quitting) startupError = `The backend stopped (${code ?? 'terminated'}). Reopen Soulseek Studio to recover saved state.`;
  });
  for (let attempt = 0; attempt < 100; attempt++) {
    if (startupError) throw new Error(startupError);
    try {
      await rpc(socketPath, 'status', {}, 500);
      backendReady = true;
      return;
    } catch { await new Promise(resolve => setTimeout(resolve, 200)); }
  }
  throw new Error('The backend did not become ready. Reopen Soulseek Studio.');
}

async function restoreCredentials() {
  const record = await readCredentials();
  if (!record?.secret) return;
  const status = await request('status');
  if (!status.connected) {
    try {
      const password = await decryptCredential(record);
      await request('configure', { username: record.username, password });
    } catch {
      // Do not block the app when the system keychain is temporarily locked.
      // Settings can save fresh credentials without exposing the old password.
    }
  }
}

function createWindow() {
  window = new BrowserWindow({
    title: 'Soulseek Studio', width: 1340, height: 880, minWidth: 960, minHeight: 680,
    backgroundColor: '#f4f2ed', show: false,
    titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 20, y: 20 },
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, url) => { if (url.split('#')[0] !== rendererURL) event.preventDefault(); });
  window.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  window.webContents.session.setPermissionCheckHandler(() => false);
  window.loadFile(rendererPath);
  window.once('ready-to-show', () => window.show());
  window.on('closed', () => { window = null; });
}

function registerIPC() {
  ipcMain.handle('soulseek:rpc', async (event, method, params = {}) => {
    trusted(event);
    if (!allowedMethods.has(method) || !params || Array.isArray(params) || typeof params !== 'object') throw new Error('Unknown operation.');
    if (Buffer.byteLength(JSON.stringify(params)) > 65536) throw new Error('Request too large.');
    if (method === 'configure' && 'password' in params) throw new Error('Save credentials through the credential settings.');
    if (method === 'configure' && typeof params.username === 'string') {
      const credentials = await readCredentials();
      if (credentials?.secret && credentials.username !== params.username.trim()) throw new Error('Enter your password to change accounts.');
    }
    return request(method, params);
  });
  ipcMain.handle('soulseek:directory', async event => {
    trusted(event);
    const selection = await dialog.showOpenDialog(window, { properties: ['openDirectory', 'createDirectory'], title: 'Choose a folder' });
    return selection.canceled ? null : selection.filePaths[0];
  });
  ipcMain.handle('soulseek:credentials-info', async event => {
    trusted(event);
    const record = await readCredentials();
    const status = await request('settings_get');
    return { username: status.username || record?.username || '', hasPassword: Boolean(status.credentials_configured || record?.secret) };
  });
  ipcMain.handle('soulseek:credentials-save', async (event, values) => {
    trusted(event);
    if (!values || typeof values.username !== 'string' || typeof values.password !== 'string' || values.username.length > 256 || values.password.length > 4096) throw new Error('Invalid credentials.');
    const username = values.username.trim();
    if (!username || !values.password) throw new Error('Enter both username and password.');
    if (!(await safeStorage.isAsyncEncryptionAvailable())) throw new Error('System credential storage is unavailable. Unlock your keychain and try again.');
    const secret = await safeStorage.encryptStringAsync(values.password);
    await request('configure', { username, password: values.password });
    const temporary = `${credentialsPath}.tmp`;
    await fs.writeFile(temporary, JSON.stringify({ username, secret: secret.toString('base64') }), { mode: 0o600 });
    await fs.chmod(temporary, 0o600);
    await fs.rename(temporary, credentialsPath);
    return { username, hasPassword: true };
  });
  ipcMain.handle('soulseek:reveal', async (event, filePath) => {
    trusted(event);
    if (typeof filePath !== 'string' || !path.isAbsolute(filePath)) throw new Error('Invalid path.');
    const settings = await request('settings_get');
    if (path.resolve(filePath) === path.resolve(settings.download_dir)) await fs.mkdir(settings.download_dir, { recursive: true });
    const rootPath = await fs.realpath(settings.download_dir);
    const target = await fs.realpath(filePath);
    const relative = path.relative(rootPath, target);
    if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Only files in the download folder can be revealed.');
    if (target === rootPath) {
      const error = await shell.openPath(rootPath);
      if (error) throw new Error('The download folder could not be opened.');
    } else shell.showItemInFolder(target);
  });
  ipcMain.handle('soulseek:notify', async (event, title, body) => {
    trusted(event);
    const settings = await request('settings_get');
    if (settings.notifications && Notification.isSupported()) new Notification({ title: String(title).slice(0, 100), body: String(body).slice(0, 250) }).show();
  });
}

async function monitorCompletions() {
  if (!backendReady) return;
  try {
    const [snapshot, settings] = await Promise.all([request('snapshot'), request('settings_get')]);
    for (const transfer of snapshot.transfers || []) {
      if (transfer.state === 'COMPLETE' && !completed.has(transfer.transfer_id)) {
        completed.add(transfer.transfer_id);
        if (observedInitialState && settings.notifications && Notification.isSupported()) new Notification({ title: 'Download complete', body: path.basename(transfer.local_path || transfer.filename).slice(0, 250) }).show();
      }
    }
    for (const wish of snapshot.wishlist || []) {
      if (wish.last_count > 0 && wish.last_search_id && !notifiedWishes.has(wish.last_search_id)) {
        notifiedWishes.add(wish.last_search_id);
        if (observedInitialState && settings.notifications && Notification.isSupported()) new Notification({ title: 'Wishlist matches found', body: `${wish.query}: ${wish.last_count} results`.slice(0, 250) }).show();
      }
    }
    while (notifiedWishes.size > 200) notifiedWishes.delete(notifiedWishes.values().next().value);
    while (completed.size > 200) completed.delete(completed.values().next().value);
    observedInitialState = true;
  } catch { /* Next interval retries observation, never a download. */ }
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => { if (!window) createWindow(); window.show(); window.focus(); });
  app.whenReady().then(async () => {
    registerIPC();
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: app.name, submenu: [{ role: 'about' }, { type: 'separator' }, { role: 'hide' }, { role: 'hideOthers' }, { type: 'separator' }, { role: 'quit' }] },
      { label: 'Edit', submenu: [{ role: 'undo' }, { role: 'redo' }, { type: 'separator' }, { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' }] },
      { label: 'View', submenu: [{ role: 'reload' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'togglefullscreen' }] },
      { role: 'windowMenu' },
    ]));
    try { await startBackend(); await restoreCredentials(); }
    catch (error) { startupError = error.message; }
    createWindow();
    notificationTimer = setInterval(monitorCompletions, 5000);
    app.on('activate', () => { if (!window) createWindow(); else window.show(); });
  });
  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
  app.on('before-quit', event => {
    if (quitting) return;
    quitting = true;
    clearInterval(notificationTimer);
    if (backend && backend.exitCode === null) {
      event.preventDefault();
      const timer = setTimeout(() => { backend.kill('SIGKILL'); app.quit(); }, 18000);
      timer.unref();
      backend.once('exit', () => { clearTimeout(timer); app.quit(); });
      backend.kill('SIGTERM');
    }
  });
}
