/**
 * Shared types for the offline dictation system.
 * These types flow between: main process <-> preload <-> renderer
 */

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
  downloadProgress?: number;
}

export interface DictationStartOptions {
  language?: DictationLanguageMode;
  providerMode?: DictationProviderMode;
  quality?: DictationModelQuality;
}

export interface DictationPartialEvent {
  transcript: string;
  isFinal: false;
}

export interface DictationFinalEvent {
  transcript: string;
  isFinal: true;
  durationMs: number;
}

export interface DictationErrorEvent {
  code: string;
  message: string;
}

export interface DictationStatusEvent {
  status: DictationStatus;
}

/** Model file names for each quality level */
export const WHISPER_MODELS: Record<DictationModelQuality, string> = {
  fast: 'ggml-tiny.q5_1.bin',
  balanced: 'ggml-small.q5_1.bin',
  accurate: 'ggml-medium.q5_1.bin',
};

/** Whisper model download URLs (Hugging Face) */
export const WHISPER_MODEL_URLS: Record<DictationModelQuality, string> = {
  fast: 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.q5_1.bin',
  balanced: 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.q5_1.bin',
  accurate: 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.q5_1.bin',
};
