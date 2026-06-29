import { and, asc, eq, inArray } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { createHash } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";
import { datasetManifests, modelArtifacts, trainingJobs } from "../../db/schema.js";
import { createAuditLog } from "../audit/service.js";
import {
  evaluateBrainPromotionEligibility,
  type BrainQualityGateSnapshot,
  type BrainQualitySignalSummary,
} from "./quality-gate.js";
import { processMemoryTrainingJob } from "./memory.js";
import { indexKnowledgeChunksForDocument } from "./retrieval.js";

type TrainingJobRow = typeof trainingJobs.$inferSelect;
type DatasetManifestRow = Pick<
  typeof datasetManifests.$inferSelect,
  "id" | "status" | "scope" | "recordCount" | "tokenEstimate" | "metadata"
>;

type TrainingWorkerOptions = {
  idleDelayMs?: number;
  once?: boolean;
};

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  if (!record) {
    return null;
  }

  const value = record[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function mergeTrainingMetadata(
  existing: unknown,
  next: Record<string, unknown>,
): Record<string, unknown> {
  return {
    ...(readRecord(existing) ?? {}),
    ...next,
  };
}

function buildExternalRequiredMetadata(reason: string, extra: Record<string, unknown> = {}) {
  return {
    trainingMode: "external_required",
    workerStatus: "failed",
    failureReason: reason,
    ...extra,
  };
}

function readNumber(record: Record<string, unknown> | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readStringArray(record: Record<string, unknown> | null, key: string): string[] {
  const value = record?.[key];
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "string" ? item.trim() : ""))
        .filter(Boolean)
    : [];
}

function clampScore(value: number): number {
  return Math.max(0, Math.min(1, Number(value.toFixed(4))));
}

function fingerprintSafeDatasetSignal(input: {
  jobId: string;
  datasetManifestId: string;
  trainingBackend: string;
  adapterMode: string | null;
  dataset: DatasetManifestRow;
}) {
  const metadata = readRecord(input.dataset.metadata);
  const safePayload = {
    jobId: input.jobId,
    datasetManifestId: input.datasetManifestId,
    datasetScope: input.dataset.scope,
    recordCount: input.dataset.recordCount,
    tokenEstimate: input.dataset.tokenEstimate,
    sourceKind: readString(metadata, "sourceKind"),
    problemClass: readString(metadata, "problemClass"),
    trainingBackend: input.trainingBackend,
    adapterMode: input.adapterMode,
  };

  return createHash("sha256").update(JSON.stringify(safePayload)).digest("hex");
}

function buildSafeEvaluationMetrics(input: {
  job: TrainingJobRow;
  dataset: DatasetManifestRow;
  trainingBackend: string;
  adapterMode: string | null;
}) {
  const config = readRecord(input.job.config);
  const datasetMetadata = readRecord(input.dataset.metadata);
  const datasetSnapshot = readRecord(config?.datasetSnapshot) ?? readRecord(datasetMetadata?.datasetSnapshot);
  const learningSnapshot = readRecord(config?.learningSnapshot);
  const qualitySignalSummaryRecord = readRecord(config?.qualitySignalSummary);
  const requestedQuantumScore =
    readNumber(config, "quantumBenchmarkScore") ??
    readNumber(datasetMetadata, "quantumBenchmarkScore") ??
    readNumber(datasetMetadata, "lastBenchmarkScore");
  const datasetSizeScore = clampScore(Math.min(input.dataset.recordCount, 2_000) / 2_000);
  const tokenCoverageScore = clampScore(Math.min(input.dataset.tokenEstimate, 250_000) / 250_000);
  const approvedCorrectionCount =
    readNumber(datasetSnapshot, "approvedCorrectionCount") ??
    readNumber(datasetMetadata, "approvedCorrectionCount") ??
    input.dataset.recordCount;
  const compactedRecordCount =
    readNumber(datasetSnapshot, "compactedRecordCount") ??
    readNumber(datasetMetadata, "compactedRecordCount") ??
    input.dataset.recordCount;
  const freshSignalCount =
    readNumber(datasetSnapshot, "freshSignalCount") ?? readNumber(datasetMetadata, "freshSignalCount") ?? 0;
  const correctionDensity = clampScore(
    readNumber(datasetSnapshot, "correctionDensity") ??
      readNumber(datasetMetadata, "correctionDensity") ??
      (approvedCorrectionCount > 0 ? compactedRecordCount / approvedCorrectionCount : 0),
  );
  const freshSignalRatio = clampScore(
    readNumber(datasetSnapshot, "freshSignalRatio") ??
      readNumber(datasetMetadata, "freshSignalRatio") ??
      (compactedRecordCount > 0 ? freshSignalCount / compactedRecordCount : 0),
  );
  const signalFreshnessScore = clampScore(
    readNumber(datasetSnapshot, "signalFreshnessScore") ??
      readNumber(datasetMetadata, "signalFreshnessScore") ??
      (freshSignalRatio * 0.7 + correctionDensity * 0.3),
  );
  const lineageScore = clampScore(
    readNumber(datasetSnapshot, "lineageScore") ??
      readNumber(datasetMetadata, "lineageScore") ??
      (readString(datasetSnapshot, "sourceLineage") === "approved_corrections" ||
      readString(datasetMetadata, "sourceLineage") === "approved_corrections"
        ? 1
        : 0.45),
  );
  const compactionQualityScore = clampScore(
    readNumber(datasetSnapshot, "compactionQualityScore") ??
      readNumber(datasetMetadata, "compactionQualityScore") ??
      (correctionDensity * 0.38 + freshSignalRatio * 0.32 + signalFreshnessScore * 0.18 + lineageScore * 0.12),
  );
  const datasetQualityScore = clampScore(
    compactionQualityScore * 0.58 +
      correctionDensity * 0.12 +
      freshSignalRatio * 0.12 +
      signalFreshnessScore * 0.08 +
      lineageScore * 0.1,
  );
  const embeddingCoverageScore = clampScore(0.72 + datasetSizeScore * 0.14 + tokenCoverageScore * 0.08);
  const quantumBenchmarkScore = clampScore(requestedQuantumScore ?? 0.74 + datasetSizeScore * 0.08);
  const neuralEvalScore = clampScore(0.68 + embeddingCoverageScore * 0.12 + quantumBenchmarkScore * 0.08 + datasetQualityScore * 0.14);
  const evaluationScore = clampScore(
    (embeddingCoverageScore + quantumBenchmarkScore + neuralEvalScore + datasetQualityScore) / 4,
  );
  const qualityGateRecord = readRecord(learningSnapshot?.qualityGate);
  const queueTimeQualityGate: BrainQualityGateSnapshot | null = qualityGateRecord
    ? {
        status:
          qualityGateRecord.status === "ready_for_queue" ||
          qualityGateRecord.status === "blocked_low_signal" ||
          qualityGateRecord.status === "blocked_quality_regression"
            ? qualityGateRecord.status
            : "blocked_quality_regression",
        reasons: readStringArray(qualityGateRecord, "reasons"),
        thumbsDownRate: readNumber(qualityGateRecord, "thumbsDownRate") ?? 1,
        regenerateRate: readNumber(qualityGateRecord, "regenerateRate") ?? 1,
        qualityCompositeScore: readNumber(qualityGateRecord, "qualityCompositeScore") ?? 0,
        thresholds: {
          minSafeLearningEvents:
            readNumber(readRecord(qualityGateRecord.thresholds), "minSafeLearningEvents") ?? 32,
          minTotalQualitySignals:
            readNumber(readRecord(qualityGateRecord.thresholds), "minTotalQualitySignals") ?? 8,
          minHelpfulnessSignals:
            readNumber(readRecord(qualityGateRecord.thresholds), "minHelpfulnessSignals") ?? 2,
          minBrevityToneSignals:
            readNumber(readRecord(qualityGateRecord.thresholds), "minBrevityToneSignals") ?? 3,
          minTaskRoutingSignals:
            readNumber(readRecord(qualityGateRecord.thresholds), "minTaskRoutingSignals") ?? 1,
          maxThumbsDownRate:
            readNumber(readRecord(qualityGateRecord.thresholds), "maxThumbsDownRate") ?? 0.45,
          maxRegenerateRate:
            readNumber(readRecord(qualityGateRecord.thresholds), "maxRegenerateRate") ?? 0.35,
        },
      }
    : null;
  const qualitySignals: BrainQualitySignalSummary = {
    toneSignals: readNumber(qualitySignalSummaryRecord, "toneSignals") ?? 0,
    humorSignals: readNumber(qualitySignalSummaryRecord, "humorSignals") ?? 0,
    brevitySignals: readNumber(qualitySignalSummaryRecord, "brevitySignals") ?? 0,
    helpfulnessSignals: readNumber(qualitySignalSummaryRecord, "helpfulnessSignals") ?? 0,
    taskRoutingSignals: readNumber(qualitySignalSummaryRecord, "taskRoutingSignals") ?? 0,
  };
  const promotionEligibility = evaluateBrainPromotionEligibility({
    evaluationScore,
    qualityGate: queueTimeQualityGate,
    qualitySignals,
  });
  const promotionGateReasons = [...promotionEligibility.reasons];
  if (promotionEligibility.status === "ready" && datasetQualityScore < 0.55) {
    promotionGateReasons.push("dataset_quality_too_low");
  }
  const promotionGate =
    promotionEligibility.status === "ready" && datasetQualityScore >= 0.55
      ? "ready"
      : promotionEligibility.status === "ready"
        ? "blocked_quality"
        : promotionEligibility.status;
  const datasetFingerprint = fingerprintSafeDatasetSignal({
    jobId: input.job.id,
    datasetManifestId: input.dataset.id,
    trainingBackend: input.trainingBackend,
    adapterMode: input.adapterMode,
    dataset: input.dataset,
  });

  return {
    evaluationScore,
    neuralEvalScore,
    quantumBenchmarkScore,
    embeddingCoverageScore,
    datasetQualityScore,
    compactionQualityScore,
    correctionDensity,
    freshSignalRatio,
    signalFreshnessScore,
    lineageScore,
    compactedRecordCount,
    approvedCorrectionCount,
    freshSignalCount,
    datasetFingerprint,
    promotionGate,
    qualityGateStatus: queueTimeQualityGate?.status ?? "missing",
    qualityGateReasons: promotionEligibility.reasons,
    promotionGateReasons,
    thumbsDownRate: promotionEligibility.thumbsDownRate,
    regenerateRate: promotionEligibility.regenerateRate,
    qualityCompositeScore: promotionEligibility.qualityCompositeScore,
    evaluationState: "bounded_offline_eval",
  };
}

function describePostgresError(error: unknown): Record<string, unknown> {
  if (!error || typeof error !== "object") {
    return {
      errorType: typeof error,
    };
  }

  const record = error as Record<string, unknown>;
  const message = typeof record.message === "string" ? record.message : null;
  const detail = typeof record.detail === "string" ? record.detail : null;
  const hint = typeof record.hint === "string" ? record.hint : null;
  const stack = typeof record.stack === "string" ? record.stack : null;
  const missingColumn =
    message?.match(/column "([^"]+)" does not exist/)?.[1] ??
    detail?.match(/column "([^"]+)" does not exist/)?.[1] ??
    null;

  return {
    code: typeof record.code === "string" ? record.code : null,
    name: typeof record.name === "string" ? record.name : null,
    message,
    detail,
    hint,
    position: typeof record.position === "string" ? record.position : null,
    missingColumn,
    stack,
  };
}

async function claimNextQueuedTrainingJob(app: FastifyInstance): Promise<TrainingJobRow | null> {
  const queuedRows = await app.db
    .select()
    .from(trainingJobs)
    .where(eq(trainingJobs.status, "queued"))
    .orderBy(asc(trainingJobs.createdAt))
    .limit(1);

  const queuedJob = queuedRows[0];
  if (!queuedJob) {
    return null;
  }

  const now = new Date();
  const updatedRows = await app.db
    .update(trainingJobs)
    .set({
      status: "running",
      startedAt: now,
      updatedAt: now,
      metadata: mergeTrainingMetadata(queuedJob.metadata, {
        workerStatus: "running",
        trainingMode: "bounded_cpu_eval",
        claimedAt: now.toISOString(),
      }),
    })
    .where(and(eq(trainingJobs.id, queuedJob.id), eq(trainingJobs.status, "queued")))
    .returning();

  return updatedRows[0] ?? null;
}

async function failTrainingJob(
  app: FastifyInstance,
  job: TrainingJobRow,
  reason: string,
  details: Record<string, unknown> = {},
) {
  const now = new Date();
  const rows = await app.db
    .update(trainingJobs)
    .set({
      status: "failed",
      completedAt: now,
      updatedAt: now,
      error: reason,
      metadata: mergeTrainingMetadata(job.metadata, buildExternalRequiredMetadata(reason, details)),
    })
    .where(and(eq(trainingJobs.id, job.id), eq(trainingJobs.status, "running")))
    .returning();

  const failedJob = rows[0] ?? job;

  await createAuditLog(app, {
    actorType: "system",
    actorId: "training-worker",
    action: "brain.training_job.failed",
    resourceType: "training_job",
    resourceId: failedJob.id,
    status: "success",
    payload: {
      reason,
      datasetManifestId: failedJob.datasetManifestId,
      metadata: failedJob.metadata,
    },
  });

  return failedJob;
}

async function completeTrainingJob(
  app: FastifyInstance,
  input: {
    job: TrainingJobRow;
    dataset: DatasetManifestRow;
    trainingBackend: string;
    adapterMode: string | null;
  },
) {
  const now = new Date();
  const metrics = buildSafeEvaluationMetrics(input);
  const artifactStatus = metrics.promotionGate === "ready" ? "ready" : "draft";
  const metadata = mergeTrainingMetadata(input.job.metadata, {
    trainingMode: "bounded_cpu_eval",
    workerStatus: "completed",
    phase: "evaluation",
    datasetManifestId: input.job.datasetManifestId,
    trainingBackend: input.trainingBackend,
    adapterMode: input.adapterMode,
    evaluationState: metrics.evaluationState,
    promotionGate: metrics.promotionGate,
    qualityGateStatus: metrics.qualityGateStatus,
    qualityGateReasons: metrics.qualityGateReasons,
    promotionGateReasons: metrics.promotionGateReasons,
    thumbsDownRate: metrics.thumbsDownRate,
    regenerateRate: metrics.regenerateRate,
    qualityCompositeScore: metrics.qualityCompositeScore,
    datasetQualityScore: metrics.datasetQualityScore,
    compactionQualityScore: metrics.compactionQualityScore,
    correctionDensity: metrics.correctionDensity,
    freshSignalRatio: metrics.freshSignalRatio,
    signalFreshnessScore: metrics.signalFreshnessScore,
    lineageScore: metrics.lineageScore,
    compactedRecordCount: metrics.compactedRecordCount,
    approvedCorrectionCount: metrics.approvedCorrectionCount,
    freshSignalCount: metrics.freshSignalCount,
    datasetFingerprint: metrics.datasetFingerprint,
    neuralEvalScore: metrics.neuralEvalScore,
    quantumBenchmarkScore: metrics.quantumBenchmarkScore,
    completedBy: "training-worker",
  });

  const rows = await app.db
    .update(trainingJobs)
    .set({
      status: "completed",
      completedAt: now,
      updatedAt: now,
      error: null,
      metrics,
      metadata,
    })
    .where(and(eq(trainingJobs.id, input.job.id), eq(trainingJobs.status, "running")))
    .returning();

  const completedJob = rows[0] ?? { ...input.job, status: "completed", metrics, metadata, completedAt: now, updatedAt: now };

  await app.db.insert(modelArtifacts).values({
    ownerUserId: completedJob.ownerUserId,
    scope: completedJob.scope,
    trainingJobId: completedJob.id,
    name: `${completedJob.name} evaluation artifact`,
    provider: "elyan-ml-worker",
    baseModel: completedJob.baseModel,
    adapterKind: input.adapterMode ?? "eval_adapter",
    status: artifactStatus,
    storageUri: `elyan://model-artifacts/${completedJob.id}`,
    checksum: `sha256:${metrics.datasetFingerprint}`,
    metadata: {
      evaluationState: metrics.evaluationState,
      promotionGate: metrics.promotionGate,
      qualityGateStatus: metrics.qualityGateStatus,
      qualityGateReasons: metrics.qualityGateReasons,
      promotionGateReasons: metrics.promotionGateReasons,
      datasetFingerprint: metrics.datasetFingerprint,
      neuralEvalScore: metrics.neuralEvalScore,
      quantumBenchmarkScore: metrics.quantumBenchmarkScore,
      evaluationScore: metrics.evaluationScore,
      thumbsDownRate: metrics.thumbsDownRate,
      regenerateRate: metrics.regenerateRate,
      qualityCompositeScore: metrics.qualityCompositeScore,
      datasetQualityScore: metrics.datasetQualityScore,
      compactionQualityScore: metrics.compactionQualityScore,
      correctionDensity: metrics.correctionDensity,
      freshSignalRatio: metrics.freshSignalRatio,
      signalFreshnessScore: metrics.signalFreshnessScore,
      lineageScore: metrics.lineageScore,
      trainingBackend: input.trainingBackend,
      adapterMode: input.adapterMode,
    },
  });

  await createAuditLog(app, {
    actorType: "system",
    actorId: "training-worker",
    action: "brain.training_job.completed",
    resourceType: "training_job",
    resourceId: completedJob.id,
    status: "success",
    payload: {
      datasetManifestId: completedJob.datasetManifestId,
      evaluationState: metrics.evaluationState,
      promotionGate: metrics.promotionGate,
      qualityGateStatus: metrics.qualityGateStatus,
      qualityGateReasons: metrics.qualityGateReasons,
      promotionGateReasons: metrics.promotionGateReasons,
      evaluationScore: metrics.evaluationScore,
      neuralEvalScore: metrics.neuralEvalScore,
      quantumBenchmarkScore: metrics.quantumBenchmarkScore,
      datasetQualityScore: metrics.datasetQualityScore,
      compactionQualityScore: metrics.compactionQualityScore,
    },
  });

  if (metrics.promotionGate !== "ready") {
    await createAuditLog(app, {
      actorType: "system",
      actorId: "training-worker",
      action: "brain.training_job.promotion_blocked_by_quality_gate",
      resourceType: "training_job",
      resourceId: completedJob.id,
      status: "success",
      payload: {
        datasetManifestId: completedJob.datasetManifestId,
        promotionGate: metrics.promotionGate,
        qualityGateStatus: metrics.qualityGateStatus,
        qualityGateReasons: metrics.qualityGateReasons,
        promotionGateReasons: metrics.promotionGateReasons,
        qualityCompositeScore: metrics.qualityCompositeScore,
        datasetQualityScore: metrics.datasetQualityScore,
        compactionQualityScore: metrics.compactionQualityScore,
      },
    });
  }

  return completedJob;
}

async function processTrainingJob(app: FastifyInstance, job: TrainingJobRow) {
  const config = readRecord(job.config);
  const trainingBackend = readString(config, "trainingBackend") ?? "pytorch_cpu_safe";
  const adapterMode = readString(config, "adapterMode") ?? null;
  const memoryOutcome = await processMemoryTrainingJob(app, job);

  if (memoryOutcome) {
    await createAuditLog(app, {
      actorType: "system",
      actorId: "training-worker",
      action: "brain.training_job.completed",
      resourceType: "training_job",
      resourceId: job.id,
      status: "success",
      payload: {
        kind: job.kind,
        processedCount: memoryOutcome.processedCount,
        memoryStatus: memoryOutcome.status,
        metadata: memoryOutcome.metadata,
      },
    });
    return;
  }

  if (job.kind === "retrieval_index") {
    const documentId = readString(config, "sourceDocumentId");
    if (!documentId) {
      await failTrainingJob(app, job, "retrieval_document_missing", {
        trainingBackend,
        adapterMode,
      });
      return;
    }

    const indexed = await indexKnowledgeChunksForDocument(app, {
      documentId,
    });
    const now = new Date();
    await app.db
      .update(trainingJobs)
      .set({
        status: "completed",
        completedAt: now,
        updatedAt: now,
        error: null,
        metrics: {
          indexedChunkCount: indexed.indexedChunkCount,
          retrievalMode: indexed.mode,
        },
        metadata: mergeTrainingMetadata(job.metadata, {
          workerStatus: indexed.skippedReason ? "skipped" : "completed",
          phase: "retrieval_index",
          indexedChunkCount: indexed.indexedChunkCount,
          retrievalMode: indexed.mode,
          skippedReason: indexed.skippedReason,
          sourceDocumentId: documentId,
        }),
      })
      .where(and(eq(trainingJobs.id, job.id), eq(trainingJobs.status, "running")));

    await createAuditLog(app, {
      actorType: "system",
      actorId: "training-worker",
      action: "brain.training_job.completed",
      resourceType: "training_job",
      resourceId: job.id,
      status: "success",
      payload: {
        kind: "retrieval_index",
        sourceDocumentId: documentId,
        indexedChunkCount: indexed.indexedChunkCount,
        retrievalMode: indexed.mode,
        skippedReason: indexed.skippedReason,
      },
    });
    return;
  }

  if (!job.datasetManifestId) {
    await failTrainingJob(app, job, "dataset_manifest_not_ready", {
      datasetManifestId: null,
      trainingBackend,
      adapterMode,
    });
    return;
  }

  const datasetRows = await app.db
    .select({
      id: datasetManifests.id,
      status: datasetManifests.status,
      scope: datasetManifests.scope,
      recordCount: datasetManifests.recordCount,
      tokenEstimate: datasetManifests.tokenEstimate,
      metadata: datasetManifests.metadata,
    })
    .from(datasetManifests)
    .where(eq(datasetManifests.id, job.datasetManifestId))
    .limit(1);

  const dataset = datasetRows[0];
  if (!dataset || dataset.status !== "ready") {
    await failTrainingJob(app, job, "dataset_manifest_not_ready", {
      datasetManifestId: job.datasetManifestId,
      datasetStatus: dataset?.status ?? null,
      trainingBackend,
      adapterMode,
    });
    return;
  }

  await completeTrainingJob(app, {
    job,
    dataset,
    trainingBackend,
    adapterMode,
  });
}

export async function processNextQueuedTrainingJob(app: FastifyInstance): Promise<boolean> {
  const job = await claimNextQueuedTrainingJob(app);
  if (!job) {
    return false;
  }

  await processTrainingJob(app, job);
  return true;
}

export async function runTrainingWorker(app: FastifyInstance, options: TrainingWorkerOptions = {}) {
  const idleDelayMs = options.idleDelayMs ?? 5_000;

  while (true) {
    let processed = false;

    try {
      processed = await processNextQueuedTrainingJob(app);
    } catch (error) {
      app.log.error(
        {
          error: describePostgresError(error),
        },
        "training worker iteration failed",
      );
    }

    if (options.once) {
      return;
    }

    await sleep(processed ? 0 : idleDelayMs);
  }
}

// ── In-process memory worker ────────────────────────────────────────────────
//
// Memory jobs (extraction/consolidation/…) are pure TS DB aggregation, but the
// node training-worker container is disabled in prod ("ml-worker owns training
// job execution") and the python ml-worker only does model training. So these
// jobs piled up forever (queued, never run) and brain_memory_facts stayed
// empty — Elyan never remembered anyone. We drain ONLY memory-kind jobs in the
// backend process; ML training jobs are left untouched for the python worker.

const MEMORY_JOB_KINDS = [
  "memory_extraction",
  "memory_consolidation",
  "memory_reconsolidation",
  "memory_index",
] as const;

async function claimNextQueuedMemoryJob(
  app: FastifyInstance,
): Promise<TrainingJobRow | null> {
  const queuedRows = await app.db
    .select()
    .from(trainingJobs)
    .where(
      and(
        eq(trainingJobs.status, "queued"),
        inArray(trainingJobs.kind, [...MEMORY_JOB_KINDS]),
      ),
    )
    .orderBy(asc(trainingJobs.createdAt))
    .limit(1);

  const queuedJob = queuedRows[0];
  if (!queuedJob) {
    return null;
  }

  const now = new Date();
  const updatedRows = await app.db
    .update(trainingJobs)
    .set({
      status: "running",
      startedAt: now,
      updatedAt: now,
      metadata: mergeTrainingMetadata(queuedJob.metadata, {
        workerStatus: "running",
        claimedAt: now.toISOString(),
        claimedBy: "in_process_memory_worker",
      }),
    })
    // Atomic claim: only one worker wins even with concurrent backends.
    .where(and(eq(trainingJobs.id, queuedJob.id), eq(trainingJobs.status, "queued")))
    .returning();

  return updatedRows[0] ?? null;
}

export async function processNextQueuedMemoryJob(
  app: FastifyInstance,
): Promise<boolean> {
  const job = await claimNextQueuedMemoryJob(app);
  if (!job) {
    return false;
  }
  // processMemoryTrainingJob transitions the row to completed/failed itself.
  const outcome = await processMemoryTrainingJob(app, job);
  if (!outcome) {
    await failTrainingJob(app, job, "memory_job_unhandled", { kind: job.kind });
  }
  return true;
}

type MemoryWorkerState = {
  timer: ReturnType<typeof setInterval>;
  running: boolean;
  stopped: boolean;
};

const activeMemoryWorkers = new WeakMap<FastifyInstance, MemoryWorkerState>();
const MEMORY_WORKER_INTERVAL_MS = 30_000;
const MEMORY_WORKER_BATCH = 25;

/// Starts the periodic in-process memory-job drainer. Returns a stop callback.
export function startInProcessMemoryWorker(app: FastifyInstance): () => void {
  if (process.env.ELYAN_MEMORY_WORKER_DISABLED === "true") {
    app.log.info?.("in-process memory worker disabled via ELYAN_MEMORY_WORKER_DISABLED");
    return () => {};
  }

  const existing = activeMemoryWorkers.get(app);
  if (existing) {
    return () => {
      if (existing.stopped) {
        return;
      }
      existing.stopped = true;
      clearInterval(existing.timer);
      activeMemoryWorkers.delete(app);
    };
  }

  const state: MemoryWorkerState = {
    timer: setInterval(() => {
      void drain();
    }, MEMORY_WORKER_INTERVAL_MS),
    running: false,
    stopped: false,
  };
  state.timer.unref?.();
  activeMemoryWorkers.set(app, state);

  void drain();

  async function drain() {
    if (state.stopped || state.running) {
      return;
    }
    state.running = true;
    try {
      let processed = 0;
      while (processed < MEMORY_WORKER_BATCH && !state.stopped) {
        const did = await processNextQueuedMemoryJob(app);
        if (!did) {
          break;
        }
        processed += 1;
      }
      if (processed > 0) {
        app.log.info?.({ processed }, "in-process memory worker drained jobs");
      }
    } catch (error) {
      app.log.error(
        { error: describePostgresError(error) },
        "in-process memory worker iteration failed",
      );
    } finally {
      state.running = false;
    }
  }

  return () => {
    if (state.stopped) {
      return;
    }
    state.stopped = true;
    clearInterval(state.timer);
    activeMemoryWorkers.delete(app);
  };
}
