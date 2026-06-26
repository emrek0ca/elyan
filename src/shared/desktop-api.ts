import type { BootstrapSnapshot, RuntimeRequest, RuntimeResponse, SystemCapabilities, WindowState } from './protocol';
import type { DesktopSubscriptionChannel } from './channels';

export type Unsubscribe = () => void;

export interface ProviderSecretInput {
  providerId: string;
  secret: string;
}

export interface AttachmentSaveInput {
  name: string;
  mimeType: string;
  dataBase64: string;
}

export interface AttachmentSaveResult {
  id: string;
  name: string;
  path: string;
  url?: string;
  mimeType: string;
  kind: string;
  sizeBytes: number;
}

export interface ProviderVaultStatus {
  available: boolean;
  persistent: boolean;
  backend: string;
  reason: string | null;
  providerIds: string[];
}

// ─── Dictation ───────────────────────────────────────────────────────────────

export type DictationProviderMode = 'auto' | 'whisperkit' | 'whispercpp' | 'disabled';
export type DictationLanguageMode = 'auto' | 'tr' | 'en';
export type DictationModelQuality = 'fast' | 'balanced' | 'accurate';

export type DictationStateKind =
  | 'idle'
  | 'requesting_permission'
  | 'downloading_model'
  | 'listening'
  | 'transcribing'
  | 'partial_result'
  | 'final_result'
  | 'error';

export interface DictationStatus {
  state: DictationStateKind;
  provider: string | null;
  modelAvailable: boolean;
  binaryAvailable: boolean;
  error: string | null;
  partialTranscript: string | null;
}

export interface DictationStartOptions {
  language?: DictationLanguageMode;
  providerMode?: DictationProviderMode;
  quality?: DictationModelQuality;
}

export interface DictationApi {
  start(options?: DictationStartOptions): Promise<void>;
  stop(opts?: { audioData?: string }): Promise<void>;
  cancel(): Promise<void>;
  getStatus(): Promise<DictationStatus>;
}

// ─── Full Desktop API ─────────────────────────────────────────────────────────

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
  attachments: {
    saveFromBase64(input: AttachmentSaveInput): Promise<AttachmentSaveResult>;
  };
  system: {
    getCapabilities(): Promise<SystemCapabilities>;
    getLocale(): Promise<string>;
    openPermissionSettings(permission: string): Promise<boolean>;
  };
  providers: {
    saveSecret(input: ProviderSecretInput): Promise<ProviderVaultStatus>;
    removeSecret(providerId: string): Promise<ProviderVaultStatus>;
    getVaultStatus(): Promise<ProviderVaultStatus>;
  };
  dictation: DictationApi;
}

