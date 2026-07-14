import assert from "node:assert/strict";
import test from "node:test";
import {
  buildElyanVoiceProfilePromptBlock,
  classifyElyanTurnIntent,
  responsePolicyForPrompt,
  sanitizeFinalAssistantResponse,
} from "./response-policy.js";

test("responsePolicyForPrompt keeps creative short prompts self-contained", () => {
  const policy = responsePolicyForPrompt("Bana çok bilinmeyen en garip hayvan ismini söyle");

  assert.equal(policy.intent, "creative_answer");
  assert.equal(policy.webRequired, false);
  assert.equal(policy.simpleSelfContained, true);
});

test("classifyElyanTurnIntent separates image generation, web research and URL review", () => {
  assert.equal(classifyElyanTurnIntent("Bana kedi resmi çiz"), "image_generation");
  assert.equal(classifyElyanTurnIntent("Bugünkü dolar kaç TL?"), "web_research");
  assert.equal(classifyElyanTurnIntent("Bu URL'yi incele: https://example.com"), "url_review");
});

test("response policy does not treat temporal small talk as web research", () => {
  assert.equal(classifyElyanTurnIntent("Bugün biraz bunaldım"), "unknown");
  assert.equal(responsePolicyForPrompt("Bugün için kısa bir tweet yaz").webRequired, false);
  assert.equal(responsePolicyForPrompt("Bugünkü dolar kaç TL?").webRequired, true);
});

test("sanitizeFinalAssistantResponse removes robotic evidence language without deleting code fences", () => {
  const sanitized = sanitizeFinalAssistantResponse({
    prompt: "Bu kodu açıkla",
    text: [
      "Bir AI olarak bunu doğrulayamıyorum.",
      "",
      "```ts",
      "const metadata = { ok: true };",
      "```",
    ].join("\n"),
    workload: "mobile_chat_fast",
  });

  assert.doesNotMatch(sanitized, /AI olarak|doğrulayamıyorum/u);
  assert.match(sanitized, /```ts/u);
  assert.match(sanitized, /metadata =/u);
});

test("buildElyanVoiceProfilePromptBlock makes warmth language-agnostic", () => {
  const block = buildElyanVoiceProfilePromptBlock({
    prompt: "Explain this gently in English",
    workload: "mobile_chat_fast",
  });

  assert.match(block, /every other language/u);
  assert.match(block, /very warm, close, sincere/u);
  assert.match(block, /teaching-oriented/u);
});

test("sanitizeFinalAssistantResponse removes unsupported current numeric claims", () => {
  const sanitized = sanitizeFinalAssistantResponse({
    prompt: "Bugünkü gram altın fiyatı kaç TL?",
    text: "Bugün gram altın 1.805 TL. Yeterli güncel kaynağa erişemedim.",
    workload: "mobile_chat_fast",
    allowVerificationLanguage: true,
    freshData: {
      freshnessRequired: true,
      status: "unavailable",
      evidence: { sufficient: false },
    },
  });

  assert.doesNotMatch(sanitized, /1\.805 TL/u);
  assert.match(sanitized, /yeterli güncel kaynağa erişemedim/iu);
});

test("sanitizeFinalAssistantResponse strips internal JSON leakage outside code fences", () => {
  const sanitized = sanitizeFinalAssistantResponse({
    prompt: "Bu debug JSON çıktısını temizle",
    text: [
      "Selam, buradayım.",
      "{\"routeDecision\":\"server_brain\",\"debug\":true,\"reasoning\":\"hidden\"}",
      "",
      "```json",
      "{\"ok\":true}",
      "```",
    ].join("\n"),
    workload: "mobile_chat_fast",
  });

  assert.doesNotMatch(sanitized, /routeDecision|reasoning/u);
  assert.match(sanitized, /```json/u);
  assert.match(sanitized, /"ok":true/u);
});

test("sanitizeFinalAssistantResponse strips pretty printed internal JSON outside code fences", () => {
  const sanitized = sanitizeFinalAssistantResponse({
    prompt: "Bu debug çıktısını temizle",
    text: [
      "Cevap hazır.",
      "{",
      "  \"metadata\": { \"selected_workload\": \"planning\" },",
      "  \"fresh_data\": { \"status\": \"stale\" },",
      "  \"reasoning\": \"hidden\"",
      "}",
      "Sonuç bu.",
    ].join("\n"),
    workload: "mobile_chat_fast",
  });

  assert.doesNotMatch(sanitized, /selected_workload|fresh_data|reasoning|metadata/u);
  assert.match(sanitized, /Cevap hazır/u);
  assert.match(sanitized, /Sonuç bu/u);
});

test("sanitizeFinalAssistantResponse prevents image-ready claims without a renderable artifact", () => {
  const sanitized = sanitizeFinalAssistantResponse({
    prompt: "Bana kedi resmi çiz",
    text: "Görsel hazır, kedi resmini oluşturdum.",
    workload: "mobile_chat_fast",
    imageGenerationRequested: true,
    hasRenderableOutput: false,
  });

  assert.doesNotMatch(sanitized, /hazır|oluşturdum/iu);
  assert.match(sanitized, /üretilemedi/iu);
});

test("sanitizeFinalAssistantResponse prevents document-ready claims without a renderable artifact", () => {
  const sanitized = sanitizeFinalAssistantResponse({
    prompt: "Bu içerikten PDF raporu oluştur",
    text: "PDF dosyası hazır.",
    workload: "document_generate",
    artifactRequired: true,
    hasRenderableOutput: false,
  });
  assert.doesNotMatch(sanitized, /dosyası hazır/iu);
  assert.match(sanitized, /üretilemedi/iu);
});

test("sanitizeFinalAssistantResponse keeps markdown lists intact on short-form prompts", () => {
  const text = [
    "Gelen kutunuzdaki son 5 e-posta şu şekilde:",
    "1. Fatura hatırlatması — Elektrik dağıtım",
    "2. Toplantı daveti — Ürün ekibi",
    "3. Kargo bildirimi — Sipariş yolda",
    "4. Bülten — Haftalık teknoloji özeti",
    "5. Güvenlik uyarısı — Yeni giriş",
  ].join("\n");
  const sanitized = sanitizeFinalAssistantResponse({
    prompt: "Son maillerimde ne var? Kısaca özetle.",
    text,
    workload: "mobile_chat_fast",
  });
  assert.match(sanitized, /Güvenlik uyarısı/u);
  assert.match(sanitized, /Fatura hatırlatması/u);
});

test("sanitizeFinalAssistantResponse skips sentence trimming for tool-grounded answers", () => {
  const text =
    "Gelen kutunu kontrol ettim. Üç önemli mail var. İlki faturayla ilgili. İkincisi toplantı daveti. Üçüncüsü kargo bildirimi.";
  const sanitized = sanitizeFinalAssistantResponse({
    prompt: "Son maillerimde ne var? Kısaca özetle.",
    text,
    workload: "mobile_chat_fast",
    toolGrounded: true,
  });
  assert.match(sanitized, /kargo bildirimi/u);
});
