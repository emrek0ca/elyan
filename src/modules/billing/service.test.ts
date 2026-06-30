import assert from "node:assert/strict";
import test from "node:test";
import { canUseDesktopConnections, getBillingPlan, normalizeBillingPlanCode } from "./catalog.js";
import {
  assertSharedBrainUsageBudgetAllowed,
  buildTrialSubscriptionSeed,
  createUpgradeOrByokRequiredError,
  decideAppleSubscriptionOwnership,
  getBillingProviderForStorePlatform,
  getSharedBrainUsageBudget,
  getCheckoutInitializationState,
  isStoreSubscriptionClaimLocked,
  normalizeStoreWebhookStatus,
  resolveUsageAccessTruth,
  resolveUsagePresentationTruth,
  shapePublicUsageSnapshot,
  shouldIgnoreStaleStoreVerification,
  upsertStoreTransaction,
} from "./service.js";

class QueuedSelectQuery<T> implements PromiseLike<T[]> {
  constructor(private readonly rows: T[]) {}

  from(): this {
    return this;
  }

  where(): this {
    return this;
  }

  orderBy(): this {
    return this;
  }

  limit(): Promise<T[]> {
    return Promise.resolve(this.rows);
  }

  then<TResult1 = T[], TResult2 = never>(
    onfulfilled?: ((value: T[]) => TResult1 | PromiseLike<TResult1>) | null,
    onrejected?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ): PromiseLike<TResult1 | TResult2> {
    return Promise.resolve(this.rows).then(onfulfilled, onrejected);
  }
}

class QueuedSelectDb {
  constructor(private readonly queuedRows: unknown[][]) {}

  select(): QueuedSelectQuery<unknown> {
    return new QueuedSelectQuery(this.queuedRows.shift() ?? []);
  }
}

function subscriptionRow(input: {
  planCode: string;
  status: string;
  taskLimitMonthly: number;
  aiCreditsMonthly: number;
  currentPeriodStartedAt?: Date;
  periodEndsAt?: Date;
  trialEndsAt?: Date | null;
}) {
  return {
    userId: "user-1",
    planCode: input.planCode,
    status: input.status,
    taskLimitMonthly: input.taskLimitMonthly,
    aiCreditsMonthly: input.aiCreditsMonthly,
    currentPeriodStartedAt: input.currentPeriodStartedAt ?? new Date("2030-01-01T00:00:00.000Z"),
    periodEndsAt: input.periodEndsAt ?? new Date("2030-02-01T00:00:00.000Z"),
    trialEndsAt: input.trialEndsAt ?? null,
  };
}

test("getCheckoutInitializationState stays pending for placeholder rows", () => {
  const state = getCheckoutInitializationState({
    paymentPageUrl: null,
    providerToken: null,
    providerPaymentId: null,
    providerSubscriptionReferenceCode: null,
    completedAt: null,
    rawLastPayload: {},
  } as never);

  assert.equal(state, "pending");
});

test("getCheckoutInitializationState stays pending for in-flight initialization markers", () => {
  const state = getCheckoutInitializationState({
    paymentPageUrl: null,
    providerToken: null,
    providerPaymentId: null,
    providerSubscriptionReferenceCode: null,
    completedAt: null,
    rawLastPayload: {
      initializationState: "initializing",
    },
  } as never);

  assert.equal(state, "pending");
});

test("getCheckoutInitializationState is ready once provider launch data exists", () => {
  const state = getCheckoutInitializationState({
    paymentPageUrl: "https://sandbox.iyzipay.com/checkout",
    providerToken: null,
    providerPaymentId: null,
    providerSubscriptionReferenceCode: null,
    completedAt: null,
    rawLastPayload: {
      initializationState: "failed",
    },
  } as never);

  assert.equal(state, "ready");
});

test("getCheckoutInitializationState reports failed for fail-closed initialization markers", () => {
  const state = getCheckoutInitializationState({
    paymentPageUrl: null,
    providerToken: null,
    providerPaymentId: null,
    providerSubscriptionReferenceCode: null,
    completedAt: null,
    rawLastPayload: {
      initializationState: "failed",
      errorCode: "service_unavailable",
    },
  } as never);

  assert.equal(state, "failed");
});

test("getBillingProviderForStorePlatform routes native stores to the matching provider", () => {
  assert.equal(getBillingProviderForStorePlatform("apple"), "apple_store");
  assert.equal(getBillingProviderForStorePlatform("google"), "google_play");
});

test("normalizeStoreWebhookStatus keeps entitlement updates fail-closed for recovery states", () => {
  assert.equal(normalizeStoreWebhookStatus("SUBSCRIPTION_STATE_ACTIVE"), "active");
  assert.equal(normalizeStoreWebhookStatus("SUBSCRIPTION_STATE_IN_TRIAL"), "trialing");
  assert.equal(normalizeStoreWebhookStatus("SUBSCRIPTION_STATE_ON_HOLD"), "past_due");
  assert.equal(normalizeStoreWebhookStatus("SUBSCRIPTION_STATE_CANCELED"), "canceled");
});

test("upsertStoreTransaction matches App Store renewals by original transaction id", async () => {
  const existingRow = {
    id: "store-tx-1",
    userId: "user-1",
    planCode: "solo",
    productId: "com.elyan.solo.monthly",
    purchaseToken: null,
    originalTransactionId: "2000001193376342",
    transactionId: "2000001194808999",
    orderId: null,
    linkedPurchaseToken: null,
    environment: "Sandbox",
    appAccountToken: null,
    verifiedAt: new Date("2026-06-01T00:00:00.000Z"),
  };
  const updatedRows: Array<Record<string, unknown>> = [];
  let insertCalled = false;

  const app = {
    db: {
      select() {
        return {
          from() {
            return this;
          },
          where() {
            return this;
          },
          limit: async () => [existingRow],
        };
      },
      update() {
        return {
          set(values: Record<string, unknown>) {
            updatedRows.push(values);
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      ...existingRow,
                      ...values,
                    },
                  ],
                };
              },
            };
          },
        };
      },
      insert() {
        insertCalled = true;
        return {
          values() {
            return {
              returning: async () => [],
            };
          },
        };
      },
    },
  };

  const row = await upsertStoreTransaction(app as never, {
    userId: "user-1",
    provider: "apple_store",
    planCode: "pro",
    productId: "com.elyan.pro.monthly",
    originalTransactionId: "2000001193376342",
    transactionId: "2000001196569299",
    status: "active",
    payload: { source: "unit-test" },
    verifiedAt: new Date("2026-06-30T00:00:00.000Z"),
  });

  assert.equal(insertCalled, false);
  assert.equal(row.id, "store-tx-1");
  assert.equal(row.transactionId, "2000001196569299");
  assert.equal(row.originalTransactionId, "2000001193376342");
  assert.equal(updatedRows.length, 1);
  assert.equal(updatedRows[0].planCode, "pro");
});

test("store subscription claim lock allows expired Apple subscriptions but blocks active paid periods", () => {
  const now = new Date("2026-06-30T00:00:00.000Z");

  assert.equal(
    isStoreSubscriptionClaimLocked(
      {
        billingProvider: "apple_store",
        planCode: "solo",
        status: "past_due",
        periodEndsAt: new Date("2026-06-25T00:00:00.000Z"),
      },
      now,
    ),
    false,
  );

  assert.equal(
    isStoreSubscriptionClaimLocked(
      {
        billingProvider: "apple_store",
        planCode: "solo",
        status: "active",
        periodEndsAt: new Date("2026-07-25T00:00:00.000Z"),
      },
      now,
    ),
    true,
  );
});

test("stale store verification cannot downgrade a newer active store period", () => {
  const now = new Date("2026-06-30T00:00:00.000Z");

  assert.equal(
    shouldIgnoreStaleStoreVerification(
      {
        billingProvider: "apple_store",
        planCode: "solo",
        status: "active",
        periodEndsAt: new Date("2026-07-01T22:59:27.000Z"),
      },
      {
        billingProvider: "apple_store",
        status: "past_due",
        periodEndsAt: new Date("2026-06-29T16:09:35.000Z"),
      },
      now,
    ),
    true,
  );

  assert.equal(
    shouldIgnoreStaleStoreVerification(
      {
        billingProvider: "apple_store",
        planCode: "solo",
        status: "active",
        periodEndsAt: new Date("2026-07-01T22:59:27.000Z"),
      },
      {
        billingProvider: "apple_store",
        status: "active",
        periodEndsAt: new Date("2026-07-02T22:59:27.000Z"),
      },
      now,
    ),
    false,
  );
});

test("upsertStoreTransaction can reassign an expired App Store original transaction after ownership check", async () => {
  const existingRow = {
    id: "store-tx-1",
    userId: "old-user",
    planCode: "solo",
    productId: "com.elyan.solo.monthly",
    purchaseToken: null,
    originalTransactionId: "2000001193376342",
    transactionId: "2000001194098613",
    orderId: null,
    linkedPurchaseToken: null,
    environment: "Sandbox",
    appAccountToken: "old-user",
    verifiedAt: new Date("2026-06-01T00:00:00.000Z"),
  };
  const updatedRows: Array<Record<string, unknown>> = [];

  const app = {
    db: {
      select() {
        return {
          from() {
            return this;
          },
          where() {
            return this;
          },
          limit: async () => [existingRow],
        };
      },
      update() {
        return {
          set(values: Record<string, unknown>) {
            updatedRows.push(values);
            return {
              where() {
                return {
                  returning: async () => [
                    {
                      ...existingRow,
                      ...values,
                    },
                  ],
                };
              },
            };
          },
        };
      },
    },
  };

  const row = await upsertStoreTransaction(app as never, {
    userId: "new-user",
    provider: "apple_store",
    planCode: "solo",
    productId: "com.elyan.solo.monthly",
    originalTransactionId: "2000001193376342",
    transactionId: "2000001200000000",
    appAccountToken: "new-user",
    status: "active",
    payload: { source: "unit-test" },
    verifiedAt: new Date("2026-06-30T00:00:00.000Z"),
    allowUserReassignment: true,
  });

  assert.equal(row.id, "store-tx-1");
  assert.equal(row.userId, "new-user");
  assert.equal(row.appAccountToken, "new-user");
  assert.equal(updatedRows.length, 1);
});

test("resolveUsageAccessTruth keeps new free trials server-brain eligible until trial expiry", () => {
  const futureTrialEndsAt = new Date(Date.now() + 60_000);
  const truth = resolveUsageAccessTruth({
    planCode: "free",
    status: "trialing",
    trialEndsAt: futureTrialEndsAt,
  });

  assert.equal(truth.mode, "trial");
  assert.equal(truth.serverBrainAllowed, true);
  assert.equal(truth.upgradeRequiredForServerBrain, false);
  assert.equal(truth.trialActive, true);
});

test("resolveUsageAccessTruth falls back to bounded free server-brain access after free trial expiry", () => {
  const truth = resolveUsageAccessTruth({
    planCode: "free",
    status: "trialing",
    trialEndsAt: new Date(Date.now() - 60_000),
  });

  assert.equal(truth.mode, "free");
  assert.equal(truth.serverBrainAllowed, true);
  assert.equal(truth.upgradeRequiredForServerBrain, false);
  assert.equal(truth.brainProfile.tier, "standard");
  assert.equal(truth.brainProfile.retrievalFanout, 2);
});

test("resolveUsageAccessTruth exposes the premium brain profile for pro plans", () => {
  const truth = resolveUsageAccessTruth({
    planCode: "pro",
    status: "active",
    trialEndsAt: null,
  });

  assert.equal(truth.brainProfile.tier, "premium");
  assert.equal(truth.brainProfile.reasoningMultiplier, 5);
  assert.equal(truth.brainProfile.retrievalFanout, 6);
  assert.equal(truth.brainProfile.memoryFanout, 8);
});

test("resolveUsageAccessTruth treats claimed pro trials as premium trial access", () => {
  const truth = resolveUsageAccessTruth({
    planCode: "pro",
    status: "trialing",
    trialEndsAt: new Date(Date.now() + 60_000),
  });

  assert.equal(truth.mode, "trial");
  assert.equal(truth.serverBrainAllowed, true);
  assert.equal(truth.trialActive, true);
  assert.equal(truth.brainProfile.tier, "premium");
  assert.equal(truth.brainProfile.reasoningMultiplier, 5);
});

test("resolveUsageAccessTruth blocks explicitly expired pro trials", () => {
  const truth = resolveUsageAccessTruth({
    planCode: "pro",
    status: "trialing",
    trialEndsAt: new Date(Date.now() - 60_000),
  });

  assert.equal(truth.serverBrainAllowed, false);
  assert.equal(truth.upgradeRequiredForServerBrain, true);
});

test("resolveUsageAccessTruth keeps provider trialing paid plans active when no expiry was sent", () => {
  const truth = resolveUsageAccessTruth({
    planCode: "pro",
    status: "trialing",
    trialEndsAt: null,
  });

  assert.equal(truth.mode, "paid");
  assert.equal(truth.serverBrainAllowed, true);
  assert.equal(truth.brainProfile.tier, "premium");
});

test("buildTrialSubscriptionSeed creates a claimable welcome pro offer without auto-activating pro", () => {
  const createdAt = new Date("2030-01-01T00:00:00.000Z");
  const seed = buildTrialSubscriptionSeed(createdAt);

  assert.equal(seed.planCode, "free");
  assert.equal(seed.status, "free");
  assert.equal(seed.taskLimitMonthly, 50);
  assert.equal(seed.aiCreditsMonthly, 120);
  assert.equal(seed.currentPeriodStartedAt, createdAt);
  assert.equal(seed.trialEndsAt.getTime(), createdAt.getTime() + 30 * 24 * 60 * 60 * 1000);
  assert.equal(seed.periodEndsAt.getTime(), seed.trialEndsAt.getTime());
});

test("resolveUsagePresentationTruth keeps active free trials on trial semantics even when a plan label could differ", () => {
  const presentation = resolveUsagePresentationTruth({
    mode: "trial",
    planCode: "pro",
    status: "trialing",
    brainProfile: {
      qualityProfile: "free_basic",
      tier: "standard",
      reasoningMultiplier: 1,
      retrievalFanout: 2,
      memoryFanout: 3,
      maxTokenScale: 1,
    },
    serverBrainAllowed: true,
    localByokAllowed: true,
    trialActive: true,
    trialEndsAt: new Date(Date.now() + 60_000),
    upgradeRequiredForServerBrain: false,
  });

  assert.equal(presentation.accessMode, "trial");
  assert.equal(presentation.planLabelSource, "trial");
});

test("resolveUsagePresentationTruth keeps paid plans on subscription semantics", () => {
  const presentation = resolveUsagePresentationTruth({
    mode: "paid",
    planCode: "pro",
    status: "active",
    brainProfile: {
      qualityProfile: "pro_max",
      tier: "premium",
      reasoningMultiplier: 5,
      retrievalFanout: 6,
      memoryFanout: 8,
      maxTokenScale: 1.3,
    },
    serverBrainAllowed: true,
    localByokAllowed: true,
    trialActive: false,
    trialEndsAt: null,
    upgradeRequiredForServerBrain: false,
  });

  assert.equal(presentation.accessMode, "paid");
  assert.equal(presentation.planLabelSource, "subscription");
});

test("shapePublicUsageSnapshot keeps authoritative quota truth and adds pending hints separately", () => {
  const periodEndsAt = new Date("2030-02-01T00:00:00.000Z");
  const snapshot = shapePublicUsageSnapshot({
    usage: {
      tasksUsed: 3,
      tasksRemaining: 9,
      tokensUsed: 120,
      tokensRemaining: 880,
      dailyLimit: 12,
      dailyUsed: 4,
      dailyRemaining: 8,
      weeklyLimit: 84,
      weeklyUsed: 18,
      weeklyRemaining: 66,
      qualityProfile: "solo_enhanced",
    },
    subscription: {
      planCode: "solo",
      periodEndsAt,
    },
    pendingTokens: 2,
  });

  assert.equal(snapshot.tokensUsed, 120);
  assert.equal(snapshot.tokensRemaining, 880);
  assert.equal(snapshot.dailyRemaining, 8);
  assert.equal(snapshot.weeklyRemaining, 66);
  assert.equal(snapshot.pendingTokens, 2);
  assert.equal(snapshot.tokenBalanceIncludesPending, true);
  assert.equal(snapshot.planCode, "solo");
  assert.equal(snapshot.periodEndsAt, periodEndsAt);
});

test("resolveUsageAccessTruth normalizes legacy team rows to pro", () => {
  const truth = resolveUsageAccessTruth({
    planCode: "team",
    status: "active",
    trialEndsAt: null,
  });

  assert.equal(truth.planCode, "pro");
  assert.equal(truth.mode, "paid");
  assert.equal(truth.brainProfile.tier, "premium");
});

test("billing catalog keeps desktop connections pro-only", () => {
  const free = getBillingPlan("free");
  const solo = getBillingPlan("solo");
  const pro = getBillingPlan("pro");

  assert.equal(free.desktopLimit, 0);
  assert.equal(free.monthlyPrice, 0);
  assert.equal(free.taskLimitMonthly, 50);
  assert.equal(free.aiCreditsMonthly, 120);
  assert.equal(free.fiveHourBudgetUnits, 4);
  assert.equal(free.byokRequired, false);
  assert.equal(solo.desktopLimit, 0);
  assert.equal(solo.monthlyPrice, 6.99);
  assert.equal(solo.fiveHourBudgetUnits, 18);
  assert.equal(
    solo.providerProducts.apple?.productId,
    "com.elyan.elyanMobile.solo.monthly",
  );
  assert.equal(
    solo.providerProducts.google?.productId,
    "com.elyan.elyanMobile.solo.monthly",
  );
  assert.equal(pro.desktopLimit > 0, true);
  assert.equal(pro.monthlyPrice, 17.99);
  assert.equal(pro.fiveHourBudgetUnits, 60);
  assert.equal(
    pro.providerProducts.apple?.productId,
    "com.elyan.elyanMobile.pro.monthly",
  );
  assert.equal(
    pro.providerProducts.google?.productId,
    "com.elyan.elyanMobile.pro.monthly",
  );
  assert.equal(canUseDesktopConnections("free"), false);
  assert.equal(canUseDesktopConnections("solo"), false);
  assert.equal(canUseDesktopConnections("pro"), true);
});

test("resolveUsageAccessTruth keeps canceled Apple access until period end", () => {
  const truth = resolveUsageAccessTruth(
    {
      planCode: "pro",
      status: "canceled",
      trialEndsAt: null,
      periodEndsAt: new Date("2030-02-01T00:00:00.000Z"),
    },
    new Date("2030-01-15T00:00:00.000Z"),
  );

  assert.equal(truth.mode, "paid");
  assert.equal(truth.serverBrainAllowed, true);
});

test("billing catalog collapses legacy team plan code to pro", () => {
  const planCode = normalizeBillingPlanCode("team");
  const plan = getBillingPlan("team");

  assert.equal(planCode, "pro");
  assert.equal(plan.code, "pro");
  assert.equal(plan.brainProfile.reasoningMultiplier, 5);
});

test("assertSharedBrainUsageBudgetAllowed rejects exhausted bounded free credits", () => {
  assert.throws(
    () =>
      assertSharedBrainUsageBudgetAllowed(
        {
          access: { mode: "free" },
          remainingAiCredits: 0,
          periodEndsAt: new Date("2030-02-01T00:00:00.000Z"),
        },
        1,
      ),
    (error: unknown) => {
      assert.equal((error as { code?: string }).code, "ai_credit_limit_reached");
      return true;
    },
  );
});

test("getSharedBrainUsageBudget resolves legacy free rows from catalog-backed monthly AI credits", async () => {
  const row = subscriptionRow({
    planCode: "free",
    status: "free",
    taskLimitMonthly: 0,
    aiCreditsMonthly: 0,
  });
  const db = new QueuedSelectDb([
    [row],
    [row],
    [{ used: 0 }],
    [{ used: 1 }],
    [{ granted: 0, used: 0 }],
    [],
  ]);

  const budget = await getSharedBrainUsageBudget(db as never, "user-1");

  assert.equal(budget.access.serverBrainAllowed, true);
  assert.equal(budget.remainingAiCredits, 119);
  assert.equal(budget.grantedAiCredits, 120);
  assert.equal(budget.periodEndsAt?.toISOString(), "2030-02-01T00:00:00.000Z");
});

test("getSharedBrainUsageBudget exposes depleted free credits to the shared brain guard", async () => {
  const row = subscriptionRow({
    planCode: "free",
    status: "free",
    taskLimitMonthly: 0,
    aiCreditsMonthly: 0,
  });
  const db = new QueuedSelectDb([
    [row],
    [row],
    [{ used: 0 }],
    [{ used: 120 }],
    [{ granted: 0, used: 0 }],
    [],
  ]);

  const budget = await getSharedBrainUsageBudget(db as never, "user-1");

  assert.equal(budget.remainingAiCredits, 0);
  assert.throws(
    () => assertSharedBrainUsageBudgetAllowed(budget, 1),
    (error: unknown) => {
      assert.equal((error as { code?: string }).code, "ai_credit_limit_reached");
      return true;
    },
  );
});

test("getSharedBrainUsageBudget keeps active paid plan credits bounded by billing usage", async () => {
  const row = subscriptionRow({
    planCode: "pro",
    status: "active",
    taskLimitMonthly: 2000,
    aiCreditsMonthly: 2000,
  });
  const db = new QueuedSelectDb([
    [row],
    [row],
    [{ used: 4 }],
    [{ used: 5 }],
    [{ granted: 0, used: 0 }],
    [],
  ]);

  const budget = await getSharedBrainUsageBudget(db as never, "user-1");

  assert.equal(budget.access.mode, "paid");
  assert.equal(budget.remainingAiCredits, 1995);
  assert.equal(budget.grantedAiCredits, 2000);
});

test("createUpgradeOrByokRequiredError keeps the failure user-safe", () => {
  const error = createUpgradeOrByokRequiredError();

  assert.equal(error.statusCode, 409);
  assert.equal(error.code, "upgrade_or_byok_required");
  assert.equal(
    error.message,
    "Token hakkın doldu. Devam etmek için planını yükselt veya kendi yerel modelini kullan.",
  );
});

test("decideAppleSubscriptionOwnership blocks a new account when token is absent and the period is locked (no Pro leakage)", () => {
  // Açık kapatma: A hesabı Pro aldı, aynı cihazda B hesabı açıldı. JWS'te
  // appAccountToken yok → sahiplik kanıtlanamaz → abonelik A'da kalır, B Pro
  // OLAMAZ. (Bu fonksiyona yalnızca makbuz farklı bir userId'ye kayıtlıyken
  // gelinir; aynı hesabın restore'u dış kontrolde zaten geçer.)
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "",
    currentUserId: "11111111-1111-1111-1111-111111111111",
    lockedByActiveStorePeriod: true,
  });
  assert.equal(decision.blocked, true);
});

test("decideAppleSubscriptionOwnership still reassigns an absent-token receipt once the period has expired", () => {
  // Süresi dolmuş/iptal abonelik kilitli değil → yeni hesap devralabilir.
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "",
    currentUserId: "11111111-1111-1111-1111-111111111111",
    lockedByActiveStorePeriod: false,
  });
  assert.equal(decision.blocked, false);
});

test("decideAppleSubscriptionOwnership allows the owner regardless of casing/dashes", () => {
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "ABCDEF12-3456-7890-ABCD-EF1234567890",
    currentUserId: "abcdef1234567890abcdef1234567890",
    lockedByActiveStorePeriod: true,
  });
  assert.equal(decision.blocked, false);
});

test("decideAppleSubscriptionOwnership blocks a different user on a locked active period", () => {
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "99999999-9999-9999-9999-999999999999",
    currentUserId: "11111111-1111-1111-1111-111111111111",
    lockedByActiveStorePeriod: true,
  });
  assert.equal(decision.blocked, true);
});

test("decideAppleSubscriptionOwnership does not block a different user when the period is not locked", () => {
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "99999999-9999-9999-9999-999999999999",
    currentUserId: "11111111-1111-1111-1111-111111111111",
    lockedByActiveStorePeriod: false,
  });
  assert.equal(decision.blocked, false);
});
