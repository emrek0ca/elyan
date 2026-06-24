import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { chatRoutes } from "./routes.js";

test("chat sessions require authenticated user", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(chatRoutes, { prefix: "/v1/chat" });

  const response = await app.inject({
    method: "GET",
    url: "/v1/chat/sessions",
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});

test("chat session archive, delete and clear routes require authenticated user", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(chatRoutes, { prefix: "/v1/chat" });

  const sessionId = "11111111-1111-4111-8111-111111111111";
  const archiveResponse = await app.inject({
    method: "PATCH",
    url: `/v1/chat/sessions/${sessionId}`,
    payload: {
      status: "archived",
    },
  });
  const deleteResponse = await app.inject({
    method: "DELETE",
    url: `/v1/chat/sessions/${sessionId}`,
  });
  const clearResponse = await app.inject({
    method: "DELETE",
    url: "/v1/chat/sessions",
  });

  assert.equal(archiveResponse.statusCode, 401);
  assert.equal(deleteResponse.statusCode, 401);
  assert.equal(clearResponse.statusCode, 401);
  await app.close();
});
