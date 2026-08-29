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

/**
 * CANLI ARIZA (mobil, 2026-08-29): "iOS canlı etkinlikleri ile normal push
 * bildirimlerini karşılaştır" cevabının BAŞINA "Bu iddiayı elimdeki kanıtlarla
 * doğrulayamıyorum" ekleniyordu. Yönlendirici o turu DOĞRU biçimde kanıtsız
 * kapatmıştı (`source:"none"`); kanıt toplanmadığı için cevaptaki ürün adları
 * ("APNs", "iOS, Android") desteksiz çıkıyor ve genel bir teknik karşılaştırma
 * sistemin kendi uyarısıyla açılıyordu.
 *
 * Düz metin bu kapıyı zaten tetiklemiyordu; tetikleyen, tablodaki AD
 * iddialarıydı. Bu yüzden test gerçek çıktı şekliyle yazılı.
 */
const COMPARISON_ANSWER =
  "Canlı Etkinlikleri ana ekranda sürekli güncellenir. Örnek kullanım: Spor skorları, taksi takibi, takvim davetleri. Push sertifikası ve APNs entegrasyonu gerekir. iOS, Android ve web tarafında çapraz platform çalışır.";
// İSTEM TERİMLERİ KANITTIR. İstem "canlı etkinlikler" sözünü içerirse o ad
// iddiası zaten DESTEKLİ sayılır ve kapı hiç tetiklenmez; bu testin ölçtüğü
// şey o değil. Bu yüzden istem, cevaptaki adları TAŞIMAYAN bir devam turu.
const COMPARISON_PROMPT = "İkisini artı eksi yönleriyle karşılaştır";

test("an evidence-free turn does not flag names inside an explanatory answer", () => {
  assert.ok(
    extractFactualClaims(COMPARISON_ANSWER).some((claim) => claim.kind === "name"),
    "test verisi ad iddiası taşımalı, yoksa kapı zaten tetiklenmez",
  );
  assert.equal(
    evaluatePrePublishFactuality({
      prompt: COMPARISON_PROMPT,
      answer: COMPARISON_ANSWER,
      evidenceFreeTurn: true,
    }).shouldCritique,
    false,
  );
});

/**
 * Fark yalnız KANIT TOPLANIP TOPLANMADIĞINDA. Aynı cevap, kanıt beklenen bir
 * turda hâlâ sorgulanır — bayrak kapıyı gevşetmez, kapsamını daraltır.
 */
test("the same answer is still gated on a turn that was supposed to gather evidence", () => {
  assert.equal(
    evaluatePrePublishFactuality({
      prompt: COMPARISON_PROMPT,
      answer: COMPARISON_ANSWER,
      evidenceFreeTurn: false,
    }).shouldCritique,
    true,
  );
});

/**
 * Kapı DARALIR, KAPANMAZ. Kanıtsız turda da uydurma bir SAYI yakalanmalı;
 * aksi hâlde "kanıt istemeyen tur" hallüsinasyon için serbest bölge olurdu.
 */
test("an evidence-free turn still flags a fabricated hard number", () => {
  assert.equal(
    evaluatePrePublishFactuality({
      prompt: "Kısa cevap ver.",
      answer: "Şirket 2030'da 50 milyon USD gelir elde etti.",
      evidenceFreeTurn: true,
    }).shouldCritique,
    true,
  );
});
