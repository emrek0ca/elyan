import assert from "node:assert/strict";
import test from "node:test";
import {
  applyDeterministicFactualityFallback,
  buildFactualityCritiquePrompt,
  evaluatePrePublishFactuality,
  extractFactualClaims,
} from "./factuality-gate.js";

test("evaluatePrePublishFactuality allows claims grounded in current turn and memory", () => {
  const decision = evaluatePrePublishFactuality({
    prompt: "Kullanici sabah acinca: Dun Ingilizce hedefinin 3. adimindaydin, bugun 15 dakikan var mi?",
    answer: "Dun Ingilizce hedefinin 3. adimindaydin, bugun 15 dakikan var mi?",
    understandingContext: {
      retrievedMemory: [
        {
          id: "mem_1",
          value: "Dun Ingilizce hedefinin 3. adimindaydin.",
          type: "preference",
          confidence: 92,
        },
      ],
      contextPackets: [],
    } as never,
    inferenceMetadata: {},
  });

  assert.equal(decision.shouldCritique, false);
  assert.equal(decision.unsupportedClaims.length, 0);
});

test("evaluatePrePublishFactuality triggers for unsupported date or name claims", () => {
  const decision = evaluatePrePublishFactuality({
    prompt: "Bu urun hakkinda kisa bilgi ver.",
    answer: "Apple Vision Prime 17 Temmuz 2027 tarihinde 2.499 USD fiyatla cikti.",
    understandingContext: {
      retrievedMemory: [],
      contextPackets: [],
    } as never,
    inferenceMetadata: {
      blocks: [
        {
          type: "web_search",
          results: [
            {
              title: "Apple Vision Pro overview",
              snippet: "Apple Vision Pro was announced earlier, but this result does not mention Prime.",
              url: "https://example.test/apple",
            },
          ],
        },
      ],
    },
  });

  assert.equal(decision.shouldCritique, true);
  assert.equal(
    decision.unsupportedClaims.some((claim) => claim.text.includes("17 Temmuz 2027")),
    true,
  );
  assert.equal(
    decision.unsupportedClaims.some((claim) => claim.text.includes("2.499 USD")),
    true,
  );
});

test("evaluatePrePublishFactuality does not trigger for bare low-risk computation numbers", () => {
  const decision = evaluatePrePublishFactuality({
    prompt: "2+2 kac?",
    answer: "2+2=4.",
    understandingContext: null,
    inferenceMetadata: {},
  });

  assert.equal(decision.shouldCritique, false);
});

test("web grounding block snippets count as evidence", () => {
  const decision = evaluatePrePublishFactuality({
    prompt: "OpenAI son duyuruyu ozetle",
    answer: "OpenAI 2026-07-07 tarihinde GPT-5 API duyurusunu paylasti.",
    understandingContext: null,
    inferenceMetadata: {
      blocks: [
        {
          type: "web_search",
          results: [
            {
              title: "OpenAI GPT-5 API duyurusu",
              snippet: "OpenAI 2026-07-07 tarihinde GPT-5 API duyurusunu paylasti.",
              url: "https://example.test/openai",
            },
          ],
        },
      ],
    },
  });

  assert.equal(decision.shouldCritique, false);
  assert.equal(decision.unsupportedClaims.length, 0);
});

test("assistant text blocks do not count as their own evidence", () => {
  const decision = evaluatePrePublishFactuality({
    prompt: "Kısa cevap ver.",
    answer: "Acme Labs 2030'da 50 milyon USD gelir acikladi.",
    understandingContext: null,
    inferenceMetadata: {
      blocks: [
        {
          type: "text",
          markdown: "Acme Labs 2030'da 50 milyon USD gelir acikladi.",
        },
      ],
    },
  });

  assert.equal(decision.shouldCritique, true);
  assert.equal(decision.unsupportedClaims.length > 0, true);
});

test("applyDeterministicFactualityFallback softens unsupported factual sentences", () => {
  const decision = evaluatePrePublishFactuality({
    prompt: "Kisa cevap ver.",
    answer: "Bu kismini biliyorum. Apple Vision Prime 2027 yilinda cikti.",
    understandingContext: null,
    inferenceMetadata: {},
  });
  const fallback = applyDeterministicFactualityFallback({
    answer: "Bu kismini biliyorum. Apple Vision Prime 2027 yilinda cikti.",
    decision,
    prompt: "Kisa cevap ver.",
  });

  assert.match(fallback, /Bu kismini biliyorum/);
  assert.match(fallback, /doğrulayamıyorum|cannot verify/);
  assert.doesNotMatch(fallback, /2027 yilinda cikti/);
});

test("deterministic fallback defaults to Turkish for non-English prompts", () => {
  const decision = evaluatePrePublishFactuality({
    prompt: "2+2 kac",
    answer: "Apple Vision Prime 2027 yilinda cikti.",
    understandingContext: null,
    inferenceMetadata: {},
  });
  const fallback = applyDeterministicFactualityFallback({
    answer: "Apple Vision Prime 2027 yilinda cikti.",
    decision,
    // Short Turkish prompt without diacritics must not fall back to English.
    prompt: "2+2 kac",
  });

  // Yazım DİAKRİTİKLİ olmalı: bu cümle kullanıcının cevabına birebir girer.
  // Aksansız hâli ("dogrulayamiyorum") aylarca kullanıcıya makine metni gibi
  // gitti ve testler o kusuru ŞART KOŞUYORDU — yani düzeltmeyi engelleyen
  // şey testin kendisiydi.
  assert.match(fallback, /doğrulayamıyorum/);
  assert.doesNotMatch(fallback, /cannot verify/);
});

test("buildFactualityCritiquePrompt includes unsupported markers and evidence", () => {
  const decision = evaluatePrePublishFactuality({
    prompt: "Kisa cevap ver.",
    answer: "Acme Labs 2030'da 50 milyon USD gelir acikladi.",
    understandingContext: null,
    inferenceMetadata: {},
  });
  const prompt = buildFactualityCritiquePrompt({
    userPrompt: "Kisa cevap ver.",
    draftAnswer: "Acme Labs 2030'da 50 milyon USD gelir acikladi.",
    decision,
  });

  assert.match(prompt, /Desteksiz gorunen iddia isaretleri/);
  assert.match(prompt, /Acme Labs|2030|50 milyon USD/);
});

test("extractFactualClaims identifies dates, numeric facts, and names", () => {
  const claims = extractFactualClaims("Acme Labs 12.07.2026'da 42 milyon USD yatirim aldi.");

  assert.equal(claims.some((claim) => claim.kind === "date"), true);
  assert.equal(claims.some((claim) => claim.kind === "number" && claim.salience === "high"), true);
  assert.equal(claims.some((claim) => claim.kind === "name" && claim.text === "Acme Labs"), true);
});
