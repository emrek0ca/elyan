import test from "node:test";
import assert from "node:assert/strict";
import { shapeSubscriptionTruth } from "./subscription-truth.js";

test("shapeSubscriptionTruth keeps the mobile plan contract stable", () => {
  const periodEndsAt = new Date("2026-06-01T00:00:00.000Z");
  const subscription = shapeSubscriptionTruth({
    planCode: "pro",
    status: "active",
    aiCreditsMonthly: 1500,
    tokensMonthly: 1500,
    taskLimitMonthly: 2000,
    periodEndsAt,
    trialEndsAt: null,
    creditBalance: 742,
    creditGrantedThisPeriod: 2000,
    creditPeriodEndsAt: periodEndsAt,
    billingProvider: "apple_store",
    subscriptionSource: "apple_store",
    manageSubscriptionHint: "Manage in App Store",
    creditStatus: "available",
  });

  assert.deepEqual(subscription, {
    planCode: "pro",
    qualityProfile: "pro_max",
    status: "active",
    aiCreditsMonthly: 1500,
    tokensMonthly: 1500,
    taskLimitMonthly: 2000,
    brainProfile: {
      qualityProfile: "pro_max",
      tier: "premium",
      reasoningMultiplier: 5,
      retrievalFanout: 6,
      memoryFanout: 8,
      maxTokenScale: 1.35,
    },
    periodEndsAt,
    trialEndsAt: null,
    creditBalance: 742,
    tokenBalance: 742,
    creditGrantedThisPeriod: 2000,
    tokensGrantedThisPeriod: 2000,
    creditPeriodEndsAt: periodEndsAt,
    tokenPeriodEndsAt: periodEndsAt,
    billingProvider: "apple_store",
    subscriptionSource: "apple_store",
    manageSubscriptionHint: "Manage in App Store",
    creditStatus: "available",
    tokenStatus: "available",
    trialOffer: {
      code: "welcome_pro_30d",
      planCode: "pro",
      durationDays: 30,
      status: "unavailable",
      eligible: false,
      claimed: false,
      claimPath: "/v1/billing/trials/pro/claim",
      expiresAt: null,
    },
  });
});

test("shapeSubscriptionTruth falls back to free plan defaults", () => {
  const subscription = shapeSubscriptionTruth(null);

  assert.deepEqual(subscription, {
    planCode: "free",
    qualityProfile: "free_basic",
    status: "free",
    aiCreditsMonthly: 120,
    tokensMonthly: 120,
    taskLimitMonthly: 50,
    brainProfile: {
      qualityProfile: "free_basic",
      tier: "standard",
      reasoningMultiplier: 1,
      retrievalFanout: 2,
      memoryFanout: 2,
      maxTokenScale: 1,
    },
    periodEndsAt: null,
    trialEndsAt: null,
    creditBalance: 120,
    tokenBalance: 120,
    creditGrantedThisPeriod: 120,
    tokensGrantedThisPeriod: 120,
    creditPeriodEndsAt: null,
    tokenPeriodEndsAt: null,
    billingProvider: null,
    subscriptionSource: null,
    manageSubscriptionHint: null,
    creditStatus: null,
    tokenStatus: null,
    trialOffer: {
      code: "welcome_pro_30d",
      planCode: "pro",
      durationDays: 30,
      status: "unavailable",
      eligible: false,
      claimed: false,
      claimPath: "/v1/billing/trials/pro/claim",
      expiresAt: null,
    },
  });
});

test("shapeSubscriptionTruth exposes available welcome pro trial offers for fresh free accounts", () => {
  const expiresAt = new Date(Date.now() + 60_000);
  const subscription = shapeSubscriptionTruth({
    planCode: "free",
    status: "free",
    trialEndsAt: expiresAt,
  });

  assert.deepEqual(subscription.trialOffer, {
    code: "welcome_pro_30d",
    planCode: "pro",
    durationDays: 30,
    status: "available",
    eligible: true,
    claimed: false,
    claimPath: "/v1/billing/trials/pro/claim",
    expiresAt,
  });
});

test("shapeSubscriptionTruth normalizes legacy zero-credit free rows to the current free allowance", () => {
  const subscription = shapeSubscriptionTruth({
    planCode: "free",
    status: "free",
    aiCreditsMonthly: 0,
    taskLimitMonthly: 0,
  });

  assert.equal(subscription.aiCreditsMonthly, 120);
  assert.equal(subscription.tokensMonthly, 120);
  assert.equal(subscription.taskLimitMonthly, 50);
});

test("shapeSubscriptionTruth marks claimed welcome pro trials after activation", () => {
  const expiresAt = new Date(Date.now() + 60_000);
  const subscription = shapeSubscriptionTruth({
    planCode: "pro",
    status: "trialing",
    trialEndsAt: expiresAt,
  });

  assert.equal(subscription.brainProfile.tier, "premium");
  assert.deepEqual(subscription.trialOffer, {
    code: "welcome_pro_30d",
    planCode: "pro",
    durationDays: 30,
    status: "claimed",
    eligible: false,
    claimed: true,
    claimPath: "/v1/billing/trials/pro/claim",
    expiresAt,
  });
});

test("shapeSubscriptionTruth keeps pro intelligence when stale rows carry a standard profile", () => {
  const subscription = shapeSubscriptionTruth({
    planCode: "pro",
    status: "active",
    brainProfile: {
      qualityProfile: "free_basic",
      tier: "standard",
      reasoningMultiplier: 1,
      retrievalFanout: 2,
      memoryFanout: 3,
      maxTokenScale: 1,
    },
  });

  assert.equal(subscription.planCode, "pro");
  assert.deepEqual(subscription.brainProfile, {
    qualityProfile: "pro_max",
    tier: "premium",
    reasoningMultiplier: 5,
    retrievalFanout: 6,
    memoryFanout: 8,
    maxTokenScale: 1.35,
  });
});

test("shapeSubscriptionTruth does not let solo inherit stale premium intelligence", () => {
  const subscription = shapeSubscriptionTruth({
    planCode: "solo",
    status: "active",
    brainProfile: {
      qualityProfile: "pro_max",
      tier: "premium",
      reasoningMultiplier: 5,
      retrievalFanout: 8,
      memoryFanout: 10,
      maxTokenScale: 2,
    },
  });

  assert.equal(subscription.planCode, "solo");
  assert.deepEqual(subscription.brainProfile, {
    qualityProfile: "solo_enhanced",
    tier: "standard",
    reasoningMultiplier: 3,
    retrievalFanout: 4,
    memoryFanout: 5,
    maxTokenScale: 1.12,
  });
});
