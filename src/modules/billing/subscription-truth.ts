import {
  getBillingPlan,
  normalizeBillingPlanCode,
  normalizePlanBrainProfile,
  type BillingPlanCode,
  type PlanBrainProfile,
  type QualityProfile,
} from "./catalog.js";

type SubscriptionTruthInput = {
  planCode?: string | null;
  status?: string | null;
  aiCreditsMonthly?: number | null;
  tokensMonthly?: number | null;
  taskLimitMonthly?: number | null;
  brainProfile?: PlanBrainProfile | null;
  periodEndsAt?: Date | null;
  trialEndsAt?: Date | null;
  creditBalance?: number | null;
  tokenBalance?: number | null;
  creditGrantedThisPeriod?: number | null;
  tokensGrantedThisPeriod?: number | null;
  creditPeriodEndsAt?: Date | null;
  tokenPeriodEndsAt?: Date | null;
  billingProvider?: string | null;
  subscriptionSource?: string | null;
  manageSubscriptionHint?: string | null;
  creditStatus?: string | null;
  tokenStatus?: string | null;
  trialOffer?: WelcomeProTrialOffer | null;
};

export type WelcomeProTrialOfferStatus = "available" | "claimed" | "expired" | "unavailable";

export type WelcomeProTrialOffer = {
  code: "welcome_pro_30d";
  planCode: "pro";
  durationDays: 30;
  status: WelcomeProTrialOfferStatus;
  eligible: boolean;
  claimed: boolean;
  claimPath: "/v1/billing/trials/pro/claim";
  expiresAt: Date | null;
};

export type SubscriptionTruth = {
  planCode: BillingPlanCode;
  qualityProfile: QualityProfile;
  status: string;
  aiCreditsMonthly: number;
  tokensMonthly: number;
  taskLimitMonthly: number;
  brainProfile: PlanBrainProfile;
  periodEndsAt: Date | null;
  trialEndsAt: Date | null;
  creditBalance: number;
  tokenBalance: number;
  creditGrantedThisPeriod: number;
  tokensGrantedThisPeriod: number;
  creditPeriodEndsAt: Date | null;
  tokenPeriodEndsAt: Date | null;
  billingProvider: string | null;
  subscriptionSource: string | null;
  manageSubscriptionHint: string | null;
  creditStatus: string | null;
  tokenStatus: string | null;
  trialOffer: WelcomeProTrialOffer;
};

const WELCOME_PRO_TRIAL_OFFER_BASE = {
  code: "welcome_pro_30d",
  planCode: "pro",
  durationDays: 30,
  claimPath: "/v1/billing/trials/pro/claim",
} as const;

function shapePlanBrainProfile(planCode: BillingPlanCode, input?: PlanBrainProfile | null): PlanBrainProfile {
  const planProfile = getBillingPlan(planCode).brainProfile;
  const candidate = normalizePlanBrainProfile(input ?? planProfile);

  if (planProfile.tier !== "premium") {
    return planProfile;
  }

  return {
    qualityProfile: planProfile.qualityProfile,
    tier: "premium",
    reasoningMultiplier: 5,
    retrievalFanout: Math.max(planProfile.retrievalFanout, candidate.retrievalFanout),
    memoryFanout: Math.max(planProfile.memoryFanout, candidate.memoryFanout),
    maxTokenScale: Math.max(planProfile.maxTokenScale, candidate.maxTokenScale),
  };
}

function resolveMonthlyTokens(planCode: BillingPlanCode, input: SubscriptionTruthInput | null | undefined, planDefault: number): number {
  const explicitValue = input?.tokensMonthly ?? input?.aiCreditsMonthly;
  const numericValue = Number(explicitValue ?? NaN);

  if (planCode === "free" && Number.isFinite(numericValue) && numericValue <= 0) {
    return planDefault;
  }

  return explicitValue ?? planDefault;
}

function resolveMonthlyTaskLimit(planCode: BillingPlanCode, inputValue: number | null | undefined, planDefault: number): number {
  const numericValue = Number(inputValue ?? NaN);
  if (planCode === "free" && Number.isFinite(numericValue) && numericValue <= 0) {
    return planDefault;
  }

  return inputValue ?? planDefault;
}

export function shapeWelcomeProTrialOffer(
  input?: Pick<SubscriptionTruthInput, "planCode" | "status" | "trialEndsAt"> | null,
  currentTime: Date = new Date(),
): WelcomeProTrialOffer {
  const planCode = normalizeBillingPlanCode(input?.planCode);
  const status = String(input?.status ?? "free").trim().toLowerCase();
  const expiresAt = input?.trialEndsAt ?? null;
  const hasFutureExpiry = expiresAt instanceof Date && expiresAt.getTime() > currentTime.getTime();
  let offerStatus: WelcomeProTrialOfferStatus = "unavailable";

  if (planCode === "free" && status === "free" && expiresAt instanceof Date) {
    offerStatus = hasFutureExpiry ? "available" : "expired";
  } else if (planCode === "pro" && status === "trialing" && hasFutureExpiry) {
    offerStatus = "claimed";
  }

  return {
    ...WELCOME_PRO_TRIAL_OFFER_BASE,
    status: offerStatus,
    eligible: offerStatus === "available",
    claimed: offerStatus === "claimed",
    expiresAt,
  };
}

export function shapeSubscriptionTruth(input?: SubscriptionTruthInput | null): SubscriptionTruth {
  const plan = getBillingPlan(input?.planCode);
  const planCode = normalizeBillingPlanCode(input?.planCode);
  const monthlyTokens = resolveMonthlyTokens(planCode, input, plan.aiCreditsMonthly);
  const tokensGrantedThisPeriod = Math.max(
    0,
    input?.tokensGrantedThisPeriod ?? input?.creditGrantedThisPeriod ?? monthlyTokens,
  );
  const explicitTokenBalance = input?.tokenBalance ?? input?.creditBalance;
  const tokenBalance = Math.max(0, explicitTokenBalance ?? tokensGrantedThisPeriod);
  const tokenPeriodEndsAt = input?.tokenPeriodEndsAt ?? input?.creditPeriodEndsAt ?? input?.periodEndsAt ?? null;
  const tokenStatus = input?.tokenStatus ?? input?.creditStatus ?? null;

  return {
    planCode,
    qualityProfile: plan.brainProfile.qualityProfile,
    status: input?.status ?? "free",
    aiCreditsMonthly: monthlyTokens,
    tokensMonthly: monthlyTokens,
    taskLimitMonthly: resolveMonthlyTaskLimit(planCode, input?.taskLimitMonthly, plan.taskLimitMonthly),
    brainProfile: shapePlanBrainProfile(planCode, input?.brainProfile ?? plan.brainProfile),
    periodEndsAt: input?.periodEndsAt ?? null,
    trialEndsAt: input?.trialEndsAt ?? null,
    creditBalance: tokenBalance,
    tokenBalance,
    creditGrantedThisPeriod: tokensGrantedThisPeriod,
    tokensGrantedThisPeriod,
    creditPeriodEndsAt: tokenPeriodEndsAt,
    tokenPeriodEndsAt,
    billingProvider: input?.billingProvider ?? null,
    subscriptionSource: input?.subscriptionSource ?? null,
    manageSubscriptionHint: input?.manageSubscriptionHint ?? null,
    creditStatus: tokenStatus,
    tokenStatus,
    trialOffer:
      input?.trialOffer ??
      shapeWelcomeProTrialOffer({
        planCode,
        status: input?.status,
        trialEndsAt: input?.trialEndsAt,
      }),
  };
}
