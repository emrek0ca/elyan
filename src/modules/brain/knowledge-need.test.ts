import assert from "node:assert/strict";
import test from "node:test";
import { compileOutputContract } from "../../core/understanding/output-contract.js";
import { classifyIntent } from "../../core/understanding/intent-classifier.js";
import {
  classifyPersonalStateNeed,
  deriveKnowledgeNeed,
  planKnowledgeRoute,
  resolveKnowledgeEvidenceState,
} from "./knowledge-need.js";

test("self-contained typed table does not start RAG or web retrieval", () => {
  const prompt = "Şu verileri tablo olarak göster: 2021: 10, 2022: 20, 2023: 30";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({ message: prompt }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(result.source, "none");
  assert.equal(result.contract, "elyan.knowledge_need.v2");
});

test("previous typed result is authoritative unless refresh is explicit", () => {
  const prompt = "Az önce verdiğin tabloda en yüksek yıl hangisi?";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({
      message: prompt,
      metadata: { authoritativeSourceReference: "previous_answer" },
    }),
    referenceAvailable: true,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(result.source, "conversation");
  assert.equal(result.evidenceRequired, true);
});

test("current-user identity questions use memory without public web", () => {
  const prompt = "Ben kimim?";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({ message: prompt }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(result.source, "memory");
});

test("required knowledge stays insufficient when every admitted source is empty", () => {
  const knowledgeNeed = deriveKnowledgeNeed({
    query: "Türkiye'nin en yüksek dağı hangisi?",
    classification: classifyIntent({
      userId: "user_1",
      message: "Türkiye'nin en yüksek dağı hangisi?",
    }),
    outputContract: compileOutputContract({
      message: "Türkiye'nin en yüksek dağı hangisi?",
    }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: true,
    attachmentContextUsed: false,
  });
  assert.equal(
    resolveKnowledgeEvidenceState({
      knowledgeNeed,
      referenceAvailable: false,
      memoryResultCount: 0,
      providerEvidenceSufficient: false,
      retrievalEvidenceState: "insufficient",
      webEvidenceSufficient: false,
    }),
    "insufficient",
  );
});

test("typed provider wins before open web and keeps one fallback", () => {
  const prompt = "Güncel dolar kuru nedir?";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({ message: prompt }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: true,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
    providerAvailable: true,
  });
  assert.equal(result.source, "provider");
  assert.equal(result.fallback, "web");
});

test("stable Elyan knowledge uses corpus without opening web", () => {
  const prompt = "Elyan masaüstü ne işe yarar?";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({ message: prompt }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
    corpusAvailable: true,
  });
  assert.equal(result.source, "corpus");
  assert.equal(result.fallback, "model");
});

test("semantic web hint never overrides an authoritative conversation reference", () => {
  const prompt = "Az önce verdiğin tabloyu kısalt.";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({
      message: prompt,
      metadata: { authoritativeSourceReference: "previous_answer" },
    }),
    referenceAvailable: true,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    webToolHint: true,
    attachmentContextUsed: false,
  });
  assert.equal(result.source, "conversation");
});

test("semantic web hint never overrides a typed provider or the stable corpus", () => {
  const providerTurn = deriveKnowledgeNeed({
    query: "Dolar kaç TL?",
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: true,
    publicWebExplicitlyRequired: false,
    webToolHint: true,
    attachmentContextUsed: false,
    providerAvailable: true,
  });
  assert.equal(providerTurn.source, "provider");

  const corpusTurn = deriveKnowledgeNeed({
    query: "Elyan masaüstü ne işe yarar?",
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    webToolHint: true,
    attachmentContextUsed: false,
    corpusAvailable: true,
  });
  assert.equal(corpusTurn.source, "corpus");
});

test("web stays closed when nothing requires fresh public data", () => {
  const result = deriveKnowledgeNeed({
    query: "Fotosentezi üç cümleyle açıkla.",
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(result.source, "none");
  assert.equal(result.fallback, "model");
});

test("personal state questions resolve on the memory layer, not the web", () => {
  for (const [prompt, reason] of [
    ["Beni nasıl tanıyorsun?", "current_user_memory_required"],
    ["Yazı tercihlerimi hatırlıyor musun?", "user_preference_memory_required"],
    ["Dünkü görevi kaldığımız yerden sürdür.", "prior_task_state_required"],
  ] as const) {
    const result = deriveKnowledgeNeed({
      query: prompt,
      referenceAvailable: false,
      socialTurn: false,
      // Taze veri sinyali bile kullanıcının kendi durumunu web'e açmaz.
      freshPublicDataRequired: true,
      publicWebExplicitlyRequired: false,
      attachmentContextUsed: false,
      providerAvailable: true,
    });
    assert.equal(result.source, "memory", prompt);
    assert.equal(result.reason, reason, prompt);
  }
});

test("empty preference memory falls back to the model instead of a dead end", () => {
  const knowledgeNeed = deriveKnowledgeNeed({
    query: "Tercihlerimi biliyor musun?",
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(knowledgeNeed.fallback, "model");
  assert.equal(
    resolveKnowledgeEvidenceState({
      knowledgeNeed,
      referenceAvailable: false,
      memoryResultCount: 0,
      providerEvidenceSufficient: false,
      retrievalEvidenceState: "none",
      webEvidenceSufficient: false,
    }),
    "none",
  );
});

test("identity turns still require evidence and abstain when memory is empty", () => {
  const knowledgeNeed = deriveKnowledgeNeed({
    query: "Ben kimim?",
    classification: classifyIntent({ userId: "user_1", message: "Ben kimim?" }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(knowledgeNeed.fallback, "abstain");
  assert.equal(
    resolveKnowledgeEvidenceState({
      knowledgeNeed,
      referenceAvailable: false,
      memoryResultCount: 0,
      providerEvidenceSufficient: false,
      retrievalEvidenceState: "none",
      webEvidenceSufficient: false,
    }),
    "insufficient",
  );
});

test("locally settled layers skip the typed-source probe entirely", () => {
  const social = planKnowledgeRoute({
    query: "Selam, nasılsın?",
    referenceAvailable: false,
    socialTurn: true,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(social.probeTypedSources, false);
  assert.equal(social.settled?.source, "none");

  const personal = planKnowledgeRoute({
    query: "Beni nasıl tanıyorsun?",
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(personal.probeTypedSources, false);
  assert.equal(personal.settled?.source, "memory");
});

test("fresh public turns probe providers but never the stable corpus", () => {
  const plan = planKnowledgeRoute({
    query: "Bugün dolar kaç TL?",
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: true,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(plan.settled, null);
  assert.equal(plan.probeTypedSources, true);
  assert.equal(plan.probeCorpus, false);
});

test("accent-free spelling reaches the same personal-state layer", () => {
  assert.equal(classifyPersonalStateNeed("Tercihlerimi hatirliyor musun?"), "preference");
  assert.equal(classifyPersonalStateNeed("Dunku gorevi surdur."), "continuation");
  assert.equal(classifyPersonalStateNeed("Beni nasil taniyorsun?"), "identity");
  assert.equal(classifyPersonalStateNeed("Raporu devam ettir."), null);
});

/**
 * HATALAR SİMETRİK DEĞİL. Yanlış pozitif, olgusal bir turu hafıza aramasına
 * kilitler ve tipli sağlayıcıyı hiç denemez — kullanıcı "Bugün dolar kaç TL?"
 * sorusuna kur yerine kendi profilinden derlenmiş bir cevap alır. Bu yüzden
 * kapı, ölçülmüş bir olumsuz kümeyle birlikte tutuluyor.
 */
test("ordinary turns never fall into the personal-state layer", () => {
  for (const prompt of [
    "Selam nasılsın?",
    "Fotosentezi 3 cümleyle açıkla.",
    "Bugün dolar kaç TL?",
    "Python'da liste sıralama nasıl yapılır?",
    "1350 TL'nin KDV'si ne kadar?",
    "Elyan masaüstü ne işe yarar?",
    "Raporu devam ettir.",
    "Dünkü hava durumu nasıldı?",
    "Kullanıcı tercihleri için bir tablo şeması yaz",
    "Uygulamanın ayarları nerede saklanıyor?",
    "Bekleyen görevleri listele",
    "Müşteri alışkanlıklarını analiz et",
    "Görevi tamamla",
  ]) {
    assert.equal(classifyPersonalStateNeed(prompt), null, prompt);
  }
});

test("personal-state phrasings are recognised across Turkish suffixes", () => {
  for (const prompt of [
    "Ben kimim?",
    "Beni tanıyor musun?",
    "Benim hakkımda ne biliyorsun?",
    "Kim olduğumu biliyor musun?",
    "Tercihlerimi hatırlıyor musun?",
    "Ayarlarımı biliyor musun?",
    "Bana nasıl hitap etmemi istediğimi biliyor musun?",
    "Dün başladığımız işi anlat",
    "Kaldığımız yerden devam edelim",
    "Yarım kalan görev neydi?",
    "resume the task",
    "continue where we left off",
  ]) {
    assert.notEqual(classifyPersonalStateNeed(prompt), null, prompt);
  }
});
