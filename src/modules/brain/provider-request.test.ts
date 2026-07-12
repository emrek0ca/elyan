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
