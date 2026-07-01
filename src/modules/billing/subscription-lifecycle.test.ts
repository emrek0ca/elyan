import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeSubscriptionStatus,
  resolveSubscriptionLifecycle,
} from "./subscription-lifecycle.js";

const NOW = new Date("2026-07-02T12:00:00.000Z");
const FUTURE = new Date("2026-07-20T00:00:00.000Z");
const PAST = new Date("2026-06-20T00:00:00.000Z");

test("lifecycle: no row means plain free with access", () => {
  const lifecycle = resolveSubscriptionLifecycle(null, NOW);
  assert.equal(lifecycle.phase, "free");
  assert.equal(lifecycle.effectivePlanCode, "free");
  assert.equal(lifecycle.accessAllowed, true);
  assert.equal(lifecycle.needsDowngradeRepair, false);
});

test("lifecycle: free row with a welcome-offer claim window is NOT a trial", () => {
  // On free rows trialEndsAt is the offer claim deadline — overloaded field.
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "free", status: "free", trialEndsAt: FUTURE },
    NOW,
  );
  assert.equal(lifecycle.phase, "free");
  assert.equal(lifecycle.trialActive, false);
  assert.equal(lifecycle.accessAllowed, true);
});

test("lifecycle: welcome trial window open → trial_active at the trial plan", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    {
      planCode: "pro",
      status: "trialing",
      billingProvider: "welcome_trial",
      trialEndsAt: FUTURE,
      periodEndsAt: FUTURE,
    },
    NOW,
  );
  assert.equal(lifecycle.phase, "trial_active");
  assert.equal(lifecycle.effectivePlanCode, "pro");
  assert.equal(lifecycle.trialActive, true);
  assert.equal(lifecycle.needsDowngradeRepair, false);
});

test("lifecycle: EXPIRED welcome trial falls to free WITH access (prod zombie fix)", () => {
  // The production bug: this row stayed pro/trialing forever and every
  // non-billing path blocked the user entirely while keeping the pro brain
  // profile. Correct behavior: free access, repair flagged.
  const lifecycle = resolveSubscriptionLifecycle(
    {
      planCode: "pro",
      status: "trialing",
      billingProvider: "welcome_trial",
      trialEndsAt: PAST,
      periodEndsAt: PAST,
    },
    NOW,
  );
  assert.equal(lifecycle.phase, "expired");
  assert.equal(lifecycle.effectivePlanCode, "free");
  assert.equal(lifecycle.accessAllowed, true);
  assert.equal(lifecycle.trialActive, false);
  assert.equal(lifecycle.needsDowngradeRepair, true);
});

test("lifecycle: paid active period keeps the paid plan", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "solo", status: "active", periodEndsAt: FUTURE },
    NOW,
  );
  assert.equal(lifecycle.phase, "paid_active");
  assert.equal(lifecycle.effectivePlanCode, "solo");
  assert.equal(lifecycle.accessAllowed, true);
});

test("lifecycle: paid active with NO period end stays active (open-ended)", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "pro", status: "active", periodEndsAt: null },
    NOW,
  );
  assert.equal(lifecycle.phase, "paid_active");
  assert.equal(lifecycle.effectivePlanCode, "pro");
});

test("lifecycle: paid active whose period lapsed is expired and repairable", () => {
  // Missed renewal webhook / lapsed store sub — previously had NO repair path.
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "pro", status: "active", periodEndsAt: PAST, billingProvider: "apple_store" },
    NOW,
  );
  assert.equal(lifecycle.phase, "expired");
  assert.equal(lifecycle.effectivePlanCode, "free");
  assert.equal(lifecycle.accessAllowed, true);
  assert.equal(lifecycle.needsDowngradeRepair, true);
});

test("lifecycle: canceled with running paid period keeps access until period end (Claude-style)", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "pro", status: "canceled", periodEndsAt: FUTURE, billingProvider: "apple_store" },
    NOW,
  );
  assert.equal(lifecycle.phase, "canceled_grace");
  assert.equal(lifecycle.effectivePlanCode, "pro");
  assert.equal(lifecycle.accessAllowed, true);
  assert.equal(lifecycle.graceEndsAt?.getTime(), FUTURE.getTime());
  assert.equal(lifecycle.needsDowngradeRepair, false);
});

test("lifecycle: canceled after period end is expired", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "pro", status: "canceled", periodEndsAt: PAST, billingProvider: "apple_store" },
    NOW,
  );
  assert.equal(lifecycle.phase, "expired");
  assert.equal(lifecycle.effectivePlanCode, "free");
  assert.equal(lifecycle.needsDowngradeRepair, true);
});

test("lifecycle: past_due is expired immediately", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "solo", status: "past_due", periodEndsAt: FUTURE },
    NOW,
  );
  assert.equal(lifecycle.phase, "expired");
  assert.equal(lifecycle.effectivePlanCode, "free");
  assert.equal(lifecycle.needsDowngradeRepair, true);
});

test("lifecycle: due pending downgrade wins over free at expiry (money not wasted)", () => {
  // User on Pro bought Solo mid-period → downgrade deferred. When the Pro
  // period lapses the repair target must be the Solo they PAID for.
  const lifecycle = resolveSubscriptionLifecycle(
    {
      planCode: "pro",
      status: "canceled",
      periodEndsAt: PAST,
      pendingPlanCode: "solo",
      pendingPlanEffectiveAt: PAST,
    },
    NOW,
  );
  assert.equal(lifecycle.phase, "expired");
  assert.equal(lifecycle.effectivePlanCode, "solo");
  assert.equal(lifecycle.duePendingPlanCode, "solo");
  assert.equal(lifecycle.needsDowngradeRepair, true);
});

test("lifecycle: pending downgrade not yet due is surfaced but not applied", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    {
      planCode: "pro",
      status: "active",
      periodEndsAt: FUTURE,
      pendingPlanCode: "solo",
      pendingPlanEffectiveAt: FUTURE,
    },
    NOW,
  );
  assert.equal(lifecycle.phase, "paid_active");
  assert.equal(lifecycle.effectivePlanCode, "pro");
  assert.equal(lifecycle.pendingPlanCode, "solo");
  assert.equal(lifecycle.duePendingPlanCode, null);
});

test("lifecycle: a same-or-higher-tier pending plan is ignored as junk", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    {
      planCode: "solo",
      status: "active",
      periodEndsAt: FUTURE,
      pendingPlanCode: "pro",
      pendingPlanEffectiveAt: PAST,
    },
    NOW,
  );
  assert.equal(lifecycle.pendingPlanCode, null);
  assert.equal(lifecycle.duePendingPlanCode, null);
});

test("lifecycle: legacy FREE-plan trial row still reports as a trial", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "free", status: "trialing", trialEndsAt: FUTURE },
    NOW,
  );
  assert.equal(lifecycle.phase, "trial_active");
  assert.equal(lifecycle.trialActive, true);
  assert.equal(lifecycle.effectivePlanCode, "free");
});

test("lifecycle: provider trial without an explicit window behaves like a paid period", () => {
  // Apple intro offers sometimes arrive with status=trialing but only a
  // periodEndsAt. Documented legacy behavior: treat as paid, not trial.
  const open = resolveSubscriptionLifecycle(
    { planCode: "pro", status: "trialing", trialEndsAt: null, periodEndsAt: FUTURE },
    NOW,
  );
  assert.equal(open.phase, "paid_active");
  assert.equal(open.trialActive, false);
  assert.equal(open.effectivePlanCode, "pro");

  const lapsed = resolveSubscriptionLifecycle(
    { planCode: "pro", status: "trialing", trialEndsAt: null, periodEndsAt: PAST },
    NOW,
  );
  assert.equal(lapsed.phase, "expired");
  assert.equal(lapsed.needsDowngradeRepair, true);
});

test("lifecycle: paid planCode with free status is corrupt data — access stays free", () => {
  const lifecycle = resolveSubscriptionLifecycle(
    { planCode: "pro", status: "free" },
    NOW,
  );
  assert.equal(lifecycle.phase, "free");
  assert.equal(lifecycle.effectivePlanCode, "free");
  assert.equal(lifecycle.accessAllowed, true);
});

test("normalizeSubscriptionStatus tolerates junk and casing", () => {
  assert.equal(normalizeSubscriptionStatus(" ACTIVE "), "active");
  assert.equal(normalizeSubscriptionStatus("nonsense"), "free");
  assert.equal(normalizeSubscriptionStatus(null), "free");
  assert.equal(normalizeSubscriptionStatus(undefined), "free");
});
