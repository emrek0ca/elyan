import {
  asRecord as readRecord,
  recordNumber as readNumber,
  recordString as readString,
} from "../../lib/record.js";
export const QUANTUM_BENCHMARK_VERSION = "elyan_quantum_benchmark_v1";
export const QUANTUM_BENCHMARK_PRODUCER = "elyan_quantum_benchmark_worker";

export type VerifiedQuantumBenchmark = {
  version: typeof QUANTUM_BENCHMARK_VERSION;
  producer: typeof QUANTUM_BENCHMARK_PRODUCER;
  runId: string;
  metric: string;
  datasetFingerprint: string;
  sampleCount: number;
  score: number;
  source: "measured";
  classicalBaselineScore: number;
  measuredAt: string;
  backend: string;
  advantageScore: number;
  qualified: boolean;
};

function isValidTimestamp(value: string): boolean {
  return Number.isFinite(Date.parse(value));
}

/**
 * Parses the server-controlled attestation or its persisted metrics form.
 * Callers must not pass request config or user-authored dataset metadata.
 */
export function readVerifiedQuantumBenchmark(
  value: unknown,
  options: { expectedDatasetFingerprint?: string } = {},
): VerifiedQuantumBenchmark | null {
  const record = readRecord(value);
  const nested = readRecord(record?.quantumBenchmarkAttestation);
  const candidate = nested ?? record;
  const flattened = nested === null;
  const readField = (nestedKey: string, flatKey: string) =>
    readString(candidate, flattened ? flatKey : nestedKey);
  const readNumericField = (nestedKey: string, flatKey: string) =>
    readNumber(candidate, flattened ? flatKey : nestedKey);

  const version = readField("version", "quantumBenchmarkVersion");
  const producer = readField("producer", "quantumBenchmarkProducer");
  const runId = readField("runId", "quantumBenchmarkRunId");
  const metric = readField("metric", "quantumBenchmarkMetric");
  const datasetFingerprint = readField("datasetFingerprint", "quantumBenchmarkDatasetFingerprint");
  const sampleCount = readNumericField("sampleCount", "quantumBenchmarkSampleCount");
  const score = readNumericField("score", "quantumBenchmarkScore");
  const source = readField("source", "quantumBenchmarkSource");
  const classicalBaselineScore = readNumericField(
    "classicalBaselineScore",
    "quantumClassicalBaselineScore",
  );
  const measuredAt = readField("measuredAt", "quantumBenchmarkMeasuredAt");
  const backend = readField("backend", "quantumBenchmarkBackend");

  if (
    version !== QUANTUM_BENCHMARK_VERSION ||
    producer !== QUANTUM_BENCHMARK_PRODUCER ||
    !runId ||
    !metric ||
    !datasetFingerprint ||
    (options.expectedDatasetFingerprint !== undefined &&
      datasetFingerprint !== options.expectedDatasetFingerprint) ||
    sampleCount === null ||
    !Number.isInteger(sampleCount) ||
    sampleCount < 32 ||
    score === null ||
    score < 0 ||
    score > 1 ||
    source !== "measured" ||
    classicalBaselineScore === null ||
    classicalBaselineScore < 0 ||
    classicalBaselineScore > 1 ||
    !measuredAt ||
    !isValidTimestamp(measuredAt) ||
    !backend
  ) {
    return null;
  }

  const normalizedScore = Number(score.toFixed(4));
  const normalizedBaseline = Number(classicalBaselineScore.toFixed(4));
  const advantageScore = Number((normalizedScore - normalizedBaseline).toFixed(4));
  return {
    version: QUANTUM_BENCHMARK_VERSION,
    producer: QUANTUM_BENCHMARK_PRODUCER,
    runId,
    metric,
    datasetFingerprint,
    sampleCount,
    score: normalizedScore,
    source: "measured",
    classicalBaselineScore: normalizedBaseline,
    measuredAt,
    backend,
    advantageScore,
    qualified: advantageScore > 0,
  };
}
