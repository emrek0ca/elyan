import assert from "node:assert/strict";
import test from "node:test";
import { buildAiCostReport } from "./report-ai-cost.js";

test("buildAiCostReport summarizes provider and turn cost guard signals", () => {
  const report = buildAiCostReport({
    generatedAt: new Date("2026-07-04T00:00:00.000Z"),
    windowHours: 24,
    since: new Date("2026-07-03T00:00:00.000Z"),
    providerRows: [
      {
        provider: "groq",
        model: "llama-fast",
        workload: "mobile_chat_fast",
        route: "shared_brain",
        status: "success",
        call_count: "3",
        prompt_tokens: "300",
        completion_tokens: "90",
        total_tokens: "390",
        avg_latency_ms: "120.4",
        p95_latency_ms: "200.2",
      },
      {
        provider: "groq",
        model: "llama-fast",
        workload: "mobile_chat_fast",
        route: "shared_brain",
        status: "error",
        call_count: 1,
        prompt_tokens: 100,
        completion_tokens: 0,
        total_tokens: 100,
        avg_latency_ms: null,
        p95_latency_ms: null,
      },
    ],
    turnRows: [
      {
        workload: "mobile_chat_fast",
        turn_count: "5",
        avg_total_ms: "80.7",
        avg_first_delta_ms: "30.1",
        p95_total_ms: "150.6",
        model_call_count: "3",
        reasoning_passes: "3",
        refinement_applied_count: "0",
        rate_limited_count: "1",
        deduped_inflight_count: "1",
        cheap_social_turn_count: "2",
        zero_model_call_count: "2",
        single_model_call_count: "2",
        multi_model_pass_count: "0",
        deduped_cost_bucket_count: "1",
      },
    ],
    modelRows: [
      {
        ready_model_count: "1",
        latest_model_id: "model-1",
        latest_model_scope: "shared",
        latest_model_provider: "elyan-ml-worker",
        latest_base_model: "llama3.2",
        latest_adapter_kind: "lora",
        latest_evaluation_score: "0.86",
        latest_quality_composite_score: "0.9",
        latest_promotion_gate: "ready",
        latest_updated_at: "2026-07-03T12:00:00.000Z",
      },
    ],
    trainingRows: [
      {
        queued_jobs: "0",
        running_jobs: "0",
        latest_job_id: "job-1",
        latest_job_status: "completed",
        latest_job_kind: "lora",
        latest_job_base_model: "llama3.2",
        latest_job_updated_at: "2026-07-03T11:00:00.000Z",
      },
    ],
    datasetRows: [
      {
        sft_ready_dataset_count: "1",
        compact_eligible_dataset_count: "1",
        latest_dataset_id: "dataset-1",
        latest_dataset_version: "dataset-v1",
        latest_compaction_quality_score: "0.88",
        latest_dataset_updated_at: "2026-07-03T10:00:00.000Z",
      },
    ],
    canaryEnabled: true,
    primaryEnabled: false,
  });

  assert.equal(report.providerInvocations.totalCalls, 4);
  assert.equal(report.providerInvocations.totalTokens, 490);
  assert.equal(report.providerInvocations.errorCalls, 1);
  assert.equal(report.providerInvocations.byWorkload.mobile_chat_fast.calls, 4);
  assert.equal(report.turnMetrics.totalTurns, 5);
  assert.equal(report.turnMetrics.modelCallCount, 3);
  assert.equal(report.turnMetrics.rateLimitedCount, 1);
  assert.equal(report.turnMetrics.dedupedInflightCount, 1);
  assert.equal(report.turnMetrics.cheapSocialTurnCount, 2);
  assert.equal(report.turnMetrics.zeroModelCallCount, 2);
  assert.equal(report.elyanModel.readyModelCount, 1);
  assert.equal(report.elyanModel.latestModel.id, "model-1");
  assert.equal(report.elyanModel.latestModel.evaluationScore, 0.86);
  assert.equal(report.elyanModel.nextAction, "promote_elyan_primary_after_operator_review");
  assert.ok(report.elyanModel.blockers.includes("evaluation_score_below_groq_retirement_gate"));
  assert.ok(report.elyanModel.blockers.includes("primary_flag_disabled"));
  assert.equal(report.elyanModel.promotionFlags.canaryEnabled, true);
  assert.equal(report.elyanModel.promotionFlags.primaryEnabled, false);
  assert.equal(report.elyanModel.liveRoutingCandidate, false);
  assert.equal(
    report.elyanModel.recommendedCommand,
    "npm run brain:elyan-promotion-preflight -- --user-id=<uuid>",
  );
});

test("buildAiCostReport explains missing Elyan model learning prerequisites", () => {
  const report = buildAiCostReport({
    generatedAt: new Date("2026-07-04T00:00:00.000Z"),
    windowHours: 24,
    since: new Date("2026-07-03T00:00:00.000Z"),
    providerRows: [],
    turnRows: [],
    modelRows: [
      {
        ready_model_count: 0,
        latest_model_id: null,
        latest_model_scope: null,
        latest_model_provider: null,
        latest_base_model: null,
        latest_adapter_kind: null,
        latest_evaluation_score: null,
        latest_quality_composite_score: null,
        latest_promotion_gate: null,
        latest_updated_at: null,
      },
    ],
    trainingRows: [
      {
        queued_jobs: 0,
        running_jobs: 0,
        latest_job_id: null,
        latest_job_status: null,
        latest_job_kind: null,
        latest_job_base_model: null,
        latest_job_updated_at: null,
      },
    ],
    datasetRows: [
      {
        sft_ready_dataset_count: 0,
        compact_eligible_dataset_count: 0,
        latest_dataset_id: null,
        latest_dataset_version: null,
        latest_compaction_quality_score: null,
        latest_dataset_updated_at: null,
      },
    ],
  });

  assert.equal(report.elyanModel.nextAction, "export_sft_ready_corrections_dataset");
  assert.deepEqual(report.elyanModel.blockers, [
    "sft_ready_dataset_missing",
    "ready_elyan_model_missing",
  ]);
  assert.equal(
    report.elyanModel.recommendedCommand,
    "npm run brain:export-sft-corrections -- --write-jsonl=artifacts/brain-datasets/sft-corrections.jsonl",
  );
});

test("buildAiCostReport marks ready primary promotion as live routing candidate only behind flags", () => {
  const report = buildAiCostReport({
    generatedAt: new Date("2026-07-04T00:00:00.000Z"),
    windowHours: 24,
    since: new Date("2026-07-03T00:00:00.000Z"),
    providerRows: [],
    turnRows: [],
    modelRows: [
      {
        ready_model_count: 1,
        latest_model_id: "model-retire",
        latest_model_scope: "shared",
        latest_model_provider: "elyan-ml-worker",
        latest_base_model: "llama3.2",
        latest_adapter_kind: "lora",
        latest_evaluation_score: 0.93,
        latest_quality_composite_score: 0.95,
        latest_promotion_gate: "ready",
        latest_updated_at: "2026-07-03T12:00:00.000Z",
      },
    ],
    trainingRows: [
      {
        queued_jobs: 0,
        running_jobs: 0,
        latest_job_id: "job-retire",
        latest_job_status: "completed",
        latest_job_kind: "lora",
        latest_job_base_model: "llama3.2",
        latest_job_updated_at: "2026-07-03T11:00:00.000Z",
      },
    ],
    datasetRows: [
      {
        sft_ready_dataset_count: 1,
        compact_eligible_dataset_count: 1,
        latest_dataset_id: "dataset-retire",
        latest_dataset_version: "dataset-v1",
        latest_compaction_quality_score: 0.9,
        latest_dataset_updated_at: "2026-07-03T10:00:00.000Z",
      },
    ],
    canaryEnabled: true,
    primaryEnabled: true,
  });

  assert.equal(report.elyanModel.nextAction, "groq_retirement_candidate");
  assert.equal(report.elyanModel.liveRoutingCandidate, true);
  assert.deepEqual(report.elyanModel.blockers, []);
});
