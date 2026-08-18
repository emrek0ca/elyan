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
    assert.equal(getFactProvider(provider.id), provider);
  }
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
