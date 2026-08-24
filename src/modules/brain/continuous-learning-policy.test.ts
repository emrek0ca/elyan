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
    intentFamilyCount: 1,
    privacyRejectedCount: 1,
    sensitiveRejectedCount: 1,
    sensitiveLeakCount: 0,
    qualityScore: 0.4,
    weightTrainingEnabled: false,
    securityBenchmarkPassed: null,
    latestBenchmarkScore: null,
    candidateEvaluationScore: null,
    canaryErrorRate: null,
    rollbackSignalCount: 0,
  });

  assert.equal(decision.status, "blocked");
  assert.equal(decision.nextAction, "add_replay_samples");
  assert.ok(decision.reasons.includes("insufficient_safe_learning_events"));
});

test("continuous learning promotion requires training and security before canary", () => {
  const decision = evaluateContinuousLearningPromotion({
    datasetStatus: "ready",
    acceptedEventCount: 500,
    rejectedEventCount: 0,
    dedupedEventCount: 8,
    replayRatio: 20,
    validationRecordCount: 100,
    intentFamilyCount: 10,
    privacyRejectedCount: 0,
    sensitiveRejectedCount: 0,
    sensitiveLeakCount: 0,
    qualityScore: 0.82,
    weightTrainingEnabled: true,
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
    acceptedEventCount: 500,
    rejectedEventCount: 0,
    dedupedEventCount: 0,
    replayRatio: 20,
    validationRecordCount: 100,
    intentFamilyCount: 10,
    privacyRejectedCount: 0,
    sensitiveRejectedCount: 0,
    sensitiveLeakCount: 0,
    qualityScore: 0.9,
    weightTrainingEnabled: true,
    securityBenchmarkPassed: true,
    latestBenchmarkScore: 0.93,
    candidateEvaluationScore: 0.91,
    canaryErrorRate: 0.08,
    rollbackSignalCount: 0,
  });

  assert.equal(decision.status, "rollback_required");
  assert.equal(decision.nextAction, "rollback_candidate");
});

test("continuous learning promotion requires measured uplift and explicit release approval", () => {
  const base = {
    datasetStatus: "ready" as const,
    acceptedEventCount: 500,
    rejectedEventCount: 0,
    dedupedEventCount: 0,
    replayRatio: 20,
    validationRecordCount: 100,
    intentFamilyCount: 10,
    privacyRejectedCount: 0,
    sensitiveRejectedCount: 0,
    sensitiveLeakCount: 0,
    qualityScore: 0.9,
    weightTrainingEnabled: true,
    securityBenchmarkPassed: true,
    latestBenchmarkScore: 0.93,
    candidateEvaluationScore: 0.9,
    baselineEvaluationScore: 0.84,
    maxIntentGroupRegression: 0.01,
    canaryErrorRate: 0.01,
    canaryTrafficPercent: 10,
    rollbackSignalCount: 0,
    criticalWrongExecutionCount: 0,
  };
  const awaitingRelease = evaluateContinuousLearningPromotion(base);
  assert.equal(awaitingRelease.status, "canary_ready");
  assert.ok(awaitingRelease.reasons.includes("explicit_release_approval_required"));

  const approved = evaluateContinuousLearningPromotion({
    ...base,
    manualReleaseApproved: true,
  });
  assert.equal(approved.status, "promotion_ready");
});
