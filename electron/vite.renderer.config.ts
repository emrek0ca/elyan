import path from 'node:path';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { RuntimeSupervisor } from './src/main/runtime-supervisor';
import type { DesktopPlatform, RuntimeRequest } from './src/shared/protocol';

function desktopPlatform(): DesktopPlatform {
  return process.platform === 'win32' || process.platform === 'linux' || process.platform === 'darwin' ? process.platform : 'linux';
}

function readBody(request: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let raw = '';
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 1024 * 1024) {
        reject(new Error('PREVIEW_BODY_TOO_LARGE'));
        request.destroy();
      }
    });
    request.on('end', () => {
      try {
        resolve(raw ? JSON.parse(raw) : {});
      } catch {
        reject(new Error('PREVIEW_INVALID_JSON'));
      }
    });
    request.on('error', reject);
  });
}

function sendJson(response: ServerResponse, status: number, payload: unknown): void {
  response.statusCode = status;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.end(JSON.stringify(payload));
}

function createPreviewRuntimeBridge() {
  const desktopRoot = path.resolve(__dirname);
  const supervisor = new RuntimeSupervisor({
    desktopRoot,
    workspaceRoot: path.resolve(desktopRoot, '..'),
    resourcesPath: path.resolve(desktopRoot, 'build'),
    packaged: false,
    platform: desktopPlatform(),
  });
  void supervisor.start();

  return {
    async handle(request: IncomingMessage, response: ServerResponse, next: () => void) {
      if (!request.url?.startsWith('/__elyan_preview/')) {
        next();
        return;
      }
      if (request.method !== 'POST') {
        sendJson(response, 405, { ok: false, error: { code: 'METHOD_NOT_ALLOWED', message: 'Preview bridge sadece POST kabul eder.' } });
        return;
      }
      try {
        if (request.url.startsWith('/__elyan_preview/bootstrap')) {
          sendJson(response, 200, await supervisor.bootstrap());
          return;
        }
        if (request.url.startsWith('/__elyan_preview/request')) {
          const body = (await readBody(request)) as RuntimeRequest;
          sendJson(response, 200, await supervisor.request(body));
          return;
        }
        sendJson(response, 404, { ok: false, error: { code: 'UNKNOWN_PREVIEW_ENDPOINT', message: 'Preview bridge endpoint bulunamadı.' } });
      } catch {
        sendJson(response, 500, { ok: false, error: { code: 'PREVIEW_BRIDGE_FAILED', message: 'Preview runtime bridge güvenli şekilde yanıt veremedi.' } });
      }
    },
    stop() {
      void supervisor.stop();
    },
  };
}

function elyanPreviewBridgePlugin() {
  return {
    name: 'elyan-preview-runtime-bridge',
    configureServer(server: { middlewares: { use: (handler: (request: IncomingMessage, response: ServerResponse, next: () => void) => void) => void }; httpServer?: { once: (event: string, listener: () => void) => void } }) {
      const bridge = createPreviewRuntimeBridge();
      server.middlewares.use((request, response, next) => {
        void bridge.handle(request, response, next);
      });
      server.httpServer?.once('close', () => bridge.stop());
    },
    configurePreviewServer(server: { middlewares: { use: (handler: (request: IncomingMessage, response: ServerResponse, next: () => void) => void) => void }; httpServer?: { once: (event: string, listener: () => void) => void } }) {
      const bridge = createPreviewRuntimeBridge();
      server.middlewares.use((request, response, next) => {
        void bridge.handle(request, response, next);
      });
      server.httpServer?.once('close', () => bridge.stop());
    },
  };
}

export default defineConfig({
  root: path.resolve(__dirname, 'src/renderer'),
  plugins: [react(), elyanPreviewBridgePlugin()],
  resolve: {
    alias: {
      '@renderer': path.resolve(__dirname, 'src/renderer'),
      '@shared': path.resolve(__dirname, 'src/shared'),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    fs: {
      allow: [path.resolve(__dirname), path.resolve(__dirname, '..', '..', 'mobile-elyan')],
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
  },
  build: {
    outDir: path.resolve(__dirname, 'dist/renderer'),
    emptyOutDir: false,
  },
});
