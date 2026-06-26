/**
 * DictationManager — orchestrates the STT provider lifecycle.
 *
 * Responsibilities:
 * - Provider selection (Auto, WhisperKit, whisper.cpp, Disabled)
 * - Audio file receipt from renderer via IPC
 * - Emitting events to renderer (partial, final, error, status)
 * - Cleanup on app quit
 *
 * Architecture:
 *   Renderer (MediaRecorder) → writes WAV to temp file → sends path via IPC
 *   DictationManager → picks provider → spawns transcription → emits events
 */

import os from 'node:os';
import fs from 'node:fs';
import type { BrowserWindow } from 'electron';
import type { DictationProviderMode, DictationStartOptions, DictationStatus, DictationStateKind } from './types';
import type { SttProvider, SttProviderCallbacks } from './providers/sttProvider';
import { WhisperCppProvider } from './providers/whisperCppProvider';
import { WhisperKitProvider } from './providers/whisperKitProvider';
import { cleanStaleAudioFiles, deleteTempAudio } from './audio/tempAudio';

type EmitFn = (channel: string, payload: unknown) => void;

interface DictationManagerOptions {
  emit: EmitFn;
}

export class DictationManager {
  private _provider: SttProvider | null = null;
  private _providerMode: DictationProviderMode = 'auto';
  private _activeOptions: DictationStartOptions = {};
  private _state: DictationStateKind = 'idle';
  private _emit: EmitFn;
  private _pendingTempFile: string | null = null;
  private _initialized = false;

  constructor(options: DictationManagerOptions) {
    this._emit = options.emit;
  }

  // ─── Provider Selection ──────────────────────────────────────────────────

  private async selectProvider(mode: DictationProviderMode): Promise<SttProvider | null> {
    if (mode === 'disabled') return null;

    const platform = os.platform();
    const arch = os.arch();

    if (mode === 'whisperkit' || (mode === 'auto' && platform === 'darwin')) {
      const whisperKit = new WhisperKitProvider();
      if (await whisperKit.isAvailable()) {
        return whisperKit;
      }
      if (mode === 'whisperkit') {
        return null; // Explicitly requested but not available
      }
      // Auto: fall through to whisper.cpp
    }

    if (mode === 'whispercpp' || mode === 'auto') {
      const whisperCpp = new WhisperCppProvider();
      if (await whisperCpp.isAvailable()) {
        return whisperCpp;
      }
      // whisper.cpp binary not installed — still return it for status reporting
      return whisperCpp;
    }

    return null;
  }

  // ─── Callbacks ───────────────────────────────────────────────────────────

  private buildCallbacks(): SttProviderCallbacks {
    return {
      onPartial: (transcript: string) => {
        this._emit('dictation-partial', { transcript, isFinal: false });
      },
      onFinal: (transcript: string, durationMs: number) => {
        this._emit('dictation-final', { transcript, isFinal: true, durationMs });
        this._state = 'idle';
        this._pendingTempFile = null;
      },
      onError: (code: string, message: string) => {
        this._emit('dictation-error', { code, message });
        this._state = 'error';
      },
      onStatus: (status: DictationStatus) => {
        this._emit('dictation-status', { status });
        this._state = status.state;
      },
    };
  }

  // ─── Public API ──────────────────────────────────────────────────────────

  async start(options: DictationStartOptions): Promise<void> {
    if (this._state !== 'idle' && this._state !== 'error') {
      // Already active — cancel first
      await this.cancel();
    }

    cleanStaleAudioFiles();

    this._activeOptions = options;
    const mode = options.providerMode ?? 'auto';
    this._providerMode = mode;

    this._provider = await this.selectProvider(mode);

    if (!this._provider) {
      this._state = 'error';
      const errorPayload = { code: 'PROVIDER_DISABLED', message: 'Dictation is disabled' };
      this._emit('dictation-error', errorPayload);
      return;
    }

    if (!this._initialized) {
      try {
        await this._provider.initialize();
        this._initialized = true;
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        this._state = 'error';
        this._emit('dictation-error', { code: 'INIT_FAILED', message });
        return;
      }
    }

    try {
      await this._provider.start(options, this.buildCallbacks());
      this._state = 'listening';
      this._emit('dictation-status', { status: this.getStatus() });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      this._state = 'error';
      this._emit('dictation-error', { code: 'START_FAILED', message });
    }
  }

  /**
   * Stop recording. The renderer has finished recording and provides
   * the temp WAV file path for transcription.
   */
  async stop(tempAudioPath?: string): Promise<void> {
    if (!this._provider) return;
    if (this._state !== 'listening' && this._state !== 'partial_result') return;

    const filePath = tempAudioPath ?? this._pendingTempFile;

    if (filePath && fs.existsSync(filePath)) {
      this._pendingTempFile = filePath;
      this._state = 'transcribing';
      this._emit('dictation-status', { status: this.getStatus() });

      const providerWithFile = this._provider as SttProvider & {
        transcribeFile?: (
          filePath: string,
          options: DictationStartOptions,
          callbacks: SttProviderCallbacks,
        ) => Promise<void>;
      };

      if (typeof providerWithFile.transcribeFile === 'function') {
        await providerWithFile.transcribeFile(filePath, this._activeOptions, this.buildCallbacks());
      } else {
        await this._provider.stop();
      }
    } else {
      // No audio file — just idle
      await this._provider.stop();
      this._state = 'idle';
      this._emit('dictation-status', { status: this.getStatus() });
    }
  }

  async cancel(): Promise<void> {
    if (this._provider) {
      await this._provider.cancel();
    }
    if (this._pendingTempFile) {
      deleteTempAudio(this._pendingTempFile);
      this._pendingTempFile = null;
    }
    this._state = 'idle';
    this._initialized = false;
    this._emit('dictation-status', { status: this.getStatus() });
  }

  getStatus(): DictationStatus {
    if (this._provider) {
      return this._provider.getStatus();
    }
    return {
      state: this._state,
      provider: null,
      modelAvailable: false,
      binaryAvailable: false,
      error: null,
      partialTranscript: null,
    };
  }

  async dispose(): Promise<void> {
    await this.cancel();
    if (this._provider) {
      await this._provider.dispose();
      this._provider = null;
    }
  }

  /** Called when renderer sends a WAV file path after recording */
  setPendingAudioFile(path: string): void {
    this._pendingTempFile = path;
  }
}
