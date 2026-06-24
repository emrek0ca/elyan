import { and, asc, eq, gte, lt, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { billingCreditLedger } from "../../db/schema.js";

type BillingReadDb = Pick<FastifyInstance["db"], "select">;
type BillingWriteDb = Pick<FastifyInstance["db"], "select" | "insert">;

export type CreditStatus = "available" | "depleted" | "trial" | "inactive";

export type CreditWindowSummary = {
  balance: number;
  granted: number;
  used: number;
};

export function buildManageSubscriptionHint(provider: string | null | undefined): string {
  const normalized = String(provider ?? "").trim().toLowerCase();

  if (normalized === "apple_store") {
    return "Aboneliğini App Store aboneliklerinden yönet.";
  }

  if (normalized === "google_play") {
    return "Aboneliğini Google Play aboneliklerinden yönet.";
  }

  return "Aboneliğini Elyan destek kanalı üzerinden yönet.";
}

export function buildCreditStatus(input: {
  balance: number;
  subscriptionStatus: string;
  trialActive: boolean;
}): CreditStatus {
  if (input.trialActive) {
    return "trial";
  }

  const normalizedStatus = input.subscriptionStatus.trim().toLowerCase();
  if (normalizedStatus !== "active" && normalizedStatus !== "trialing") {
    return "inactive";
  }

  return input.balance > 0 ? "available" : "depleted";
}

export async function getLatestCreditBalance(db: BillingReadDb, userId: string): Promise<number> {
  const rows = await db
    .select({
      balanceAfter: billingCreditLedger.balanceAfter,
    })
    .from(billingCreditLedger)
    .where(eq(billingCreditLedger.userId, userId))
    .orderBy(sql`${billingCreditLedger.createdAt} desc`, sql`${billingCreditLedger.id} desc`)
    .limit(1);

  return Math.max(0, Number(rows[0]?.balanceAfter ?? 0));
}

export async function getCreditWindowSummary(
  db: BillingReadDb,
  input: {
    userId: string;
    startAt?: Date | null;
    endAt?: Date | null;
  },
): Promise<CreditWindowSummary> {
  const clauses = [eq(billingCreditLedger.userId, input.userId)];
  if (input.startAt) {
    clauses.push(gte(billingCreditLedger.createdAt, input.startAt));
  }
  if (input.endAt) {
    clauses.push(lt(billingCreditLedger.createdAt, input.endAt));
  }

  const [rows, balance] = await Promise.all([
    db
      .select({
        granted: sql<number>`coalesce(sum(case when ${billingCreditLedger.deltaCredits} > 0 then ${billingCreditLedger.deltaCredits} else 0 end), 0)`,
        used: sql<number>`coalesce(sum(case when ${billingCreditLedger.deltaCredits} < 0 then abs(${billingCreditLedger.deltaCredits}) else 0 end), 0)`,
      })
      .from(billingCreditLedger)
      .where(and(...clauses)),
    getLatestCreditBalance(db, input.userId),
  ]);

  return {
    balance,
    granted: Number(rows[0]?.granted ?? 0),
    used: Number(rows[0]?.used ?? 0),
  };
}

export async function recordCreditLedgerEntry(
  db: BillingWriteDb,
  input: {
    userId: string;
    entitlementEventId?: string | null;
    taskId?: string | null;
    aiProviderInvocationId?: string | null;
    reason: string;
    deltaCredits: number;
    metadata?: Record<string, unknown>;
  },
) {
  const lastBalance = await getLatestCreditBalance(db, input.userId);
  const nextBalance = Math.max(0, lastBalance + Math.trunc(input.deltaCredits));
  const rows = await db
    .insert(billingCreditLedger)
    .values({
      userId: input.userId,
      entitlementEventId: input.entitlementEventId ?? null,
      taskId: input.taskId ?? null,
      aiProviderInvocationId: input.aiProviderInvocationId ?? null,
      reason: input.reason,
      deltaCredits: Math.trunc(input.deltaCredits),
      balanceAfter: nextBalance,
      metadata: input.metadata ?? {},
    })
    .returning();

  return rows[0];
}
