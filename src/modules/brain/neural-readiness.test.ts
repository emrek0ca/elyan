import assert from "node:assert/strict";
import test from "node:test";
import { getNeuralBrainReadiness, ML_WORKER_HEARTBEAT_KEY } from "./neural-readiness.js";
import {
  QUANTUM_BENCHMARK_PRODUCER,
  QUANTUM_BENCHMARK_VERSION,
} from "./quantum-benchmark.js";

class FakeQuery<T> {
  constructor(private readonly result: T) {}

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  limit() {
    return this;
  }

  then<TResult1 = T, TResult2 = never>(
    resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.result).then(resolve, reject);
  }

  catch<TResult = never>(
    reject?: ((reason: unknown) => TResult | PromiseLike<TResult>) | null,
  ) {
    return Promise.resolve(this.result).catch(reject);
  }
}

class FakeDb {
  constructor(private readonly selects: unknown[]) {}

  select() {
    return new FakeQuery(this.selects.shift() ?? []);
  }
}

test("getNeuralBrainReadiness uses latest safe runtime quantum benchmark when training metrics are pending", async () => {
  const measuredAt = new Date().toISOString();
  const app = {
    db: new FakeDb([
      [],
      [{ count: 0 }],
      [
        {
          value: JSON.stringify({
            quantumBenchmarkVersion: QUANTUM_BENCHMARK_VERSION,
            quantumBenchmarkProducer: QUANTUM_BENCHMARK_PRODUCER,
            quantumBenchmarkRunId: "qsched-live-1",
            quantumBenchmarkMetric: "dispatch_schedule_quality",
            quantumBenchmarkDatasetFingerprint: "f".repeat(64),
            quantumBenchmarkSampleCount: 64,
            quantumBenchmarkScore: 0.87,
            quantumBenchmarkSource: "measured",
            quantumClassicalBaselineScore: 0.73,
            quantumBenchmarkMeasuredAt: measuredAt,
            quantumBenchmarkBackend: "elyan_quantum_scheduler",
          }),
          metadata: {
            signal: "quantum_task_result",
            route: "desktop_runtime",
          },
          createdAt: new Date(),
        },
      ],
      [
        {
          value: JSON.stringify({
            policy: "quantum_guided_dispatch_v1",
            source: "desktop_runtime_scheduler",
            admissionWeight: 0.09,
            policyOutcome: "backend_active_boosted",
            boostedStepCount: 2,
            responsivePolicyOutcome: "backend_active_responsive_boosted",
            quantumBenchmarkQualified: true,
            quantumBenchmarkMetric: "dispatch_schedule_quality",
            livenessScore: 0.82,
            livenessQualified: true,
            livenessGuardActive: true,
            livenessGuardTimeoutRisk: "medium",
            livenessGuardEffectiveMaxReplans: 3,
            repairAttemptCount: 2,
          }),
          metadata: {
            signal: "runtime_dispatch_policy_feedback",
            route: "desktop_runtime",
          },
          confidence: 86,
          createdAt: new Date(),
        },
      ],
    ]),
    services: {
      reliability: {
        store: {
          get: async (key: string) =>
            key === ML_WORKER_HEARTBEAT_KEY
              ? JSON.stringify({
                  timestamp: new Date().toISOString(),
                  mode: "local",
                  optionalLibraries: { qiskit: true },
                  runnerBacklog: 0,
                })
              : null,
        },
      },
    },
  };

  const readiness = await getNeuralBrainReadiness(app as never);

  assert.equal(readiness.trainingWorkerReady, true);
  assert.equal(readiness.quantumLearningReady, true);
  assert.equal(readiness.latestQuantumBenchmarkScore, 0.87);
  assert.equal(readiness.latestQuantumClassicalBaselineScore, 0.73);
  assert.equal(readiness.latestQuantumBenchmarkSource, "measured");
  assert.equal(readiness.latestQuantumAdvantageScore, 0.14);
  assert.equal(readiness.latestQuantumBenchmarkQualified, true);
  assert.equal(readiness.latestQuantumDispatchAdmissionWeight, 0.09);
  assert.equal(readiness.latestQuantumDispatchFeedbackConfidence, 86);
  assert.equal(readiness.latestQuantumDispatchPolicyOutcome, "backend_active_boosted");
  assert.equal(readiness.latestQuantumDispatchBoostedStepCount, 2);
  assert.equal(readiness.latestQuantumDispatchFeedbackQualified, true);
  assert.equal(readiness.latestQuantumDispatchLivenessScore, 0.82);
  assert.equal(readiness.latestQuantumResponsivePolicyOutcome, "backend_active_responsive_boosted");
  assert.equal(readiness.latestQuantumDispatchLivenessQualified, true);
  assert.equal(readiness.latestQuantumLivenessGuardActive, true);
  assert.equal(readiness.latestQuantumLivenessGuardTimeoutRisk, "medium");
  assert.equal(readiness.latestQuantumLivenessGuardEffectiveMaxReplans, 3);
  assert.equal(readiness.latestQuantumLivenessRepairAttemptCount, 2);
});
