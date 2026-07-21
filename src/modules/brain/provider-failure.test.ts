import assert from "node:assert/strict";
import test from "node:test";
import {
  buildProviderAttemptFailure,
  providerHttpStatusClass,
  providerRetryDelayMs,
  readProviderRetryAfterMs,
  summarizeProviderAttemptFailures,
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

test("provider policy denials remain non-transient classifications", () => {
  for (const reason of [
    "policy_blocked:data_sharing_consent_required",
    "private_data_blocked",
    "paid_fallback_disabled",
  ]) {
    const failure = buildProviderAttemptFailure({
      provider: "gemini",
      model: "fast",
      attempt: 1,
      error: { status: 403, reason },
    });
    assert.equal(failure.failureClass, "policy_blocked");
  }
});

test("provider failure summary keeps policy-only exhaustion non-retryable", () => {
  const summary = summarizeProviderAttemptFailures([
    {
      provider: "gemini",
      model: "flash",
      status: 403,
      failureClass: "policy_blocked",
      reason: "data_sharing_consent_required",
      retryAfterMs: null,
      attempt: 1,
    },
  ]);

  assert.deepEqual(summary, {
    failureClass: "policy_blocked",
    providerStatus: 403,
    retryAfterMs: null,
    transient: false,
    retrySuggested: false,
  });
});

test("provider failure summary preserves transient evidence across candidates", () => {
  const summary = summarizeProviderAttemptFailures([
    {
      provider: "groq",
      model: "fast",
      status: 429,
      failureClass: "rate_limited",
      reason: "rate_limited",
      retryAfterMs: 5_000,
      attempt: 1,
    },
    {
      provider: "gemini",
      model: "flash",
      status: 403,
      failureClass: "policy_blocked",
      reason: "private_data_blocked",
      retryAfterMs: null,
      attempt: 1,
    },
  ]);

  assert.deepEqual(summary, {
    failureClass: "rate_limited",
    providerStatus: 429,
    retryAfterMs: 5_000,
    transient: true,
    retrySuggested: true,
  });
});

test("TypeError provider failures are classified as transient network failures", () => {
  const failure = buildProviderAttemptFailure({
    provider: "groq",
    model: "fast",
    attempt: 1,
    error: new TypeError("fetch failed with private transport detail"),
  });

  assert.equal(failure.failureClass, "unavailable");
  assert.equal(failure.reason, "TypeError");
});
