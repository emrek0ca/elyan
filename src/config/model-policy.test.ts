import assert from "node:assert/strict";
import test from "node:test";
import { buildGroqModelCatalog } from "../modules/brain/groq-models.js";
import {
  GEMINI_INVENTORY,
  GEMINI_MODELS,
  GEMINI_RETIRED,
  MODEL_INVENTORY,
  MODEL_POLICY,
  RETIRED_MODELS,
  isKnownModel,
  isRetiredModel,
  isRetiredGeminiModel,
} from "./model-policy.js";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

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


// ---------------------------------------------------------------------------
// GEMINI TARAFI. Canlı arıza (2026-08-22): `GEMINI_FAST_MODEL` emekli bir
// modele işaret ediyordu; metadata ucu 200, ÜRETİM 404. Her
// `callGeminiFreeStructured` null döndü ve uydurma kapısı her turda fail-open
// çalıştı — asistan "şarkıyı çalıyorum" dedi, hiçbir şey çalışmadı.
// ---------------------------------------------------------------------------

test("no gemini role points at a retired model", () => {
  for (const [role, model] of Object.entries(GEMINI_MODELS.roles)) {
    assert.ok(model, `${role} rolü boş`);
    assert.equal(isRetiredGeminiModel(model), false, `${role} emekli model: ${model}`);
    assert.ok(GEMINI_INVENTORY.has(model), `${role} envanter dışı: ${model}`);
  }
  for (const retired of GEMINI_RETIRED) {
    assert.equal(GEMINI_INVENTORY.has(retired), false, retired);
  }
});

test("no retired model name is hardcoded anywhere in src", () => {
  // Emekli ad kodda yeniden belirirse politika hiçbir şey ifade etmez. Bu kapı
  // masaüstündeki eşdeğerinin aynısıdır (test_model_policy_sync.py).
  const root = fileURLToPath(new URL("..", import.meta.url));
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(full);
        continue;
      }
      if (!entry.name.endsWith(".ts")) continue;
      // Politikanın kendisi ve bu test emekli adları taşımak ZORUNDA.
      if (entry.name === "model-policy.ts" || entry.name === "model-policy.test.ts") continue;
      const text = readFileSync(full, "utf8");
      for (const retired of [...RETIRED_MODELS, ...GEMINI_RETIRED]) {
        if (text.includes(retired)) offenders.push(`${entry.name}: ${retired}`);
      }
    }
  };
  walk(root);
  assert.deepEqual(offenders, [], `emekli model adı kodda geri geldi: ${offenders.join(", ")}`);
});
