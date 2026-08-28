export type BillingPlanCode = "free" | "solo" | "pro";
export type QualityProfile = "free_basic" | "solo_enhanced" | "pro_max";

export type PlanBrainProfile = {
  qualityProfile: QualityProfile;
  tier: "standard" | "premium";
  reasoningMultiplier: 1 | 3 | 5;
  retrievalFanout: number;
  memoryFanout: number;
  maxTokenScale: number;
};

export type BillingPlan = {
  code: BillingPlanCode;
  label: string;
  monthlyPrice: number;
  currencyCode: "USD";
  interval: "MONTHLY";
  desktopLimit: number;
  taskLimitMonthly: number;
  aiCreditsMonthly: number;
  imageGenerationLimitDaily: number;
  imageGenerationLimitMonthly: number;
  fiveHourBudgetUnits: number;
  dailyBudgetUnits: number;
  weeklyBudgetUnits: number;
  documentUploadLimit: number;
  imageUploadLimit: number;
  toolUnitsLimit: number;
  byokRequired: boolean;
  brainProfile: PlanBrainProfile;
  recommended?: boolean;
  visible: boolean;
  features: string[];
  providerProducts: {
    apple?: {
      productId: string;
      subscriptionGroup: "elyan_plans";
      duration: "P1M";
    };
    google?: {
      productId: string;
      basePlanId: "monthly";
      offerId?: string;
    };
  };
};

function createBrainProfile(input: PlanBrainProfile): PlanBrainProfile {
  return input;
}

export function canUseDesktopConnections(code?: string | null): boolean {
  return getBillingPlan(code).desktopLimit > 0;
}

const BILLING_PLAN_CATALOG: Record<BillingPlanCode, BillingPlan> = {
  free: {
    code: "free",
    label: "Free",
    monthlyPrice: 0,
    currencyCode: "USD",
    interval: "MONTHLY",
    desktopLimit: 0,
    taskLimitMonthly: 50,
    aiCreditsMonthly: 120,
    imageGenerationLimitDaily: 3,
    imageGenerationLimitMonthly: 3,
    fiveHourBudgetUnits: 12,
    dailyBudgetUnits: 12,
    weeklyBudgetUnits: 72,
    documentUploadLimit: 4,
    imageUploadLimit: 4,
    toolUnitsLimit: 3,
    byokRequired: false,
    brainProfile: createBrainProfile({
      qualityProfile: "free_basic",
      tier: "standard",
      reasoningMultiplier: 1,
      retrievalFanout: 2,
      memoryFanout: 2,
      maxTokenScale: 1,
    }),
    visible: true,
    providerProducts: {},
    features: [
      "Masaüstü bağlantısı yok",
      "5 saatlik ve haftalık kullanım penceresi",
      "Elyan'ı mobil sohbetle denemek için",
    ],
  },
  solo: {
    code: "solo",
    label: "Solo",
    monthlyPrice: 6.99,
    currencyCode: "USD",
    interval: "MONTHLY",
    desktopLimit: 1,
    taskLimitMonthly: 200,
    aiCreditsMonthly: 600,
    imageGenerationLimitDaily: 10,
    imageGenerationLimitMonthly: 10,
    fiveHourBudgetUnits: 18,
    dailyBudgetUnits: 18,
    weeklyBudgetUnits: 288,
    documentUploadLimit: 14,
    imageUploadLimit: 14,
    toolUnitsLimit: 9,
    byokRequired: false,
    brainProfile: createBrainProfile({
      qualityProfile: "solo_enhanced",
      tier: "standard",
      reasoningMultiplier: 3,
      retrievalFanout: 4,
      memoryFanout: 5,
      maxTokenScale: 1.12,
    }),
    visible: true,
    providerProducts: {
      apple: {
        productId: "com.elyan.elyanMobile.solo.monthly",
        subscriptionGroup: "elyan_plans",
        duration: "P1M",
      },
      google: {
        // Google Play product IDs must be all-lowercase (no uppercase allowed),
        // unlike App Store product IDs. Keep Apple's camelCase ID above intact.
        productId: "com.elyan.elyanmobile.solo.monthly",
        basePlanId: "monthly",
      },
    },
    features: [
      "1 masaüstü bağlantısı",
      "Genişletilmiş 5 saatlik ve haftalık kullanım",
      "Günlük hafif kullanım için",
    ],
  },
  pro: {
    code: "pro",
    label: "Pro",
    monthlyPrice: 17.99,
    currencyCode: "USD",
    interval: "MONTHLY",
    desktopLimit: 2,
    taskLimitMonthly: 2_000,
    aiCreditsMonthly: 2_000,
    imageGenerationLimitDaily: 20,
    imageGenerationLimitMonthly: 20,
    fiveHourBudgetUnits: 60,
    dailyBudgetUnits: 60,
    weeklyBudgetUnits: 960,
    documentUploadLimit: 48,
    imageUploadLimit: 48,
    toolUnitsLimit: 24,
    byokRequired: false,
    brainProfile: createBrainProfile({
      qualityProfile: "pro_max",
      tier: "premium",
      reasoningMultiplier: 5,
      retrievalFanout: 6,
      memoryFanout: 8,
      maxTokenScale: 1.35,
    }),
    recommended: true,
    visible: true,
    providerProducts: {
      apple: {
        productId: "com.elyan.elyanMobile.pro.monthly",
        subscriptionGroup: "elyan_plans",
        duration: "P1M",
      },
      google: {
        // Google Play product IDs must be all-lowercase (no uppercase allowed),
        // unlike App Store product IDs. Keep Apple's camelCase ID above intact.
        productId: "com.elyan.elyanmobile.pro.monthly",
        basePlanId: "monthly",
      },
    },
    features: [
      "2 masaüstü bağlantısı",
      "En yüksek 5 saatlik ve haftalık kullanım",
      "Öncelikli kuyruk ve daha geniş geçmiş",
    ],
  },
};

export function normalizeBillingPlanCode(code?: string | null): BillingPlanCode {
  const normalized = String(code || "free").trim().toLowerCase();

  if (normalized === "solo" || normalized === "pro" || normalized === "free") {
    return normalized;
  }

  if (normalized === "team") {
    return "pro";
  }

  return "free";
}

export function getBillingPlan(code?: string | null): BillingPlan {
  const normalized = normalizeBillingPlanCode(code);
  return BILLING_PLAN_CATALOG[normalized] ?? BILLING_PLAN_CATALOG.free;
}

/**
 * Ordering of the sellable tiers. Higher rank supersedes lower — used for
 * upgrade-vs-downgrade decisions (an upgrade applies immediately, a downgrade
 * is deferred to the end of the paid period). "pro_max" is a *quality
 * profile*, not a plan, and deliberately has no rank here.
 */
const BILLING_PLAN_TIER_RANK: Record<BillingPlanCode, number> = {
  free: 0,
  solo: 1,
  pro: 2,
};

export function planTierRank(code?: string | null): number {
  return BILLING_PLAN_TIER_RANK[normalizeBillingPlanCode(code)] ?? 0;
}

export function listSellableBillingPlans(): BillingPlan[] {
  return Object.values(BILLING_PLAN_CATALOG).filter((plan) => plan.visible);
}

export function getPlanBrainProfile(code?: string | null): PlanBrainProfile {
  return getBillingPlan(code).brainProfile;
}

export function normalizePlanBrainProfile(input?: unknown): PlanBrainProfile {
  const fallback = BILLING_PLAN_CATALOG.free.brainProfile;
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return fallback;
  }

  const record = input as Record<string, unknown>;
  const qualityProfile =
    record.qualityProfile === "pro_max"
      ? "pro_max"
      : record.qualityProfile === "solo_enhanced"
        ? "solo_enhanced"
        : "free_basic";
  const tier = record.tier === "premium" ? "premium" : "standard";
  const reasoningMultiplierRaw = Number(record.reasoningMultiplier);
  const reasoningMultiplier =
    reasoningMultiplierRaw >= 5 ? 5 : reasoningMultiplierRaw >= 3 ? 3 : 1;
  const retrievalFanout = Math.max(
    1,
    Math.min(
      10,
      Math.round(
        Number(record.retrievalFanout) ||
          (qualityProfile === "pro_max" ? 6 : qualityProfile === "solo_enhanced" ? 4 : 2),
      ),
    ),
  );
  const memoryFanout = Math.max(
    1,
    Math.min(
      12,
      Math.round(
        Number(record.memoryFanout) ||
          (qualityProfile === "pro_max" ? 8 : qualityProfile === "solo_enhanced" ? 5 : 2),
      ),
    ),
  );
  const maxTokenScaleRaw = Number(record.maxTokenScale);
  const maxTokenScale =
    Number.isFinite(maxTokenScaleRaw) && maxTokenScaleRaw > 0
      ? Math.min(2, Math.max(1, Number(maxTokenScaleRaw.toFixed(2))))
      : qualityProfile === "pro_max"
        ? 1.35
        : qualityProfile === "solo_enhanced"
          ? 1.12
          : 1;

  return createBrainProfile({
    qualityProfile,
    tier,
    reasoningMultiplier: reasoningMultiplier === 5 ? 5 : reasoningMultiplier === 3 ? 3 : 1,
    retrievalFanout,
    memoryFanout,
    maxTokenScale,
  });
}

export function applyBillingPlanDefaults(code?: string | null): Pick<BillingPlan, "taskLimitMonthly" | "aiCreditsMonthly"> {
  const plan = getBillingPlan(code);
  return {
    taskLimitMonthly: plan.taskLimitMonthly,
    aiCreditsMonthly: plan.aiCreditsMonthly,
  };
}

export function isSellablePlanCode(code?: string | null): code is Exclude<BillingPlanCode, "free"> {
  const normalized = normalizeBillingPlanCode(code);
  return normalized === "solo" || normalized === "pro";
}
