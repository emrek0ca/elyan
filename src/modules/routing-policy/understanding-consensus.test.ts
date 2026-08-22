import assert from "node:assert/strict";
import test from "node:test";
import type { IntentClassification } from "../../core/understanding/types.js";
import { buildUnderstandingConsensus } from "./understanding-consensus.js";

function classification(
  overrides: Partial<IntentClassification> = {},
): IntentClassification {
  return {
    primaryIntent: "automation",
    secondaryIntents: [],
    requiresLocalRuntime: true,
    requiresRetrieval: false,
    requiresToolUse: true,
    requiresCitation: false,
    requiresLongRunningTask: false,
    privacyRisk: "high",
    confidence: 0.91,
    reason: "typed",
    taskFrame: {
      goal: "local action",
      likelyAnswerShape: "execution",
      reasoningMode: "fast",
      shouldClarify: false,
    },
    ecosystemHints: [],
    routingHints: {
      mode: "local_private",
      preferredCapabilities: ["close_app"],
      avoidCloud: true,
      requiresLocalRuntime: true,
    },
    ...overrides,
  };
}

test("consensus agrees on a direct local capability without storing model prose", () => {
  const result = buildUnderstandingConsensus({
    message: "Chrome u kapat",
    primary: classification(),
    verifier: classification(),
    verifierInvoked: true,
  });

  assert.equal(result.status, "agreed");
  assert.equal(result.targetSurface, "desktop");
  assert.equal(result.goal.objectiveHash.length, 24);
  assert.equal(result.selectedCapabilities.includes("close_app"), true);
  assert.equal(JSON.stringify(result).includes("typed"), false);
});

test("consensus fails closed when semantic candidates disagree on execution surface", () => {
  const result = buildUnderstandingConsensus({
    message: "Chrome u kapat",
    primary: classification(),
    verifier: classification({
      primaryIntent: "chat",
      requiresLocalRuntime: false,
      requiresToolUse: false,
      privacyRisk: "low",
      routingHints: {
        mode: "fast",
        preferredCapabilities: [],
        avoidCloud: false,
        requiresLocalRuntime: false,
      },
    }),
    verifierInvoked: true,
  });

  assert.equal(result.status, "clarification_required");
  assert.equal(result.conflict.targetSurface, true);
  assert.equal(result.privacy.maySendPrivateContextToServer, true);
});

// ---------------------------------------------------------------------------
// CANLI ARIZA (görev dbc7352e, 2026-08-22 17:22).
//
// "masaüstüne zürafalar hakkında bir pdf hazırla ve kaydet" isteğinde anlama
// katmanları YÜZEY konusunda ayrıştı → status "clarification_required" →
// tur sunucu sohbetine düştü → model kullanıcıya "Netleştireyim: tam olarak
// neyi yapmamı istiyorsun?" diye sordu.
//
// Kullanıcı NEREYE ve NE yapılacağını zaten söylemişti. Katmanların birbiriyle
// anlaşamaması, kullanıcının açık talimatını geçersiz kılmaz.
// ---------------------------------------------------------------------------

test("açık masaüstü hedefi yüzey çatışmasını netleştirmeye çevirmez", () => {
  const consensus = buildUnderstandingConsensus({
    message: "masaüstüne zürafalar hakkında bir pdf hazırla ve kaydet",
    primary: classification({ requiresLocalRuntime: true, privacyRisk: "high" }),
    verifier: classification({ requiresLocalRuntime: false, privacyRisk: "low" }),
    verifierInvoked: true,
    explicitTargetSurface: "desktop",
  });

  assert.notEqual(consensus.status, "clarification_required");
  assert.equal(consensus.targetSurface, "desktop");
});

test("açık hedef YOKKEN yüzey çatışması hâlâ netleştirme ister", () => {
  const consensus = buildUnderstandingConsensus({
    message: "bunu bir pdf yap",
    primary: classification({ requiresLocalRuntime: true, privacyRisk: "high" }),
    verifier: classification({ requiresLocalRuntime: false, privacyRisk: "low" }),
    verifierInvoked: true,
  });

  assert.equal(consensus.status, "clarification_required");
});
