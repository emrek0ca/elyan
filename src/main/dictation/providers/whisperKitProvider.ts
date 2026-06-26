/**
 * WhisperKit STT provider — macOS only.
 *
 * WhisperKit provides on-device, Apple Neural Engine-accelerated
 * speech recognition on macOS 14+/Apple Silicon.
 *
 * This provider is a platform-guarded stub:
 * - On non-macOS or macOS without WhisperKit, isAvailable() returns false
 * - In Auto mode, the DictationManager falls back to whisper.cpp
 *
 * Full WhisperKit integration requires the WhisperKit Swift CLI tool
 * to be available at {userData}/bin/whisperkit/whisperkit-cli
 *
 * The CLI approach avoids native Swift module binding complexity
 * while staying within the Electron security boundary.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn, type ChildProcess } from 'node:child_process';
import { app } from 'electron';
import type { SttProvider, SttProviderCallbacks } from './sttProvider';
import type { DictationStartOptions, DictationStatus, DictationStateKind } from '../types';
import { deleteTempAudio } from '../audio/tempAudio';

const TRANSCRIPTION_TIMEOUT_MS = 90_000;

function getWhisperKitBinaryPath(): string {
  return path.join(app.getPath('userData'), 'bin', 'whisperkit', 'whisperkit-cli');
}

function getWhisperKitModelDir(): string {
  return path.join(app.getPath('userData'), 'models', 'whisperkit');
}

function isMacOS(): boolean {
  return os.platform() === 'darwin';
}

function isAppleSilicon(): boolean {
  return os.platform() === 'darwin' && os.arch() === 'arm64';
}

export class WhisperKitProvider implements SttProvider {
  readonly name = 'WhisperKit';

  private _state: DictationStateKind = 'idle';
  private _error: string | null = null;
  private _partialTranscript: string | null = null;
  private _process: ChildProcess | null = null;
  private _timeoutHandle: ReturnType<typeof setTimeout> | null = null;
  private _currentTempFile: string | null = null;

  async isAvailable(): Promise<boolean> {
    if (!isMacOS()) return false;
    const binaryPath = getWhisperKitBinaryPath();
    return fs.existsSync(binaryPath);
  }

  async initialize(): Promise<void> {
    // No-op — lazy initialization per transcription
  }

  getStatus(): DictationStatus {
    const modelDir = getWhisperKitModelDir();
    const modelAvailable = fs.existsSync(modelDir) &&
      fs.readdirSync(modelDir).length > 0;

    return {
      state: this._state,
      provider: this.name,
      modelAvailable,
      binaryAvailable: fs.existsSync(getWhisperKitBinaryPath()),
      error: this._error,
      partialTranscript: this._partialTranscript,
    };
  }

  async start(options: DictationStartOptions, callbacks: SttProviderCallbacks): Promise<void> {
    this._state = 'listening';
    this._error = null;
    this._partialTranscript = null;
    callbacks.onStatus(this.getStatus());
  }

  async transcribeFile(filePath: string, options: DictationStartOptions, callbacks: SttProviderCallbacks): Promise<void> {
    this._state = 'transcribing';
    this._currentTempFile = filePath;
    callbacks.onStatus(this.getStatus());

    const binaryPath = getWhisperKitBinaryPath();
    if (!fs.existsSync(binaryPath)) {
      this._state = 'error';
      this._error = 'binary_missing';
      callbacks.onError('BINARY_MISSING', 'WhisperKit CLI not found');
      callbacks.onStatus(this.getStatus());
      return;
    }

    const modelDir = getWhisperKitModelDir();
    const langArgs: string[] = [];
    if (options.language && options.language !== 'auto') {
      langArgs.push('--language', options.language);
    }

    const args = [
      'transcribe',
      '--audio-path', filePath,
      '--model-path', modelDir,
      '--verbose', 'false',
      ...langArgs,
    ];

    return new Promise<void>((resolve) => {
      this._process = spawn(binaryPath, args, {
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      let stdout = '';
      let stderr = '';
      const startTime = Date.now();

      // WhisperKit CLI may emit partial results on stderr as JSON lines
      this._process.stderr?.on('data', (chunk: Buffer) => {
        const lines = chunk.toString().split('\n');
        for (const line of lines) {
          if (line.includes('"partial"')) {
            try {
              const parsed = JSON.parse(line) as { partial?: string };
              if (parsed.partial) {
                this._partialTranscript = parsed.partial;
                callbacks.onPartial(parsed.partial);
              }
            } catch {
              // Not JSON — treat as informational stderr
            }
          }
          stderr += line + '\n';
        }
      });

      this._process.stdout?.on('data', (chunk: Buffer) => {
        stdout += chunk.toString();
      });

      this._timeoutHandle = setTimeout(() => {
        this._process?.kill('SIGTERM');
        this._state = 'error';
        this._error = 'timeout';
        callbacks.onError('TIMEOUT', 'WhisperKit transcription timed out');
        callbacks.onStatus(this.getStatus());
        deleteTempAudio(filePath);
        resolve();
      }, TRANSCRIPTION_TIMEOUT_MS);

      this._process.on('close', (code) => {
        if (this._timeoutHandle) {
          clearTimeout(this._timeoutHandle);
          this._timeoutHandle = null;
        }
        deleteTempAudio(filePath);
        this._currentTempFile = null;
        this._process = null;

        if (code === 0 || code === null) {
          const transcript = stdout.trim();
          this._state = 'final_result';
          callbacks.onFinal(transcript, Date.now() - startTime);
          callbacks.onStatus(this.getStatus());
          this._state = 'idle';
        } else {
          const errMsg = stderr.trim() || `WhisperKit exited with code ${code}`;
          this._state = 'error';
          this._error = 'transcription_failed';
          callbacks.onError('TRANSCRIPTION_FAILED', errMsg);
          callbacks.onStatus(this.getStatus());
        }
        resolve();
      });

      this._process.on('error', (err: Error) => {
        if (this._timeoutHandle) {
          clearTimeout(this._timeoutHandle);
          this._timeoutHandle = null;
        }
        deleteTempAudio(filePath);
        this._currentTempFile = null;
        this._process = null;
        this._state = 'error';
        this._error = err.message;
        callbacks.onError('PROCESS_ERROR', err.message);
        callbacks.onStatus(this.getStatus());
        resolve();
      });
    });
  }

  async stop(): Promise<void> {
    // Handled externally by DictationManager after audio is ready
  }

  async cancel(): Promise<void> {
    if (this._process) {
      this._process.kill('SIGTERM');
      this._process = null;
    }
    if (this._timeoutHandle) {
      clearTimeout(this._timeoutHandle);
      this._timeoutHandle = null;
    }
    if (this._currentTempFile) {
      deleteTempAudio(this._currentTempFile);
      this._currentTempFile = null;
    }
    this._state = 'idle';
    this._error = null;
    this._partialTranscript = null;
  }

  async dispose(): Promise<void> {
    await this.cancel();
  }
}
