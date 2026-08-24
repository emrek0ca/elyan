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

test("continuous learning promotion stays closed while safety signals are unmeasured", () => {
  const base = {
    datasetStatus: "ready" as const,
    acceptedEventCount: 900,
    rejectedEventCount: 0,
    dedupedEventCount: 0,
    replayRatio: 25,
    validationRecordCount: 220,
    intentFamilyCount: 12,
    privacyRejectedCount: 0,
    sensitiveRejectedCount: 0,
    qualityScore: 0.9,
    weightTrainingEnabled: true,
    securityBenchmarkPassed: true,
    latestBenchmarkScore: 0.94,
    candidateEvaluationScore: 0.92,
    baselineEvaluationScore: 0.8,
    maxIntentGroupRegression: 0.01,
    manualReleaseApproved: true,
  };

  // Ölçülmemiş güvenlik sinyali "temiz" değildir: alanlar eksikken promotion
  // açılmamalı.
  const unmeasured = evaluateContinuousLearningPromotion(base);
  assert.notEqual(unmeasured.status, "promotion_ready");
  assert.equal(unmeasured.reasons.includes("canary_error_rate_not_measured"), true);
  assert.equal(unmeasured.reasons.includes("sensitive_leak_count_not_measured"), true);
  assert.equal(
    unmeasured.reasons.includes("critical_wrong_execution_count_not_measured"),
    true,
  );

  const measured = evaluateContinuousLearningPromotion({
    ...base,
    canaryErrorRate: 0.005,
    canaryTrafficPercent: 5,
    sensitiveLeakCount: 0,
    criticalWrongExecutionCount: 0,
  });
  assert.equal(measured.status, "promotion_ready");
});
