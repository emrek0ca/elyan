import { and, eq, gte, isNull, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  quotaState,
  subscriptions,
  usageRecords,
  usageWindows,
  userIdentityHistory,
  users,
} from "../../db/schema.js";
import { AppError, unauthorized } from "../../lib/errors.js";
import {
  getBillingPlan,
  normalizeBillingPlanCode,
  type BillingPlanCode,
  type QualityProfile,
} from "../billing/catalog.js";
import { BILLING_USAGE_METRICS, recordUsageLedgerEntry } from "../billing/usage-ledger.js";

const FIVE_HOUR_WINDOW_MS = 5 * 60 * 60 * 1000;
const WEEKLY_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
export const TRIAL_FIVE_HOUR_LIMIT = getBillingPlan("free").fiveHourBudgetUnits;
export const TRIAL_DAILY_LIMIT = TRIAL_FIVE_HOUR_LIMIT;
export const TRIAL_WEEKLY_LIMIT = getBillingPlan("free").weeklyBudgetUnits;

export const TRIAL_QUOTA_SAFE_ERROR_CODES = [
  "five_hour_quota_reached",
  "daily_quota_reached",
  "weekly_quota_reached",
  "document_quota_reached",
  "image_quota_reached",
  "server_brain_unavailable",
] as const;

export type TrialQuotaPolicy = {
  mode: "identity_window";
  source: "usage_records+quota_state";
  commitPoint: "task.create+brain.inference";
  consumptionMetric: "budget_units";
  fiveHourWindowHours: number;
  dailyWindowHours: number;
  weeklyWindowHours: number;
  idempotency: {
    scope: "identity";
    keyStrategy: "taskId+metric";
    singleWritePerTask: true;
  };
  appliesTo: Array<"chat" | "task" | "document_upload" | "image_upload">;
  safeErrorCodes: readonly (typeof TRIAL_QUOTA_SAFE_ERROR_CODES)[number][];
  surfaces: {
    authMe: "/v1/auth/me";
    mobileBootstrap: "/v1/mobile/bootstrap";
    brainProfile: "/v1/brain/profile";
  };
};

export type TrialQuotaUsage = {
  identityId: string;
  planCode: BillingPlanCode;
  qualityProfile: QualityProfile;
  dailyLimit: number;
  dailyUsed: number;
  dailyRemaining: number;
  dailyResetAt: Date;
  dailyProgressPercent: number;
  weeklyLimit: number;
  weeklyUsed: number;
  weeklyRemaining: number;
  weeklyResetAt: Date;
  weeklyProgressPercent: number;
  documentUploadLimit: number;
  documentUploadCount: number;
  documentUploadRemaining: number;
  imageUploadLimit: number;
  imageUploadCount: number;
  imageUploadRemaining: number;
};

export type QuotaWindowTruth = {
  type: "five_hour" | "weekly";
  title: string;
  windowHours: number;
  limit: number;
  used: number;
  remaining: number;
  remainingFraction: number | null;
  remainingPercent: number | null;
  resetAt: Date;
};

type QuotaWindowCount = {
  usedUnits: number;
  documentUnits: number;
  imageUnits: number;
  oldestCreatedAt: Date | null;
};

type QuotaIdentityRow = {
  userId: string;
  email: string;
  identityId: string | null;
  deletedAt: Date | null;
  planCode: string | null;
};

export type QuotaDb = Pick<FastifyInstance["db"], "select" | "insert" | "update">;

function now(): Date {
  return new Date();
}

function clampPercent(value: number): number {
  if (!Number.isFinite(value) || value < 0) {
    return 0;
  }

  if (value > 100) {
    return 100;
  }

  return Math.round(value);
}

function asDateOrNull(value: unknown): Date | null {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value;
  }

  if (typeof value === "string" && value.trim()) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  return null;
}

function buildResetAt(windowStart: Date | null, windowSizeMs: number): Date {
  if (!windowStart) {
    return new Date(now().getTime() + windowSizeMs);
  }

  return new Date(windowStart.getTime() + windowSizeMs);
}

function buildRemainingPercent(used: number, limit: number): number {
  if (limit <= 0) {
    return 0;
  }

  return clampPercent(((limit - used) / limit) * 100);
}

function normalizeCount(value: unknown): number {
  return Math.max(0, Math.trunc(Number.isFinite(Number(value)) ? Number(value) : 0));
}

function readQualityProfileForPlan(planCode: BillingPlanCode): QualityProfile {
  return getBillingPlan(planCode).brainProfile.qualityProfile;
}

export function normalizeIdentityEmail(email: string): string {
  return email.trim().toLowerCase();
}

async function getUserIdentityRow(db: QuotaDb, userId: string): Promise<QuotaIdentityRow | null> {
  const rows = await db
    .select({
      userId: users.id,
      email: users.email,
      identityId: users.identityId,
      deletedAt: users.deletedAt,
      planCode: subscriptions.planCode,
    })
    .from(users)
    .leftJoin(subscriptions, eq(subscriptions.userId, users.id))
    .where(eq(users.id, userId))
    .limit(1);

  return rows[0] ?? null;
}

export async function findUserIdentityByEmail(
  db: QuotaDb,
  email: string,
): Promise<typeof userIdentityHistory.$inferSelect | null> {
  const normalizedEmail = normalizeIdentityEmail(email);
  const rows = await db
    .select()
    .from(userIdentityHistory)
    .where(eq(userIdentityHistory.normalizedEmail, normalizedEmail))
    .limit(1);

  return rows[0] ?? null;
}

export async function ensureUserIdentity(
  db: QuotaDb,
  input: {
    userId: string;
    email: string;
  },
): Promise<typeof userIdentityHistory.$inferSelect> {
  const normalizedEmail = normalizeIdentityEmail(input.email);
  const user = await getUserIdentityRow(db, input.userId);

  if (!user) {
    throw unauthorized("Bilgileri kontrol et.");
  }

  const existingIdentityRows = await db
    .select()
    .from(userIdentityHistory)
    .where(eq(userIdentityHistory.normalizedEmail, normalizedEmail))
    .limit(1);

  let identity = existingIdentityRows[0] ?? null;

  if (!identity) {
    const insertedRows = await db
      .insert(userIdentityHistory)
      .values({
        normalizedEmail,
        firstUserId: input.userId,
        latestUserId: input.userId,
      })
      .returning();
    identity = insertedRows[0] ?? null;
  } else if (identity.latestUserId !== input.userId) {
    const updatedRows = await db
      .update(userIdentityHistory)
      .set({
        latestUserId: input.userId,
        updatedAt: new Date(),
      })
      .where(eq(userIdentityHistory.id, identity.id))
      .returning();
    identity = updatedRows[0] ?? identity;
  }

  if (!identity) {
    throw new AppError(500, "identity_create_failed", "Kimlik durumu hazırlanamadı.");
  }

  if (user.identityId !== identity.id) {
    await db
      .update(users)
      .set({
        identityId: identity.id,
        updatedAt: new Date(),
      })
      .where(eq(users.id, input.userId));
  }

  return identity;
}

async function countUsageInWindow(
  db: QuotaDb,
  input: {
    identityId: string;
    startAt: Date;
  },
): Promise<QuotaWindowCount> {
  const rows = await db
    .select({
      usedUnits: sql<number>`coalesce(sum(case
        when ${usageRecords.budgetUnits} > 0 then ${usageRecords.budgetUnits}
        when ${usageRecords.metric} in (${BILLING_USAGE_METRICS.subscriptionAiCredit}, ${BILLING_USAGE_METRICS.trialTask}) then ${usageRecords.quantity}
        else 0
      end), 0)`,
      documentUnits: sql<number>`coalesce(sum(${usageRecords.documentUnits}), 0)`,
      imageUnits: sql<number>`coalesce(sum(${usageRecords.imageUnits}), 0)`,
      oldestCreatedAt: sql<Date | null>`min(${usageRecords.createdAt})`,
    })
    .from(usageRecords)
    .where(and(eq(usageRecords.identityId, input.identityId), gte(usageRecords.createdAt, input.startAt)));

  const row = rows[0];
  return {
    usedUnits: normalizeCount(row?.usedUnits),
    documentUnits: normalizeCount(row?.documentUnits),
    imageUnits: normalizeCount(row?.imageUnits),
    oldestCreatedAt: asDateOrNull(row?.oldestCreatedAt),
  };
}

async function syncQuotaWindowMaterialization(
  db: QuotaDb,
  input: {
    identityId: string;
    type: "daily" | "weekly";
    startedAt: Date;
    endsAt: Date;
    usedUnits: number;
    documentUploadCount: number;
    imageUploadCount: number;
  },
) {
  await db
    .insert(usageWindows)
    .values({
      identityId: input.identityId,
      windowType: input.type,
      windowStartedAt: input.startedAt,
      windowEndsAt: input.endsAt,
      usedUnits: input.usedUnits,
      documentUploadCount: input.documentUploadCount,
      imageUploadCount: input.imageUploadCount,
    })
    .onConflictDoUpdate({
      target: [usageWindows.identityId, usageWindows.windowType],
      set: {
        windowStartedAt: input.startedAt,
        windowEndsAt: input.endsAt,
        usedUnits: input.usedUnits,
        documentUploadCount: input.documentUploadCount,
        imageUploadCount: input.imageUploadCount,
        updatedAt: new Date(),
      },
    });
}

async function syncQuotaStateMaterialization(
  db: QuotaDb,
  input: {
    identityId: string;
    dailyUsedUnits: number;
    weeklyUsedUnits: number;
    dailyResetAt: Date;
    weeklyResetAt: Date;
    documentUploadCount: number;
    imageUploadCount: number;
  },
) {
  await db
    .insert(quotaState)
    .values({
      identityId: input.identityId,
      dailyUsedUnits: input.dailyUsedUnits,
      weeklyUsedUnits: input.weeklyUsedUnits,
      dailyResetAt: input.dailyResetAt,
      weeklyResetAt: input.weeklyResetAt,
      documentUploadCount: input.documentUploadCount,
      imageUploadCount: input.imageUploadCount,
    })
    .onConflictDoUpdate({
      target: quotaState.identityId,
      set: {
        dailyUsedUnits: input.dailyUsedUnits,
        weeklyUsedUnits: input.weeklyUsedUnits,
        dailyResetAt: input.dailyResetAt,
        weeklyResetAt: input.weeklyResetAt,
        documentUploadCount: input.documentUploadCount,
        imageUploadCount: input.imageUploadCount,
        updatedAt: new Date(),
      },
    });
}

export async function getTrialQuotaUsage(db: QuotaDb, userId: string): Promise<TrialQuotaUsage> {
  const user = await getUserIdentityRow(db, userId);
  if (!user || user.deletedAt) {
    throw unauthorized("Bilgileri kontrol et.");
  }

  const identity =
    user.identityId
      ? (
          await db
            .select()
            .from(userIdentityHistory)
            .where(eq(userIdentityHistory.id, user.identityId))
            .limit(1)
        )[0] ??
        (await ensureUserIdentity(db, {
          userId: user.userId,
          email: user.email,
        }))
      : await ensureUserIdentity(db, {
          userId: user.userId,
          email: user.email,
        });
  const planCode = normalizeBillingPlanCode(user.planCode);
  const plan = getBillingPlan(planCode);
  const current = now();
  const dailyStartAt = new Date(current.getTime() - FIVE_HOUR_WINDOW_MS);
  const weeklyStartAt = new Date(current.getTime() - WEEKLY_WINDOW_MS);

  const [daily, weekly] = await Promise.all([
    countUsageInWindow(db, {
      identityId: identity.id,
      startAt: dailyStartAt,
    }),
    countUsageInWindow(db, {
      identityId: identity.id,
      startAt: weeklyStartAt,
    }),
  ]);

  const dailyUsed = daily.usedUnits;
  const weeklyUsed = weekly.usedUnits;
  const dailyRemaining = Math.max(0, plan.fiveHourBudgetUnits - dailyUsed);
  const weeklyRemaining = Math.max(0, plan.weeklyBudgetUnits - weeklyUsed);
  const documentUploadCount = weekly.documentUnits;
  const imageUploadCount = weekly.imageUnits;
  const documentUploadRemaining = Math.max(0, plan.documentUploadLimit - documentUploadCount);
  const imageUploadRemaining = Math.max(0, plan.imageUploadLimit - imageUploadCount);
  const dailyResetAt = buildResetAt(daily.oldestCreatedAt, FIVE_HOUR_WINDOW_MS);
  const weeklyResetAt = buildResetAt(weekly.oldestCreatedAt, WEEKLY_WINDOW_MS);

  await syncQuotaStateMaterialization(db, {
    identityId: identity.id,
    dailyUsedUnits: dailyUsed,
    weeklyUsedUnits: weeklyUsed,
    dailyResetAt,
    weeklyResetAt,
    documentUploadCount,
    imageUploadCount,
  });
  await Promise.all([
    syncQuotaWindowMaterialization(db, {
      identityId: identity.id,
      type: "daily",
      startedAt: dailyStartAt,
      endsAt: dailyResetAt,
      usedUnits: dailyUsed,
      documentUploadCount: daily.documentUnits,
      imageUploadCount: daily.imageUnits,
    }),
    syncQuotaWindowMaterialization(db, {
      identityId: identity.id,
      type: "weekly",
      startedAt: weeklyStartAt,
      endsAt: weeklyResetAt,
      usedUnits: weeklyUsed,
      documentUploadCount,
      imageUploadCount,
    }),
  ]);

  return {
    identityId: identity.id,
    planCode,
    qualityProfile: readQualityProfileForPlan(planCode),
    dailyLimit: plan.fiveHourBudgetUnits,
    dailyUsed,
    dailyRemaining,
    dailyResetAt,
    dailyProgressPercent: buildRemainingPercent(dailyUsed, plan.fiveHourBudgetUnits),
    weeklyLimit: plan.weeklyBudgetUnits,
    weeklyUsed,
    weeklyRemaining,
    weeklyResetAt,
    weeklyProgressPercent: buildRemainingPercent(weeklyUsed, plan.weeklyBudgetUnits),
    documentUploadLimit: plan.documentUploadLimit,
    documentUploadCount,
    documentUploadRemaining,
    imageUploadLimit: plan.imageUploadLimit,
    imageUploadCount,
    imageUploadRemaining,
  };
}

export function buildTrialQuotaWindows(quota: TrialQuotaUsage): QuotaWindowTruth[] {
  return [
    {
      type: "five_hour",
      title: "5 Saatlik",
      windowHours: 5,
      limit: quota.dailyLimit,
      used: quota.dailyUsed,
      remaining: quota.dailyRemaining,
      remainingFraction: quota.dailyLimit > 0 ? quota.dailyRemaining / quota.dailyLimit : null,
      remainingPercent: quota.dailyProgressPercent,
      resetAt: quota.dailyResetAt,
    },
    {
      type: "weekly",
      title: "7 Günlük",
      windowHours: 168,
      limit: quota.weeklyLimit,
      used: quota.weeklyUsed,
      remaining: quota.weeklyRemaining,
      remainingFraction: quota.weeklyLimit > 0 ? quota.weeklyRemaining / quota.weeklyLimit : null,
      remainingPercent: quota.weeklyProgressPercent,
      resetAt: quota.weeklyResetAt,
    },
  ];
}

export function getTrialQuotaPolicy(): TrialQuotaPolicy {
  return {
    mode: "identity_window",
    source: "usage_records+quota_state",
    commitPoint: "task.create+brain.inference",
    consumptionMetric: "budget_units",
    fiveHourWindowHours: 5,
    dailyWindowHours: 5,
    weeklyWindowHours: 168,
    idempotency: {
      scope: "identity",
      keyStrategy: "taskId+metric",
      singleWritePerTask: true,
    },
    appliesTo: ["chat", "task", "document_upload", "image_upload"],
    safeErrorCodes: TRIAL_QUOTA_SAFE_ERROR_CODES,
    surfaces: {
      authMe: "/v1/auth/me",
      mobileBootstrap: "/v1/mobile/bootstrap",
      brainProfile: "/v1/brain/profile",
    },
  };
}

export async function assertTrialTaskQuotaAllowed(
  app: FastifyInstance,
  userId: string,
  requiredBudgetUnits = 1,
): Promise<void> {
  const quota = await getTrialQuotaUsage(app.db, userId);
  assertTrialTaskQuotaAllowedFromUsage(quota, requiredBudgetUnits);
}

export function assertTrialTaskQuotaAllowedFromUsage(
  quota: TrialQuotaUsage,
  requiredBudgetUnits = 1,
): void {
  const requiredUnits = Math.max(1, normalizeCount(requiredBudgetUnits));

  if (quota.dailyRemaining < requiredUnits) {
    throw new AppError(409, "five_hour_quota_reached", "5 saatlik kullanım hakkı doldu.", {
      retryAt: quota.dailyResetAt,
      requiredBudgetUnits: requiredUnits,
    });
  }

  if (quota.weeklyRemaining < requiredUnits) {
    throw new AppError(409, "weekly_quota_reached", "Haftalık kullanım hakkı doldu.", {
      retryAt: quota.weeklyResetAt,
      requiredBudgetUnits: requiredUnits,
    });
  }
}

export function assertAttachmentQuotaAllowedFromUsage(
  quota: TrialQuotaUsage,
  input: {
    requiredDocumentUploads?: number;
    requiredImageUploads?: number;
  },
): void {
  const requiredDocumentUploads = normalizeCount(input.requiredDocumentUploads);
  const requiredImageUploads = normalizeCount(input.requiredImageUploads);

  if (requiredDocumentUploads > 0 && quota.documentUploadRemaining < requiredDocumentUploads) {
    throw new AppError(409, "document_quota_reached", "Belge yükleme hakkı doldu.", {
      retryAt: quota.weeklyResetAt,
      requiredDocumentUploads,
    });
  }

  if (requiredImageUploads > 0 && quota.imageUploadRemaining < requiredImageUploads) {
    throw new AppError(409, "image_quota_reached", "Görsel yükleme hakkı doldu.", {
      retryAt: quota.weeklyResetAt,
      requiredImageUploads,
    });
  }
}

export async function assertAttachmentQuotaAllowed(
  app: FastifyInstance,
  userId: string,
  input: {
    requiredDocumentUploads?: number;
    requiredImageUploads?: number;
  },
): Promise<void> {
  const quota = await getTrialQuotaUsage(app.db, userId);
  assertAttachmentQuotaAllowedFromUsage(quota, input);
}

export async function recordTrialTaskUsage(
  db: QuotaDb,
  input: {
    userId: string;
    taskId: string;
    requiredBudgetUnits?: number;
  },
) {
  const quota = await getTrialQuotaUsage(db, input.userId);
  await recordUsageLedgerEntry(db, {
    userId: input.userId,
    identityId: quota.identityId,
    taskId: input.taskId,
    metric: BILLING_USAGE_METRICS.trialTask,
    quantity: 1,
    budgetUnits: Math.max(1, normalizeCount(input.requiredBudgetUnits ?? 1)),
    qualityProfile: quota.qualityProfile,
    planSnapshot: {
      planCode: quota.planCode,
      qualityProfile: quota.qualityProfile,
      source: "trial_task",
    },
  });
}

export async function resolveUsageIdentityContext(
  db: QuotaDb,
  input: {
    userId: string;
    email?: string | null;
  },
): Promise<{
  identityId: string;
  planCode: BillingPlanCode;
  qualityProfile: QualityProfile;
}> {
  const user = await getUserIdentityRow(db, input.userId);
  if (!user || user.deletedAt) {
    throw unauthorized("Bilgileri kontrol et.");
  }

  const identity = user.identityId
    ? (
        await db
          .select()
          .from(userIdentityHistory)
          .where(eq(userIdentityHistory.id, user.identityId))
          .limit(1)
      )[0] ?? null
    : await ensureUserIdentity(db, {
        userId: input.userId,
        email: input.email ?? user.email,
      });

  if (!identity) {
    throw new AppError(500, "identity_missing", "Kimlik durumu hazırlanamadı.");
  }

  const planCode = normalizeBillingPlanCode(user.planCode);
  return {
    identityId: identity.id,
    planCode,
    qualityProfile: readQualityProfileForPlan(planCode),
  };
}
