import path from 'node:path';
import fs from 'node:fs';
import { BrowserWindow, type App } from 'electron';
import { EventEmitter } from 'node:events';
import type { DesktopPlatform, WindowState } from '../shared/protocol';
import type { NativeWindowChromeCapabilities } from './native/addon-loader';

interface WindowManagerOptions {
  app: App;
  desktopRoot: string;
  platform: DesktopPlatform;
  chrome: NativeWindowChromeCapabilities;
}

export class WindowManager extends EventEmitter {
  private window: BrowserWindow | null = null;
  private closeTimer: NodeJS.Timeout | null = null;
  private isClosing = false;
  private allowClose = false;

  constructor(private readonly options: WindowManagerOptions) {
    super();
  }

  createOrFocus(): BrowserWindow {
    if (this.window && !this.window.isDestroyed()) {
      if (this.window.isMinimized()) {
        this.window.restore();
      }
      this.window.focus();
      return this.window;
    }

    const preloadPath = path.join(this.options.desktopRoot, 'dist', 'preload', 'index.js');
    const appIconPath = this.resolveAppIconPath();
    if (this.options.platform === 'darwin' && appIconPath) {
      this.options.app.dock?.setIcon(appIconPath);
    }
    const browserWindow = new BrowserWindow({
      width: 1460,
      height: 960,
      minWidth: 1120,
      minHeight: 760,
      show: false,
      frame: false,
      titleBarStyle: this.options.platform === 'darwin' ? 'hiddenInset' : 'hidden',
      titleBarOverlay:
        this.options.platform === 'win32'
          ? {
              color: '#f5efe5',
              symbolColor: '#231e18',
              height: 44,
            }
          : false,
      icon: appIconPath,
      trafficLightPosition:
        this.options.platform === 'darwin'
          ? {
              x: this.options.chrome.trafficLightOffsetX,
              y: this.options.chrome.trafficLightOffsetY,
            }
          : undefined,
      backgroundColor: '#f6f1e7',
      webPreferences: {
        preload: preloadPath,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        spellcheck: false,
      },
    });

    this.window = browserWindow;
    this.bindWindowEvents(browserWindow);
    this.loadRenderer(browserWindow);
    return browserWindow;
  }

  private resolveAppIconPath(): string {
    const platformIcon = this.options.platform === 'win32' ? 'icon.ico' : 'icon.png';
    const fallbackIconPath = path.resolve(this.options.desktopRoot, '..', 'logo.png');
    const candidates = [
      path.join(this.options.app.isPackaged ? process.resourcesPath : path.join(this.options.desktopRoot, 'resources'), platformIcon),
      path.join(this.options.app.isPackaged ? process.resourcesPath : path.join(this.options.desktopRoot, 'resources'), 'icon.png'),
      fallbackIconPath,
    ];
    return candidates.find((candidate) => fs.existsSync(candidate)) ?? fallbackIconPath;
  }

  getWindow(): BrowserWindow | null {
    return this.window && !this.window.isDestroyed() ? this.window : null;
  }

  minimize(): void {
    this.getWindow()?.minimize();
  }

  maximizeOrRestore(): WindowState {
    const browserWindow = this.getWindow();
    if (!browserWindow) {
      return this.stateSnapshot();
    }
    if (browserWindow.isMaximized()) {
      browserWindow.unmaximize();
    } else {
      browserWindow.maximize();
    }
    return this.stateSnapshot();
  }

  close(): void {
    const browserWindow = this.getWindow();
    if (!browserWindow) {
      return;
    }
    if (this.allowClose) {
      browserWindow.close();
      return;
    }
    this.requestClose();
  }

  acknowledgeCloseAnimation(): void {
    if (!this.isClosing) {
      return;
    }
    this.forceClose('renderer_ack');
  }

  stateSnapshot(): WindowState {
    const browserWindow = this.getWindow();
    return {
      isFocused: browserWindow?.isFocused() ?? false,
      isVisible: browserWindow?.isVisible() ?? false,
      isMaximized: browserWindow?.isMaximized() ?? false,
      isMinimized: browserWindow?.isMinimized() ?? false,
      isFullScreen: browserWindow?.isFullScreen() ?? false,
      isClosing: this.isClosing,
      platform: this.options.platform,
    };
  }

  prepareForQuit(): void {
    this.allowClose = true;
    if (this.closeTimer) {
      clearTimeout(this.closeTimer);
      this.closeTimer = null;
    }
  }

  private bindWindowEvents(browserWindow: BrowserWindow): void {
    browserWindow.on('ready-to-show', () => {
      browserWindow.show();
      this.emitLifecycle('window.ready');
    });
    browserWindow.on('close', (event) => {
      if (this.allowClose) {
        return;
      }
      event.preventDefault();
      this.requestClose();
    });
    browserWindow.on('closed', () => {
      this.window = null;
      this.isClosing = false;
      this.allowClose = false;
      this.emitLifecycle('window.closed');
    });
    browserWindow.on('focus', () => this.emitLifecycle('window.focus'));
    browserWindow.on('blur', () => this.emitLifecycle('window.blur'));
    browserWindow.on('maximize', () => this.emitLifecycle('window.maximize'));
    browserWindow.on('unmaximize', () => this.emitLifecycle('window.unmaximize'));
    browserWindow.on('minimize', () => this.emitLifecycle('window.minimize'));
    browserWindow.on('restore', () => this.emitLifecycle('window.restore'));
    browserWindow.on('enter-full-screen', () => this.emitLifecycle('window.enter-full-screen'));
    browserWindow.on('leave-full-screen', () => this.emitLifecycle('window.leave-full-screen'));
  }

  private loadRenderer(browserWindow: BrowserWindow): void {
    const devUrl = process.env.ELECTRON_RENDERER_URL;
    if (devUrl) {
      void browserWindow.loadURL(devUrl);
      return;
    }
    void browserWindow.loadFile(path.join(this.options.desktopRoot, 'dist', 'renderer', 'index.html'));
  }

  private requestClose(): void {
    const browserWindow = this.getWindow();
    if (!browserWindow || this.isClosing) {
      return;
    }
    this.isClosing = true;
    this.emit('close-handshake', {
      phase: 'requested',
      state: this.stateSnapshot(),
    });
    this.closeTimer = setTimeout(() => {
      this.forceClose('timeout');
    }, 260);
  }

  private forceClose(reason: string): void {
    const browserWindow = this.getWindow();
    if (!browserWindow) {
      return;
    }
    this.allowClose = true;
    this.isClosing = true;
    if (this.closeTimer) {
      clearTimeout(this.closeTimer);
      this.closeTimer = null;
    }
    this.emit('close-handshake', {
      phase: 'confirmed',
      reason,
      state: this.stateSnapshot(),
    });
    browserWindow.close();
  }

  private emitLifecycle(type: string): void {
    this.emit('window-lifecycle', {
      type,
      state: this.stateSnapshot(),
    });
  }
}
