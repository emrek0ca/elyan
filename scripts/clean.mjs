import fs from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const workspaceRoot = root;

const electronPaths = [
  'dist',
  'release',
  'test-results',
  'playwright-report',
  'coverage',
  '.vitest',
  'build/pyinstaller-work',
  'build/runtime',
  'native/window_tools/build',
];

const workspacePaths = [
  '.pytest_cache',
  '__pycache__',
  'actions/__pycache__',
  'runtime/__pycache__',
  'tests/__pycache__',
  'memory/__pycache__',
];

for (const relative of electronPaths) {
  await fs.rm(path.join(root, relative), { recursive: true, force: true });
}

for (const relative of workspacePaths) {
  await fs.rm(path.join(workspaceRoot, relative), { recursive: true, force: true });
}
