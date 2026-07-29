import type { FastifyPluginAsync } from "fastify";
import { z } from "zod";
import { AppError } from "../../lib/errors.js";
import { assertRequestBudget } from "../../lib/reliability/request-budget.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { assertCloudSpeechConsent } from "../consents/service.js";
import { reserveSpeechAdmission } from "./admission.js";
import {
  transcribeSpeechWithGroq,
  type SpeechTranscriptionInput,
  type SpeechTranscriptionResult,
} from "./groq-speech-adapter.js";

const MAX_AUDIO_BYTES = 1024 * 1024;
const MAX_WIRE_AUDIO_BYTES = MAX_AUDIO_BYTES + 1;
const speechQuerySchema = z.object({
  language: z
    .string()
    .trim()
    .toLowerCase()
    .regex(/^[a-z]{2}$/)
    .optional(),
});

type SpeechTranscriber = (
  config: Parameters<typeof transcribeSpeechWithGroq>[0],
  input: SpeechTranscriptionInput,
) => Promise<SpeechTranscriptionResult>;

type CloudSpeechConsentAssert = (
  app: Parameters<typeof assertCloudSpeechConsent>[0],
  userId: string,
) => Promise<unknown>;

export function buildSpeechTelemetry(input: {
  bytes: number;
  model: string;
  resultCode: string;
  startedAtMs: number;
}) {
  return {
    event: "speech.transcription",
    bytes: Math.max(0, Math.floor(input.bytes)),
    model: input.model.trim().slice(0, 100),
    resultCode: input.resultCode.trim().slice(0, 100),
    durationMs: Math.max(0, Date.now() - input.startedAtMs),
  };
}

export function buildSpeechRoutes(
  transcribe: SpeechTranscriber = transcribeSpeechWithGroq,
  assertConsent: CloudSpeechConsentAssert = assertCloudSpeechConsent,
): FastifyPluginAsync {
  return async (app) => {
    app.addContentTypeParser(
      ["audio/mp4", "audio/m4a", "audio/x-m4a"],
      { parseAs: "buffer", bodyLimit: MAX_WIRE_AUDIO_BYTES },
      (_request, body, done) => done(null, body),
    );

    app.post(
      "/transcriptions",
      {
        bodyLimit: MAX_WIRE_AUDIO_BYTES,
        onRequest: async (request, reply) => {
          await app.authenticateUser(request, reply);
          if (reply.sent) return;
          await assertRequestBudget(app, {
            scope: "speech_upload_ip",
            identity: request.ip,
            max: app.config.ELYAN_SPEECH_IP_RPM_LIMIT,
            windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
          });
        },
      },
      async (request, reply) => {
        const auth = getUserAuth(request);
        await assertRequestBudget(app, {
          scope: "speech_transcription",
          identity: auth.sub,
          max: 20,
          windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
        });
        await assertConsent(app, auth.sub);

        if (
          !Buffer.isBuffer(request.body) ||
          request.body.length < 128 ||
          request.body.length > MAX_AUDIO_BYTES
        ) {
          throw new AppError(
            400,
            "invalid_audio",
            "Geçerli bir ses kaydı gönderin.",
          );
        }
        const query = speechQuerySchema.parse(request.query);
        const contentType = request.headers["content-type"]
          ?.split(";", 1)[0]
          ?.trim()
          .toLowerCase();
        if (!contentType) {
          throw new AppError(
            400,
            "invalid_audio",
            "Ses biçimi desteklenmiyor.",
          );
        }

        const admission = await reserveSpeechAdmission(app, auth.sub);
        const providerAbort = new AbortController();
        const abortProvider = () => providerAbort.abort();
        const abortProviderIfDisconnected = () => {
          if (!reply.raw.writableEnded) providerAbort.abort();
        };
        request.raw.once("aborted", abortProvider);
        reply.raw.once("close", abortProviderIfDisconnected);
        if (request.raw.aborted) providerAbort.abort();
        const startedAtMs = Date.now();
        const configuredModel =
          app.config.GROQ_TRANSCRIBE_MODEL?.trim() || "whisper-large-v3-turbo";
        try {
          const result = await transcribe(app.config, {
            audio: request.body,
            contentType,
            language: query.language,
            signal: providerAbort.signal,
          });
          request.log.info(
            buildSpeechTelemetry({
              bytes: request.body.length,
              model: result.model,
              resultCode: "ok",
              startedAtMs,
            }),
            "speech transcription completed",
          );
          return result;
        } catch (error) {
          const telemetry = buildSpeechTelemetry({
            bytes: request.body.length,
            model: configuredModel,
            resultCode: providerAbort.signal.aborted
              ? "client_cancelled"
              : error instanceof AppError
                ? error.code
                : "speech_transcription_failed",
            startedAtMs,
          });
          if (providerAbort.signal.aborted) {
            request.log.info(telemetry, "speech transcription cancelled");
          } else {
            request.log.warn(telemetry, "speech transcription failed");
          }
          throw error;
        } finally {
          request.raw.removeListener("aborted", abortProvider);
          reply.raw.removeListener("close", abortProviderIfDisconnected);
          await admission.release();
        }
      },
    );
  };
}

export const speechRoutes = buildSpeechRoutes();
