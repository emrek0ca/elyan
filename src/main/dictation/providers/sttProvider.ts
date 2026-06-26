/**
 * Abstract STT provider interface.
 * All providers must implement this interface.
 */

import type {
  DictationLanguageMode,
  DictationModelQuality,
  DictationStartOptions,
  DictationStatus,
} from '../types';

export type PartialTranscriptCallback = (transcript: string) => void;
export type FinalTranscriptCallback = (transcript: string, durationMs: number) => void;
export type ErrorCallback = (code: string, message: string) => void;
export type StatusCallback = (status: DictationStatus) => void;

export interface SttProviderCallbacks {
  onPartial: PartialTranscriptCallback;
  onFinal: FinalTranscriptCallback;
  onError: ErrorCallback;
  onStatus: StatusCallback;
}

export interface SttProvider {
  /** Human-readable name */
  readonly name: string;

  /** Check if this provider can be used on this platform/architecture */
  isAvailable(): Promise<boolean>;

  /** Initialize (lazy — called before first start) */
  initialize(): Promise<void>;

  /** Begin recording and transcription */
  start(options: DictationStartOptions, callbacks: SttProviderCallbacks): Promise<void>;

  /** Stop recording and finalize transcript */
  stop(): Promise<void>;

  /** Cancel recording — no final transcript emitted */
  cancel(): Promise<void>;

  /** Get current provider status snapshot */
  getStatus(): DictationStatus;

  /** Cleanup on app quit */
  dispose(): Promise<void>;
}
