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
      // Reasoning taban artışıyla hizalı (workloads.ts): taban 2400'ün altında
      // bir premium tavanı anlamsız — Math.max(base, …) zaten tabanı korur.
      ? 4096
      : workload === "mobile_chat_deep_refine"
        ? 1200
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
  const heavyWorkload =
    workload === "document_generate" ||
    workload === "table_generate" ||
    workload === "document_analysis";
  const fastWorkload = workload === "mobile_chat_fast";
  const maxConcurrent = heavyWorkload
    ? brainProfile.tier === "premium"
      ? 2
      : 2
    : fastWorkload
      ? brainProfile.tier === "premium"
        ? 4
        : 6
      : brainProfile.tier === "premium"
        ? 2
        : 4;
  return {
    namespace:
      brainProfile.tier === "premium"
        ? "shared-brain:premium"
        : "shared-brain:standard",
    maxConcurrent,
    ttlMs: Math.max(workloadProfile.timeoutMs + 8_000, 20_000),
    salt: `${
      String(planCode ?? "free")
        .trim()
        .toLowerCase() || "free"
    }:${workload}:${brainProfile.reasoningMultiplier}:${brainProfile.retrievalFanout}:${brainProfile.memoryFanout}`,
    retryAfterSeconds: 5,
  };
}
