import assert from "node:assert/strict";
import test from "node:test";
import { sanitizePublicErrorDetails } from "./public-error-details.js";

test("public error details preserve actionable fields and remove compound internals", () => {
  assert.deepEqual(sanitizePublicErrorDetails({
    retryAfterMs: 1_000,
    requiredPlanCodes: ["pro"],
    secondaryVisionProvider: "gemini",
    servingModel: "private-model",
    providerStatus: 429,
    failureClass: "rate_limited",
    attemptFailures: [
      {
        provider: "gemini",
        model: "private-model",
        status: 429,
        retryAfterMs: 4_000,
      },
    ],
    debug: { rawResponse: "secret" },
  }), {
    retryAfterMs: 1_000,
    requiredPlanCodes: ["pro"],
  });
});
