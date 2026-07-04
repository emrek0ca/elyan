import type { PlanBrainProfile } from "../billing/catalog.js";
import { getSharedBrainWorkloadProfile, type SharedBrainWorkload } from "./workloads.js";

export function getChatTimeoutMs(workload: SharedBrainWorkload | undefined): number {
  return getSharedBrainWorkloadProfile(workload).timeoutMs;
}

export function getMaxTokensForWorkload(
  workload: SharedBrainWorkload | undefined,
  brainProfile: PlanBrainProfile,
): number {
  const baseTokens = getSharedBrainWorkloadProfile(workload).maxTokens;
  if (brainProfile.tier !== "premium" && brainProfile.reasoningMultiplier < 5) {
    return baseTokens;
  }

  const scaledTokens = Math.round(baseTokens * brainProfile.maxTokenScale);
  const maxTokensByWorkload =
    workload === "planning"
      ? 900
      : workload === "mobile_chat_deep_refine"
        ? 980
        : workload === "mobile_chat_balanced"
          ? 760
          : workload === "mobile_chat_fast"
            ? 360
            : workload === "document_analysis"
              ? 900
              : baseTokens;

  return Math.max(baseTokens, Math.min(scaledTokens, maxTokensByWorkload));
}

export function getLoadSheddingOptions(
  workload: SharedBrainWorkload | undefined,
  brainProfile: PlanBrainProfile,
  planCode?: string | null,
) {
  const workloadProfile = getSharedBrainWorkloadProfile(workload);
  return {
    namespace:
      brainProfile.tier === "premium"
        ? "shared-brain:premium"
        : "shared-brain:standard",
    maxConcurrent: brainProfile.tier === "premium" ? 2 : 4,
    ttlMs: Math.max(workloadProfile.timeoutMs + 8_000, 20_000),
    salt: `${
      String(planCode ?? "free")
        .trim()
        .toLowerCase() || "free"
    }:${workload}:${brainProfile.reasoningMultiplier}:${brainProfile.retrievalFanout}:${brainProfile.memoryFanout}`,
    retryAfterSeconds: 5,
  };
}
