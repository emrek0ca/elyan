import { and, asc, eq, inArray, lt } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { createHash } from "node:crypto";
import { setTimeout as sleep } from "node:timers/promises";
import {
  brainMemoryEpisodes,
  cognitiveMutationOutbox,
  datasetManifests,
  modelArtifacts,
  trainingJobs,
} from "../../db/schema.js";
import { createAuditLog } from "../audit/service.js";
import {
  evaluateBrainPromotionEligibility,
  type BrainQualityGateSnapshot,
  type BrainQualitySignalSummary,
} from "./quality-gate.js";
import {
  processMemoryImportanceDecay,
  processMemoryTrainingJob,
} from "./memory.js";
import {
  buildProactiveComposePrompt,
  buildProactiveOpeningCompose,
  DIGEST_KIND,
  sweepDueProactiveTriggers,
  type ProactiveComposeResult,
  type ProactiveTriggerRow,
  type ProactiveTriggerSweepResult,
} from "./proactive-engine.js";
import {
  buildMorningDigest,
  emptyNightWatchSweep,
  listNightWatchJobs,
  runNightWatchSweep,
  type NightWatchSweepResult,
} from "./night-watch.js";
import {
  emptyObserverSweep,
  runProactiveObserverSweep,
  type ObserverSweepResult,
} from "./proactive-observer.js";
import {
  processContinuousLearningDailyBuild,
  type ContinuousLearningBuildResult,
} from "./continuous-learning-pipeline.js";
import { generateSharedBrainReply } from "./inference.js";
import { indexKnowledgeChunksForDocument } from "./retrieval.js";
import { readVerifiedQuantumBenchmark } from "./quantum-benchmark.js";
import {
  processDueAutomations,
  type AutomationSweepResult,
} from "../automations/runner.js";
import {
  asRecord as readRecord,
  recordNumber as readNumber,
  recordString as readString,
  recordStringList as readStringArray,
} from "../../lib/record.js";

type TrainingJobRow = typeof trainingJobs.$inferSelect;
type DatasetManifestRow = Pick<
  typeof datasetManifests.$inferSelect,
  "id" | "status" | "scope" | "recordCount" | "tokenEstimate" | "metadata"
>;

type TrainingWorkerOptions = {
  idleDelayMs?: number;
  once?: boolean;
};

const EVALUATION_METRIC_VERSION = "bounded_offline_eval_v2";

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
  const datasetFingerprint = fingerprintSafeDatasetSignal({
    jobId: input.job.id,
    datasetManifestId: input.dataset.id,
    trainingBackend: input.trainingBackend,
    adapterMode: input.adapterMode,
    dataset: input.dataset,
  });
  const verifiedQuantumBenchmark = readVerifiedQuantumBenchmark(input.job.metadata, {
    expectedDatasetFingerprint: datasetFingerprint,
  });
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
  const quantumBenchmarkScore = verifiedQuantumBenchmark?.score ?? null;
  const neuralBaselineScore = clampScore(
    0.7 + embeddingCoverageScore * 0.14 + datasetQualityScore * 0.16,
  );
  const neuralEvalScore = !verifiedQuantumBenchmark?.qualified
    ? neuralBaselineScore
    : clampScore(neuralBaselineScore * 0.92 + verifiedQuantumBenchmark.score * 0.08);
  const evaluationInputs = [embeddingCoverageScore, neuralEvalScore, datasetQualityScore];
  if (verifiedQuantumBenchmark?.qualified && quantumBenchmarkScore !== null) {
    evaluationInputs.push(quantumBenchmarkScore);
  }
  const evaluationScore = clampScore(
    evaluationInputs.reduce((sum, score) => sum + score, 0) / evaluationInputs.length,
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
  return {
    evaluationMetricVersion: EVALUATION_METRIC_VERSION,
    evaluationScore,
    neuralEvalScore,
    quantumBenchmarkScore,
    quantumBenchmarkVerified: verifiedQuantumBenchmark !== null,
    quantumBenchmarkSource: verifiedQuantumBenchmark?.source ?? null,
    quantumClassicalBaselineScore: verifiedQuantumBenchmark?.classicalBaselineScore ?? null,
    quantumBenchmarkMeasuredAt: verifiedQuantumBenchmark?.measuredAt ?? null,
    quantumBenchmarkBackend: verifiedQuantumBenchmark?.backend ?? null,
    quantumBenchmarkVersion: verifiedQuantumBenchmark?.version ?? null,
    quantumBenchmarkProducer: verifiedQuantumBenchmark?.producer ?? null,
    quantumBenchmarkRunId: verifiedQuantumBenchmark?.runId ?? null,
    quantumBenchmarkMetric: verifiedQuantumBenchmark?.metric ?? null,
    quantumBenchmarkDatasetFingerprint: verifiedQuantumBenchmark?.datasetFingerprint ?? null,
    quantumBenchmarkSampleCount: verifiedQuantumBenchmark?.sampleCount ?? null,
    quantumAdvantageScore: verifiedQuantumBenchmark?.advantageScore ?? null,
    quantumBenchmarkQualified: verifiedQuantumBenchmark?.qualified ?? false,
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
  const metadata = mergeTrainingMetadata(input.job.metadata, {
    trainingMode: "bounded_cpu_eval",
    artifactPurpose: "behavior_evaluation",
    servable: false,
    workerStatus: "completed",
    phase: "evaluation",
    datasetManifestId: input.job.datasetManifestId,
    trainingBackend: input.trainingBackend,
    adapterMode: input.adapterMode,
    evaluationState: metrics.evaluationState,
    evaluationMetricVersion: metrics.evaluationMetricVersion,
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
    quantumBenchmarkVerified: metrics.quantumBenchmarkVerified,
    quantumBenchmarkSource: metrics.quantumBenchmarkSource,
    quantumClassicalBaselineScore: metrics.quantumClassicalBaselineScore,
    quantumBenchmarkMeasuredAt: metrics.quantumBenchmarkMeasuredAt,
    quantumBenchmarkBackend: metrics.quantumBenchmarkBackend,
    quantumBenchmarkVersion: metrics.quantumBenchmarkVersion,
    quantumBenchmarkProducer: metrics.quantumBenchmarkProducer,
    quantumBenchmarkRunId: metrics.quantumBenchmarkRunId,
    quantumBenchmarkMetric: metrics.quantumBenchmarkMetric,
    quantumBenchmarkDatasetFingerprint: metrics.quantumBenchmarkDatasetFingerprint,
    quantumBenchmarkSampleCount: metrics.quantumBenchmarkSampleCount,
    quantumAdvantageScore: metrics.quantumAdvantageScore,
    quantumBenchmarkQualified: metrics.quantumBenchmarkQualified,
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
    adapterKind: "behavior_eval",
    status: "draft",
    storageUri: null,
    checksum: null,
    metadata: {
      artifactPurpose: "behavior_evaluation",
      servable: false,
      trainingMode: "bounded_cpu_eval",
      evaluationState: metrics.evaluationState,
      evaluationMetricVersion: metrics.evaluationMetricVersion,
      promotionGate: metrics.promotionGate,
      qualityGateStatus: metrics.qualityGateStatus,
      qualityGateReasons: metrics.qualityGateReasons,
      promotionGateReasons: metrics.promotionGateReasons,
      datasetFingerprint: metrics.datasetFingerprint,
      neuralEvalScore: metrics.neuralEvalScore,
      quantumBenchmarkScore: metrics.quantumBenchmarkScore,
      quantumBenchmarkVerified: metrics.quantumBenchmarkVerified,
      quantumBenchmarkSource: metrics.quantumBenchmarkSource,
      quantumClassicalBaselineScore: metrics.quantumClassicalBaselineScore,
      quantumBenchmarkMeasuredAt: metrics.quantumBenchmarkMeasuredAt,
      quantumBenchmarkBackend: metrics.quantumBenchmarkBackend,
      quantumBenchmarkVersion: metrics.quantumBenchmarkVersion,
      quantumBenchmarkProducer: metrics.quantumBenchmarkProducer,
      quantumBenchmarkRunId: metrics.quantumBenchmarkRunId,
      quantumBenchmarkMetric: metrics.quantumBenchmarkMetric,
      quantumBenchmarkDatasetFingerprint: metrics.quantumBenchmarkDatasetFingerprint,
      quantumBenchmarkSampleCount: metrics.quantumBenchmarkSampleCount,
      quantumAdvantageScore: metrics.quantumAdvantageScore,
      quantumBenchmarkQualified: metrics.quantumBenchmarkQualified,
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
      evaluationMetricVersion: metrics.evaluationMetricVersion,
      promotionGate: metrics.promotionGate,
      qualityGateStatus: metrics.qualityGateStatus,
      qualityGateReasons: metrics.qualityGateReasons,
      promotionGateReasons: metrics.promotionGateReasons,
      evaluationScore: metrics.evaluationScore,
      neuralEvalScore: metrics.neuralEvalScore,
      quantumBenchmarkScore: metrics.quantumBenchmarkScore,
      quantumBenchmarkQualified: metrics.quantumBenchmarkQualified,
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
const DOCUMENT_JOB_KINDS = ["retrieval_index"] as const;

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

async function claimNextQueuedDocumentJob(
  app: FastifyInstance,
): Promise<TrainingJobRow | null> {
  const queuedRows = await app.db
    .select()
    .from(trainingJobs)
    .where(
      and(
        eq(trainingJobs.status, "queued"),
        inArray(trainingJobs.kind, [...DOCUMENT_JOB_KINDS]),
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
        trainingMode: "document_worker",
        claimedAt: now.toISOString(),
        claimedBy: "document_worker",
      }),
    })
    .where(and(eq(trainingJobs.id, queuedJob.id), eq(trainingJobs.status, "queued")))
    .returning();

  return updatedRows[0] ?? null;
}

export async function processNextQueuedDocumentJob(
  app: FastifyInstance,
): Promise<boolean> {
  const job = await claimNextQueuedDocumentJob(app);
  if (!job) {
    return false;
  }
  await processTrainingJob(app, job);
  return true;
}

type MemoryWorkerState = {
  timer: ReturnType<typeof setInterval>;
  running: boolean;
  stopped: boolean;
};

export type BrainWorkerIterationResult = {
  memoryJobsProcessed: number;
  memoryDecayProcessed: number;
  memoryDecayUpdated: number;
  proactive: ProactiveTriggerSweepResult;
  expiredEpisodes?: number;
  outboxProcessed?: number;
  continuousLearning?: ContinuousLearningBuildResult;
};

type BrainWorkerIterationOptions = {
  memoryBatch?: number;
  processMemoryJob?: (app: FastifyInstance) => Promise<boolean>;
  processDecay?: typeof processMemoryImportanceDecay;
  processProactive?: typeof processDueProactiveTriggers;
  processExpiredEpisodes?: typeof processExpiredCognitiveEpisodes;
  processOutbox?: typeof processCognitiveMutationOutbox;
  processContinuousLearning?: typeof processContinuousLearningDailyBuild;
};

const activeMemoryWorkers = new WeakMap<FastifyInstance, MemoryWorkerState>();
const MEMORY_WORKER_INTERVAL_MS = 30_000;
const MEMORY_WORKER_BATCH = 25;
const PROACTIVE_WORKER_BATCH = 5;
const COGNITIVE_MAINTENANCE_BATCH = 100;
export const BRAIN_WORKER_HEARTBEAT_KEY = "elyan:brain-worker:heartbeat";
const BRAIN_WORKER_HEARTBEAT_TTL_MS = 90_000;
const BRAIN_WORKER_HEARTBEAT_FRESH_MS = 75_000;

function emptyProactiveSweep(): ProactiveTriggerSweepResult {
  return {
    processed: 0,
    fired: 0,
    expired: 0,
    deferred: 0,
    failed: 0,
  };
}

export async function processExpiredCognitiveEpisodes(
  app: FastifyInstance,
  input: { limit?: number; now?: Date } = {},
): Promise<number> {
  const limit = Math.max(1, Math.min(input.limit ?? COGNITIVE_MAINTENANCE_BATCH, 500));
  const now = input.now ?? new Date();
  return app.db.transaction(async (tx) => {
    const rows = await tx
      .select({ id: brainMemoryEpisodes.id })
      .from(brainMemoryEpisodes)
      .where(and(
        eq(brainMemoryEpisodes.lifecycleStatus, "active"),
        lt(brainMemoryEpisodes.expiresAt, now),
      ))
      .limit(limit)
      .for("update", { skipLocked: true });
    if (rows.length === 0) return 0;
    await tx
      .update(brainMemoryEpisodes)
      .set({ lifecycleStatus: "expired", staleAt: now, updatedAt: now })
      .where(inArray(brainMemoryEpisodes.id, rows.map((row) => row.id)));
    return rows.length;
  });
}

export async function processCognitiveMutationOutbox(
  app: FastifyInstance,
  input: { limit?: number; now?: Date } = {},
): Promise<number> {
  const limit = Math.max(1, Math.min(input.limit ?? COGNITIVE_MAINTENANCE_BATCH, 500));
  const now = input.now ?? new Date();
  return app.db.transaction(async (tx) => {
    const rows = await tx
      .select({ id: cognitiveMutationOutbox.id })
      .from(cognitiveMutationOutbox)
      .where(and(
        eq(cognitiveMutationOutbox.status, "pending"),
        lt(cognitiveMutationOutbox.availableAt, new Date(now.getTime() + 1)),
      ))
      .orderBy(asc(cognitiveMutationOutbox.availableAt))
      .limit(limit)
      .for("update", { skipLocked: true });
    if (rows.length === 0) return 0;
    await tx
      .update(cognitiveMutationOutbox)
      .set({ status: "processed", processedAt: now, lastErrorCode: null })
      .where(inArray(cognitiveMutationOutbox.id, rows.map((row) => row.id)));
    return rows.length;
  });
}

/**
 * The morning digest is assembled from settled job rows, never generated.
 *
 * A model asked to "summarise last night" with a thin context is exactly the
 * setup that produces a confident account of work that never happened — and
 * the user cannot check it, because they were asleep.
 */
async function composeMorningDigestMessage(
  app: FastifyInstance,
  trigger: ProactiveTriggerRow,
): Promise<ProactiveComposeResult> {
  const payload =
    trigger.payload && typeof trigger.payload === "object"
      ? (trigger.payload as Record<string, unknown>)
      : {};
  const nightDate =
    typeof payload.nightDate === "string" ? payload.nightDate : "";
  if (!nightDate) {
    return { text: "" };
  }
  const jobs = await listNightWatchJobs(app, {
    userId: trigger.userId,
    nightDate,
  });
  const digest = buildMorningDigest(jobs);
  return { text: digest.text };
}

export async function composeProactiveTriggerMessage(
  app: FastifyInstance,
  trigger: ProactiveTriggerRow,
): Promise<ProactiveComposeResult> {
  if (trigger.kind === DIGEST_KIND) {
    return composeMorningDigestMessage(app, trigger);
  }

  // Observer suggestions already carry a complete, evidence-bound sentence.
  // Handing it to a model to "make it nicer" is the one step where the
  // grounding could quietly be lost, and it buys nothing.
  if (trigger.createdBy === "observer") {
    return buildProactiveOpeningCompose(trigger);
  }

  const reply = await generateSharedBrainReply(app, {
    userId: trigger.userId,
    prompt: buildProactiveComposePrompt(trigger),
    workload: "mobile_chat_fast",
    route: "proactive_follow_up",
    requestMetadata: {
      chatSessionId: trigger.sessionId,
      proactiveTriggerId: trigger.id,
      proactiveKind: trigger.kind,
    },
    maxCompletionTokensOverride: 180,
    timeoutMsOverride: 10_000,
    internalEvaluation: {
      skipUsageValidation: true,
      skipInvocationLogging: true,
      skipReviewLogging: true,
    },
  });

  return {
    text: reply.text,
    blocks: Array.isArray(reply.metadata.blocks)
      ? reply.metadata.blocks.slice(0, 12)
      : [],
  };
}

export async function processDueProactiveTriggers(
  app: FastifyInstance,
  input: {
    limit?: number;
    now?: Date;
    compose?: (trigger: ProactiveTriggerRow) => Promise<ProactiveComposeResult>;
  } = {},
): Promise<ProactiveTriggerSweepResult> {
  if (app.config?.ELYAN_PROACTIVE_ENGINE_ENABLED !== true) {
    return emptyProactiveSweep();
  }

  return sweepDueProactiveTriggers(app, {
    limit: input.limit ?? PROACTIVE_WORKER_BATCH,
    now: input.now,
    compose:
      input.compose ??
      ((trigger) => composeProactiveTriggerMessage(app, trigger)),
  });
}

/**
 * Night watch entry point for the scheduler loop. Kept separate from
 * `processDueProactiveTriggers` so the two flags can be rolled out apart:
 * delivering follow-ups and working overnight are different promises to the
 * user and should be switchable independently.
 */
export async function runNightWatchWave(
  app: FastifyInstance,
  input: { now?: Date } = {},
): Promise<NightWatchSweepResult> {
  if (app.config?.ELYAN_NIGHT_WATCH_ENABLED !== true) {
    return emptyNightWatchSweep();
  }
  return runNightWatchSweep(app, { now: input.now });
}

/**
 * The observer runs on its own, much slower cadence.
 *
 * Noticing things is not urgent — and the cost of noticing too often is not
 * CPU, it is the temptation to say something every time. Once every quarter
 * hour is plenty for "is a deadline approaching".
 */
let lastObserverRunAtMs = 0;

export async function runProactiveObserverWave(
  app: FastifyInstance,
  input: { now?: Date; force?: boolean } = {},
): Promise<ObserverSweepResult> {
  if (app.config?.ELYAN_PROACTIVE_OBSERVER_ENABLED !== true) {
    return emptyObserverSweep();
  }
  const now = input.now ?? new Date();
  const intervalMs = Math.max(
    60_000,
    app.config?.ELYAN_PROACTIVE_OBSERVER_INTERVAL_MS ?? 15 * 60_000,
  );
  if (!input.force && now.getTime() - lastObserverRunAtMs < intervalMs) {
    return emptyObserverSweep();
  }
  lastObserverRunAtMs = now.getTime();
  return runProactiveObserverSweep(app, { now });
}

export async function processBrainWorkerIteration(
  app: FastifyInstance,
  options: BrainWorkerIterationOptions = {},
): Promise<BrainWorkerIterationResult> {
  const memoryBatch = Math.max(1, Math.min(options.memoryBatch ?? MEMORY_WORKER_BATCH, 100));
  const processMemoryJob = options.processMemoryJob ?? processNextQueuedMemoryJob;
  const processDecay = options.processDecay ?? processMemoryImportanceDecay;
  const processProactive = options.processProactive ?? processDueProactiveTriggers;
  const processExpiredEpisodes = options.processExpiredEpisodes ?? processExpiredCognitiveEpisodes;
  const processOutbox = options.processOutbox ?? processCognitiveMutationOutbox;
  const processContinuousLearning = options.processContinuousLearning ?? processContinuousLearningDailyBuild;

  let memoryJobsProcessed = 0;
  while (memoryJobsProcessed < memoryBatch) {
    const did = await processMemoryJob(app);
    if (!did) break;
    memoryJobsProcessed += 1;
  }

  let memoryDecayProcessed = 0;
  let memoryDecayUpdated = 0;
  if (memoryJobsProcessed === 0) {
    const decay = await processDecay(app);
    memoryDecayProcessed = decay.processedCount;
    memoryDecayUpdated = decay.updatedCount;
  }

  const proactive = await processProactive(app);
  const cognitiveMaintenanceEnabled =
    app.config?.ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED === true ||
    (app.config?.ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT ?? 0) > 0;
  const [expiredEpisodes, outboxProcessed] = cognitiveMaintenanceEnabled
    ? await Promise.all([processExpiredEpisodes(app), processOutbox(app)])
    : [0, 0];
  const continuousLearningEnabled =
    app.config?.ELYAN_CONTINUOUS_LEARNING_V2_ENABLED === true ||
    app.config?.ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED === true;
  const continuousLearning = continuousLearningEnabled
    ? await processContinuousLearning(app)
    : undefined;

  return {
    memoryJobsProcessed,
    memoryDecayProcessed,
    memoryDecayUpdated,
    proactive,
    ...(cognitiveMaintenanceEnabled ? { expiredEpisodes, outboxProcessed } : {}),
    ...(continuousLearning ? { continuousLearning } : {}),
  };
}

export async function runBrainWorker(
  app: FastifyInstance,
  options: {
    idleDelayMs?: number;
    once?: boolean;
  } = {},
) {
  const idleDelayMs = options.idleDelayMs ?? MEMORY_WORKER_INTERVAL_MS;

  while (true) {
    let processed = false;

    try {
      await writeBrainWorkerHeartbeat(app);
      const result = await processBrainWorkerIteration(app);
      processed =
        result.memoryJobsProcessed > 0 ||
        result.memoryDecayUpdated > 0 ||
        result.proactive.processed > 0;
      processed =
        processed ||
        (result.expiredEpisodes ?? 0) > 0 ||
        (result.outboxProcessed ?? 0) > 0 ||
        result.continuousLearning?.processed === true;
      if (result.memoryJobsProcessed > 0) {
        app.log.info?.(
          { processed: result.memoryJobsProcessed },
          "brain worker drained memory jobs",
        );
      }
      if (result.memoryDecayUpdated > 0) {
        app.log.info?.(
          {
            processed: result.memoryDecayProcessed,
            updated: result.memoryDecayUpdated,
          },
          "brain worker decayed fact importance",
        );
      }
      if (result.proactive.processed > 0) {
        app.log.info?.(result.proactive, "brain worker processed proactive triggers");
      }
      if (result.continuousLearning?.processed === true) {
        app.log.info?.(
          {
            runId: result.continuousLearning.runId,
            datasetManifestId: result.continuousLearning.datasetManifestId,
            acceptedEventCount: result.continuousLearning.candidate.acceptedEventCount,
            promotionStatus: result.continuousLearning.promotionReport.status,
            shadow: result.continuousLearning.shadow,
          },
          "brain worker built continuous learning manifest",
        );
      }
    } catch (error) {
      app.log.error(
        { error: describePostgresError(error) },
        "brain worker iteration failed",
      );
    }

    if (options.once) {
      return;
    }

    await sleep(processed ? 0 : idleDelayMs);
  }
}

export async function runDocumentWorker(
  app: FastifyInstance,
  options: {
    idleDelayMs?: number;
    once?: boolean;
  } = {},
) {
  const idleDelayMs = options.idleDelayMs ?? MEMORY_WORKER_INTERVAL_MS;

  while (true) {
    let processed = false;
    try {
      processed = await processNextQueuedDocumentJob(app);
      if (processed) {
        app.log.info?.("document worker processed queued document job");
      }
    } catch (error) {
      app.log.error?.({ error }, "document worker iteration failed");
    }
    if (options.once) {
      break;
    }
    await sleep(processed ? 0 : idleDelayMs);
  }
}

export async function runProactiveScheduler(
  app: FastifyInstance,
  options: {
    idleDelayMs?: number;
    once?: boolean;
  } = {},
) {
  const idleDelayMs = options.idleDelayMs ?? MEMORY_WORKER_INTERVAL_MS;

  while (true) {
    let processed = false;
    try {
      const result = await processDueProactiveTriggers(app);
      processed = result.processed > 0;
      if (processed) {
        app.log.info?.(result, "proactive scheduler processed triggers");
      }
    } catch (error) {
      app.log.error?.({ error }, "proactive scheduler iteration failed");
    }

    try {
      const automations: AutomationSweepResult = await processDueAutomations(app);
      if (automations.processed > 0) {
        app.log.info?.(automations, "automation scheduler dispatched tasks");
        processed = true;
      }
    } catch (error) {
      app.log.error?.({ error }, "automation scheduler iteration failed");
    }

    // The night sweep is intentionally in the same loop but independently
    // guarded: a failure to plan tonight's work must not stop due follow-ups
    // from firing, and vice versa.
    try {
      const nightResult = await runNightWatchWave(app);
      if (
        nightResult.planned > 0 ||
        nightResult.settled > 0 ||
        nightResult.digestsScheduled > 0
      ) {
        app.log.info?.(nightResult, "night watch sweep");
        processed = true;
      }
    } catch (error) {
      app.log.error?.({ error }, "night watch sweep failed");
    }

    try {
      const observed = await runProactiveObserverWave(app);
      if (observed.created > 0) {
        app.log.info?.(observed, "proactive observer created suggestions");
        processed = true;
      }
    } catch (error) {
      app.log.error?.({ error }, "proactive observer sweep failed");
    }
    if (options.once) {
      break;
    }
    await sleep(processed ? 0 : idleDelayMs);
  }
}

async function writeBrainWorkerHeartbeat(app: FastifyInstance): Promise<void> {
  await app.services?.reliability?.store
    .set(
      BRAIN_WORKER_HEARTBEAT_KEY,
      JSON.stringify({
        timestamp: new Date().toISOString(),
        mode: "brain_worker",
      }),
      BRAIN_WORKER_HEARTBEAT_TTL_MS,
    )
    .catch(() => undefined);
}

async function hasFreshBrainWorkerHeartbeat(app: FastifyInstance): Promise<boolean> {
  const raw = await app.services?.reliability?.store
    .get(BRAIN_WORKER_HEARTBEAT_KEY)
    .catch(() => null);
  if (!raw) {
    return false;
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    const record =
      parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : null;
    const timestamp = typeof record?.timestamp === "string" ? record.timestamp : null;
    const updatedAt = timestamp ? Date.parse(timestamp) : Number.NaN;
    return Number.isFinite(updatedAt) && Date.now() - updatedAt <= BRAIN_WORKER_HEARTBEAT_FRESH_MS;
  } catch {
    return false;
  }
}

/// Starts the periodic in-process memory-job drainer. Returns a stop callback.
export function startInProcessMemoryWorker(app: FastifyInstance): () => void {
  if (
    app.config?.ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED === true ||
    (app.config?.ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT ?? 0) > 0
  ) {
    app.log.info?.("in-process memory worker disabled; cognitive foundation requires brain-worker");
    return () => {};
  }
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

  void maybeStartFallbackDrain();

  async function maybeStartFallbackDrain() {
    if (state.stopped) {
      return;
    }
    if (await hasFreshBrainWorkerHeartbeat(app)) {
      state.stopped = true;
      clearInterval(state.timer);
      activeMemoryWorkers.delete(app);
      app.log.info?.("in-process memory worker skipped; external brain worker heartbeat is fresh");
      return;
    }
    void drain();
  }

  async function drain() {
    if (state.stopped || state.running) {
      return;
    }
    if (await hasFreshBrainWorkerHeartbeat(app)) {
      state.stopped = true;
      clearInterval(state.timer);
      activeMemoryWorkers.delete(app);
      app.log.info?.("in-process memory worker stopped; external brain worker heartbeat is fresh");
      return;
    }
    state.running = true;
    try {
      const result = await processBrainWorkerIteration(app);
      if (result.memoryDecayUpdated > 0) {
        app.log.info?.(
          {
            processed: result.memoryDecayProcessed,
            updated: result.memoryDecayUpdated,
          },
          "in-process memory worker decayed fact importance",
        );
      }
      if (result.memoryJobsProcessed > 0) {
        app.log.info?.(
          { processed: result.memoryJobsProcessed },
          "in-process memory worker drained jobs",
        );
      }
      if (result.proactive.processed > 0) {
        app.log.info?.(result.proactive, "in-process brain worker processed proactive triggers");
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
