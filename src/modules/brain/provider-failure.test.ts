import assert from "node:assert/strict";
import test from "node:test";
import {
  buildProviderAttemptFailure,
  providerHttpStatusClass,
  providerRetryDelayMs,
  readProviderRetryAfterMs,
} from "./provider-failure.js";

test("provider failure metadata keeps retry evidence but drops raw response bodies", () => {
  const failure = buildProviderAttemptFailure({
    provider: "primary",
    model: "fast",
    attempt: 2,
    error: {
      status: 429,
      retryAfterMs: 4_000,
      body: "secret provider response",
    },
  });

  assert.deepEqual(failure, {
    provider: "primary",
    model: "fast",
    status: 429,
    failureClass: "rate_limited",
    reason: "provider_request_failed",
    retryAfterMs: 4_000,
    attempt: 2,
  });
  assert.equal("body" in failure, false);
});

test("provider retry parsing and jitter are bounded", () => {
  assert.equal(
    readProviderRetryAfterMs(new Headers({ "retry-after": "3" })),
    3_000,
  );
  assert.equal(providerRetryDelayMs(0), 120);
  assert.equal(providerRetryDelayMs(1), 300);
  assert.equal(providerHttpStatusClass(200), "2xx");
  assert.equal(providerHttpStatusClass(429), "4xx");
  assert.equal(providerHttpStatusClass(503), "5xx");
  assert.equal(providerHttpStatusClass(null), "network");
});

test("synthetic 503 output validation failures remain invalid_output", () => {
  const failure = buildProviderAttemptFailure({
    provider: "primary",
    model: "fast",
    attempt: 1,
    error: {
      status: 503,
      reason: "invalid_turn_envelope_response",
    },
  });

  assert.equal(failure.failureClass, "invalid_output");
});
