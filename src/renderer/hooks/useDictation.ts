/**
 * useDictation — React hook for dictation state management.
 *
 * Manages the full dictation lifecycle in the renderer:
 * - Requests microphone permission via browser API
 * - Records audio with MediaRecorder
 * - Sends audio to main process via IPC for transcription
 * - Receives partial/final transcript events
 *
 * Architecture:
 *   useDictation (renderer) → MediaRecorder API → temp WAV → IPC → DictationManager (main)
 *   DictationManager → whisper.cpp/WhisperKit → transcript → IPC event → useDictation
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { DictationStateKind, DictationStartOptions } from '../../shared/desktop-api';

export interface DictationState {
  state: DictationStateKind;
  partialTranscript: string | null;
  error: string | null;
  modelAvailable: boolean;
  binaryAvailable: boolean;
  provider: string | null;
  downloadProgress?: number;
}

export interface UseDictationResult {
  dictationState: DictationState;
  start: (options?: DictationStartOptions) => Promise<void>;
  stop: () => Promise<void>;
  cancel: () => Promise<void>;
  isActive: boolean;
  canStart: boolean;
}

const INITIAL_STATE: DictationState = {
  state: 'idle',
  partialTranscript: null,
  error: null,
  modelAvailable: true, // Optimistic — will be corrected from status
  binaryAvailable: true,
  provider: null,
};

import { getDesktopApi } from '../desktop-api';

function hasDesktopApi(): boolean {
  return true; // We now rely on getDesktopApi() which provides a safe preview fallback
}

export function useDictation(): UseDictationResult {
  const [dictationState, setDictationState] = useState<DictationState>(INITIAL_STATE);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const activeOptionsRef = useRef<DictationStartOptions>({});

  // Subscribe to dictation events from main process
  useEffect(() => {
    const api = getDesktopApi();
    if (!api) return;

    const unsubPartial = api.subscribe('dictation-partial', (payload: unknown) => {
      const p = payload as { transcript?: string };
      setDictationState(prev => ({
        ...prev,
        state: 'partial_result',
        partialTranscript: p.transcript ?? null,
      }));
    });

    const unsubFinal = api.subscribe('dictation-final', (payload: unknown) => {
      const p = payload as { transcript?: string };
      setDictationState(prev => ({
        ...prev,
        state: 'final_result',
        partialTranscript: null,
      }));
    });

    const unsubError = api.subscribe('dictation-error', (payload: unknown) => {
      const p = payload as { code?: string; message?: string };
      setDictationState(prev => ({
        ...prev,
        state: 'error',
        error: p.message ?? p.code ?? 'Unknown error',
      }));
    });

    const unsubStatus = api.subscribe('dictation-status', (payload: unknown) => {
      const p = payload as { status?: DictationState };
      if (p.status) {
        setDictationState(p.status);
      }
    });

    // Load initial status
    api.dictation?.getStatus().then(status => {
      setDictationState(status);
    }).catch(() => { /* ignore */ });

    return () => {
      unsubPartial();
      unsubFinal();
      unsubError();
      unsubStatus();
    };
  }, []);

  const start = useCallback(async (options: DictationStartOptions = {}) => {
    const api = getDesktopApi();
    if (!api?.dictation) {
      setDictationState(prev => ({ ...prev, state: 'error', error: 'Desktop API unavailable' }));
      return;
    }

    activeOptionsRef.current = options;

    // Request microphone permission
    setDictationState(prev => ({ ...prev, state: 'requesting_permission', error: null }));

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Microphone permission denied';
      setDictationState(prev => ({
        ...prev,
        state: 'error',
        error: message,
      }));
      return;
    }

    // Initialize recording
    chunksRef.current = [];
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
    } catch {
      // Fallback without mimeType
      recorder = new MediaRecorder(stream);
    }

    mediaRecorderRef.current = recorder;

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunksRef.current.push(event.data);
      }
    };

    recorder.start(250); // 250ms chunks

    setDictationState(prev => ({ ...prev, state: 'listening', error: null }));

    // Notify main process
    try {
      await api.dictation.start(options);
    } catch (err) {
      recorder.stop();
      stream.getTracks().forEach(t => t.stop());
      const message = err instanceof Error ? err.message : 'Failed to start dictation';
      setDictationState(prev => ({ ...prev, state: 'error', error: message }));
    }
  }, []);

  const stop = useCallback(async () => {
    const api = getDesktopApi();
    const recorder = mediaRecorderRef.current;

    if (!recorder || recorder.state === 'inactive') {
      // Nothing recording — just cancel at main process level
      await api?.dictation?.cancel();
      setDictationState(prev => ({ ...prev, state: 'idle' }));
      return;
    }

    setDictationState(prev => ({ ...prev, state: 'transcribing' }));

    return new Promise<void>((resolve) => {
      recorder.onstop = async () => {
        const stream = recorder.stream;
        stream.getTracks().forEach(t => t.stop());

        const webmBlob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        chunksRef.current = [];
        mediaRecorderRef.current = null;

        try {
          const { convertWebmToWav } = await import('../lib/wavEncoder');
          const wavBlob = await convertWebmToWav(webmBlob);

          // Convert blob to base64 and send to main process
          const reader = new FileReader();
          reader.onload = async () => {
            try {
              const base64 = (reader.result as string).split(',')[1] ?? '';
              await api?.dictation?.stop({ audioData: base64 });
            } catch (err) {
              const message = err instanceof Error ? err.message : 'Failed to stop dictation';
              setDictationState(prev => ({ ...prev, state: 'error', error: message }));
            }
            resolve();
          };
          reader.readAsDataURL(wavBlob);
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Audio conversion failed';
          setDictationState(prev => ({ ...prev, state: 'error', error: message }));
          resolve();
        }
      };

      recorder.stop();
    });
  }, []);

  const cancel = useCallback(async () => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
      recorder.stream.getTracks().forEach(t => t.stop());
      mediaRecorderRef.current = null;
    }
    chunksRef.current = [];

    const api = getDesktopApi();
    await api?.dictation?.cancel();
    setDictationState(prev => ({ ...prev, state: 'idle', partialTranscript: null, error: null }));
  }, []);

  const isActive = dictationState.state !== 'idle' && dictationState.state !== 'error';
  const canStart = hasDesktopApi() && dictationState.state === 'idle';

  return { dictationState, start, stop, cancel, isActive, canStart };
}
