import Decimal from 'decimal.js';
import type {
  ControlPlaneAccount,
  ControlPlanePlan,
  ControlPlaneUsageSnapshot,
  ControlPlaneUsageSnapshotState,
} from './types';

const CREDIT_SCALE = 2;
const TOKENS_PER_REQUEST_LIMIT_MULTIPLIER = 4_000;

function formatCredits(value: Decimal.Value): string {
  return new Decimal(value).toFixed(CREDIT_SCALE);
}

function resolveDailyTokenLimit(plan: ControlPlanePlan) {
  const requestLimit = Math.max(0, plan.dailyLimits.hostedRequestsPerDay);
  return requestLimit > 0 ? requestLimit * TOKENS_PER_REQUEST_LIMIT_MULTIPLIER : 0;
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
  remainingHostedToolActionCalls: number,
  remainingTokens: number
): ControlPlaneUsageSnapshotState {
  if (!isHostedPlan) {
    return 'ok';
  }

  if (monthlyCreditsRemaining.lte(0)) {
    return 'monthly_credits_exhausted';
  }

  if (remainingRequests <= 0 || remainingHostedToolActionCalls <= 0 || remainingTokens <= 0) {
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
    dailyTokens?: number;
  }
): ControlPlaneUsageSnapshot {
  const dayKey = getUtcDayKey(now);
  const resetAt = getNextUtcMidnight(now).toISOString();
  const requests = counters?.dailyRequests ?? 0;
  const toolActionCalls = counters?.dailyHostedToolActionCalls ?? 0;
  const tokens = counters?.dailyTokens ?? 0;
  const dailyRequestsLimit = plan.dailyLimits.hostedRequestsPerDay;
  const dailyHostedToolActionCallsLimit = plan.dailyLimits.hostedToolActionCallsPerDay;
  const dailyTokensLimit = resolveDailyTokenLimit(plan);
  const isHostedPlan = dailyRequestsLimit > 0 || dailyHostedToolActionCallsLimit > 0;
  const remainingRequests = Math.max(dailyRequestsLimit - requests, 0);
  const remainingHostedToolActionCalls = Math.max(dailyHostedToolActionCallsLimit - toolActionCalls, 0);
  const remainingTokens = Math.max(dailyTokensLimit - tokens, 0);
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
    dailyTokens: tokens,
    dailyTokensLimit,
    remainingTokens,
    monthlyCreditsRemaining,
    monthlyCreditsBurned,
    state: resolveSnapshotState(
      isHostedPlan,
      new Decimal(monthlyCreditsRemaining),
      remainingRequests,
      remainingHostedToolActionCalls,
      remainingTokens
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
  const tokens = baseline?.dailyTokens ?? 0;

  return createUsageSnapshot(plan, balanceCredits, now, {
    dailyRequests: requests,
    dailyHostedToolActionCalls: toolActionCalls,
    dailyTokens: tokens,
  });
}

export function advanceUsageSnapshot(
  snapshot: ControlPlaneUsageSnapshot,
  plan: ControlPlanePlan,
  balanceCredits: Decimal.Value,
  requestCount: number,
  hostedToolActionCalls: number,
  requestTokens: number,
  now = new Date()
): ControlPlaneUsageSnapshot {
  const normalized = normalizeUsageSnapshot(snapshot, plan, balanceCredits, now);

  return createUsageSnapshot(plan, balanceCredits, now, {
    dailyRequests: normalized.dailyRequests + requestCount,
    dailyHostedToolActionCalls: normalized.dailyHostedToolActionCalls + hostedToolActionCalls,
    dailyTokens: normalized.dailyTokens + requestTokens,
  });
}

export function evaluateUsageConsumption(
  snapshot: ControlPlaneUsageSnapshot,
  requestCount: number,
  hostedToolActionCalls: number,
  requestTokens: number,
  balanceBefore: Decimal.Value,
  balanceAfter: Decimal.Value
): {
  allowed: boolean;
  denialReason?: 'daily_requests_limit' | 'daily_tool_action_calls_limit' | 'daily_tokens_limit' | 'monthly_credits_exhausted';
  resetAt?: string;
  remainingRequests?: number;
  remainingHostedToolActionCalls?: number;
  remainingTokens?: number;
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
      remainingTokens: snapshot.remainingTokens,
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
      remainingTokens: snapshot.remainingTokens,
      monthlyCreditsRemaining: formatCredits(balanceBefore),
    };
  }

  const remainingTokens = snapshot.remainingTokens - requestTokens;
  if (remainingTokens < 0) {
    return {
      allowed: false,
      denialReason: 'daily_tokens_limit',
      resetAt: snapshot.resetAt,
      remainingRequests: snapshot.remainingRequests,
      remainingHostedToolActionCalls: snapshot.remainingHostedToolActionCalls,
      remainingTokens: snapshot.remainingTokens,
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
        denialReason?: 'daily_requests_limit' | 'daily_tool_action_calls_limit' | 'daily_tokens_limit' | 'monthly_credits_exhausted';
        resetAt?: string;
        remainingRequests?: number;
        remainingHostedToolActionCalls?: number;
        remainingTokens?: number;
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

  if (denial.denialReason === 'daily_tokens_limit') {
    return {
      message: `Hosted daily token limit reached for ${plan.title}. ${denial.remainingTokens ?? 0} tokens remaining. Resets at ${denial.resetAt ?? 'the next UTC midnight'}.`,
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
