import test from "node:test";
import assert from "node:assert/strict";
import { getBaseUrlReachability, getDatabaseReachability, loadEnv } from "./env.js";

test("loadEnv derives iyzico public base url from app base url", () => {
  const env = loadEnv({
    NODE_ENV: "development",
    HOST: "0.0.0.0",
    PORT: "4000",
    LOG_LEVEL: "silent",
    APP_BASE_URL: "http://192.168.1.15:4000",
    DATABASE_URL: "postgres://postgres:postgres@127.0.0.1:5432/elyan_backend",
    JWT_SECRET: "change-me-please-1234-at-least-32",
    ACCESS_TOKEN_TTL: "15m",
    REFRESH_TOKEN_TTL: "30d",
    RUNTIME_TOKEN_TTL: "12h",
    PAIRING_TTL_MINUTES: "10",
    RUNTIME_SECRET_PEPPER: "change-me-runtime-pepper-1234",
    CORS_ORIGIN: "*",
  });

  assert.equal(env.IYZICO_PUBLIC_BASE_URL, "http://192.168.1.15:4000");
  assert.equal(env.REALTIME_REDIS_FANOUT_ENABLED, true);
  assert.equal(env.REALTIME_REDIS_CHANNEL_PREFIX, "elyan:realtime");
  assert.equal(env.REALTIME_EVENT_RETENTION_HOURS, 48);
  assert.equal(env.SSE_MAX_STREAMS_PER_USER, 4);
  assert.equal(env.SSE_REPLAY_LIMIT, 500);
  assert.equal(env.SSE_HEARTBEAT_MS, 15_000);
  assert.equal(env.GROQ_REASONING_MODEL, "openai/gpt-oss-120b");
  assert.equal(env.GROQ_FAST_MODEL, "openai/gpt-oss-20b");
  assert.equal(env.GROQ_FALLBACK_MODEL, "qwen/qwen3.6-27b");
  assert.equal(env.GROQ_BASE_URL, "https://api.groq.com/openai/v1");
  assert.equal(env.GEMINI_BASE_URL, "https://generativelanguage.googleapis.com/v1beta/openai");
  assert.equal(env.GEMINI_INTERACTIONS_BASE_URL, "https://generativelanguage.googleapis.com/v1beta");
  assert.equal(env.GEMINI_TEXT_MODEL, "gemini-3.5-flash");
  assert.equal(env.GEMINI_FAST_MODEL, "gemini-3.1-flash-lite");
  assert.equal(env.GEMINI_REASONING_MODEL, "gemini-3.5-flash");
  assert.equal(env.GEMINI_VISION_MODEL, "gemini-3.5-flash");
  assert.equal(env.GEMINI_IMAGE_MODEL, "gemini-3.1-flash-image");
  assert.equal(env.GEMINI_IMAGE_PRO_MODEL, "gemini-3-pro-image-preview");
  assert.equal(env.GEMINI_IMAGE_SIZE, "2K");
  assert.equal(env.ELYAN_SHARED_BRAIN_FAST_MODEL, "qwen2.5-coder:3b");
  assert.equal(env.ELYAN_SHARED_BRAIN_BALANCED_MODEL, "qwen2.5:7b-instruct-q5_K_M");
  assert.equal(env.ELYAN_SHARED_BRAIN_PLANNING_MODEL, "qwen2.5:7b-instruct-q5_K_M");
  assert.equal(env.ELYAN_WORLD_CONTEXT_PACKETS_ENABLED, true);
  assert.equal(env.ELYAN_MODEL_CANARY_ENABLED, false);
  assert.equal(env.ELYAN_MODEL_PRIMARY_ENABLED, false);
});

test("getBaseUrlReachability flags loopback origins as unreachable for other devices", () => {
  const loopback = getBaseUrlReachability({
    HOST: "0.0.0.0",
    PORT: 4000,
    APP_BASE_URL: "http://127.0.0.1:4000",
  });
  const lan = getBaseUrlReachability({
    HOST: "0.0.0.0",
    PORT: 4000,
    APP_BASE_URL: "http://192.168.1.15:4000",
  });

  assert.equal(loopback.externalClientsCanReachAdvertisedBaseUrl, false);
  assert.match(loopback.warning ?? "", /local-only host/i);
  assert.equal(lan.externalClientsCanReachAdvertisedBaseUrl, true);
  assert.equal(lan.warning, null);
});

test("getDatabaseReachability explains when compose needs a database host override", () => {
  const hostRun = getDatabaseReachability({
    DATABASE_URL: "postgres://postgres:postgres@127.0.0.1:5432/elyan_backend",
  });
  const compose = getDatabaseReachability({
    DATABASE_URL: "postgres://postgres:postgres@postgres:5432/elyan_backend",
  });

  assert.equal(hostRun.localOnlyHost, true);
  assert.match(hostRun.warning ?? "", /docker-compose backend container/i);
  assert.equal(compose.localOnlyHost, false);
  assert.equal(compose.connectionUrlHost, "postgres");
  assert.equal(compose.warning, null);
});
