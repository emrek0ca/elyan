import path from 'node:path';
import fs from 'node:fs';
import { app, globalShortcut, Menu, powerMonitor, session, shell } from 'electron';
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
let operatorAbortFlagPath = '';
let emergencyShortcutRegistered = false;
let controlPlaneSyncTimer: NodeJS.Timeout | null = null;
let controlPlaneSyncInFlight: Promise<void> | null = null;

const MACOS_PERMISSION_URIS: Record<string, string> = {
  accessibility: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility',
  screenrecording: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
  screen_recording: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture',
  inputmonitoring: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent',
  input_monitoring: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent',
  automation: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Automation',
  privacy: 'x-apple.systempreferences:com.apple.preference.security?Privacy',
};

function normalizePermissionName(value: string): string {
  return String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
}

async function openSystemPermissionSettings(permission: string): Promise<boolean> {
  if (platform !== 'darwin') {
    return false;
  }
  const normalized = normalizePermissionName(permission);
  const target = MACOS_PERMISSION_URIS[normalized] ?? MACOS_PERMISSION_URIS.privacy ?? 'x-apple.systempreferences:com.apple.preference.security?Privacy';
  await shell.openExternal(target);
  return true;
}

function buildApplicationMenu(workspaceRoot: string): void {
  const algorithmPath = process.env.ELYAN_ALGORITHM_DOC || path.resolve(workspaceRoot, '..', 'elyan_ekosistem_algoritmasi.txt');
  const template = [
    {
      label: 'Elyan',
      submenu: [
        { role: 'about' as const },
        { type: 'separator' as const },
        { role: 'hide' as const },
        { role: 'hideOthers' as const },
        { role: 'unhide' as const },
        { type: 'separator' as const },
        { role: 'quit' as const },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' as const },
        { role: 'redo' as const },
        { type: 'separator' as const },
        { role: 'cut' as const },
        { role: 'copy' as const },
        { role: 'paste' as const },
        { role: 'pasteAndMatchStyle' as const },
        { role: 'delete' as const },
        { role: 'selectAll' as const },
        { type: 'separator' as const },
        {
          label: 'Speech',
          submenu: [
            { role: 'startSpeaking' as const },
            { role: 'stopSpeaking' as const },
          ],
        },
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
      submenu: [
        { role: 'minimize' as const },
        { role: 'zoom' as const },
        { type: 'separator' as const },
        { role: 'front' as const },
      ],
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
  const workspaceRoot = desktopRoot;
  nativeSnapshotPath = path.join(app.getPath('userData'), 'native', 'desktop-runtime.json');
  operatorAbortFlagPath = path.join(app.getPath('temp'), 'elyan-operator', 'abort.flag');
  const nativeAddon = loadNativeWindowAddon({
    desktopRoot,
    resourcesPath: process.resourcesPath,
    packaged: app.isPackaged,
    platform,
  });
  const runtimeEnvironment = {
    ...process.env,
    ELYAN_DESKTOP_NATIVE_STATE_PATH: nativeSnapshotPath,
    ELYAN_OPERATOR_ABORT_FLAG_PATH: operatorAbortFlagPath,
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
    openSystemPermissionSettings,
    getAttachmentStoreDir: () => path.join(app.getPath('temp'), 'elyan-attachments'),
  });
  buildApplicationMenu(workspaceRoot);
  // Grant clipboard permissions so Cmd+C/Cmd+V/paste work inside the renderer.
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    const granted = ['clipboard-read', 'clipboard-sanitized-write', 'media'].includes(permission);
    callback(granted);
  });
  session.defaultSession.setPermissionCheckHandler((_webContents, permission) => {
    return ['clipboard-read', 'clipboard-sanitized-write', 'media'].includes(permission);
  });
  windowManager.createOrFocus();
  void runtimeSupervisor.start();
  scheduleControlPlaneTruthSync();
  void refreshControlPlaneTruth();
  registerOperatorEmergencyStopShortcut(nativeAddon);
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

function getControlPlaneRefreshIntervalMs(): number {
  const raw = Number.parseFloat(process.env.ELYAN_CONTROL_PLANE_REFRESH_INTERVAL_SECONDS ?? '45');
  const normalized = Number.isFinite(raw) ? raw : 45;
  return Math.max(15000, Math.min(300000, Math.round(normalized * 1000)));
}

function scheduleControlPlaneTruthSync(): void {
  if (controlPlaneSyncTimer) {
    clearInterval(controlPlaneSyncTimer);
  }
  controlPlaneSyncTimer = setInterval(() => {
    void refreshControlPlaneTruth();
  }, getControlPlaneRefreshIntervalMs());
  controlPlaneSyncTimer.unref?.();
}

function emitRuntimeStatus(payload: unknown): void {
  const browserWindow = windowManager?.getWindow();
  if (!browserWindow || browserWindow.isDestroyed()) {
    return;
  }
  browserWindow.webContents.send('runtime-status', payload);
}

function emitBackendTruth(payload: unknown): void {
  const browserWindow = windowManager?.getWindow();
  if (!browserWindow || browserWindow.isDestroyed()) {
    return;
  }
  browserWindow.webContents.send('backend-truth', payload);
}

async function refreshNativeDesktopSnapshot(nativeAddon: ReturnType<typeof loadNativeWindowAddon>): Promise<void> {
  if (!nativeSnapshotPath) {
    return;
  }
  try {
    nativeDesktopSnapshot = await buildNativeDesktopSnapshot(platform, nativeAddon);
    nativeDesktopSnapshot = {
      ...nativeDesktopSnapshot,
      operator: {
        ...nativeDesktopSnapshot.operator,
        emergencyStopAvailable: emergencyShortcutRegistered,
      },
    };
    await persistNativeDesktopSnapshot(nativeDesktopSnapshot, nativeSnapshotPath);
  } catch {
    nativeDesktopSnapshot = {
      ...nativeAddon.runtimeSnapshot,
      collectedAt: new Date().toISOString(),
      lastErrorCode: 'native_snapshot_persist_failed',
    };
  }
}

function writeOperatorAbortFlag(reason: string): void {
  if (!operatorAbortFlagPath) {
    return;
  }
  fs.mkdirSync(path.dirname(operatorAbortFlagPath), { recursive: true });
  fs.writeFileSync(
    operatorAbortFlagPath,
    JSON.stringify({ reason, at: new Date().toISOString() }),
    'utf-8',
  );
}

function registerOperatorEmergencyStopShortcut(nativeAddon: ReturnType<typeof loadNativeWindowAddon>): void {
  if (platform !== 'darwin' || !nativeAddon.capabilities.globalShortcuts) {
    emergencyShortcutRegistered = false;
    void refreshNativeDesktopSnapshot(nativeAddon);
    return;
  }
  globalShortcut.unregister('CommandOrControl+Shift+Escape');
  emergencyShortcutRegistered = globalShortcut.register('CommandOrControl+Shift+Escape', () => {
    writeOperatorAbortFlag('emergency_stop');
    void runtimeSupervisor?.request({
      capability: 'desktop_operator.cancel',
      payload: {
        reason: 'emergency_stop',
        source: 'global_shortcut',
      },
    });
  });
  void refreshNativeDesktopSnapshot(nativeAddon);
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
  if (controlPlaneSyncInFlight) {
    return controlPlaneSyncInFlight;
  }
  controlPlaneSyncInFlight = (async () => {
    const response = await runtimeSupervisor.request({ capability: 'backend.truth_refresh', payload: {} });
    if (!response.ok || !response.result || typeof response.result !== 'object') {
      return;
    }
    const result = response.result as Record<string, unknown>;
    emitBackendTruth(result);
    if (result.runtime) {
      emitRuntimeStatus(result.runtime);
    }
  })().finally(() => {
    controlPlaneSyncInFlight = null;
  });
  return controlPlaneSyncInFlight;
}

function clearControlPlaneTruthSync(): void {
  if (controlPlaneSyncTimer) {
    clearInterval(controlPlaneSyncTimer);
    controlPlaneSyncTimer = null;
  }
}

app.on('before-quit', () => {
  clearControlPlaneTruthSync();
  globalShortcut.unregisterAll();
  windowManager?.prepareForQuit();
  void runtimeSupervisor?.stop();
});

ensureSingleInstance();

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  windowManager?.createOrFocus();
});

app.setName('Elyan');
void app.whenReady().then(bootstrapDesktopShell);
