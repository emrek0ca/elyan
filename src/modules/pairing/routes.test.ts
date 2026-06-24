import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { pairingRoutes } from "./routes.js";

test("create pairing session requires authenticated user", async () => {
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
    payload: {
      deviceLabel: "Elyan",
      platform: "macos",
      externalDeviceId: "desktop-ext-1",
    },
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});
