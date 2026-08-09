import assert from "node:assert/strict";
import test from "node:test";
import {
  chatGenerationAgePhase,
  chatGenerationQueuePriority,
  chatGenerationProviderForStage,
  decideChatQueueAdmission,
  estimateChatGenerationReservationTokens,
  getChatGenerationQueueLimits,
  getChatGenerationTiming,
} from "./chat-generation-policy.js";

function app(overrides: Record<string, unknown> = {}) {
  return {
    config: {
      ELYAN_CHAT_WORKER_CONCURRENCY: 4,
      ELYAN_CHAT_PRIMARY_GLOBAL_CONCURRENCY: 6,
      ELYAN_CHAT_FALLBACK_GLOBAL_CONCURRENCY: 4,
      ELYAN_CHAT_GLOBAL_BACKLOG_MAX: 1_000,
      ELYAN_CHAT_USER_BACKLOG_MAX: 3,
      ELYAN_GROQ_RPM_LIMIT: 30,
      ELYAN_GROQ_TPM_LIMIT: 8_000,
      ELYAN_GEMINI_RPM_LIMIT: 10,
      ...overrides,
    },
  } as never;
}

test("chat generation queue defaults support bounded multi-user throughput", () => {
  assert.deepEqual(getChatGenerationQueueLimits(app()), {
    workerConcurrency: 4,
    primaryGlobalConcurrency: 6,
    fallbackGlobalConcurrency: 4,
    globalBacklogMax: 1_000,
    userBacklogMax: 3,
    groqRpmLimit: 30,
    groqTpmLimit: 8_000,
    geminiRpmLimit: 10,
  });
});

test("chat generation admission preserves one active and three waiting jobs per user", () => {
  const limits = getChatGenerationQueueLimits(app());
  assert.deepEqual(
    decideChatQueueAdmission({ globalActive: 999, userActive: 3 }, limits),
    { accepted: true, reason: "accepted" },
  );
  assert.deepEqual(
    decideChatQueueAdmission({ globalActive: 999, userActive: 4 }, limits),
    { accepted: false, reason: "user_backpressure" },
  );
  assert.deepEqual(
    decideChatQueueAdmission({ globalActive: 1_000, userActive: 0 }, limits),
    { accepted: false, reason: "global_backpressure" },
  );
});

test("chat generation timing follows fast, balanced and heavy SLAs", () => {
  assert.deepEqual(getChatGenerationTiming("mobile_chat_fast"), {
    fallbackAfterMs: 20_000,
    deadlineMs: 60_000,
  });
  assert.deepEqual(getChatGenerationTiming("mobile_chat_balanced"), {
    fallbackAfterMs: 45_000,
    deadlineMs: 120_000,
  });
  assert.deepEqual(getChatGenerationTiming("planning"), {
    fallbackAfterMs: 90_000,
    deadlineMs: 240_000,
  });
  assert.equal(chatGenerationAgePhase("mobile_chat_fast", 19_999), "primary");
  assert.equal(chatGenerationAgePhase("mobile_chat_fast", 20_000), "fallback");
  assert.equal(chatGenerationAgePhase("mobile_chat_fast", 60_000), "deadline");
});

test("chat generation provider stages and token reservations are deterministic", () => {
  assert.equal(chatGenerationProviderForStage("primary"), "groq");
  assert.equal(chatGenerationProviderForStage("fallback"), "gemini");
  const tokens = estimateChatGenerationReservationTokens({
    prompt: "12 × 14 kaçtır?",
    workload: "mobile_chat_fast",
    limit: 8_000,
  });
  assert.equal(tokens > 1_200, true);
  assert.equal(tokens <= 8_000, true);
});

test("short chat jobs receive queue priority over deep workloads", () => {
  assert.equal(chatGenerationQueuePriority("mobile_chat_fast"), 1);
  assert.equal(chatGenerationQueuePriority("mobile_chat_balanced"), 5);
  assert.equal(chatGenerationQueuePriority("planning"), 10);
});
