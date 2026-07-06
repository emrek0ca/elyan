import assert from "node:assert/strict";
import test from "node:test";
import { evaluateContinuousLearningPromotion } from "./continuous-learning-policy.js";

test("continuous learning promotion blocks unsafe or weak datasets before training", () => {
  const decision = evaluateContinuousLearningPromotion({
    datasetStatus: "ready",
    acceptedEventCount: 12,
    rejectedEventCount: 4,
    dedupedEventCount: 1,
    replayRatio: 0,
    validationRecordCount: 1,
    privacyRejectedCount: 1,
    sensitiveRejectedCount: 1,
    qualityScore: 0.4,
    securityBenchmarkPassed: null,
    latestBenchmarkScore: null,
    candidateEvaluationScore: null,
    canaryErrorRate: null,
    rollbackSignalCount: 0,
  });

  assert.equal(decision.status, "blocked");
  assert.equal(decision.nextAction, "fix_privacy_filter");
  assert.ok(decision.reasons.includes("privacy_filter_rejected_events"));
  assert.ok(decision.reasons.includes("insufficient_safe_learning_events"));
});

test("continuous learning promotion requires training and security before canary", () => {
  const decision = evaluateContinuousLearningPromotion({
    datasetStatus: "ready",
    acceptedEventCount: 80,
    rejectedEventCount: 0,
    dedupedEventCount: 8,
    replayRatio: 20,
    validationRecordCount: 8,
    privacyRejectedCount: 0,
    sensitiveRejectedCount: 0,
    qualityScore: 0.78,
    securityBenchmarkPassed: null,
    latestBenchmarkScore: null,
    candidateEvaluationScore: null,
    canaryErrorRate: null,
    rollbackSignalCount: 0,
  });

  assert.equal(decision.status, "training_eligible");
  assert.equal(decision.nextAction, "run_candidate_training");
});

test("continuous learning promotion rolls back on canary regression", () => {
  const decision = evaluateContinuousLearningPromotion({
    datasetStatus: "ready",
    acceptedEventCount: 400,
    rejectedEventCount: 0,
    dedupedEventCount: 0,
    replayRatio: 20,
    validationRecordCount: 40,
    privacyRejectedCount: 0,
    sensitiveRejectedCount: 0,
    qualityScore: 0.9,
    securityBenchmarkPassed: true,
    latestBenchmarkScore: 0.93,
    candidateEvaluationScore: 0.91,
    canaryErrorRate: 0.08,
    rollbackSignalCount: 0,
  });

  assert.equal(decision.status, "rollback_required");
  assert.equal(decision.nextAction, "rollback_candidate");
});
