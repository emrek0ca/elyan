import type { BootstrapSnapshot, RuntimeRequest, RuntimeResponse, SystemCapabilities, WindowState } from './protocol';
import type { DesktopSubscriptionChannel } from './channels';

export type Unsubscribe = () => void;

export interface ProviderSecretInput {
  providerId: string;
  secret: string;
}

export interface ProviderVaultStatus {
  available: boolean;
  persistent: boolean;
  backend: string;
  reason: string | null;
  providerIds: string[];
}

export interface ElyanDesktopApi {
  bootstrap(): Promise<BootstrapSnapshot>;
  request(request: RuntimeRequest): Promise<RuntimeResponse>;
  subscribe(channel: DesktopSubscriptionChannel, listener: (payload: unknown) => void): Unsubscribe;
  window: {
    minimize(): Promise<void>;
    maximizeOrRestore(): Promise<WindowState>;
    close(): Promise<void>;
    acknowledgeCloseAnimation(): Promise<void>;
    getState(): Promise<WindowState>;
  };
  system: {
    getCapabilities(): Promise<SystemCapabilities>;
  };
  providers: {
    saveSecret(input: ProviderSecretInput): Promise<ProviderVaultStatus>;
    removeSecret(providerId: string): Promise<ProviderVaultStatus>;
    getVaultStatus(): Promise<ProviderVaultStatus>;
  };
}
