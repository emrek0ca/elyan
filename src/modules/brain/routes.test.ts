import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
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
