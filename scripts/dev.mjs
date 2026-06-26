import { spawn } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, '..');
const rendererUrl = process.env.ELECTRON_RENDERER_URL ?? 'http://127.0.0.1:5173';

function npmCommand() {
  return process.platform === 'win32' ? 'npm.cmd' : 'npm';
}

function binPath(name) {
  const executable = process.platform === 'win32' ? `${name}.cmd` : name;
  return path.join(root, 'node_modules', '.bin', executable);
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: root,
      stdio: 'inherit',
      shell: false,
      ...options,
    });
    child.on('exit', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} ${args.join(' ')} exited with ${code}`));
      }
    });
    child.on('error', reject);
  });
}

function waitForPort(port, host = '127.0.0.1', timeoutMs = 20000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const tryConnect = () => {
      const socket = net.connect({ port, host });
      socket.once('connect', () => {
        socket.destroy();
        resolve();
      });
      socket.once('error', () => {
        socket.destroy();
        if (Date.now() - started > timeoutMs) {
          reject(new Error(`Timed out waiting for ${host}:${port}`));
          return;
        }
        setTimeout(tryConnect, 180);
      });
    };
    tryConnect();
  });
}

await run(npmCommand(), ['run', 'build:main']);
await run(npmCommand(), ['run', 'build:preload']);

const vite = spawn(npmCommand(), ['run', 'dev:renderer'], {
  cwd: root,
  stdio: 'inherit',
  shell: false,
  env: {
    ...process.env,
    ELYAN_ELECTRON_DEV: '1',
  },
});

const stopChildren = () => {
  vite.kill('SIGTERM');
};

process.on('SIGINT', () => {
  stopChildren();
  process.exit(130);
});
process.on('SIGTERM', () => {
  stopChildren();
  process.exit(143);
});

await waitForPort(5173);

const electron = spawn(binPath('electron'), ['.'], {
  cwd: root,
  stdio: 'inherit',
  shell: false,
  env: {
    ...process.env,
    ELECTRON_RENDERER_URL: rendererUrl,
    NODE_ENV: 'development',
  },
});

electron.on('exit', (code) => {
  stopChildren();
  process.exit(code ?? 0);
});
