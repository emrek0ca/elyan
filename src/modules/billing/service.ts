import { createHash, randomUUID } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";
import { and, desc, eq, gt, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { SignJWT, importPKCS8 } from "jose";
import {
  applyBillingPlanDefaults,
  canUseDesktopConnections,
  getBillingPlan,
  isSellablePlanCode,
  listSellableBillingPlans,
  normalizeBillingPlanCode,
  type BillingPlanCode,
} from "./catalog.js";
import { buildIyzicoCustomer, IyzicoClient, type IyzicoCatalogPlanInput } from "./iyzico.js";
import {
  aiProviderInvocations,
  billingCreditLedger,
  billingCheckoutSessions,
  billingEntitlementEvents,
  billingPlanMappings,
  billingProfiles,
  billingStoreTransactions,
  billingWebhookEvents,
  devices,
  subscriptions,
  users,
} from "../../db/schema.js";
import { createIdempotencyFingerprint } from "../../lib/idempotency.js";
import { AppError, badRequest, conflict, notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import {
  assertTrialTaskQuotaAllowedFromUsage,
  buildTrialQuotaWindows,
  getTrialQuotaUsage,
} from "../quota/service.js";
import {
  buildCreditStatus,
  buildManageSubscriptionHint,
  getCreditWindowSummary,
  recordCreditLedgerEntry,
} from "./credit-ledger.js";
import { getBillingUsageSummary } from "./usage-ledger.js";
import {
  resolveTokenBudgetState,
  TOKEN_METERING_UNIT_SIZE,
  TOKEN_METERING_VERSION,
} from "./token-metering.js";
import { shapeWelcomeProTrialOffer } from "./subscription-truth.js";
import { invalidateBrainProfileCache } from "../brain/profile-cache.js";
import { verifyAppleNotification, verifyAppleTransaction } from "./apple-store.js";

type BillingProfileInput = {
  fullName: string;
  email: string;
  phone: string;
  identityNumber: string;
  addressLine1: string;
  city: string;
  country: string;
  zipCode: string;
};

type CheckoutRow = typeof billingCheckoutSessions.$inferSelect;
type BillingDb = Pick<FastifyInstance["db"], "select" | "insert" | "update">;
type CheckoutInitializationResult = { checkout: CheckoutRow } | { failed: true; error: unknown };
type SubscriptionRow = typeof subscriptions.$inferSelect;
type BillingProvider = "iyzico" | "apple_store" | "google_play";
type BillingReadDb = Pick<FastifyInstance["db"], "select">;

const CHECKOUT_INITIALIZATION_WAIT_TIMEOUT_MS = 5_000;
const CHECKOUT_INITIALIZATION_POLL_INTERVAL_MS = 100;
const CHECKOUT_INITIALIZATION_FAILED_STATE = "failed";
export const NEW_USER_TRIAL_DAYS = 30;
const NEW_USER_TRIAL_WINDOW_MS = NEW_USER_TRIAL_DAYS * 24 * 60 * 60 * 1000;

function now(): Date {
  return new Date();
}

function getDatabaseErrorCode(error: unknown): string {
  return typeof error === "object" && error && "code" in error ? String((error as { code?: unknown }).code ?? "") : "";
}

function toDateFromEpochMs(value: unknown): Date | null {
  const numeric = Number(value || 0);

  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }

  return new Date(numeric);
}

function readObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function subscriptionStatusAllowsUsage(status?: string | null): boolean {
  const normalized = String(status || "").trim().toLowerCase();
  return normalized === "free" || normalized === "trialing" || normalized === "active";
}

function normalizeSubscriptionStatus(status?: string | null): string {
  return String(status || "free").trim().toLowerCase() || "free";
}

export type UsageAccessTruth = {
  mode: "free" | "trial" | "paid";
  planCode: BillingPlanCode;
  status: string;
  brainProfile: ReturnType<typeof getBillingPlan>["brainProfile"];
  serverBrainAllowed: boolean;
  localByokAllowed: boolean;
  trialActive: boolean;
  trialEndsAt: Date | null;
  upgradeRequiredForServerBrain: boolean;
};

export type UsagePresentationTruth = {
  accessMode: UsageAccessTruth["mode"];
  planLabelSource: "trial" | "subscription";
};

export type SharedBrainUsageBudgetTruth = {
  access: UsageAccessTruth;
  remainingAiCredits: number | null;
  grantedAiCredits: number | null;
  periodEndsAt: Date | null;
};

export function buildTrialSubscriptionSeed(createdAt: Date = now()) {
  const trialEndsAt = new Date(createdAt.getTime() + NEW_USER_TRIAL_WINDOW_MS);
  return {
    planCode: "free" as const,
    status: "free" as const,
    ...applyBillingPlanDefaults("free"),
    currentPeriodStartedAt: createdAt,
    periodEndsAt: trialEndsAt,
    trialEndsAt,
  };
}

export function shapePublicUsageSnapshot(input: {
  usage: Record<string, unknown>;
  subscription?: {
    planCode?: string | null;
    periodEndsAt?: Date | null;
  } | null;
  pendingTokens?: number | null;
}) {
  const snapshot: Record<string, unknown> = {
    ...input.usage,
  };
  const planCode = input.subscription?.planCode;
  if (typeof planCode === "string" && planCode.trim().length > 0 && snapshot.planCode == null) {
    snapshot.planCode = normalizeBillingPlanCode(planCode);
  }
  const periodEndsAt = input.subscription?.periodEndsAt;
  if (periodEndsAt instanceof Date && snapshot.periodEndsAt == null) {
    snapshot.periodEndsAt = periodEndsAt;
  }

  const pendingTokens = Math.max(0, Math.trunc(Number(input.pendingTokens ?? 0)));
  if (pendingTokens > 0) {
    snapshot.pendingTokens = pendingTokens;
    snapshot.tokenBalanceIncludesPending = true;
  } else {
    delete snapshot.pendingTokens;
    delete snapshot.tokenBalanceIncludesPending;
  }

  return snapshot;
}

export function resolveUsageAccessTruth(
  subscription?: {
    planCode?: string | null;
    status?: string | null;
    trialEndsAt?: Date | null;
    periodEndsAt?: Date | null;
  } | null,
  currentTime: Date = now(),
): UsageAccessTruth {
  const planCode = normalizeBillingPlanCode(subscription?.planCode);
  const status = normalizeSubscriptionStatus(subscription?.status);
  const trialEndsAt = subscription?.trialEndsAt ?? null;
  const hasActiveTrialWindow =
    status === "trialing" &&
    trialEndsAt instanceof Date &&
    trialEndsAt.getTime() > currentTime.getTime();
  const hasExpiredTrialWindow =
    status === "trialing" &&
    trialEndsAt instanceof Date &&
    trialEndsAt.getTime() <= currentTime.getTime();
  const trialActive = hasActiveTrialWindow;
  const periodStillActive =
    subscription?.periodEndsAt instanceof Date &&
    subscription.periodEndsAt.getTime() > currentTime.getTime();
  const paidActive =
    planCode !== "free" &&
    (
      status === "active" ||
      (status === "trialing" && !hasExpiredTrialWindow) ||
      (status === "canceled" && periodStillActive)
    );
  const freeActive = planCode === "free" && subscriptionStatusAllowsUsage(status);
  const serverBrainAllowed = trialActive || paidActive || freeActive;

  return {
    mode: trialActive ? "trial" : paidActive ? "paid" : "free",
    planCode,
    status,
    brainProfile: getBillingPlan(planCode).brainProfile,
    serverBrainAllowed,
    localByokAllowed: true,
    trialActive,
    trialEndsAt,
    upgradeRequiredForServerBrain: !serverBrainAllowed,
  };
}

export function createUpgradeOrByokRequiredError(access?: Partial<UsageAccessTruth>) {
  return new AppError(
    409,
    "upgrade_or_byok_required",
    "Token hakkın doldu. Devam etmek için planını yükselt veya kendi yerel modelini kullan.",
    {
      serverBrainAllowed: false,
      localByokAllowed: true,
      trialEndsAt: access?.trialEndsAt ?? null,
    },
  );
}

export function resolveUsagePresentationTruth(access: UsageAccessTruth): UsagePresentationTruth {
  return {
    accessMode: access.mode,
    planLabelSource: access.mode === "trial" ? "trial" : "subscription",
  };
}

function serializeCheckout(checkout: CheckoutRow) {
  return {
    referenceId: checkout.referenceId,
    planCode: normalizeBillingPlanCode(checkout.planCode),
    provider: checkout.provider,
    mode: checkout.mode,
    status: checkout.status,
    launchUrl: checkout.launchUrl,
    paymentPageUrl: checkout.paymentPageUrl,
    callbackUrl: checkout.callbackUrl,
    successUrl: checkout.successUrl,
    cancelUrl: checkout.cancelUrl,
    providerPaymentId: checkout.providerPaymentId,
    providerSubscriptionReferenceCode: checkout.providerSubscriptionReferenceCode,
    providerCustomerReferenceCode: checkout.providerCustomerReferenceCode,
    providerPricingPlanReferenceCode: checkout.providerPricingPlanReferenceCode,
    createdAt: checkout.createdAt,
    updatedAt: checkout.updatedAt,
    completedAt: checkout.completedAt,
  };
}

type CheckoutInitializationState = "ready" | "pending" | "failed";

export function getCheckoutInitializationState(
  checkout: Pick<
    CheckoutRow,
    | "paymentPageUrl"
    | "providerToken"
    | "providerPaymentId"
    | "providerSubscriptionReferenceCode"
    | "completedAt"
    | "rawLastPayload"
  >,
): CheckoutInitializationState {
  if (
    String(checkout.paymentPageUrl || "").trim() ||
    String(checkout.providerToken || "").trim() ||
    String(checkout.providerPaymentId || "").trim() ||
    String(checkout.providerSubscriptionReferenceCode || "").trim() ||
    checkout.completedAt
  ) {
    return "ready";
  }

  const payload = readObject(checkout.rawLastPayload);

  if (payload.initializationState === CHECKOUT_INITIALIZATION_FAILED_STATE) {
    return "failed";
  }

  return "pending";
}

function shapePlanSummary(code: string) {
  const plan = getBillingPlan(code);
  return {
    code: plan.code,
    label: plan.label,
    monthlyPrice: plan.monthlyPrice,
    currencyCode: plan.currencyCode,
    interval: plan.interval,
    desktopLimit: plan.desktopLimit,
    taskLimitMonthly: plan.taskLimitMonthly,
    aiCreditsMonthly: plan.aiCreditsMonthly,
    fiveHourBudgetUnits: plan.fiveHourBudgetUnits,
    dailyBudgetUnits: plan.dailyBudgetUnits,
    weeklyBudgetUnits: plan.weeklyBudgetUnits,
    documentUploadLimit: plan.documentUploadLimit,
    imageUploadLimit: plan.imageUploadLimit,
    toolUnitsLimit: plan.toolUnitsLimit,
    byokRequired: plan.byokRequired,
    brainProfile: plan.brainProfile,
    qualityProfile: plan.brainProfile.qualityProfile,
    recommended: Boolean(plan.recommended),
    features: plan.features,
    providerProducts: plan.providerProducts,
  };
}

function createCheckoutFingerprint(input: {
  planCode: Exclude<BillingPlanCode, "free">;
  successUrl?: string;
  cancelUrl?: string;
}) {
  return createIdempotencyFingerprint({
    planCode: input.planCode,
    successUrl: input.successUrl ?? null,
    cancelUrl: input.cancelUrl ?? null,
  });
}

async function getSubscriptionRowFromDb(db: BillingReadDb, userId: string): Promise<SubscriptionRow | null> {
  const rows = await db.select().from(subscriptions).where(eq(subscriptions.userId, userId)).limit(1);
  return rows[0] ?? null;
}

async function getSubscriptionRow(app: FastifyInstance, userId: string): Promise<SubscriptionRow | null> {
  return getSubscriptionRowFromDb(app.db, userId);
}

export async function getUserUsageAccessTruth(db: BillingReadDb, userId: string): Promise<UsageAccessTruth> {
  const subscription = await getSubscriptionRowFromDb(db, userId);
  return resolveUsageAccessTruth(subscription);
}

export async function assertSharedBrainUsageAllowed(
  db: BillingReadDb,
  userId: string,
  estimatedAiCredits: number,
): Promise<UsageAccessTruth> {
  const budget = await getSharedBrainUsageBudget(db, userId);
  assertSharedBrainUsageBudgetAllowed(budget, estimatedAiCredits);
  return budget.access;
}

export async function getSharedBrainUsageBudget(
  db: BillingReadDb,
  userId: string,
): Promise<SharedBrainUsageBudgetTruth> {
  const access = await getUserUsageAccessTruth(db, userId);

  if (
    access.mode === "trial" ||
    access.mode === "paid" ||
    (access.mode === "free" && access.serverBrainAllowed)
  ) {
    const usage = await getBillingUsageSummary(db, userId);
    return {
      access,
      remainingAiCredits: usage.aiUsage.remaining,
      grantedAiCredits: usage.aiUsage.granted,
      periodEndsAt: usage.periodEndsAt,
    };
  }

  throw createUpgradeOrByokRequiredError(access);
}

export function assertSharedBrainUsageBudgetAllowed(
  budget: {
    access: Pick<UsageAccessTruth, "mode">;
    remainingAiCredits: number | null;
    periodEndsAt: Date | null;
  },
  estimatedAiCredits: number,
): void {
  if (budget.remainingAiCredits == null) {
    return;
  }

  const requiredCredits = Math.max(1, Math.ceil(estimatedAiCredits));
  if (budget.remainingAiCredits < requiredCredits) {
    throw new AppError(409, "ai_credit_limit_reached", "Kullanım hakkı doldu.", {
      retryAt: budget.periodEndsAt,
      estimatedCredits: requiredCredits,
    });
  }
}

export function isStoreSubscriptionClaimLocked(
  subscription?: {
    billingProvider?: string | null;
    planCode?: string | null;
    status?: string | null;
    periodEndsAt?: Date | null;
  } | null,
  currentTime: Date = now(),
) {
  if (!subscription) {
    return false;
  }
  const provider = String(subscription.billingProvider || "").trim();
  if (provider !== "apple_store" && provider !== "google_play") {
    return false;
  }
  const planCode = normalizeBillingPlanCode(subscription.planCode);
  if (planCode === "free") {
    return false;
  }
  const status = normalizeSubscriptionStatus(subscription.status);
  const periodStillActive =
    subscription.periodEndsAt instanceof Date &&
    subscription.periodEndsAt.getTime() > currentTime.getTime();
  if (periodStillActive && (status === "active" || status === "trialing" || status === "canceled")) {
    return true;
  }
  return !(subscription.periodEndsAt instanceof Date) && (status === "active" || status === "trialing");
}

export function shouldIgnoreStaleStoreVerification(
  existing?: {
    billingProvider?: string | null;
    planCode?: string | null;
    status?: string | null;
    periodEndsAt?: Date | null;
  } | null,
  incoming?: {
    billingProvider?: string | null;
    status?: string | null;
    periodEndsAt?: Date | null;
  } | null,
  currentTime: Date = now(),
) {
  if (!existing || !incoming) {
    return false;
  }
  const existingProvider = String(existing.billingProvider || "").trim();
  const incomingProvider = String(incoming.billingProvider || "").trim();
  if (
    (existingProvider !== "apple_store" && existingProvider !== "google_play") ||
    (incomingProvider !== "apple_store" && incomingProvider !== "google_play")
  ) {
    return false;
  }
  if (normalizeBillingPlanCode(existing.planCode) === "free") {
    return false;
  }
  const existingStatus = normalizeSubscriptionStatus(existing.status);
  const existingPeriodEndsAt = existing.periodEndsAt;
  if (
    !(existingPeriodEndsAt instanceof Date) ||
    existingPeriodEndsAt.getTime() <= currentTime.getTime() ||
    (existingStatus !== "active" && existingStatus !== "trialing" && existingStatus !== "canceled")
  ) {
    return false;
  }
  const incomingPeriodEndsAt = incoming.periodEndsAt;
  return !(incomingPeriodEndsAt instanceof Date) || incomingPeriodEndsAt.getTime() <= existingPeriodEndsAt.getTime();
}

async function getUserRow(app: FastifyInstance, userId: string) {
  const rows = await app.db
    .select({
      id: users.id,
      email: users.email,
      displayName: users.displayName,
      role: users.role,
    })
    .from(users)
    .where(eq(users.id, userId))
    .limit(1);

  return rows[0] ?? null;
}

async function getBillingProfileRow(app: FastifyInstance, userId: string) {
  const rows = await app.db.select().from(billingProfiles).where(eq(billingProfiles.userId, userId)).limit(1);
  return rows[0] ?? null;
}

async function upsertBillingPlanMapping(
  app: FastifyInstance,
  input: {
    planCode: string;
    provider: BillingProvider;
    productReferenceCode: string;
    pricingPlanReferenceCode: string;
    productName: string;
    pricingPlanName: string;
    currencyCode: string;
    priceMinor: number;
  },
) {
  const planCode = normalizeBillingPlanCode(input.planCode);
  const existing = await loadBillingPlanMapping(app, {
    provider: input.provider,
    planCode,
  });

  if (existing) {
    const rows = await app.db
      .update(billingPlanMappings)
      .set({
        provider: input.provider,
        planCode,
        productReferenceCode: input.productReferenceCode,
        pricingPlanReferenceCode: input.pricingPlanReferenceCode,
        productName: input.productName,
        pricingPlanName: input.pricingPlanName,
        currencyCode: input.currencyCode,
        priceMinor: input.priceMinor,
        syncedAt: now(),
        updatedAt: now(),
      })
      .where(eq(billingPlanMappings.id, existing.id))
      .returning();

    return rows[0];
  }

  const rows = await app.db
    .insert(billingPlanMappings)
    .values({
      provider: input.provider,
      planCode,
      productReferenceCode: input.productReferenceCode,
      pricingPlanReferenceCode: input.pricingPlanReferenceCode,
      productName: input.productName,
      pricingPlanName: input.pricingPlanName,
      currencyCode: input.currencyCode,
      priceMinor: input.priceMinor,
    })
    .returning();

  return rows[0];
}

async function ensureIyzicoPlanMapping(app: FastifyInstance, planCode: Exclude<BillingPlanCode, "free">) {
  const client = new IyzicoClient(app.config);
  const productName = client.getProductName();
  const existing = await loadBillingPlanMapping(app, {
    provider: "iyzico",
    planCode,
  });

  const plan = getBillingPlan(planCode);
  const providerPlan: IyzicoCatalogPlanInput = {
    planCode: plan.code,
    planName: client.getProviderPlanName({
      planCode: plan.code,
      planName: plan.label,
      monthlyPrice: plan.monthlyPrice,
      currencyCode: plan.currencyCode,
    }),
    monthlyPrice: plan.monthlyPrice,
    currencyCode: plan.currencyCode,
  };
  const expectedPriceMinor = Math.round(plan.monthlyPrice * 100);

  if (
    existing?.pricingPlanReferenceCode &&
    existing?.productReferenceCode &&
    existing.priceMinor === expectedPriceMinor &&
    existing.pricingPlanName === providerPlan.planName &&
    existing.productName === productName &&
    existing.currencyCode === plan.currencyCode
  ) {
    return existing;
  }

  const products = await client.listProducts();
  let product = products.find((item) => String(item.name || "").trim() === productName);

  if (!product) {
    product = await client.createProduct({
      name: productName,
      description: "Elyan subscription catalog",
    });
  }

  const productReferenceCode = String(product.referenceCode || "").trim();

  if (!productReferenceCode) {
    throw conflict("iyzico_product_reference_missing");
  }

  const pricingPlans = await client.listPricingPlans(productReferenceCode);
  let pricingPlan = pricingPlans.find((item) => String(item.name || "").trim() === providerPlan.planName);

  if (!pricingPlan) {
    pricingPlan = await client.createPricingPlan(productReferenceCode, providerPlan);
  }

  const pricingPlanReferenceCode = String(pricingPlan.referenceCode || "").trim();

  if (!pricingPlanReferenceCode) {
    throw conflict("iyzico_pricing_plan_reference_missing");
  }

  return upsertBillingPlanMapping(app, {
    provider: "iyzico",
    planCode,
    productReferenceCode,
    pricingPlanReferenceCode,
    productName,
    pricingPlanName: providerPlan.planName,
    currencyCode: plan.currencyCode,
    priceMinor: expectedPriceMinor,
  });
}

async function resolvePlanCodeFromPricingReference(
  app: FastifyInstance,
  pricingPlanReferenceCode?: string | null,
  provider?: BillingProvider | null,
) {
  const reference = String(pricingPlanReferenceCode || "").trim();

  if (!reference) {
    return null;
  }

  const query = app.db
    .select({
      planCode: billingPlanMappings.planCode,
    })
    .from(billingPlanMappings);

  const rows = await query
    .where(
      provider
        ? and(eq(billingPlanMappings.provider, provider), eq(billingPlanMappings.pricingPlanReferenceCode, reference))
        : eq(billingPlanMappings.pricingPlanReferenceCode, reference),
    )
    .limit(1);

  return rows[0]?.planCode ? normalizeBillingPlanCode(rows[0].planCode) : null;
}

async function resolvePlanCodeFromProviderReference(
  app: FastifyInstance,
  input: {
    provider: BillingProvider;
    productReferenceCode?: string | null;
    pricingPlanReferenceCode?: string | null;
  },
) {
  const productReferenceCode = String(input.productReferenceCode || "").trim();
  const pricingPlanReferenceCode = String(input.pricingPlanReferenceCode || "").trim();

  if (!productReferenceCode && !pricingPlanReferenceCode) {
    return null;
  }

  const referenceConditions = [];

  if (productReferenceCode) {
    referenceConditions.push(eq(billingPlanMappings.productReferenceCode, productReferenceCode));
  }

  if (pricingPlanReferenceCode) {
    referenceConditions.push(eq(billingPlanMappings.pricingPlanReferenceCode, pricingPlanReferenceCode));
  }

  const rows = await app.db
    .select({
      planCode: billingPlanMappings.planCode,
    })
    .from(billingPlanMappings)
    .where(
      and(
        eq(billingPlanMappings.provider, input.provider),
        referenceConditions.length === 1 ? referenceConditions[0] : or(...referenceConditions),
      ),
    )
    .limit(1);

  return rows[0]?.planCode ? normalizeBillingPlanCode(rows[0].planCode) : null;
}

async function upsertCheckoutSession(
  db: BillingDb,
  input: {
    referenceId: string;
    userId: string;
    planCode: string;
    provider: string;
    status: string;
    launchUrl?: string;
    paymentPageUrl?: string;
    callbackUrl?: string;
    successUrl?: string;
    cancelUrl?: string;
    providerToken?: string;
    providerPaymentId?: string;
    providerSubscriptionReferenceCode?: string;
    providerCustomerReferenceCode?: string;
    providerPricingPlanReferenceCode?: string;
    idempotencyKey?: string;
    idempotencyFingerprint?: string;
    rawLastPayload?: Record<string, unknown>;
    completedAt?: Date | null;
  }) {
  const planCode = normalizeBillingPlanCode(input.planCode);
  const existingRows = await db
    .select()
    .from(billingCheckoutSessions)
    .where(eq(billingCheckoutSessions.referenceId, input.referenceId))
    .limit(1);

  if (existingRows[0]) {
    const rows = await db
      .update(billingCheckoutSessions)
      .set({
        planCode,
        provider: input.provider,
        status: input.status,
        launchUrl: input.launchUrl ?? existingRows[0].launchUrl,
        paymentPageUrl: input.paymentPageUrl ?? existingRows[0].paymentPageUrl,
        callbackUrl: input.callbackUrl ?? existingRows[0].callbackUrl,
        successUrl: input.successUrl ?? existingRows[0].successUrl,
        cancelUrl: input.cancelUrl ?? existingRows[0].cancelUrl,
        providerToken: input.providerToken ?? existingRows[0].providerToken,
        providerPaymentId: input.providerPaymentId ?? existingRows[0].providerPaymentId,
        providerSubscriptionReferenceCode:
          input.providerSubscriptionReferenceCode ?? existingRows[0].providerSubscriptionReferenceCode,
        providerCustomerReferenceCode:
          input.providerCustomerReferenceCode ?? existingRows[0].providerCustomerReferenceCode,
        providerPricingPlanReferenceCode:
          input.providerPricingPlanReferenceCode ?? existingRows[0].providerPricingPlanReferenceCode,
        idempotencyKey: input.idempotencyKey ?? existingRows[0].idempotencyKey,
        idempotencyFingerprint: input.idempotencyFingerprint ?? existingRows[0].idempotencyFingerprint,
        rawLastPayload: input.rawLastPayload ?? readObject(existingRows[0].rawLastPayload),
        completedAt: input.completedAt ?? existingRows[0].completedAt,
        updatedAt: now(),
      })
      .where(eq(billingCheckoutSessions.id, existingRows[0].id))
      .returning();

    return rows[0];
  }

  const rows = await db
    .insert(billingCheckoutSessions)
    .values({
      referenceId: input.referenceId,
      userId: input.userId,
      planCode,
      provider: input.provider,
      status: input.status,
      launchUrl: input.launchUrl,
      paymentPageUrl: input.paymentPageUrl,
      callbackUrl: input.callbackUrl,
      successUrl: input.successUrl,
      cancelUrl: input.cancelUrl,
      providerToken: input.providerToken,
      providerPaymentId: input.providerPaymentId,
      providerSubscriptionReferenceCode: input.providerSubscriptionReferenceCode,
      providerCustomerReferenceCode: input.providerCustomerReferenceCode,
      providerPricingPlanReferenceCode: input.providerPricingPlanReferenceCode,
      idempotencyKey: input.idempotencyKey,
      idempotencyFingerprint: input.idempotencyFingerprint,
      rawLastPayload: input.rawLastPayload ?? {},
      completedAt: input.completedAt,
    })
    .returning();

  return rows[0];
}

async function getExistingCheckoutForIdempotency(
  db: BillingDb,
  input: {
    userId: string;
    idempotencyKey?: string;
    fingerprint?: string;
  },
) {
  if (!input.idempotencyKey || !input.fingerprint) {
    return null;
  }

  const rows = await db
    .select()
    .from(billingCheckoutSessions)
    .where(
      and(
        eq(billingCheckoutSessions.userId, input.userId),
        eq(billingCheckoutSessions.idempotencyKey, input.idempotencyKey),
      ),
    )
    .limit(1);

  const checkout = rows[0];

  if (!checkout) {
    return null;
  }

  if (checkout.idempotencyFingerprint !== input.fingerprint) {
    throw new AppError(
      409,
      "idempotency_conflict",
      "Idempotency key is already bound to a different checkout payload",
      {
        idempotencyKey: input.idempotencyKey,
        existingReferenceId: checkout.referenceId,
      },
    );
  }

  return checkout;
}

function throwCheckoutInitializationState(checkout: CheckoutRow): never {
  const initializationState = getCheckoutInitializationState(checkout);

  if (initializationState === "failed") {
    throw conflict("checkout_initialization_failed", {
      referenceId: checkout.referenceId,
    });
  }

  throw conflict("checkout_initialization_in_progress", {
    referenceId: checkout.referenceId,
    retryAfterMs: CHECKOUT_INITIALIZATION_POLL_INTERVAL_MS,
  });
}

async function waitForCheckoutInitialization(
  db: BillingDb,
  input: {
    userId: string;
    idempotencyKey?: string;
    fingerprint?: string;
  },
): Promise<CheckoutRow | null> {
  const deadline = Date.now() + CHECKOUT_INITIALIZATION_WAIT_TIMEOUT_MS;

  while (Date.now() < deadline) {
    const checkout = await getExistingCheckoutForIdempotency(db, input);

    if (!checkout) {
      return null;
    }

    if (getCheckoutInitializationState(checkout) !== "pending") {
      return checkout;
    }

    await sleep(CHECKOUT_INITIALIZATION_POLL_INTERVAL_MS);
  }

  return getExistingCheckoutForIdempotency(db, input);
}

async function resolveCheckoutForIdempotentReplay(
  db: BillingDb,
  input: {
    userId: string;
    idempotencyKey?: string;
    fingerprint?: string;
  },
): Promise<CheckoutRow | null> {
  const checkout = await getExistingCheckoutForIdempotency(db, input);

  if (!checkout) {
    return null;
  }

  if (getCheckoutInitializationState(checkout) === "ready") {
    return checkout;
  }

  const awaitedCheckout = await waitForCheckoutInitialization(db, input);

  if (!awaitedCheckout) {
    return null;
  }

  if (getCheckoutInitializationState(awaitedCheckout) === "ready") {
    return awaitedCheckout;
  }

  throwCheckoutInitializationState(awaitedCheckout);
}

function createCheckoutInitializationFailurePayload(error: unknown): Record<string, unknown> {
  if (error instanceof AppError) {
    return {
      initializationState: CHECKOUT_INITIALIZATION_FAILED_STATE,
      errorCode: error.code,
      errorMessage: error.message,
      errorDetails: error.details ?? null,
    };
  }

  if (error instanceof Error) {
    return {
      initializationState: CHECKOUT_INITIALIZATION_FAILED_STATE,
      errorCode: "checkout_initialization_failed",
      errorMessage: error.message,
    };
  }

  return {
    initializationState: CHECKOUT_INITIALIZATION_FAILED_STATE,
    errorCode: "checkout_initialization_failed",
    errorMessage: "Unknown checkout initialization failure",
  };
}

async function markCheckoutInitializationFailed(db: BillingDb, referenceId: string, error: unknown): Promise<void> {
  await db
    .update(billingCheckoutSessions)
    .set({
      status: CHECKOUT_INITIALIZATION_FAILED_STATE,
      rawLastPayload: createCheckoutInitializationFailurePayload(error),
      updatedAt: now(),
    })
    .where(eq(billingCheckoutSessions.referenceId, referenceId));
}

async function markCheckoutInitializationFailedBestEffort(
  db: BillingDb,
  referenceId: string,
  error: unknown,
): Promise<void> {
  try {
    await markCheckoutInitializationFailed(db, referenceId, error);
  } catch {
    // Preserve the original checkout initialization error when cleanup also fails.
  }
}

async function persistSubscriptionState(
  app: FastifyInstance,
  userId: string,
  input: {
    planCode: string;
    status: "free" | "trialing" | "active" | "past_due" | "canceled";
    billingProvider?: string;
    providerCustomerReferenceCode?: string | null;
    providerSubscriptionReferenceCode?: string | null;
    providerPricingPlanReferenceCode?: string | null;
    currentPeriodStartedAt?: Date | null;
    periodEndsAt?: Date | null;
    trialEndsAt?: Date | null;
    cancelAtPeriodEnd?: boolean;
  },
) {
  const current = await getSubscriptionRow(app, userId);
  const incomingProvider = input.billingProvider ?? current?.billingProvider ?? "internal";
  const appleOwnsActivePeriod =
    current?.billingProvider === "apple_store" &&
    current.periodEndsAt instanceof Date &&
    current.periodEndsAt.getTime() > Date.now();
  if (appleOwnsActivePeriod && incomingProvider !== "apple_store") {
    throw conflict("active_apple_subscription_provider_locked");
  }
  const planCode = normalizeBillingPlanCode(input.planCode);
  const defaults = applyBillingPlanDefaults(planCode);
  const rows = await app.db
    .update(subscriptions)
    .set({
      planCode,
      status: input.status,
      billingProvider: incomingProvider,
      providerCustomerReferenceCode: input.providerCustomerReferenceCode ?? null,
      providerSubscriptionReferenceCode: input.providerSubscriptionReferenceCode ?? null,
      providerPricingPlanReferenceCode: input.providerPricingPlanReferenceCode ?? null,
      taskLimitMonthly: defaults.taskLimitMonthly,
      aiCreditsMonthly: defaults.aiCreditsMonthly,
      currentPeriodStartedAt: input.currentPeriodStartedAt ?? null,
      periodEndsAt: input.periodEndsAt ?? null,
      trialEndsAt: input.trialEndsAt ?? null,
      cancelAtPeriodEnd: input.cancelAtPeriodEnd ?? input.status === "canceled",
      canceledAt: input.status === "canceled" ? now() : null,
      updatedAt: now(),
    })
    .where(eq(subscriptions.userId, userId))
    .returning();

  invalidateBrainProfileCache(app, userId);
  return rows[0];
}

export async function claimWelcomeProTrial(app: FastifyInstance, userId: string) {
  const claimedAt = now();
  const trialEndsAt = new Date(claimedAt.getTime() + NEW_USER_TRIAL_WINDOW_MS);
  const proDefaults = applyBillingPlanDefaults("pro");
  const updatedRows = await app.db
    .update(subscriptions)
    .set({
      planCode: "pro",
      status: "trialing",
      billingProvider: "welcome_trial",
      providerCustomerReferenceCode: null,
      providerSubscriptionReferenceCode: null,
      providerPricingPlanReferenceCode: null,
      taskLimitMonthly: proDefaults.taskLimitMonthly,
      aiCreditsMonthly: proDefaults.aiCreditsMonthly,
      currentPeriodStartedAt: claimedAt,
      periodEndsAt: trialEndsAt,
      trialEndsAt,
      cancelAtPeriodEnd: false,
      canceledAt: null,
      updatedAt: claimedAt,
    })
    .where(
      and(
        eq(subscriptions.userId, userId),
        eq(subscriptions.planCode, "free"),
        eq(subscriptions.status, "free"),
        gt(subscriptions.trialEndsAt, claimedAt),
      ),
    )
    .returning();

  if (updatedRows[0]) {
    invalidateBrainProfileCache(app, userId);
    return getBillingSummary(app, userId);
  }

  const subscription = await getSubscriptionRow(app, userId);
  const offer = shapeWelcomeProTrialOffer(subscription, claimedAt);

  if (offer.claimed) {
    return getBillingSummary(app, userId);
  }

  throw conflict(offer.status === "expired" ? "welcome_pro_trial_expired" : "welcome_pro_trial_unavailable", {
    trialOffer: offer,
  });
}

type StorePlatform = "apple" | "google";

type StorePurchaseVerificationInput = {
  platform: StorePlatform;
  planCode: Exclude<BillingPlanCode, "free">;
  productId: string;
  verificationData: string;
  transactionId?: string;
  originalTransactionId?: string;
  packageName?: string;
};

function normalizeStorePlatform(platform: string): StorePlatform {
  const normalized = platform.trim().toLowerCase();
  if (normalized === "apple" || normalized === "google") {
    return normalized;
  }
  throw badRequest("Unsupported store platform");
}

function parseEpochMs(value: unknown): Date | null {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }
  return new Date(numeric);
}

function readReceiptText(value: unknown): string {
  return String(value || "").trim();
}

function parseJsonObject(value: string): Record<string, unknown> | null {
  const trimmed = value.trim();

  if (!trimmed) {
    return null;
  }

  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function readStoreVerificationPayload(input: StorePurchaseVerificationInput): Record<string, unknown> {
  return parseJsonObject(input.verificationData) ?? {};
}

export function getBillingProviderForStorePlatform(platform: StorePlatform): BillingProvider {
  return platform === "apple" ? "apple_store" : "google_play";
}

async function loadBillingPlanMapping(
  app: FastifyInstance,
  input: {
    provider: BillingProvider;
    planCode: string;
  },
) {
  const planCode = normalizeBillingPlanCode(input.planCode);
  const rows = await app.db
    .select()
    .from(billingPlanMappings)
    .where(and(eq(billingPlanMappings.provider, input.provider), eq(billingPlanMappings.planCode, planCode)))
    .limit(1);

  return rows[0] ?? null;
}

function buildStoreEventKey(platform: StorePlatform, referenceId: string) {
  return `store:${platform}:${referenceId}`;
}

function hashBillingPayload(payload: Record<string, unknown>) {
  return createHash("sha256").update(JSON.stringify(payload)).digest("hex");
}

export async function upsertStoreTransaction(
  app: FastifyInstance,
  input: {
    userId?: string | null;
    provider: BillingProvider;
    planCode: string;
    productId?: string | null;
    purchaseToken?: string | null;
    originalTransactionId?: string | null;
    transactionId?: string | null;
    orderId?: string | null;
    linkedPurchaseToken?: string | null;
    environment?: string | null;
    appAccountToken?: string | null;
    status: string;
    payload: Record<string, unknown>;
    verifiedAt?: Date | null;
    allowUserReassignment?: boolean;
  },
) {
  const planCode = normalizeBillingPlanCode(input.planCode);
  const transactionId = readReceiptText(input.transactionId) || null;
  const purchaseToken = readReceiptText(input.purchaseToken) || null;
  const originalTransactionId = readReceiptText(input.originalTransactionId) || null;
  const orderId = readReceiptText(input.orderId) || null;
  const rawPayloadHash = hashBillingPayload(input.payload);
  const matchConditions = [];
  if (transactionId) {
    matchConditions.push(and(eq(billingStoreTransactions.provider, input.provider), eq(billingStoreTransactions.transactionId, transactionId)));
  }
  if (purchaseToken) {
    matchConditions.push(and(eq(billingStoreTransactions.provider, input.provider), eq(billingStoreTransactions.purchaseToken, purchaseToken)));
  }
  if (originalTransactionId) {
    matchConditions.push(
      and(eq(billingStoreTransactions.provider, input.provider), eq(billingStoreTransactions.originalTransactionId, originalTransactionId)),
    );
  }

  const existingRows = matchConditions.length
    ? await app.db
        .select()
        .from(billingStoreTransactions)
        .where(or(...matchConditions))
        .limit(1)
    : [];

  if (existingRows[0]) {
    if (input.userId && existingRows[0].userId && existingRows[0].userId !== input.userId && !input.allowUserReassignment) {
      throw conflict("store_transaction_owned_by_another_user");
    }
    const rows = await app.db
      .update(billingStoreTransactions)
      .set({
        userId: input.userId ?? existingRows[0].userId,
        planCode,
        productId: input.productId ?? existingRows[0].productId,
        purchaseToken: purchaseToken ?? existingRows[0].purchaseToken,
        originalTransactionId: originalTransactionId ?? existingRows[0].originalTransactionId,
        transactionId: transactionId ?? existingRows[0].transactionId,
        orderId: orderId ?? existingRows[0].orderId,
        linkedPurchaseToken: input.linkedPurchaseToken ?? existingRows[0].linkedPurchaseToken,
        environment: input.environment ?? existingRows[0].environment,
        appAccountToken: input.appAccountToken ?? existingRows[0].appAccountToken,
        status: input.status,
        rawPayloadHash,
        payload: input.payload,
        verifiedAt: input.verifiedAt ?? existingRows[0].verifiedAt,
        lastSeenAt: now(),
        updatedAt: now(),
      })
      .where(eq(billingStoreTransactions.id, existingRows[0].id))
      .returning();

    return rows[0];
  }

  const rows = await app.db
    .insert(billingStoreTransactions)
    .values({
      userId: input.userId ?? null,
      provider: input.provider,
      planCode,
      productId: input.productId ?? null,
      purchaseToken,
      originalTransactionId,
      transactionId,
      orderId,
      linkedPurchaseToken: input.linkedPurchaseToken ?? null,
      environment: input.environment ?? null,
      appAccountToken: input.appAccountToken ?? null,
      status: input.status,
      rawPayloadHash,
      payload: input.payload,
      verifiedAt: input.verifiedAt ?? now(),
      lastSeenAt: now(),
      updatedAt: now(),
    })
    .returning();

  return rows[0];
}

async function insertEntitlementEvent(
  app: FastifyInstance,
  input: {
    userId: string;
    storeTransactionId?: string | null;
    sourceProvider: BillingProvider;
    planCode: string;
    eventType: string;
    status: string;
    sourceReferenceCode?: string | null;
    effectivePeriodStartedAt?: Date | null;
    effectivePeriodEndsAt?: Date | null;
    creditGrantAmount?: number;
    creditDelta?: number;
    revokeFutureEntitlement?: boolean;
    payload: Record<string, unknown>;
  },
) {
  const planCode = normalizeBillingPlanCode(input.planCode);
  const eventFingerprint = hashBillingPayload({
    userId: input.userId,
    sourceProvider: input.sourceProvider,
    planCode,
    eventType: input.eventType,
    status: input.status,
    sourceReferenceCode: input.sourceReferenceCode ?? null,
    effectivePeriodStartedAt: input.effectivePeriodStartedAt?.toISOString() ?? null,
    effectivePeriodEndsAt: input.effectivePeriodEndsAt?.toISOString() ?? null,
    creditGrantAmount: input.creditGrantAmount ?? 0,
    creditDelta: input.creditDelta ?? 0,
  });

  const existing = await app.db
    .select()
    .from(billingEntitlementEvents)
    .where(eq(billingEntitlementEvents.eventFingerprint, eventFingerprint))
    .limit(1);

  if (existing[0]) {
    return { event: existing[0], created: false } as const;
  }

  const rows = await app.db
    .insert(billingEntitlementEvents)
    .values({
      userId: input.userId,
      storeTransactionId: input.storeTransactionId ?? null,
      sourceProvider: input.sourceProvider,
      planCode,
      eventType: input.eventType,
      status: input.status,
      sourceReferenceCode: input.sourceReferenceCode ?? null,
      eventFingerprint,
      effectivePeriodStartedAt: input.effectivePeriodStartedAt ?? null,
      effectivePeriodEndsAt: input.effectivePeriodEndsAt ?? null,
      creditGrantAmount: Math.max(0, Math.trunc(input.creditGrantAmount ?? 0)),
      creditDelta: Math.trunc(input.creditDelta ?? 0),
      revokeFutureEntitlement: input.revokeFutureEntitlement ?? false,
      payload: input.payload,
    })
    .returning();

  return { event: rows[0], created: true } as const;
}

async function grantPlanCredits(
  app: FastifyInstance,
  input: {
    userId: string;
    entitlementEventId: string;
    amount: number;
    planCode: string;
    periodEndsAt?: Date | null;
    sourceProvider: BillingProvider;
  },
) {
  if (input.amount <= 0) {
    return null;
  }

  const planCode = normalizeBillingPlanCode(input.planCode);
  return recordCreditLedgerEntry(app.db, {
    userId: input.userId,
    entitlementEventId: input.entitlementEventId,
    reason: "subscription_grant",
    deltaCredits: Math.max(0, Math.trunc(input.amount)),
    metadata: {
      planCode,
      sourceProvider: input.sourceProvider,
      periodEndsAt: input.periodEndsAt?.toISOString() ?? null,
    },
  });
}

async function applyStoreEntitlementEvent(
  app: FastifyInstance,
  input: {
    userId: string;
    sourceProvider: BillingProvider;
    planCode: BillingPlanCode;
    eventType: string;
    status: "free" | "trialing" | "active" | "past_due" | "canceled";
    sourceReferenceCode?: string | null;
    storeTransactionId?: string | null;
    currentPeriodStartedAt?: Date | null;
    periodEndsAt?: Date | null;
    payload: Record<string, unknown>;
  },
) {
  const planCode = normalizeBillingPlanCode(input.planCode);
  const plan = getBillingPlan(planCode);
  const shouldGrant =
    (input.status === "active" || input.status === "trialing") &&
    input.periodEndsAt instanceof Date &&
    input.periodEndsAt.getTime() > Date.now();

  const entitlementResult = await insertEntitlementEvent(app, {
    userId: input.userId,
    storeTransactionId: input.storeTransactionId ?? null,
    sourceProvider: input.sourceProvider,
    planCode,
    eventType: input.eventType,
    status: input.status,
    sourceReferenceCode: input.sourceReferenceCode ?? null,
    effectivePeriodStartedAt: input.currentPeriodStartedAt ?? null,
    effectivePeriodEndsAt: input.periodEndsAt ?? null,
    creditGrantAmount: shouldGrant ? plan.aiCreditsMonthly : 0,
    payload: input.payload,
  });

  if (entitlementResult.created && shouldGrant) {
    await grantPlanCredits(app, {
      userId: input.userId,
      entitlementEventId: entitlementResult.event.id,
      amount: plan.aiCreditsMonthly,
      planCode: plan.code,
      periodEndsAt: input.periodEndsAt ?? null,
      sourceProvider: input.sourceProvider,
    });
  }

  return entitlementResult.event;
}

function readAppleTransactionJws(input: StorePurchaseVerificationInput, payload: Record<string, unknown>) {
  const rawVerificationData = readReceiptText(input.verificationData);

  if (rawVerificationData.includes(".") && !rawVerificationData.trim().startsWith("{")) {
    return rawVerificationData;
  }

  const signedTransactionInfo = readReceiptText(payload.signedTransactionInfo);
  if (signedTransactionInfo) {
    return signedTransactionInfo;
  }

  const transactionInfo = readReceiptText(payload.transactionInfo);
  if (transactionInfo) {
    return transactionInfo;
  }

  return "";
}

function resolveApplePlanCode(app: FastifyInstance, productId: string): Exclude<BillingPlanCode, "free"> {
  const mappings = new Map<string, Exclude<BillingPlanCode, "free">>([
    [app.config.APPLE_SOLO_PRODUCT_ID.trim(), "solo"],
    [app.config.APPLE_PRO_PRODUCT_ID.trim(), "pro"],
  ]);
  const planCode = mappings.get(productId);
  if (!planCode) {
    throw conflict("apple_product_not_configured", { productId });
  }
  return planCode;
}

async function ensureStorePlanMapping(
  app: FastifyInstance,
  input: {
    provider: BillingProvider;
    planCode: BillingPlanCode;
    productReferenceCode: string;
    pricingPlanReferenceCode: string;
    productName: string;
    pricingPlanName: string;
    currencyCode: string;
    priceMinor: number;
  },
) {
  const planCode = normalizeBillingPlanCode(input.planCode);
  const existing = await loadBillingPlanMapping(app, {
    provider: input.provider,
    planCode,
  });

  if (existing) {
    if (
      existing.productReferenceCode !== input.productReferenceCode ||
      existing.pricingPlanReferenceCode !== input.pricingPlanReferenceCode
    ) {
      throw conflict("billing_plan_mapping_conflict", {
        provider: input.provider,
        planCode,
      });
    }

    if (
      existing.productName !== input.productName ||
      existing.pricingPlanName !== input.pricingPlanName ||
      existing.currencyCode !== input.currencyCode ||
      existing.priceMinor !== input.priceMinor
    ) {
      return upsertBillingPlanMapping(app, input);
    }

    return existing;
  }

  return upsertBillingPlanMapping(app, input);
}

async function verifyAppleStorePurchase(app: FastifyInstance, input: StorePurchaseVerificationInput) {
  const payload = readStoreVerificationPayload(input);
  const transactionJws = readAppleTransactionJws(input, payload);
  if (!transactionJws) {
    throw conflict("apple_signed_transaction_missing");
  }
  const verified = await verifyAppleTransaction(app.config, transactionJws);
  const transaction = verified.transaction;
  const bundleId = readReceiptText(transaction.bundleId);
  const productId = readReceiptText(transaction.productId);
  const returnedOriginalTransactionId = readReceiptText(transaction.originalTransactionId);
  const returnedTransactionId = readReceiptText(transaction.transactionId);
  const appAccountToken = readReceiptText(transaction.appAccountToken);
  const purchaseDate = parseEpochMs(transaction.purchaseDate);
  const expiresAt = parseEpochMs(transaction.expiresDate);
  const revocationDate = parseEpochMs(transaction.revocationDate);
  const isTrial =
    String(transaction.offerDiscountType || "").trim().toLowerCase().includes("trial") ||
    String(transaction.offerType || "").trim().toLowerCase().includes("trial");
  const resolvedPlanCode = resolveApplePlanCode(app, productId);
  const plan = getBillingPlan(resolvedPlanCode);
  if (!returnedTransactionId || !returnedOriginalTransactionId) {
    throw conflict("apple_transaction_identifiers_missing");
  }

  if (input.planCode !== resolvedPlanCode) {
    throw conflict("apple_plan_product_mismatch", {
      requestedPlanCode: input.planCode,
      verifiedPlanCode: resolvedPlanCode,
    });
  }
  if (productId !== input.productId) {
    throw conflict("apple_product_mismatch", {
      productId,
    });
  }

  await ensureStorePlanMapping(app, {
    provider: "apple_store",
    planCode: plan.code,
    productReferenceCode: input.productId,
    pricingPlanReferenceCode: input.productId,
    productName: plan.label,
    pricingPlanName: plan.label,
    currencyCode: plan.currencyCode,
    priceMinor: Math.round(plan.monthlyPrice * 100),
  });

  return {
    billingProvider: "apple_store",
    providerCustomerReferenceCode: returnedOriginalTransactionId,
    providerSubscriptionReferenceCode: returnedOriginalTransactionId,
    providerPricingPlanReferenceCode: productId,
    currentPeriodStartedAt: purchaseDate,
    periodEndsAt: expiresAt,
    trialEndsAt: isTrial ? expiresAt : null,
    status: revocationDate
      ? "canceled"
      : isTrial && expiresAt && expiresAt.getTime() > Date.now()
        ? "trialing"
        : expiresAt && expiresAt.getTime() > Date.now()
          ? "active"
          : "past_due",
    verificationPayload: {
      transactionInfo: transaction,
      certificateVerified: true,
    },
    referenceId: returnedTransactionId,
    transactionId: returnedTransactionId,
    originalTransactionId: returnedOriginalTransactionId,
    appAccountToken,
    environment: verified.environment,
    productId,
    planCode: resolvedPlanCode,
  } as const;
}

async function getGooglePlayAccessToken(app: FastifyInstance) {
  const serviceAccountEmail = app.config.GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL.trim();
  const privateKey = app.config.GOOGLE_PLAY_PRIVATE_KEY.trim().replace(/\\n/g, "\n");

  if (!serviceAccountEmail || !privateKey) {
    throw conflict("google_play_service_account_missing");
  }

  const key = await importPKCS8(privateKey, "RS256");
  const assertion = await new SignJWT({ scope: "https://www.googleapis.com/auth/androidpublisher" })
    .setProtectedHeader({ alg: "RS256", typ: "JWT" })
    .setIssuer(serviceAccountEmail)
    .setSubject(serviceAccountEmail)
    .setAudience("https://oauth2.googleapis.com/token")
    .setIssuedAt()
    .setExpirationTime("55m")
    .sign(key);

  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion,
    }),
  });

  if (!response.ok) {
    throw conflict("google_play_access_token_failed", {
      statusCode: response.status,
    });
  }

  const payload = (await response.json()) as Record<string, unknown>;
  const accessToken = readReceiptText(payload.access_token);
  if (!accessToken) {
    throw conflict("google_play_access_token_missing");
  }

  return accessToken;
}

async function verifyGooglePlayStorePurchase(app: FastifyInstance, input: StorePurchaseVerificationInput) {
  const packageName = readReceiptText(input.packageName || app.config.GOOGLE_PLAY_PACKAGE_NAME);
  if (!packageName) {
    throw conflict("google_play_package_name_missing");
  }

  const accessToken = await getGooglePlayAccessToken(app);
  const purchaseToken = readReceiptText(input.verificationData);
  const response = await fetch(
    `https://androidpublisher.googleapis.com/androidpublisher/v3/applications/${encodeURIComponent(packageName)}/purchases/subscriptionsv2/tokens/${encodeURIComponent(purchaseToken)}`,
    {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        accept: "application/json",
      },
    },
  );

  if (!response.ok) {
    throw conflict("google_play_purchase_verification_failed", {
      statusCode: response.status,
    });
  }

  const payload = (await response.json()) as Record<string, unknown>;
  const lineItem = Array.isArray(payload.lineItems)
    ? (payload.lineItems[0] && typeof payload.lineItems[0] === "object" && !Array.isArray(payload.lineItems[0])
        ? (payload.lineItems[0] as Record<string, unknown>)
        : null)
    : null;
  const expiryAt = parseEpochMs(lineItem?.expiryTime ?? payload.expiryTime);
  const startAt = parseEpochMs(payload.startTime);
  const orderId =
    readReceiptText(payload.latestOrderId) ||
    readReceiptText(lineItem?.latestSuccessfulOrderId) ||
    purchaseToken;
  const linkedToken = readReceiptText(payload.linkedPurchaseToken);
  const subscriptionState = String(payload.subscriptionState || "").trim().toUpperCase();
  const acknowledgementState = String(payload.acknowledgementState || "").trim().toUpperCase();
  const canceledStateContext =
    payload.canceledStateContext && typeof payload.canceledStateContext === "object"
      ? (payload.canceledStateContext as Record<string, unknown>)
      : null;

  if (acknowledgementState !== "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED") {
    await fetch(
      `https://androidpublisher.googleapis.com/androidpublisher/v3/applications/${encodeURIComponent(packageName)}/purchases/subscriptions/${encodeURIComponent(input.productId)}/tokens/${encodeURIComponent(purchaseToken)}:acknowledge`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${accessToken}`,
          accept: "application/json",
        },
      },
    ).catch(() => null);
  }

  const plan = getBillingPlan(input.planCode);
  await ensureStorePlanMapping(app, {
    provider: "google_play",
    planCode: plan.code,
    productReferenceCode: input.productId,
    pricingPlanReferenceCode: input.productId,
    productName: plan.label,
    pricingPlanName: plan.label,
    currencyCode: plan.currencyCode,
    priceMinor: Math.round(plan.monthlyPrice * 100),
  });

  const status =
    subscriptionState === "SUBSCRIPTION_STATE_CANCELED" || canceledStateContext
      ? "canceled"
      : subscriptionState === "SUBSCRIPTION_STATE_IN_GRACE_PERIOD" ||
          subscriptionState === "SUBSCRIPTION_STATE_ON_HOLD" ||
          (expiryAt != null && expiryAt.getTime() <= Date.now())
        ? "past_due"
        : "active";

  return {
    billingProvider: "google_play",
    providerCustomerReferenceCode: orderId,
    providerSubscriptionReferenceCode: purchaseToken,
    providerPricingPlanReferenceCode: input.productId,
    currentPeriodStartedAt: startAt,
    periodEndsAt: expiryAt,
    trialEndsAt: subscriptionState === "SUBSCRIPTION_STATE_IN_TRIAL" ? expiryAt : null,
    status,
    verificationPayload: payload,
    referenceId: orderId || purchaseToken,
    linkedToken,
    purchaseToken,
    orderId,
    productId: input.productId,
    environment: "Production",
  } as const;
}

async function persistStoreVerificationEvent(
  app: FastifyInstance,
  input: {
    platform: StorePlatform;
    referenceId: string;
    userId: string;
    planCode: BillingPlanCode;
    payload: Record<string, unknown>;
  },
) {
  const provider = getBillingProviderForStorePlatform(input.platform);
  const planCode = normalizeBillingPlanCode(input.planCode);

  await insertWebhookEvent(app, {
    eventKey: buildStoreEventKey(input.platform, input.referenceId),
    provider,
    eventType: "purchase_verified",
    status: "verified",
    userId: input.userId,
    providerSubscriptionReferenceCode: input.referenceId,
    providerCustomerReferenceCode: input.referenceId,
    payload: {
      platform: input.platform,
      planCode,
      ...input.payload,
    },
  });
}

export async function verifyStorePurchase(
  app: FastifyInstance,
  userId: string,
  input: StorePurchaseVerificationInput,
) {
  const platform = normalizeStorePlatform(input.platform);
  const provider = getBillingProviderForStorePlatform(platform);
  const requestedPlanCode = normalizeBillingPlanCode(input.planCode);
  const requestedPlan = getBillingPlan(requestedPlanCode);
  if (!isSellablePlanCode(requestedPlan.code)) {
    throw badRequest("Unsupported billing plan for store verification");
  }

  const verification =
    platform === "apple"
      ? await verifyAppleStorePurchase(app, input)
      : await verifyGooglePlayStorePurchase(app, input);
  const planCode = "planCode" in verification
    ? normalizeBillingPlanCode(verification.planCode)
    : requestedPlanCode;
  const plan = getBillingPlan(planCode);
  let allowStoreTransactionUserReassignment = false;
  if (platform === "apple") {
    const originalTransactionId = "originalTransactionId" in verification
      ? readReceiptText(verification.originalTransactionId)
      : "";
    const appAccountToken = "appAccountToken" in verification
      ? readReceiptText(verification.appAccountToken)
      : "";
    if (originalTransactionId) {
      const ownedTransactions = await app.db
        .select({
          userId: billingStoreTransactions.userId,
        })
        .from(billingStoreTransactions)
        .where(
          and(
            eq(billingStoreTransactions.provider, provider),
            eq(billingStoreTransactions.originalTransactionId, originalTransactionId),
          ),
        )
        .limit(1);
      if (ownedTransactions[0]?.userId && ownedTransactions[0].userId !== userId) {
        const existingSubscription = await loadSubscriptionForProviderRefs(app, {
          providerSubscriptionReferenceCode: originalTransactionId,
          providerCustomerReferenceCode: originalTransactionId,
        });
        const verifiedForCurrentUser = appAccountToken === userId;
        const lockedByActiveStorePeriod = isStoreSubscriptionClaimLocked(existingSubscription);
        if (!verifiedForCurrentUser && lockedByActiveStorePeriod) {
          throw conflict("apple_subscription_owned_by_another_user");
        }
        allowStoreTransactionUserReassignment = true;
      }
    }
  }

  const existingSubscription = await getSubscriptionRow(app, userId);
  if (
    shouldIgnoreStaleStoreVerification(existingSubscription, {
      billingProvider: verification.billingProvider || provider,
      status: verification.status,
      periodEndsAt: verification.periodEndsAt,
    })
  ) {
    app.log.warn(
      {
        userId,
        platform,
        provider,
        currentPlanCode: existingSubscription?.planCode ?? null,
        currentStatus: existingSubscription?.status ?? null,
        currentPeriodEndsAt: existingSubscription?.periodEndsAt ?? null,
        incomingPlanCode: planCode,
        incomingStatus: verification.status,
        incomingPeriodEndsAt: verification.periodEndsAt,
        incomingReferenceId: verification.referenceId,
      },
      "Ignoring stale store verification that would downgrade an active subscription period",
    );
    return getBillingSummary(app, userId);
  }

  await persistStoreVerificationEvent(app, {
    platform,
    referenceId: verification.referenceId,
    userId,
    planCode,
    payload: verification.verificationPayload,
  });

  const storeTransaction = await upsertStoreTransaction(app, {
    userId,
    provider,
    planCode,
    productId: verification.productId ?? input.productId,
    purchaseToken:
      platform === "apple"
        ? null
        : "purchaseToken" in verification
        ? readReceiptText(verification.purchaseToken)
        : readReceiptText(input.verificationData),
    originalTransactionId:
      "originalTransactionId" in verification
        ? readReceiptText(verification.originalTransactionId)
        : readReceiptText(input.originalTransactionId),
    transactionId:
      "transactionId" in verification
        ? readReceiptText(verification.transactionId)
        : readReceiptText(input.transactionId),
    orderId: "orderId" in verification ? readReceiptText(verification.orderId) : null,
    linkedPurchaseToken: "linkedToken" in verification ? readReceiptText(verification.linkedToken) : null,
    environment: "environment" in verification ? readReceiptText(verification.environment) : null,
    appAccountToken:
      "appAccountToken" in verification ? readReceiptText(verification.appAccountToken) : null,
    status: verification.status,
    payload: verification.verificationPayload,
    verifiedAt: now(),
    allowUserReassignment: allowStoreTransactionUserReassignment,
  });

  await persistSubscriptionState(app, userId, {
    planCode,
    status: verification.status,
    billingProvider: verification.billingProvider || provider,
    providerCustomerReferenceCode: verification.providerCustomerReferenceCode,
    providerSubscriptionReferenceCode: verification.providerSubscriptionReferenceCode,
    providerPricingPlanReferenceCode: verification.providerPricingPlanReferenceCode,
    currentPeriodStartedAt: verification.currentPeriodStartedAt,
    periodEndsAt: verification.periodEndsAt,
    trialEndsAt: verification.trialEndsAt,
  });

  await applyStoreEntitlementEvent(app, {
    userId,
    sourceProvider: verification.billingProvider || provider,
    planCode: plan.code,
    eventType: "purchase_verified",
    status: verification.status,
    sourceReferenceCode: verification.referenceId,
    storeTransactionId: storeTransaction.id,
    currentPeriodStartedAt: verification.currentPeriodStartedAt,
    periodEndsAt: verification.periodEndsAt,
    payload: verification.verificationPayload,
  });

  return getBillingSummary(app, userId);
}

function buildProfileState(
  profile: typeof billingProfiles.$inferSelect | null,
  userEmail: string,
) {
  const materialized = {
    fullName: profile?.fullName ?? "",
    email: profile?.email ?? userEmail,
    phone: profile?.phone ?? "",
    identityNumber: profile?.identityNumber ?? "",
    addressLine1: profile?.addressLine1 ?? "",
    city: profile?.city ?? "",
    country: profile?.country ?? "",
    zipCode: profile?.zipCode ?? "",
  };
  const requiredEntries = Object.entries(materialized);
  const missingFields = requiredEntries.filter(([, value]) => !String(value || "").trim()).map(([key]) => key);

  return {
    isComplete: missingFields.length === 0,
    missingFields,
    profile: materialized,
  };
}

function extractSubscriptionDetail(payload: Record<string, unknown>) {
  const data = payload.data && typeof payload.data === "object" && !Array.isArray(payload.data)
    ? (payload.data as Record<string, unknown>)
    : payload;

  return {
    referenceCode: String(data.referenceCode || "").trim(),
    parentReferenceCode: String(data.parentReferenceCode || "").trim(),
    pricingPlanReferenceCode: String(data.pricingPlanReferenceCode || "").trim(),
    customerReferenceCode: String(data.customerReferenceCode || "").trim(),
    subscriptionStatus: String(data.subscriptionStatus || payload.status || "").trim(),
    startDate: toDateFromEpochMs(data.startDate),
    endDate: toDateFromEpochMs(data.endDate),
    trialEndDate: toDateFromEpochMs(data.trialEndDate),
  };
}

async function loadCheckoutForReference(app: FastifyInstance, referenceId: string) {
  const rows = await app.db
    .select()
    .from(billingCheckoutSessions)
    .where(eq(billingCheckoutSessions.referenceId, referenceId))
    .limit(1);

  return rows[0] ?? null;
}

async function loadCheckoutBySubscriptionReference(app: FastifyInstance, subscriptionReferenceCode: string) {
  const rows = await app.db
    .select()
    .from(billingCheckoutSessions)
    .where(eq(billingCheckoutSessions.providerSubscriptionReferenceCode, subscriptionReferenceCode))
    .limit(1);

  return rows[0] ?? null;
}

async function loadSubscriptionForProviderRefs(
  app: FastifyInstance,
  input: {
    providerSubscriptionReferenceCode?: string | null;
    providerCustomerReferenceCode?: string | null;
  },
) {
  const conditions = [];

  if (input.providerSubscriptionReferenceCode) {
    conditions.push(eq(subscriptions.providerSubscriptionReferenceCode, input.providerSubscriptionReferenceCode));
  }

  if (input.providerCustomerReferenceCode) {
    conditions.push(eq(subscriptions.providerCustomerReferenceCode, input.providerCustomerReferenceCode));
  }

  if (conditions.length === 0) {
    return null;
  }

  const predicate = conditions.length === 1 ? conditions[0] : or(...conditions);
  const rows = await app.db.select().from(subscriptions).where(predicate).limit(1);
  return rows[0] ?? null;
}

async function insertWebhookEvent(
  app: FastifyInstance,
  input: {
    eventKey: string;
    provider?: string;
    eventType: string;
    status: string;
    userId?: string | null;
    checkoutReferenceId?: string | null;
    providerSubscriptionReferenceCode?: string | null;
    providerCustomerReferenceCode?: string | null;
    payload: Record<string, unknown>;
  },
) {
  const existing = await app.db
    .select()
    .from(billingWebhookEvents)
    .where(eq(billingWebhookEvents.eventKey, input.eventKey))
    .limit(1);

  if (existing[0]) {
    return existing[0];
  }

  const rows = await app.db
    .insert(billingWebhookEvents)
    .values({
      eventKey: input.eventKey,
      provider: input.provider ?? "iyzico",
      eventType: input.eventType,
      status: input.status,
      userId: input.userId ?? null,
      checkoutReferenceId: input.checkoutReferenceId ?? null,
      providerSubscriptionReferenceCode: input.providerSubscriptionReferenceCode ?? null,
      providerCustomerReferenceCode: input.providerCustomerReferenceCode ?? null,
      payload: input.payload,
    })
    .returning();

  return rows[0];
}

export async function listBillingPlans(app: FastifyInstance, userId?: string) {
  const currentSubscription = userId ? await getSubscriptionRow(app, userId) : null;

  return {
    plans: listSellableBillingPlans().map((plan) => ({
      ...shapePlanSummary(plan.code),
      current: normalizeBillingPlanCode(currentSubscription?.planCode) === plan.code,
    })),
    currentPlanCode: normalizeBillingPlanCode(currentSubscription?.planCode),
  };
}

export async function getBillingProfileState(app: FastifyInstance, userId: string) {
  const [user, profile] = await Promise.all([getUserRow(app, userId), getBillingProfileRow(app, userId)]);

  if (!user) {
    throw notFound("User not found");
  }

  return buildProfileState(profile, user.email);
}

export async function saveBillingProfile(app: FastifyInstance, userId: string, input: BillingProfileInput) {
  const existing = await getBillingProfileRow(app, userId);

  if (existing) {
    const rows = await app.db
      .update(billingProfiles)
      .set({
        fullName: input.fullName,
        email: input.email,
        phone: input.phone,
        identityNumber: input.identityNumber,
        addressLine1: input.addressLine1,
        city: input.city,
        country: input.country,
        zipCode: input.zipCode,
        updatedAt: now(),
      })
      .where(eq(billingProfiles.id, existing.id))
      .returning();

    return buildProfileState(rows[0], input.email);
  }

  const rows = await app.db
    .insert(billingProfiles)
    .values({
      userId,
      fullName: input.fullName,
      email: input.email,
      phone: input.phone,
      identityNumber: input.identityNumber,
      addressLine1: input.addressLine1,
      city: input.city,
      country: input.country,
      zipCode: input.zipCode,
    })
    .returning();

  return buildProfileState(rows[0], input.email);
}

export async function getBillingSummary(app: FastifyInstance, userId: string) {
  const [user, loadedSubscription, profile] = await Promise.all([
    getUserRow(app, userId),
    getSubscriptionRow(app, userId),
    getBillingProfileRow(app, userId),
  ]);

  if (!user) {
    throw notFound("User not found");
  }
  let subscription = loadedSubscription;
  const currentTime = now();
  const welcomeProExpired =
    subscription?.billingProvider === "welcome_trial" &&
    subscription.status === "trialing" &&
    subscription.periodEndsAt instanceof Date &&
    subscription.periodEndsAt.getTime() <= currentTime.getTime();
  const canceledPaidPeriodEnded =
    subscription?.billingProvider === "apple_store" &&
    subscription.status === "canceled" &&
    subscription.periodEndsAt instanceof Date &&
    subscription.periodEndsAt.getTime() <= currentTime.getTime();
  if (subscription && (welcomeProExpired || canceledPaidPeriodEnded)) {
    const freeDefaults = applyBillingPlanDefaults("free");
    const nextPeriodEnd = new Date(currentTime.getTime() + 5 * 60 * 60 * 1000);
    const repairedRows = await app.db
      .update(subscriptions)
      .set({
        planCode: "free",
        status: "free",
        billingProvider: "internal",
        providerCustomerReferenceCode: null,
        providerSubscriptionReferenceCode: null,
        providerPricingPlanReferenceCode: null,
        taskLimitMonthly: freeDefaults.taskLimitMonthly,
        aiCreditsMonthly: freeDefaults.aiCreditsMonthly,
        currentPeriodStartedAt: currentTime,
        periodEndsAt: nextPeriodEnd,
        cancelAtPeriodEnd: false,
        canceledAt: canceledPaidPeriodEnded ? subscription.canceledAt : null,
        updatedAt: currentTime,
      })
      .where(eq(subscriptions.userId, userId))
      .returning();
    subscription = repairedRows[0] ?? subscription;
    invalidateBrainProfileCache(app, userId);
  }

  const [desktopCountRows, usageSummary, invocationRows, recentCheckouts, recentEvents, recentStoreTransactions, trialQuota] = await Promise.all([
    app.db
      .select({
        count: sql<number>`count(*)`,
      })
      .from(devices)
      .where(and(eq(devices.userId, userId), eq(devices.type, "desktop"), eq(devices.isActive, true))),
    getBillingUsageSummary(app.db, userId),
    app.db
      .select({
        count: sql<number>`count(*)`,
        promptTokens: sql<number>`coalesce(sum(${aiProviderInvocations.promptTokens}), 0)`,
        completionTokens: sql<number>`coalesce(sum(${aiProviderInvocations.completionTokens}), 0)`,
        totalTokens: sql<number>`coalesce(sum(${aiProviderInvocations.totalTokens}), 0)`,
      })
      .from(aiProviderInvocations)
      .where(eq(aiProviderInvocations.userId, userId)),
    app.db
      .select()
      .from(billingCheckoutSessions)
      .where(eq(billingCheckoutSessions.userId, userId))
      .orderBy(desc(billingCheckoutSessions.createdAt))
      .limit(5),
    app.db
      .select()
      .from(billingWebhookEvents)
      .where(eq(billingWebhookEvents.userId, userId))
      .orderBy(desc(billingWebhookEvents.receivedAt))
      .limit(10),
    app.db
      .select()
      .from(billingStoreTransactions)
      .where(eq(billingStoreTransactions.userId, userId))
      .orderBy(desc(billingStoreTransactions.verifiedAt), desc(billingStoreTransactions.createdAt))
      .limit(5),
    getTrialQuotaUsage(app.db, userId),
  ]);

  const activeSubscription = subscription ?? null;
  const plan = getBillingPlan(activeSubscription?.planCode);
  const profileState = buildProfileState(profile, user.email);
  const desktopCount = Number(desktopCountRows[0]?.count ?? 0);
  const accessTruth = resolveUsageAccessTruth(activeSubscription);
  const presentationTruth = resolveUsagePresentationTruth(accessTruth);
  const latestStoreTransaction = recentStoreTransactions[0] ?? null;
  const creditBalance = usageSummary.aiUsage.remaining;
  const creditGrantedThisPeriod = usageSummary.aiUsage.granted;
  const manageSubscriptionHint = buildManageSubscriptionHint(activeSubscription?.billingProvider);
  const subscriptionSource = latestStoreTransaction?.provider ?? activeSubscription?.billingProvider ?? "iyzico";
  const creditStatus = buildCreditStatus({
    balance: creditBalance,
    subscriptionStatus: activeSubscription?.status ?? "free",
    trialActive: accessTruth.trialActive,
  });
  const trialOffer = shapeWelcomeProTrialOffer(activeSubscription);
  const planCode = normalizeBillingPlanCode(activeSubscription?.planCode);
  const billingSource =
    activeSubscription?.billingProvider === "welcome_trial"
      ? "welcome_pro"
      : activeSubscription?.billingProvider === "apple_store"
        ? "apple"
        : "internal";
  const periodStartsAt =
    activeSubscription?.currentPeriodStartedAt ?? usageSummary.periodStartsAt;
  const periodEndsAt =
    activeSubscription?.periodEndsAt ?? usageSummary.periodEndsAt;

  return {
    billingState: {
      version: "2026-06-billing-v2",
      plan: {
        code: planCode,
        status: activeSubscription?.status ?? "free",
        source: billingSource,
        periodStartsAt,
        periodEndsAt,
        cancelAtPeriodEnd: activeSubscription?.cancelAtPeriodEnd ?? false,
        pendingPlanCode: null,
        pendingPlanEffectiveAt: null,
      },
      entitlements: {
        desktopLimit: plan.desktopLimit,
        brainProfile: accessTruth.brainProfile,
        qualityProfile: accessTruth.brainProfile.qualityProfile,
      },
      usage: {
        quotaWindows: buildTrialQuotaWindows(trialQuota),
        budgetUnits: {
          fiveHour: {
            limit: trialQuota.dailyLimit,
            used: trialQuota.dailyUsed,
            remaining: trialQuota.dailyRemaining,
            resetsAt: trialQuota.dailyResetAt,
          },
          weekly: {
            limit: trialQuota.weeklyLimit,
            used: trialQuota.weeklyUsed,
            remaining: trialQuota.weeklyRemaining,
            resetsAt: trialQuota.weeklyResetAt,
          },
        },
        tokens: {
          limit: usageSummary.aiCreditsMonthly,
          used: usageSummary.aiUsage.used,
          reserved: 0,
          remaining: creditBalance,
          resetsAt: periodEndsAt,
        },
        tasks: {
          limit: usageSummary.taskLimitMonthly,
          used: usageSummary.taskUsage.used,
          remaining: usageSummary.taskUsage.remaining,
          resetsAt: periodEndsAt,
        },
      },
      welcomePro: {
        status: trialOffer.status,
        eligible: trialOffer.eligible,
        claimBy: trialOffer.status === "available" ? trialOffer.expiresAt : null,
        claimedAt:
          trialOffer.claimed ? activeSubscription?.currentPeriodStartedAt ?? null : null,
        activeUntil: trialOffer.claimed ? trialOffer.expiresAt : null,
        claimPath: trialOffer.claimPath,
      },
      actions: {
        canClaimWelcomePro: trialOffer.eligible,
        canUpgrade: planCode !== "pro",
        canDowngrade: planCode === "pro" && billingSource === "apple",
        canCancel: billingSource === "apple" && planCode !== "free",
        manageSubscriptionHint,
      },
    },
    subscription: {
      planCode: normalizeBillingPlanCode(activeSubscription?.planCode),
      status: activeSubscription?.status ?? "free",
      brainProfile: accessTruth.brainProfile,
      qualityProfile: accessTruth.brainProfile.qualityProfile,
      billingProvider: activeSubscription?.billingProvider ?? "iyzico",
      providerCustomerReferenceCode: activeSubscription?.providerCustomerReferenceCode ?? null,
      providerSubscriptionReferenceCode: activeSubscription?.providerSubscriptionReferenceCode ?? null,
      providerPricingPlanReferenceCode: activeSubscription?.providerPricingPlanReferenceCode ?? null,
      currentPeriodStartedAt: activeSubscription?.currentPeriodStartedAt ?? usageSummary.periodStartsAt,
      periodEndsAt: activeSubscription?.periodEndsAt ?? usageSummary.periodEndsAt,
      trialEndsAt: activeSubscription?.trialEndsAt ?? null,
      cancelAtPeriodEnd: activeSubscription?.cancelAtPeriodEnd ?? false,
      canceledAt: activeSubscription?.canceledAt ?? null,
      creditBalance,
      tokenBalance: creditBalance,
      creditGrantedThisPeriod,
      tokensGrantedThisPeriod: creditGrantedThisPeriod,
      creditPeriodEndsAt: activeSubscription?.periodEndsAt ?? usageSummary.periodEndsAt,
      tokenPeriodEndsAt: activeSubscription?.periodEndsAt ?? usageSummary.periodEndsAt,
      creditStatus,
      tokenStatus: creditStatus,
      subscriptionSource,
      manageSubscriptionHint,
      trialOffer,
    },
    plan: shapePlanSummary(activeSubscription?.planCode ?? "free"),
    profile: profileState,
    entitlements: {
      desktopLimit: plan.desktopLimit,
      taskLimitMonthly: usageSummary.taskLimitMonthly,
      aiCreditsMonthly: usageSummary.aiCreditsMonthly,
      tokensMonthly: usageSummary.aiCreditsMonthly,
      fiveHourBudgetUnits: trialQuota.dailyLimit,
      dailyBudgetUnits: trialQuota.dailyLimit,
      weeklyBudgetUnits: trialQuota.weeklyLimit,
      documentUploadLimit: trialQuota.documentUploadLimit,
      imageUploadLimit: trialQuota.imageUploadLimit,
      toolUnitsLimit: plan.toolUnitsLimit,
      qualityProfile: accessTruth.brainProfile.qualityProfile,
      byokRequired: plan.byokRequired,
    },
    usage: {
      windowStartedAt: usageSummary.periodStartsAt,
      windowEndsAt: usageSummary.periodEndsAt,
      tasksUsed: usageSummary.taskUsage.used,
      tasksRemaining: usageSummary.taskUsage.remaining,
      aiCreditsUsed: usageSummary.aiUsage.used,
      aiCreditsRemaining: creditBalance,
      tokensUsed: usageSummary.aiUsage.used,
      tokensRemaining: creditBalance,
      creditBalance,
      tokenBalance: creditBalance,
      creditGrantedThisPeriod,
      tokensGrantedThisPeriod: creditGrantedThisPeriod,
      creditPeriodEndsAt: activeSubscription?.periodEndsAt ?? usageSummary.periodEndsAt,
      tokenPeriodEndsAt: activeSubscription?.periodEndsAt ?? usageSummary.periodEndsAt,
      creditStatus,
      tokenStatus: creditStatus,
      subscriptionSource,
      manageSubscriptionHint,
      brainProfile: accessTruth.brainProfile,
      dailyLimit: trialQuota.dailyLimit,
      dailyUsed: trialQuota.dailyUsed,
      dailyRemaining: trialQuota.dailyRemaining,
      dailyResetAt: trialQuota.dailyResetAt,
      dailyProgressPercent: trialQuota.dailyProgressPercent,
      weeklyLimit: trialQuota.weeklyLimit,
      weeklyUsed: trialQuota.weeklyUsed,
      weeklyRemaining: trialQuota.weeklyRemaining,
      weeklyResetAt: trialQuota.weeklyResetAt,
      weeklyProgressPercent: trialQuota.weeklyProgressPercent,
      documentUploadLimit: trialQuota.documentUploadLimit,
      documentUploadCount: trialQuota.documentUploadCount,
      documentUploadRemaining: trialQuota.documentUploadRemaining,
      imageUploadLimit: trialQuota.imageUploadLimit,
      imageUploadCount: trialQuota.imageUploadCount,
      imageUploadRemaining: trialQuota.imageUploadRemaining,
      budgetUnitsTracked: true,
      qualityProfile: accessTruth.brainProfile.qualityProfile,
      quotaWindows: buildTrialQuotaWindows(trialQuota),
      serverBrainAllowed: accessTruth.serverBrainAllowed,
      localByokAllowed: accessTruth.localByokAllowed,
      trialActive: accessTruth.trialActive,
      trialEndsAt: accessTruth.trialEndsAt,
      upgradeRequiredForServerBrain: accessTruth.upgradeRequiredForServerBrain,
      accessMode: presentationTruth.accessMode,
      planLabelSource: presentationTruth.planLabelSource,
      desktopCount,
      aiInvocationCount: Number(invocationRows[0]?.count ?? 0),
      promptTokens: Number(invocationRows[0]?.promptTokens ?? 0),
      completionTokens: Number(invocationRows[0]?.completionTokens ?? 0),
      totalTokens: Number(invocationRows[0]?.totalTokens ?? 0),
      aiCreditsTracked: true,
      tokensTracked: true,
      budgetState: resolveTokenBudgetState({
        remaining: creditBalance,
        granted: creditGrantedThisPeriod,
      }),
      meteringPolicy: {
        version: TOKEN_METERING_VERSION,
        accounting: "weighted_actual_usage",
        unitSize: TOKEN_METERING_UNIT_SIZE,
        pendingUsageIsEstimate: true,
        clientMustNotCalculate: true,
      },
    },
    recentCheckouts: recentCheckouts.map((item) => serializeCheckout(item)),
    latestStoreTransaction: latestStoreTransaction
      ? {
          provider: latestStoreTransaction.provider,
          planCode: normalizeBillingPlanCode(latestStoreTransaction.planCode),
          productId: latestStoreTransaction.productId,
          purchaseToken: latestStoreTransaction.purchaseToken,
          originalTransactionId: latestStoreTransaction.originalTransactionId,
          transactionId: latestStoreTransaction.transactionId,
          orderId: latestStoreTransaction.orderId,
          status: latestStoreTransaction.status,
          environment: latestStoreTransaction.environment,
          verifiedAt: latestStoreTransaction.verifiedAt,
        }
      : null,
    recentBillingEvents: recentEvents.map((item) => ({
      eventType: item.eventType,
      status: item.status,
      receivedAt: item.receivedAt,
    })),
  };
}

export async function assertDesktopPairingAllowed(
  app: FastifyInstance,
  userId: string,
  currentDesktopDeviceId?: string,
): Promise<void> {
  const access = await getUserUsageAccessTruth(app.db, userId);
  const desktopCountRows = await app.db
    .select({
      count: sql<number>`count(*)`,
    })
    .from(devices)
    .where(
      and(
        eq(devices.userId, userId),
        eq(devices.type, "desktop"),
        eq(devices.isActive, true),
      ),
    )
    .limit(1);
  const desktopCount = Math.max(
    0,
    Number(desktopCountRows[0]?.count ?? 0) - (currentDesktopDeviceId ? 1 : 0),
  );

  if (!subscriptionStatusAllowsUsage(access.status)) {
    throw conflict("subscription_inactive");
  }

  if (!canUseDesktopConnections(access.planCode)) {
    throw conflict("desktop_plan_required");
  }

  if (desktopCount >= getBillingPlan(access.planCode).desktopLimit) {
    throw conflict("desktop_limit_reached");
  }
}

export async function assertTaskCreationAllowed(app: FastifyInstance, userId: string): Promise<void> {
  const quota = await getTrialQuotaUsage(app.db, userId);
  assertTrialTaskQuotaAllowedFromUsage(quota);
}

export async function createSubscriptionCheckout(
  app: FastifyInstance,
  userId: string,
  input: {
    planCode: Exclude<BillingPlanCode, "free">;
    successUrl?: string;
    cancelUrl?: string;
    requestId: string;
    idempotencyKey?: string;
  },
) {
  if (!isSellablePlanCode(input.planCode)) {
    throw badRequest("invalid_plan_code");
  }

  const idempotencyFingerprint = input.idempotencyKey ? createCheckoutFingerprint(input) : undefined;
  const existingCheckout = await resolveCheckoutForIdempotentReplay(app.db, {
    userId,
    idempotencyKey: input.idempotencyKey,
    fingerprint: idempotencyFingerprint,
  });

  if (existingCheckout) {
    return serializeCheckout(existingCheckout);
  }

  const [user, subscription, profileState] = await Promise.all([
    getUserRow(app, userId),
    getSubscriptionRow(app, userId),
    getBillingProfileState(app, userId),
  ]);

  if (!user) {
    throw notFound("User not found");
  }

  if (!profileState.isComplete) {
    throw conflict(`billing_profile_incomplete:${profileState.missingFields.join(",")}`);
  }

  const planCode = normalizeBillingPlanCode(input.planCode);
  if (!isSellablePlanCode(planCode)) {
    throw badRequest("invalid_plan_code");
  }
  const currentPlanCode = normalizeBillingPlanCode(subscription?.planCode);

  if (
    subscription?.providerSubscriptionReferenceCode &&
    (subscription.status === "active" || subscription.status === "trialing") &&
    currentPlanCode === planCode
  ) {
    throw conflict("subscription_already_active_for_plan");
  }

  if (
    subscription?.providerSubscriptionReferenceCode &&
    (subscription.status === "active" || subscription.status === "trialing") &&
    currentPlanCode !== planCode
  ) {
    throw conflict("subscription_change_requires_change_plan_route");
  }

  const client = new IyzicoClient(app.config);
  const referenceId = randomUUID();
  const callbackUrl = client.getCallbackUrl(referenceId);
  const launchUrl = client.getLaunchUrl(referenceId);
  let claimedInitializationSlot = false;

  if (input.idempotencyKey && idempotencyFingerprint) {
    try {
      const initializationResult = await app.db.transaction(async (tx): Promise<CheckoutInitializationResult> => {
        const claimedRows = await tx.insert(billingCheckoutSessions).values({
          referenceId,
          userId,
          planCode,
          provider: "iyzico",
          status: "initializing",
          launchUrl,
          callbackUrl,
          successUrl: input.successUrl,
          cancelUrl: input.cancelUrl,
          idempotencyKey: input.idempotencyKey,
          idempotencyFingerprint,
          rawLastPayload: {
            initializationState: "initializing",
          },
        }).returning();

        const claimedCheckout = claimedRows[0];

        if (!claimedCheckout) {
          return {
            failed: true,
            error: conflict("checkout_initialization_claim_failed", {
              referenceId,
            }),
          };
        }

        claimedInitializationSlot = true;

        try {
          const mapping = await ensureIyzicoPlanMapping(app, planCode);
          const checkoutResponse = await client.initializeSubscriptionCheckout({
            conversationId: referenceId,
            callbackUrl,
            pricingPlanReferenceCode: mapping.pricingPlanReferenceCode,
            customer: buildIyzicoCustomer(profileState.profile),
          });

          const checkout = await upsertCheckoutSession(tx, {
            referenceId,
            userId,
            planCode,
            provider: "iyzico",
            status: String(checkoutResponse.status || "pending").trim().toLowerCase() || "pending",
            launchUrl,
            paymentPageUrl: String(checkoutResponse.paymentPageUrl || "").trim() || launchUrl,
            callbackUrl,
            successUrl: input.successUrl,
            cancelUrl: input.cancelUrl,
            providerToken: String(checkoutResponse.token || "").trim() || null || undefined,
            providerPricingPlanReferenceCode: mapping.pricingPlanReferenceCode,
            idempotencyKey: input.idempotencyKey,
            idempotencyFingerprint,
            rawLastPayload: checkoutResponse,
          });

          return { checkout };
        } catch (error) {
          await markCheckoutInitializationFailed(tx, referenceId, error);
          return {
            failed: true,
            error,
          };
        }
      });

      if ("failed" in initializationResult) {
        throw initializationResult.error;
      }

      const checkout = initializationResult.checkout;

      try {
        await createAuditLog(app, {
          userId,
          actorType: "user",
          actorId: userId,
          action: "billing.checkout.create",
          resourceType: "billing_checkout",
          resourceId: referenceId,
          status: "success",
          requestId: input.requestId,
          payload: {
            planCode,
            provider: "iyzico",
            idempotencyKey: input.idempotencyKey ?? null,
          },
        });
      } catch {
        // Audit loss should not turn a successful checkout init into a failed one.
      }

      return serializeCheckout(checkout);
    } catch (error) {
      const code = getDatabaseErrorCode(error);

      if (code === "23505") {
        const racedCheckout = await resolveCheckoutForIdempotentReplay(app.db, {
          userId,
          idempotencyKey: input.idempotencyKey,
          fingerprint: idempotencyFingerprint,
        });

        if (racedCheckout) {
          return serializeCheckout(racedCheckout);
        }
      }

      if (claimedInitializationSlot) {
        await markCheckoutInitializationFailedBestEffort(app.db, referenceId, error);
      }

      throw error;
    }
  }

  let mapping: Awaited<ReturnType<typeof ensureIyzicoPlanMapping>> | undefined;
  let checkoutResponse: Record<string, unknown> | undefined;

  try {
    mapping = await ensureIyzicoPlanMapping(app, planCode);
    checkoutResponse = await client.initializeSubscriptionCheckout({
      conversationId: referenceId,
      callbackUrl,
      pricingPlanReferenceCode: mapping.pricingPlanReferenceCode,
      customer: buildIyzicoCustomer(profileState.profile),
    });
  } catch (error) {
    if (claimedInitializationSlot) {
      await markCheckoutInitializationFailedBestEffort(app.db, referenceId, error);
    }

    throw error;
  }

  let checkout;

  try {
    checkout = await upsertCheckoutSession(app.db, {
      referenceId,
      userId,
      planCode,
      provider: "iyzico",
      status: String(checkoutResponse.status || "pending").trim().toLowerCase() || "pending",
      launchUrl,
      paymentPageUrl: String(checkoutResponse.paymentPageUrl || "").trim() || launchUrl,
      callbackUrl,
      successUrl: input.successUrl,
      cancelUrl: input.cancelUrl,
      providerToken: String(checkoutResponse.token || "").trim() || null || undefined,
      providerPricingPlanReferenceCode: mapping.pricingPlanReferenceCode,
      idempotencyKey: input.idempotencyKey,
      idempotencyFingerprint,
      rawLastPayload: checkoutResponse,
      });
  } catch (error) {
    const code = typeof error === "object" && error && "code" in error ? String(error.code) : "";

    if (code === "23505" && input.idempotencyKey) {
      const racedCheckout = await resolveCheckoutForIdempotentReplay(app.db, {
        userId,
        idempotencyKey: input.idempotencyKey,
        fingerprint: idempotencyFingerprint,
      });

      if (racedCheckout) {
        return serializeCheckout(racedCheckout);
      }
    }

    if (claimedInitializationSlot) {
      await markCheckoutInitializationFailedBestEffort(app.db, referenceId, error);
    }

    throw error;
  }

  try {
    await createAuditLog(app, {
      userId,
      actorType: "user",
      actorId: userId,
      action: "billing.checkout.create",
      resourceType: "billing_checkout",
      resourceId: referenceId,
      status: "success",
      requestId: input.requestId,
      payload: {
        planCode,
        provider: "iyzico",
        idempotencyKey: input.idempotencyKey ?? null,
      },
    });
  } catch {
    // Audit loss should not turn a successful checkout init into a failed one.
  }

  return serializeCheckout(checkout);
}

export async function getBillingCheckout(app: FastifyInstance, referenceId: string, userId: string) {
  const checkout = await loadCheckoutForReference(app, referenceId);

  if (!checkout || checkout.userId !== userId) {
    throw notFound("Checkout not found");
  }

  return serializeCheckout(checkout);
}

export async function getCheckoutLaunchPayload(app: FastifyInstance, referenceId: string) {
  const checkout = await loadCheckoutForReference(app, referenceId);

  if (!checkout) {
    throw notFound("Checkout not found");
  }

  const rawPayload = readObject(checkout.rawLastPayload);

  return {
    checkoutFormContent: String(rawPayload.checkoutFormContent || "").trim(),
    paymentPageUrl: String(checkout.paymentPageUrl || rawPayload.paymentPageUrl || "").trim(),
  };
}

export async function completeSubscriptionCheckout(
  app: FastifyInstance,
  input: {
    token: string;
    referenceId?: string;
  },
) {
  const token = String(input.token || "").trim();

  if (!token) {
    throw badRequest("iyzico_checkout_token_required");
  }

  const client = new IyzicoClient(app.config);
  const checkoutResponse = await client.retrieveSubscriptionCheckout(token, input.referenceId);
  const detail = extractSubscriptionDetail(checkoutResponse);
  const referenceId = input.referenceId || String(checkoutResponse.conversationId || "").trim();

  if (!referenceId) {
    throw conflict("billing_checkout_reference_missing");
  }

  const checkout = await loadCheckoutForReference(app, referenceId);

  if (!checkout) {
    throw notFound("Checkout not found");
  }

  const planCode =
    normalizeBillingPlanCode(
      (await resolvePlanCodeFromPricingReference(app, detail.pricingPlanReferenceCode, "iyzico")) ??
        checkout.planCode,
    );
  const normalizedStatus = client.normalizeSubscriptionStatus(detail.subscriptionStatus);
  const updatedCheckout = await upsertCheckoutSession(app.db, {
    referenceId,
    userId: checkout.userId,
    planCode,
    provider: "iyzico",
    status: normalizedStatus,
    launchUrl: checkout.launchUrl ?? undefined,
    paymentPageUrl: checkout.paymentPageUrl ?? undefined,
    callbackUrl: checkout.callbackUrl ?? undefined,
    successUrl: checkout.successUrl ?? undefined,
    cancelUrl: checkout.cancelUrl ?? undefined,
    providerToken: token,
    providerPaymentId: detail.parentReferenceCode,
    providerSubscriptionReferenceCode: detail.referenceCode,
    providerCustomerReferenceCode: detail.customerReferenceCode,
    providerPricingPlanReferenceCode: detail.pricingPlanReferenceCode,
    rawLastPayload: checkoutResponse,
    completedAt: detail.referenceCode ? now() : null,
  });

  await persistSubscriptionState(app, checkout.userId, {
    planCode,
    status: normalizedStatus,
    providerCustomerReferenceCode: detail.customerReferenceCode || null,
    providerSubscriptionReferenceCode: detail.referenceCode || null,
    providerPricingPlanReferenceCode: detail.pricingPlanReferenceCode || null,
    currentPeriodStartedAt: detail.startDate,
    periodEndsAt: detail.endDate,
    trialEndsAt: detail.trialEndDate,
  });

  await createAuditLog(app, {
    userId: checkout.userId,
    actorType: "system",
    actorId: "iyzico",
    action: "billing.checkout.complete",
    resourceType: "billing_checkout",
    resourceId: referenceId,
    status: "success",
    payload: {
      planCode,
      subscriptionStatus: normalizedStatus,
      providerSubscriptionReferenceCode: detail.referenceCode,
    },
  });

  return {
    checkout: serializeCheckout(updatedCheckout),
    billing: await getBillingSummary(app, checkout.userId),
  };
}

export async function handleIyzicoWebhook(
  app: FastifyInstance,
  payload: Record<string, unknown>,
  headers: Record<string, unknown>,
) {
  const client = new IyzicoClient(app.config);
  const signature = String(headers["x-iyz-signature-v3"] || headers["X-IYZ-SIGNATURE-V3"] || "").trim();
  client.validateWebhookSignatureV3(payload, signature);

  const eventType = String(payload.iyziEventType || payload.eventType || "").trim().toLowerCase();
  const subscriptionReferenceCode = String(payload.subscriptionReferenceCode || "").trim();
  const customerReferenceCode = String(payload.customerReferenceCode || "").trim();
  const orderReferenceCode = String(payload.orderReferenceCode || "").trim();
  const eventKey = `iyzico:${eventType}:${subscriptionReferenceCode || orderReferenceCode}:${String(payload.iyziEventTime || "")}`;

  let checkout = subscriptionReferenceCode ? await loadCheckoutBySubscriptionReference(app, subscriptionReferenceCode) : null;
  let subscription = await loadSubscriptionForProviderRefs(app, {
    providerSubscriptionReferenceCode: subscriptionReferenceCode,
    providerCustomerReferenceCode: customerReferenceCode,
  });

  if (!subscription && checkout) {
    subscription = await getSubscriptionRow(app, checkout.userId);
  }

  let planCode = normalizeBillingPlanCode(subscription?.planCode ?? checkout?.planCode ?? "free");
  let normalizedStatus = client.normalizeSubscriptionStatus(
    eventType.endsWith(".failure") ? "failure" : eventType.endsWith(".success") ? "active" : String(payload.status || ""),
  );
  let currentPeriodStartedAt: Date | null = subscription?.currentPeriodStartedAt ?? null;
  let periodEndsAt: Date | null = subscription?.periodEndsAt ?? null;
  let trialEndsAt: Date | null = subscription?.trialEndsAt ?? null;
  let providerPricingPlanReferenceCode = subscription?.providerPricingPlanReferenceCode ?? checkout?.providerPricingPlanReferenceCode ?? null;

  if (subscriptionReferenceCode) {
    try {
      const detailResponse = await client.getSubscriptionDetail(subscriptionReferenceCode);
      const detail = extractSubscriptionDetail(detailResponse);
      planCode = normalizeBillingPlanCode(
        (await resolvePlanCodeFromPricingReference(app, detail.pricingPlanReferenceCode, "iyzico")) ??
          planCode,
      );
      normalizedStatus = client.normalizeSubscriptionStatus(detail.subscriptionStatus);
      currentPeriodStartedAt = detail.startDate;
      periodEndsAt = detail.endDate;
      trialEndsAt = detail.trialEndDate;
      providerPricingPlanReferenceCode = detail.pricingPlanReferenceCode || providerPricingPlanReferenceCode;
    } catch {
      // Keep webhook processing fail-closed to known event status when detail lookup is unavailable.
    }
  }

  const storedEvent = await insertWebhookEvent(app, {
    eventKey,
    eventType,
    status: normalizedStatus,
    userId: subscription?.userId ?? checkout?.userId ?? null,
    checkoutReferenceId: checkout?.referenceId ?? null,
    providerSubscriptionReferenceCode: subscriptionReferenceCode || null,
    providerCustomerReferenceCode: customerReferenceCode || null,
    payload,
  });

  if (subscription?.userId) {
    await persistSubscriptionState(app, subscription.userId, {
      planCode,
      status: normalizedStatus,
      providerCustomerReferenceCode: customerReferenceCode || subscription.providerCustomerReferenceCode,
      providerSubscriptionReferenceCode: subscriptionReferenceCode || subscription.providerSubscriptionReferenceCode,
      providerPricingPlanReferenceCode,
      currentPeriodStartedAt,
      periodEndsAt,
      trialEndsAt,
    });
  }

  if (checkout) {
    checkout = await upsertCheckoutSession(app.db, {
      referenceId: checkout.referenceId,
      userId: checkout.userId,
      planCode,
      provider: "iyzico",
      status: normalizedStatus,
      launchUrl: checkout.launchUrl ?? undefined,
      paymentPageUrl: checkout.paymentPageUrl ?? undefined,
      callbackUrl: checkout.callbackUrl ?? undefined,
      successUrl: checkout.successUrl ?? undefined,
      cancelUrl: checkout.cancelUrl ?? undefined,
      providerToken: checkout.providerToken ?? undefined,
      providerPaymentId: orderReferenceCode || checkout.providerPaymentId || undefined,
      providerSubscriptionReferenceCode: subscriptionReferenceCode || checkout.providerSubscriptionReferenceCode || undefined,
      providerCustomerReferenceCode: customerReferenceCode || checkout.providerCustomerReferenceCode || undefined,
      providerPricingPlanReferenceCode: providerPricingPlanReferenceCode || checkout.providerPricingPlanReferenceCode || undefined,
      rawLastPayload: payload,
      completedAt: now(),
    });
  }

  if (subscription?.userId) {
    await createAuditLog(app, {
      userId: subscription.userId,
      actorType: "system",
      actorId: "iyzico",
      action: "billing.webhook.process",
      resourceType: "subscription",
      resourceId: subscription.providerSubscriptionReferenceCode ?? null,
      status: "success",
      payload: {
        eventType,
        planCode,
        normalizedStatus,
      },
    });
  }

  return {
    eventType: storedEvent.eventType,
    status: storedEvent.status,
    receivedAt: storedEvent.receivedAt,
    checkoutReferenceId: storedEvent.checkoutReferenceId,
    providerSubscriptionReferenceCode: storedEvent.providerSubscriptionReferenceCode,
  };
}

function decodeBase64JsonObject(value: string): Record<string, unknown> | null {
  const trimmed = value.trim();

  if (!trimmed) {
    return null;
  }

  try {
    const decoded = Buffer.from(trimmed, "base64").toString("utf-8");
    return parseJsonObject(decoded);
  } catch {
    return null;
  }
}

export function normalizeStoreWebhookStatus(
  value: string | number | null | undefined,
): "free" | "trialing" | "active" | "past_due" | "canceled" {
  const normalized = String(value ?? "").trim().toLowerCase();

  if (normalized.includes("cancel") || normalized.includes("refund") || normalized.includes("expired")) {
    return "canceled";
  }

  if (normalized.includes("hold") || normalized.includes("grace") || normalized.includes("pause")) {
    return "past_due";
  }

  if (normalized.includes("trial")) {
    return "trialing";
  }

  return normalized ? "active" : "active";
}

async function syncStoreSubscriptionFromProof(
  app: FastifyInstance,
  input: {
    provider: BillingProvider;
    userId?: string | null;
    planCodeHint?: BillingPlanCode | null;
    providerSubscriptionReferenceCode?: string | null;
    providerCustomerReferenceCode?: string | null;
    providerPricingPlanReferenceCode?: string | null;
    transactionId?: string | null;
    purchaseToken?: string | null;
    orderId?: string | null;
    linkedPurchaseToken?: string | null;
    environment?: string | null;
    eventType?: string | null;
    status: "free" | "trialing" | "active" | "past_due" | "canceled";
    currentPeriodStartedAt?: Date | null;
    periodEndsAt?: Date | null;
    trialEndsAt?: Date | null;
    cancelAtPeriodEnd?: boolean;
    appAccountToken?: string | null;
    payload: Record<string, unknown>;
  },
) {
  const subscription = await loadSubscriptionForProviderRefs(app, {
    providerSubscriptionReferenceCode: input.providerSubscriptionReferenceCode,
    providerCustomerReferenceCode: input.providerCustomerReferenceCode,
  });

  if (!subscription?.userId) {
    return null;
  }

  const resolvedPlanCode = normalizeBillingPlanCode(
    (input.planCodeHint ? input.planCodeHint : null) ??
    (await resolvePlanCodeFromProviderReference(app, {
      provider: input.provider,
      productReferenceCode: input.providerPricingPlanReferenceCode,
      pricingPlanReferenceCode: input.providerPricingPlanReferenceCode,
    })) ??
    getBillingPlan(subscription.planCode).code,
  );

  await persistSubscriptionState(app, subscription.userId, {
    planCode: resolvedPlanCode,
    status: input.status,
    billingProvider: input.provider,
    providerCustomerReferenceCode: input.providerCustomerReferenceCode || subscription.providerCustomerReferenceCode,
    providerSubscriptionReferenceCode:
      input.providerSubscriptionReferenceCode || subscription.providerSubscriptionReferenceCode,
    providerPricingPlanReferenceCode:
      input.providerPricingPlanReferenceCode || subscription.providerPricingPlanReferenceCode,
    currentPeriodStartedAt: input.currentPeriodStartedAt ?? subscription.currentPeriodStartedAt,
    periodEndsAt: input.periodEndsAt ?? subscription.periodEndsAt,
    trialEndsAt: input.trialEndsAt ?? subscription.trialEndsAt,
    cancelAtPeriodEnd: input.cancelAtPeriodEnd,
  });

  const storeTransaction = await upsertStoreTransaction(app, {
    userId: subscription.userId,
    provider: input.provider,
    planCode: resolvedPlanCode,
    productId: input.providerPricingPlanReferenceCode ?? null,
    purchaseToken: input.purchaseToken ?? input.providerSubscriptionReferenceCode ?? null,
    originalTransactionId: input.providerCustomerReferenceCode ?? input.providerSubscriptionReferenceCode ?? null,
    transactionId: input.transactionId ?? null,
    orderId: input.orderId ?? null,
    linkedPurchaseToken: input.linkedPurchaseToken ?? null,
    environment: input.environment ?? null,
    appAccountToken: input.appAccountToken ?? null,
    status: input.status,
    payload: input.payload,
    verifiedAt: now(),
  });

  await applyStoreEntitlementEvent(app, {
    userId: subscription.userId,
    sourceProvider: input.provider,
    planCode: resolvedPlanCode,
    eventType: input.eventType?.trim() || "webhook_sync",
    status: input.status,
    sourceReferenceCode: input.providerSubscriptionReferenceCode ?? input.providerCustomerReferenceCode ?? null,
    storeTransactionId: storeTransaction.id,
    currentPeriodStartedAt: input.currentPeriodStartedAt ?? subscription.currentPeriodStartedAt,
    periodEndsAt: input.periodEndsAt ?? subscription.periodEndsAt,
    payload: input.payload,
  });

  return subscription.userId;
}

export async function handleAppleStoreWebhook(app: FastifyInstance, payload: Record<string, unknown>) {
  const signedPayload = readReceiptText(payload.signedPayload);
  if (!signedPayload) {
    throw badRequest("apple_signed_notification_missing");
  }
  const verified = await verifyAppleNotification(app.config, signedPayload);
  const notification = verified.notification;
  const transactionInfo = verified.transaction;
  const renewalInfo = verified.renewalInfo;
  const notificationType = String(notification.notificationType || "").trim().toUpperCase();
  const subtype = String(notification.subtype || "").trim().toUpperCase();
  const providerSubscriptionReferenceCode =
    readReceiptText(transactionInfo?.originalTransactionId);
  const providerCustomerReferenceCode = providerSubscriptionReferenceCode;
  const providerPricingPlanReferenceCode =
    readReceiptText(transactionInfo?.productId) || null;
  const status =
    notificationType === "REFUND" ||
    notificationType === "REVOKE" ||
    notificationType === "EXPIRED"
      ? "canceled"
      : notificationType === "DID_FAIL_TO_RENEW" && subtype !== "GRACE_PERIOD"
        ? "past_due"
        : "active";
  const eventKey = buildStoreEventKey(
    "apple",
    readReceiptText(notification.notificationUUID) ||
      providerSubscriptionReferenceCode ||
      readReceiptText(transactionInfo?.transactionId) ||
      randomUUID(),
  );

  const storedEvent = await insertWebhookEvent(app, {
    eventKey,
    provider: "apple_store",
    eventType: notificationType || "notification",
    status,
    providerSubscriptionReferenceCode: providerSubscriptionReferenceCode || null,
    providerCustomerReferenceCode: providerCustomerReferenceCode || null,
    payload: {
      notificationType,
      subtype: subtype || null,
      notificationUUID: notification.notificationUUID ?? null,
      environment: verified.environment,
      transactionInfo,
      renewalInfo,
      certificateVerified: true,
    },
  });

  if (providerSubscriptionReferenceCode && transactionInfo) {
    await syncStoreSubscriptionFromProof(app, {
      provider: "apple_store",
      providerSubscriptionReferenceCode,
      providerCustomerReferenceCode,
      providerPricingPlanReferenceCode,
      transactionId: readReceiptText(transactionInfo.transactionId) || null,
      environment: readReceiptText(verified.environment),
      eventType: notificationType || "notification",
      status,
      currentPeriodStartedAt: parseEpochMs(transactionInfo.purchaseDate),
      periodEndsAt: parseEpochMs(transactionInfo.expiresDate),
      cancelAtPeriodEnd:
        notificationType === "DID_CHANGE_RENEWAL_STATUS" &&
        Number(renewalInfo?.autoRenewStatus) === 0,
      appAccountToken: readReceiptText(transactionInfo.appAccountToken) || null,
      planCodeHint: providerPricingPlanReferenceCode
        ? resolveApplePlanCode(app, providerPricingPlanReferenceCode)
        : undefined,
      payload: {
        notificationType,
        subtype: subtype || null,
        notificationUUID: notification.notificationUUID ?? null,
        transactionInfo,
        renewalInfo,
        certificateVerified: true,
      },
    });
  }

  return {
    eventType: storedEvent.eventType,
    status: storedEvent.status,
    receivedAt: storedEvent.receivedAt,
  };
}

export async function handleGooglePlayWebhook(app: FastifyInstance, payload: Record<string, unknown>) {
  const message = payload.message && typeof payload.message === "object" && !Array.isArray(payload.message)
    ? (payload.message as Record<string, unknown>)
    : payload;
  const data = typeof message.data === "string" ? decodeBase64JsonObject(message.data) ?? {} : message;
  const notification = data.subscriptionNotification && typeof data.subscriptionNotification === "object"
    ? (data.subscriptionNotification as Record<string, unknown>)
    : data;
  const purchaseToken =
    readReceiptText(notification.purchaseToken) ||
    readReceiptText(data.purchaseToken) ||
    readReceiptText(message.purchaseToken);
  const subscriptionId =
    readReceiptText(notification.subscriptionId) ||
    readReceiptText(data.subscriptionId) ||
    readReceiptText(message.subscriptionId);
  const eventType = String(notification.notificationType || data.notificationType || message.notificationType || "notification").trim();
  const eventKey = buildStoreEventKey(
    "google",
    purchaseToken || readReceiptText(message.messageId) || randomUUID(),
  );
  const status = normalizeStoreWebhookStatus(
    `${eventType}:${String(notification.subscriptionState || data.subscriptionState || "")}`,
  );

  const storedEvent = await insertWebhookEvent(app, {
    eventKey,
    provider: "google_play",
    eventType,
    status,
    providerSubscriptionReferenceCode: purchaseToken || null,
    providerCustomerReferenceCode: subscriptionId || null,
    payload: {
      message,
      data,
      subscriptionNotification: notification,
    },
  });

  await syncStoreSubscriptionFromProof(app, {
    provider: "google_play",
    providerSubscriptionReferenceCode: purchaseToken || null,
    providerCustomerReferenceCode: subscriptionId || null,
    providerPricingPlanReferenceCode: subscriptionId || null,
    purchaseToken: purchaseToken || null,
    linkedPurchaseToken: readReceiptText(data.linkedPurchaseToken) || null,
    eventType,
    status,
    payload,
  });

  return {
    eventType: storedEvent.eventType,
    status: storedEvent.status,
    receivedAt: storedEvent.receivedAt,
  };
}

export async function updateSubscriptionPlan(
  app: FastifyInstance,
  userId: string,
  input: {
    planCode: Exclude<BillingPlanCode, "free">;
    effectiveAt: "now" | "next_period";
  },
) {
  const subscription = await getSubscriptionRow(app, userId);

  if (!subscription?.providerSubscriptionReferenceCode) {
    throw conflict("subscription_upgrade_requires_active_provider_subscription");
  }

  if (subscription.billingProvider === "apple_store") {
    throw conflict("apple_subscription_plan_change_requires_app_store");
  }

  const planCode = normalizeBillingPlanCode(input.planCode);
  if (!isSellablePlanCode(planCode)) {
    throw badRequest("invalid_plan_code");
  }
  const currentPlanCode = normalizeBillingPlanCode(subscription.planCode);

  if (currentPlanCode === planCode) {
    throw conflict("subscription_already_on_target_plan");
  }

  const mapping = await ensureIyzicoPlanMapping(app, planCode);
  const client = new IyzicoClient(app.config);
  const upgradeResponse = await client.upgradeSubscription({
    subscriptionReferenceCode: subscription.providerSubscriptionReferenceCode,
    newPricingPlanReferenceCode: mapping.pricingPlanReferenceCode,
    upgradePeriod: input.effectiveAt === "now" ? "NOW" : "NEXT_PERIOD",
  });
  const detail = extractSubscriptionDetail(upgradeResponse);

  await persistSubscriptionState(app, userId, {
    planCode,
    status: client.normalizeSubscriptionStatus(detail.subscriptionStatus || subscription.status),
    providerCustomerReferenceCode: detail.customerReferenceCode || subscription.providerCustomerReferenceCode,
    providerSubscriptionReferenceCode: subscription.providerSubscriptionReferenceCode,
    providerPricingPlanReferenceCode: detail.pricingPlanReferenceCode || mapping.pricingPlanReferenceCode,
    currentPeriodStartedAt: detail.startDate ?? subscription.currentPeriodStartedAt,
    periodEndsAt: detail.endDate ?? subscription.periodEndsAt,
    trialEndsAt: detail.trialEndDate ?? subscription.trialEndsAt,
  });

  await createAuditLog(app, {
    userId,
    actorType: "user",
    actorId: userId,
    action: "billing.subscription.change_plan",
    resourceType: "subscription",
    resourceId: subscription.providerSubscriptionReferenceCode,
    status: "success",
    payload: {
      fromPlanCode: subscription.planCode,
      toPlanCode: planCode,
      effectiveAt: input.effectiveAt,
    },
  });

  return getBillingSummary(app, userId);
}

export async function cancelCurrentSubscription(app: FastifyInstance, userId: string) {
  const subscription = await getSubscriptionRow(app, userId);

  if (!subscription?.providerSubscriptionReferenceCode) {
    throw conflict("subscription_cancel_requires_active_provider_subscription");
  }

  if (subscription.billingProvider === "apple_store") {
    throw conflict("apple_subscription_cancel_requires_app_store");
  }

  const client = new IyzicoClient(app.config);
  await client.cancelSubscription(subscription.providerSubscriptionReferenceCode);

  let detailStatus: "free" | "trialing" | "active" | "past_due" | "canceled" = "canceled";
  let currentPeriodStartedAt = subscription.currentPeriodStartedAt;
  let periodEndsAt = subscription.periodEndsAt;
  let trialEndsAt = subscription.trialEndsAt;

  try {
    const detailResponse = await client.getSubscriptionDetail(subscription.providerSubscriptionReferenceCode);
    const detail = extractSubscriptionDetail(detailResponse);
    detailStatus = client.normalizeSubscriptionStatus(detail.subscriptionStatus);
    currentPeriodStartedAt = detail.startDate ?? currentPeriodStartedAt;
    periodEndsAt = detail.endDate ?? periodEndsAt;
    trialEndsAt = detail.trialEndDate ?? trialEndsAt;
  } catch {
    // Cancellation should still complete locally when provider detail lookup is temporarily unavailable.
  }

  await persistSubscriptionState(app, userId, {
    planCode: normalizeBillingPlanCode(subscription.planCode),
    status: detailStatus,
    providerCustomerReferenceCode: subscription.providerCustomerReferenceCode,
    providerSubscriptionReferenceCode: subscription.providerSubscriptionReferenceCode,
    providerPricingPlanReferenceCode: subscription.providerPricingPlanReferenceCode,
    currentPeriodStartedAt,
    periodEndsAt,
    trialEndsAt,
  });

  await createAuditLog(app, {
    userId,
    actorType: "user",
    actorId: userId,
    action: "billing.subscription.cancel",
    resourceType: "subscription",
    resourceId: subscription.providerSubscriptionReferenceCode,
    status: "success",
    payload: {
      planCode: normalizeBillingPlanCode(subscription.planCode),
    },
  });

  return getBillingSummary(app, userId);
}
