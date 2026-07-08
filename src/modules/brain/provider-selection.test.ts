import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import {
  buildInferenceProviderCandidates,
  buildProviderHeaders,
  getConfiguredProviderApiKey,
} from "./provider-selection.js";
import type { SharedBrainRuntimeSnapshot } from "./runtime.js";

function appWithConfig(config: Record<string, unknown>): FastifyInstance {
  return {
    config: {
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
      ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER: undefined,
      ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL: undefined,
      ELYAN_SHARED_BRAIN_MODEL: "local-balanced",
      ELYAN_SHARED_BRAIN_FAST_MODEL: "local-fast",
      ELYAN_SHARED_BRAIN_BALANCED_MODEL: "local-balanced",
      ELYAN_SHARED_BRAIN_PLANNING_MODEL: "local-planning",
      GROQ_API_KEY: "",
      GROQ_BASE_URL: "https://api.groq.com/openai/v1",
      GEMINI_API_KEY: "",
      GEMINI_BASE_URL: "https://generativelanguage.googleapis.com/v1beta/openai",
      ...config,
    },
  } as unknown as FastifyInstance;
}

function runtimeSnapshot(
  override: Partial<SharedBrainRuntimeSnapshot> = {},
): SharedBrainRuntimeSnapshot {
  return {
    provider: "ollama",
    baseUrl: "http://127.0.0.1:11434",
    ready: false,
    checkedAt: new Date("2026-01-01T00:00:00.000Z"),
    source: "config",
    ...override,
  };
}

test("getConfiguredProviderApiKey selects the first non-empty Groq key", () => {
  const app = appWithConfig({
    GROQ_API_KEY: " , first-key , second-key ",
  });

  assert.equal(getConfiguredProviderApiKey(app, "groq"), "first-key");
});

test("getConfiguredProviderApiKey reads Gemini key without pooling", () => {
  const app = appWithConfig({
    GEMINI_API_KEY: " gemini-key ",
  });

  assert.equal(getConfiguredProviderApiKey(app, "gemini"), "gemini-key");
});

test("buildProviderHeaders adds Groq bearer auth without leaking pooled keys", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "primary-key, secondary-key",
  });

  assert.deepEqual(buildProviderHeaders(app, "groq"), {
    "content-type": "application/json",
    Authorization: "Bearer primary-key",
  });
  assert.deepEqual(buildProviderHeaders(app, "ollama"), {
    "content-type": "application/json",
  });
});

test("buildProviderHeaders adds Gemini bearer auth", () => {
  const app = appWithConfig({
    GEMINI_API_KEY: "gemini-key",
  });

  assert.deepEqual(buildProviderHeaders(app, "gemini"), {
    "content-type": "application/json",
    Authorization: "Bearer gemini-key",
  });
});

test("buildInferenceProviderCandidates prefers hosted Groq when configured", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_REASONING_MODEL: "reasoning-model",
    GROQ_FALLBACK_MODEL: "reasoning-model",
    GROQ_FAST_MODEL: "fast-model",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "mobile_chat_balanced",
    runtime: runtimeSnapshot({ ready: true }),
    localModels: ["local-fast", "local-balanced"],
  });

  assert.equal(candidates[0]?.provider, "groq");
  assert.equal(candidates[0]?.hosted, true);
  assert.equal(candidates[0]?.baseUrl, "https://api.groq.com/openai/v1");
  assert.deepEqual(candidates[0]?.preferredModels, ["reasoning-model", "fast-model"]);
  assert.equal(candidates[1]?.provider, "ollama");
  assert.equal(candidates[1]?.hosted, false);
});

test("buildInferenceProviderCandidates keeps Groq first for normal chat when Gemini is configured", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_REASONING_MODEL: "groq-reasoning",
    GROQ_FAST_MODEL: "groq-fast",
    GROQ_FALLBACK_MODEL: "groq-fallback",
    GEMINI_API_KEY: "gemini-key",
    GEMINI_TEXT_MODEL: "gemini-text",
    GEMINI_FAST_MODEL: "gemini-fast",
    GEMINI_VISION_MODEL: "gemini-vision",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "mobile_chat_balanced",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
  });

  assert.equal(candidates[0]?.provider, "groq");
  assert.deepEqual(candidates[0]?.preferredModels, [
    "groq-reasoning",
    "groq-fallback",
  ]);
  assert.equal(candidates[1]?.provider, "gemini");
  assert.deepEqual(candidates[1]?.preferredModels, ["gemini-text", "gemini-fast"]);
});

test("buildInferenceProviderCandidates prefers Gemini for vision workloads", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_VISION_MODEL: "groq-vision",
    GROQ_FAST_MODEL: "groq-fast",
    GEMINI_API_KEY: "gemini-key",
    GEMINI_VISION_MODEL: "gemini-vision",
    GEMINI_FAST_MODEL: "gemini-fast",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "vision_reasoning",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
  });

  assert.equal(candidates[0]?.provider, "gemini");
  assert.deepEqual(candidates[0]?.preferredModels, [
    "gemini-vision",
    "gemini-fast",
  ]);
  assert.equal(candidates[1]?.provider, "groq");
});

test("buildInferenceProviderCandidates uses ready local runtime when hosted is unavailable", () => {
  const app = appWithConfig({
    ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
    ELYAN_SHARED_BRAIN_BASE_URL: "http://configured.local:11434",
    ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER: "vllm",
    ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL: "http://fallback.local:8000",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "planning",
    runtime: runtimeSnapshot({
      provider: "vllm",
      baseUrl: "http://ready.local:8000",
      ready: true,
      source: "probe",
    }),
    localModels: ["local-planning"],
  });

  assert.deepEqual(
    candidates.map((candidate) => ({
      provider: candidate.provider,
      baseUrl: candidate.baseUrl,
      hosted: candidate.hosted,
      preferredModels: candidate.preferredModels,
    })),
    [
      {
        provider: "vllm",
        baseUrl: "http://ready.local:8000",
        hosted: false,
        preferredModels: ["local-planning"],
      },
      {
        provider: "ollama",
        baseUrl: "http://configured.local:11434",
        hosted: false,
        preferredModels: ["local-planning"],
      },
      {
        provider: "vllm",
        baseUrl: "http://fallback.local:8000",
        hosted: false,
        preferredModels: ["local-planning"],
      },
    ],
  );
});
