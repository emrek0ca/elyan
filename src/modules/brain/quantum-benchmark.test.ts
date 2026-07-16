import assert from "node:assert/strict";
import test from "node:test";
import {
  QUANTUM_BENCHMARK_PRODUCER,
  QUANTUM_BENCHMARK_VERSION,
  readVerifiedQuantumBenchmark,
} from "./quantum-benchmark.js";

const attestation = {
  version: QUANTUM_BENCHMARK_VERSION,
  producer: QUANTUM_BENCHMARK_PRODUCER,
  runId: "run-1",
  metric: "routing_accuracy",
  datasetFingerprint: "a".repeat(64),
  sampleCount: 128,
  score: 0.81,
  source: "measured",
  classicalBaselineScore: 0.78,
  measuredAt: "2026-07-15T00:00:00.000Z",
  backend: "qiskit_aer",
};

test("readVerifiedQuantumBenchmark accepts a bound server attestation", () => {
  assert.deepEqual(
    readVerifiedQuantumBenchmark(
      { quantumBenchmarkAttestation: attestation },
      { expectedDatasetFingerprint: "a".repeat(64) },
    ),
    {
      ...attestation,
      source: "measured",
      advantageScore: 0.03,
      qualified: true,
    },
  );
});

test("readVerifiedQuantumBenchmark rejects self-declared and unbound scores", () => {
  assert.equal(readVerifiedQuantumBenchmark({ quantumBenchmarkScore: 0.99 }), null);
  assert.equal(
    readVerifiedQuantumBenchmark({
      quantumBenchmarkAttestation: { ...attestation, producer: "user" },
    }),
    null,
  );
  assert.equal(
    readVerifiedQuantumBenchmark(
      { quantumBenchmarkAttestation: attestation },
      { expectedDatasetFingerprint: "b".repeat(64) },
    ),
    null,
  );
  assert.equal(
    readVerifiedQuantumBenchmark({
      quantumBenchmarkAttestation: { ...attestation, sampleCount: 3 },
    }),
    null,
  );
  assert.equal(
    readVerifiedQuantumBenchmark({
      quantumBenchmarkAttestation: { ...attestation, score: 4.2 },
    }),
    null,
  );
});

test("readVerifiedQuantumBenchmark reads the persisted metrics contract", () => {
  assert.deepEqual(
    readVerifiedQuantumBenchmark({
      quantumBenchmarkVersion: QUANTUM_BENCHMARK_VERSION,
      quantumBenchmarkProducer: QUANTUM_BENCHMARK_PRODUCER,
      quantumBenchmarkRunId: "run-2",
      quantumBenchmarkMetric: "routing_accuracy",
      quantumBenchmarkDatasetFingerprint: "c".repeat(64),
      quantumBenchmarkSampleCount: 64,
      quantumBenchmarkScore: 0.76,
      quantumBenchmarkSource: "measured",
      quantumClassicalBaselineScore: 0.8,
      quantumBenchmarkMeasuredAt: "2026-07-15T00:00:00.000Z",
      quantumBenchmarkBackend: "qiskit_aer",
    }),
    {
      version: QUANTUM_BENCHMARK_VERSION,
      producer: QUANTUM_BENCHMARK_PRODUCER,
      runId: "run-2",
      metric: "routing_accuracy",
      datasetFingerprint: "c".repeat(64),
      sampleCount: 64,
      score: 0.76,
      source: "measured",
      classicalBaselineScore: 0.8,
      measuredAt: "2026-07-15T00:00:00.000Z",
      backend: "qiskit_aer",
      advantageScore: -0.04,
      qualified: false,
    },
  );
});
