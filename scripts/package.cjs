const fs = require('node:fs/promises');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { packager } = require('@electron/packager');

async function main() {
  const root = path.resolve(__dirname, '..');
  if (!process.argv.includes('--reuse-backend')) {
    const built = spawnSync(path.join(root, '.venv/bin/python'), [
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'soulseek-backend',
    '--distpath', '.build/python', '--workpath', '.build/pyinstaller', '--specpath', '.build',
    '--paths', 'src', '--collect-all', 'aioslsk', '--collect-data', 'mcp',
    '--add-data', 'src/soulseek_mcp/beatport_feed.py:soulseek_mcp',
    '--collect-all', 'mutagen',
    'scripts/backend_entry.py',
  ], { cwd: root, stdio: 'inherit' });
    if (built.status !== 0) throw new Error('Backend packaging failed.');
  }
  await fs.access(path.join(root, '.build/python/soulseek-backend/soulseek-backend'));
  const staging = path.join(root, '.build/desktop');
  await fs.mkdir(staging, { recursive: true });
  for (const item of ['electron', 'dist/renderer']) await fs.cp(path.join(root, item), path.join(staging, item), { recursive: true });
  const manifest = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'));
  const minimal = { name: manifest.name, productName: manifest.productName, version: manifest.version, main: manifest.main, license: manifest.license };
  await fs.writeFile(path.join(staging, 'package.json'), JSON.stringify(minimal, null, 2));
  await fs.copyFile(path.join(root, 'THIRD_PARTY_NOTICES.md'), path.join(staging, 'THIRD_PARTY_NOTICES.md'));
  await fs.copyFile(path.join(root, 'LICENSE'), path.join(staging, 'LICENSE'));
  const outputs = await packager({
    dir: staging, name: manifest.productName, platform: 'darwin', arch: 'arm64',
    electronVersion: manifest.devDependencies.electron, out: path.join(root, 'release'),
    icon: path.join(root, 'assets/icon.icns'),
    overwrite: true, asar: true, appBundleId: 'local.soulseek.studio',
    appCategoryType: 'public.app-category.music',
    extraResource: [path.join(root, '.build/python/soulseek-backend')],
    darwinDarkModeSupport: true,
  });
  // Packager uses the source basename for extra resources. Normalize it to the
  // stable path expected by the app launcher.
  for (const output of outputs) {
    const resources = path.join(output, `${manifest.productName}.app/Contents/Resources`);
    await fs.rm(path.join(resources, 'backend'), { recursive: true, force: true });
    await fs.rename(path.join(resources, 'soulseek-backend'), path.join(resources, 'backend'));
    console.log(path.join(output, `${manifest.productName}.app`));
  }
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });
