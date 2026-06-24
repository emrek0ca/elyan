import { desc, eq, inArray, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { trainingJobs } from "../../db/schema.js";

const ML_WORKER_HEARTBEAT_KEY = "elyan:ml-worker:heartbeat";
const ML_WORKER_STALE_AFTER_MS = 90_000;

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readNumber(record: Record<string, unknown> | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

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
  const latestQuantumScore =
    readNumber(latestMetrics, "quantumBenchmarkScore") ??
    readNumber(latestMetadata, "quantumBenchmarkScore");
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
    mlWorkerMode,
    mlWorkerLastJobAt,
    mlWorkerLastErrorCode,
    optionalLibraries,
    runnerBacklog,
    brainBlockingReasons,
  };
}

export { ML_WORKER_HEARTBEAT_KEY };
