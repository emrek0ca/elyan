import type { DesktopSubscriptionChannel } from '../shared/channels';
import type {
  AttachmentSaveInput,
  AttachmentSaveResult,
  ElyanDesktopApi,
  ProviderVaultStatus,
  Unsubscribe,
} from '../shared/desktop-api';
import {
  createPreviewBootstrapSnapshot,
  createRuntimeUnavailableResponse,
  ensureRuntimeRequest,
  type BootstrapSnapshot,
  type RuntimeRequest,
  type RuntimeResponse,
  type SystemCapabilities,
  type WindowState,
} from '../shared/protocol';

function responseFor(request: RuntimeRequest, result: unknown, ok = true): RuntimeResponse {
  const normalized = ensureRuntimeRequest(request);
  return {
    id: normalized.id ?? '',
    taskId: normalized.taskId ?? '',
    ok,
    capability: normalized.capability,
    result: result as RuntimeResponse['result'],
    events: [],
    artifacts: [],
    error: ok ? null : { code: 'RUNTIME_UNAVAILABLE', message: 'Yerel Elyan runtime hazır değil.' },
    durationMs: 0,
    requestId: normalized.id,
  };
}

async function postPreviewBridge<T>(endpoint: 'bootstrap' | 'request', payload: unknown): Promise<T> {
  const response = await fetch(`/__elyan_preview/${endpoint}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`preview_bridge_${response.status}`);
  }
  return (await response.json()) as T;
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function createPreviewApi(): ElyanDesktopApi {
  let snapshot: BootstrapSnapshot = createPreviewBootstrapSnapshot();
  const listeners = new Map<DesktopSubscriptionChannel, Set<(payload: unknown) => void>>();
  const windowState: WindowState = {
    isFocused: true,
    isVisible: true,
    isMaximized: false,
    isMinimized: false,
    isFullScreen: false,
    isClosing: false,
    platform: 'darwin',
  };

  const emit = (channel: DesktopSubscriptionChannel, payload: unknown) => {
    for (const listener of listeners.get(channel) ?? []) {
      listener(payload);
    }
  };

  return {
    async bootstrap() {
      try {
        snapshot = await postPreviewBridge<BootstrapSnapshot>('bootstrap', {});
      } catch {
        snapshot = createPreviewBootstrapSnapshot();
      }
      return snapshot;
    },
    async request(request) {
      const normalized = ensureRuntimeRequest(request);
      try {
        let response = await postPreviewBridge<RuntimeResponse>('request', normalized);
        if (response.error?.code === 'RUNTIME_NOT_READY' || response.error?.code === 'RUNTIME_UNAVAILABLE') {
          await wait(900);
          response = await postPreviewBridge<RuntimeResponse>('request', normalized);
        }
        if (normalized.capability === 'backend.truth_refresh' && (!response.ok || !response.result || typeof response.result !== 'object')) {
          return responseFor(normalized, {
            ok: true,
            truthOk: true,
            authMe: snapshot.backend?.authMe ?? {},
            mobileBootstrap: snapshot.backend?.mobileBootstrap ?? {},
            health: snapshot.backend?.health ?? {},
            brainProfile: snapshot.backend?.brainProfile ?? {},
            runtimeSession: snapshot.backend?.runtimeSession ?? {},
            controlPlane: snapshot.backend?.controlPlane ?? {},
            runtime: snapshot.runtime,
            state: snapshot.state,
            syncedAt: new Date().toISOString(),
          });
        }
        if (response.capability === 'bootstrap' && response.ok && response.result && typeof response.result === 'object') {
          snapshot = response.result as unknown as BootstrapSnapshot;
        }
        return response;
      } catch {
        if (normalized.capability === 'bootstrap') {
          return responseFor(normalized, snapshot);
        }
        if (normalized.capability === 'runtime.status') {
          return responseFor(normalized, snapshot.runtime);
        }
        if (normalized.capability === 'backend.truth_refresh') {
          return responseFor(normalized, {
            ok: true,
            truthOk: true,
            authMe: snapshot.backend?.authMe ?? {},
            mobileBootstrap: snapshot.backend?.mobileBootstrap ?? {},
            health: snapshot.backend?.health ?? {},
            brainProfile: snapshot.backend?.brainProfile ?? {},
            runtimeSession: snapshot.backend?.runtimeSession ?? {},
            controlPlane: snapshot.backend?.controlPlane ?? {},
            runtime: snapshot.runtime,
            state: snapshot.state,
            syncedAt: new Date().toISOString(),
          });
        }
        return createRuntimeUnavailableResponse(normalized, 'Preview runtime bridge hazir degil.', 'PREVIEW_BRIDGE_UNAVAILABLE');
      }
    },
    subscribe(channel, listener) {
      const bucket = listeners.get(channel) ?? new Set<(payload: unknown) => void>();
      bucket.add(listener);
      listeners.set(channel, bucket);
      return (() => {
        bucket.delete(listener);
      }) satisfies Unsubscribe;
    },
    window: {
      async minimize() {},
      async maximizeOrRestore() {
        windowState.isMaximized = !windowState.isMaximized;
        return { ...windowState };
      },
      async close() {
        emit('close-handshake', { phase: 'requested', state: { ...windowState, isClosing: true } });
      },
      async acknowledgeCloseAnimation() {},
      async getState() {
        return { ...windowState };
      },
    },
    attachments: {
      async saveFromBase64(_input: AttachmentSaveInput): Promise<AttachmentSaveResult> {
        throw new Error('preview_attachment_materialization_unavailable');
      },
    },
    system: {
      async getCapabilities(): Promise<SystemCapabilities> {
        return {
          platform: windowState.platform,
          windowChrome: {
            customTitlebar: true,
            closeAnimation: true,
            trafficLights: true,
            vibrancy: true,
            mica: false,
            clientSideDecorations: true,
            tray: false,
            attention: true,
          },
          nativeControl: {
            automation: false,
            screenCapture: false,
            globalShortcuts: false,
            fileSystemAccess: false,
            processInspection: false,
            permissionRequired: true,
            rendererDirectControl: false,
            sideEffectsRequireTaskId: true,
            osPermissionModel: 'preview_safe_mode',
            accessibilityPermissionRequired: false,
            screenRecordingPermissionRequired: false,
            inputMonitoringPermissionRequired: false,
            automationPermissionRequired: false,
          },
          runtime: {
            packagedBinaryAvailable: false,
            pythonFallbackAvailable: true,
            rustIndexerManagedByPython: true,
          },
          nativeAddon: {
            available: false,
            failureReason: 'runtime_unavailable',
            version: null,
          },
          nativeDesktop: {
            available: false,
            source: 'fallback',
            collectedAt: new Date().toISOString(),
            platform: windowState.platform,
            osPermissionModel: 'preview_safe_mode',
            processInspectionAvailable: false,
            activeWindowAvailable: false,
            permissionProbeAvailable: false,
            globalShortcutsAvailable: false,
            screenCaptureAvailable: false,
            permissions: {
              accessibility: { required: false, granted: true, status: 'not_required' },
              screenRecording: { required: false, granted: true, status: 'not_required' },
              inputMonitoring: { required: false, granted: true, status: 'not_required' },
              automation: { required: false, granted: true, status: 'not_required' },
            },
            processes: {
              available: false,
              total: 0,
              items: [],
            },
            activeWindow: {
              available: false,
              appName: '',
              windowTitle: '',
              processId: null,
            },
            operator: {
              available: false,
              mode: 'scaffold_only',
              screenObservationReady: false,
              accessibilityReady: false,
              inputControlReady: false,
              emergencyStopAvailable: false,
              failSafeCornerAbort: true,
              playwrightReady: false,
              browserFirstReady: false,
              operatorResolutionMode: '',
              lastTargetSource: '',
              lastVerificationSource: '',
              lastTargetConfidence: 0,
              activeRunSummary: {},
              lastErrorCode: 'preview_runtime',
            },
            lastErrorCode: 'preview_runtime',
          },
        };
      },
      async getLocale(): Promise<string> {
        return 'tr-TR';
      },
      async openPermissionSettings(): Promise<boolean> {
        return false;
      },
    },
    providers: {
      async saveSecret() {
        return {
          available: true,
          persistent: false,
          backend: 'preview',
          reason: 'preview_session_only',
          providerIds: [],
        } satisfies ProviderVaultStatus;
      },
      async removeSecret() {
        return {
          available: true,
          persistent: false,
          backend: 'preview',
          reason: 'preview_session_only',
          providerIds: [],
        } satisfies ProviderVaultStatus;
      },
      async getVaultStatus() {
        return {
          available: true,
          persistent: false,
          backend: 'preview',
          reason: 'preview_session_only',
          providerIds: [],
        } satisfies ProviderVaultStatus;
      },
    },
    dictation: {
      async start() {},
      async stop() {},
      async cancel() {},
      async getStatus() {
        return {
          state: 'idle',
          provider: null,
          modelAvailable: false,
          binaryAvailable: false,
          error: null,
          partialTranscript: null,
        };
      },
    },
  };
}

function currentDesktopApi(): ElyanDesktopApi {
  return window.elyanDesktop ?? createPreviewApi();
}

export function getDesktopApi(): ElyanDesktopApi {
  return {
    bootstrap() {
      return currentDesktopApi().bootstrap();
    },
    request(request) {
      return currentDesktopApi().request(request);
    },
    subscribe(channel, listener) {
      return currentDesktopApi().subscribe(channel, listener);
    },
    window: {
      minimize() {
        return currentDesktopApi().window.minimize();
      },
      maximizeOrRestore() {
        return currentDesktopApi().window.maximizeOrRestore();
      },
      close() {
        return currentDesktopApi().window.close();
      },
      acknowledgeCloseAnimation() {
        return currentDesktopApi().window.acknowledgeCloseAnimation();
      },
      getState() {
        return currentDesktopApi().window.getState();
      },
    },
    attachments: {
      saveFromBase64(input: AttachmentSaveInput) {
        return currentDesktopApi().attachments.saveFromBase64(input);
      },
    },
    system: {
      getCapabilities() {
        return currentDesktopApi().system.getCapabilities();
      },
      getLocale() {
        return currentDesktopApi().system.getLocale();
      },
      openPermissionSettings(permission: string) {
        return currentDesktopApi().system.openPermissionSettings(permission);
      },
    },
    providers: {
      saveSecret(input) {
        return currentDesktopApi().providers.saveSecret(input);
      },
      removeSecret(providerId) {
        return currentDesktopApi().providers.removeSecret(providerId);
      },
      getVaultStatus() {
        return currentDesktopApi().providers.getVaultStatus();
      },
    },
    dictation: {
      start(options) {
        return currentDesktopApi().dictation.start(options);
      },
      stop(opts) {
        return currentDesktopApi().dictation.stop(opts);
      },
      cancel() {
        return currentDesktopApi().dictation.cancel();
      },
      getStatus() {
        return currentDesktopApi().dictation.getStatus();
      },
    },
  };
}
