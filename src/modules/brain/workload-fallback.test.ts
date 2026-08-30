import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import { resolveWorkloadFallbackRetry } from "./inference.js";

const unavailable = (details: Record<string, unknown>) =>
  new AppError(503, "server_brain_unavailable", "ulaşamıyorum", details);

/**
 * KAÇIŞ KAPAĞI TANIMLIYDI AMA HİÇ AÇILMIYORDU.
 *
 * `fallbackWorkload` her profilde vardı ve kod tabanında TEK BİR TÜKETİCİSİ
 * yoktu. Canlıda ölçüldü: "pdf olarak ver" turunda `document_generate`
 * zinciri tüketti, tanımlı yedeği (`document_analysis`) denenmedi ve
 * kullanıcı hiçbir cevap almadı.
 */
test("an output-shape failure falls back to the simpler workload", () => {
  const fallback = resolveWorkloadFallbackRetry(
    unavailable({
      failureClass: "invalid_output",
      attemptFailures: [{ reason: "provider_error:json_validate_failed" }],
    }),
    { prompt: "pdf ver", userId: "u1", workload: "document_generate" } as never,
  );
  assert.equal(fallback, "document_analysis");
});

/**
 * KAPASİTE arızası yeniden denemeyi HAK ETMEZ: sağlayıcı zaten yüklü, ikinci
 * tur yalnız kullanıcıyı bekletir ve yükü artırır.
 */
test("a capacity failure is not retried on another workload", () => {
  const fallback = resolveWorkloadFallbackRetry(
    unavailable({
      failureClass: "rate_limited",
      attemptFailures: [{ reason: "provider_rate_limited" }],
    }),
    { prompt: "pdf ver", userId: "u1", workload: "document_generate" } as never,
  );
  assert.equal(fallback, null);
});

/** Yedeğin yedeği denenmez — özyineleme olamaz. */
test("a fallback attempt does not fall back again", () => {
  const fallback = resolveWorkloadFallbackRetry(
    unavailable({ failureClass: "invalid_output" }),
    {
      prompt: "pdf ver",
      userId: "u1",
      workload: "document_generate",
      internalEvaluation: { refinementPass: true },
    } as never,
  );
  assert.equal(fallback, null);
});

test("an unrelated error is never turned into a retry", () => {
  assert.equal(
    resolveWorkloadFallbackRetry(new Error("beklenmeyen"), {
      prompt: "x",
      userId: "u1",
      workload: "document_generate",
    } as never),
    null,
  );
});
