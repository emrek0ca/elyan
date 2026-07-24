import assert from "node:assert/strict";
import test from "node:test";
import {
  buildGroqModelCatalog,
  resolveGroqFallbackModel,
} from "./groq-models.js";

test("buildGroqModelCatalog keeps the single Elyan brain on the configured Groq models", () => {
  const catalog = buildGroqModelCatalog({
    GROQ_REASONING_MODEL: "openai/gpt-oss-120b",
    GROQ_FAST_MODEL: "openai/gpt-oss-20b",
    GROQ_FALLBACK_MODEL: "qwen/qwen3.6-27b",
  });

  assert.equal(catalog.reasoningModel, "openai/gpt-oss-120b");
  assert.equal(catalog.fastModel, "openai/gpt-oss-20b");
  assert.equal(catalog.fallbackModel, "qwen/qwen3.6-27b");
  assert.deepEqual(catalog.defaultModelByWorkload, {
    intent: "openai/gpt-oss-20b",
    fast_route: "openai/gpt-oss-20b",
    mobile_chat_fast: "openai/gpt-oss-120b",
    mobile_chat_balanced: "openai/gpt-oss-120b",
    mobile_chat_deep_refine: "openai/gpt-oss-120b",
    document_analysis: "qwen/qwen3.6-27b",
    document_generate: "openai/gpt-oss-120b",
    table_generate: "openai/gpt-oss-120b",
    image_analyze: "meta-llama/llama-4-scout-17b-16e-instruct",
    planning: "openai/gpt-oss-120b",
    // Public research yolları kalite-öncelikli: büyük reasoning modelinde.
    public_research: "openai/gpt-oss-120b",
    public_deep_research: "openai/gpt-oss-120b",
    public_quantum_research: "openai/gpt-oss-120b",
    desktop_handoff: "openai/gpt-oss-20b",
    vision_reasoning: "meta-llama/llama-4-scout-17b-16e-instruct",
  });
  assert.deepEqual(catalog.models, [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
  ]);
});

test("resolveGroqFallbackModel returns a distinct backup model when primary fails", () => {
  const fallback = resolveGroqFallbackModel(
    {
      GROQ_REASONING_MODEL: "openai/gpt-oss-120b",
      GROQ_FAST_MODEL: "openai/gpt-oss-20b",
      GROQ_FALLBACK_MODEL: "qwen/qwen3.6-27b",
    },
    "openai/gpt-oss-120b",
  );

  assert.equal(fallback, "qwen/qwen3.6-27b");
});

test("resolveGroqFallbackModel drops chat failover to the fast reliable model, not flaky qwen", () => {
  // mobile_chat_fast artık 120b primary; düşerse hızlı+güvenilir 20b'ye insin
  // (qwen json_validate_failed 400'leriyle kırılgan, ikinci sıraya alındı).
  const fallback = resolveGroqFallbackModel(
    {
      GROQ_REASONING_MODEL: "openai/gpt-oss-120b",
      GROQ_FAST_MODEL: "openai/gpt-oss-20b",
      GROQ_FALLBACK_MODEL: "qwen/qwen3.6-27b",
    },
    "openai/gpt-oss-120b",
    "mobile_chat_fast",
  );

  assert.equal(fallback, "openai/gpt-oss-20b");
});

test("resolveGroqFallbackModel prefers the fast Groq model for document analysis failover", () => {
  const fallback = resolveGroqFallbackModel(
    {
      GROQ_REASONING_MODEL: "openai/gpt-oss-120b",
      GROQ_FAST_MODEL: "openai/gpt-oss-20b",
      GROQ_FALLBACK_MODEL: "qwen/qwen3.6-27b",
    },
    "qwen/qwen3.6-27b",
    "document_analysis",
  );

  assert.equal(fallback, "openai/gpt-oss-20b");
});
