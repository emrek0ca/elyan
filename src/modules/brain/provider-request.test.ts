import assert from "node:assert/strict";
import test from "node:test";
import {
  buildRequestBody,
  buildSharedBrainRequestAttempt,
  getChatCompletionPath,
  type SharedBrainConversationMessage,
} from "./provider-request.js";

test("buildRequestBody attaches vision images to the final user message", () => {
  const messages: SharedBrainConversationMessage[] = [
    { role: "system", content: "You are Elyan." },
    { role: "user", content: "Bu görseli açıkla" },
  ];
  const body = buildRequestBody(
    "groq",
    "llama-vision",
    messages,
    512,
    undefined,
    false,
    [{ documentId: "doc-1", label: "image.jpg", mimeType: "image/jpeg", base64: "abc123" }],
  ) as Record<string, unknown>;

  const outMessages = body.messages as Array<Record<string, unknown>>;
  const last = outMessages.at(-1) as Record<string, unknown>;
  const content = last.content as Array<Record<string, unknown>>;
  assert.equal(content[0]?.type, "text");
  assert.equal(content[1]?.type, "image_url");
  assert.deepEqual(content[1]?.image_url, { url: "data:image/jpeg;base64,abc123" });
});

test("Gemini vision request receives adaptive high-detail hint", () => {
  const body = buildRequestBody(
    "gemini",
    "vision-model",
    [{ role: "user", content: "Küçük yazıyı oku" }],
    512,
    undefined,
    false,
    [{ documentId: "doc-1", label: "text_crop", mimeType: "image/jpeg", base64: "abc123", detail: "high" }],
  ) as Record<string, unknown>;
  const messages = body.messages as Array<Record<string, unknown>>;
  const content = messages.at(-1)?.content as Array<Record<string, unknown>>;
  assert.deepEqual(content[1]?.image_url, {
    url: "data:image/jpeg;base64,abc123",
    detail: "high",
  });
});

test("Groq vision request omits provider-specific detail hint", () => {
  const body = buildRequestBody(
    "groq",
    "vision-model",
    [{ role: "user", content: "Küçük yazıyı oku" }],
    512,
    undefined,
    false,
    [{ documentId: "doc-1", label: "text_crop", mimeType: "image/jpeg", base64: "abc123", detail: "high" }],
  ) as Record<string, unknown>;
  const messages = body.messages as Array<Record<string, unknown>>;
  const content = messages.at(-1)?.content as Array<Record<string, unknown>>;
  assert.deepEqual(content[1]?.image_url, { url: "data:image/jpeg;base64,abc123" });
});

test("buildRequestBody caps high reasoning effort when the token budget is tight", () => {
  const body = buildRequestBody(
    "groq",
    "openai/gpt-oss-20b",
    [{ role: "user", content: "Derin analiz yap" }],
    1024,
    undefined,
    true,
    [],
    "visible",
    "high",
  ) as Record<string, unknown>;

  assert.equal(body.reasoning_format, "parsed");
  assert.equal(body.reasoning_effort, "medium");
});

test("machine-JSON turns need a bigger budget before high reasoning is allowed", () => {
  // CANLI ARIZA (2026-08-30, `document_generate`, görev d3d62fa8): gizli
  // düşünme turu `max_tokens`a sayıldığı için görünür JSON'a yer kalmıyordu.
  // İki belirti, tek kök: JSON yarıda kesilince Groq 400 `json_validate_failed`
  // döndürüyor, hiç token kalmayınca akış boş dönüyor. 13 denemenin tamamı
  // düştü ve kullanıcı "Şu anda düşünme servisine ulaşamıyorum" gördü.
  //
  // Eşik ÇIPLAK BİR SAYIYDI (1500) ve asıl kuralı ifade etmiyordu: çıktının
  // geçerli JSON olmak ZORUNDA olduğu turlarda kesilme kalite kaybı değil,
  // sert hatadır. Bu yüzden makine-JSON tabanı daha yüksek.
  const machineJson = buildRequestBody(
    "groq",
    "openai/gpt-oss-120b",
    [{ role: "user", content: "Bunu bana pdf olarak verir misin" }],
    2_000,
    undefined,
    true,
    [],
    "hidden",
    "high",
    undefined,
    undefined,
    true,
  ) as Record<string, unknown>;
  assert.equal(machineJson.reasoning_effort, "medium");

  // Aynı bütçe serbest metinde yeterlidir; orada kesilme yalnız kısaltır.
  const freeText = buildRequestBody(
    "groq",
    "openai/gpt-oss-120b",
    [{ role: "user", content: "Uzun uzun anlat" }],
    2_000,
    undefined,
    true,
    [],
    "hidden",
    "high",
  ) as Record<string, unknown>;
  assert.equal(freeText.reasoning_effort, "high");
});

test("never sends unsupported reasoning controls to Compound", () => {
  const body = buildRequestBody(
    "groq",
    "groq/compound-mini",
    [{ role: "user", content: "Güncel altın fiyatını bul" }],
    1024,
    undefined,
    false,
    [],
    "hidden",
    "high",
  ) as Record<string, unknown>;

  assert.equal("reasoning_format" in body, false);
  assert.equal("reasoning_effort" in body, false);
});

test("buildRequestBody requests schema-constrained Gemini output", () => {
  const schema = {
    type: "object",
    required: ["visualDescription"],
    properties: { visualDescription: { type: "string" } },
  };
  const body = buildRequestBody(
    "gemini",
    "gemini-fast",
    [{ role: "user", content: "Describe the image" }],
    256,
    undefined,
    false,
    [],
    "hidden",
    "low",
    0.2,
    schema,
  ) as Record<string, unknown>;

  assert.deepEqual(body.response_format, {
    type: "json_schema",
    json_schema: {
      name: "elyan_structured_output",
      strict: true,
      schema,
    },
  });
});

test("buildSharedBrainRequestAttempt adds TurnEnvelope response_format only for supported chat providers", () => {
  const chatBody = {
    messages: [{ role: "user", content: "Selam" }],
  };
  const groqAttempt = buildSharedBrainRequestAttempt({
    provider: "groq",
    path: getChatCompletionPath("groq"),
    body: chatBody,
    turnEnvelopeEnabled: true,
  });

  assert.equal(groqAttempt.turnEnvelopeMode, true);
  assert.ok("response_format" in groqAttempt.body);
  const messages = groqAttempt.body.messages as Array<Record<string, unknown>>;
  assert.equal(messages[0]?.role, "system");

  const ollamaGenerateAttempt = buildSharedBrainRequestAttempt({
    provider: "ollama",
    path: "/api/generate",
    body: { prompt: "Selam" },
    turnEnvelopeEnabled: true,
  });
  assert.equal(ollamaGenerateAttempt.turnEnvelopeMode, false);
  assert.equal("response_format" in ollamaGenerateAttempt.body, false);
});

test("TurnEnvelope format uses json_object for gpt-oss and unsupported Groq models", () => {
  const chatBody = (model: string) => ({
    model,
    messages: [{ role: "user", content: "Selam" }],
  });
  // gpt-oss reasoning modeli JSON üretebilir; provider-level schema zorlaması
  // canlıda boş/invalid çıktı üretebildiği için compact zarf talimatına düşer.
  const gptOss = buildSharedBrainRequestAttempt({
    provider: "groq",
    path: getChatCompletionPath("groq"),
    body: chatBody("openai/gpt-oss-20b"),
    turnEnvelopeEnabled: true,
  });
  assert.deepEqual(gptOss.body.response_format, { type: "json_object" });
  const gptOssSystem = (gptOss.body.messages as Array<Record<string, unknown>>)[0];
  assert.match(String(gptOssSystem?.content ?? ""), /must contain exactly these keys/u);
  // Desteklemeyen model (qwen, Groq 400: "does not support response format
  // json_schema") de json_object'e düşer; şema anayasası system mesajına taşınır.
  const qwen = buildSharedBrainRequestAttempt({
    provider: "groq",
    path: getChatCompletionPath("groq"),
    body: chatBody("qwen/qwen3.6-27b"),
    turnEnvelopeEnabled: true,
  });
  assert.equal(qwen.turnEnvelopeMode, true);
  assert.deepEqual(qwen.body.response_format, { type: "json_object" });
  const qwenSystem = (qwen.body.messages as Array<Record<string, unknown>>)[0];
  assert.match(String(qwenSystem?.content ?? ""), /must contain exactly these keys/u);
});

test("buildRequestBody makine-JSON rotasında biçimi ZORLAR (qwen hariç)", () => {
  // Bu testin kendi yorumu arızayı ZATEN anlatıyordu: "hiç `response_format`
  // kalmıyordu ve model soruyu sınıflamak yerine CEVAPLIYORDU (~%40 düzyazı)".
  // Ama iddia o bozuk durumu KİLİTLİYORDU.
  //
  // Bastırma kuralı qwen için yazılmıştı, tüm Groq modellerine uygulanıyordu.
  // Ölçüm (gerçek 33KB planlama promptu, canlı Groq):
  //   qwen/qwen3.6-27b   json_object → 0/2 (HTTP 400)   → bastırma HAKLI
  //   openai/gpt-oss-20b json_object → 2/2              → bastırma SAF KAYIP
  //   openai/gpt-oss-120b json_object → 4/4 (2–3 adım)
  //
  // Canlı bedel: iki görevde de ilk plan denemesi Markdown döndü, onarım tek
  // adıma çöktü, belgeye konu tarifi yazıldı.
  const body = buildRequestBody(
    "groq",
    "openai/gpt-oss-120b",
    [{ role: "user", content: "selam" }],
    512,
    undefined,
    false,
    [],
    "hidden",
    "low",
    0.2,
    undefined,
    true,
  ) as Record<string, unknown>;

  assert.deepEqual(body.response_format, { type: "json_object" });

  // qwen HÂLÂ bastırılır: bu model biçim bayrağıyla 400 dönüyor.
  const qwenBody = buildRequestBody(
    "groq",
    "qwen/qwen3.6-27b",
    [{ role: "user", content: "selam" }],
    512,
    undefined,
    false,
    [],
    "hidden",
    "low",
    0.2,
    undefined,
    true,
  ) as Record<string, unknown>;
  assert.equal(qwenBody.response_format, undefined);

  // Groq makine rotasında KATI ŞEMA yine gönderilmez (gpt-oss'ta
  // json_validate_failed veriyordu); sözleşme prompt içinde taşınır ve typed
  // parser doğrular. Ama biçim yine JSON'a zorlanır.
  const schema = { type: "object", properties: {} };
  const schemaBody = buildRequestBody(
    "groq",
    "openai/gpt-oss-120b",
    [{ role: "user", content: "selam" }],
    512,
    undefined,
    false,
    [],
    "hidden",
    "low",
    0.2,
    schema,
    true,
  ) as Record<string, unknown>;
  assert.deepEqual(schemaBody.response_format, { type: "json_object" });

  // Bayrak kapalıyken davranış hiç değişmez (mevcut sohbet yolu korunur).
  const plainBody = buildRequestBody(
    "groq",
    "openai/gpt-oss-120b",
    [{ role: "user", content: "selam" }],
    512,
  ) as Record<string, unknown>;
  assert.equal("response_format" in plainBody, false);

  // json_object'i desteklemeyen sağlayıcıya gövde eklenmez.
  const ollamaBody = buildRequestBody(
    "ollama",
    "llama3",
    [{ role: "user", content: "selam" }],
    512,
    undefined,
    false,
    [],
    "hidden",
    "low",
    0.2,
    undefined,
    true,
  ) as Record<string, unknown>;
  assert.equal("response_format" in ollamaBody, false);
});
