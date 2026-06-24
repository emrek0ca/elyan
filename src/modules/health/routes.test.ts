import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { healthRoutes } from "./routes.js";

test("control-plane health alias returns minimal public diagnostics", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch;
  const app = Fastify();
  Object.assign(app, {
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      DATABASE_URL: "postgres://user:pass@db:5432/elyan",
      IYZICO_API_KEY: "api",
      IYZICO_SECRET_KEY: "secret",
      IYZICO_MERCHANT_ID: "merchant",
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "https://brain.example.com",
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
    },
    db: {
      execute: async () => [{ ok: 1 }],
    },
  });

  await app.register(healthRoutes);

  const response = await app.inject({
    method: "GET",
    url: "/control-plane/health",
  });

  assert.equal(response.statusCode, 200);
  assert.equal(response.json().ok, true);
  assert.equal(response.json().mobile.statusSummary, "ready");
  assert.equal(response.json().realtime.sseEnabled, true);
  assert.equal(response.json().realtime.websocketEnabled, true);
  assert.equal(Array.isArray(response.json().coreSurfaces), true);
  assert.equal("agent" in response.json(), false);
  assert.equal("brainControl" in response.json(), false);
  assert.equal("retrieval" in response.json(), false);

  await app.close();
  globalThis.fetch = originalFetch;
});
