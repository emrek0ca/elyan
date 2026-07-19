import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_USER_APPROVAL_MODE,
  decideUserToolApproval,
  normalizeUserApprovalMode,
  userApprovalModeValues,
} from "./policy.js";

test("approval mode normalization uses the safe read-only default", () => {
  assert.equal(DEFAULT_USER_APPROVAL_MODE, "read_only_auto");
  assert.equal(normalizeUserApprovalMode("read_only_auto"), "read_only_auto");
  assert.equal(normalizeUserApprovalMode("not-a-mode"), "read_only_auto");
  assert.equal(userApprovalModeValues.length, 3);
});

test("gmail.send requires approval in every user mode", () => {
  for (const mode of userApprovalModeValues) {
    assert.deepEqual(
      decideUserToolApproval({
        mode,
        permission: "side_effect",
        idempotency: "non_idempotent",
      }),
      {
        requiresApproval: true,
        automatic: false,
        reason: "side_effect",
      },
    );
  }
});

test("only trusted mode automatically permits idempotent user writes", () => {
  for (const mode of userApprovalModeValues) {
    const decision = decideUserToolApproval({
      mode,
      permission: "write",
      idempotency: "idempotent_write",
    });
    assert.equal(
      decision.requiresApproval,
      mode !== "trusted_idempotent_writes",
    );
    assert.equal(
      decision.automatic,
      mode === "trusted_idempotent_writes",
    );
  }
});

test("non-idempotent actions cannot be waived by a user mode", () => {
  for (const mode of userApprovalModeValues) {
    const decision = decideUserToolApproval({
      mode,
      permission: "write",
      idempotency: "non_idempotent",
    });
    assert.equal(decision.requiresApproval, true);
    assert.equal(decision.automatic, false);
  }
});

test("internal scope cannot waive a non-idempotent action", () => {
  const decision = decideUserToolApproval({
    mode: "trusted_idempotent_writes",
    permission: "write",
    idempotency: "non_idempotent",
    scope: "internal_state",
  });
  assert.equal(decision.requiresApproval, true);
  assert.equal(decision.automatic, false);
});

test("typed internal state writes keep the existing automatic engine path", () => {
  const decision = decideUserToolApproval({
    mode: "always_ask",
    permission: "write",
    idempotency: "internal_state_write",
    scope: "internal_state",
  });
  assert.equal(decision.requiresApproval, false);
  assert.equal(decision.automatic, true);
  assert.equal(decision.reason, "internal_state_policy");
});

test("an exact resolved approval can authorize an immutable approval class", () => {
  assert.deepEqual(
    decideUserToolApproval({
      mode: "trusted_idempotent_writes",
      permission: "side_effect",
      idempotency: "non_idempotent",
      explicitApproval: true,
    }),
    {
      requiresApproval: false,
      automatic: false,
      reason: "explicit_approval",
    },
  );
});
