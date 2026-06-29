import assert from "node:assert/strict";
import test from "node:test";
import { resolveSharedBrainModel } from "./model-resolution.js";

test("resolveSharedBrainModel skips Ollama model discovery when Groq is primary", async () => {
  const originalFetch = globalThis.fetch;
  let fetchCalled = false;

  globalThis.fetch = async () => {
    fetchCalled = true;
    return new Response("unexpected", { status: 500 });
  };

  const app = {
    config: {
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
      ELYAN_SHARED_BRAIN_FAST_MODEL: "qwen2.5-coder:3b",
      ELYAN_SHARED_BRAIN_BALANCED_MODEL: "qwen2.5:7b-instruct-q5_K_M",
      ELYAN_SHARED_BRAIN_PLANNING_MODEL: "qwen2.5:7b-instruct-q5_K_M",
      GROQ_API_KEY: "groq-key",
      GROQ_REASONING_MODEL: "openai/gpt-oss-120b",
      GROQ_FAST_MODEL: "openai/gpt-oss-20b",
      GROQ_FALLBACK_MODEL: "qwen/qwen3.6-27b",
      OPENAI_API_KEY: "",
      ANTHROPIC_API_KEY: "",
      OPENROUTER_API_KEY: "",
    },
  };

  try {
    const result = await resolveSharedBrainModel(app as never, {
      userId: "user-1",
      workload: "mobile_chat_fast",
      runtime: {
        provider: "ollama",
        baseUrl: "http://127.0.0.1:11434",
        ready: true,
        checkedAt: new Date("2030-01-01T00:00:00.000Z"),
        source: "probe",
      },
      selection: {
        readyModels: [],
        activeSharedModel: null,
        rollbackSharedModel: null,
        warmupJob: null,
        activeUserModel: null,
        baseModel: "llama3.2",
        activeAdapter: "base",
        trainingPlan: null,
      },
    });

    assert.equal(fetchCalled, false);
    assert.equal(result.configuredBaseModel, "openai/gpt-oss-120b");
    assert.equal(result.resolvedBaseModel, "openai/gpt-oss-20b");
    assert.equal(result.resolvedFallbackModel, "qwen/qwen3.6-27b");
    assert.deepEqual(result.availableModels, [
      "openai/gpt-oss-120b",
      "openai/gpt-oss-20b",
      "qwen/qwen3.6-27b",
      "meta-llama/llama-4-scout-17b-16e-instruct",
    ]);
    assert.equal(result.resolvedBaseModelSource, "configured");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
