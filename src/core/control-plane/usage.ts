import Decimal from 'decimal.js';
import type {
  ControlPlaneAccount,
  ControlPlanePlan,
  ControlPlaneUsageSnapshot,
  ControlPlaneUsageSnapshotState,
} from './types';

const CREDIT_SCALE = 2;

function formatCredits(value: Decimal.Value): string {
  return new Decimal(value).toFixed(CREDIT_SCALE);
}

export function getUtcDayKey(date = new Date()) {
  return date.toISOString().slice(0, 10);
}

export function getNextUtcMidnight(date = new Date()) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() + 1));
}

function resolveSnapshotState(
  isHostedPlan: boolean,
  monthlyCreditsRemaining: Decimal,
  remainingRequests: number,
  remainingHostedToolActionCalls: number
): ControlPlaneUsageSnapshotState {
  if (!isHostedPlan) {
    return 'ok';
  }

  if (monthlyCreditsRemaining.lte(0)) {
    return 'monthly_credits_exhausted';
  }

  if (remainingRequests <= 0 || remainingHostedToolActionCalls <= 0) {
    return 'daily_limit_reached';
  }

  return 'ok';
}

export function createUsageSnapshot(
  plan: ControlPlanePlan,
  balanceCredits: Decimal.Value,
  now = new Date(),
  counters?: {
    dailyRequests?: number;
    dailyHostedToolActionCalls?: number;
  }
): ControlPlaneUsageSnapshot {
  const dayKey = getUtcDayKey(now);
  const resetAt = getNextUtcMidnight(now).toISOString();
  const requests = counters?.dailyRequests ?? 0;
  const toolActionCalls = counters?.dailyHostedToolActionCalls ?? 0;
  const dailyRequestsLimit = plan.dailyLimits.hostedRequestsPerDay;
  const dailyHostedToolActionCallsLimit = plan.dailyLimits.hostedToolActionCallsPerDay;
  const isHostedPlan = dailyRequestsLimit > 0 || dailyHostedToolActionCallsLimit > 0;
  const remainingRequests = Math.max(dailyRequestsLimit - requests, 0);
  const remainingHostedToolActionCalls = Math.max(dailyHostedToolActionCallsLimit - toolActionCalls, 0);
  const monthlyCreditsRemaining = formatCredits(balanceCredits);
  const monthlyCreditsBurned = formatCredits(
    Decimal.max(new Decimal(plan.monthlyIncludedCredits).minus(monthlyCreditsRemaining), 0)
  );

  return {
    dayKey,
    resetAt,
    dailyRequests: requests,
    dailyRequestsLimit,
    remainingRequests,
    dailyHostedToolActionCalls: toolActionCalls,
    dailyHostedToolActionCallsLimit,
    remainingHostedToolActionCalls,
    monthlyCreditsRemaining,
    monthlyCreditsBurned,
    state: resolveSnapshotState(
      isHostedPlan,
      new Decimal(monthlyCreditsRemaining),
      remainingRequests,
      remainingHostedToolActionCalls
    ),
  };
}

export function normalizeUsageSnapshot(
  snapshot: ControlPlaneAccount['usageSnapshot'] | undefined,
  plan: ControlPlanePlan,
  balanceCredits: Decimal.Value,
  now = new Date()
): ControlPlaneUsageSnapshot {
  const currentDayKey = getUtcDayKey(now);
  const baseline = snapshot && snapshot.dayKey === currentDayKey ? snapshot : undefined;
  const requests = baseline?.dailyRequests ?? 0;
  const toolActionCalls = baseline?.dailyHostedToolActionCalls ?? 0;

  return createUsageSnapshot(plan, balanceCredits, now, {
    dailyRequests: requests,
    dailyHostedToolActionCalls: toolActionCalls,
  });
}

export function advanceUsageSnapshot(
  snapshot: ControlPlaneUsageSnapshot,
  plan: ControlPlanePlan,
  balanceCredits: Decimal.Value,
  requestCount: number,
  hostedToolActionCalls: number,
  now = new Date()
): ControlPlaneUsageSnapshot {
  const normalized = normalizeUsageSnapshot(snapshot, plan, balanceCredits, now);

  return createUsageSnapshot(plan, balanceCredits, now, {
    dailyRequests: normalized.dailyRequests + requestCount,
    dailyHostedToolActionCalls: normalized.dailyHostedToolActionCalls + hostedToolActionCalls,
  });
}

export function evaluateUsageConsumption(
  snapshot: ControlPlaneUsageSnapshot,
  requestCount: number,
  hostedToolActionCalls: number,
  balanceBefore: Decimal.Value,
  balanceAfter: Decimal.Value
): {
  allowed: boolean;
  denialReason?: 'daily_requests_limit' | 'daily_tool_action_calls_limit' | 'monthly_credits_exhausted';
  resetAt?: string;
  remainingRequests?: number;
  remainingHostedToolActionCalls?: number;
  monthlyCreditsRemaining?: string;
} {
  const remainingRequests = snapshot.remainingRequests - requestCount;
  if (remainingRequests < 0) {
    return {
      allowed: false,
      denialReason: 'daily_requests_limit',
      resetAt: snapshot.resetAt,
      remainingRequests: snapshot.remainingRequests,
      remainingHostedToolActionCalls: snapshot.remainingHostedToolActionCalls,
      monthlyCreditsRemaining: formatCredits(balanceBefore),
    };
  }

  const remainingHostedToolActionCalls = snapshot.remainingHostedToolActionCalls - hostedToolActionCalls;
  if (remainingHostedToolActionCalls < 0) {
    return {
      allowed: false,
      denialReason: 'daily_tool_action_calls_limit',
      resetAt: snapshot.resetAt,
      remainingRequests: snapshot.remainingRequests,
      remainingHostedToolActionCalls: snapshot.remainingHostedToolActionCalls,
      monthlyCreditsRemaining: formatCredits(balanceBefore),
    };
  }

  if (new Decimal(balanceAfter).lt(0)) {
    return {
      allowed: false,
      denialReason: 'monthly_credits_exhausted',
      monthlyCreditsRemaining: formatCredits(balanceBefore),
    };
  }

  return {
    allowed: true,
  };
}

export function describeUsageLimitDenial(
  denial:
    | {
        denialReason?: 'daily_requests_limit' | 'daily_tool_action_calls_limit' | 'monthly_credits_exhausted';
        resetAt?: string;
        remainingRequests?: number;
        remainingHostedToolActionCalls?: number;
        monthlyCreditsRemaining?: string;
      }
    | undefined,
  plan: ControlPlanePlan
) {
  if (!denial?.denialReason) {
    return null;
  }

  if (denial.denialReason === 'monthly_credits_exhausted') {
    return {
      message: `Hosted credits are exhausted for ${plan.title}. Monthly balance is ${denial.monthlyCreditsRemaining ?? '0.00'}. Upgrade to a higher hosted plan to continue.`,
      code: denial.denialReason,
    };
  }

  const limitLabel =
    denial.denialReason === 'daily_requests_limit' ? 'daily hosted request' : 'daily hosted tool/action';
  const remaining =
    denial.denialReason === 'daily_requests_limit'
      ? denial.remainingRequests ?? 0
      : denial.remainingHostedToolActionCalls ?? 0;

  return {
    message: `Hosted ${limitLabel} limit reached for ${plan.title}. ${remaining} remaining. Resets at ${denial.resetAt ?? 'the next UTC midnight'}. Upgrade to a higher hosted plan for more headroom.`,
    code: denial.denialReason,
  };
}
