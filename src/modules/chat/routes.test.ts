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

test("a runtime token can never carry a desktop access grant", async () => {
  const app = Fastify();
  app.decorate("authenticateUserOrRuntime", async (request) => {
    (request as unknown as { auth: unknown }).auth = {
      kind: "runtime",
      sub: "11111111-1111-4111-8111-111111111111",
      deviceId: "22222222-2222-4222-8222-222222222222",
      connectionId: "33333333-3333-4333-8333-333333333333",
    };
  });
  app.setErrorHandler((error, _request, reply) => {
    const statusCode = (error as { statusCode?: number }).statusCode ?? 500;
    reply.code(statusCode).send({ code: (error as { code?: string }).code ?? "ERROR" });
  });

  await app.register(chatRoutes, { prefix: "/v1/chat" });

  const targetDeviceId = "22222222-2222-4222-8222-222222222222";
  const response = await app.inject({
    method: "POST",
    url: "/v1/chat/messages",
    payload: {
      content: "Masaüstünde bir şey yap",
      targetDeviceId,
      desktopAccess: {
        mode: "task",
        targetDeviceId,
        clientGrantId: "44444444-4444-4444-8444-444444444444",
      },
    },
  });

  // Masaüstü erişimi bir KULLANICI yetkilendirmesidir; runtime token'ı kendi
  // kendine grant üretemez.
  assert.equal(response.statusCode, 403);
  await app.close();
});
