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
};

/**
 * Kullanıcının abonelik gerçeği — istemciye giden TEK şekil.
 *
 * TEK KELİME: `token`. Sistemde tek bir sayaç var; "kredi" onun eski adı.
 * Yarım kalmış bir yeniden adlandırma yüzünden aynı değer iki isimle
 * taşınıyordu (`aiCreditsMonthly`/`tokensMonthly`, `creditBalance`/
 * `tokenBalance`, …) ve okuyan herkes "acaba ikisi farklı mı?" diye
 * duraksıyordu. Farklı değiller; aşağıdaki `@deprecated` alanlar kanonik
 * alanların birebir kopyasıdır ve YALNIZCA yayındaki eski istemciler için
 * duruyor (kullanıcının telefonundaki kurulu sürüm hâlâ `credit*` okuyor —
 * kablodan kaldırmak onu kırardı).
 *
 * Yeni kod SADECE `token*` okur/yazar. Eski adlar, istemci sürümleri
 * geçtikten sonra tek hamlede silinebilsin diye tek bir blokta toplandı.
 */
export type SubscriptionTruth = {
  /** Plan kaç masaüstü bağlamaya izin veriyor (0 = hiç). */
  desktopLimit: number;
  /** Kısayol: istemci sınırı hesaplamak zorunda kalmasın. */
  desktopAllowed: boolean;
  planCode: BillingPlanCode;
  qualityProfile: QualityProfile;
  status: string;
  taskLimitMonthly: number;
  brainProfile: PlanBrainProfile;
  periodEndsAt: Date | null;
  trialEndsAt: Date | null;
  billingProvider: string | null;
  subscriptionSource: string | null;
  manageSubscriptionHint: string | null;

  // Kanonik sayaç alanları.
  tokensMonthly: number;
  tokenBalance: number;
  tokensGrantedThisPeriod: number;
  tokenPeriodEndsAt: Date | null;
  tokenStatus: string | null;

  // --- Eski adlar (yayındaki istemciler için; yeni kod kullanmaz) ---
  /** @deprecated `tokensMonthly` ile aynı değer. */
  aiCreditsMonthly: number;
  /** @deprecated `tokenBalance` ile aynı değer. */
  creditBalance: number;
  /** @deprecated `tokensGrantedThisPeriod` ile aynı değer. */
  creditGrantedThisPeriod: number;
  /** @deprecated `tokenPeriodEndsAt` ile aynı değer. */
  creditPeriodEndsAt: Date | null;
  /** @deprecated `tokenStatus` ile aynı değer. */
  creditStatus: string | null;
};

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
    // MASAÜSTÜ SINIRI İSTEMCİYE SÖYLENİR.
    //
    // Canlı arıza (2026-08-26): free plandaki kullanıcı masaüstünü
    // eşleştirmeye çalıştı, sunucu `desktop_plan_required` döndürdü ve mobil
    // "biraz sonra tekrar dener misin?" dedi. Kullanıcı defalarca denedi —
    // oysa tekrar denemekle ASLA çalışmayacaktı. Sınır sunucuda biliniyordu
    // ama istemciye hiç gönderilmiyordu; istemci de ancak duvara çarparak
    // öğrenebiliyordu.
    desktopLimit: plan.desktopLimit,
    desktopAllowed: plan.desktopLimit > 0,
    qualityProfile: plan.brainProfile.qualityProfile,
    status: input?.status ?? "free",
    taskLimitMonthly: resolveMonthlyTaskLimit(planCode, input?.taskLimitMonthly, plan.taskLimitMonthly),
    brainProfile: shapePlanBrainProfile(planCode, input?.brainProfile ?? plan.brainProfile),
    periodEndsAt: input?.periodEndsAt ?? null,
    trialEndsAt: input?.trialEndsAt ?? null,
    billingProvider: input?.billingProvider ?? null,
    subscriptionSource: input?.subscriptionSource ?? null,
    manageSubscriptionHint: input?.manageSubscriptionHint ?? null,

    // Kanonik sayaç: her değer BİR kez hesaplanır.
    tokensMonthly: monthlyTokens,
    tokenBalance,
    tokensGrantedThisPeriod,
    tokenPeriodEndsAt,
    tokenStatus,

    // Eski adlar — aynı değerlerin kopyası, yalnız yayındaki istemciler için.
    aiCreditsMonthly: monthlyTokens,
    creditBalance: tokenBalance,
    creditGrantedThisPeriod: tokensGrantedThisPeriod,
    creditPeriodEndsAt: tokenPeriodEndsAt,
    creditStatus: tokenStatus,
  };
}
