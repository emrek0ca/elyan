import { ipcMain, type BrowserWindow } from 'electron';
import { IPC_CHANNELS, type DesktopSubscriptionChannel } from '../shared/channels';
import type { ElyanDesktopApi } from '../shared/desktop-api';
import type { NativeDesktopSnapshot, SystemCapabilities, WindowState } from '../shared/protocol';
import type { NativeWindowAddon } from './native/addon-loader';
import type { ProviderVault } from './provider-vault';
import { RuntimeSupervisor } from './runtime-supervisor';
import { WindowManager } from './window-manager';

interface RegisterDesktopIpcOptions {
  supervisor: RuntimeSupervisor;
  windowManager: WindowManager;
  nativeAddon: NativeWindowAddon;
  providerVault: ProviderVault;
  getWindow: () => BrowserWindow | null;
  getNativeDesktopSnapshot: () => NativeDesktopSnapshot;
}

function emitToRenderer(getWindow: () => BrowserWindow | null, channel: DesktopSubscriptionChannel, payload: unknown): void {
  const browserWindow = getWindow();
  if (!browserWindow || browserWindow.isDestroyed()) {
    return;
  }
  browserWindow.webContents.send(channel, payload);
}

export function registerDesktopIpc(options: RegisterDesktopIpcOptions): void {
  const { supervisor, windowManager, nativeAddon, providerVault, getWindow, getNativeDesktopSnapshot } = options;

  ipcMain.handle(IPC_CHANNELS.bootstrap, async () => supervisor.bootstrap());
  ipcMain.handle(IPC_CHANNELS.request, async (_event, request) => {
    const response = await supervisor.request(request);
    if (response.events.length > 0) {
      emitToRenderer(getWindow, 'runtime-event', {
        requestId: response.requestId ?? response.id,
        events: response.events,
      });
    }
    if (response.capability === 'runtime.status' && response.ok) {
      emitToRenderer(getWindow, 'runtime-status', response.result);
    }
    if (response.capability === 'bootstrap' && response.ok && response.result && typeof response.result === 'object') {
      const result = response.result as Record<string, unknown>;
      if (result.runtime) {
        emitToRenderer(getWindow, 'runtime-status', result.runtime);
      }
      if (result.backend) {
        emitToRenderer(getWindow, 'backend-truth', result.backend);
      }
    }
    return response;
  });

  ipcMain.handle(IPC_CHANNELS.windowMinimize, async () => {
    windowManager.minimize();
  });
  ipcMain.handle(IPC_CHANNELS.windowMaximizeOrRestore, async (): Promise<WindowState> => windowManager.maximizeOrRestore());
  ipcMain.handle(IPC_CHANNELS.windowClose, async () => {
    windowManager.close();
  });
  ipcMain.handle(IPC_CHANNELS.windowGetState, async (): Promise<WindowState> => windowManager.stateSnapshot());
  ipcMain.handle(IPC_CHANNELS.windowAckCloseAnimation, async () => {
    windowManager.acknowledgeCloseAnimation();
  });
  ipcMain.handle(IPC_CHANNELS.systemGetCapabilities, async (): Promise<SystemCapabilities> => ({
    platform: windowManager.stateSnapshot().platform,
    windowChrome: {
      customTitlebar: nativeAddon.capabilities.customTitlebar,
      closeAnimation: nativeAddon.capabilities.closeAnimation,
      trafficLights: nativeAddon.capabilities.trafficLights,
      vibrancy: nativeAddon.capabilities.vibrancy,
      mica: nativeAddon.capabilities.mica,
      clientSideDecorations: nativeAddon.capabilities.clientSideDecorations,
      tray: nativeAddon.capabilities.tray,
      attention: nativeAddon.capabilities.attention,
    },
    nativeControl: {
      automation: nativeAddon.capabilities.automation,
      screenCapture: nativeAddon.capabilities.screenCapture,
      globalShortcuts: nativeAddon.capabilities.globalShortcuts,
      fileSystemAccess: nativeAddon.capabilities.fileSystemAccess,
      processInspection: nativeAddon.capabilities.processInspection,
      permissionRequired: nativeAddon.capabilities.permissionRequired,
      rendererDirectControl: nativeAddon.capabilities.rendererDirectControl,
      sideEffectsRequireTaskId: nativeAddon.capabilities.sideEffectsRequireTaskId,
      osPermissionModel: nativeAddon.capabilities.osPermissionModel,
      accessibilityPermissionRequired: nativeAddon.capabilities.accessibilityPermissionRequired,
      screenRecordingPermissionRequired: nativeAddon.capabilities.screenRecordingPermissionRequired,
      inputMonitoringPermissionRequired: nativeAddon.capabilities.inputMonitoringPermissionRequired,
      automationPermissionRequired: nativeAddon.capabilities.automationPermissionRequired,
    },
    runtime: supervisor.getAvailability(),
    nativeAddon: nativeAddon.status,
    nativeDesktop: getNativeDesktopSnapshot(),
  }));
  ipcMain.handle(IPC_CHANNELS.providersGetVaultStatus, async () => providerVault.getStatus());
  ipcMain.handle(IPC_CHANNELS.providersSaveSecret, async (_event, payload) => {
    const status = await providerVault.saveSecret(String(payload?.providerId ?? ''), String(payload?.secret ?? ''));
    await supervisor.request({
      capability: 'providers.secrets_sync',
      payload: {
        providerId: String(payload?.providerId ?? ''),
        secret: String(payload?.secret ?? ''),
      },
    });
    return status;
  });
  ipcMain.handle(IPC_CHANNELS.providersRemoveSecret, async (_event, payload) => {
    const providerId = String(payload?.providerId ?? '');
    const status = await providerVault.removeSecret(providerId);
    await supervisor.request({
      capability: 'providers.secrets_sync',
      payload: {
        providerId,
        remove: true,
      },
    });
    return status;
  });

  supervisor.on('status', (payload) => {
    emitToRenderer(getWindow, 'runtime-status', payload);
  });
  supervisor.on('runtime-event', (payload) => {
    emitToRenderer(getWindow, 'runtime-event', payload);
  });
  windowManager.on('window-lifecycle', (payload) => {
    emitToRenderer(getWindow, 'window-lifecycle', payload);
  });
  windowManager.on('close-handshake', (payload) => {
    emitToRenderer(getWindow, 'close-handshake', payload);
  });
}

export type DesktopApiShape = ElyanDesktopApi;
