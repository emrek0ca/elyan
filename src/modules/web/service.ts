import { sql, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { tasks, users } from "../../db/schema.js";
import { getBillingSummary, shapePublicUsageSnapshot } from "../billing/service.js";
import { shapeSubscriptionTruth } from "../billing/subscription-truth.js";
import { getBrainProfile } from "../brain/service.js";
import { listUserDevices, pruneStaleDevices } from "../devices/service.js";
import { getTrialQuotaPolicy } from "../quota/service.js";
import { shapeMobileBootstrapBrain } from "../mobile/service.js";

export async function getWebBootstrap(app: FastifyInstance, userId: string) {
  pruneStaleDevices(app, userId).catch(() => undefined);
  const [userRows, devices, pendingCounts, billing, brain] = await Promise.all([
    app.db
      .select({
        id: users.id,
        email: users.email,
        displayName: users.displayName,
        role: users.role,
        createdAt: users.createdAt,
      })
      .from(users)
      .where(eq(users.id, userId))
      .limit(1),
    listUserDevices(app, userId),
    app.db
      .select({
        pendingApprovals: sql<number>`count(*) filter (where ${tasks.status} = 'waiting_approval')`,
        activeTasks: sql<number>`count(*) filter (where ${tasks.status} in ('queued', 'planning', 'running', 'waiting_approval'))`,
      })
      .from(tasks)
      .where(eq(tasks.userId, userId)),
    getBillingSummary(app, userId),
    getBrainProfile(app, userId),
  ]);

  return {
    user: userRows[0] ?? null,
    billingState: billing.billingState,
    quota: getTrialQuotaPolicy(),
    subscription: shapeSubscriptionTruth({
      planCode: billing.subscription.planCode,
      status: billing.subscription.status,
      aiCreditsMonthly: billing.entitlements.aiCreditsMonthly,
      taskLimitMonthly: billing.entitlements.taskLimitMonthly,
      brainProfile: billing.subscription.brainProfile,
      periodEndsAt: billing.subscription.periodEndsAt,
      trialEndsAt: billing.subscription.trialEndsAt,
      creditBalance: billing.usage.creditBalance,
      tokenBalance: billing.usage.tokenBalance,
      creditGrantedThisPeriod: billing.usage.creditGrantedThisPeriod,
      tokensGrantedThisPeriod: billing.usage.tokensGrantedThisPeriod,
      creditPeriodEndsAt: billing.usage.creditPeriodEndsAt,
      tokenPeriodEndsAt: billing.usage.tokenPeriodEndsAt,
      billingProvider: billing.subscription.billingProvider,
      subscriptionSource: billing.usage.subscriptionSource,
      manageSubscriptionHint: billing.usage.manageSubscriptionHint,
      creditStatus: billing.usage.creditStatus,
      tokenStatus: billing.usage.tokenStatus,
    }),
    usage: shapePublicUsageSnapshot({
      usage: billing.usage,
      subscription: billing.subscription,
    }),
    brain: shapeMobileBootstrapBrain(brain),
    devices,
    recentTasks: [],
    historyFeed: [],
    summary: {
      pendingApprovals: Number(pendingCounts[0]?.pendingApprovals ?? 0),
      activeTasks: Number(pendingCounts[0]?.activeTasks ?? 0),
      connectedDesktops: devices.filter(
        (device) => device.type === "desktop" && device.runtime.isConnected,
      ).length,
    },
  };
}
