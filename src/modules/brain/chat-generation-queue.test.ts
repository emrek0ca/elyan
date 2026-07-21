import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import {
  CHAT_GENERATION_QUEUE_NAMES,
  chatGenerationJobId,
  createChatGenerationLeaseFence,
  createLocalConcurrencyGate,
  isGeminiFallbackQueueConfigured,
  isChatGenerationQueueEnabled,
  readChatGenerationQueueFailure,
} from "./chat-generation-queue.js";

test("chat queue job data stays task-identity only", () => {
  assert.equal(CHAT_GENERATION_QUEUE_NAMES.primary, "elyan-chat-primary-v1");
  assert.equal(CHAT_GENERATION_QUEUE_NAMES.fallback, "elyan-chat-fallback-v1");
  assert.equal(
    chatGenerationJobId("primary", "task:private/value"),
    "chat-primary-task-private-value",
  );
});

test("chat queue is fail-closed without Redis", () => {
  assert.equal(
    isChatGenerationQueueEnabled({
      config: { ELYAN_CHAT_QUEUE_ENABLED: true, REDIS_URL: undefined },
    } as never),
    false,
  );
});

test("chat queue reads rate-limit evidence from safe attempt metadata", () => {
  const failure = readChatGenerationQueueFailure(
    new AppError(503, "server_brain_unavailable", "safe", {
      transient: true,
      retrySuggested: true,
      attemptFailures: [
        {
          failureClass: "rate_limited",
          retryAfterMs: 3_000,
        },
      ],
    }),
  );
  assert.deepEqual(failure, {
    retryable: true,
    rateLimited: true,
    retryAfterMs: 3_000,
    failureClass: "rate_limited",
  });
});

test("chat queue sends configured free-only Gemini to the fallback lane", () => {
  assert.equal(
    isGeminiFallbackQueueConfigured({
      config: {
        GEMINI_API_KEY: "free-key",
        GEMINI_FREE_ONLY: true,
        GEMINI_PAID_FALLBACK_ENABLED: false,
        GEMINI_PAID_DATA_PROCESSING_ATTESTED: false,
      },
    } as never),
    true,
  );
  assert.equal(
    isGeminiFallbackQueueConfigured({
      config: {
        GEMINI_API_KEY: "   ",
        GEMINI_FREE_ONLY: true,
      },
    } as never),
    false,
  );
});

test("chat queue does not retry policy denials or permanent 4xx errors", () => {
  for (const error of [
    new AppError(503, "server_brain_unavailable", "safe", {
      transient: true,
      retrySuggested: true,
      attemptFailures: [
        {
          failureClass: "policy_blocked",
          retryAfterMs: null,
        },
      ],
    }),
    new AppError(403, "provider_rejected", "safe", {
      transient: true,
      retrySuggested: true,
      failureClass: "rejected",
    }),
  ]) {
    assert.equal(readChatGenerationQueueFailure(error).retryable, false);
  }
});

test("chat queue retries transient failures and preserves Retry-After", () => {
  for (const failureClass of ["rate_limited", "timeout", "unavailable"]) {
    const failure = readChatGenerationQueueFailure(
      new AppError(
        failureClass === "rate_limited" ? 429 : 503,
        "server_brain_unavailable",
        "safe",
        {
          transient: true,
          retrySuggested: true,
          failureClass,
          retryAfterMs: 4_250,
        },
      ),
    );
    assert.equal(failure.retryable, true);
    assert.equal(failure.retryAfterMs, 4_250);
  }
  assert.equal(
    readChatGenerationQueueFailure(new TypeError("network request failed"))
      .retryable,
    true,
  );
  assert.equal(
    readChatGenerationQueueFailure(
      new DOMException("request timed out", "AbortError"),
    ).retryable,
    true,
  );
});

test("primary and fallback lanes share one per-replica concurrency gate", async () => {
  const withLocalConcurrency = createLocalConcurrencyGate(4);
  let active = 0;
  let maxActive = 0;
  await Promise.all(
    Array.from({ length: 16 }, () =>
      withLocalConcurrency(async () => {
        active += 1;
        maxActive = Math.max(maxActive, active);
        await new Promise((resolve) => setTimeout(resolve, 5));
        active -= 1;
      }),
    ),
  );
  assert.equal(maxActive, 4);
});

test("chat generation lease fence permanently cancels work after renewal loss", () => {
  const fence = createChatGenerationLeaseFence();
  assert.equal(fence.shouldAbort(), false);
  fence.markLost();
  assert.equal(fence.shouldAbort(), true);
  fence.markLost();
  assert.equal(fence.shouldAbort(), true);
});
