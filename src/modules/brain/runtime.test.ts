import assert from "node:assert/strict";
import test from "node:test";
import { getSharedBrainRuntimeSnapshot, warmSharedBrainRuntime } from "./runtime.js";

test("shared brain runtime falls back to the next healthy provider", async () => {
  const originalFetch = globalThis.fetch;
  const requestedUrls: string[] = [];

  globalThis.fetch = async (input: RequestInfo | URL) => {
    const url = String(input);
    requestedUrls.push(url);

    if (url.includes("primary.example.com")) {
      return new Response("unavailable", { status: 503 });
    }

    return new Response("{}", { status: 200 });
  };

  const app = {
    config: {
      ELYAN_SHARED_BRAIN_PROVIDER: "vllm",
      ELYAN_SHARED_BRAIN_BASE_URL: "https://primary.example.com",
      ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL: "https://fallback.example.com",
    },
  };

  try {
    const configSnapshot = getSharedBrainRuntimeSnapshot(app as never);
    assert.equal(configSnapshot.provider, "vllm");
    assert.equal(configSnapshot.ready, false);

    const warmSnapshot = await warmSharedBrainRuntime(app as never);

    assert.equal(warmSnapshot.provider, "ollama");
    assert.equal(warmSnapshot.ready, true);
    assert.ok(requestedUrls.some((url) => url.includes("primary.example.com")));
    assert.ok(requestedUrls.some((url) => url.includes("fallback.example.com")));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("shared brain runtime stays unavailable when no provider probes pass", async () => {
  const originalFetch = globalThis.fetch;
  const requestedUrls: string[] = [];

  globalThis.fetch = async (input: RequestInfo | URL) => {
    requestedUrls.push(String(input));
    return new Response("unavailable", { status: 503 });
  };

  const app = {
    config: {
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "https://primary.example.com",
      ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER: "llamacpp",
      ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL: "https://fallback.example.com",
    },
  };

  try {
    const warmSnapshot = await warmSharedBrainRuntime(app as never);

    assert.equal(warmSnapshot.provider, "ollama");
    assert.equal(warmSnapshot.ready, false);
    assert.ok(requestedUrls.some((url) => url.includes("primary.example.com")));
    assert.ok(requestedUrls.some((url) => url.includes("fallback.example.com")));
  } finally {
    globalThis.fetch = originalFetch;
  }
});
