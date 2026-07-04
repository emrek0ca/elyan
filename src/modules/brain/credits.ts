import {
  calculateBillablePlanTokens,
  type TokenMeteringSurface,
} from "../billing/token-metering.js";
import type { SharedBrainWorkload } from "./workloads.js";

export function calculateBillableAiCredits(input: {
  promptTokens: number;
  completionTokens: number;
  workload?: SharedBrainWorkload;
  userInputTokens?: number;
  surface?: TokenMeteringSurface;
}): number {
  return calculateBillablePlanTokens({
    surface: input.surface ?? "chat",
    workload: input.workload,
    userInputTokens: input.userInputTokens ?? input.promptTokens,
    promptTokens: input.promptTokens,
    completionTokens: input.completionTokens,
  }).billableTokens;
}
