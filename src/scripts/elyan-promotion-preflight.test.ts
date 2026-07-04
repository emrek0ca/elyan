import assert from "node:assert/strict";
import test from "node:test";
import { shapeElyanPromotionPreflight } from "./elyan-promotion-preflight.js";

function makeProfile(overrides: Record<string, unknown> = {}) {
  return {
    benchmark: {
      latestRunAt: "2030-01-04T00:00:00.000Z",
      latestOverallScore: 0.82,
    },
    chat: {
      activeArtifact: {
        id: "model-1",
        scope: "shared",
        provider: "elyan-ml-worker",
        baseModel: "llama3.2",
        adapterKind: "lora",
        storageUri: "elyan://model-artifacts/model-1",
        checksum: "sha256:model-1",
        metadata: {
          prompt: "must not leak",
        },
      },
      latencySummary: {
        recentBrainTimeoutCount: 0,
      },
      elyanProviderPlan: {
        routeReason: "elyan_canary_candidate",
        liveRoutingEnabled: true,
        shadowEvaluationEnabled: true,
        canaryEnabled: true,
        primaryEnabled: false,
        transportProvider: "ollama",
        transportReady: true,
        traffic: {
          groqPercent: 99,
          elyanShadowPercent: 0,
          elyanCanaryPercent: 1,
          elyanPrimaryPercent: 0,
        },
        safety: {
          requiresOperatorPromotion: true,
          requiresGroqFallback: true,
          allowedCanaryWorkloads: ["intent", "fast_route", "mobile_chat_fast"],
        },
      },
    },
    learning: {},
    training: {
      elyanModel: {
        stage: "canary_ready",
        elyanRole: "canary",
        groqRole: "primary",
        servingStrategy: "groq_primary_elyan_canary",
        canShadowEvaluate: true,
        canCanary: true,
        canPromoteLocalPrimary: false,
        canRetireGroq: false,
        nextAction: "run_canary_evaluation",
        blockers: ["benchmark_score_below_primary_gate"],
        gates: {
          minimumEvaluationScoreForCanary: 0.72,
          minimumEvaluationScoreForPrimary: 0.82,
          minimumBenchmarkScoreForPrimary: 0.78,
          minimumEvaluationScoreForGroqRetirement: 0.92,
          minimumBenchmarkScoreForGroqRetirement: 0.9,
        },
      },
    },
    ...overrides,
  };
}

test("shapeElyanPromotionPreflight reports canary readiness without private artifact metadata", () => {
  const preflight = shapeElyanPromotionPreflight(makeProfile() as never);

  assert.equal(preflight.canChangeLiveTraffic, true);
  assert.equal(preflight.nextAction, "monitor_canary_before_primary");
  assert.equal(preflight.providerPlan.routeReason, "elyan_canary_candidate");
  assert.equal(preflight.providerPlan.traffic.elyanCanaryPercent, 1);
  assert.equal(preflight.artifact.id, "model-1");
  assert.equal(JSON.stringify(preflight).includes("must not leak"), false);
});

test("shapeElyanPromotionPreflight blocks promotion when no ready model or transport exists", () => {
  const preflight = shapeElyanPromotionPreflight(
    makeProfile({
      chat: {
        activeArtifact: null,
        latencySummary: {
          recentBrainTimeoutCount: 0,
        },
        elyanProviderPlan: {
          routeReason: "no_ready_elyan_model",
          liveRoutingEnabled: false,
          shadowEvaluationEnabled: false,
          canaryEnabled: false,
          primaryEnabled: false,
          transportProvider: "unresolved",
          transportReady: false,
          traffic: {
            groqPercent: 100,
            elyanShadowPercent: 0,
            elyanCanaryPercent: 0,
            elyanPrimaryPercent: 0,
          },
          safety: {
            requiresOperatorPromotion: true,
            requiresGroqFallback: true,
            allowedCanaryWorkloads: ["intent", "fast_route", "mobile_chat_fast"],
          },
        },
      },
      training: {
        elyanModel: {
          stage: "collecting_data",
          elyanRole: "learning",
          groqRole: "primary",
          servingStrategy: "groq_primary_elyan_learning",
          canShadowEvaluate: false,
          canCanary: false,
          canPromoteLocalPrimary: false,
          canRetireGroq: false,
          nextAction: "export_sft_ready_corrections_dataset",
          blockers: ["ready_elyan_model_missing"],
          gates: {
            minimumEvaluationScoreForCanary: 0.72,
            minimumEvaluationScoreForPrimary: 0.82,
            minimumBenchmarkScoreForPrimary: 0.78,
            minimumEvaluationScoreForGroqRetirement: 0.92,
            minimumBenchmarkScoreForGroqRetirement: 0.9,
          },
        },
      },
    }) as never,
  );

  assert.equal(preflight.canChangeLiveTraffic, false);
  assert.equal(preflight.nextAction, "resolve_promotion_blockers");
  assert.ok(preflight.blockers.includes("ready_elyan_model_missing"));
  assert.ok(preflight.blockers.includes("transport_not_ready"));
  assert.ok(preflight.blockers.includes("no_ready_elyan_model"));
});
