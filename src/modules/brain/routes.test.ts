import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { readFile } from "node:fs/promises";
import { brainRoutes } from "./routes.js";

test("brain profile requires authenticated user", async () => {
  const app = Fastify();
  // /profile artık kullanıcı VEYA runtime token kabul eder.
  app.decorate("authenticateUserOrRuntime", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(brainRoutes, { prefix: "/v1/brain" });

  const response = await app.inject({
    method: "GET",
    url: "/v1/brain/profile",
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});

test("brain chat requires authenticated user", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(brainRoutes, { prefix: "/v1/brain" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/brain/chat",
    payload: {
      prompt: "Selam",
    },
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});

test("brain chat captures explicit profile facts before rebuilding user context", async () => {
  const source = await readFile(
    new URL(
      import.meta.url.endsWith(".ts") ? "./routes.ts" : "./routes.js",
      import.meta.url,
    ),
    "utf8",
  );
  const chatStart = source.indexOf('app.post("/chat"');
  const chatEnd = source.indexOf('app.post("/connector-writes', chatStart);
  const chatRoute = source.slice(chatStart, chatEnd);
  const captureAt = chatRoute.indexOf("recordTaskLearningFromCreation");
  const retrieveAt = chatRoute.indexOf("buildTaskUnderstanding");

  assert.ok(
    captureAt >= 0,
    "chat route must call the existing learning capture path",
  );
  assert.ok(
    retrieveAt >= 0,
    "chat route must rebuild the full typed understanding context",
  );
  assert.ok(
    captureAt < retrieveAt,
    "explicit facts must be persisted before same-turn retrieval",
  );
});

test("connector write approval requires authenticated user", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(brainRoutes, { prefix: "/v1/brain" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/brain/connector-writes/11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222",
    payload: {
      approved: true,
    },
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});

test("connector write approval returns safe 404 for missing or expired draft", async () => {
  const app = Fastify();
  app.decorate("db", {
    select() {
      const query: any = {};
      query.from = () => query;
      query.where = () => query;
      query.limit = () => Promise.resolve([]);
      return query;
    },
  } as any);
  app.decorate("authenticateUser", async (request) => {
    request.auth = {
      kind: "user",
      sub: "user-1",
      sessionId: "session-1",
      email: "user@example.com",
    };
  });

  await app.register(brainRoutes, { prefix: "/v1/brain" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/brain/connector-writes/11111111-1111-4111-8111-111111111111.22222222-2222-4222-8222-222222222222",
    payload: {
      approved: true,
    },
  });

  assert.equal(response.statusCode, 404);
  assert.deepEqual(response.json(), {
    error: {
      code: "connector_write_not_found",
      message: "Bu taslak bulunamadı veya süresi doldu.",
    },
  });
  await app.close();
});

test("brain memory list requires authenticated user", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(brainRoutes, { prefix: "/v1/brain" });

  const response = await app.inject({
    method: "GET",
    url: "/v1/brain/memory",
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});

test("brain review interactions require authenticated user", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(brainRoutes, { prefix: "/v1/brain" });

  const response = await app.inject({
    method: "GET",
    url: "/v1/brain/review/interactions",
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});
