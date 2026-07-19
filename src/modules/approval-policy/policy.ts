export const userApprovalModeValues = [
  "always_ask",
  "read_only_auto",
  "trusted_idempotent_writes",
] as const;

export type UserApprovalMode = (typeof userApprovalModeValues)[number];

export const DEFAULT_USER_APPROVAL_MODE: UserApprovalMode = "read_only_auto";

export type ApprovalToolPermission = "read" | "write" | "side_effect";
export type ApprovalToolIdempotency =
  | "read_only"
  | "idempotent_write"
  | "internal_state_write"
  | "non_idempotent";
export type ApprovalToolScope = "user_action" | "internal_state";

export type UserToolApprovalDecision = {
  requiresApproval: boolean;
  automatic: boolean;
  reason:
    | "explicit_approval"
    | "internal_state_policy"
    | "read_only"
    | "trusted_idempotent_write"
    | "side_effect"
    | "non_idempotent"
    | "write_requires_approval"
    | "unclassified";
};

export function isUserApprovalMode(value: unknown): value is UserApprovalMode {
  return (
    typeof value === "string" &&
    (userApprovalModeValues as readonly string[]).includes(value)
  );
}

export function normalizeUserApprovalMode(value: unknown): UserApprovalMode {
  return isUserApprovalMode(value) ? value : DEFAULT_USER_APPROVAL_MODE;
}

/**
 * Single approval decision seam for both agent engines and desktop resumes.
 * A user mode can never waive side effects or non-idempotent actions. Only an
 * exact, already-resolved approval may authorize those calls.
 */
export function decideUserToolApproval(input: {
  mode: UserApprovalMode;
  permission: ApprovalToolPermission | null | undefined;
  idempotency: ApprovalToolIdempotency | null | undefined;
  scope?: ApprovalToolScope;
  explicitApproval?: boolean;
}): UserToolApprovalDecision {
  if (input.explicitApproval === true) {
    return {
      requiresApproval: false,
      automatic: false,
      reason: "explicit_approval",
    };
  }

  if (input.permission === "side_effect") {
    return {
      requiresApproval: true,
      automatic: false,
      reason: "side_effect",
    };
  }

  if (input.idempotency === "non_idempotent") {
    return {
      requiresApproval: true,
      automatic: false,
      reason: "non_idempotent",
    };
  }

  if (
    input.scope === "internal_state" &&
    input.permission === "write" &&
    input.idempotency === "internal_state_write"
  ) {
    return {
      requiresApproval: false,
      automatic: true,
      reason: "internal_state_policy",
    };
  }

  if (input.permission === "read" && input.idempotency === "read_only") {
    return {
      requiresApproval: false,
      automatic: true,
      reason: "read_only",
    };
  }

  if (
    input.permission === "write" &&
    input.idempotency === "idempotent_write"
  ) {
    const automatic = input.mode === "trusted_idempotent_writes";
    return {
      requiresApproval: !automatic,
      automatic,
      reason: automatic
        ? "trusted_idempotent_write"
        : "write_requires_approval",
    };
  }

  return {
    requiresApproval: true,
    automatic: false,
    reason:
      input.permission === "write"
        ? "write_requires_approval"
        : "unclassified",
  };
}

export function shouldAutomaticallyApproveUserTool(input: Parameters<typeof decideUserToolApproval>[0]) {
  const decision = decideUserToolApproval(input);
  return decision.automatic && !decision.requiresApproval;
}
