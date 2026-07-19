import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import {
  CHAT_GENERATION_QUEUE_NAMES,
  chatGenerationJobId,
  createLocalConcurrencyGate,
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
