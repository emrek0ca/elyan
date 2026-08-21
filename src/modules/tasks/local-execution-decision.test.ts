import assert from "node:assert/strict";
import test from "node:test";
import { decideLocalExecution } from "./local-execution-decision.js";

// ---------------------------------------------------------------------------
// KANIT UZLAŞMASI. Tek sinyal yetmiyor — ikisi de ölçüldü:
//   yetenek eşleşmesi  korpus %98.1 → tutulan %57.5 (ezber)
//   konuşma eylemi     korpus %96.2 → tutulan %66.7
// Birlikte (eval:local-execution, 38 vaka):
//   korpus  %76.9   tutulan %91.7   YANLIŞ YÜRÜTME 0 / 0
//
// Bu testler ağsız çalışır: e5 yoksa karar `evidence_unavailable` döner ve
// sonuç FAIL-CLOSED olmalıdır. Asıl güvence budur.
// ---------------------------------------------------------------------------

test("without warm semantics the decision fails closed", async () => {
  // Test sürecinde yetenek vektör önbelleği ısınmamıştır.
  const decision = await decideLocalExecution({ message: "Chrome'u kapat" });
  assert.equal(decision.requiresLocalExecution, false);
  assert.equal(decision.reason, "evidence_unavailable");
});

test("an empty message never unlocks execution", async () => {
  for (const message of ["", "   "]) {
    const decision = await decideLocalExecution({ message });
    assert.equal(decision.requiresLocalExecution, false);
    assert.equal(decision.capability, null);
  }
});

test("the decision shape always carries its reason", async () => {
  const decision = await decideLocalExecution({ message: "Chrome nedir" });
  assert.ok(
    [
      "speech_act_and_capability_agree",
      "speech_act_blocks",
      "capability_not_local_action",
      "evidence_unavailable",
    ].includes(decision.reason),
  );
  assert.equal(typeof decision.requiresLocalExecution, "boolean");
});
