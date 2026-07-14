import assert from "node:assert/strict";
import test from "node:test";
import {
  buildElyanResponseContract,
  inspectElyanFinalResponse,
} from "./response-contract.js";

const contractCases = [
  ["Bana çok bilinmeyen garip bir hayvan ismi söyle", "creative_answer", "answer", "none", "brief"],
  ["X için kısa bir tweet yaz", "writing", "execute", "none", "brief"],
  ["Bu kod neden hata veriyor? const x = 1", "technical_help", "explain", "none", "balanced"],
  ["12 * 14 kaç?", "math", "answer", "none", "brief"],
  ["Bana kedi resmi çiz", "image_generation", "execute", "route_only", "balanced"],
  ["Bugünkü dolar kaç TL?", "web_research", "research", "required", "balanced"],
  ["Oğuz, Kıpçak ve Karluk dillerini araştır", "web_research", "research", "none", "balanced"],
  ["Oğuz dillerini kaynaklı şekilde araştır", "web_research", "research", "required", "balanced"],
  ["Elon Musk kimdir?", "unknown", "answer", "required", "brief"],
  ["Bu URL'yi incele: https://example.com", "url_review", "research", "required", "balanced"],
  ["Bugün biraz bunaldım", "unknown", "answer", "none", "brief"],
  ["Bugün için kısa bir motivasyon cümlesi yaz", "writing", "execute", "none", "brief"],
  ["Lan", "casual_chat", "answer", "none", "brief"],
  ["Bunu adım adım ve detaylı anlat", "unknown", "explain", "none", "detailed"],
] as const;

for (const [prompt, intent, action, toolPolicy, length] of contractCases) {
  test(`response contract: ${prompt}`, () => {
    const contract = buildElyanResponseContract({ prompt, workload: "mobile_chat_fast" });
    assert.equal(contract.intent, intent);
    assert.equal(contract.action, action);
    assert.equal(contract.toolPolicy, toolPolicy);
    assert.equal(contract.length, length);
  });
}

test("quality report detects internal state and repeated finals", () => {
  const paragraph = "Bu cevap kullanıcıya gösterilmesi gereken tek sonuçtur.";
  const report = inspectElyanFinalResponse({
    prompt: "Bunu açıkla",
    text: `reasoning: hidden\n${paragraph}\n\n${paragraph}`,
  });
  assert.equal(report.passed, false);
  assert.ok(report.issues.includes("internal_state_leak"));
  assert.ok(report.issues.includes("repeated_answer"));
});

test("quality report rejects generic non-answer", () => {
  const report = inspectElyanFinalResponse({
    prompt: "JWT doğrulama hatasını açıkla",
    text: "Nasıl yardımcı olabilirim?",
  });
  assert.ok(report.issues.includes("non_answer"));
});

test("quality report rejects fake image success without an artifact", () => {
  const report = inspectElyanFinalResponse({
    prompt: "Bana kedi resmi çiz",
    text: "Görsel hazır.",
    hasRenderableArtifact: false,
  });
  assert.ok(report.issues.includes("missing_requested_artifact"));
  assert.ok(report.issues.includes("false_success_claim"));
});

test("quality report requires a block for generated documents but not plain writing", () => {
  const documentContract = buildElyanResponseContract({
    prompt: "Bu içerikten PDF raporu oluştur",
  });
  const writingContract = buildElyanResponseContract({
    prompt: "Bu konu için kısa bir rapor metni yaz",
  });
  assert.equal(documentContract.artifactRequired, true);
  assert.equal(writingContract.artifactRequired, false);
  const report = inspectElyanFinalResponse({
    prompt: "Bu içerikten PDF raporu oluştur",
    text: "PDF dosyası hazır.",
    hasRenderableArtifact: false,
  });
  assert.ok(report.issues.includes("missing_requested_artifact"));
  assert.ok(report.issues.includes("false_success_claim"));
});

test("quality report accepts an honest artifact failure state", () => {
  const report = inspectElyanFinalResponse({
    prompt: "Bana kedi resmi çiz",
    text: "Görsel şu anda üretilemedi. Lütfen biraz sonra tekrar dene.",
    hasRenderableArtifact: false,
  });
  assert.deepEqual(report.issues, []);
});

test("quality report accepts concise self-contained prose", () => {
  const report = inspectElyanFinalResponse({
    prompt: "Bana garip bir hayvan ismi söyle",
    text: "Aye-aye. Madagaskar'da yaşayan, uzun orta parmağıyla ağaç içindeki böcekleri çıkaran tuhaf görünümlü bir primat.",
  });
  assert.deepEqual(report.issues, []);
  assert.equal(report.passed, true);
});
