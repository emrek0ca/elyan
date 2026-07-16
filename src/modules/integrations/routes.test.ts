import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { integrationAppRoutes } from "./routes.js";

test("shipping integration app surface does not expose direct Gmail send", async () => {
  const app = Fastify();
  app.decorate("authenticateUser", async (request) => {
    request.auth = {
      kind: "user",
      sub: "user-1",
      sessionId: "session-1",
      email: "user@example.com",
    };
  });
  app.decorate("authenticateRuntime", async (_request, reply) => {
    reply.code(401).send({ error: "unauthorized" });
  });

  await app.register(integrationAppRoutes, { prefix: "/v1/integrations" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/integrations/gmail/send",
    payload: {
      to: ["target@example.com"],
      subject: "Test",
      body: "This must not bypass connector write approvals.",
    },
  });

  assert.equal(response.statusCode, 404);
  await app.close();
});
