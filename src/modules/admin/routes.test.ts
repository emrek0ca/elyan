import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { adminRoutes } from "./routes.js";

test("admin ops summary requires authenticated user", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (_request, reply) => {
    reply.code(401).send({
      code: "UNAUTHORIZED",
      message: "Unauthorized",
    });
  });

  await app.register(adminRoutes, { prefix: "/v1/admin" });

  const response = await app.inject({
    method: "GET",
    url: "/v1/admin/ops/summary",
  });

  assert.equal(response.statusCode, 401);
  await app.close();
});
