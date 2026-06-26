import type { QualityProfile } from "./catalog.js";

export const TOKEN_METERING_VERSION = "2026-06-13.weighted-chat-task.v1";
export const TOKEN_METERING_UNIT_SIZE = 1_000;

export type TokenMeteringSurface = "chat" | "task";

export type TokenMeteringWorkload =
  | "intent"
  | "fast_route"
  | "mobile_chat_fast"
  | "mobile_chat_balanced"
  | "mobile_chat_deep_refine"
  | "document_analysis"
  | "planning"
  | "desktop_handoff";

export type TokenMeteringDepth = "short" | "standard" | "deep" | "planning";
export type TokenBudgetState = "normal" | "conserve" | "critical";

export type AdaptiveInferenceBudget = {
  maxCompletionTokens: number;
  conversationTokenBudget: number;
  conversationMessageBudget: number;
  requestedLongForm: boolean;
  qualityEscalated: boolean;
  budgetState: TokenBudgetState;
  budgetReason:
    | "standard"
    | "quality_escalated"
    | "long_form_expanded"
    | "low_balance_conserve"
    | "low_balance_critical";
};

export type BillableTokenUsage = {
  billableTokens: number;
  meteringVersion: typeof TOKEN_METERING_VERSION;
  surface: TokenMeteringSurface;
  workload: TokenMeteringWorkload;
  depth: TokenMeteringDepth;
  weightedTokenPoints: number;
  tokenUnitSize: number;
  components: {
    userInputTokens: number;
    promptContextTokens: number;
    promptTokens: number;
    completionTokens: number;
  };
};

export function estimateTextTokens(text: string): number {
  const compact = text.replace(/\s+/g, " ").trim();
  return compact ? Math.max(1, Math.ceil(compact.length / 4)) : 0;
}

function normalizeCount(value: number | null | undefined): number {
  return Math.max(0, Math.trunc(Number.isFinite(value) ? Number(value) : 0));
}

function normalizeWorkload(value: string | null | undefined): TokenMeteringWorkload {
  switch (value) {
    case "intent":
    case "fast_route":
    case "mobile_chat_fast":
    case "mobile_chat_balanced":
    case "mobile_chat_deep_refine":
    case "document_analysis":
    case "planning":
    case "desktop_handoff":
      return value;
    default:
      return "mobile_chat_fast";
  }
}

function isLongFormPrompt(prompt: string): boolean {
  const normalized = String(prompt || "").toLocaleLowerCase("tr-TR");
  const conciseSignals = [
    "kısa",
    "kısaca",
    "özet",
    "özetle",
    "tek cümle",
    "birkaç cümle",
    "madde madde kısa",
  ];
  if (conciseSignals.some((signal) => normalized.includes(signal))) {
    return false;
  }

  const longFormSignals = [
    "uzun",
    "detaylı",
    "ayrıntılı",
    "kapsamlı",
    "eksiksiz",
    "tam metin",
    "makale",
    "rapor",
    "inceleme",
    "adım adım",
    "derinlemesine",
    "genişlet",
    "devam et",
    "yarım bırakma",
  ];
  return longFormSignals.some((signal) => normalized.includes(signal));
}

function shouldEscalateChatQuality(input: {
  workload: TokenMeteringWorkload;
  prompt: string;
  requestedLongForm: boolean;
}): boolean {
  if (
    input.workload !== "mobile_chat_fast" &&
    input.workload !== "mobile_chat_balanced" &&
    input.workload !== "mobile_chat_deep_refine"
  ) {
    return false;
  }
  if (input.requestedLongForm) {
    return false;
  }

  const normalized = String(input.prompt || "").toLocaleLowerCase("tr-TR").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return false;
  }

  const wordCount = normalized.split(/\s+/).filter(Boolean).length;
  const questionCount = (normalized.match(/\?/g) ?? []).length;
  const sentenceCount = normalized
    .split(/[.!?]+/)
    .map((part) => part.trim())
    .filter(Boolean).length;

  return (
    normalized.length >= 110 ||
    wordCount >= 18 ||
    questionCount >= 2 ||
    sentenceCount >= 2 ||
    /\b(neden|nasıl|acikla|açıkla|örnek|ornek|karşılaştır|karsilastir|anlat|detay|detaylı|detayli|analiz|incele|değerlendir|degerlendir|yarım bırakma|yarim birakma|tamamla|mantık|mantik|muhakeme|akıl yürüt|akil yurut|algoritma|çözümle|cozumle|kanıtla|kanitla|sağlık|saglik|health|reasoning|logic)\b/i.test(
      normalized,
    )
  );
}

export function resolveTokenBudgetState(input: {
  remaining?: number | null;
  granted?: number | null;
}): TokenBudgetState {
  const remaining = normalizeCount(input.remaining);
  const granted = normalizeCount(input.granted);
  if (granted <= 0) {
    return "normal";
  }

  const remainingFraction = remaining / granted;
  if (remaining <= 2 || remainingFraction <= 0.03) {
    return "critical";
  }
  if (remaining <= 8 || remainingFraction <= 0.12) {
    return "conserve";
  }
  return "normal";
}

export function resolveAdaptiveInferenceBudget(input: {
  workload?: string | null;
  prompt?: string | null;
  baseMaxTokens: number;
  requestedLongFormHint?: boolean | null;
  premium?: boolean;
  qualityProfile?: QualityProfile | null;
  planCode?: string | null;
  remainingCredits?: number | null;
  grantedCredits?: number | null;
}): AdaptiveInferenceBudget {
  const workload = normalizeWorkload(input.workload);
  const baseMaxTokens = Math.max(0, Math.trunc(input.baseMaxTokens));
  const requestedLongForm =
    input.requestedLongFormHint === true ||
    isLongFormPrompt(String(input.prompt ?? ""));
  const qualityEscalated = shouldEscalateChatQuality({
    workload,
    prompt: String(input.prompt ?? ""),
    requestedLongForm,
  });
  const normalizedPlanCode = String(input.planCode ?? "").trim().toLowerCase();
  const isFreePlan = normalizedPlanCode === "free";
  const qualityProfile =
    input.qualityProfile === "pro_max"
      ? "pro_max"
      : input.qualityProfile === "solo_enhanced"
        ? "solo_enhanced"
        : input.premium
          ? "pro_max"
          : normalizedPlanCode === "solo"
            ? "solo_enhanced"
            : "free_basic";
  const isProProfile = qualityProfile === "pro_max";
  const isSoloProfile = qualityProfile === "solo_enhanced";
  const budgetState = resolveTokenBudgetState({
    remaining: input.remainingCredits,
    granted: input.grantedCredits,
  });
  const longFormCap =
    workload === "planning"
      ? isFreePlan
        ? 700
        : isProProfile
        ? 1_800
        : isSoloProfile
          ? 1_400
          : 1_100
      : workload === "mobile_chat_deep_refine"
        ? isFreePlan
          ? 540
          : isProProfile
            ? 1_900
            : isSoloProfile
              ? 1_500
              : 840
      : workload === "mobile_chat_balanced"
        ? isFreePlan
          ? 480
          : isProProfile
          ? 1_600
          : isSoloProfile
            ? 1_200
            : 700
        : workload === "document_analysis"
          ? isFreePlan
            ? 900
            : isProProfile
              ? 2_200
              : isSoloProfile
                ? 1_650
                : 1_200
        : workload === "mobile_chat_fast"
          ? isFreePlan
            ? 260
            : isProProfile
            ? 720
            : isSoloProfile
              ? 520
              : 400
          : baseMaxTokens;
  const criticalCompletionCap = isFreePlan ? 180 : isProProfile ? 320 : isSoloProfile ? 280 : 220;
  const conserveCompletionCap = isFreePlan ? 240 : isProProfile ? 680 : isSoloProfile ? 520 : 360;
  const maxCompletionTokens =
    budgetState === "critical"
      ? Math.min(baseMaxTokens, criticalCompletionCap)
      : budgetState === "conserve"
        ? Math.min(
            requestedLongForm ? Math.max(baseMaxTokens, Math.round(baseMaxTokens * 1.5)) : baseMaxTokens,
            conserveCompletionCap,
          )
        : requestedLongForm
          ? Math.max(baseMaxTokens, Math.min(longFormCap, Math.round(baseMaxTokens * 3)))
          : qualityEscalated
            ? Math.max(
                baseMaxTokens,
                Math.min(
                  workload === "mobile_chat_fast" ? 480 : workload === "mobile_chat_deep_refine" ? 980 : 760,
                  Math.round(
                    baseMaxTokens *
                      (workload === "mobile_chat_fast" ? 1.8 : workload === "mobile_chat_deep_refine" ? 1.7 : 1.55),
                  ),
                ),
              )
            : baseMaxTokens;
  const conversationTokenBudget =
    budgetState === "critical"
      ? isFreePlan
        ? 650
        : isProProfile
          ? 1_000
          : isSoloProfile
            ? 860
            : 760
      : budgetState === "conserve"
        ? isFreePlan
          ? 900
          : isProProfile
          ? 2_200
          : isSoloProfile
            ? 1_800
            : 1_200
        : requestedLongForm
          ? isFreePlan
            ? 1_400
            : isProProfile
            ? 4_200
            : isSoloProfile
              ? 3_200
              : 2_400
          : qualityEscalated
            ? isFreePlan
              ? 1_500
              : isProProfile
                ? 3_600
                : isSoloProfile
                  ? 2_900
                  : 2_100
          : isFreePlan
            ? 1_400
            : isProProfile
            ? 3_200
            : isSoloProfile
              ? 2_600
              : 1_800;

  return {
    maxCompletionTokens,
    conversationTokenBudget,
    conversationMessageBudget: isFreePlan ? 6 : isProProfile ? 14 : isSoloProfile ? 12 : 9,
    requestedLongForm,
    qualityEscalated,
    budgetState,
    budgetReason:
      budgetState === "critical"
        ? "low_balance_critical"
        : budgetState === "conserve"
          ? "low_balance_conserve"
          : requestedLongForm
            ? "long_form_expanded"
            : qualityEscalated
              ? "quality_escalated"
              : "standard",
  };
}

export function classifyTokenMeteringDepth(input: {
  userInputTokens: number;
  workload?: string | null;
}): TokenMeteringDepth {
  const userInputTokens = normalizeCount(input.userInputTokens);
  const workload = normalizeWorkload(input.workload);

  if (workload === "planning" || userInputTokens > 1_800) {
    return "planning";
  }

  if (userInputTokens > 512) {
    return "deep";
  }

  if (userInputTokens > 64) {
    return "standard";
  }

  return "short";
}

function workloadMultiplier(workload: TokenMeteringWorkload): number {
  switch (workload) {
    case "intent":
    case "fast_route":
    case "mobile_chat_fast":
      return 0.72;
    case "mobile_chat_balanced":
      return 0.92;
    case "mobile_chat_deep_refine":
      return 1.08;
    case "document_analysis":
      return 1.02;
    case "planning":
      return 1.18;
    case "desktop_handoff":
      return 0;
  }
}

function depthMultiplier(depth: TokenMeteringDepth): number {
  switch (depth) {
    case "short":
      return 0.65;
    case "standard":
      return 0.9;
    case "deep":
      return 1.08;
    case "planning":
      return 1.18;
  }
}

function surfaceMultiplier(surface: TokenMeteringSurface): number {
  return surface === "task" ? 1.25 : 1;
}

function componentWeights(surface: TokenMeteringSurface) {
  if (surface === "task") {
    return {
      userInput: 0.55,
      promptContext: 0.09,
      completion: 0.9,
    };
  }

  return {
    userInput: 0.42,
    promptContext: 0.06,
    completion: 0.72,
  };
}

export function calculateBillablePlanTokens(input: {
  surface?: TokenMeteringSurface | null;
  workload?: string | null;
  userInputTokens?: number | null;
  promptTokens?: number | null;
  completionTokens?: number | null;
}): BillableTokenUsage {
  const surface = input.surface ?? "chat";
  const workload = normalizeWorkload(input.workload);
  const userInputTokens = normalizeCount(input.userInputTokens ?? input.promptTokens ?? 0);
  const promptTokens = normalizeCount(input.promptTokens ?? userInputTokens);
  const completionTokens = normalizeCount(input.completionTokens);
  const promptContextTokens = Math.max(0, promptTokens - userInputTokens);
  const depth = classifyTokenMeteringDepth({ userInputTokens, workload });
  const weights = componentWeights(surface);
  const weightedBase =
    userInputTokens * weights.userInput +
    promptContextTokens * weights.promptContext +
    completionTokens * weights.completion;
  const weightedTokenPoints =
    weightedBase *
    workloadMultiplier(workload) *
    depthMultiplier(depth) *
    surfaceMultiplier(surface);

  const billableTokens =
    workload === "desktop_handoff"
      ? 0
      : Math.max(1, Math.ceil(weightedTokenPoints / TOKEN_METERING_UNIT_SIZE));

  return {
    billableTokens,
    meteringVersion: TOKEN_METERING_VERSION,
    surface,
    workload,
    depth,
    weightedTokenPoints: Math.round(weightedTokenPoints),
    tokenUnitSize: TOKEN_METERING_UNIT_SIZE,
    components: {
      userInputTokens,
      promptContextTokens,
      promptTokens,
      completionTokens,
    },
  };
}
