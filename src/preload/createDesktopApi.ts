import { IPC_CHANNELS, isDesktopSubscriptionChannel, type DesktopSubscriptionChannel } from '../shared/channels';
import type {
  AttachmentSaveInput,
  AttachmentSaveResult,
  DictationStartOptions,
  DictationStatus,
  ElyanDesktopApi,
  ProviderVaultStatus,
  Unsubscribe,
} from '../shared/desktop-api';
import type { BootstrapSnapshot, RuntimeRequest, RuntimeResponse, SystemCapabilities, WindowState } from '../shared/protocol';

interface DesktopTransport {
  invoke<T>(channel: string, payload?: unknown): Promise<T>;
  on(channel: DesktopSubscriptionChannel, listener: (payload: unknown) => void): Unsubscribe;
}

export function createDesktopApi(transport: DesktopTransport): ElyanDesktopApi {
  return {
    bootstrap(): Promise<BootstrapSnapshot> {
      return transport.invoke<BootstrapSnapshot>(IPC_CHANNELS.bootstrap);
    },
    request(request: RuntimeRequest): Promise<RuntimeResponse> {
      return transport.invoke<RuntimeResponse>(IPC_CHANNELS.request, request);
    },
    subscribe(channel: DesktopSubscriptionChannel, listener: (payload: unknown) => void): Unsubscribe {
      if (!isDesktopSubscriptionChannel(channel)) {
        throw new Error(`Unsupported subscription channel: ${channel}`);
      }
      return transport.on(channel, listener);
    },
    window: {
      minimize(): Promise<void> {
        return transport.invoke<void>(IPC_CHANNELS.windowMinimize);
      },
      maximizeOrRestore(): Promise<WindowState> {
        return transport.invoke<WindowState>(IPC_CHANNELS.windowMaximizeOrRestore);
      },
      close(): Promise<void> {
        return transport.invoke<void>(IPC_CHANNELS.windowClose);
      },
      acknowledgeCloseAnimation(): Promise<void> {
        return transport.invoke<void>(IPC_CHANNELS.windowAckCloseAnimation);
      },
      getState(): Promise<WindowState> {
        return transport.invoke<WindowState>(IPC_CHANNELS.windowGetState);
      },
    },
    attachments: {
      saveFromBase64(input: AttachmentSaveInput): Promise<AttachmentSaveResult> {
        return transport.invoke<AttachmentSaveResult>(IPC_CHANNELS.attachmentsSaveFromBase64, input);
      },
    },
    system: {
      getCapabilities(): Promise<SystemCapabilities> {
        return transport.invoke<SystemCapabilities>(IPC_CHANNELS.systemGetCapabilities);
      },
      getLocale(): Promise<string> {
        return transport.invoke<string>(IPC_CHANNELS.systemGetLocale);
      },
      openPermissionSettings(permission: string): Promise<boolean> {
        return transport.invoke<boolean>(IPC_CHANNELS.systemOpenPermissionSettings, { permission });
      },
    },
    providers: {
      saveSecret(input) {
        return transport.invoke<ProviderVaultStatus>(IPC_CHANNELS.providersSaveSecret, input);
      },
      removeSecret(providerId) {
        return transport.invoke<ProviderVaultStatus>(IPC_CHANNELS.providersRemoveSecret, { providerId });
      },
      getVaultStatus() {
        return transport.invoke<ProviderVaultStatus>(IPC_CHANNELS.providersGetVaultStatus);
      },
    },
    dictation: {
      start(options?: DictationStartOptions): Promise<void> {
        return transport.invoke<void>(IPC_CHANNELS.dictationStart, options ?? {});
      },
      stop(opts?: { audioData?: string }): Promise<void> {
        return transport.invoke<void>(IPC_CHANNELS.dictationStop, opts ?? {});
      },
      cancel(): Promise<void> {
        return transport.invoke<void>(IPC_CHANNELS.dictationCancel);
      },
      getStatus(): Promise<DictationStatus> {
        return transport.invoke<DictationStatus>(IPC_CHANNELS.dictationGetStatus);
      },
    },
  };
}

