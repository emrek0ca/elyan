import assert from "node:assert/strict";
import test from "node:test";
import { buildGroqModelCatalog } from "../modules/brain/groq-models.js";
import {
  MODEL_INVENTORY,
  MODEL_POLICY,
  RETIRED_MODELS,
  isKnownModel,
  isRetiredModel,
} from "./model-policy.js";

// ---------------------------------------------------------------------------
// Sunucu ve masaüstü aynı model politikasını paylaşır. Canlı arıza
// (2026-08-21): iki taraf listeyi ayrı ayrı elle tutuyordu; masaüstünün yedek
// zincirinde sağlayıcının artık sunmadığı iki model kalmıştı ve birincil model
// geçersiz JSON döndürdüğünde OLMAYAN bir modele düşülüyordu.
// ---------------------------------------------------------------------------

test("model policy is internally consistent", () => {
  assert.equal(MODEL_POLICY.contract, "elyan.model_policy.v1");
  assert.ok(MODEL_INVENTORY.size > 0);
  for (const retired of RETIRED_MODELS) {
    assert.equal(
      MODEL_INVENTORY.has(retired),
      false,
      `emekli model envanterde duruyor: ${retired}`,
    );
  }
  for (const [role, models] of Object.entries(MODEL_POLICY.desktopRoles)) {
    assert.ok(models.length > 0, `${role} rolü boş`);
    for (const model of models) {
      assert.ok(isKnownModel(model), `${role} envanter dışı model: ${model}`);
      assert.equal(isRetiredModel(model), false, `${role} emekli model: ${model}`);
    }
  }
});

test("every default the server catalog resolves is a known, live model", () => {
  const catalog = buildGroqModelCatalog({});
  const selected = [
    catalog.reasoningModel,
    catalog.fastModel,
    catalog.structuredJsonModel,
    catalog.fallbackModel,
    catalog.visionModel,
    catalog.compoundModel,
    catalog.compoundMiniModel,
    ...Object.values(catalog.defaultModelByWorkload),
  ].filter((model): model is string => typeof model === "string" && model.length > 0);

  for (const model of selected) {
    assert.equal(
      isRetiredModel(model),
      false,
      `sunucu katalogu emekli model seçiyor: ${model}`,
    );
    assert.ok(
      isKnownModel(model),
      `sunucu katalogu envanter dışı model seçiyor: ${model}`,
    );
  }
});

test("a retired model configured through env never becomes the structured lane", () => {
  const retired = [...RETIRED_MODELS][0];
  assert.ok(retired, "emekli model listesi boş");
  const catalog = buildGroqModelCatalog({ GROQ_ROUTING_MODEL: retired });
  assert.equal(isRetiredModel(catalog.structuredJsonModel), false);
  assert.ok(isKnownModel(catalog.structuredJsonModel));
});
