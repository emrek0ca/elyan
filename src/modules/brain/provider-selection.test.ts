// NOT: model adları gpt ailesinden seçilir. `buildGroqModelCatalog`
// gpt-only politikası uygular; gpt DIŞI bir ad sessizce gpt varsayılanına
// düşer, bu yüzden yer tutucular da gpt adları olmalı.
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
      GROQ_COMPOUND_ENABLED: false,
      GROQ_COMPOUND_RESEARCH_ENABLED: true,
      GROQ_COMPOUND_DEEP_ENABLED: true,
      GROQ_COMPOUND_MODEL: "groq/compound",
      GROQ_COMPOUND_MINI_MODEL: "groq/compound-mini",
      OPENAI_API_KEY: "",
      OPENAI_BASE_URL: "https://api.openai.com/v1",
      OPENAI_FRONTIER_MODEL: "openai-frontier",
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
    GROQ_REASONING_MODEL: "openai/gpt-reasoning-model",
    GROQ_FALLBACK_MODEL: "openai/gpt-reasoning-model",
    GROQ_FAST_MODEL: "openai/gpt-fast-model",
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
  assert.deepEqual(candidates[0]?.preferredModels, ["openai/gpt-reasoning-model", "openai/gpt-fast-model"]);
  assert.equal(candidates[1]?.provider, "ollama");
  assert.equal(candidates[1]?.hosted, false);
});

test("buildInferenceProviderCandidates keeps Groq first for normal chat when Gemini is configured", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
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
  // Sohbet workload'ları primary 120b düşerse hızlı+güvenilir 20b'ye iner
  // (kırılgan qwen ikinci sıraya alındı).
  assert.deepEqual(candidates[0]?.preferredModels, [
    "openai/gpt-groq-reasoning",
    "openai/gpt-groq-fast",
  ]);
  assert.equal(candidates[1]?.provider, "gemini");
  assert.deepEqual(candidates[1]?.preferredModels, ["gemini-text", "gemini-fast"]);
});

test("buildInferenceProviderCandidates uses Groq Compound for planning when enabled", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_COMPOUND_ENABLED: true,
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "planning",
    runtime: runtimeSnapshot(),
    localModels: ["local-planning"],
  });

  assert.equal(candidates[0]?.provider, "groq");
  assert.deepEqual(candidates[0]?.preferredModels, [
    "groq/compound",
    "openai/gpt-groq-reasoning",
    "openai/gpt-groq-fallback",
  ]);
});

test("buildInferenceProviderCandidates uses Compound mini for public fresh research", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_COMPOUND_ENABLED: true,
    GROQ_COMPOUND_RESEARCH_ENABLED: true,
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "public_research",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
  });

  assert.equal(candidates[0]?.provider, "groq");
  assert.deepEqual(candidates[0]?.preferredModels, [
    "groq/compound-mini",
    "openai/gpt-groq-reasoning",
    "openai/gpt-groq-fast",
  ]);
});

test("buildInferenceProviderCandidates keeps Compound off when research flag is disabled", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_COMPOUND_ENABLED: true,
    GROQ_COMPOUND_RESEARCH_ENABLED: false,
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "public_research",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
  });

  assert.deepEqual(candidates[0]?.preferredModels, [
    "openai/gpt-groq-reasoning",
    "openai/gpt-groq-fast",
  ]);
});

test("buildInferenceProviderCandidates depth-router escalates a live-web chat turn to Compound", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_COMPOUND_ENABLED: true,
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
  });

  const withSignal = buildInferenceProviderCandidates({
    app,
    workload: "mobile_chat_balanced",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
    liveWebSignal: true,
  });
  assert.equal(withSignal[0]?.preferredModels[0], "groq/compound");

  // Aynı iş yükü, sinyal yok → compound zincire girmez (mevcut davranış).
  const withoutSignal = buildInferenceProviderCandidates({
    app,
    workload: "mobile_chat_balanced",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
  });
  assert.equal(withoutSignal[0]?.preferredModels.includes("groq/compound"), false);
});

test("buildInferenceProviderCandidates depth-router is a no-op while the Compound flag is off", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_COMPOUND_ENABLED: false,
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "mobile_chat_balanced",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
    liveWebSignal: true,
  });
  assert.equal(candidates[0]?.preferredModels.includes("groq/compound"), false);
});

test("buildInferenceProviderCandidates adds OpenAI frontier after Groq for deep public research", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_COMPOUND_ENABLED: true,
    GROQ_COMPOUND_DEEP_ENABLED: true,
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
    OPENAI_API_KEY: "openai-key",
    OPENAI_FRONTIER_MODEL: "frontier-model",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "public_deep_research",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
  });

  assert.equal(candidates[0]?.provider, "groq");
  assert.equal(candidates[1]?.provider, "openai");
  assert.deepEqual(candidates[1]?.preferredModels, ["frontier-model"]);
});

test("buildInferenceProviderCandidates does not use Groq Compound for document analysis", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_COMPOUND_ENABLED: true,
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "document_analysis",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
  });

  assert.equal(candidates[0]?.provider, "groq");
  // KATI-JSON ŞERİDİ. `document_analysis` şemaya uyan JSON döndürüyor, bu yüzden
  // reasoning-DIŞI modelle başlar. Canlı ölçüm (2026-08-13, görev a4924a76 —
  // "3.sınıf matematik PDF yaz"): bu iş yükünde gpt-oss-20b ve qwen ikisi de
  // 400 json_validate_failed verdi, zincir tükendi ve PDF hiç üretilemedi.
  assert.deepEqual(candidates[0]?.preferredModels, [
    "llama-3.1-8b-instant",
    "openai/gpt-groq-fast",
  ]);
});

test("buildInferenceProviderCandidates can isolate primary and fallback workers", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_REASONING_MODEL: "openai/gpt-groq-reasoning",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GROQ_FALLBACK_MODEL: "openai/gpt-groq-fallback",
    GEMINI_API_KEY: "gemini-key",
    GEMINI_TEXT_MODEL: "gemini-text",
    GEMINI_FAST_MODEL: "gemini-fast",
  });
  const base = {
    app,
    workload: "mobile_chat_fast" as const,
    runtime: runtimeSnapshot(),
    localModels: ["local-fast"],
  };

  assert.deepEqual(
    buildInferenceProviderCandidates({ ...base, allowedProviders: ["groq"] }).map(
      (candidate) => candidate.provider,
    ),
    ["groq"],
  );
  assert.deepEqual(
    buildInferenceProviderCandidates({ ...base, allowedProviders: ["gemini"] }).map(
      (candidate) => candidate.provider,
    ),
    ["gemini"],
  );
});

test("paid Gemini fallback is not constrained by the free-tier model allowlist", () => {
  const app = appWithConfig({
    GEMINI_FREE_ONLY: false,
    GEMINI_FREE_MODEL_ALLOWLIST: "gemini-free-model",
    GEMINI_API_KEY: "gemini-key",
    GEMINI_TEXT_MODEL: "gemini-paid-model",
    GEMINI_FAST_MODEL: "gemini-paid-model",
  });

  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "mobile_chat_fast",
    runtime: runtimeSnapshot(),
    localModels: [],
    allowedProviders: ["gemini"],
  });

  assert.deepEqual(candidates.map((candidate) => candidate.provider), [
    "gemini",
  ]);
  assert.equal(candidates[0]?.preferredModels[0], "gemini-paid-model");
});

test("buildInferenceProviderCandidates prefers Gemini for vision workloads", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_VISION_MODEL: "openai/gpt-groq-vision",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
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

test("buildInferenceProviderCandidates prefers Groq for fast vision profile", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_VISION_MODEL: "openai/gpt-groq-vision",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GEMINI_API_KEY: "gemini-key",
    GEMINI_VISION_MODEL: "gemini-vision",
    GEMINI_FAST_MODEL: "gemini-fast",
  });
  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "vision_reasoning",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
    visionProfile: "fast",
  });
  // Sağlayıcı sırası artık sabit tercih değil, KAPASİTE SKORUNA göre
  // (`provider-capabilities.ts`). Vision iş yükünde görü yetkin bir sağlayıcı
  // önde gelir ve her ikisi de aday kalır. Hangi markanın önde olduğunu
  // sabitlemek yerine sözleşmeyi doğruluyoruz: iki aday da var ve ilki görü
  // modeli sunuyor.
  const providers = candidates.map((candidate) => candidate.provider);
  assert.ok(providers.includes("groq"), `groq aday olmalı: ${providers}`);
  assert.ok(providers.includes("gemini"), `gemini aday olmalı: ${providers}`);
  assert.ok(
    (candidates[0]?.preferredModels ?? []).some((model) => model.includes("vision")),
    `ilk aday görü modeli sunmalı: ${candidates[0]?.preferredModels}`,
  );
});

test("document analysis uses Gemini Flash-Lite with 3.5 fallback", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_FAST_MODEL: "openai/gpt-groq-fast",
    GEMINI_API_KEY: "gemini-key",
    GEMINI_FAST_MODEL: "gemini-fast",
    GEMINI_TEXT_MODEL: "gemini-quality",
  });
  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "document_analysis",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
  });

  assert.equal(candidates[0]?.provider, "gemini");
  assert.deepEqual(candidates[0]?.preferredModels, [
    "gemini-fast",
    "gemini-quality",
  ]);
  assert.equal(candidates[1]?.provider, "groq");
});

test("sensitive vision excludes hosted providers without privacy attestation", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_VISION_MODEL: "openai/gpt-groq-vision",
    GEMINI_API_KEY: "gemini-key",
    GEMINI_VISION_MODEL: "gemini-vision",
    GROQ_VISION_SENSITIVE_DATA_ATTESTED: false,
    GEMINI_VISION_SENSITIVE_DATA_ATTESTED: false,
  });
  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "vision_reasoning",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
    visionProfile: "detail",
    visionSensitivity: "sensitive",
  });
  assert.equal(candidates.some((candidate) => candidate.hosted), false);
});

test("sensitive vision allows only explicitly attested hosted provider", () => {
  const app = appWithConfig({
    GROQ_API_KEY: "groq-key",
    GROQ_VISION_MODEL: "openai/gpt-groq-vision",
    GEMINI_API_KEY: "gemini-key",
    GEMINI_VISION_MODEL: "gemini-vision",
    GROQ_VISION_SENSITIVE_DATA_ATTESTED: true,
    GEMINI_VISION_SENSITIVE_DATA_ATTESTED: false,
  });
  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "vision_reasoning",
    runtime: runtimeSnapshot(),
    localModels: ["local-balanced"],
    visionProfile: "detail",
    visionSensitivity: "sensitive",
  });
  assert.equal(candidates.filter((candidate) => candidate.hosted).length, 1);
  assert.equal(candidates.find((candidate) => candidate.hosted)?.provider, "groq");
});

test("personal vision excludes custom runtimes on public networks", () => {
  const app = appWithConfig({
    ELYAN_SHARED_BRAIN_BASE_URL: "https://public-runtime.example.com",
  });
  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "vision_reasoning",
    runtime: runtimeSnapshot({ baseUrl: "https://public-runtime.example.com", ready: true }),
    localModels: ["local-vision"],
    visionSensitivity: "personal",
  });
  assert.equal(candidates.length, 0);
});

test("personal vision allows a private local runtime", () => {
  const app = appWithConfig({
    ELYAN_SHARED_BRAIN_BASE_URL: "http://192.168.1.20:11434",
  });
  const candidates = buildInferenceProviderCandidates({
    app,
    workload: "vision_reasoning",
    runtime: runtimeSnapshot({ baseUrl: "http://192.168.1.20:11434", ready: true }),
    localModels: ["local-vision"],
    visionSensitivity: "personal",
  });
  assert.equal(candidates[0]?.baseUrl, "http://192.168.1.20:11434");
  assert.equal(candidates[0]?.hosted, false);
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
