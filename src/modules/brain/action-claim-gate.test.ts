import assert from "node:assert/strict";
import test from "node:test";
import {
  evaluateActionClaimEvidence,
  type ActionClaimSemantics,
} from "./action-claim-gate.js";

const performedActionSemantics: ActionClaimSemantics = {
  assertsPerformedAction: true,
  actionSummary: "created a file on the desktop",
  confidence: 0.92,
};

const noActionSemantics: ActionClaimSemantics = {
  assertsPerformedAction: false,
  actionSummary: "",
  confidence: 0.9,
};

// Üretim vakası 33e3f4e8: "elyan-test.txt dosyası oluşturuluyor..." metni
// shared_brain rotasında, sıfır araç, sıfır artefakt ile completed yazıldı.
// Bu tam olarak reddedilmesi gereken durumdur.
test("fabricated: action claim on shared_brain with no executed tools is rejected", () => {
  const decision = evaluateActionClaimEvidence({
    route: "shared_brain",
    executedToolCount: 0,
    hasArtifactEvidence: false,
    fallbackUsed: false,
    hasVisibleText: true,
    semantics: performedActionSemantics,
  });
  assert.equal(decision.fabricated, true);
  assert.equal(decision.reason, "action_claim_without_execution");
  assert.equal(decision.actionSummary, "created a file on the desktop");
});

// RC-5 karşı-kanıt: gerçek araç yürüdüyse iddia uydurma DEĞİLDİR.
test("not fabricated: executed tools count as evidence even with an action claim", () => {
  const decision = evaluateActionClaimEvidence({
    route: "shared_brain",
    executedToolCount: 2,
    hasArtifactEvidence: false,
    fallbackUsed: false,
    hasVisibleText: true,
    semantics: performedActionSemantics,
  });
  assert.equal(decision.fabricated, false);
  assert.equal(decision.reason, "tools_executed");
});

// Görsel üretimi gibi bir artefakt varsa iddia uydurma DEĞİLDİR.
test("not fabricated: a produced artifact counts as evidence", () => {
  const decision = evaluateActionClaimEvidence({
    route: "shared_brain",
    executedToolCount: 0,
    hasArtifactEvidence: true,
    fallbackUsed: false,
    hasVisibleText: true,
    semantics: performedActionSemantics,
  });
  assert.equal(decision.fabricated, false);
  assert.equal(decision.reason, "artifact_produced");
});

// Saf sohbet turu ("bugün nasılsın") eylem iddiası içermez → asla reddedilmez.
test("not fabricated: a plain conversational reply is never blocked", () => {
  const decision = evaluateActionClaimEvidence({
    route: "shared_brain",
    executedToolCount: 0,
    hasArtifactEvidence: false,
    fallbackUsed: false,
    hasVisibleText: true,
    semantics: noActionSemantics,
  });
  assert.equal(decision.fabricated, false);
  assert.equal(decision.reason, "no_action_claim");
});

// KIRMIZI ÇİZGİ / RC-5: semantik karar veremediğinde (Gemini yok) gereksiz
// yere REDDETMEK YASAK. Kapı izin verir.
test("not fabricated: semantics unavailable never over-rejects", () => {
  const decision = evaluateActionClaimEvidence({
    route: "shared_brain",
    executedToolCount: 0,
    hasArtifactEvidence: false,
    fallbackUsed: false,
    hasVisibleText: true,
    semantics: null,
  });
  assert.equal(decision.fabricated, false);
  assert.equal(decision.reason, "semantics_unavailable");
});

// Etiketli continuity/degraded geri-düşüş zaten dürüst bir yanıttır → geçer.
test("not fabricated: labeled fallback turns are exempt", () => {
  const decision = evaluateActionClaimEvidence({
    route: "shared_brain",
    executedToolCount: 0,
    hasArtifactEvidence: false,
    fallbackUsed: true,
    hasVisibleText: true,
    semantics: performedActionSemantics,
  });
  assert.equal(decision.fabricated, false);
  assert.equal(decision.reason, "labeled_fallback");
});

// Masaüstü rotası gerçek yürütme semantiğine sahiptir → bu kapı devreye girmez.
test("not fabricated: non-shared_brain routes are out of scope", () => {
  const decision = evaluateActionClaimEvidence({
    route: "desktop",
    executedToolCount: 0,
    hasArtifactEvidence: false,
    fallbackUsed: false,
    hasVisibleText: true,
    semantics: performedActionSemantics,
  });
  assert.equal(decision.fabricated, false);
  assert.equal(decision.reason, "not_shared_brain");
});

// Düşük güvenli eylem iddiası eşiği geçemez → reddedilmez (gürültüye karşı).
test("not fabricated: low-confidence action claim stays below threshold", () => {
  const decision = evaluateActionClaimEvidence({
    route: "shared_brain",
    executedToolCount: 0,
    hasArtifactEvidence: false,
    fallbackUsed: false,
    hasVisibleText: true,
    semantics: {
      assertsPerformedAction: true,
      actionSummary: "maybe inspected the screen",
      confidence: 0.4,
    },
  });
  assert.equal(decision.fabricated, false);
  assert.equal(decision.reason, "no_action_claim");
});
