import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { pairingRoutes } from "./routes.js";

test("create pairing session rejects an invalid bearer token", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(pairingRoutes, { prefix: "/v1/pairing" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/pairing/sessions",
    headers: {
      authorization: "Bearer invalid-token",
    },
    payload: {
      deviceLabel: "Elyan",
      platform: "macos",
      externalDeviceId: "desktop-ext-1",
    },
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});

test("create pairing session without auth header skips user authentication", async () => {
  const app = Fastify();
  let authenticateCalled = false;
  app.decorate("authenticateUser", async (_request, reply) => {
    authenticateCalled = true;
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(pairingRoutes, { prefix: "/v1/pairing" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/pairing/sessions",
    payload: {
      deviceLabel: "Elyan",
      platform: "macos",
      externalDeviceId: "desktop-ext-1",
    },
  });

  // Anonim istek auth katmanına girmez; 401 dışı bir sonuç üretir (bu çıplak
  // test app'inde db olmadığından 500 döner — sözleşme "401 değil"dir).
  assert.equal(authenticateCalled, false);
  assert.notEqual(response.statusCode, 401);
  await app.close();
});
