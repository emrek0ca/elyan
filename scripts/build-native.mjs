import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const addonRoot = path.join(root, 'native', 'window_tools');
const macosNativeRoot = path.join(root, 'native', 'macos');
const nodeGyp = path.join(root, 'node_modules', '.bin', process.platform === 'win32' ? 'node-gyp.cmd' : 'node-gyp');
const required = process.env.ELYAN_NATIVE_REQUIRED === '1';

function buildOptionalMacNativeGlass() {
  if (process.platform !== 'darwin') {
    return;
  }
  if (process.env.ELYAN_NATIVE_MAC_GLASS === '0') {
    console.warn('[elyan-native] optional macOS Swift glass bridge disabled by ELYAN_NATIVE_MAC_GLASS=0.');
    return;
  }
  const swiftSource = path.join(macosNativeRoot, 'ElyanNativeGlass.swift');
  if (!fs.existsSync(swiftSource)) {
    console.warn('[elyan-native] optional macOS Swift glass bridge source missing; CSS glass fallback remains available.');
    return;
  }
  const swiftProbe = spawnSync('xcrun', ['--find', 'swiftc'], { stdio: 'pipe', shell: false });
  if (swiftProbe.status !== 0) {
    console.warn('[elyan-native] swiftc not found; CSS glass fallback remains available.');
    return;
  }
  const outputDir = path.join(addonRoot, 'build', 'Release');
  fs.mkdirSync(outputDir, { recursive: true });
  const outputPath = path.join(outputDir, 'libelyan_native_glass.dylib');
  const result = spawnSync('xcrun', [
    'swiftc',
    '-emit-library',
    '-parse-as-library',
    '-O',
    '-module-name',
    'ElyanNativeGlass',
    swiftSource,
    '-o',
    outputPath,
  ], {
    cwd: root,
    stdio: 'inherit',
    shell: false,
  });
  if (result.status !== 0) {
    console.warn('[elyan-native] optional macOS Swift glass bridge build failed; CSS glass fallback remains available.');
    if (required) {
      process.exit(result.status ?? 1);
    }
  }
}

if (!fs.existsSync(path.join(addonRoot, 'binding.gyp'))) {
  console.warn('[elyan-native] window_tools binding.gyp missing; skipping optional native addon build.');
  process.exit(required ? 1 : 0);
}

if (!fs.existsSync(nodeGyp)) {
  console.warn('[elyan-native] node-gyp is not installed; run npm install before building native addon.');
  process.exit(required ? 1 : 0);
}

const result = spawnSync(nodeGyp, ['rebuild'], {
  cwd: addonRoot,
  stdio: 'inherit',
  shell: false,
});

if (result.status !== 0) {
  console.warn('[elyan-native] optional native addon build failed; Electron will use safe window capability fallbacks.');
  process.exit(required ? result.status ?? 1 : 0);
}

buildOptionalMacNativeGlass();
