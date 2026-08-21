import assert from "node:assert/strict";
import test from "node:test";
import {
  FAILURE_CLASSES,
  FAILURE_TAXONOMY,
  classifyFailureCode,
  failureTaxonomyEntries,
  isAuthorizationFailureCode,
} from "./failure-taxonomy.js";

// ---------------------------------------------------------------------------
// Taksonomi iş emrine yazılır ve masaüstü aynı kaynaktan üretilen tabloyla
// okur. Canlı arıza (2026-08-21): masaüstü tabloyu okumayıp metin eşleşmeli
// kendi merdivenini kullanıyordu; `CAPABILITY_SCOPE_MISMATCH` güvenlik reddi
// sanıldı ve tur yarım yan etkiyle öldü.
// ---------------------------------------------------------------------------

test("failure taxonomy is well formed", () => {
  assert.equal(FAILURE_TAXONOMY.contract, "elyan.failure_taxonomy.v1");
  const codes = new Set<string>();
  for (const entry of failureTaxonomyEntries()) {
    assert.equal(codes.has(entry.code), false, `yinelenen kod: ${entry.code}`);
    codes.add(entry.code);
    assert.ok(FAILURE_CLASSES.includes(entry.class));
    assert.equal(entry.code, entry.code.toUpperCase());
  }
  for (const code of FAILURE_TAXONOMY.authorizationCodes) {
    assert.ok(codes.has(code), `yetki kodu tabloda yok: ${code}`);
  }
});

test("scope mismatch replans while genuine denials stay fail-closed", () => {
  const mismatch = classifyFailureCode("CAPABILITY_SCOPE_MISMATCH");
  assert.equal(mismatch.class, "capability");
  assert.equal(mismatch.replanAllowed, true);
  assert.equal(mismatch.retryable, false);

  for (const denial of [
    "EXPLICIT_APPROVAL_REQUIRED",
    "CAPABILITY_GRANT_DENIED",
    "CAPABILITY_GRANT_REPLAY",
    "WORK_ORDER_TRUST_MISSING",
  ]) {
    const entry = classifyFailureCode(denial);
    assert.equal(entry.replanAllowed, false, denial);
    assert.equal(entry.retryable, false, denial);
    assert.equal(isAuthorizationFailureCode(denial), true, denial);
  }
});

test("an unknown code falls back to the declared default", () => {
  const entry = classifyFailureCode("brand_new_failure");
  assert.equal(entry.class, FAILURE_TAXONOMY.unknownDefault.class);
  assert.equal(entry.retryable, FAILURE_TAXONOMY.unknownDefault.retryable);
  assert.equal(isAuthorizationFailureCode("brand_new_failure"), false);
});
