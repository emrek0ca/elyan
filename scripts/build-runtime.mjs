import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const workspaceRoot = root;
const bridgeScript = path.join(workspaceRoot, 'runtime', 'bridge.py');
const required = process.env.ELYAN_RUNTIME_BUNDLE_REQUIRED === '1';

function platformFolder() {
  if (process.platform === 'darwin') {
    return 'macos';
  }
  if (process.platform === 'win32') {
    return 'windows';
  }
  return 'linux';
}

function runtimeBinaryName() {
  return process.platform === 'win32' ? 'elyan-runtime.exe' : 'elyan-runtime';
}

function pythonExecutable() {
  return process.env.ELYAN_DESKTOP_PYTHON || process.env.ELYAN_PYTHON_BIN || (process.platform === 'win32' ? 'python' : 'python3');
}

const outputRoot = path.join(root, 'build', 'runtime', platformFolder());
fs.mkdirSync(outputRoot, { recursive: true });
for (const marker of ['PYINSTALLER_MISSING.txt', 'RUNTIME_MISSING.txt']) {
  fs.rmSync(path.join(outputRoot, marker), { force: true });
}
const existingRuntimeBinary = path.join(outputRoot, 'elyan-runtime', runtimeBinaryName());

if (!fs.existsSync(bridgeScript)) {
  console.warn('[elyan-runtime] runtime/bridge.py missing; packaged runtime cannot be built.');
  fs.writeFileSync(path.join(outputRoot, 'RUNTIME_MISSING.txt'), 'runtime/bridge.py was not found.\n');
  process.exit(required ? 1 : 0);
}

const python = pythonExecutable();
const pyinstallerCheck = spawnSync(python, ['-m', 'PyInstaller', '--version'], {
  cwd: workspaceRoot,
  encoding: 'utf8',
  shell: false,
});

if (pyinstallerCheck.status !== 0) {
  if (fs.existsSync(existingRuntimeBinary)) {
    console.warn('[elyan-runtime] PyInstaller unavailable; reusing the existing packaged runtime binary.');
    process.exit(0);
  }
  console.warn('[elyan-runtime] PyInstaller unavailable; packaged app will fall back to degraded runtime status unless a runtime binary is supplied.');
  fs.writeFileSync(path.join(outputRoot, 'PYINSTALLER_MISSING.txt'), 'Install PyInstaller or set ELYAN_RUNTIME_BUNDLE_REQUIRED=1 in CI.\n');
  process.exit(required ? 1 : 0);
}

const distPath = outputRoot;
const workPath = path.join(root, 'build', 'pyinstaller-work', platformFolder());
fs.mkdirSync(workPath, { recursive: true });

const result = spawnSync(
  python,
  [
    '-m',
    'PyInstaller',
    '--clean',
    '--noconfirm',
    '--name',
    'elyan-runtime',
    '--distpath',
    distPath,
    '--workpath',
    workPath,
    '--specpath',
    path.join(root, 'pyinstaller'),
    bridgeScript,
  ],
  {
    cwd: workspaceRoot,
    stdio: 'inherit',
    shell: false,
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
    },
  },
);

if (result.status !== 0) {
  console.warn('[elyan-runtime] PyInstaller runtime bundle failed.');
  process.exit(required ? result.status ?? 1 : 0);
}
