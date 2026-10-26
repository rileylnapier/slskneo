const { _electron: electron } = require('playwright');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const { rpc } = require('../electron/rpc.cjs');

async function eventually(check, timeout = 15000) {
  const start = Date.now();
  let last;
  while (Date.now() - start < timeout) {
    try { await check(); return; } catch (error) { last = error; }
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw last || new Error('Condition did not become true.');
}

async function main() {
  const root = path.resolve(__dirname, '..');
  const temporary = await fs.mkdtemp('/tmp/soulseek-electron-');
  const stateDir = path.join(temporary, 'state');
  const socketPath = path.join(stateDir, 'soulseek.sock');
  const sharedDir = path.join(temporary, 'Music');
  await fs.mkdir(sharedDir);
  await fs.writeFile(path.join(sharedDir, 'offline-test.txt'), 'Local integration fixture. Never shared on the network.');
  const executable = process.env.SLSK_ELECTRON_EXECUTABLE || require('electron');
  const packed = Boolean(process.env.SLSK_ELECTRON_EXECUTABLE);
  const app = await electron.launch({
    executablePath: executable, args: packed ? [] : [root],
    env: { ...process.env, SLSK_STATE_DIR: stateDir, SLSK_SOCKET: socketPath, SLSK_USERNAME: '', SLSK_PASSWORD: '' },
    timeout: 45000,
  });
  try {
    const page = await app.firstWindow();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.getByRole('navigation').getByRole('button', { name: 'Search', exact: true }).waitFor();
    await eventually(async () => assert.equal((await rpc(socketPath, 'status')).connected, false));
    const privileged = await page.evaluate(() => ({ require: typeof window.require, process: typeof window.process }));
    assert.deepEqual(privileged, { require: 'undefined', process: 'undefined' });
    await page.screenshot({ path: path.join(root, 'analysis/electron-search.png') });

    await page.getByRole('navigation').getByRole('button', { name: 'Wishlist', exact: true }).click();
    await page.getByLabel('New wishlist search').fill('Integration wishlist');
    await page.getByRole('button', { name: 'Add to wishlist', exact: true }).click();
    await eventually(async () => assert.equal((await rpc(socketPath, 'wishlist')).items[0]?.query, 'Integration wishlist'));
    const wish = (await rpc(socketPath, 'wishlist')).items[0];
    await page.getByRole('switch', { name: 'Pause wishlist search Integration wishlist' }).click();
    await eventually(async () => assert.equal((await rpc(socketPath, 'wishlist')).items[0]?.enabled, false));
    await rpc(socketPath, 'wishlist_update', { id: wish.id, enabled: true });
    await page.getByRole('switch', { name: 'Pause wishlist search Integration wishlist' }).waitFor();
    await page.screenshot({ path: path.join(root, 'analysis/electron-wishlist.png') });
    await page.getByRole('button', { name: 'Remove wishlist search', exact: true }).click();
    await eventually(async () => assert.equal((await rpc(socketPath, 'wishlist')).items.length, 0));

    await app.evaluate(({ dialog }, folder) => { dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [folder] }); }, sharedDir);
    await page.getByRole('navigation').getByRole('button', { name: 'Shared Files', exact: true }).click();
    await page.getByRole('button', { name: /Add.*folder/i }).first().click();
    await eventually(async () => {
      const shares = await rpc(socketPath, 'shares');
      assert.equal(shares.total_files, 1);
      assert.equal(shares.directories[0].path, await fs.realpath(sharedDir));
    });
    await page.screenshot({ path: path.join(root, 'analysis/electron-shares.png') });

    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await page.getByRole('heading', { name: 'Soulseek account', exact: true }).waitFor();
    await page.getByRole('switch', { name: 'Download completion notifications' }).click();
    await page.getByRole('button', { name: 'Save settings', exact: true }).click();
    await eventually(async () => assert.equal((await rpc(socketPath, 'settings_get')).notifications, false));
    await page.screenshot({ path: path.join(root, 'analysis/electron-settings.png') });
    await page.getByRole('navigation').getByRole('button', { name: 'Downloads', exact: true }).click();
    await page.screenshot({ path: path.join(root, 'analysis/electron-downloads.png') });
    assert.equal((await rpc(socketPath, 'status')).connected, false);

    // Exercise the first-login UI without creating a network account or touching
    // the keychain. All earlier checks above use the real backend.
    const loginSettings = await rpc(socketPath, 'settings_get');
    await app.evaluate(({ ipcMain }, defaults) => {
      let saved = false;
      let connected = false;
      globalThis.loginTestCalls = [];
      ipcMain.removeHandler('soulseek:credentials-save');
      ipcMain.handle('soulseek:credentials-save', (_event, values) => {
        assertLogin(values.username === 'local-login-fixture' && Boolean(values.password));
        saved = true;
        globalThis.loginTestCalls.push('save');
        return { username: values.username, hasPassword: true };
      });
      function assertLogin(valid) { if (!valid) throw new Error('Login fixture was not passed to credential storage.'); }
      ipcMain.removeHandler('soulseek:credentials-info');
      ipcMain.handle('soulseek:credentials-info', () => ({ username: 'local-login-fixture', hasPassword: saved }));
      ipcMain.removeHandler('soulseek:rpc');
      ipcMain.handle('soulseek:rpc', (_event, method) => {
        if (method === 'configure') { globalThis.loginTestCalls.push('configure'); return defaults; }
        if (method === 'connect') { assertLogin(saved); globalThis.loginTestCalls.push('connect'); connected = true; return { connected }; }
        if (method === 'settings_get') return { ...defaults, username: 'local-login-fixture', credentials_configured: saved };
        if (method === 'snapshot') return { status: { connected, credentials_configured: saved }, searches: [], transfers: [], uploads: [], wishlist: [], shares: [], history: [] };
        throw new Error('Unexpected login-test method: ' + method);
      });
    }, loginSettings);
    await page.getByRole('navigation').getByRole('button', { name: 'Settings', exact: true }).click();
    const loginButton = page.getByRole('button', { name: 'Save and connect', exact: true });
    assert.equal(await loginButton.isEnabled(), false);
    await page.getByRole('textbox', { name: 'Username', exact: true }).fill('local-login-fixture');
    await page.getByLabel('Password', { exact: true }).fill('local-fixture-only');
    assert.equal(await loginButton.isEnabled(), true, 'Typing credentials enables login without a separate save');
    await loginButton.click();
    await page.getByRole('button', { name: 'Disconnect', exact: true }).first().waitFor();
    assert.deepEqual(await app.evaluate(() => globalThis.loginTestCalls), ['save', 'configure', 'connect']);
    assert.equal((await rpc(socketPath, 'status')).connected, false, 'Login UI test must never connect the real backend');
    assert.deepEqual(errors, [], 'No renderer runtime errors');
    const report = { healthy: true, packaged: packed, checks: [
      'Electron startup with real backend', 'isolated renderer', 'five tabs',
      'wishlist create/toggle/remove', 'shared UI/socket state', 'real offline file indexing',
      'settings persistence without credentials', 'first-login save-and-connect flow', 'no implicit login', 'no renderer errors',
    ] };
    await fs.writeFile(path.join(root, packed ? 'analysis/packaged-smoke.json' : 'analysis/electron-smoke.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report));
  } finally {
    await app.close();
    await fs.rm(temporary, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
