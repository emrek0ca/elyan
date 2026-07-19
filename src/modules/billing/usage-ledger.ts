import { and, eq, gte, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { subscriptions, usageRecords } from "../../db/schema.js";
import { conflict } from "../../lib/errors.js";
import { getCreditWindowSummary } from "./credit-ledger.js";
import {
  getBillingPlan,
  normalizeBillingPlanCode,
  type BillingPlanCode,
  type QualityProfile,
} from "./catalog.js";

export const BILLING_USAGE_METRICS = {
  trialTask: "trial_task",
  subscriptionTask: "subscription_task",
  subscriptionAiCredit: "subscription_ai_credit",
  subscriptionImageGeneration: "subscription_image_generation",
} as const;

export function buildScopedAiCreditUsageMetric(
  phase?: string | null,
): string {
  const normalizedPhase = String(phase ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
  return normalizedPhase
    ? `${BILLING_USAGE_METRICS.subscriptionAiCredit}:${normalizedPhase}`
    : BILLING_USAGE_METRICS.subscriptionAiCredit;
}

type SubscriptionRow = typeof subscriptions.$inferSelect;

type UsageWindow = {
  startAt: Date;
  endAt: Date;
};

type BillingReadDb = Pick<FastifyInstance["db"], "select">;
type BillingWriteDb = Pick<FastifyInstance["db"], "insert">;

export type BillingUsageSummary = {
  planCode: BillingPlanCode;
  subscriptionStatus: string;
  taskLimitMonthly: number;
  aiCreditsMonthly: number;
  imageGenerationLimitDaily: number;
  taskUsage: {
    used: number;
    remaining: number;
  };
  aiUsage: {
    used: number;
    remaining: number;
    granted: number;
  };
  imageGenerationUsage: {
    limit: number;
    used: number;
    remaining: number;
  };
  periodStartsAt: Date;
  periodEndsAt: Date;
  imageGenerationWindowStartsAt: Date;
  imageGenerationWindowEndsAt: Date;
};

function now(): Date {
  return new Date();
}

function startOfCurrentUtcMonth(): Date {
  const current = now();
  return new Date(Date.UTC(current.getUTCFullYear(), current.getUTCMonth(), 1, 0, 0, 0, 0));
}

function addUtcMonths(startAt: Date, months: number): Date {
  return new Date(Date.UTC(startAt.getUTCFullYear(), startAt.getUTCMonth() + months, 1, 0, 0, 0, 0));
}

function startOfCurrentUtcDay(): Date {
  const current = now();
  return new Date(Date.UTC(current.getUTCFullYear(), current.getUTCMonth(), current.getUTCDate(), 0, 0, 0, 0));
}

function addUtcDays(startAt: Date, days: number): Date {
  return new Date(startAt.getTime() + days * 24 * 60 * 60 * 1000);
}

async function getSubscriptionRow(db: BillingReadDb, userId: string): Promise<SubscriptionRow | null> {
  const rows = await db.select().from(subscriptions).where(eq(subscriptions.userId, userId)).limit(1);
  return rows[0] ?? null;
}

function getUsageWindow(subscription: SubscriptionRow | null): UsageWindow {
  const startAt = subscription?.currentPeriodStartedAt ?? startOfCurrentUtcMonth();
  const endAt = subscription?.periodEndsAt ?? addUtcMonths(startAt, 1);

  return {
    startAt,
    endAt,
  };
}

function resolveMonthlyAllowance(input: {
  storedValue?: number | null;
  planDefault: number;
  planCode: BillingPlanCode;
}): number {
  const storedValue = Number(input.storedValue ?? NaN);
  if (Number.isFinite(storedValue) && storedValue > 0) {
    return Math.trunc(storedValue);
  }

  // Older free rows were seeded with 0 credits while the plan was BYOK-only.
  // Once Free became a bounded server-brain plan, those rows should inherit
  // the catalog allowance instead of staying permanently locked out.
  if (input.planCode === "free") {
    return input.planDefault;
  }

  return Number.isFinite(storedValue) ? Math.max(0, Math.trunc(storedValue)) : input.planDefault;
}

async function countUsageMetricInWindow(
  db: BillingReadDb,
  input: {
    userId: string;
    metric: string;
    startAt: Date;
  },
): Promise<number> {
  const metricCondition =
    input.metric === BILLING_USAGE_METRICS.subscriptionAiCredit
      ? sql<boolean>`(${usageRecords.metric} = ${input.metric} or ${usageRecords.metric} like ${`${input.metric}:%`})`
      : eq(usageRecords.metric, input.metric);
  const rows = await db
    .select({
      used: sql<number>`coalesce(sum(${usageRecords.quantity}), 0)`,
    })
    .from(usageRecords)
    .where(
      and(
        eq(usageRecords.userId, input.userId),
        metricCondition,
        gte(usageRecords.createdAt, input.startAt),
      ),
    );

  return Number(rows[0]?.used ?? 0);
}

export async function getBillingUsageSummary(db: BillingReadDb, userId: string): Promise<BillingUsageSummary> {
  const subscription = await getSubscriptionRow(db, userId);
  const plan = getBillingPlan(subscription?.planCode);
  const planCode = normalizeBillingPlanCode(subscription?.planCode ?? plan.code);
  const window = getUsageWindow(subscription);
  const imageGenerationWindow: UsageWindow = {
    startAt: startOfCurrentUtcDay(),
    endAt: addUtcDays(startOfCurrentUtcDay(), 1),
  };
  const [taskUsageUsed, aiUsageUsed, imageGenerationUsed, creditSummary] = await Promise.all([
    countUsageMetricInWindow(db, {
      userId,
      metric: BILLING_USAGE_METRICS.subscriptionTask,
      startAt: window.startAt,
    }),
    countUsageMetricInWindow(db, {
      userId,
      metric: BILLING_USAGE_METRICS.subscriptionAiCredit,
      startAt: window.startAt,
    }),
    countUsageMetricInWindow(db, {
      userId,
      metric: BILLING_USAGE_METRICS.subscriptionImageGeneration,
      startAt: imageGenerationWindow.startAt,
    }),
    getCreditWindowSummary(db, {
      userId,
      startAt: window.startAt,
      endAt: window.endAt,
    }),
  ]);

  const taskLimitMonthly = resolveMonthlyAllowance({
    storedValue: subscription?.taskLimitMonthly,
    planDefault: plan.taskLimitMonthly,
    planCode,
  });
  const aiCreditsMonthly = resolveMonthlyAllowance({
    storedValue: subscription?.aiCreditsMonthly,
    planDefault: plan.aiCreditsMonthly,
    planCode,
  });
  const creditGranted = creditSummary.granted > 0 ? creditSummary.granted : aiCreditsMonthly;
  const creditUsed = creditSummary.granted > 0 ? creditSummary.used : aiUsageUsed;
  const creditRemaining =
    creditSummary.granted > 0
      ? creditSummary.balance
      : Math.max(0, aiCreditsMonthly - aiUsageUsed);
  const imageGenerationLimitDaily = plan.imageGenerationLimitDaily;

  return {
    planCode,
    subscriptionStatus: subscription?.status ?? "free",
    taskLimitMonthly,
    aiCreditsMonthly,
    imageGenerationLimitDaily,
    taskUsage: {
      used: taskUsageUsed,
      remaining: Math.max(0, taskLimitMonthly - taskUsageUsed),
    },
    aiUsage: {
      used: creditUsed,
      remaining: creditRemaining,
      granted: creditGranted,
    },
    imageGenerationUsage: {
      limit: imageGenerationLimitDaily,
      used: imageGenerationUsed,
      remaining: Math.max(0, imageGenerationLimitDaily - imageGenerationUsed),
    },
    periodStartsAt: window.startAt,
    periodEndsAt: window.endAt,
    imageGenerationWindowStartsAt: imageGenerationWindow.startAt,
    imageGenerationWindowEndsAt: imageGenerationWindow.endAt,
  };
}

function assertSubscriptionActive(summary: BillingUsageSummary): void {
  const canceledPeriodStillActive =
    summary.subscriptionStatus === "canceled" &&
    summary.periodEndsAt.getTime() > Date.now();
  if (
    summary.subscriptionStatus === "past_due" ||
    (summary.subscriptionStatus === "canceled" && !canceledPeriodStillActive)
  ) {
    throw conflict("subscription_inactive");
  }
}

export async function assertMonthlyTaskUsageAllowed(db: BillingReadDb, userId: string): Promise<void> {
  const summary = await getBillingUsageSummary(db, userId);
  assertSubscriptionActive(summary);
}

export async function assertMonthlyAiUsageAllowed(
  db: BillingReadDb,
  userId: string,
  estimatedCredits: number,
): Promise<void> {
  const summary = await getBillingUsageSummary(db, userId);
  assertSubscriptionActive(summary);
  void estimatedCredits;
}

export async function assertMonthlyImageGenerationAllowed(
  db: BillingReadDb,
  userId: string,
): Promise<BillingUsageSummary> {
  const summary = await getBillingUsageSummary(db, userId);
  assertSubscriptionActive(summary);
  if (summary.imageGenerationUsage.remaining <= 0) {
    throw conflict("image_generation_limit_reached", {
      planCode: summary.planCode,
      limit: summary.imageGenerationUsage.limit,
      used: summary.imageGenerationUsage.used,
      retryAt: summary.imageGenerationWindowEndsAt,
    });
  }
  return summary;
}

export async function recordImageGenerationUsage(
  db: BillingWriteDb,
  input: {
    userId: string;
    taskId?: string | null;
    planCode?: BillingPlanCode | null;
    limit?: number | null;
    usedBefore?: number | null;
  },
): Promise<void> {
  await recordUsageLedgerEntry(db, {
    userId: input.userId,
    taskId: input.taskId ?? null,
    metric: BILLING_USAGE_METRICS.subscriptionImageGeneration,
    quantity: 1,
    imageUnits: 1,
    planSnapshot: {
      planCode: input.planCode ?? null,
      limit: input.limit ?? null,
      usedBefore: input.usedBefore ?? null,
    },
  });
}

export async function recordUsageLedgerEntry(
  db: BillingWriteDb,
  input: {
    userId: string;
    identityId?: string | null;
    metric: string;
    taskId?: string | null;
    quantity?: number;
    budgetUnits?: number;
    documentUnits?: number;
    imageUnits?: number;
    toolUnits?: number;
    qualityProfile?: QualityProfile | null;
    planSnapshot?: Record<string, unknown> | null;
  },
) {
  const rows = await db
    .insert(usageRecords)
    .values({
      userId: input.userId,
      identityId: input.identityId ?? null,
      taskId: input.taskId ?? null,
      metric: input.metric,
      quantity: Math.max(1, Math.trunc(input.quantity ?? 1)),
      budgetUnits: Math.max(0, Math.trunc(input.budgetUnits ?? 0)),
      documentUnits: Math.max(0, Math.trunc(input.documentUnits ?? 0)),
      imageUnits: Math.max(0, Math.trunc(input.imageUnits ?? 0)),
      toolUnits: Math.max(0, Math.trunc(input.toolUnits ?? 0)),
      qualityProfile: input.qualityProfile ?? null,
      planSnapshot:
        input.planSnapshot && typeof input.planSnapshot === "object" && !Array.isArray(input.planSnapshot)
          ? input.planSnapshot
          : {},
    })
    .onConflictDoNothing({
      target: [usageRecords.taskId, usageRecords.metric],
    })
    .returning({ id: usageRecords.id });
  return rows[0] ?? null;
}
