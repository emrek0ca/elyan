/**
 * Live speech: the sliding-window engine.
 *
 * `whisper-large-v3-turbo` is not a streaming model — it transcribes a clip and
 * returns. Building live voice on it therefore means *manufacturing* streaming:
 * keep a short rolling tail of audio, re-transcribe it a few times a second to
 * produce provisional text, and cut a segment when the speaker actually pauses.
 *
 * That trade is deliberate. A true streaming vendor would be more accurate per
 * token, but it is a new provider, a new privacy surface, and a new consent
 * gate. This gets the latency that makes voice feel alive using the pipeline
 * that is already approved and already paid for. Measure first (see
 * `CANLI-SES-PLANI.md` §4), swap later if the numbers demand it.
 *
 * This module owns *timing and text*, not transport. It never touches sockets,
 * Fastify, or the database, so it can be exercised directly. The transport
 * layer feeds it PCM and forwards whatever it emits.
 */

/** 16 kHz mono 16-bit PCM: what the client is expected to send. */
export const SAMPLE_RATE_HZ = 16_000;
export const BYTES_PER_SAMPLE = 2;

/**
 * How much audio a provisional pass looks at. Long enough for Whisper to have
 * real context (it is bad at very short clips), short enough to stay cheap.
 */
export const WINDOW_MS = 4_000;

/** Floor between provisional passes. Below this we are paying for jitter. */
export const PARTIAL_INTERVAL_MS = 500;

/**
 * Silence that ends a segment. Turkish speakers pause mid-sentence constantly,
 * so a tighter value chops utterances in half — the single most annoying
 * failure mode in a voice UI.
 */
export const SILENCE_HOLD_MS = 900;

/** Below this RMS (0..1) a frame counts as silence. */
export const SILENCE_RMS_THRESHOLD = 0.012;

/** A segment shorter than this is a cough, not speech. */
export const MIN_SEGMENT_MS = 400;

/** Hard stop so a stuck-open mic cannot bill forever. */
export const MAX_SEGMENT_MS = 30_000;

export type StreamingEvent =
  | { type: "partial"; text: string; segmentId: number; atMs: number }
  | { type: "final"; text: string; segmentId: number; durationMs: number }
  | { type: "error"; code: string };

export type TranscribeWindow = (
  pcm: Buffer,
  options: { final: boolean },
) => Promise<string>;

export type StreamingSessionOptions = {
  transcribe: TranscribeWindow;
  emit: (event: StreamingEvent) => void;
  language?: string;
  now?: () => number;
  windowMs?: number;
  partialIntervalMs?: number;
  silenceHoldMs?: number;
  silenceRmsThreshold?: number;
};

/** Root-mean-square level of a 16-bit little-endian PCM buffer, 0..1. */
export function pcmRms(pcm: Buffer): number {
  const sampleCount = Math.floor(pcm.length / BYTES_PER_SAMPLE);
  if (sampleCount === 0) return 0;
  let sumSquares = 0;
  for (let index = 0; index < sampleCount; index += 1) {
    const sample = pcm.readInt16LE(index * BYTES_PER_SAMPLE) / 32_768;
    sumSquares += sample * sample;
  }
  return Math.sqrt(sumSquares / sampleCount);
}

export function bytesForMs(ms: number): number {
  return Math.floor((ms / 1000) * SAMPLE_RATE_HZ) * BYTES_PER_SAMPLE;
}

export function msForBytes(bytes: number): number {
  return (bytes / BYTES_PER_SAMPLE / SAMPLE_RATE_HZ) * 1000;
}

/**
 * Whisper re-transcribing an overlapping window rewrites its own tail as it
 * gains context. Emitting every revision makes the caption twitch, so a
 * provisional result is only forwarded when it actually says something new.
 */
export function isMeaningfulRevision(
  previous: string,
  next: string,
): boolean {
  const a = previous.trim();
  const b = next.trim();
  if (!b) return false;
  if (a === b) return false;
  // Pure growth is always worth showing; the caption is extending.
  if (b.startsWith(a)) return true;
  // Otherwise require the text to have moved enough to be worth a repaint.
  return Math.abs(b.length - a.length) > 2 || !b.includes(a.slice(0, 12));
}

export class StreamingSpeechSession {
  constructor(private readonly options: StreamingSessionOptions) {
    this.windowBytes = bytesForMs(options.windowMs ?? WINDOW_MS);
    this.partialIntervalMs = options.partialIntervalMs ?? PARTIAL_INTERVAL_MS;
    this.silenceHoldMs = options.silenceHoldMs ?? SILENCE_HOLD_MS;
    this.silenceThreshold =
      options.silenceRmsThreshold ?? SILENCE_RMS_THRESHOLD;
    this.now = options.now ?? Date.now;
  }

  private readonly windowBytes: number;
  private readonly partialIntervalMs: number;
  private readonly silenceHoldMs: number;
  private readonly silenceThreshold: number;
  private readonly now: () => number;

  /** Audio belonging to the segment currently being spoken. */
  private segment: Buffer = Buffer.alloc(0);
  private segmentId = 0;
  private lastPartialAtMs = 0;
  private lastPartialText = "";
  private silenceRunMs = 0;
  private sawSpeech = false;
  private partialInFlight = false;
  private closed = false;

  /**
   * Feed one chunk of PCM. Safe to call as fast as audio arrives: provisional
   * passes are rate-limited and never overlap, so a slow provider degrades the
   * caption's refresh rate rather than queueing work without bound.
   */
  async push(chunk: Buffer): Promise<void> {
    if (this.closed || chunk.length === 0) return;

    const nowMs = this.now();
    if (this.segment.length === 0) {
      this.lastPartialAtMs = nowMs;
    }
    this.segment = Buffer.concat([this.segment, chunk]);

    const loud = pcmRms(chunk) >= this.silenceThreshold;
    if (loud) {
      this.sawSpeech = true;
      this.silenceRunMs = 0;
    } else {
      this.silenceRunMs += msForBytes(chunk.length);
    }

    const segmentMs = msForBytes(this.segment.length);

    // A pause after real speech closes the segment. Silence before any speech
    // is just an open mic in a quiet room — it must not emit empty finals.
    if (this.sawSpeech && this.silenceRunMs >= this.silenceHoldMs) {
      await this.cut();
      return;
    }
    if (segmentMs >= MAX_SEGMENT_MS) {
      await this.cut();
      return;
    }
    // Silence-only buffers are dropped so memory does not grow while nobody
    // is speaking.
    if (!this.sawSpeech && segmentMs > this.silenceHoldMs * 2) {
      this.segment = Buffer.alloc(0);
      this.silenceRunMs = 0;
      return;
    }

    if (
      this.sawSpeech &&
      nowMs - this.lastPartialAtMs >= this.partialIntervalMs &&
      !this.partialInFlight
    ) {
      await this.emitPartial(nowMs);
    }
  }

  /** Speaker stopped (or the socket closed): flush whatever is buffered. */
  async finish(): Promise<void> {
    if (this.closed) return;
    await this.cut();
    this.closed = true;
  }

  private async emitPartial(nowMs: number): Promise<void> {
    this.partialInFlight = true;
    this.lastPartialAtMs = nowMs;
    // Only the tail is re-read: the caption is about what is being said now,
    // and a growing clip would make every pass slower than the last.
    const window =
      this.segment.length > this.windowBytes
        ? this.segment.subarray(this.segment.length - this.windowBytes)
        : this.segment;
    try {
      const text = await this.options.transcribe(window, { final: false });
      if (isMeaningfulRevision(this.lastPartialText, text)) {
        this.lastPartialText = text.trim();
        this.options.emit({
          type: "partial",
          text: this.lastPartialText,
          segmentId: this.segmentId,
          atMs: nowMs,
        });
      }
    } catch {
      // A dropped provisional pass is invisible to the user — the next one
      // covers the same audio. Never surface it as an error.
    } finally {
      this.partialInFlight = false;
    }
  }

  private async cut(): Promise<void> {
    const durationMs = msForBytes(this.segment.length);
    const audio = this.segment;
    this.resetSegment();

    if (!this.sawSpeechInLastSegment || durationMs < MIN_SEGMENT_MS) return;

    try {
      // The final pass reads the whole segment, not the window: this is the
      // text the task will be built from, so accuracy outranks latency here.
      const text = (await this.options.transcribe(audio, { final: true })).trim();
      if (!text) return;
      this.options.emit({
        type: "final",
        text,
        segmentId: this.segmentId,
        durationMs,
      });
    } catch {
      this.options.emit({ type: "error", code: "transcription_failed" });
    } finally {
      this.segmentId += 1;
    }
  }

  private sawSpeechInLastSegment = false;

  private resetSegment(): void {
    this.sawSpeechInLastSegment = this.sawSpeech;
    this.segment = Buffer.alloc(0);
    this.silenceRunMs = 0;
    this.sawSpeech = false;
    this.lastPartialText = "";
  }
}
