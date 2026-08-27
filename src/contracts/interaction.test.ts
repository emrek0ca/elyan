import assert from "node:assert/strict";
import test from "node:test";
import { interactionEnvelopeSchema } from "./interaction.js";

const base = {
  contract: "elyan.interaction.v1" as const,
  id: "interaction-1",
  taskId: "task-1",
  taskRunId: "run-1",
  revision: 2,
  expiresAt: "2030-01-01T00:01:00.000Z",
  resolution: null,
};

test("interaction envelope keeps clarification, permission and approval actions distinct", () => {
  assert.equal(
    interactionEnvelopeSchema.safeParse({
      ...base,
      kind: "clarification",
      availableActions: ["answer"],
      question: "Hangi klasöre kaydedeyim?",
    }).success,
    true,
  );
  for (const kind of ["permission", "approval"] as const) {
    assert.equal(
      interactionEnvelopeSchema.safeParse({
        ...base,
        kind,
        availableActions: ["approve", "reject"],
        summary: "Bu işlem için onay gerekiyor.",
      }).success,
      true,
    );
  }
});

test("interaction envelope rejects an action surface that does not match its kind", () => {
  assert.equal(
    interactionEnvelopeSchema.safeParse({
      ...base,
      kind: "clarification",
      availableActions: ["approve", "reject"],
      question: "Hangi klasöre kaydedeyim?",
    }).success,
    false,
  );
  assert.equal(
    interactionEnvelopeSchema.safeParse({
      ...base,
      kind: "permission",
      availableActions: ["answer"],
      summary: "Bu işlem için onay gerekiyor.",
    }).success,
    false,
  );
});
