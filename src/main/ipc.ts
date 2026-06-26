import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { app, ipcMain, type BrowserWindow } from 'electron';
import { IPC_CHANNELS, type DesktopSubscriptionChannel } from '../shared/channels';
import type { ElyanDesktopApi, AttachmentSaveResult } from '../shared/desktop-api';
import type { NativeDesktopSnapshot, SystemCapabilities, WindowState } from '../shared/protocol';
import type { NativeWindowAddon } from './native/addon-loader';
import type { ProviderVault } from './provider-vault';
import { RuntimeSupervisor } from './runtime-supervisor';
import { WindowManager } from './window-manager';
import { DictationManager } from './dictation/dictationManager';
import { createTempAudioPath } from './dictation/audio/tempAudio';

interface RegisterDesktopIpcOptions {
  supervisor: RuntimeSupervisor;
  windowManager: WindowManager;
  nativeAddon: NativeWindowAddon;
  providerVault: ProviderVault;
  getWindow: () => BrowserWindow | null;
  getNativeDesktopSnapshot: () => NativeDesktopSnapshot;
  openSystemPermissionSettings: (permission: string) => Promise<boolean>;
  getAttachmentStoreDir: () => string;
}

function emitToRenderer(getWindow: () => BrowserWindow | null, channel: DesktopSubscriptionChannel, payload: unknown): void {
  const browserWindow = getWindow();
  if (!browserWindow || browserWindow.isDestroyed()) {
    return;
  }
  browserWindow.webContents.send(channel, payload);
}

function sanitizeAttachmentStem(value: string): string {
  const base = path.parse(String(value || '').trim().replace(/\0/g, '')).name || 'clipboard';
  return base
    .replace(/[^a-zA-Z0-9._-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80) || 'clipboard';
}

function extensionForMimeType(mimeType: string): string {
  const normalized = String(mimeType || '').trim().toLowerCase();
  switch (normalized) {
    case 'image/png':
      return '.png';
    case 'image/jpeg':
    case 'image/jpg':
      return '.jpg';
    case 'image/gif':
      return '.gif';
    case 'image/webp':
      return '.webp';
    case 'image/heic':
      return '.heic';
    case 'image/heif':
      return '.heif';
    case 'application/pdf':
      return '.pdf';
    case 'text/plain':
      return '.txt';
    case 'text/markdown':
      return '.md';
    case 'application/json':
      return '.json';
    case 'application/rtf':
      return '.rtf';
    default:
      return '';
  }
}

function kindForMimeType(mimeType: string): string {
  const normalized = String(mimeType || '').trim().toLowerCase();
  if (normalized.startsWith('image/')) {
    return 'image';
  }
  if (normalized.startsWith('audio/')) {
    return 'audio';
  }
  if (normalized.includes('pdf') || normalized.startsWith('text/')) {
    return 'document';
  }
  return 'other';
}

export function registerDesktopIpc(options: RegisterDesktopIpcOptions): void {
  const {
    supervisor,
    windowManager,
    nativeAddon,
    providerVault,
    getWindow,
    getNativeDesktopSnapshot,
    openSystemPermissionSettings,
    getAttachmentStoreDir,
  } = options;

  // ─── Dictation manager setup ──────────────────────────────────────────────
  const dictationManager = new DictationManager({
    emit: (channel, payload) => {
      emitToRenderer(getWindow, channel as DesktopSubscriptionChannel, payload);
    },
  });

  // Cleanup on app quit
  app.on('before-quit', () => {
    dictationManager.dispose().catch(() => { /* ignore */ });
  });

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
    if (response.capability === 'backend.truth_refresh' && response.ok && response.result && typeof response.result === 'object') {
      const result = response.result as Record<string, unknown>;
      emitToRenderer(getWindow, 'backend-truth', result);
      if (result.runtime) {
        emitToRenderer(getWindow, 'runtime-status', result.runtime);
      }
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
  ipcMain.handle(IPC_CHANNELS.attachmentsSaveFromBase64, async (_event, payload): Promise<AttachmentSaveResult> => {
    const name = sanitizeAttachmentStem(String(payload?.name ?? 'clipboard'));
    const mimeType = String(payload?.mimeType ?? '').trim() || 'application/octet-stream';
    const dataBase64 = String(payload?.dataBase64 ?? '').trim();
    if (!dataBase64) {
      throw new Error('attachment_data_missing');
    }
    const targetDir = getAttachmentStoreDir();
    fs.mkdirSync(targetDir, { recursive: true });
    const id = crypto.randomUUID();
    const extension = extensionForMimeType(mimeType);
    const fileName = `${id}-${name}${extension}`;
    const filePath = path.join(targetDir, fileName);
    const buffer = Buffer.from(dataBase64, 'base64');
    fs.writeFileSync(filePath, buffer);
    return {
      id,
      name: extension ? `${name}${extension}` : name,
      path: filePath,
      url: pathToFileURL(filePath).href,
      mimeType,
      kind: kindForMimeType(mimeType),
      sizeBytes: buffer.byteLength,
    };
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
  ipcMain.handle(IPC_CHANNELS.systemOpenPermissionSettings, async (_event, payload): Promise<boolean> => {
    return openSystemPermissionSettings(String(payload?.permission ?? 'privacy'));
  });
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

  // ─── Locale ───────────────────────────────────────────────────────────────
  ipcMain.handle(IPC_CHANNELS.systemGetLocale, async (): Promise<string> => {
    return app.getLocale();
  });

  // ─── Dictation ────────────────────────────────────────────────────────────
  ipcMain.handle(IPC_CHANNELS.dictationStart, async (_event, payload) => {
    await dictationManager.start(payload ?? {});
  });

  ipcMain.handle(IPC_CHANNELS.dictationStop, async (_event, payload) => {
    let tempFile: string | undefined;
    if (typeof payload?.audioData === 'string' && payload.audioData.length > 0) {
      try {
        tempFile = createTempAudioPath();
        const buffer = Buffer.from(payload.audioData, 'base64');
        if (tempFile) {
          await fs.promises.writeFile(tempFile, buffer);
        }
      } catch (err) {
        console.error('[Dictation] Failed to write temp audio file:', err);
      }
    }
    await dictationManager.stop(tempFile);
  });

  ipcMain.handle(IPC_CHANNELS.dictationCancel, async () => {
    await dictationManager.cancel();
  });

  ipcMain.handle(IPC_CHANNELS.dictationGetStatus, async () => {
    return dictationManager.getStatus();
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
