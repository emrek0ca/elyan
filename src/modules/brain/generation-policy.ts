import {
  isExplicitChartRequest,
  isExplicitMathOrLatexRequest,
  isExplicitMathSurface3DRequest,
  isExplicitTableRequest,
} from "../../core/understanding/structured-output-policy.js";
import { hasMathReasoningSignal, isSocialChatPrompt } from "./chat-heuristics.js";
import type { SharedBrainWorkload } from "./workloads.js";

/**
 * Reasoning depth dial for gpt-oss models. HARD analytical work gets "high"
 * so answers are thorough instead of shallow. The fast mobile lane stays low
 * so its first visible tokens are not delayed by an unnecessary hidden turn;
 * balanced/deep workloads retain their deeper reasoning budget.
 */
export function resolveReasoningEffort(
  workload: SharedBrainWorkload | undefined,
  reasoningMode: string | undefined,
): "low" | "medium" | "high" {
  // The route classifier is an internal control-plane call. It must never
  // inherit a user-turn reasoning mode and spend a hidden model pass before
  // the actual chat can even be dispatched.
  // AÇIK "deep" işareti hızlı şeridi de yener. Kısa devre önce geldiği için
  // anlama katmanı turu derin olarak işaretlese bile efor low kalıyordu;
  // yani "bunu iyice düşün" sinyali sessizce yok sayılıyordu.
  if (reasoningMode === "deep") {
    return "high";
  }
  // Rota sınıflandırıcı bir iç kontrol-düzlemi çağrısıdır ve kullanıcı turunun
  // reasoning modunu miras almamalı.
  if (workload === "fast_route" || workload === "mobile_chat_fast") {
    return "low";
  }
  if (
    workload === "planning" ||
    workload === "document_generate" ||
    workload === "document_analysis" ||
    workload === "mobile_chat_deep_refine" ||
    workload === "mobile_chat_balanced"
  ) {
    return "high";
  }
  if (reasoningMode === "balanced") {
    return "medium";
  }
  if (workload === "vision_reasoning" || workload === "image_analyze") {
    return "low";
  }
  return "low";
}

export function isReasoningChannelModel(model: string): boolean {
  const normalized = model.toLowerCase();
  return normalized.includes("gpt-oss");
}

export const ANALYTICAL_GENERATION_TEMPERATURE = 0.25;
export const BALANCED_GENERATION_TEMPERATURE = 0.4;
// 0.6 → 0.65: sohbet sesi daha canlı/çeşitli; affect dial'in üst sınırı (0.72)
// hâlâ tavan, analitik taban (0.25) etkilenmez.
export const CONVERSATIONAL_GENERATION_TEMPERATURE = 0.65;

/**
 * Persistent affective read (from dialogue-state's deriveAffectiveStance) used
 * to modulate expressive variety. Optional: absent stance keeps legacy behavior.
 */
export type GenerationAffect = {
  mood: "positive" | "frustrated" | "anxious" | "sad" | "tired" | "curious" | "neutral";
  rapport: number;
  volatility: number;
};

export function resolveGenerationTemperature(input: {
  workload: SharedBrainWorkload | undefined;
  prompt: string;
  affect?: GenerationAffect | null;
}): number {
  const workload = input.workload;
  if (
    workload === "planning" ||
    workload === "document_generate" ||
    workload === "document_analysis" ||
    workload === "table_generate" ||
    workload === "image_analyze" ||
    workload === "vision_reasoning" ||
    workload === "mobile_chat_deep_refine"
  ) {
    return ANALYTICAL_GENERATION_TEMPERATURE;
  }
  if (
    hasMathReasoningSignal(input.prompt) ||
    isExplicitMathOrLatexRequest(input.prompt) ||
    isExplicitChartRequest(input.prompt) ||
    isExplicitTableRequest(input.prompt) ||
    isExplicitMathSurface3DRequest(input.prompt)
  ) {
    return ANALYTICAL_GENERATION_TEMPERATURE;
  }
  let base: number;
  if (isSocialChatPrompt(input.prompt)) {
    base = CONVERSATIONAL_GENERATION_TEMPERATURE;
  } else if (workload === "mobile_chat_fast" || workload === "fast_route") {
    base = CONVERSATIONAL_GENERATION_TEMPERATURE;
  } else {
    base = BALANCED_GENERATION_TEMPERATURE;
  }
  return applyAffectToTemperature(base, input.affect);
}

/**
 * Nudge expressive variety by the persistent affective stance — a behavioral
 * dial, not a prompt line. Established rapport + a positive/curious read warms
 * the voice (more alive); distress or an unstable mood steadies it (calmer, less
 * erratic). Bounded so it never overrides the analytical floor.
 */
function applyAffectToTemperature(
  base: number,
  affect: GenerationAffect | null | undefined,
): number {
  if (!affect) return base;
  let delta = 0;
  if (affect.mood === "positive" || affect.mood === "curious") delta += 0.08;
  if (affect.mood === "frustrated" || affect.mood === "anxious" || affect.mood === "sad") {
    delta -= 0.1;
  }
  if (affect.rapport >= 0.55) delta += 0.06;
  if (affect.volatility >= 0.6) delta -= 0.08;
  const adjusted = base + delta;
  return Math.max(0.3, Math.min(0.72, Math.round(adjusted * 100) / 100));
}
