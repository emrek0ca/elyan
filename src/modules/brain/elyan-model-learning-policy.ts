import { z } from "zod";

const qualityGateStatusSchema = z.enum([
  "ready_for_queue",
  "blocked_low_signal",
  "blocked_quality_regression",
]);

const promotionGateStatusSchema = z.enum([
  "ready",
  "blocked_eval",
  "blocked_quality",
  "blocked_eval_and_quality",
]);

const inputSchema = z.object({
  groqConfigured: z.boolean(),
  costGuardEnabled: z.boolean(),
  activeSharedModelId: z.string().nullable(),
  activeUserModelId: z.string().nullable(),
  warmupJobId: z.string().nullable(),
  warmupJobStatus: z.string().nullable(),
  qualityGateStatus: qualityGateStatusSchema,
  qualityGateReasons: z.array(z.string()),
  promotionGateStatus: promotionGateStatusSchema,
  promotionGateReasons: z.array(z.string()),
  approvedCorrectionDatasetReady: z.boolean(),
  compactDatasetEligible: z.boolean().nullable(),
  evaluationScore: z.number().nullable(),
  benchmarkScore: z.number().nullable(),
  recentTimeoutCount: z.number().int().min(0),
  weightTrainingAvailable: z.boolean().default(false),
});

export type ElyanModelLearningPolicyInput = z.input<typeof inputSchema>;

export type ElyanModelLearningStage =
  | "collecting_data"
  | "queue_ready"
  | "training_active"
  | "shadow_evaluation"
  | "canary_ready"
  | "local_primary_ready"
  | "groq_retirement_ready";

export type ElyanModelLearningPolicy = {
  modelName: "Elyan";
  stage: ElyanModelLearningStage;
  groqRole: "primary" | "fallback" | "disabled_candidate" | "not_configured";
  elyanRole: "learning" | "shadow" | "canary" | "primary_candidate" | "primary_ready";
  servingStrategy:
    | "groq_primary_elyan_learning"
    | "groq_primary_elyan_shadow"
    | "groq_primary_elyan_canary"
    | "elyan_primary_groq_fallback"
    | "elyan_primary_groq_removable";
  canQueueTraining: boolean;
  canShadowEvaluate: boolean;
  canCanary: boolean;
  canPromoteLocalPrimary: boolean;
  canRetireGroq: boolean;
  nextAction:
    | "collect_more_safe_learning_events"
    | "use_behavior_memory"
    | "export_sft_ready_corrections_dataset"
    | "queue_elyan_model_refresh"
    | "wait_for_training_worker"
    | "run_shadow_evaluation"
    | "run_canary_evaluation"
    | "promote_elyan_primary_with_groq_fallback"
    | "retire_groq_after_operator_approval";
  blockers: string[];
  gates: {
    minimumEvaluationScoreForCanary: number;
    minimumEvaluationScoreForPrimary: number;
    minimumBenchmarkScoreForPrimary: number;
    minimumEvaluationScoreForGroqRetirement: number;
    minimumBenchmarkScoreForGroqRetirement: number;
  };
  costReduction: {
    costGuardEnabled: boolean;
    expectedPath: string[];
  };
};

const GATES = {
  minimumEvaluationScoreForCanary: 0.72,
  minimumEvaluationScoreForPrimary: 0.82,
  minimumBenchmarkScoreForPrimary: 0.78,
  minimumEvaluationScoreForGroqRetirement: 0.92,
  minimumBenchmarkScoreForGroqRetirement: 0.9,
} as const;

function scoreAtLeast(score: number | null, threshold: number): boolean {
  return typeof score === "number" && Number.isFinite(score) && score >= threshold;
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

export function buildElyanModelLearningPolicy(
  rawInput: ElyanModelLearningPolicyInput,
): ElyanModelLearningPolicy {
  const input = inputSchema.parse(rawInput);
  const hasReadyModel = Boolean(input.activeSharedModelId || input.activeUserModelId);
  const trainingActive =
    Boolean(input.warmupJobId) &&
    (input.warmupJobStatus === "queued" || input.warmupJobStatus === "running");
  const compactDatasetReady =
    input.approvedCorrectionDatasetReady && input.compactDatasetEligible !== false;
  const qualityReady = input.qualityGateStatus === "ready_for_queue";
  const promotionReady = input.promotionGateStatus === "ready";
  const canQueueTraining =
    input.weightTrainingAvailable && !trainingActive && compactDatasetReady && qualityReady;
  const canShadowEvaluate = hasReadyModel;
  const canCanary =
    hasReadyModel &&
    promotionReady &&
    scoreAtLeast(input.evaluationScore, GATES.minimumEvaluationScoreForCanary);
  const canPromoteLocalPrimary =
    canCanary &&
    scoreAtLeast(input.evaluationScore, GATES.minimumEvaluationScoreForPrimary) &&
    scoreAtLeast(input.benchmarkScore, GATES.minimumBenchmarkScoreForPrimary);
  const canRetireGroq =
    canPromoteLocalPrimary &&
    scoreAtLeast(input.evaluationScore, GATES.minimumEvaluationScoreForGroqRetirement) &&
    scoreAtLeast(input.benchmarkScore, GATES.minimumBenchmarkScoreForGroqRetirement) &&
    input.recentTimeoutCount === 0;

  const blockers: string[] = [];
  if (!compactDatasetReady) {
    blockers.push("sft_ready_dataset_missing_or_not_compact_eligible");
  }
  if (!input.weightTrainingAvailable) {
    blockers.push("weight_training_unavailable_behavior_memory_active");
  }
  if (!qualityReady) {
    blockers.push(...input.qualityGateReasons);
  }
  if (hasReadyModel && !promotionReady) {
    blockers.push(...input.promotionGateReasons);
  }
  if (hasReadyModel && !scoreAtLeast(input.evaluationScore, GATES.minimumEvaluationScoreForCanary)) {
    blockers.push("evaluation_score_below_canary_gate");
  }
  if (canCanary && !scoreAtLeast(input.benchmarkScore, GATES.minimumBenchmarkScoreForPrimary)) {
    blockers.push("benchmark_score_below_primary_gate");
  }
  if (canPromoteLocalPrimary && input.recentTimeoutCount > 0) {
    blockers.push("recent_timeouts_block_groq_retirement");
  }

  let stage: ElyanModelLearningStage = "collecting_data";
  let nextAction: ElyanModelLearningPolicy["nextAction"] = "collect_more_safe_learning_events";
  if (canRetireGroq) {
    stage = "groq_retirement_ready";
    nextAction = "retire_groq_after_operator_approval";
  } else if (canPromoteLocalPrimary) {
    stage = "local_primary_ready";
    nextAction = "promote_elyan_primary_with_groq_fallback";
  } else if (canCanary) {
    stage = "canary_ready";
    nextAction = "run_canary_evaluation";
  } else if (canShadowEvaluate) {
    stage = "shadow_evaluation";
    nextAction = "run_shadow_evaluation";
  } else if (trainingActive) {
    stage = "training_active";
    nextAction = "wait_for_training_worker";
  } else if (canQueueTraining) {
    stage = "queue_ready";
    nextAction = "queue_elyan_model_refresh";
  } else if (!input.weightTrainingAvailable) {
    nextAction = "use_behavior_memory";
  } else if (!input.approvedCorrectionDatasetReady) {
    nextAction = "export_sft_ready_corrections_dataset";
  }

  const servingStrategy: ElyanModelLearningPolicy["servingStrategy"] =
    stage === "groq_retirement_ready"
      ? "elyan_primary_groq_removable"
      : stage === "local_primary_ready"
        ? "elyan_primary_groq_fallback"
        : stage === "canary_ready"
          ? "groq_primary_elyan_canary"
          : stage === "shadow_evaluation"
            ? "groq_primary_elyan_shadow"
            : "groq_primary_elyan_learning";

  return {
    modelName: "Elyan",
    stage,
    groqRole: !input.groqConfigured
      ? "not_configured"
      : stage === "groq_retirement_ready"
        ? "disabled_candidate"
        : stage === "local_primary_ready"
          ? "fallback"
          : "primary",
    elyanRole:
      stage === "groq_retirement_ready"
        ? "primary_ready"
        : stage === "local_primary_ready"
          ? "primary_candidate"
          : stage === "canary_ready"
            ? "canary"
            : stage === "shadow_evaluation"
              ? "shadow"
              : "learning",
    servingStrategy,
    canQueueTraining,
    canShadowEvaluate,
    canCanary,
    canPromoteLocalPrimary,
    canRetireGroq,
    nextAction,
    blockers: unique(blockers),
    gates: { ...GATES },
    costReduction: {
      costGuardEnabled: input.costGuardEnabled,
      expectedPath: input.weightTrainingAvailable
        ? [
            "dedupe_identical_inflight_turns",
            "serve_cheap_social_turns_without_groq",
            "compile_approved_corrections_into_behavior_memory",
            "retrieve_only_relevant_behavior_lessons_per_turn",
            "train_elyan_adapter_from_sft_ready_corrections",
            "shadow_eval_elyan_against_groq",
            "canary_low_risk_workloads_to_elyan",
            "promote_elyan_primary_with_groq_fallback",
            "retire_groq_after_quality_and_latency_gates",
          ]
        : [
            "dedupe_identical_inflight_turns",
            "serve_cheap_social_turns_without_groq",
            "compile_approved_corrections_into_behavior_memory",
            "retrieve_only_relevant_behavior_lessons_per_turn",
            "keep_hosted_model_as_primary",
          ],
    },
  };
}
