import assert from "node:assert/strict";
import test from "node:test";
import {
  buildChatContextSnapshot,
  readChatContextSnapshot,
  resolveChatTurnKind,
  snapshotConversation,
  verifyChatContextSnapshot,
} from "./chat-context-snapshot.js";
import { CHAT_CONTEXT_REGRESSION_FIXTURE } from "./chat-regression-fixture.js";
import { evaluateSemanticResponseGate } from "../brain/semantic-response-gate.js";

test("chat context snapshot sorts equal timestamps by message id and keeps completed pairs", () => {
  const snapshot = buildChatContextSnapshot({
    sessionId: "session-1",
    userMessageId: "user-current",
    assistantMessageId: "assistant-current",
    prompt: "Az önceki cevabı düzelt",
    priorTurns: [
      {
        messageId: "assistant-b",
        role: "assistant",
        content: "İkinci yanıt",
        status: "completed",
        createdAt: "2026-08-16T10:00:00.000Z",
      },
      {
        messageId: "user-a",
        role: "user",
        content: "İlk soru",
        status: "completed",
        createdAt: "2026-08-16T10:00:00.000Z",
      },
      {
        messageId: "assistant-a",
        role: "assistant",
        content: "İlk yanıt",
        status: "completed",
        createdAt: "2026-08-16T10:00:00.000Z",
      },
      {
        messageId: "user-b",
        role: "user",
        content: "İkinci soru",
        status: "completed",
        createdAt: "2026-08-16T10:00:00.000Z",
      },
      {
        messageId: "ack",
        role: "assistant",
        content: "Yanıt hazırlanıyor.",
        status: "running",
        createdAt: "2026-08-16T10:01:00.000Z",
      },
    ],
  });

  assert.deepEqual(
    snapshotConversation(snapshot).map((turn) => turn.content),
    ["İlk soru", "İlk yanıt", "İkinci soru", "İkinci yanıt"],
  );
  assert.equal(snapshot.turnKind, "correction");
  assert.equal(snapshot.priorAssistant?.messageId, "assistant-b");
});

test("chat context snapshot verifies prompt and history digests", () => {
  const snapshot = buildChatContextSnapshot({
    sessionId: "session-1",
    userMessageId: "user-current",
    assistantMessageId: "assistant-current",
    prompt: "Önceki cevabı özetle",
    priorTurns: [],
  });

  assert.deepEqual(
    verifyChatContextSnapshot({
      snapshot,
      sessionId: "session-1",
      userMessageId: "user-current",
      assistantMessageId: "assistant-current",
      prompt: "Önceki cevabı özetle",
    }),
    { ok: true },
  );
  assert.deepEqual(
    verifyChatContextSnapshot({
      snapshot,
      sessionId: "session-1",
      userMessageId: "user-current",
      assistantMessageId: "assistant-current",
      prompt: "Başka bir soru",
    }),
    { ok: false, reason: "prompt_digest_mismatch" },
  );
  assert.deepEqual(readChatContextSnapshot(snapshot), snapshot);
});

test("chat turn kind separates deep requests from correction/follow-up semantics", () => {
  assert.equal(
    resolveChatTurnKind({ prompt: "Derin düşün ve üç seçenek çıkar" }),
    "new_request",
  );
  assert.equal(
    resolveChatTurnKind({
      prompt: "Az önceki cevap ilgisizdi, düzelt",
      hasPriorAssistant: true,
    }),
    "correction",
  );
  assert.equal(
    resolveChatTurnKind({
      prompt: "Bunu biraz daha açar mısın?",
      hasPriorAssistant: true,
    }),
    "follow_up",
  );
});

test("five-turn regression fixture keeps deep chat in chat contract and fences correction", () => {
  assert.equal(CHAT_CONTEXT_REGRESSION_FIXTURE.length, 5);
  assert.equal(CHAT_CONTEXT_REGRESSION_FIXTURE[3].expectedOutputContract, "chat_reply");
  assert.equal(CHAT_CONTEXT_REGRESSION_FIXTURE[4].expectedTurnKind, "correction");

  const badCorrection = evaluateSemanticResponseGate({
    prompt: CHAT_CONTEXT_REGRESSION_FIXTURE[4].prompt,
    text: "Kaynak doğrulaması yapılamadığı için belge oluşturmadım.",
    workload: CHAT_CONTEXT_REGRESSION_FIXTURE[4].expectedWorkload,
    turnKind: CHAT_CONTEXT_REGRESSION_FIXTURE[4].expectedTurnKind,
    priorAssistant: { visibleSummary: "Kaynak doğrulaması yapılamadığı için belge oluşturmadım." },
    blocks: [{ type: "text", blockId: "text-1" }],
  });

  assert.equal(badCorrection.accepted, false);
  assert.equal(badCorrection.reason, "unsupported_source_or_document_claim");
});
