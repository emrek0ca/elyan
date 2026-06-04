import path from 'node:path';
import { app, Menu, powerMonitor, shell } from 'electron';
import { loadNativeWindowAddon } from './native/addon-loader';
import { buildNativeDesktopSnapshot, persistNativeDesktopSnapshot } from './native/runtime-snapshot';
import { registerDesktopIpc } from './ipc';
import { ProviderVault } from './provider-vault';
import { RuntimeSupervisor } from './runtime-supervisor';
import { WindowManager } from './window-manager';
import type { DesktopPlatform, NativeDesktopSnapshot } from '../shared/protocol';

const platform = process.platform as DesktopPlatform;

let runtimeSupervisor: RuntimeSupervisor | null = null;
let windowManager: WindowManager | null = null;
let providerVault: ProviderVault | null = null;
let nativeDesktopSnapshot: NativeDesktopSnapshot | null = null;
let nativeSnapshotPath = '';

function buildApplicationMenu(workspaceRoot: string): void {
  const algorithmPath = process.env.ELYAN_ALGORITHM_DOC || path.resolve(workspaceRoot, '..', 'elyan_ekosistem_algoritmasi.txt');
  const template = [
    {
      label: 'Elyan',
      submenu: [
        { role: 'about' as const },
        { type: 'separator' as const },
        { role: 'quit' as const },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' as const },
        { role: 'togglefullscreen' as const },
        ...(process.env.NODE_ENV !== 'production' ? [{ role: 'toggleDevTools' as const }] : []),
      ],
    },
    {
      label: 'Window',
      submenu: [{ role: 'minimize' as const }, { role: 'zoom' as const }],
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Open Elyan Algorithm',
          click: () => {
            void shell.openPath(algorithmPath);
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function ensureSingleInstance(): void {
  const gotLock = app.requestSingleInstanceLock();
  if (gotLock) {
    app.on('second-instance', () => {
      windowManager?.createOrFocus();
    });
    return;
  }
  app.quit();
}

async function bootstrapDesktopShell(): Promise<void> {
  const desktopRoot = path.resolve(__dirname, '..', '..');
  const workspaceRoot = path.resolve(desktopRoot, '..');
  nativeSnapshotPath = path.join(app.getPath('userData'), 'native', 'desktop-runtime.json');
  const nativeAddon = loadNativeWindowAddon({
    desktopRoot,
    resourcesPath: process.resourcesPath,
    packaged: app.isPackaged,
    platform,
  });
  const runtimeEnvironment = {
    ...process.env,
    ELYAN_DESKTOP_NATIVE_STATE_PATH: nativeSnapshotPath,
  };
  await refreshNativeDesktopSnapshot(nativeAddon);
  runtimeSupervisor = new RuntimeSupervisor({
    desktopRoot,
    workspaceRoot,
    resourcesPath: process.resourcesPath,
    packaged: app.isPackaged,
    environment: runtimeEnvironment,
    platform,
  });
  windowManager = new WindowManager({
    app,
    desktopRoot,
    platform,
    chrome: nativeAddon.capabilities,
  });
  providerVault = new ProviderVault(app.getPath('userData'), process.platform);
  registerDesktopIpc({
    supervisor: runtimeSupervisor,
    windowManager,
    nativeAddon,
    providerVault,
    getWindow: () => windowManager?.getWindow() ?? null,
    getNativeDesktopSnapshot: () => nativeDesktopSnapshot ?? nativeAddon.runtimeSnapshot,
  });
  buildApplicationMenu(workspaceRoot);
  windowManager.createOrFocus();
  void runtimeSupervisor.start();
  void syncProviderVaultToRuntime();
  powerMonitor.on('resume', () => {
    void refreshNativeDesktopSnapshot(nativeAddon);
    void refreshControlPlaneTruth();
  });
  powerMonitor.on('unlock-screen', () => {
    void refreshNativeDesktopSnapshot(nativeAddon);
    void refreshControlPlaneTruth();
  });
  powerMonitor.on('on-ac', () => {
    void refreshNativeDesktopSnapshot(nativeAddon);
    void refreshControlPlaneTruth();
  });
}

async function refreshNativeDesktopSnapshot(nativeAddon: ReturnType<typeof loadNativeWindowAddon>): Promise<void> {
  if (!nativeSnapshotPath) {
    return;
  }
  try {
    nativeDesktopSnapshot = await buildNativeDesktopSnapshot(platform, nativeAddon);
    await persistNativeDesktopSnapshot(nativeDesktopSnapshot, nativeSnapshotPath);
  } catch {
    nativeDesktopSnapshot = {
      ...nativeAddon.runtimeSnapshot,
      collectedAt: new Date().toISOString(),
      lastErrorCode: 'native_snapshot_persist_failed',
    };
  }
}

async function syncProviderVaultToRuntime(): Promise<void> {
  if (!providerVault || !runtimeSupervisor) {
    return;
  }
  const secrets = await providerVault.listSecrets();
  for (const [providerId, secret] of Object.entries(secrets)) {
    await runtimeSupervisor.request({
      capability: 'providers.secrets_sync',
      payload: { providerId, secret },
    });
  }
}

async function refreshControlPlaneTruth(): Promise<void> {
  if (!runtimeSupervisor) {
    return;
  }
  await runtimeSupervisor.request({ capability: 'runtime.status', payload: {} });
  await runtimeSupervisor.request({ capability: 'backend.auth_me', payload: {} });
  await runtimeSupervisor.request({ capability: 'backend.mobile_bootstrap', payload: {} });
  await runtimeSupervisor.request({ capability: 'runtime.session', payload: {} });
}

ensureSingleInstance();

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  windowManager?.createOrFocus();
});

app.on('before-quit', () => {
  windowManager?.prepareForQuit();
  void runtimeSupervisor?.stop();
});

void app.whenReady().then(bootstrapDesktopShell);
