import { normalizeBillingPlanCode, planTierRank, type BillingPlanCode } from "./catalog.js";

/**
 * Subscription lifecycle — the ONE place that decides what a subscription row
 * means *right now*.
 *
 * Before this module the same question ("does this user have access, and at
 * which plan?") was answered in at least four places with subtly different
 * rules: `resolveUsageAccessTruth`, the lazy repair block inside
 * `getBillingSummary`, `isStoreSubscriptionClaimLocked`, and ad-hoc status
 * checks. The worst symptom in production: a welcome-trial row whose
 * `trialEndsAt` lapsed stayed `pro/trialing` in the database forever. The
 * summary endpoint would lazily repair it, but every OTHER path (chat quota,
 * brain profile, device limits) saw the zombie row and concluded
 * "paid plan, not active → block entirely" — an expired-trial user was locked
 * out of chat completely instead of falling back to free-tier limits, while
 * simultaneously keeping the premium brain profile. This resolver fixes the
 * class of bugs, not the instances.
 *
 * ## Field semantics (documented because they are overloaded)
 *
 * - On a `status="trialing"` row, `trialEndsAt` is when the trial window ends.
 * - On a `status="free"` row, `trialEndsAt` is the *claim deadline* for the
 *   welcome-Pro offer (see `shapeWelcomeProTrialOffer`). It does NOT mean the
 *   user is on a trial — the status branch below never treats it as one.
 * - `pendingPlanCode`/`pendingPlanEffectiveAt` record a *deferred downgrade*:
 *   the user bought a lower tier while a higher paid period was still
 *   running. Claude-style rule: the higher plan keeps running until the paid
 *   period ends, then the pending plan takes over — money is never thrown
 *   away.
 */

export const SUBSCRIPTION_STATUSES = ["free", "trialing", "active", "past_due", "canceled"] as const;
export type SubscriptionStatus = (typeof SUBSCRIPTION_STATUSES)[number];

export function normalizeSubscriptionStatus(value?: string | null): SubscriptionStatus {
  const normalized = String(value || "free").trim().toLowerCase();
  return (SUBSCRIPTION_STATUSES as readonly string[]).includes(normalized)
    ? (normalized as SubscriptionStatus)
    : "free";
}

export type SubscriptionPhase =
  /** Free plan, normal state. Also the phase for "no subscription row". */
  | "free"
  /** A trial window (welcome trial or store trial) is still open. */
  | "trial_active"
  /** Paid plan with a running (or open-ended) period. */
  | "paid_active"
  /**
   * Canceled, but the already-paid period is still running. Access continues
   * at the paid plan until `graceEndsAt` — cancellation never burns paid days.
   */
  | "canceled_grace"
  /**
   * The paid/trial window has lapsed (or payment failed). The row still says
   * a paid plan but the user's effective access is the downgrade target
   * (pending plan if one is due, otherwise free). `needsDowngradeRepair`
   * tells writers to persist that reality.
   */
  | "expired";

export type SubscriptionLifecycleInput = {
  planCode?: string | null;
  status?: string | null;
  billingProvider?: string | null;
  periodEndsAt?: Date | null;
  trialEndsAt?: Date | null;
  pendingPlanCode?: string | null;
  pendingPlanEffectiveAt?: Date | null;
};

export type SubscriptionLifecycle = {
  phase: SubscriptionPhase;
  /** Plan code as stored on the row (normalized). */
  planCode: BillingPlanCode;
  /** Status as stored on the row (normalized). */
  status: SubscriptionStatus;
  /** The plan whose limits/profile the user should get RIGHT NOW. */
  effectivePlanCode: BillingPlanCode;
  /**
   * Server-brain access at the effective plan. Note this is true for
   * `expired` too — an expired-trial user has *free-tier* access, they are
   * not locked out.
   */
  accessAllowed: boolean;
  trialActive: boolean;
  trialEndsAt: Date | null;
  /** For canceled_grace: when the paid access runs out. */
  graceEndsAt: Date | null;
  /** True when the stored row no longer matches reality and should be rewritten. */
  needsDowngradeRepair: boolean;
  /** Deferred downgrade not yet due (surfaced to clients as "X'e geçecek"). */
  pendingPlanCode: BillingPlanCode | null;
  pendingPlanEffectiveAt: Date | null;
  /** Deferred downgrade whose effective date has arrived — the repair target. */
  duePendingPlanCode: BillingPlanCode | null;
};

function asDate(value: unknown): Date | null {
  return value instanceof Date && Number.isFinite(value.getTime()) ? value : null;
}

export function resolveSubscriptionLifecycle(
  subscription: SubscriptionLifecycleInput | null | undefined,
  currentTime: Date = new Date(),
): SubscriptionLifecycle {
  const nowMs = currentTime.getTime();
  const planCode = normalizeBillingPlanCode(subscription?.planCode);
  const status = normalizeSubscriptionStatus(subscription?.status);
  const periodEndsAt = asDate(subscription?.periodEndsAt);
  const trialEndsAt = asDate(subscription?.trialEndsAt);

  // A pending plan only counts when it is a real, lower-tier target relative
  // to the stored plan. Anything else (same tier, higher tier, junk) is
  // ignored — those transitions apply immediately elsewhere, never deferred.
  const rawPending = subscription?.pendingPlanCode
    ? normalizeBillingPlanCode(subscription.pendingPlanCode)
    : null;
  const pendingPlanEffectiveAt = asDate(subscription?.pendingPlanEffectiveAt);
  const pendingPlanCode =
    rawPending != null && planTierRank(rawPending) < planTierRank(planCode) ? rawPending : null;
  const pendingDue =
    pendingPlanCode != null &&
    pendingPlanEffectiveAt != null &&
    pendingPlanEffectiveAt.getTime() <= nowMs;
  const duePendingPlanCode = pendingDue ? pendingPlanCode : null;

  const base = {
    planCode,
    status,
    trialEndsAt,
    pendingPlanCode,
    pendingPlanEffectiveAt,
    duePendingPlanCode,
  };

  const expired = (): SubscriptionLifecycle => ({
    ...base,
    phase: "expired",
    // A due pending downgrade wins over plain free — the user PAID for that
    // lower tier; dropping them to free would throw their money away.
    effectivePlanCode: duePendingPlanCode ?? "free",
    accessAllowed: true,
    trialActive: false,
    graceEndsAt: null,
    needsDowngradeRepair: true,
  });

  if (!subscription || status === "free") {
    // Free-status rows: `trialEndsAt` here is the welcome-offer claim window,
    // not a trial (see module docs) — so this branch never reports
    // trial_active. Note the guard is on STATUS, not plan: a free-plan row
    // with status="trialing" (legacy free trial) goes through the trialing
    // branch below and correctly reports as a trial. A paid planCode with
    // status="free" is corrupt data — access stays at the free tier.
    return {
      ...base,
      phase: "free",
      effectivePlanCode: "free",
      accessAllowed: true,
      trialActive: false,
      graceEndsAt: null,
      needsDowngradeRepair: false,
    };
  }

  if (status === "trialing") {
    if (trialEndsAt == null) {
      // Provider-managed trial with no explicit window (e.g. an Apple intro
      // offer where only periodEndsAt was sent). Treat like a paid period:
      // active while the period runs, expired when it lapses.
      if (periodEndsAt == null || periodEndsAt.getTime() > nowMs) {
        return {
          ...base,
          phase: "paid_active",
          effectivePlanCode: planCode,
          accessAllowed: true,
          trialActive: false,
          graceEndsAt: null,
          needsDowngradeRepair: false,
        };
      }
      return expired();
    }
    if (trialEndsAt.getTime() > nowMs) {
      return {
        ...base,
        phase: "trial_active",
        effectivePlanCode: planCode,
        accessAllowed: true,
        trialActive: true,
        graceEndsAt: null,
        needsDowngradeRepair: false,
      };
    }
    return expired();
  }

  if (status === "active") {
    if (periodEndsAt == null || periodEndsAt.getTime() > nowMs) {
      return {
        ...base,
        phase: "paid_active",
        effectivePlanCode: planCode,
        accessAllowed: true,
        trialActive: false,
        graceEndsAt: null,
        needsDowngradeRepair: false,
      };
    }
    // Paid period lapsed without a renewal event (missed webhook, lapsed
    // store subscription). Same expired handling as everything else — this
    // shape previously had NO repair path at all.
    return expired();
  }

  if (status === "canceled") {
    if (periodEndsAt != null && periodEndsAt.getTime() > nowMs) {
      return {
        ...base,
        phase: "canceled_grace",
        effectivePlanCode: planCode,
        accessAllowed: true,
        trialActive: false,
        graceEndsAt: periodEndsAt,
        needsDowngradeRepair: false,
      };
    }
    return expired();
  }

  // past_due: payment failed and the provider did not recover it. Treat as
  // expired-with-repair; a fresh store verification with a newer receipt
  // simply overwrites the repaired row.
  return expired();
}
