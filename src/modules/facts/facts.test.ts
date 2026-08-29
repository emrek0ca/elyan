import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import { lookupTokens, matchCryptoAsset, matchForeignCurrency, normalizeLookupText } from "./catalog.js";
import { locationCandidates } from "./geocode.js";
import {
  isFactProviderCircuitOpen,
  recordFactProviderFailure,
  recordFactProviderSuccess,
  resetFactProviderCircuitsForTests,
} from "./http.js";
import { FACT_PROVIDERS, getFactProvider } from "./registry.js";
import { buildFactDirectAnswer } from "./direct-answer.js";
import { buildFactOutputBlocks } from "./blocks.js";

function appWith(config: Record<string, unknown>): FastifyInstance {
  return { config, log: { warn() {}, debug() {} } } as unknown as FastifyInstance;
}

test("catalog matches assets the old regex silently missed", () => {
  // Eski hâl yalnız /bitcoin|btc/ ve /ethereum|eth/ tanıyordu; bu üçü aramaya
  // düşüyordu. Katalog bunları veri olarak taşıyor.
  assert.equal(matchCryptoAsset("solana kaç TL")?.symbol, "SOL");
  assert.equal(matchCryptoAsset("cardano fiyatı nedir")?.symbol, "ADA");
  assert.equal(matchCryptoAsset("dogecoin ne kadar oldu")?.symbol, "DOGE");
  assert.equal(matchCryptoAsset("bitcoin kaç dolar")?.symbol, "BTC");
});

test("catalog tolerates Turkish suffixes without a regex per word", () => {
  assert.equal(matchCryptoAsset("bitcoinin fiyatı ne")?.symbol, "BTC");
  assert.equal(matchForeignCurrency("dolarla ödeme yapacağım kur ne")?.code, "USD");
  assert.equal(matchForeignCurrency("sterlin kaç lira")?.code, "GBP");
});

test("catalog does not treat TRY as the foreign side of a pair", () => {
  assert.equal(matchForeignCurrency("lira ne durumda"), null);
});

test("Turkish normalization keeps dotted and dotless i comparable", () => {
  assert.equal(normalizeLookupText("İSTANBUL"), "istanbul");
  assert.equal(normalizeLookupText("Iğdır"), "igdir");
  assert.ok(lookupTokens("Bitcoin'in").has("bitcoin"));
});

test("location candidates strip question phrasing and keep the place", () => {
  const candidates = locationCandidates("Çankırı hava durumu");
  assert.ok(candidates.includes("Çankırı"), `unexpected: ${candidates.join("|")}`);
  assert.equal(locationCandidates("hava durumu nedir").length, 0);
});

test("every registered provider exposes a usable semantic catalog entry", () => {
  assert.ok(FACT_PROVIDERS.length >= 6);
  for (const provider of FACT_PROVIDERS) {
    assert.ok(provider.intents.length >= 3, `${provider.id} has too few intents`);
    // Niyet ifadeleri KELİME değil CÜMLE olmalı; e5 benzerliği buna dayanıyor.
    for (const intent of provider.intents) {
      assert.ok(intent.split(" ").length >= 3, `${provider.id}: "${intent}" too short`);
    }
    assert.ok(provider.ttlMs > 0 && provider.timeoutMs > 0);
    assert.ok(provider.authority.length > 2);
    assert.ok(["allowed", "conditional"].includes(provider.commercialUse));
    assert.equal(typeof provider.allowStale, "boolean");
    assert.equal(getFactProvider(provider.id), provider);
  }
});

test("market providers never allow stale values", () => {
  for (const id of [
    "alpha_vantage_metals",
    "tcmb_fx",
    "frankfurter",
    "coingecko",
  ] as const) {
    assert.equal(getFactProvider(id)?.allowStale, false, id);
  }
});

test("metals provider recognizes gold and a bounded history request", () => {
  const provider = getFactProvider("alpha_vantage_metals");
  assert.ok(provider);
  assert.deepEqual(provider.extract("Güncel altın fiyatı nedir?"), {
    symbol: "GOLD",
    ticker: "XAU",
    label: "Altın",
    history: false,
  });
  assert.deepEqual(provider.extract("Altının son 30 gününü grafik yap"), {
    symbol: "GOLD",
    ticker: "XAU",
    label: "Altın",
    history: true,
  });
});

test("FRED provider stays scoped to United States macro questions", () => {
  const provider = getFactProvider("fred");
  assert.ok(provider);
  assert.deepEqual(provider.extract("ABD enflasyonu kaç?"), {
    metric: {
      seriesId: "CPIAUCSL",
      label: "ABD tüketici enflasyonu",
      unit: "% yıllık",
      aliases: ["enflasyon", "inflation", "cpi"],
      transform: "pc1",
    },
  });
  assert.equal(provider.extract("Türkiye enflasyonu kaç?"), null);
});

test("EVDS provider handles only bounded historical currency series", () => {
  const provider = getFactProvider("tcmb_evds");
  assert.ok(provider);
  assert.deepEqual(provider.extract("Doların son 30 gününü tablo yap"), {
    code: "USD",
    days: 30,
  });
  assert.deepEqual(provider.extract("Euro tarihsel kur grafiği"), {
    code: "EUR",
    days: 30,
  });
  assert.equal(provider.extract("Dolar kaç TL?"), null);
});

test("typed metal series produces deterministic table and chart blocks", () => {
  const answer = {
    providerId: "alpha_vantage_metals" as const,
    dataClass: "daily" as const,
    snippet: "XAU series",
    directAnswer: "Altın serisi hazır.",
    citation: {
      title: "Gold",
      url: "https://www.alphavantage.co/documentation/",
      sourceHost: "alphavantage.co",
      observedAt: "2026-08-29T12:00:00.000Z",
    },
    values: {
      symbol: "XAU",
      series: [
        { date: "2026-08-28", usdPerOunce: 3400.5 },
        { date: "2026-08-29", usdPerOunce: 3410.25 },
      ],
    },
    confidence: 0.96,
    ttlMs: 30_000,
  };
  const blocks = buildFactOutputBlocks({
    answer,
    tableRequested: true,
    chartRequested: true,
  }) as Array<{ type?: string; rows?: unknown[]; values?: unknown[] }>;
  assert.deepEqual(blocks.map((block) => block.type), ["table", "chart"]);
  assert.equal(blocks[0]?.rows?.length, 2);
  assert.deepEqual(blocks[1]?.values, [3400.5, 3410.25]);
});

test("provider extract returns null when the turn lacks the entity", () => {
  const crypto = getFactProvider("coingecko");
  const weather = getFactProvider("open_meteo");
  assert.ok(crypto && weather);
  assert.equal(crypto.extract("bugün nasılsın"), null);
  assert.equal(weather.extract("hava durumu nedir"), null);
});

test("circuit breaker opens after repeated failures and blocks further calls", () => {
  resetFactProviderCircuitsForTests();
  assert.equal(isFactProviderCircuitOpen("coingecko"), false);
  recordFactProviderFailure("coingecko");
  recordFactProviderFailure("coingecko");
  assert.equal(isFactProviderCircuitOpen("coingecko"), false);
  recordFactProviderFailure("coingecko");
  assert.equal(isFactProviderCircuitOpen("coingecko"), true);
  // Kesici sağlayıcı BAŞINA çalışır: biri düşerken diğerleri kapanmaz.
  assert.equal(isFactProviderCircuitOpen("open_meteo"), false);
  recordFactProviderSuccess("coingecko");
  assert.equal(isFactProviderCircuitOpen("coingecko"), false);
  resetFactProviderCircuitsForTests();
});

test("direct answer lane stays closed unless explicitly enabled", async () => {
  const result = await buildFactDirectAnswer(
    appWith({ ELYAN_FACT_DIRECT_ANSWER_ENABLED: false }),
    { prompt: "Çankırı hava durumu", desiredOutputKinds: ["chat_reply"] },
  );
  assert.equal(result, null);
});

test("direct answer lane refuses turns that ask for reasoning or non-chat output", async () => {
  const app = appWith({ ELYAN_FACT_DIRECT_ANSWER_ENABLED: true });
  // Şablon cümle bir gerekçe sorusunu cevaplayamaz.
  assert.equal(
    await buildFactDirectAnswer(app, {
      prompt: "Çankırı hava durumu neden bu kadar değişken açıkla",
      desiredOutputKinds: ["chat_reply"],
    }),
    null,
  );
  // Tablo/grafik isteyen tur modelsiz basılamaz.
  assert.equal(
    await buildFactDirectAnswer(app, {
      prompt: "Çankırı hava durumu",
      desiredOutputKinds: ["chat_reply", "table"],
    }),
    null,
  );
});

test("direct answer reuses already-resolved evidence instead of refetching", async () => {
  const app = appWith({ ELYAN_FACT_DIRECT_ANSWER_ENABLED: true });
  const answer = {
    providerId: "open_meteo" as const,
    dataClass: "hourly" as const,
    snippet: "Çankırı gözlemi; sıcaklık 20.7 °C",
    directAnswer: "Çankırı için şu anki hava durumu: 20.7 °C, açık.",
    citation: {
      title: "Çankırı canlı hava durumu",
      url: "https://api.open-meteo.com/v1/forecast",
      sourceHost: "api.open-meteo.com",
      observedAt: new Date().toISOString(),
    },
    values: { temperatureC: 20.7 },
    confidence: 0.95,
    ttlMs: 600_000,
  };
  const result = await buildFactDirectAnswer(app, {
    prompt: "Çankırı hava durumu",
    desiredOutputKinds: ["chat_reply"],
    answer,
  });
  assert.ok(result);
  assert.match(result.text, /20\.7 °C/);
  assert.match(result.text, /api\.open-meteo\.com/);
  assert.equal(result.block?.type, "web_search");
});

test("direct answer refuses a low-confidence provider result", async () => {
  const app = appWith({ ELYAN_FACT_DIRECT_ANSWER_ENABLED: true });
  const result = await buildFactDirectAnswer(app, {
    prompt: "sıradaki resmi tatil",
    desiredOutputKinds: ["chat_reply"],
    answer: {
      providerId: "nager_holidays" as const,
      dataClass: "daily" as const,
      snippet: "Türkiye 2026 resmî tatilleri",
      directAnswer: "Sıradaki tatil ...",
      citation: {
        title: "t",
        url: "https://date.nager.at/api/v3/PublicHolidays/2026/TR",
        sourceHost: "date.nager.at",
        observedAt: new Date().toISOString(),
      },
      values: {},
      confidence: 0.88,
      ttlMs: 1_000,
    },
  });
  assert.equal(result, null);
});
