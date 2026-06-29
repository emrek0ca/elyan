import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../errors.js";
import { recordCircuitFailure, recordCircuitSuccess, getCircuitState, isCircuitCallAllowed } from "./circuit-breaker.js";
import { tryAcquireLoadSheddingPermit, withLoadSheddingPermit } from "./load-shedding.js";
import { assertRequestBudget, enforceRouteRequestBudget } from "./request-budget.js";
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

function createAdmissionApp(input: {
  nodeEnv?: "development" | "test" | "production";
  store?: ReliabilityStore;
  planCode?: string;
}) {
  const store = input.store ?? createMemoryStore();
  return {
    config: {
      NODE_ENV: input.nodeEnv ?? "test",
      REQUEST_BUDGET_WINDOW_MS: 60_000,
      AUTH_REQUEST_BUDGET_MAX: 10,
      CHAT_REQUEST_BUDGET_MAX: 60,
      TASK_REQUEST_BUDGET_MAX: 60,
    },
    services: {
      reliability: {
        store,
      },
    },
    db: {
      select() {
        return {
          from() {
            return this;
          },
          where() {
            return this;
          },
          limit: async () => [{ planCode: input.planCode ?? "free" }],
        };
      },
    },
  };
}

function createAdmissionRequest(input: {
  method: string;
  url: string;
  userId?: string;
  planCode?: string;
  ip?: string;
  body?: Record<string, unknown>;
}): never {
  return {
    method: input.method,
    url: input.url,
    ip: input.ip ?? "203.0.113.10",
    headers: {
      "user-agent": "elyan-test",
      "x-elyan-device-id": "device-1",
    },
    auth: input.userId
      ? {
          sub: input.userId,
          planCode: input.planCode,
        }
      : undefined,
    body: input.body,
  } as never;
}

test("admission applies plan-aware chat budgets before expensive brain work", async () => {
  const freeApp = createAdmissionApp({ planCode: "free" });
  for (let i = 0; i < 40; i += 1) {
    await enforceRouteRequestBudget(
      freeApp as never,
      createAdmissionRequest({
        method: "POST",
        url: "/v1/chat/messages",
        userId: "free-user",
        body: { content: `hello ${i}` },
      }),
    );
  }
  await assert.rejects(
    () =>
      enforceRouteRequestBudget(
        freeApp as never,
        createAdmissionRequest({
          method: "POST",
          url: "/v1/chat/messages",
          userId: "free-user",
          body: { content: "hello over limit" },
        }),
      ),
    (error) => error instanceof AppError && error.statusCode === 429 && error.code === "rate_limited",
  );

  const proApp = createAdmissionApp({ planCode: "pro" });
  for (let i = 0; i < 60; i += 1) {
    await enforceRouteRequestBudget(
      proApp as never,
      createAdmissionRequest({
        method: "POST",
        url: "/v1/chat/messages",
        userId: "pro-user",
        body: { content: `hello ${i}` },
      }),
    );
  }
});

test("admission throttles repeated auth attempts by ip and credential", async () => {
  const app = createAdmissionApp({});
  for (let i = 0; i < 4; i += 1) {
    await enforceRouteRequestBudget(
      app as never,
      createAdmissionRequest({
        method: "POST",
        url: "/v1/auth/login",
        body: { email: "person@example.com" },
      }),
    );
  }
  await assert.rejects(
    () =>
      enforceRouteRequestBudget(
        app as never,
        createAdmissionRequest({
          method: "POST",
          url: "/v1/auth/login",
          body: { email: "person@example.com" },
        }),
      ),
    (error) => error instanceof AppError && error.statusCode === 429 && error.code === "rate_limited",
  );
});

test("admission allows normal authenticated chat cadence", async () => {
  const app = createAdmissionApp({ planCode: "solo" });
  for (let i = 0; i < 8; i += 1) {
    await enforceRouteRequestBudget(
      app as never,
      createAdmissionRequest({
        method: "POST",
        url: "/v1/chat/messages",
        userId: "solo-user",
        body: { content: `normal message ${i}` },
      }),
    );
  }
});

test("admission tightens production limits when Redis is unavailable", async () => {
  const app = createAdmissionApp({
    nodeEnv: "production",
    store: createMemoryStore(),
    planCode: "free",
  });
  for (let i = 0; i < 20; i += 1) {
    await enforceRouteRequestBudget(
      app as never,
      createAdmissionRequest({
        method: "POST",
        url: "/v1/chat/messages",
        userId: "degraded-user",
        body: { content: `degraded ${i}` },
      }),
    );
  }
  await assert.rejects(
    () =>
      enforceRouteRequestBudget(
        app as never,
        createAdmissionRequest({
          method: "POST",
          url: "/v1/chat/messages",
          userId: "degraded-user",
          body: { content: "degraded over limit" },
        }),
      ),
    (error) => error instanceof AppError && error.statusCode === 429,
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
