/**
 * Live speech transport.
 *
 * `StreamingSpeechSession` owns timing and text; this file owns the socket. It
 * authenticates the connection, gates it on consent and quota, decodes PCM off
 * the wire, and forwards whatever the session emits.
 *
 * No new socket server is stood up: `@fastify/websocket` is already registered
 * in `build-app.ts`, so this is one more route on it. The realtime hub is
 * deliberately untouched — that hub routes commands to *desktop runtime
 * devices* keyed by deviceId, which is a different addressing model from a
 * mobile user holding a mic open.
 *
 * Registered only when `ELYAN_VOICE_STREAMING_ENABLED` is true. With the flag
 * off this route does not exist and the turn-based upload path is unchanged.
 */

import { randomUUID } from "node:crypto";
import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import type { RawData } from "ws";
import { classifyIntent } from "../../core/understanding/intent-classifier.js";
import { AppError } from "../../lib/errors.js";
import { createTask } from "../tasks/service.js";
import {
  buildVoiceTaskPayload,
  decideVoiceDispatch,
} from "./voice-dispatch.js";
import {
  maybeWarnOnVoiceLatencyBreach,
  recordFinalToDispatchLatency,
  recordFirstPartialLatency,
  recordPartialEmitted,
  recordSegmentCommitted,
  recordSegmentDuration,
} from "./voice-metrics.js";
import { extractBearerToken } from "../../lib/request-auth.js";
import type { AuthTokenPayload } from "../../types/auth.js";
import { assertCloudSpeechConsent } from "../consents/service.js";
import { reserveStreamingSpeechAdmission } from "./admission.js";
import { transcribeSpeechWithGroq } from "./groq-speech-adapter.js";
import { pcmToWav, WAV_CONTENT_TYPE } from "./pcm-wav.js";
import {
  StreamingSpeechSession,
  msForBytes,
  type StreamingEvent,
} from "./streaming-session.js";

/**
 * ~1 s of 16 kHz PCM is 32 KB, ~43 KB base64. The cap leaves generous headroom
 * for a slow client batching a few chunks while still refusing anything that
 * is clearly not a mic frame.
 */
const MAX_AUDIO_MESSAGE_BYTES = 256 * 1024;

/** Audio seconds are charged in blocks so the store is not hit per chunk. */
const BUDGET_CHARGE_INTERVAL_MS = 10_000;

/** Concurrency slots are TTL'd; refresh them well inside that window. */
const SLOT_TOUCH_INTERVAL_MS = 20_000;

/** An idle socket is a billable open mic. Close it. */
const IDLE_TIMEOUT_MS = 120_000;

/**
 * Araya giren ters vekiller soketi upstream'den veri akmadığında kesiyor
 * (canlıda nginx `proxy_read_timeout 120s`). Kullanıcı mikrofonu açık tutup
 * susarsa sunucu hiçbir şey göndermez — ne `partial` ne `final` — ve bağlantı
 * kimse bir şey yapmadan düşer. İstemcinin gördüğü şey "bağlantı kesildi"dir.
 *
 * Bu yüzden sessiz oturumda da düzenli bir çerçeve gidiyor. `pong` seçildi:
 * istemcilerde zaten no-op, yeni tip tanıtmıyor. Boşta kalma sayacını
 * KURMUYOR — o sayaç istemci mesajlarına bakar ve açık mikrofonu kapatma
 * politikası olarak kalmalı.
 */
const HEARTBEAT_INTERVAL_MS = 25_000;

export const clientMessageSchema = z.union([
  z.object({
    type: z.literal("start"),
    locale: z
      .string()
      .trim()
      .toLowerCase()
      .regex(/^[a-z]{2}$/)
      .optional(),
    sessionId: z.string().trim().min(1).max(128).optional(),
    /**
     * The desktop the user currently has selected. Without it `createTask`
     * still resolves *a* device, but voice would silently ignore the choice
     * the user made in the app — the task would land on whichever machine the
     * resolver happened to pick.
     */
    deviceId: z.string().uuid().optional(),
  }),
  z.object({
    type: z.literal("audio"),
    seq: z.number().int().nonnegative(),
    b64: z.string().min(1).max(MAX_AUDIO_MESSAGE_BYTES),
  }),
  z.object({ type: z.literal("stop") }),
  /**
   * Sessize alınmış mikrofon ses göndermez, ama oturum hâlâ açıktır. Boşta
   * kalma sayacı (`IDLE_TIMEOUT_MS`) her mesajda kurulduğu için sessize alma
   * iki dakikada oturumu `idle_timeout` ile öldürüyordu — kullanıcı hiçbir şey
   * yapmamışken bağlantı düşüyordu. WS ping/pong kontrol çerçevesi Fastify'ın
   * `message` kancasına gelmediği için sayacı kurmuyor; bu yüzden protokole
   * ait, ölçülebilir bir `ping` gerekiyor. Ses saniyesi harcamaz.
   */
  z.object({ type: z.literal("ping") }),
]);

export type ClientMessage = z.infer<typeof clientMessageSchema>;

/**
 * Wire shape sent to the client. `partial` carries `seq` (the plan's field
 * name) rather than the engine's `segmentId` so the mobile caption can tell
 * revisions of the current utterance apart from a new one.
 */
export type ServerMessage =
  | { type: "ready"; sessionId: string | null }
  | { type: "partial"; text: string; seq: number }
  | { type: "final"; text: string; segmentId: number }
  | { type: "intent"; ready: true; taskId?: string }
  | { type: "pong" }
  | { type: "error"; code: string };

export function toServerMessage(event: StreamingEvent): ServerMessage {
  if (event.type === "partial") {
    return { type: "partial", text: event.text, seq: event.segmentId };
  }
  if (event.type === "final") {
    return { type: "final", text: event.text, segmentId: event.segmentId };
  }
  return { type: "error", code: event.code };
}

/**
 * Base64 from an untrusted client can decode to garbage or to a buffer with a
 * dangling odd byte, which would make `readInt16LE` walk off the end during RMS.
 */
export function decodeAudioChunk(b64: string): Buffer | null {
  let decoded: Buffer;
  try {
    decoded = Buffer.from(b64, "base64");
  } catch {
    return null;
  }
  if (decoded.length < 2) return null;
  // Trim a trailing half-sample rather than rejecting the frame: a chunk
  // boundary landing mid-sample is a client framing artifact, not an attack.
  return decoded.length % 2 === 0 ? decoded : decoded.subarray(0, decoded.length - 1);
}

type StreamTranscriber = typeof transcribeSpeechWithGroq;
type CloudSpeechConsentAssert = (
  app: Parameters<typeof assertCloudSpeechConsent>[0],
  userId: string,
) => Promise<unknown>;
type StreamingAdmissionReserve = typeof reserveStreamingSpeechAdmission;
type VoiceTaskDispatcher = (
  app: Parameters<typeof createTask>[0],
  input: Parameters<typeof createTask>[1],
) => Promise<unknown>;

/**
 * Dependencies are injected the same way `buildSpeechRoutes` does it, so the
 * socket can be driven in a test without a provider, a consent row, or Redis.
 */
export function buildSpeechStreamRoutes(
  transcribe: StreamTranscriber = transcribeSpeechWithGroq,
  assertConsent: CloudSpeechConsentAssert = assertCloudSpeechConsent,
  reserveAdmission: StreamingAdmissionReserve = reserveStreamingSpeechAdmission,
  dispatchTask: VoiceTaskDispatcher = createTask,
): FastifyPluginAsync {
  return async (app) => {
  app.get("/stream", { websocket: true }, async (socket, request) => {
    let admission: Awaited<
      ReturnType<typeof reserveStreamingSpeechAdmission>
    > | null = null;
    let session: StreamingSpeechSession | null = null;
    let touchTimer: NodeJS.Timeout | undefined;
    let idleTimer: NodeJS.Timeout | undefined;
    let heartbeatTimer: NodeJS.Timeout | undefined;
    let closed = false;
    let started = false;
    let language: string | undefined;
    let activeSessionId: string | null = null;
    let preferredDeviceId: string | undefined;
    let unchargedMs = 0;
    /** Set on the first audio frame after a cut; cleared once measured. */
    let segmentStartedAtMs: number | null = null;
    let lastPartialText = "";

    const send = (message: ServerMessage) => {
      if (closed || socket.readyState !== socket.OPEN) return;
      try {
        socket.send(JSON.stringify(message));
      } catch {
        // The close handler does the teardown; a failed write is not
        // separately recoverable.
      }
    };

    const shutdown = (code: number, reason: string) => {
      if (closed) return;
      closed = true;
      if (touchTimer) clearInterval(touchTimer);
      if (idleTimer) clearTimeout(idleTimer);
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      void admission?.release().catch(() => undefined);
      admission = null;
      try {
        socket.close(code, reason);
      } catch {
        // Already gone.
      }
    };

    const armIdleTimer = () => {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        send({ type: "error", code: "idle_timeout" });
        shutdown(4408, "idle");
      }, IDLE_TIMEOUT_MS);
      idleTimer.unref?.();
    };

    try {
      const token = extractBearerToken(request);
      const payload = (await app.jwt.verify(token)) as AuthTokenPayload;
      if (payload.kind !== "user") {
        socket.close(4401, "User token required");
        return;
      }
      const userId = payload.sub;

      // Live audio is still cloud speech. Same consent as the upload path —
      // streaming does not introduce a new permission type (§4 trap 5).
      await assertConsent(app, userId);
      admission = await reserveAdmission(app, userId);

      const activeAdmission = admission;
      touchTimer = setInterval(() => {
        void activeAdmission.touch().catch(() => undefined);
      }, SLOT_TOUCH_INTERVAL_MS);
      touchTimer.unref?.();

      // F2: a committed segment may start work immediately. The mic is not
      // touched here — dispatch and listening run in parallel, which is the
      // whole point (§3 F2).
      const maybeDispatch = async (
        text: string,
        segmentId: number,
        finalAtMs: number,
      ) => {
        const decision = decideVoiceDispatch(
          text,
          classifyIntent({ userId, message: text }),
        );
        if (!decision.dispatch) {
          app.log.debug(
            { reason: decision.reason, segmentId },
            "live voice segment not dispatched",
          );
          return;
        }
        try {
          const created = await dispatchTask(app, {
            userId,
            // Honour the device the user picked. `requestedTargetDeviceId` is
            // what routing reports back on; `targetDeviceId` is the preference
            // the resolver starts from — the tasks route passes both the same
            // way for exactly this reason.
            targetDeviceId: preferredDeviceId,
            requestedTargetDeviceId: preferredDeviceId,
            title: decision.title,
            payload: buildVoiceTaskPayload({
              text,
              sessionId: activeSessionId,
              segmentId,
              locale: language,
            }),
            requestedCapabilities: [],
            requestId: randomUUID(),
          });
          const taskId =
            created && typeof created === "object" && "task" in created
              ? (created.task as { id?: string } | undefined)?.id
              : undefined;
          // End of sentence → work actually started. The second §4 target.
          recordFinalToDispatchLatency(Date.now() - finalAtMs);
          maybeWarnOnVoiceLatencyBreach(
            (payload, message) => app.log.warn(payload, message),
            (payload, message) => app.log.info(payload, message),
          );
          send({ type: "intent", ready: true, ...(taskId ? { taskId } : {}) });
        } catch (error) {
          // A refused dispatch (approval required, quota, no device) must not
          // kill the session — the user is still talking.
          app.log.warn({ error, segmentId }, "live voice dispatch failed");
          send({ type: "error", code: "dispatch_failed" });
        }
      };

      session = new StreamingSpeechSession({
        transcribe: async (pcm) => {
          try {
            const result = await transcribe(app.config, {
              audio: pcmToWav(pcm),
              contentType: WAV_CONTENT_TYPE,
              language,
            });
            return result.text;
          } catch (error) {
            // VAD cuts on level, Whisper decides on content: a segment that
            // was loud enough but held no words is routine, not a failure.
            // Returning empty lets the engine drop it silently instead of
            // surfacing an error the user cannot act on.
            if (
              error instanceof AppError &&
              error.code === "speech_not_detected"
            ) {
              return "";
            }
            throw error;
          }
        },
        emit: (event) => {
          send(toServerMessage(event));
          if (event.type === "partial") {
            // The headline number: how long after the user started talking
            // their words first appeared. Measured once per segment.
            if (segmentStartedAtMs != null) {
              recordFirstPartialLatency(Date.now() - segmentStartedAtMs);
              segmentStartedAtMs = null;
            }
            recordPartialEmitted(lastPartialText, event.text);
            lastPartialText = event.text;
          }
          if (event.type === "final") {
            recordSegmentCommitted();
            recordSegmentDuration(event.durationMs);
            // Checked per segment, not per dispatch: the first-partial target
            // can regress on its own while nothing is ever dispatched.
            maybeWarnOnVoiceLatencyBreach(
              (payload, message) => app.log.warn(payload, message),
              (payload, message) => app.log.info(payload, message),
            );
            lastPartialText = "";
            segmentStartedAtMs = null;
            void maybeDispatch(event.text, event.segmentId, Date.now());
          }
        },
      });

      armIdleTimer();

      heartbeatTimer = setInterval(() => {
        send({ type: "pong" });
      }, HEARTBEAT_INTERVAL_MS);
      heartbeatTimer.unref?.();

      socket.on("message", async (raw: RawData) => {
        if (closed) return;
        let parsed: ClientMessage;
        try {
          parsed = clientMessageSchema.parse(JSON.parse(raw.toString()));
        } catch {
          send({ type: "error", code: "invalid_message" });
          return;
        }

        armIdleTimer();

        if (parsed.type === "start") {
          language = parsed.locale;
          activeSessionId = parsed.sessionId ?? null;
          preferredDeviceId = parsed.deviceId;
          started = true;
          send({ type: "ready", sessionId: activeSessionId });
          return;
        }

        if (parsed.type === "ping") {
          // `armIdleTimer()` yukarıda zaten çalıştı; asıl iş oydu. Yanıt,
          // istemcinin soketin gerçekten canlı olduğunu görmesi için.
          send({ type: "pong" });
          return;
        }

        if (parsed.type === "stop") {
          await session?.finish().catch(() => undefined);
          shutdown(1000, "stopped");
          return;
        }

        // audio
        if (!started) {
          send({ type: "error", code: "not_started" });
          return;
        }
        const pcm = decodeAudioChunk(parsed.b64);
        if (!pcm) {
          send({ type: "error", code: "invalid_audio" });
          return;
        }

        // First frame of a new utterance: the clock for the first-partial
        // target starts here, not at socket open (the mic may idle for
        // minutes before anyone speaks).
        segmentStartedAtMs ??= Date.now();

        // Meter the audio actually accepted, in blocks. Charging per chunk
        // would hammer the store; charging only at the end would let a long
        // session blow past the budget before anyone noticed.
        unchargedMs += msForBytes(pcm.length);
        if (unchargedMs >= BUDGET_CHARGE_INTERVAL_MS) {
          const seconds = Math.floor(unchargedMs / 1000);
          unchargedMs -= seconds * 1000;
          const allowed = await activeAdmission
            .consumeSeconds(seconds)
            .catch(() => false);
          if (!allowed) {
            send({ type: "error", code: "speech_quota_exhausted" });
            shutdown(4429, "quota");
            return;
          }
        }

        try {
          await session?.push(pcm);
        } catch (error) {
          app.log.warn({ error }, "live speech session push failed");
          send({ type: "error", code: "transcription_failed" });
        }
      });

      socket.on("close", () => {
        // finish() may emit a final segment, but the socket is already gone;
        // the session is dropped rather than flushed into a dead connection.
        closed = true;
        if (touchTimer) clearInterval(touchTimer);
        if (idleTimer) clearTimeout(idleTimer);
        if (heartbeatTimer) clearInterval(heartbeatTimer);
        void activeAdmission.release().catch(() => undefined);
      });
    } catch (error) {
      if (touchTimer) clearInterval(touchTimer);
      if (idleTimer) clearTimeout(idleTimer);
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      void admission?.release().catch(() => undefined);
      if (error instanceof AppError) {
        send({ type: "error", code: error.code });
        socket.close(error.statusCode === 429 ? 4429 : 4401, error.code);
        return;
      }
      app.log.warn({ error }, "live speech socket setup failed");
      socket.close(4401, "speech stream authentication failed");
    }
  });
  };
}

export const speechStreamRoutes = buildSpeechStreamRoutes();
