import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import { buildPersistedFailureDiagnostics } from "./service.js";

/**
 * Kullanıcı arızayı SONRADAN bildirir; o yüzden teşhis konteynerden uzun
 * yaşamalı. `docker compose up --build` her deployda logları siliyor ve
 * geriye yalnız kullanıcıya gösterilen kibar cümle kalıyordu.
 */
test("a failed turn persists why it failed, not just that it failed", () => {
  const payload = buildPersistedFailureDiagnostics(
    new AppError(503, "server_brain_unavailable", "Şu anda ulaşamıyorum.", {
      workload: "document_generate",
      failureClass: "invalid_output",
      providerStatus: "degraded",
      attemptedModels: ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
      attemptFailures: [
        { model: "openai/gpt-oss-120b", reason: "json_validate_failed" },
        { model: "openai/gpt-oss-120b", reason: "empty_stream_response" },
      ],
    }),
  );

  assert.equal(payload.errorCode, "server_brain_unavailable");
  assert.equal(payload.workload, "document_generate");
  assert.equal(payload.failureClass, "invalid_output");
  assert.deepEqual(payload.attemptedModels, [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
  ]);
  assert.equal((payload.attemptFailures as unknown[]).length, 2);
});

test("an unknown failure still records something usable", () => {
  const payload = buildPersistedFailureDiagnostics(new Error("beklenmeyen"));
  assert.equal(payload.failureClass, "unavailable");
  assert.equal("errorCode" in payload, false);
});

test("the event payload cannot grow without bound", () => {
  const payload = buildPersistedFailureDiagnostics(
    new AppError(503, "server_brain_unavailable", "x", {
      attemptFailures: Array.from({ length: 40 }, (_, index) => ({
        reason: `r${index}`,
      })),
      attemptedModels: Array.from({ length: 40 }, (_, index) => `m${index}`),
    }),
  );
  assert.equal((payload.attemptFailures as unknown[]).length, 12);
  assert.equal((payload.attemptedModels as unknown[]).length, 12);
});
