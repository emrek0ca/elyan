import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import { AppError } from "../../lib/errors.js";
import {
  acquireProviderRequestPermit,
  joinProviderUrl,
} from "./provider-http.js";

function rateLimitApp(input: {
  allowed: boolean;
  redisReady?: boolean;
  required?: boolean;
}) {
  const calls: Array<{
    key: string;
    amount: number;
    limit: number;
    ttlMs: number;
    requireRedis: boolean;
  }> = [];
  const app = {
    config: {
      RELIABILITY_REDIS_REQUIRED: input.required ?? true,
      ELYAN_GROQ_RPM_LIMIT: 30,
      ELYAN_GEMINI_RPM_LIMIT: 10,
    },
    services: {
      reliability: {
        store: {
          tryConsumeBudget: async (
            key: string,
            amount: number,
            limit: number,
            ttlMs: number,
            requireRedis: boolean,
          ) => {
            calls.push({ key, amount, limit, ttlMs, requireRedis });
            return { allowed: input.allowed, used: input.allowed ? 1 : limit };
          },
          ping: async () => input.redisReady ?? true,
        },
      },
    },
  } as unknown as FastifyInstance;
  return { app, calls };
}

test("joinProviderUrl normalizes duplicate v1 path segments", () => {
  assert.equal(
    joinProviderUrl("https://api.example.com/v1/", "/v1/chat/completions"),
    "https://api.example.com/v1/chat/completions",
  );
});

test("joinProviderUrl accepts paths with or without a leading slash", () => {
  assert.equal(
    joinProviderUrl("http://127.0.0.1:11434", "api/chat"),
    "http://127.0.0.1:11434/api/chat",
  );
});

test("hosted provider request permits use the configured organization-wide limit", async () => {
  const { app, calls } = rateLimitApp({ allowed: true });
  await acquireProviderRequestPermit(app, "groq", 120_500);
  await acquireProviderRequestPermit(app, "gemini", 120_500);
  await acquireProviderRequestPermit(app, "ollama", 120_500);

  assert.equal(calls.length, 2);
  assert.deepEqual(
    calls.map((call) => ({
      key: call.key,
      amount: call.amount,
      limit: call.limit,
      requireRedis: call.requireRedis,
    })),
    [
      {
        key: "provider-rate:groq:requests:120000",
        amount: 1,
        limit: 30,
        requireRedis: true,
      },
      {
        key: "provider-rate:gemini:requests:120000",
        amount: 1,
        limit: 10,
        requireRedis: true,
      },
    ],
  );
  assert.equal(calls[0]?.ttlMs, 64_500);
});

test("hosted provider request limit returns a safe retry-after error", async () => {
  const { app } = rateLimitApp({ allowed: false, redisReady: true });
  await assert.rejects(
    () => acquireProviderRequestPermit(app, "groq", 120_500),
    (error: unknown) => {
      assert.ok(error instanceof AppError);
      assert.equal(error.statusCode, 429);
      assert.equal(error.code, "rate_limited");
      assert.deepEqual(error.details, {
        transient: true,
        retrySuggested: true,
        failureClass: "rate_limited",
        retryAfterMs: 59_500,
        retryAfterSeconds: 60,
      });
      return true;
    },
  );
});

test("required Redis outage fails closed instead of pretending the provider is full", async () => {
  const { app } = rateLimitApp({ allowed: false, redisReady: false });
  await assert.rejects(
    () => acquireProviderRequestPermit(app, "gemini", 120_500),
    (error: unknown) => {
      assert.ok(error instanceof AppError);
      assert.equal(error.statusCode, 503);
      assert.equal(error.code, "server_brain_unavailable");
      assert.equal(
        (error.details as Record<string, unknown>).failureClass,
        "rate_limit_store_unavailable",
      );
      return true;
    },
  );
});
