import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { mobileRoutes } from "./routes.js";

test("mobile world-signals route rejects mismatched body userId", async () => {
  const app = Fastify();
  app.decorateRequest("auth", null as never);
  app.decorate("authenticateUser", async (request) => {
    (request as typeof request & { auth: unknown }).auth = {
      kind: "user",
      sub: "user-1",
      sessionId: "auth-session-1",
    } as never;
  });
  app.decorate("config", {
    REQUEST_BUDGET_WINDOW_MS: 60_000,
  } as never);
  app.decorate("services", {
    reliability: {
      store: {
        async increment() {
          return 1;
        },
      },
    },
  } as never);

  await app.register(mobileRoutes, { prefix: "/v1/mobile" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/mobile/world-signals",
    payload: {
      schemaVersion: 1,
      clientRequestId: "req_1",
      userId: "user-2",
      deviceId: "device-ext",
      signals: [
        {
          signalId: "sig_1",
          source: "mobile",
          kind: "device",
          summary: "Device summary",
          confidence: 0.7,
          facts: { batteryBand: "normal" },
          privacy: { rawDataUploaded: false },
          createdAt: "2030-01-01T00:00:00.000Z",
        },
      ],
    },
  });

  assert.equal(response.statusCode, 403);
  assert.match(response.body, /user_mismatch/i);
  await app.close();
});
