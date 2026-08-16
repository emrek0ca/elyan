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
  // MODEL POLİTİKASI: yalnız gpt. gpt DIŞI bir yapılandırma değeri (burada
  // qwen) sessizce yok sayılıp gpt varsayılanına düşer — böylece bayat bir env
  // satırı model seçimini bir daha ele geçiremez (canlı: ELYAN_SHARED_BRAIN_MODEL
  // kodun gpt-oss-120b niyetini llama-3.1-8b ile eziyordu).
  assert.equal(catalog.fallbackModel, "openai/gpt-oss-120b");
  assert.deepEqual(catalog.defaultModelByWorkload, {
    // Yönlendirme/niyet KATI JSON ister → reasoning-dışı model. gpt-oss gizli
    // düşünme turunda bütçeyi tüketip JSON'u boş bırakıyordu (canlı 2026-08-08).
    intent: "llama-3.1-8b-instant",
    fast_route: "llama-3.1-8b-instant",
    mobile_chat_fast: "openai/gpt-oss-20b",
    mobile_chat_balanced: "openai/gpt-oss-20b",
    mobile_chat_deep_refine: "openai/gpt-oss-120b",
    // KATI-JSON ŞERİDİ. Belge analizi şemaya uyan JSON döndürüyor; canlıda
    // (2026-08-13, görev a4924a76 — "3.sınıf matematik PDF yaz") bu iş yükünde
    // gpt-oss-20b ve qwen ikisi de 400 json_validate_failed verdi ve PDF hiç
    // üretilemedi. Şerit reasoning-DIŞI modelde kalır.
    document_analysis: "llama-3.1-8b-instant",
    document_generate: "openai/gpt-oss-120b",
    table_generate: "openai/gpt-oss-120b",
    image_analyze: "qwen/qwen3.6-27b",
    // Masaüstü plan JSON'u reasoning gpt-oss yerine katı-JSON şeridini kullanır.
    planning: "llama-3.1-8b-instant",
    // Public research yolları kalite-öncelikli: büyük reasoning modelinde.
    public_research: "openai/gpt-oss-120b",
    public_deep_research: "openai/gpt-oss-120b",
    public_quantum_research: "openai/gpt-oss-120b",
    desktop_handoff: "openai/gpt-oss-20b",
    vision_reasoning: "qwen/qwen3.6-27b",
  });
  assert.deepEqual(catalog.models, [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.6-27b",
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

  // qwen politika dışı olduğu için fallback gpt varsayılanına düşer; primary
  // ile aynı olduğundan çözücü bir sonraki farklı modele geçer.
  assert.equal(fallback, "openai/gpt-oss-20b");
});

test("resolveGroqFallbackModel backs fast chat up with the reasoning model", () => {
  // mobile_chat_fast hız-kritik yol olarak 20b'de başlar; 20b düşerse
  // qwen'e değil daha güvenilir reasoning modeline yükselir.
  const fallback = resolveGroqFallbackModel(
    {
      GROQ_REASONING_MODEL: "openai/gpt-oss-120b",
      GROQ_FAST_MODEL: "openai/gpt-oss-20b",
      GROQ_FALLBACK_MODEL: "qwen/qwen3.6-27b",
    },
    "openai/gpt-oss-20b",
    "mobile_chat_fast",
  );

  assert.equal(fallback, "openai/gpt-oss-120b");
});

test("resolveGroqFallbackModel does not cross the structured JSON lane", () => {
  const fallback = resolveGroqFallbackModel(
    {
      GROQ_REASONING_MODEL: "openai/gpt-oss-120b",
      GROQ_FAST_MODEL: "openai/gpt-oss-20b",
      GROQ_FALLBACK_MODEL: "qwen/qwen3.6-27b",
    },
    "qwen/qwen3.6-27b",
    "document_analysis",
  );

  assert.equal(fallback, null);
});
