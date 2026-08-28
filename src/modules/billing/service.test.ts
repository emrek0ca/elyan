import assert from "node:assert/strict";
import test from "node:test";
import { canUseDesktopConnections, getBillingPlan, normalizeBillingPlanCode } from "./catalog.js";
import {
  assertSharedBrainUsageBudgetAllowed,
  buildTrialSubscriptionSeed,
  createUpgradeOrByokRequiredError,
  decideStoreWebhookSync,
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

test("stale store verification lets a plan UPGRADE apply immediately even when the incoming period is shorter", () => {
  // Prod bug: user on Solo tapped Pro. Apple pro-rated the crossgrade and
  // returned a Pro receipt with a period end earlier than the running Solo
  // period. Old logic ignored the incoming verification as "stale" and left
  // the user on Solo. Upgrades must always take effect right away.
  const now = new Date("2026-06-30T00:00:00.000Z");
  assert.equal(
    shouldIgnoreStaleStoreVerification(
      {
        billingProvider: "apple_store",
        planCode: "solo",
        status: "active",
        periodEndsAt: new Date("2026-07-25T00:00:00.000Z"),
      },
      {
        billingProvider: "apple_store",
        planCode: "pro",
        status: "active",
        // Pro period end BEFORE the current Solo period end — pro-rated
        // upgrade — must still take effect.
        periodEndsAt: new Date("2026-07-15T00:00:00.000Z"),
      },
      now,
    ),
    false,
  );
});

test("stale store verification defers a DOWNGRADE within an active paid period (Claude-style)", () => {
  // Symmetric case: user on Pro tapped Solo. Solo shouldn't kick in until
  // the paid Pro period expires — otherwise the user loses days they paid
  // for. Backend state stays on Pro; UI shows "Pro, X gün sonra Solo'ya
  // geçecek".
  const now = new Date("2026-06-30T00:00:00.000Z");
  assert.equal(
    shouldIgnoreStaleStoreVerification(
      {
        billingProvider: "apple_store",
        planCode: "pro",
        status: "active",
        periodEndsAt: new Date("2026-07-25T00:00:00.000Z"),
      },
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

test("store webhook downgrade is deferred instead of replacing the active paid plan", () => {
  const now = new Date("2026-06-30T00:00:00.000Z");

  assert.equal(
    decideStoreWebhookSync(
      {
        billingProvider: "apple_store",
        planCode: "pro",
        status: "active",
        periodEndsAt: new Date("2026-07-25T00:00:00.000Z"),
      },
      {
        billingProvider: "apple_store",
        planCode: "solo",
        status: "active",
        periodEndsAt: new Date("2026-07-25T00:00:00.000Z"),
      },
      "DID_CHANGE_RENEWAL_PREF",
      now,
    ),
    "defer_downgrade",
  );
});

test("store webhook status events do not regress plan or period", () => {
  const now = new Date("2026-06-30T00:00:00.000Z");
  const existing = {
    billingProvider: "apple_store",
    planCode: "pro",
    status: "active",
    periodEndsAt: new Date("2026-07-25T00:00:00.000Z"),
  };
  const incoming = {
    billingProvider: "apple_store",
    planCode: "pro",
    status: "canceled",
    periodEndsAt: new Date("2026-07-25T00:00:00.000Z"),
  };

  assert.equal(decideStoreWebhookSync(existing, incoming, "REFUND", now), "apply_status_only");
  assert.equal(
    decideStoreWebhookSync(
      existing,
      { ...incoming, status: "active" },
      "DID_CHANGE_RENEWAL_STATUS",
      now,
    ),
    "apply_status_only",
  );
});

test("stale ordinary store webhooks are ignored", () => {
  const now = new Date("2026-06-30T00:00:00.000Z");

  assert.equal(
    decideStoreWebhookSync(
      {
        billingProvider: "apple_store",
        planCode: "solo",
        status: "active",
        periodEndsAt: new Date("2026-07-25T00:00:00.000Z"),
      },
      {
        billingProvider: "apple_store",
        planCode: "solo",
        status: "active",
        periodEndsAt: new Date("2026-07-01T00:00:00.000Z"),
      },
      "DID_RENEW",
      now,
    ),
    "ignore",
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

test("resolveUsageAccessTruth drops expired pro trials to free-tier access (not a lockout)", () => {
  // Intentional behavior change: an expired welcome trial used to leave a
  // zombie pro/trialing row that blocked chat entirely on every non-billing
  // path (while keeping the premium brain profile) until the billing screen
  // lazily repaired it. Correct: the user falls to FREE limits immediately —
  // free plan, free brain profile, access allowed.
  const truth = resolveUsageAccessTruth({
    planCode: "pro",
    status: "trialing",
    trialEndsAt: new Date(Date.now() - 60_000),
  });

  assert.equal(truth.mode, "free");
  assert.equal(truth.planCode, "free");
  assert.equal(truth.serverBrainAllowed, true);
  assert.equal(truth.upgradeRequiredForServerBrain, false);
  assert.equal(truth.trialActive, false);
  assert.equal(truth.brainProfile.tier, "standard");
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

test("buildTrialSubscriptionSeed starts new users on the free plan (no gifted pro month)", () => {
  // Hediye 30 günlük Pro kaldırıldı: ücretli planlar App Store üzerinden
  // satılıyor ve hediye dönem abonelik durum makinesinde ayrı bir
  // "trialing" kaynağı yaratıp akışı karmaşıklaştırıyordu.
  const createdAt = new Date("2030-01-01T00:00:00.000Z");
  const seed = buildTrialSubscriptionSeed(createdAt);

  assert.equal(seed.planCode, "free");
  assert.equal(seed.status, "free");
  assert.equal(seed.currentPeriodStartedAt, createdAt);
  assert.equal(seed.periodEndsAt, null);
  assert.equal(seed.trialEndsAt, null);
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

test("billing catalog keeps desktop connections aligned with plan limits", () => {
  const free = getBillingPlan("free");
  const solo = getBillingPlan("solo");
  const pro = getBillingPlan("pro");

  assert.equal(free.desktopLimit, 0);
  assert.equal(free.monthlyPrice, 0);
  assert.equal(free.taskLimitMonthly, 50);
  assert.equal(free.aiCreditsMonthly, 120);
  assert.equal(free.fiveHourBudgetUnits, 12);
  assert.equal(free.byokRequired, false);
  assert.equal(solo.desktopLimit, 1);
  assert.equal(solo.monthlyPrice, 6.99);
  assert.equal(solo.fiveHourBudgetUnits, 18);
  assert.equal(
    solo.providerProducts.apple?.productId,
    "com.elyan.elyanMobile.solo.monthly",
  );
  assert.equal(
    solo.providerProducts.google?.productId,
    "com.elyan.elyanmobile.solo.monthly",
  );
  assert.equal(pro.desktopLimit, 2);
  assert.equal(pro.monthlyPrice, 17.99);
  assert.equal(pro.fiveHourBudgetUnits, 60);
  assert.equal(
    pro.providerProducts.apple?.productId,
    "com.elyan.elyanMobile.pro.monthly",
  );
  assert.equal(
    pro.providerProducts.google?.productId,
    "com.elyan.elyanmobile.pro.monthly",
  );
  assert.equal(canUseDesktopConnections("free"), false);
  assert.equal(canUseDesktopConnections("solo"), true);
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

test("decideAppleSubscriptionOwnership transfers even when the receipt token names another account", () => {
  // App Store aboneliği Apple ID'ye aittir. Makbuzu sunabilmek için o Apple
  // ID'de oturum açmış olmak gerekir; dolayısıyla sunan kişi Apple'a göre
  // sahiptir ve hesap değişimi DEVİRDİR, ihlal değil.
  //
  // "Tek yetki" kuralı burada değil, devir anında önceki hesabı ücretsize
  // düşüren `releaseTransferredStoreEntitlement` ile korunuyor — böylece
  // milyonlarca kullanıcı kendi Apple ID'siyle Pro/Solo alabilirken tek bir
  // abonelik asla iki hesabı birden yetkilendiremez.
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "22222222-2222-2222-2222-222222222222",
    currentUserId: "11111111-1111-1111-1111-111111111111",
    lockedByActiveStorePeriod: true,
  });
  assert.equal(decision.blocked, false);
});

test("decideAppleSubscriptionOwnership transfers an absent-token receipt instead of stranding the payer", () => {
  // DEĞİŞEN SÖZLEŞME (ve nedeni):
  //
  // Eski kural "token yoksa blokla" idi. Ama uygulama `appAccountToken`'ı bu
  // sürümden önce HİÇ göndermiyordu; dolayısıyla mevcut tüm satın almalarda
  // token yok. Kural, parasını ödemiş kullanıcıyı "bu abonelik başka bir
  // hesaba bağlı" duvarına çarpıp planından kalıcı olarak mahrum bırakıyordu.
  //
  // Token yokluğu "başkasının" kanıtı değildir; hiçbir şeyin kanıtı değildir.
  // App Store aboneliği Apple ID'ye aittir ve devri Apple'ın kendi modelidir.
  //
  // "Pro sızıntısı" (tek abonelikle iki hesabın aynı anda Pro olması) artık
  // BURADA değil, devir anında önceki sahibi ücretsize düşüren
  // `releaseTransferredStoreEntitlement` ile engelleniyor — yani özellik
  // korunuyor, yalnız doğru katmana taşındı.
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "",
    currentUserId: "11111111-1111-1111-1111-111111111111",
    lockedByActiveStorePeriod: true,
  });
  assert.equal(decision.blocked, false);
});

test("decideAppleSubscriptionOwnership accepts a receipt whose token is the current user", () => {
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "11111111-1111-1111-1111-111111111111",
    currentUserId: "11111111-1111-1111-1111-111111111111",
    lockedByActiveStorePeriod: true,
  });
  assert.equal(decision.blocked, false);
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

test("decideAppleSubscriptionOwnership does not block a different user when the period is not locked", () => {
  const decision = decideAppleSubscriptionOwnership({
    appAccountToken: "99999999-9999-9999-9999-999999999999",
    currentUserId: "11111111-1111-1111-1111-111111111111",
    lockedByActiveStorePeriod: false,
  });
  assert.equal(decision.blocked, false);
});
