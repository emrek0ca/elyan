import assert from "node:assert/strict";
import test from "node:test";
import {
  buildGroqCompoundRequestExtensions,
  extractGroqCompoundEvidence,
  isGroqCompoundModel,
  resolveGroqCompoundModel,
  shouldUseGroqCompound,
  withGroqCompoundGuidance,
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
    {
      compound_custom: {
        tools: { enabled_tools: ["web_search", "visit_website"] },
      },
    },
    "iki harfli kod düşürülmeli",
  );
  assert.deepEqual(
    buildGroqCompoundRequestExtensions(
      { ...base, GROQ_COMPOUND_SEARCH_COUNTRY: "turkey" },
      "groq/compound",
    ),
    {
      search_settings: { country: "turkey" },
      compound_custom: {
        tools: { enabled_tools: ["web_search", "visit_website"] },
      },
    },
  );
});

test("Compound guidance keeps system instructions first and the user message last", () => {
  const messages = withGroqCompoundGuidance(
    [
      { role: "system", content: "Base policy" },
      { role: "user", content: "Güncel altın fiyatı nedir?" },
      { role: "assistant", content: "stale assistant tail" },
      { role: "system", content: "Late policy" },
    ],
    "groq/compound-mini",
  );

  assert.equal(messages[0]?.role, "system");
  assert.match(messages[0]?.content ?? "", /Base policy/u);
  assert.match(messages[0]?.content ?? "", /Late policy/u);
  assert.equal(messages.at(-1)?.role, "user");
  assert.equal(messages.filter((message) => message.role === "system").length, 1);
});

test("Compound tools are bounded by model depth and computation need", () => {
  assert.deepEqual(
    buildGroqCompoundRequestExtensions(baseConfig, "groq/compound-mini"),
    {
      compound_custom: { tools: { enabled_tools: ["web_search"] } },
    },
  );
  assert.deepEqual(
    buildGroqCompoundRequestExtensions(baseConfig, "groq/compound", {
      requiresComputation: true,
    }),
    {
      compound_custom: {
        tools: {
          enabled_tools: ["web_search", "visit_website", "code_interpreter"],
        },
      },
    },
  );
});

test("Compound evidence parses string tool output and plain text query arguments", () => {
  const evidence = extractGroqCompoundEvidence({
    choices: [
      {
        message: {
          executed_tools: [
            {
              type: "web_search",
              arguments: "query: güncel gram altın fiyatı",
              output:
                "TCMB Döviz Kurları\nhttps://www.tcmb.gov.tr/kurlar/today.xml\nAltın verisi https://example.com/gold.",
            },
          ],
        },
      },
    ],
  });

  assert.deepEqual(evidence.toolsUsed, ["web_search"]);
  assert.deepEqual(evidence.searchQueries, ["güncel gram altın fiyatı"]);
  assert.deepEqual(
    evidence.citations.map((citation) => citation.url),
    ["https://www.tcmb.gov.tr/kurlar/today.xml", "https://example.com/gold"],
  );
  assert.equal(evidence.citations[0]?.toolType, "web_search");
  assert.equal(evidence.citations[0]?.query, "güncel gram altın fiyatı");
});
