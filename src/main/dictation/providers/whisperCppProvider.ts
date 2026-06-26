/**
 * whisper.cpp STT provider.
 *
 * Runs the whisper.cpp binary as a child process to transcribe
 * recorded WAV audio. Supports macOS arm64/x64, Windows x64, Linux x64.
 *
 * Binary resolution:
 *   {app.getPath('userData')}/bin/whisper/{platform}-{arch}/whisper-cli
 *
 * Model resolution:
 *   {app.getPath('userData')}/models/whisper/ggml-{quality}.q5_1.bin
 *
 * Audio is captured in the renderer (Chromium MediaRecorder → WAV)
 * and passed as a temp file path via IPC. The temp file is deleted
 * after transcription.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn, type ChildProcess } from 'node:child_process';
import { app } from 'electron';
import type { SttProvider, SttProviderCallbacks } from './sttProvider';
import type { DictationStartOptions, DictationStatus, DictationStateKind } from '../types';
import { resolveModel } from '../models/modelResolver';
import { downloadModel } from '../models/modelDownloader';
import { deleteTempAudio } from '../audio/tempAudio';

const TRANSCRIPTION_TIMEOUT_MS = 60_000;

function getBinaryDir(): string {
  const platform = os.platform();
  const arch = os.arch();
  const platformKey = platform === 'win32' ? 'win32' : platform === 'darwin' ? 'darwin' : 'linux';
  const archKey = arch === 'arm64' ? 'arm64' : 'x64';
  return path.join(app.getPath('userData'), 'bin', 'whisper', `${platformKey}-${archKey}`);
}

function getBinaryName(): string {
  return os.platform() === 'win32' ? 'whisper-cli.exe' : 'whisper-cli';
}

function getBinaryPath(): string {
  return path.join(getBinaryDir(), getBinaryName());
}

export class WhisperCppProvider implements SttProvider {
  readonly name = 'whisper.cpp';

  private _state: DictationStateKind = 'idle';
  private _error: string | null = null;
  private _partialTranscript: string | null = null;
  private _process: ChildProcess | null = null;
  private _timeoutHandle: ReturnType<typeof setTimeout> | null = null;
  private _currentTempFile: string | null = null;

  async isAvailable(): Promise<boolean> {
    const binaryPath = getBinaryPath();
    return fs.existsSync(binaryPath);
  }

  async initialize(): Promise<void> {
    // No-op: whisper.cpp is initialized lazily per transcription
  }

  getStatus(): DictationStatus {
    const quality = (typeof localStorage !== 'undefined' ? localStorage?.getItem?.('elyan-dictation-quality') : 'balanced') as 'fast' | 'balanced' | 'accurate';
    const modelResult = resolveModel(quality);
    return {
      state: this._state,
      provider: this.name,
      modelAvailable: modelResult.available,
      binaryAvailable: fs.existsSync(getBinaryPath()),
      error: this._error,
      partialTranscript: this._partialTranscript,
    };
  }

  async start(options: DictationStartOptions, callbacks: SttProviderCallbacks): Promise<void> {
    const quality = options.quality ?? 'balanced';
    const modelResult = resolveModel(quality);

    if (!modelResult.available || !modelResult.path) {
      this._state = 'downloading_model';
      callbacks.onStatus(this.getStatus());
      try {
        await downloadModel(modelResult.downloadUrl, modelResult.expectedPath, (progress) => {
          callbacks.onStatus({
            ...this.getStatus(),
            downloadProgress: progress.percent,
          });
        });
      } catch (err: unknown) {
        this._state = 'error';
        this._error = 'model_missing';
        const message = err instanceof Error ? err.message : String(err);
        callbacks.onError('MODEL_MISSING', `Failed to download speech model: ${message}`);
        callbacks.onStatus(this.getStatus());
        return;
      }
    }

    // whisper.cpp does not support real-time streaming:
    // the renderer will record audio and call stop() when done.
    // At stop(), we receive the temp file path and transcribe it.
    this._state = 'listening';
    this._error = null;
    this._partialTranscript = null;
    callbacks.onStatus(this.getStatus());
  }

  async transcribeFile(filePath: string, options: DictationStartOptions, callbacks: SttProviderCallbacks): Promise<void> {
    this._state = 'transcribing';
    this._currentTempFile = filePath;
    callbacks.onStatus(this.getStatus());

    const quality = options.quality ?? 'balanced';
    const modelResult = resolveModel(quality);

    if (!modelResult.available || !modelResult.path) {
      this._state = 'error';
      this._error = 'model_missing';
      callbacks.onError('MODEL_MISSING', `Speech model not found at: ${modelResult.expectedPath}`);
      callbacks.onStatus(this.getStatus());
      return;
    }

    const binaryPath = getBinaryPath();
    if (!fs.existsSync(binaryPath)) {
      this._state = 'error';
      this._error = 'binary_missing';
      callbacks.onError('BINARY_MISSING', `whisper.cpp binary not found at: ${binaryPath}`);
      callbacks.onStatus(this.getStatus());
      return;
    }

    const langArgs: string[] = [];
    if (options.language && options.language !== 'auto') {
      langArgs.push('-l', options.language);
    }

    const args = [
      '-m', modelResult.path,
      '-f', filePath,
      '--output-txt',
      '--no-timestamps',
      ...langArgs,
    ];

    return new Promise<void>((resolve) => {
      this._process = spawn(binaryPath, args, {
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      let stdout = '';
      let stderr = '';
      const startTime = Date.now();

      this._process.stdout?.on('data', (chunk: Buffer) => {
        stdout += chunk.toString();
      });

      this._process.stderr?.on('data', (chunk: Buffer) => {
        stderr += chunk.toString();
      });

      this._timeoutHandle = setTimeout(() => {
        this._process?.kill('SIGTERM');
        this._state = 'error';
        this._error = 'timeout';
        callbacks.onError('TIMEOUT', 'Transcription timed out');
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
          let transcript = stdout.trim();
          const txtFile = filePath + '.txt';
          if (require('node:fs').existsSync(txtFile)) {
            transcript = require('node:fs').readFileSync(txtFile, 'utf-8').trim();
            try { require('node:fs').unlinkSync(txtFile); } catch { /* ignore */ }
          }
          
          this._state = 'final_result';
          callbacks.onFinal(transcript, Date.now() - startTime);
          callbacks.onStatus(this.getStatus());
          this._state = 'idle';
        } else {
          const errMsg = stderr.trim() || `Process exited with code ${code}`;
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
    // Stop is handled externally by the dictation manager
    // after audio is recorded and ready to transcribe
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
