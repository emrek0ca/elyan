export type BrainRecentFeedbackSummary = {
  thumbsUp: number;
  thumbsDown: number;
  regenerate: number;
};

export type BrainQualitySignalSummary = {
  toneSignals: number;
  humorSignals: number;
  brevitySignals: number;
  helpfulnessSignals: number;
  taskRoutingSignals: number;
};

export type BrainResponseStylePreference = {
  code: "formal" | "balanced" | "warm";
  label: string;
  source: "learned" | "default";
};

export type BrainQueueQualityGateStatus =
  | "ready_for_queue"
  | "blocked_low_signal"
  | "blocked_quality_regression";

export type BrainPromotionGateStatus =
  | "ready"
  | "blocked_eval"
  | "blocked_quality"
  | "blocked_eval_and_quality";

export type BrainQualityGateSnapshot = {
  status: BrainQueueQualityGateStatus;
  reasons: string[];
  thumbsDownRate: number;
  regenerateRate: number;
  qualityCompositeScore: number;
  thresholds: {
    minSafeLearningEvents: number;
    minTotalQualitySignals: number;
    minHelpfulnessSignals: number;
    minBrevityToneSignals: number;
    minTaskRoutingSignals: number;
    maxThumbsDownRate: number;
    maxRegenerateRate: number;
  };
};

export type BrainPromotionEligibility = {
  status: BrainPromotionGateStatus;
  reasons: string[];
  evaluationScore: number;
  qualityCompositeScore: number;
  thumbsDownRate: number;
  regenerateRate: number;
};

export const BRAIN_QUALITY_GATE_THRESHOLDS = {
  minSafeLearningEvents: 32,
  minTotalQualitySignals: 8,
  minHelpfulnessSignals: 2,
  minBrevityToneSignals: 3,
  minTaskRoutingSignals: 1,
  maxThumbsDownRate: 0.45,
  maxRegenerateRate: 0.35,
  minEvaluationScore: 0.72,
} as const;

function clampRate(value: number): number {
  return Math.max(0, Math.min(1, Number(value.toFixed(4))));
}

function normalizeCount(value: number, target: number): number {
  if (target <= 0) {
    return 0;
  }

  return clampRate(value / target);
}

function buildSentimentPenaltyAdjustedComponent(input: {
  thumbsDownRate: number;
  regenerateRate: number;
}) {
  const thumbsPenalty = clampRate(
    input.thumbsDownRate / BRAIN_QUALITY_GATE_THRESHOLDS.maxThumbsDownRate,
  );
  const regeneratePenalty = clampRate(
    input.regenerateRate / BRAIN_QUALITY_GATE_THRESHOLDS.maxRegenerateRate,
  );
  return clampRate(1 - (thumbsPenalty + regeneratePenalty) / 2);
}

export function computeFeedbackRates(input: BrainRecentFeedbackSummary) {
  const thumbsDenominator = Math.max(1, input.thumbsUp + input.thumbsDown);
  const feedbackDenominator = Math.max(
    1,
    input.thumbsUp + input.thumbsDown + input.regenerate,
  );

  return {
    thumbsDownRate: clampRate(input.thumbsDown / thumbsDenominator),
    regenerateRate: clampRate(input.regenerate / feedbackDenominator),
  };
}

export function computeQualityCompositeScore(input: {
  qualitySignals: BrainQualitySignalSummary;
  feedbackSummary: BrainRecentFeedbackSummary;
}) {
  const { thumbsDownRate, regenerateRate } = computeFeedbackRates(
    input.feedbackSummary,
  );
  const helpfulnessComponent = normalizeCount(
    input.qualitySignals.helpfulnessSignals,
    4,
  );
  const brevityToneComponent = normalizeCount(
    input.qualitySignals.brevitySignals + input.qualitySignals.toneSignals,
    6,
  );
  const routingComponent = normalizeCount(
    input.qualitySignals.taskRoutingSignals,
    3,
  );
  const sentimentPenaltyAdjustedComponent =
    buildSentimentPenaltyAdjustedComponent({
      thumbsDownRate,
      regenerateRate,
    });

  return clampRate(
    helpfulnessComponent * 0.35 +
      brevityToneComponent * 0.25 +
      routingComponent * 0.2 +
      sentimentPenaltyAdjustedComponent * 0.2,
  );
}

export function evaluateBrainQueueQualityGate(input: {
  safeLearningEvents: number;
  feedbackSummary: BrainRecentFeedbackSummary;
  qualitySignals: BrainQualitySignalSummary;
  responseStylePreference: BrainResponseStylePreference;
  routingSignals: number;
  bridgeSignals: number;
}) {
  const totalQualitySignals =
    input.qualitySignals.toneSignals +
    input.qualitySignals.humorSignals +
    input.qualitySignals.brevitySignals +
    input.qualitySignals.helpfulnessSignals +
    input.qualitySignals.taskRoutingSignals;
  const { thumbsDownRate, regenerateRate } = computeFeedbackRates(
    input.feedbackSummary,
  );
  const qualityCompositeScore = computeQualityCompositeScore({
    qualitySignals: input.qualitySignals,
    feedbackSummary: input.feedbackSummary,
  });
  const reasons: string[] = [];
  const thresholds = BRAIN_QUALITY_GATE_THRESHOLDS;

  if (input.safeLearningEvents < thresholds.minSafeLearningEvents) {
    reasons.push("insufficient_safe_learning_events");
  }
  if (totalQualitySignals < thresholds.minTotalQualitySignals) {
    reasons.push("insufficient_quality_signals");
  }
  if (input.qualitySignals.helpfulnessSignals < thresholds.minHelpfulnessSignals) {
    reasons.push("insufficient_helpfulness_signals");
  }
  if (
    input.qualitySignals.brevitySignals + input.qualitySignals.toneSignals <
    thresholds.minBrevityToneSignals
  ) {
    reasons.push("insufficient_brevity_tone_signals");
  }
  if (input.qualitySignals.taskRoutingSignals < thresholds.minTaskRoutingSignals) {
    reasons.push("insufficient_task_routing_signals");
  }
  if (input.routingSignals + input.bridgeSignals <= 0) {
    reasons.push("routing_learning_not_ready");
  }

  const lowSignalReasons = [...reasons];

  if (thumbsDownRate > thresholds.maxThumbsDownRate) {
    reasons.push("thumbs_down_rate_too_high");
  }
  if (regenerateRate > thresholds.maxRegenerateRate) {
    reasons.push("regenerate_rate_too_high");
  }

  const status: BrainQueueQualityGateStatus =
    reasons.some(
      (reason) =>
        reason === "thumbs_down_rate_too_high" ||
        reason === "regenerate_rate_too_high",
    )
      ? "blocked_quality_regression"
      : lowSignalReasons.length > 0
        ? "blocked_low_signal"
        : "ready_for_queue";

  return {
    status,
    reasons,
    thumbsDownRate,
    regenerateRate,
    qualityCompositeScore,
    thresholds,
  } satisfies BrainQualityGateSnapshot;
}

export function evaluateBrainPromotionEligibility(input: {
  evaluationScore: number;
  qualityGate: BrainQualityGateSnapshot | null;
  qualitySignals: BrainQualitySignalSummary;
}) {
  const reasons: string[] = [];
  const qualityGate = input.qualityGate;

  const evalReady =
    input.evaluationScore >= BRAIN_QUALITY_GATE_THRESHOLDS.minEvaluationScore;
  if (!evalReady) {
    reasons.push("evaluation_score_too_low");
  }

  const qualityReady =
    qualityGate != null &&
    qualityGate.status === "ready_for_queue" &&
    input.qualitySignals.helpfulnessSignals >=
      BRAIN_QUALITY_GATE_THRESHOLDS.minHelpfulnessSignals &&
    qualityGate.thumbsDownRate <=
      BRAIN_QUALITY_GATE_THRESHOLDS.maxThumbsDownRate &&
    qualityGate.regenerateRate <=
      BRAIN_QUALITY_GATE_THRESHOLDS.maxRegenerateRate;

  if (!qualityGate) {
    reasons.push("quality_gate_missing");
  } else if (qualityGate.status !== "ready_for_queue") {
    reasons.push(...qualityGate.reasons);
  }

  if (
    qualityGate &&
    qualityGate.status === "ready_for_queue" &&
    input.qualitySignals.helpfulnessSignals <
      BRAIN_QUALITY_GATE_THRESHOLDS.minHelpfulnessSignals
  ) {
    reasons.push("insufficient_helpfulness_signals");
  }

  const status: BrainPromotionGateStatus =
    evalReady && qualityReady
      ? "ready"
      : !evalReady && !qualityReady
        ? "blocked_eval_and_quality"
        : !evalReady
          ? "blocked_eval"
          : "blocked_quality";

  return {
    status,
    reasons: Array.from(new Set(reasons)),
    evaluationScore: clampRate(input.evaluationScore),
    qualityCompositeScore: qualityGate?.qualityCompositeScore ?? 0,
    thumbsDownRate: qualityGate?.thumbsDownRate ?? 1,
    regenerateRate: qualityGate?.regenerateRate ?? 1,
  } satisfies BrainPromotionEligibility;
}
