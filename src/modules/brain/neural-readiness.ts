import { and, desc, eq, inArray, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { learningEvents, trainingJobs } from "../../db/schema.js";
import {
  readVerifiedQuantumBenchmark,
type VerifiedQuantumBenchmark,
} from "./quantum-benchmark.js";
import {
  asRecord as readRecord,
  recordNumber as readNumber,
  recordString as readString,
} from "../../lib/record.js";

const ML_WORKER_HEARTBEAT_KEY = "elyan:ml-worker:heartbeat";
const ML_WORKER_STALE_AFTER_MS = 90_000;

function readBooleanRecord(record: Record<string, unknown> | null, key: string): Record<string, boolean> {
  const value = readRecord(record?.[key]);
  if (!value) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(value)
      .filter((entry): entry is [string, boolean] => typeof entry[1] === "boolean")
      .map(([name, ready]) => [name, ready]),
  );
}

function readJsonRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "string" || !value.trim()) {
    return readRecord(value);
  }

  try {
    return readRecord(JSON.parse(value));
  } catch {
    return null;
  }
}

type RuntimeDispatchPolicyFeedback = {
  feedbackConfidence: number | null;
  admissionWeight: number | null;
  policyOutcome:
    | "backend_active_boosted"
    | "backend_active_no_boost"
    | "runtime_observed_without_backend"
    | "benchmark_only"
    | null;
  boostedStepCount: number;
  responsivePolicyOutcome:
    | "backend_active_responsive_boosted"
    | "backend_active_no_responsive_boost"
    | "runtime_responsive_observed_without_backend"
    | "liveness_benchmark_only"
    | null;
  qualified: boolean;
  livenessScore: number | null;
  livenessQualified: boolean;
  livenessGuardActive: boolean;
  livenessGuardTimeoutRisk: "low" | "medium" | "high" | null;
  livenessGuardEffectiveMaxReplans: number | null;
  repairAttemptCount: number | null;
};

function readLatestRuntimeDispatchFeedbackRecord(
  value: unknown,
  confidence?: unknown,
): RuntimeDispatchPolicyFeedback | null {
  const record = readJsonRecord(value);
  const policy = readString(record, "policy");
  const source = readString(record, "source");
  const metric = readString(record, "quantumBenchmarkMetric");
  const admissionWeight = readNumber(record, "admissionWeight");
  const rawPolicyOutcome = readString(record, "policyOutcome");
  const policyOutcome =
    rawPolicyOutcome === "backend_active_boosted" ||
    rawPolicyOutcome === "backend_active_no_boost" ||
    rawPolicyOutcome === "runtime_observed_without_backend" ||
    rawPolicyOutcome === "benchmark_only"
      ? rawPolicyOutcome
      : null;
  const boostedStepCount = readNumber(record, "boostedStepCount");
  const rawResponsivePolicyOutcome = readString(record, "responsivePolicyOutcome");
  const responsivePolicyOutcome =
    rawResponsivePolicyOutcome === "backend_active_responsive_boosted" ||
    rawResponsivePolicyOutcome === "backend_active_no_responsive_boost" ||
    rawResponsivePolicyOutcome === "runtime_responsive_observed_without_backend" ||
    rawResponsivePolicyOutcome === "liveness_benchmark_only"
      ? rawResponsivePolicyOutcome
      : null;
  const quantumBenchmarkQualified = record?.quantumBenchmarkQualified === true;
  const livenessScore = readNumber(record, "livenessScore");
  const livenessQualified = record?.livenessQualified === true;
  const rawTimeoutRisk = readString(record, "livenessGuardTimeoutRisk");
  const livenessGuardTimeoutRisk =
    rawTimeoutRisk === "low" || rawTimeoutRisk === "medium" || rawTimeoutRisk === "high"
      ? rawTimeoutRisk
      : null;
  const livenessGuardEffectiveMaxReplans = readNumber(record, "livenessGuardEffectiveMaxReplans");
  const repairAttemptCount = readNumber(record, "repairAttemptCount");
  const feedbackConfidence =
    typeof confidence === "number" &&
    Number.isFinite(confidence) &&
    confidence >= 0 &&
    confidence <= 100
      ? confidence
      : null;

  if (
    policy !== "quantum_guided_dispatch_v1" ||
    source !== "desktop_runtime_scheduler" ||
    metric !== "dispatch_schedule_quality" ||
    boostedStepCount === null ||
    !Number.isInteger(boostedStepCount) ||
    boostedStepCount < 0 ||
    boostedStepCount > 16 ||
    (admissionWeight !== null && (admissionWeight < 0 || admissionWeight > 0.15)) ||
    (livenessScore !== null && (livenessScore < 0 || livenessScore > 1)) ||
    (livenessGuardEffectiveMaxReplans !== null &&
      (!Number.isInteger(livenessGuardEffectiveMaxReplans) ||
        livenessGuardEffectiveMaxReplans < 0 ||
        livenessGuardEffectiveMaxReplans > 3)) ||
    (repairAttemptCount !== null &&
      (!Number.isInteger(repairAttemptCount) ||
        repairAttemptCount < 0 ||
        repairAttemptCount > 16))
  ) {
    return null;
  }

  return {
    feedbackConfidence,
    admissionWeight,
    policyOutcome,
    boostedStepCount,
    responsivePolicyOutcome,
    qualified: quantumBenchmarkQualified && policyOutcome === "backend_active_boosted",
    livenessScore,
    livenessQualified:
      livenessQualified && responsivePolicyOutcome === "backend_active_responsive_boosted",
    livenessGuardActive: record?.livenessGuardActive === true,
    livenessGuardTimeoutRisk,
    livenessGuardEffectiveMaxReplans,
    repairAttemptCount,
  };
}

async function readLatestRuntimeQuantumBenchmark(
  app: FastifyInstance,
): Promise<VerifiedQuantumBenchmark | null> {
  const rows = await app.db
    .select({
      value: learningEvents.value,
      metadata: learningEvents.metadata,
      confidence: learningEvents.confidence,
      createdAt: learningEvents.createdAt,
    })
    .from(learningEvents)
    .where(
      and(
        eq(learningEvents.type, "quantum"),
        eq(learningEvents.key, "benchmark"),
        eq(learningEvents.source, "runtime"),
        eq(learningEvents.privacyLevel, "safe"),
      ),
    )
    .orderBy(desc(learningEvents.createdAt))
    .limit(5)
    .catch(() => []);

  for (const row of rows) {
    const valueRecord = readJsonRecord(row.value);
    const verified =
      readVerifiedQuantumBenchmark(valueRecord) ??
      readVerifiedQuantumBenchmark(row.metadata);
    if (verified) {
      return verified;
    }
  }

  return null;
}

async function readLatestRuntimeDispatchPolicyFeedback(
  app: FastifyInstance,
): Promise<RuntimeDispatchPolicyFeedback | null> {
  const rows = await app.db
    .select({
      value: learningEvents.value,
      metadata: learningEvents.metadata,
      confidence: learningEvents.confidence,
      createdAt: learningEvents.createdAt,
    })
    .from(learningEvents)
    .where(
      and(
        eq(learningEvents.type, "routing"),
        eq(learningEvents.key, "dispatch_policy_feedback"),
        eq(learningEvents.source, "runtime"),
        eq(learningEvents.privacyLevel, "safe"),
      ),
    )
    .orderBy(desc(learningEvents.createdAt))
    .limit(5)
    .catch(() => []);

  for (const row of rows) {
    const valueFeedback = readLatestRuntimeDispatchFeedbackRecord(row.value, row.confidence);
    if (valueFeedback) {
      return valueFeedback;
    }
    const metadataFeedback = readLatestRuntimeDispatchFeedbackRecord(row.metadata, row.confidence);
    if (metadataFeedback) {
      return metadataFeedback;
    }
  }

  return null;
}

async function readMlWorkerHeartbeat(app: FastifyInstance) {
  const raw = await app.services?.reliability?.store.get(ML_WORKER_HEARTBEAT_KEY).catch(() => null);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as unknown;
    const record = readRecord(parsed);
    const timestamp = readString(record, "timestamp");
    const updatedAt = timestamp ? Date.parse(timestamp) : Number.NaN;
    if (!Number.isFinite(updatedAt)) {
      return null;
    }
    return {
      ...record,
      ageMs: Date.now() - updatedAt,
    };
  } catch {
    return null;
  }
}

export async function getNeuralBrainReadiness(app: FastifyInstance) {
  const heartbeat = await readMlWorkerHeartbeat(app);
  const trainingWorkerReady = Boolean(heartbeat && heartbeat.ageMs <= ML_WORKER_STALE_AFTER_MS);
  const mlWorkerMode = readString(heartbeat, "mode");
  const mlWorkerLastJobAt = readString(heartbeat, "lastJobAt");
  const mlWorkerLastErrorCode = readString(heartbeat, "lastErrorCode");
  const optionalLibraries = readBooleanRecord(heartbeat, "optionalLibraries");
  const runnerBacklog = readNumber(heartbeat, "runnerBacklog");
  const latestRows = await app.db
    .select({
      metrics: trainingJobs.metrics,
      metadata: trainingJobs.metadata,
      updatedAt: trainingJobs.updatedAt,
    })
    .from(trainingJobs)
    .where(eq(trainingJobs.status, "completed"))
    .orderBy(desc(trainingJobs.updatedAt))
    .limit(1)
    .catch(() => []);
  const activeRows = await app.db
    .select({ count: sql<number>`count(*)::int` })
    .from(trainingJobs)
    .where(inArray(trainingJobs.status, ["queued", "running"]))
      .catch(() => []);
  const latestRuntimeQuantumBenchmark =
    await readLatestRuntimeQuantumBenchmark(app);
  const latestRuntimeDispatchPolicyFeedback =
    await readLatestRuntimeDispatchPolicyFeedback(app);

  const latestMetrics = readRecord(latestRows[0]?.metrics);
  const latestMetadata = readRecord(latestRows[0]?.metadata);
  const latestEvaluationScore =
    readNumber(latestMetrics, "evaluationScore") ??
    readNumber(latestMetrics, "neuralEvalScore") ??
    readNumber(latestMetadata, "neuralEvalScore");
  const latestQualityCompositeScore =
    readNumber(latestMetrics, "datasetQualityScore") ??
    readNumber(latestMetrics, "qualityCompositeScore") ??
    readNumber(latestMetadata, "datasetQualityScore") ??
    readNumber(latestMetadata, "qualityCompositeScore");
  const latestQuantumBenchmark =
    readVerifiedQuantumBenchmark(latestMetrics) ??
    readVerifiedQuantumBenchmark(latestMetadata) ??
    latestRuntimeQuantumBenchmark;
  const latestQuantumScore = latestQuantumBenchmark?.score ?? null;
  const activeTrainingJobs = Number(activeRows[0]?.count ?? 0);
  const embeddingReady = trainingWorkerReady;
  const evaluationReady = trainingWorkerReady && (latestEvaluationScore !== null || latestQualityCompositeScore !== null);
  const quantumLearningReady = trainingWorkerReady && latestQuantumScore !== null;
  const neuralReady =
    trainingWorkerReady && Math.max(latestEvaluationScore ?? 0, latestQualityCompositeScore ?? 0) >= 0.72;
  const brainBlockingReasons = [
    trainingWorkerReady ? null : "ml_worker_unavailable",
    embeddingReady ? null : "embedding_worker_unavailable",
    evaluationReady ? null : "evaluation_pending",
    quantumLearningReady ? null : "quantum_learning_pending",
  ].filter((value): value is string => Boolean(value));

  return {
    neuralReady,
    trainingWorkerReady,
    embeddingReady,
    evaluationReady,
    quantumLearningReady,
    activeTrainingJobs,
    latestEvaluationScore,
    latestQualityCompositeScore,
    latestQuantumBenchmarkScore: latestQuantumScore,
    latestQuantumClassicalBaselineScore: latestQuantumBenchmark?.classicalBaselineScore ?? null,
    latestQuantumBenchmarkSource: latestQuantumBenchmark?.source ?? null,
    latestQuantumAdvantageScore: latestQuantumBenchmark?.advantageScore ?? null,
    latestQuantumBenchmarkQualified: latestQuantumBenchmark?.qualified ?? false,
    latestQuantumDispatchAdmissionWeight:
      latestRuntimeDispatchPolicyFeedback?.admissionWeight ?? null,
    latestQuantumDispatchFeedbackConfidence:
      latestRuntimeDispatchPolicyFeedback?.feedbackConfidence ?? null,
    latestQuantumDispatchPolicyOutcome:
      latestRuntimeDispatchPolicyFeedback?.policyOutcome ?? null,
    latestQuantumDispatchBoostedStepCount:
      latestRuntimeDispatchPolicyFeedback?.boostedStepCount ?? 0,
    latestQuantumDispatchFeedbackQualified:
      latestRuntimeDispatchPolicyFeedback?.qualified ?? false,
    latestQuantumDispatchLivenessScore:
      latestRuntimeDispatchPolicyFeedback?.livenessScore ?? null,
    latestQuantumResponsivePolicyOutcome:
      latestRuntimeDispatchPolicyFeedback?.responsivePolicyOutcome ?? null,
    latestQuantumDispatchLivenessQualified:
      latestRuntimeDispatchPolicyFeedback?.livenessQualified ?? false,
    latestQuantumLivenessGuardActive:
      latestRuntimeDispatchPolicyFeedback?.livenessGuardActive ?? false,
    latestQuantumLivenessGuardTimeoutRisk:
      latestRuntimeDispatchPolicyFeedback?.livenessGuardTimeoutRisk ?? null,
    latestQuantumLivenessGuardEffectiveMaxReplans:
      latestRuntimeDispatchPolicyFeedback?.livenessGuardEffectiveMaxReplans ?? null,
    latestQuantumLivenessRepairAttemptCount:
      latestRuntimeDispatchPolicyFeedback?.repairAttemptCount ?? null,
    mlWorkerMode,
    mlWorkerLastJobAt,
    mlWorkerLastErrorCode,
    optionalLibraries,
    runnerBacklog,
    brainBlockingReasons,
  };
}

export { ML_WORKER_HEARTBEAT_KEY };
