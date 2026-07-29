import assert from "node:assert/strict";
import test from "node:test";
import Fastify, { type FastifyRequest } from "fastify";
import { AppError } from "../../lib/errors.js";
import { buildSpeechRoutes, buildSpeechTelemetry } from "./routes.js";

function authenticatedSpeechApp(budgetValue = 1, authenticated = true) {
  const app = Fastify();
  app.setErrorHandler((error, _request, reply) => {
    if (error instanceof AppError) {
      return reply.status(error.statusCode).send({
        error: error.code,
        message: error.message,
      });
    }
    return reply.send(error);
  });
  app.decorateRequest("auth", null as never);
  app.decorate("authenticateUser", async (request: FastifyRequest) => {
    if (!authenticated) {
      throw new AppError(401, "unauthorized", "Oturum gerekli.");
    }
    request.auth = {
      kind: "user",
      sub: "user-1",
      sessionId: "session-1",
    } as never;
  });
  app.decorate("config", {
    REQUEST_BUDGET_WINDOW_MS: 60_000,
    ELYAN_AI_DATA_SHARING_CONSENT_REQUIRED: false,
    GROQ_API_KEY: "test-key",
    GROQ_BASE_URL: "https://api.groq.com/openai/v1",
    GROQ_TRANSCRIBE_MODEL: "whisper-large-v3-turbo",
  } as never);
  app.decorate("services", {
    reliability: {
      store: {
        async increment() {
          return budgetValue;
        },
        async tryAcquireExpiringSlot() {
          return { allowed: true, used: 1 };
        },
        async releaseExpiringSlot() {
          return true;
        },
      },
    },
  } as never);
  return app;
}

test("speech transcription route forwards authenticated raw audio without persisting it", async () => {
  const app = authenticatedSpeechApp();
  let received:
    {
      bytes: number;
      language?: string;
      contentType: string;
      signalAborted: boolean;
    } | undefined;
  await app.register(
    buildSpeechRoutes(
      async (_config, input) => {
        received = {
          bytes: input.audio.length,
          language: input.language,
          contentType: input.contentType,
          signalAborted: input.signal?.aborted ?? true,
        };
        return {
          text: "Raporu hazirla.",
          language: input.language ?? null,
          model: "whisper-large-v3-turbo",
        };
      },
      async () => true,
    ),
    { prefix: "/v1/speech" },
  );

  const response = await app.inject({
    method: "POST",
    url: "/v1/speech/transcriptions?language=tr",
    headers: { "content-type": "audio/mp4" },
    payload: Buffer.alloc(512, 1),
  });

  assert.equal(response.statusCode, 200);
  assert.deepEqual(received, {
    bytes: 512,
    language: "tr",
    contentType: "audio/mp4",
    signalAborted: false,
  });
  assert.equal(response.json().text, "Raporu hazirla.");
  await app.close();
});

test("speech transcription route rejects unsupported content types", async () => {
  const app = authenticatedSpeechApp();
  await app.register(
    buildSpeechRoutes(undefined, async () => true),
    {
      prefix: "/v1/speech",
    },
  );
  const response = await app.inject({
    method: "POST",
    url: "/v1/speech/transcriptions",
    headers: { "content-type": "application/json" },
    payload: { audio: "not-audio" },
  });

  assert.equal(response.statusCode, 400);
  await app.close();
});

test("speech transcription authenticates before parsing the audio body", async () => {
  const app = authenticatedSpeechApp(1, false);
  await app.register(
    buildSpeechRoutes(undefined, async () => true),
    {
      prefix: "/v1/speech",
    },
  );
  const response = await app.inject({
    method: "POST",
    url: "/v1/speech/transcriptions",
    headers: { "content-type": "audio/mp4" },
    payload: Buffer.alloc(1024 * 1024 + 1),
  });

  assert.equal(response.statusCode, 401);
  assert.equal(response.json().error, "unauthorized");
  await app.close();
});

test("speech transcription route rejects empty and oversized audio safely", async () => {
  const app = authenticatedSpeechApp();
  await app.register(
    buildSpeechRoutes(undefined, async () => true),
    {
      prefix: "/v1/speech",
    },
  );
  const emptyResponse = await app.inject({
    method: "POST",
    url: "/v1/speech/transcriptions",
    headers: { "content-type": "audio/m4a" },
    payload: Buffer.alloc(64),
  });
  const oversizedResponse = await app.inject({
    method: "POST",
    url: "/v1/speech/transcriptions",
    headers: { "content-type": "audio/mp4" },
    payload: Buffer.alloc(1024 * 1024 + 1),
  });

  assert.equal(emptyResponse.statusCode, 400);
  assert.equal(emptyResponse.json().error, "invalid_audio");
  assert.equal(oversizedResponse.statusCode, 400);
  assert.equal(oversizedResponse.json().error, "invalid_audio");
  await app.close();
});

test("speech transcription route enforces a per-user request budget", async () => {
  const app = authenticatedSpeechApp(21);
  await app.register(
    buildSpeechRoutes(undefined, async () => true),
    {
      prefix: "/v1/speech",
    },
  );
  const response = await app.inject({
    method: "POST",
    url: "/v1/speech/transcriptions",
    headers: { "content-type": "audio/mp4" },
    payload: Buffer.alloc(512),
  });

  assert.equal(response.statusCode, 429);
  assert.equal(response.json().error, "request_budget_exceeded");
  await app.close();
});

test("speech transcription route requires explicit cloud speech consent", async () => {
  const app = authenticatedSpeechApp();
  let transcribeCalled = false;
  await app.register(
    buildSpeechRoutes(
      async () => {
        transcribeCalled = true;
        return {
          text: "Bu çağrılmamalı.",
          language: "tr",
          model: "whisper-large-v3-turbo",
        };
      },
      async () => {
        throw new AppError(
          403,
          "CLOUD_SPEECH_CONSENT_REQUIRED",
          "Ses bulut izni gerekiyor.",
        );
      },
    ),
    { prefix: "/v1/speech" },
  );

  const response = await app.inject({
    method: "POST",
    url: "/v1/speech/transcriptions?language=tr",
    headers: { "content-type": "audio/mp4" },
    payload: Buffer.alloc(512, 1),
  });

  assert.equal(response.statusCode, 403);
  assert.equal(response.json().error, "CLOUD_SPEECH_CONSENT_REQUIRED");
  assert.equal(transcribeCalled, false);
  await app.close();
});

test("cloud speech consent is independent from the general AI consent flag", async () => {
  const app = authenticatedSpeechApp();
  app.config.ELYAN_AI_DATA_SHARING_CONSENT_REQUIRED = true;
  await app.register(
    buildSpeechRoutes(
      async () => ({
        text: "Yalnız bulut ses izniyle çalıştı.",
        language: "tr",
        model: "whisper-large-v3-turbo",
      }),
      async () => true,
    ),
    { prefix: "/v1/speech" },
  );
  const response = await app.inject({
    method: "POST",
    url: "/v1/speech/transcriptions?language=tr",
    headers: { "content-type": "audio/mp4" },
    payload: Buffer.alloc(512, 1),
  });

  assert.equal(response.statusCode, 200);
  await app.close();
});

test("speech telemetry contains metrics only", () => {
  const telemetry = buildSpeechTelemetry({
    bytes: 512,
    model: "whisper-large-v3-turbo",
    resultCode: "speech_not_detected",
    startedAtMs: Date.now() - 10,
  });

  assert.equal(telemetry.event, "speech.transcription");
  assert.equal(telemetry.bytes, 512);
  assert.equal(telemetry.model, "whisper-large-v3-turbo");
  assert.equal(telemetry.resultCode, "speech_not_detected");
  assert.ok(telemetry.durationMs >= 0);
  assert.equal("text" in telemetry, false);
  assert.equal("audio" in telemetry, false);
  assert.equal("userId" in telemetry, false);
  assert.equal("error" in telemetry, false);
});
