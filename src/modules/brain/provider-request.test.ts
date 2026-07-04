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
