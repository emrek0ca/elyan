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

test("buildRequestBody leaves Groq machine-JSON routes to the typed parser", () => {
  // Masaüstü plan/anlama rotasında turn envelope KAPALIdır ve şema override
  // yoktur; bu ikisi birleşince hiç `response_format` kalmıyordu ve model
  // soruyu sınıflamak yerine CEVAPLIYORDU (ölçüldü: soru biçimli mesajlarda
  // ~%40 düzyazı → masaüstü ayrıştıramaz → desen tabanlı bozulmuş mod).
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

  assert.equal(body.response_format, undefined);

  // Groq makine rotasında şema da provider response_format olarak gönderilmez;
  // aynı sözleşme prompt içinde taşınır ve typed parser doğrular.
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
  assert.equal(schemaBody.response_format, undefined);

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
