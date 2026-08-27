import assert from "node:assert/strict";
import test from "node:test";
import {
  buildGroqCompoundRequestExtensions,
  isGroqCompoundModel,
  resolveGroqCompoundModel,
  shouldUseGroqCompound,
} from "./groq-compound.js";

const baseConfig = {
  GROQ_COMPOUND_MODEL: "groq/compound",
  GROQ_COMPOUND_MINI_MODEL: "groq/compound-mini",
} as const;

test("isGroqCompoundModel detects compound model names", () => {
  assert.equal(isGroqCompoundModel("groq/compound"), true);
  assert.equal(isGroqCompoundModel("groq/compound-mini"), true);
  assert.equal(isGroqCompoundModel("openai/gpt-oss-120b"), false);
  assert.equal(isGroqCompoundModel(""), false);
});

// KRİTİK GÜVENLİK — bayrak KAPALIYKEN derinlik sinyali hiçbir şeyi değiştirmez.
// Compound wiring'i açılana kadar sıfır davranış değişikliği garantisi.
test("shouldUseGroqCompound stays off when the master flag is disabled, even with a live-web signal", () => {
  assert.equal(
    shouldUseGroqCompound({
      config: { ...baseConfig, GROQ_COMPOUND_ENABLED: false },
      workload: "mobile_chat_balanced",
      liveWebSignal: true,
    }),
    false,
  );
});

// Derinlik-router — bayrak açıkken, UYGUN OLMAYAN bir iş yükünde (balanced)
// canlı-web sinyali compound'u tetikler. "aç + derinlik-router"ın özü.
test("a live-web signal cannot make a non-eligible workload eligible for Compound", () => {
  // DAVRANIŞ DEĞİŞİKLİĞİ (ölçümle): sinyal eskiden her iş yükünü compound'a
  // yönlendiriyordu. Yerel koşuda sıradan bir sohbet turu ("Şu an saat kaç?")
  // canlı-web sinyali taşıdığı için compound'a gitti, iki kez boş dönüş
  // (503) verdi ve turu uzattı — o turun araç döngüsüne değil yalnız saate
  // ihtiyacı vardı. Sinyal artık uygun iş yükleri içinde bir önceliktir,
  // uygunluk kapısının kendisi değil.
  const config = {
    ...baseConfig,
    GROQ_COMPOUND_ENABLED: true,
  };
  assert.equal(
    shouldUseGroqCompound({
      config,
      workload: "mobile_chat_balanced",
      liveWebSignal: true,
    }),
    false,
  );
  assert.equal(
    shouldUseGroqCompound({ config, workload: "mobile_chat_balanced" }),
    false,
  );
});

// Uygun iş yükleri sinyal olmadan da compound kullanır (mevcut davranış korunur)
// — deep iş yükleri için DEEP alt-bayrağı da gerekir.
test("shouldUseGroqCompound keeps eligible workloads on compound without a signal", () => {
  const config = {
    ...baseConfig,
    GROQ_COMPOUND_ENABLED: true,
    GROQ_COMPOUND_DEEP_ENABLED: true,
  };
  assert.equal(
    shouldUseGroqCompound({ config, workload: "planning" }),
    true,
  );
  assert.equal(
    shouldUseGroqCompound({ config, workload: "mobile_chat_deep_refine" }),
    true,
  );
});

// Alt-bayraklar iş yükü bazında hâlâ geçerli — canlı-web sinyali onları EZMEZ.
test("shouldUseGroqCompound respects per-workload sub-flags over the live-web signal", () => {
  assert.equal(
    shouldUseGroqCompound({
      config: {
        ...baseConfig,
        GROQ_COMPOUND_ENABLED: true,
        GROQ_COMPOUND_RESEARCH_ENABLED: false,
      },
      workload: "public_research",
      liveWebSignal: true,
    }),
    false,
  );
  assert.equal(
    shouldUseGroqCompound({
      config: {
        ...baseConfig,
        GROQ_COMPOUND_ENABLED: true,
        GROQ_COMPOUND_DEEP_ENABLED: false,
      },
      workload: "planning",
      liveWebSignal: true,
    }),
    false,
  );
});

test("resolveGroqCompoundModel picks mini for fast paths and full compound for deep paths", () => {
  assert.equal(
    resolveGroqCompoundModel(baseConfig, "mobile_chat_fast"),
    "groq/compound-mini",
  );
  assert.equal(
    resolveGroqCompoundModel(baseConfig, "mobile_chat_balanced"),
    "groq/compound",
  );
  assert.equal(resolveGroqCompoundModel(baseConfig, "planning"), "groq/compound");
});

test("ISO ülke kodu search_settings'e girmez, ülke adı girer", () => {
  // Ölçüm: `tr` → HTTP 400 "invalid country code: tr", `turkey` → 200.
  // ISO kodu göndermek aramayı yerelleştirmiyor, HER compound isteğini
  // düşürüyor: tüm araştırma yolu sessizce fallback'e iniyor.
  const base = {
    GROQ_COMPOUND_ENABLED: true,
    GROQ_COMPOUND_RESEARCH_ENABLED: true,
    GROQ_COMPOUND_DEEP_ENABLED: true,
    GROQ_COMPOUND_MODEL: "groq/compound",
    GROQ_COMPOUND_MINI_MODEL: "groq/compound-mini",
  } as Parameters<typeof buildGroqCompoundRequestExtensions>[0];

  assert.deepEqual(
    buildGroqCompoundRequestExtensions(
      { ...base, GROQ_COMPOUND_SEARCH_COUNTRY: "tr" },
      "groq/compound",
    ),
    {},
    "iki harfli kod düşürülmeli",
  );
  assert.deepEqual(
    buildGroqCompoundRequestExtensions(
      { ...base, GROQ_COMPOUND_SEARCH_COUNTRY: "turkey" },
      "groq/compound",
    ),
    { search_settings: { country: "turkey" } },
  );
});
