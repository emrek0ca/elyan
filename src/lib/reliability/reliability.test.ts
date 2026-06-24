import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../errors.js";
import { recordCircuitFailure, recordCircuitSuccess, getCircuitState, isCircuitCallAllowed } from "./circuit-breaker.js";
import { tryAcquireLoadSheddingPermit, withLoadSheddingPermit } from "./load-shedding.js";
import { assertRequestBudget } from "./request-budget.js";
import { ReliabilityStore } from "./redis.js";

function createMemoryStore(required = false) {
  return new ReliabilityStore({
    REDIS_URL: undefined,
    RELIABILITY_REDIS_REQUIRED: required,
  });
}

test("ReliabilityStore uses memory fallback when Redis is optional", async () => {
  const store = createMemoryStore();

  assert.equal(await store.ping(), true);
  assert.deepEqual(store.summary(), {
    mode: "memory",
    ready: true,
    required: false,
  });
  assert.equal(await store.increment("budget:test", 1000), 1);
  assert.equal(await store.increment("budget:test", 1000), 2);
});

test("ReliabilityStore reports unavailable when Redis is required and absent", async () => {
  const store = createMemoryStore(true);

  assert.equal(await store.ping(), false);
  assert.deepEqual(store.summary(), {
    mode: "memory",
    ready: false,
    required: true,
  });
});

test("circuit breaker opens, half-opens after TTL, and closes on success", async () => {
  const store = createMemoryStore();
  const key = "circuit:test";

  await recordCircuitFailure(store, key, { failureThreshold: 2, openMs: 10 }, "server_brain_unavailable");
  assert.equal((await getCircuitState(store, key)).state, "closed");

  await recordCircuitFailure(store, key, { failureThreshold: 2, openMs: 10 }, "server_brain_unavailable");
  assert.equal((await getCircuitState(store, key)).state, "open");
  assert.equal(await isCircuitCallAllowed(store, key), false);

  await new Promise((resolve) => setTimeout(resolve, 15));
  assert.equal((await getCircuitState(store, key)).state, "half_open");
  assert.equal(await isCircuitCallAllowed(store, key), true);

  await recordCircuitSuccess(store, key, 10);
  assert.equal((await getCircuitState(store, key)).state, "closed");
});

test("request budget fails closed with a safe error", async () => {
  const store = createMemoryStore();
  const app = {
    services: {
      reliability: {
        store,
      },
    },
  };

  await assertRequestBudget(app as never, {
    scope: "chat",
    identity: "user-1",
    max: 1,
    windowMs: 1000,
  });

  await assert.rejects(
    () =>
      assertRequestBudget(app as never, {
        scope: "chat",
        identity: "user-1",
        max: 1,
        windowMs: 1000,
      }),
    (error) => error instanceof AppError && error.statusCode === 429 && error.code === "request_budget_exceeded",
  );
});

test("load shedding bypasses safely when reliability storage is unavailable", async () => {
  const app = {};
  const result = await withLoadSheddingPermit(
    app as never,
    {
      namespace: "shared-brain:standard",
      maxConcurrent: 1,
      ttlMs: 1000,
    },
    async () => "ok",
  );

  assert.equal(result, "ok");
});

test("load shedding only grants the configured number of concurrent permits", async () => {
  const store = createMemoryStore();
  const app = {
    services: {
      reliability: {
        store,
      },
    },
  };

  const first = await tryAcquireLoadSheddingPermit(app as never, {
    namespace: "shared-brain:standard",
    maxConcurrent: 1,
    ttlMs: 1_000,
  });
  const second = await tryAcquireLoadSheddingPermit(app as never, {
    namespace: "shared-brain:standard",
    maxConcurrent: 1,
    ttlMs: 1_000,
  });

  assert.ok(first);
  assert.equal(second, null);

  await first.release();

  const third = await tryAcquireLoadSheddingPermit(app as never, {
    namespace: "shared-brain:standard",
    maxConcurrent: 1,
    ttlMs: 1_000,
  });

  assert.ok(third);
  await third.release();
});
