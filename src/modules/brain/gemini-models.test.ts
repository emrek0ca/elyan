import assert from "node:assert/strict";
import test from "node:test";
import {
  buildGeminiModelCatalog,
  resolveGeminiFallbackModel,
} from "./gemini-models.js";

test("buildGeminiModelCatalog maps vision workloads to Gemini vision model", () => {
  const catalog = buildGeminiModelCatalog({
    GEMINI_TEXT_MODEL: "gemini-text",
    GEMINI_FAST_MODEL: "gemini-fast",
    GEMINI_REASONING_MODEL: "gemini-reasoning",
    GEMINI_VISION_MODEL: "gemini-vision",
    GEMINI_IMAGE_MODEL: "gemini-image",
  });

  assert.equal(catalog.defaultModelByWorkload.mobile_chat_fast, "gemini-fast");
  assert.equal(catalog.defaultModelByWorkload.mobile_chat_balanced, "gemini-text");
  assert.equal(catalog.defaultModelByWorkload.vision_reasoning, "gemini-vision");
  assert.equal(catalog.defaultModelByWorkload.image_analyze, "gemini-vision");
  assert.deepEqual(catalog.models, [
    "gemini-text",
    "gemini-fast",
    "gemini-reasoning",
    "gemini-vision",
    "gemini-image",
  ]);
});

test("resolveGeminiFallbackModel returns a distinct backup model", () => {
  const fallback = resolveGeminiFallbackModel(
    {
      GEMINI_TEXT_MODEL: "gemini-text",
      GEMINI_FAST_MODEL: "gemini-fast",
      GEMINI_REASONING_MODEL: "gemini-reasoning",
      GEMINI_VISION_MODEL: "gemini-vision",
    },
    "gemini-vision",
  );

  assert.equal(fallback, "gemini-fast");
});
