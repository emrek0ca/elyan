import { IPC_CHANNELS, isDesktopSubscriptionChannel, type DesktopSubscriptionChannel } from '../shared/channels';
import type { ElyanDesktopApi, ProviderVaultStatus, Unsubscribe } from '../shared/desktop-api';
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
    system: {
      getCapabilities(): Promise<SystemCapabilities> {
        return transport.invoke<SystemCapabilities>(IPC_CHANNELS.systemGetCapabilities);
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
  };
}
