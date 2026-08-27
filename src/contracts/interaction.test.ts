import assert from "node:assert/strict";
import test from "node:test";
import {
  buildInteractionEnvelope,
  interactionActionsForKind,
  interactionEnvelopeSchema,
  isInteractionActionAllowed,
  normalizeInteractionKind,
} from "./interaction.js";

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

test("kind normalization maps desktop vocabulary onto the three canonical kinds", () => {
  assert.equal(normalizeInteractionKind("clarify"), "clarification");
  assert.equal(normalizeInteractionKind("question"), "clarification");
  assert.equal(normalizeInteractionKind("desktop_plan"), "approval");
  assert.equal(normalizeInteractionKind("plan_approval"), "approval");
  // Masaüstü `kind` alanına yetenek adı yazar; bu bir izin sorusudur.
  assert.equal(normalizeInteractionKind("email_send"), "permission");
  assert.equal(normalizeInteractionKind(undefined), "permission");
});

test("the action surface is derived from the kind, never supplied by the caller", () => {
  assert.deepEqual(interactionActionsForKind("clarification"), ["answer"]);
  assert.deepEqual(interactionActionsForKind("permission"), ["approve", "reject"]);
  assert.deepEqual(interactionActionsForKind("approval"), ["approve", "reject"]);

  const built = buildInteractionEnvelope({
    id: "i-1",
    taskId: "t-1",
    taskRunId: "r-1",
    kind: "clarification",
    revision: 3,
    question: "Hangi klasöre kaydedeyim?",
    expiresAt: "2030-01-01T00:01:00.000Z",
    // Çağıran yanlış eylem yüzeyi dayatamaz: tür kazanır.
    extra: { availableActions: ["approve", "reject"], custom: "kept" },
  });
  assert.deepEqual(built.availableActions, ["answer"]);
  assert.equal((built as Record<string, unknown>).custom, "kept");
  assert.equal(built.resolution, null);
});

test("an action is only allowed where its kind actually offers it", () => {
  assert.equal(isInteractionActionAllowed("clarification", "answer"), true);
  assert.equal(isInteractionActionAllowed("clarification", "approve"), false);
  assert.equal(isInteractionActionAllowed("permission", "answer"), false);
  assert.equal(isInteractionActionAllowed("approval", "reject"), true);
});
