import assert from "node:assert/strict";
import test from "node:test";
import { buildElyanModelLearningPolicy } from "./elyan-model-learning-policy.js";

test("Elyan model policy collects data until a safe SFT dataset is ready", () => {
  const policy = buildElyanModelLearningPolicy({
    groqConfigured: true,
    costGuardEnabled: true,
    activeSharedModelId: null,
    activeUserModelId: null,
    warmupJobId: null,
    warmupJobStatus: null,
    qualityGateStatus: "blocked_low_signal",
    qualityGateReasons: ["insufficient_safe_learning_events"],
    promotionGateStatus: "blocked_eval",
    promotionGateReasons: [],
    approvedCorrectionDatasetReady: false,
    compactDatasetEligible: null,
    evaluationScore: null,
    benchmarkScore: null,
    recentTimeoutCount: 0,
  });

  assert.equal(policy.stage, "collecting_data");
  assert.equal(policy.groqRole, "primary");
  assert.equal(policy.elyanRole, "learning");
  assert.equal(policy.canRetireGroq, false);
  assert.equal(policy.nextAction, "export_sft_ready_corrections_dataset");
  assert.ok(policy.blockers.includes("sft_ready_dataset_missing_or_not_compact_eligible"));
});

test("Elyan model policy queues refresh only after dataset and quality gates pass", () => {
  const policy = buildElyanModelLearningPolicy({
    groqConfigured: true,
    costGuardEnabled: true,
    activeSharedModelId: null,
    activeUserModelId: null,
    warmupJobId: null,
    warmupJobStatus: null,
    qualityGateStatus: "ready_for_queue",
    qualityGateReasons: [],
    promotionGateStatus: "blocked_eval",
    promotionGateReasons: [],
    approvedCorrectionDatasetReady: true,
    compactDatasetEligible: true,
    evaluationScore: null,
    benchmarkScore: null,
    recentTimeoutCount: 0,
  });

  assert.equal(policy.stage, "queue_ready");
  assert.equal(policy.canQueueTraining, true);
  assert.equal(policy.nextAction, "queue_elyan_model_refresh");
  assert.deepEqual(policy.blockers, []);
});

test("Elyan model policy never retires Groq before strong eval, benchmark, and latency gates", () => {
  const policy = buildElyanModelLearningPolicy({
    groqConfigured: true,
    costGuardEnabled: true,
    activeSharedModelId: "model_1",
    activeUserModelId: null,
    warmupJobId: null,
    warmupJobStatus: null,
    qualityGateStatus: "ready_for_queue",
    qualityGateReasons: [],
    promotionGateStatus: "ready",
    promotionGateReasons: [],
    approvedCorrectionDatasetReady: true,
    compactDatasetEligible: true,
    evaluationScore: 0.93,
    benchmarkScore: 0.91,
    recentTimeoutCount: 0,
  });

  assert.equal(policy.stage, "groq_retirement_ready");
  assert.equal(policy.servingStrategy, "elyan_primary_groq_removable");
  assert.equal(policy.groqRole, "disabled_candidate");
  assert.equal(policy.elyanRole, "primary_ready");
  assert.equal(policy.canRetireGroq, true);
  assert.equal(policy.nextAction, "retire_groq_after_operator_approval");
});
