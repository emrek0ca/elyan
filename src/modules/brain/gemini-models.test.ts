import assert from "node:assert/strict";
import test from "node:test";
import {
  buildGeminiModelCatalog,
  resolveGeminiFallbackModel,
} from "./gemini-models.js";
import {
  GEMINI_MODELS,
  isRetiredGeminiModel,
} from "../../config/model-policy.js";

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

test("a retired model in configuration falls back to the role default", () => {
  // ÖLÇÜLEN ARIZA (2026-08-28): `GEMINI_FAST_MODEL=gemini-2.5-flash-lite`.
  // O ad model politikasının kendi `retired` listesinde ve sağlayıcı ona 404
  // dönüyor (`gemini-2.5-flash` aynı uçta 200). Her yardımcı çağrı sessizce
  // `null` dönüyor, eylem-iddia kapısı tamamen kapalı kalıyordu.
  const catalog = buildGeminiModelCatalog({
    GEMINI_FAST_MODEL: "gemini-2.5-flash-lite",
  } as never);

  assert.notEqual(catalog.fastModel, "gemini-2.5-flash-lite");
  assert.equal(catalog.fastModel, GEMINI_MODELS.roles.fast_utility);
  assert.equal(isRetiredGeminiModel(catalog.fastModel), false);
});

test("a live configured model is still honoured", () => {
  // Kapı yalnız EMEKLİ adları eler; operatörün geçerli tercihi korunur.
  const live = GEMINI_MODELS.inventory.find(
    (model) => !isRetiredGeminiModel(model),
  );
  assert.ok(live, "envanterde canlı model yok");
  const catalog = buildGeminiModelCatalog({
    GEMINI_FAST_MODEL: live,
  } as never);
  assert.equal(catalog.fastModel, live);
});
