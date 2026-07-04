import assert from "node:assert/strict";
import test from "node:test";
import { buildElyanModelLearningPolicy } from "./elyan-model-learning-policy.js";
import { buildElyanModelProviderPlan } from "./elyan-model-provider-plan.js";

const readyArtifact = {
  id: "model_1",
  scope: "shared" as const,
  provider: "elyan-ml-worker",
  baseModel: "llama3.2",
  adapterKind: "lora",
  storageUri: "elyan://model-artifacts/model_1",
  checksum: "sha256:model_1",
  metadata: {
    servingProvider: "ollama",
  },
};

test("Elyan provider plan keeps Groq at 100 percent when no trained artifact exists", () => {
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

  const plan = buildElyanModelProviderPlan({
    policy,
    artifact: null,
    workload: "mobile_chat_fast",
    runtimeProvider: "ollama",
    runtimeReady: true,
    canaryEnabled: true,
    primaryEnabled: true,
  });

  assert.equal(plan.liveRoutingEnabled, false);
  assert.equal(plan.routeReason, "no_ready_elyan_model");
  assert.equal(plan.traffic.groqPercent, 100);
  assert.equal(plan.traffic.elyanCanaryPercent, 0);
});

test("Elyan provider plan shadows a ready model without changing live routing", () => {
  const policy = buildElyanModelLearningPolicy({
    groqConfigured: true,
    costGuardEnabled: true,
    activeSharedModelId: "model_1",
    activeUserModelId: null,
    warmupJobId: null,
    warmupJobStatus: null,
    qualityGateStatus: "ready_for_queue",
    qualityGateReasons: [],
    promotionGateStatus: "blocked_eval",
    promotionGateReasons: ["evaluation_score_too_low"],
    approvedCorrectionDatasetReady: true,
    compactDatasetEligible: true,
    evaluationScore: 0.5,
    benchmarkScore: 0.9,
    recentTimeoutCount: 0,
  });

  const plan = buildElyanModelProviderPlan({
    policy,
    artifact: readyArtifact,
    workload: "mobile_chat_fast",
    runtimeProvider: "ollama",
    runtimeReady: true,
    canaryEnabled: true,
    primaryEnabled: true,
  });

  assert.equal(plan.stage, "shadow_evaluation");
  assert.equal(plan.transportProvider, "ollama");
  assert.equal(plan.liveRoutingEnabled, false);
  assert.equal(plan.shadowEvaluationEnabled, true);
  assert.equal(plan.traffic.groqPercent, 100);
  assert.equal(plan.traffic.elyanShadowPercent, 100);
});

test("Elyan provider plan requires canary flag and low-risk workload before live canary", () => {
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
    evaluationScore: 0.75,
    benchmarkScore: 0.7,
    recentTimeoutCount: 0,
  });

  const disabled = buildElyanModelProviderPlan({
    policy,
    artifact: readyArtifact,
    workload: "mobile_chat_fast",
    runtimeProvider: "ollama",
    runtimeReady: true,
    canaryEnabled: false,
    primaryEnabled: false,
  });
  const riskyWorkload = buildElyanModelProviderPlan({
    policy,
    artifact: readyArtifact,
    workload: "planning",
    runtimeProvider: "ollama",
    runtimeReady: true,
    canaryEnabled: true,
    primaryEnabled: false,
  });
  const enabled = buildElyanModelProviderPlan({
    policy,
    artifact: readyArtifact,
    workload: "mobile_chat_fast",
    runtimeProvider: "ollama",
    runtimeReady: true,
    canaryEnabled: true,
    primaryEnabled: false,
  });

  assert.equal(disabled.liveRoutingEnabled, false);
  assert.equal(disabled.routeReason, "canary_disabled");
  assert.equal(riskyWorkload.liveRoutingEnabled, false);
  assert.equal(riskyWorkload.routeReason, "workload_not_canary_safe");
  assert.equal(enabled.liveRoutingEnabled, true);
  assert.equal(enabled.routeReason, "elyan_canary_candidate");
  assert.equal(enabled.traffic.elyanCanaryPercent, 1);
});

test("Elyan provider plan promotes primary only when the primary flag is enabled", () => {
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
    evaluationScore: 0.86,
    benchmarkScore: 0.81,
    recentTimeoutCount: 0,
  });

  const disabled = buildElyanModelProviderPlan({
    policy,
    artifact: readyArtifact,
    workload: "mobile_chat_balanced",
    runtimeProvider: "ollama",
    runtimeReady: true,
    canaryEnabled: true,
    primaryEnabled: false,
  });
  const enabled = buildElyanModelProviderPlan({
    policy,
    artifact: readyArtifact,
    workload: "mobile_chat_balanced",
    runtimeProvider: "ollama",
    runtimeReady: true,
    canaryEnabled: true,
    primaryEnabled: true,
  });

  assert.equal(disabled.liveRoutingEnabled, false);
  assert.equal(disabled.routeReason, "primary_disabled");
  assert.equal(enabled.liveRoutingEnabled, true);
  assert.equal(enabled.routeReason, "elyan_primary_candidate");
  assert.equal(enabled.traffic.elyanPrimaryPercent, 80);
  assert.equal(enabled.traffic.groqPercent, 20);
});
