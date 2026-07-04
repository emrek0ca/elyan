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
 * so answers are thorough instead of shallow. Moderate thinking workloads get
 * "medium". Everything else stays "low" to protect latency.
 */
export function resolveReasoningEffort(
  workload: SharedBrainWorkload | undefined,
  reasoningMode: string | undefined,
): "low" | "medium" | "high" {
  if (
    reasoningMode === "deep" ||
    workload === "planning" ||
    workload === "document_generate" ||
    workload === "document_analysis" ||
    workload === "mobile_chat_deep_refine"
  ) {
    return "high";
  }
  if (
    workload === "mobile_chat_balanced" ||
    workload === "vision_reasoning" ||
    workload === "image_analyze"
  ) {
    return "medium";
  }
  return "low";
}

export function isReasoningChannelModel(model: string): boolean {
  const normalized = model.toLowerCase();
  return normalized.includes("gpt-oss");
}

export const ANALYTICAL_GENERATION_TEMPERATURE = 0.25;
export const BALANCED_GENERATION_TEMPERATURE = 0.4;
export const CONVERSATIONAL_GENERATION_TEMPERATURE = 0.6;

export function resolveGenerationTemperature(input: {
  workload: SharedBrainWorkload | undefined;
  prompt: string;
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
  if (isSocialChatPrompt(input.prompt)) {
    return CONVERSATIONAL_GENERATION_TEMPERATURE;
  }
  if (workload === "mobile_chat_fast" || workload === "fast_route") {
    return CONVERSATIONAL_GENERATION_TEMPERATURE;
  }
  return BALANCED_GENERATION_TEMPERATURE;
}
