import { z } from "zod";

const inputSchema = z.object({
  datasetStatus: z.enum(["draft", "ready", "failed"]),
  acceptedEventCount: z.number().int().min(0),
  rejectedEventCount: z.number().int().min(0),
  dedupedEventCount: z.number().int().min(0),
  replayRatio: z.number().int().min(0).max(100),
  validationRecordCount: z.number().int().min(0),
  privacyRejectedCount: z.number().int().min(0),
  sensitiveRejectedCount: z.number().int().min(0),
  qualityScore: z.number().min(0).max(1),
  securityBenchmarkPassed: z.boolean().nullable().default(null),
  latestBenchmarkScore: z.number().min(0).max(1).nullable().default(null),
  candidateEvaluationScore: z.number().min(0).max(1).nullable().default(null),
  canaryErrorRate: z.number().min(0).max(1).nullable().default(null),
  rollbackSignalCount: z.number().int().min(0).default(0),
});

export type ContinuousLearningPromotionInput = z.input<typeof inputSchema>;

export type ContinuousLearningPromotionDecision = {
  status:
    | "blocked"
    | "dataset_ready"
    | "training_eligible"
    | "shadow_ready"
    | "canary_ready"
    | "promotion_ready"
    | "rollback_required";
  nextAction:
    | "collect_more_events"
    | "fix_privacy_filter"
    | "add_replay_samples"
    | "run_candidate_training"
    | "run_security_benchmarks"
    | "run_shadow_evaluation"
    | "run_canary"
    | "promote_candidate"
    | "rollback_candidate";
  reasons: string[];
  gates: {
    minAcceptedEvents: number;
    minReplayRatio: number;
    minValidationRecords: number;
    minQualityScore: number;
    minBenchmarkScoreForCanary: number;
    minEvaluationScoreForCanary: number;
    minBenchmarkScoreForPromotion: number;
    minEvaluationScoreForPromotion: number;
    maxCanaryErrorRate: number;
  };
};

const GATES = {
  minAcceptedEvents: 32,
  minReplayRatio: 10,
  minValidationRecords: 3,
  minQualityScore: 0.62,
  minBenchmarkScoreForCanary: 0.78,
  minEvaluationScoreForCanary: 0.72,
  minBenchmarkScoreForPromotion: 0.9,
  minEvaluationScoreForPromotion: 0.88,
  maxCanaryErrorRate: 0.02,
} as const;

function scoreAtLeast(score: number | null, threshold: number): boolean {
  return typeof score === "number" && Number.isFinite(score) && score >= threshold;
}

export function evaluateContinuousLearningPromotion(
  rawInput: ContinuousLearningPromotionInput,
): ContinuousLearningPromotionDecision {
  const input = inputSchema.parse(rawInput);
  const reasons: string[] = [];

  if (input.rollbackSignalCount > 0) {
    return {
      status: "rollback_required",
      nextAction: "rollback_candidate",
      reasons: ["rollback_signal_detected"],
      gates: GATES,
    };
  }

  if (
    typeof input.canaryErrorRate === "number" &&
    input.canaryErrorRate > GATES.maxCanaryErrorRate
  ) {
    return {
      status: "rollback_required",
      nextAction: "rollback_candidate",
      reasons: ["canary_error_rate_too_high"],
      gates: GATES,
    };
  }

  if (input.datasetStatus === "failed") {
    reasons.push("dataset_failed");
  }
  if (input.privacyRejectedCount > 0 || input.sensitiveRejectedCount > 0) {
    reasons.push("privacy_filter_rejected_events");
  }
  if (input.acceptedEventCount < GATES.minAcceptedEvents) {
    reasons.push("insufficient_safe_learning_events");
  }
  if (input.replayRatio < GATES.minReplayRatio) {
    reasons.push("replay_ratio_too_low");
  }
  if (input.validationRecordCount < GATES.minValidationRecords) {
    reasons.push("validation_split_too_small");
  }
  if (input.qualityScore < GATES.minQualityScore) {
    reasons.push("dataset_quality_too_low");
  }

  if (reasons.length > 0 || input.datasetStatus !== "ready") {
    return {
      status: "blocked",
      nextAction: reasons.includes("privacy_filter_rejected_events")
        ? "fix_privacy_filter"
        : reasons.includes("replay_ratio_too_low")
          ? "add_replay_samples"
          : "collect_more_events",
      reasons: reasons.length > 0 ? reasons : ["dataset_not_ready"],
      gates: GATES,
    };
  }

  if (input.securityBenchmarkPassed !== true) {
    return {
      status: "training_eligible",
      nextAction: "run_candidate_training",
      reasons: ["candidate_training_required_before_security_benchmarks"],
      gates: GATES,
    };
  }

  if (
    !scoreAtLeast(input.candidateEvaluationScore, GATES.minEvaluationScoreForCanary) ||
    !scoreAtLeast(input.latestBenchmarkScore, GATES.minBenchmarkScoreForCanary)
  ) {
    return {
      status: "shadow_ready",
      nextAction: "run_shadow_evaluation",
      reasons: ["candidate_not_ready_for_canary"],
      gates: GATES,
    };
  }

  if (
    !scoreAtLeast(input.candidateEvaluationScore, GATES.minEvaluationScoreForPromotion) ||
    !scoreAtLeast(input.latestBenchmarkScore, GATES.minBenchmarkScoreForPromotion)
  ) {
    return {
      status: "canary_ready",
      nextAction: "run_canary",
      reasons: ["candidate_not_ready_for_full_promotion"],
      gates: GATES,
    };
  }

  return {
    status: "promotion_ready",
    nextAction: "promote_candidate",
    reasons: [],
    gates: GATES,
  };
}
