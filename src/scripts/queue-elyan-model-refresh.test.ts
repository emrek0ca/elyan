import assert from "node:assert/strict";
import test from "node:test";
import { shapeRefreshQueuePreflight } from "./queue-elyan-model-refresh.js";

function makeProfile(overrides: Record<string, unknown> = {}) {
  return {
    benchmark: {
      latestRunAt: "2030-01-04T00:00:00.000Z",
      latestOverallScore: 0.91,
    },
    chat: {
      elyanProviderPlan: {
        logicalProvider: "elyan",
        routeReason: "shadow_eval_only",
        liveRoutingEnabled: false,
        traffic: {
          groqPercent: 100,
          elyanShadowPercent: 100,
          elyanCanaryPercent: 0,
          elyanPrimaryPercent: 0,
        },
      },
    },
    learning: {
      correctionDatasetStatus: {
        datasetId: "dataset-1",
      },
    },
    training: {
      queueEligibility: {
        status: "ready_for_queue",
        reasons: [],
      },
      trainingEligibility: {
        approvedCorrectionDatasetReady: true,
        compactDatasetEligible: true,
        compactDatasetQualityScore: 0.82,
        benchmarkBaselineReady: true,
        benchmarkScoreAttached: true,
      },
      pipeline: {
        activeJobId: null,
        activeJobStatus: null,
      },
      elyanModel: {
        stage: "queue_ready",
        elyanRole: "learning",
        groqRole: "primary",
        servingStrategy: "groq_primary_elyan_learning",
        nextAction: "queue_elyan_model_refresh",
      },
    },
    ...overrides,
  };
}

test("shapeRefreshQueuePreflight allows queue only when all training gates pass", () => {
  const preflight = shapeRefreshQueuePreflight(makeProfile() as never);

  assert.equal(preflight.canQueue, true);
  assert.equal(preflight.nextAction, "queue_elyan_model_refresh");
  assert.deepEqual(preflight.blockers, []);
  assert.equal(preflight.gates.correctionDatasetId, "dataset-1");
  assert.equal(preflight.elyanModel.stage, "queue_ready");
  assert.equal(preflight.providerPlan.routeReason, "shadow_eval_only");
});

test("shapeRefreshQueuePreflight reports blockers without exposing prompt content", () => {
  const preflight = shapeRefreshQueuePreflight(
    makeProfile({
      benchmark: {
        latestRunAt: null,
        latestOverallScore: null,
      },
      learning: {
        correctionDatasetStatus: {
          datasetId: null,
        },
      },
      training: {
        queueEligibility: {
          status: "blocked_low_signal",
          reasons: ["insufficient_safe_learning_events"],
        },
        trainingEligibility: {
          approvedCorrectionDatasetReady: false,
          compactDatasetEligible: false,
          compactDatasetQualityScore: null,
          benchmarkBaselineReady: false,
          benchmarkScoreAttached: false,
        },
        pipeline: {
          activeJobId: "job-1",
          activeJobStatus: "queued",
        },
        elyanModel: {
          stage: "collecting_data",
          elyanRole: "learning",
          groqRole: "primary",
          servingStrategy: "groq_primary_elyan_learning",
          nextAction: "export_sft_ready_corrections_dataset",
        },
      },
    }) as never,
  );

  assert.equal(preflight.canQueue, false);
  assert.deepEqual(preflight.blockers, [
    "active_shared_training_job_exists",
    "quality_gate_not_ready",
    "sft_ready_dataset_missing",
    "compact_dataset_not_eligible",
    "benchmark_baseline_missing",
  ]);
  assert.equal(JSON.stringify(preflight).includes("prompt"), false);
});
