import assert from "node:assert/strict";
import { setImmediate as waitForImmediate } from "node:timers/promises";
import test from "node:test";
import Fastify, {
  type FastifyInstance,
  type FastifyReply,
  type FastifyRequest,
} from "fastify";
import { WEB_WARMUP_DEDUPE_MS, webRoutes } from "./routes.js";

type WebTestAppOptions = {
  authenticated?: boolean;
  acquireLock?: (
    key: string,
    owner: string,
    ttlMs: number,
  ) => Promise<boolean>;
  bootstrap?: (app: FastifyInstance, userId: string) => Promise<unknown>;
  warmup?: (app: FastifyInstance, userId: string) => Promise<void>;
  loggerStream?: { write: (line: string) => void };
};

async function createWebTestApp(options: WebTestAppOptions = {}) {
  const app = Fastify({
    disableRequestLogging: true,
    logger: options.loggerStream
      ? { level: "debug", stream: options.loggerStream }
      : false,
  });
  app.decorateRequest("auth", null as never);
  app.decorate(
    "authenticateUser",
    async (request: FastifyRequest, reply: FastifyReply) => {
      if (options.authenticated === false) {
        await reply.code(401).send({
          error: { code: "UNAUTHORIZED", message: "Authentication required" },
        });
        return;
      }
      request.auth = {
        kind: "user",
        sub: "user-secret-1",
        sessionId: "auth-session-1",
        email: "web-test@example.test",
      };
    },
  );
  if (options.acquireLock) {
    app.decorate("services", {
      reliability: {
        store: {
          acquireLock: options.acquireLock,
        },
      },
    } as never);
  }
  await app.register(webRoutes, {
    prefix: "/v1/web",
    getBootstrap:
      options.bootstrap ??
      (async (_app, userId) => ({ user: { id: userId }, source: "web" })),
    warmup: options.warmup ?? (async () => undefined),
  });
  return app;
}

test("web bootstrap and warmup both require user authentication", async () => {
  let bootstrapCalls = 0;
  let warmupCalls = 0;
  const app = await createWebTestApp({
    authenticated: false,
    bootstrap: async () => {
      bootstrapCalls += 1;
      return {};
    },
    warmup: async () => {
      warmupCalls += 1;
    },
  });

  const [bootstrap, warmup] = await Promise.all([
    app.inject({ method: "GET", url: "/v1/web/bootstrap" }),
    app.inject({ method: "POST", url: "/v1/web/warmup" }),
  ]);

  assert.equal(bootstrap.statusCode, 401);
  assert.equal(warmup.statusCode, 401);
  assert.equal(bootstrapCalls, 0);
  assert.equal(warmupCalls, 0);
  await app.close();
});

test("web bootstrap returns private conditional JSON for the authenticated user", async () => {
  const app = await createWebTestApp();
  const first = await app.inject({ method: "GET", url: "/v1/web/bootstrap" });

  assert.equal(first.statusCode, 200);
  assert.equal(first.headers["cache-control"], "private, max-age=0, must-revalidate");
  assert.equal(first.json().user.id, "user-secret-1");
  assert.equal(first.json().source, "web");
  assert.ok(first.headers.etag);

  const cached = await app.inject({
    method: "GET",
    url: "/v1/web/bootstrap",
    headers: { "if-none-match": first.headers.etag as string },
  });
  assert.equal(cached.statusCode, 304);
  await app.close();
});

test("web warmup returns 202 and atomically dedupes by an opaque TTL lock", async () => {
  const locks = new Set<string>();
  const lockCalls: Array<{ key: string; owner: string; ttlMs: number }> = [];
  let warmupCalls = 0;
  const app = await createWebTestApp({
    acquireLock: async (key, owner, ttlMs) => {
      lockCalls.push({ key, owner, ttlMs });
      if (locks.has(key)) return false;
      locks.add(key);
      return true;
    },
    warmup: async () => {
      warmupCalls += 1;
    },
  });

  const responses = await Promise.all([
    app.inject({ method: "POST", url: "/v1/web/warmup" }),
    app.inject({ method: "POST", url: "/v1/web/warmup" }),
  ]);
  await waitForImmediate();

  assert.deepEqual(
    responses.map((response) => response.statusCode),
    [202, 202],
  );
  assert.deepEqual(
    responses.map((response) => response.json().queued).sort(),
    [false, true],
  );
  assert.equal(warmupCalls, 1);
  assert.equal(lockCalls.length, 2);
  assert.equal(lockCalls[0]?.key, lockCalls[1]?.key);
  assert.equal(lockCalls[0]?.ttlMs, WEB_WARMUP_DEDUPE_MS);
  assert.equal(lockCalls[0]?.key.includes("user-secret-1"), false);
  await app.close();
});

test("web warmup fails open without a reliability store", async () => {
  let warmupCalls = 0;
  const app = await createWebTestApp({
    warmup: async () => {
      warmupCalls += 1;
    },
  });

  const response = await app.inject({ method: "POST", url: "/v1/web/warmup" });
  await waitForImmediate();

  assert.equal(response.statusCode, 202);
  assert.equal(response.json().queued, true);
  assert.equal(warmupCalls, 1);
  await app.close();
});

test("web warmup logs only safe classes when dedupe and warmup fail", async () => {
  const lines: string[] = [];
  const app = await createWebTestApp({
    loggerStream: { write: (line) => lines.push(line) },
    acquireLock: async () => {
      throw new Error("redis secret for user-secret-1");
    },
    warmup: async () => {
      throw new Error("provider secret for user-secret-1");
    },
  });

  const response = await app.inject({ method: "POST", url: "/v1/web/warmup" });
  await waitForImmediate();
  const logs = lines.join("\n");

  assert.equal(response.statusCode, 202);
  assert.equal(response.json().queued, true);
  assert.match(logs, /reliability_store_unavailable/);
  assert.match(logs, /warmup_failed/);
  assert.doesNotMatch(logs, /redis secret|provider secret|user-secret-1/);
  await app.close();
});
