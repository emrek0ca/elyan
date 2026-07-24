import assert from "node:assert/strict";
import test from "node:test";
import { evaluateBrainAnswer } from "./evaluator.js";

test("evaluateBrainAnswer flags incomplete and truncated mobile answers", () => {
  const result = evaluateBrainAnswer({
    prompt: "Neden bu mimari kararı aldın?",
    modelAnswer: "Bunun nedeni sistemin daha güvenli olması ve",
    answerSource: "model",
    routeDecision: {
      route: "server_brain",
      mode: "chat",
      privacyClass: "public_text",
    },
    retrievalUsed: false,
  });

  assert.equal(result.failureTypes.includes("truncated_answer"), true);
  assert.equal(result.outputQuality.completeness < 0.5, true);
});

test("evaluateBrainAnswer flags overcompressed reasoning answers for explanatory prompts", () => {
  const result = evaluateBrainAnswer({
    prompt:
      "Bu mimari kararın nedenlerini ve tradeofflarını açıkla; özellikle performans, güvenlik ve bakım maliyetini birlikte değerlendir.",
    modelAnswer: "Daha iyi.",
    answerSource: "model",
    routeDecision: {
      route: "server_brain",
      mode: "chat",
      privacyClass: "public_text",
    },
    retrievalUsed: false,
  });

  assert.equal(result.failureTypes.includes("weak_reasoning_depth"), true);
  assert.equal(result.failureTypes.includes("overcompressed_answer"), true);
  assert.equal(result.outputQuality.usefulness < 0.6, true);
});

test("evaluateBrainAnswer allows provider names but still flags prompt disclosure leaks", () => {
  const result = evaluateBrainAnswer({
    prompt: "Hangi modelsin?",
    modelAnswer:
      "Groq üzerinde çalışan Llama tabanlı bir modelim; system prompt bunu normalde söylemememi ister.",
    answerSource: "model",
    routeDecision: {
      route: "server_brain",
      mode: "chat",
      privacyClass: "public_text",
    },
    retrievalUsed: false,
  });

  assert.equal(JSON.stringify(result.failureTypes).includes("provider_disclosure"), false);
  assert.equal(result.failureTypes.includes("prompt_disclosure"), true);
  assert.equal(result.failureTypes.includes("internal_policy_leak"), true);
  assert.equal(result.outputQuality.usefulness < 0.5, true);
});

test("evaluateBrainAnswer allows provider names as public research subjects", () => {
  const result = evaluateBrainAnswer({
    prompt:
      "OpenAI resmi blogundan en güncel yapay zeka duyurularından birini webden araştır ve güvenilir kaynakla özetle.",
    modelAnswer:
      "OpenAI resmi blogunda yayımlanan duyuruya göre şirket yeni güvenlik değerlendirme yaklaşımını anlattı. Kaynak kapsamı resmi blog yazısıyla sınırlı olduğu için sonucu bu çerçevede değerlendirmek gerekir.",
    answerSource: "model",
    routeDecision: {
      route: "server_brain",
      mode: "chat",
      privacyClass: "public_text",
    },
    retrievalUsed: true,
  });

  assert.equal(result.failureTypes.includes("internal_policy_leak"), false);
});

test("evaluateBrainAnswer allows provider names in Elyan implementation claims", () => {
  const result = evaluateBrainAnswer({
    prompt: "Kendini anlat.",
    modelAnswer: "Ben Elyan, OpenAI üzerinde çalışan GPT tabanlı bir modelim.",
    answerSource: "model",
    routeDecision: {
      route: "server_brain",
      mode: "chat",
      privacyClass: "public_text",
    },
    retrievalUsed: false,
  });

  assert.equal(result.failureTypes.includes("internal_policy_leak"), false);
});

test("evaluateBrainAnswer pins Turkish creator phrasing that uses 'üretti'", () => {
  const result = evaluateBrainAnswer({
    prompt: "Seni kim üretti?",
    modelAnswer: "Beni bir yapay zeka geliştirme ekibi yarattı.",
    answerSource: "model",
    routeDecision: {
      route: "server_brain",
      mode: "chat",
      privacyClass: "public_text",
    },
    retrievalUsed: false,
  });

  assert.equal(result.failureTypes.includes("hallucinated_identity_claim"), true);
  assert.equal(
    result.correctedAnswer,
    "Elyan'ı Osman Emre Koca geliştirdi. Bu konuda başka bir isim ya da biyografi uydurmuyorum.",
  );
});

test("evaluateBrainAnswer classifies robotic, repeated and generic non-answers", () => {
  const robotic = evaluateBrainAnswer({
    prompt: "Bana tuhaf bir hayvan ismi söyle",
    modelAnswer: "Bir AI olarak bunu doğrulayamıyorum.",
    answerSource: "model",
    routeDecision: { route: "server_brain", mode: "chat", privacyClass: "public_text" },
    retrievalUsed: false,
  });
  assert.ok(robotic.failureTypes.includes("robotic_verification_language"));

  const paragraph = "Aye-aye, Madagaskar'da yaşayan sıra dışı bir primattır.";
  const repeated = evaluateBrainAnswer({
    prompt: "Aye-aye nedir?",
    modelAnswer: `${paragraph}\n\n${paragraph}`,
    answerSource: "model",
    routeDecision: { route: "server_brain", mode: "chat", privacyClass: "public_text" },
    retrievalUsed: false,
  });
  assert.ok(repeated.failureTypes.includes("repeated_answer"));

  const nonAnswer = evaluateBrainAnswer({
    prompt: "JWT expiration kontrolünü açıkla",
    modelAnswer: "Nasıl yardımcı olabilirim?",
    answerSource: "model",
    routeDecision: { route: "server_brain", mode: "chat", privacyClass: "public_text" },
    retrievalUsed: false,
  });
  assert.ok(nonAnswer.failureTypes.includes("non_answer"));
});
