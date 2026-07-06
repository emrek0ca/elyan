import { and, asc, eq, gt, gte, isNull, lt, or } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { createHash } from "node:crypto";
import {
  continuousLearningRuns,
  datasetManifests,
  learningEvents,
} from "../../db/schema.js";
import { createAuditLog } from "../audit/service.js";
import { evaluateContinuousLearningPromotion } from "./continuous-learning-policy.js";

type LearningEventRow = Pick<
  typeof learningEvents.$inferSelect,
  | "id"
  | "userId"
  | "taskId"
  | "type"
  | "key"
  | "value"
  | "confidence"
  | "scope"
  | "source"
  | "privacyLevel"
  | "metadata"
  | "expiresAt"
  | "createdAt"
>;

export type ContinuousLearningDatasetOptions = {
  minConfidence?: number;
  replayRatio?: number;
  validationRatio?: number;
  now?: Date;
};

type RejectionReason =
  | "privacy_level_not_safe"
  | "expired"
  | "metadata_not_training_eligible"
  | "sensitive_value_detected"
  | "low_confidence"
  | "duplicate";

export type ContinuousLearningDatasetCandidate = {
  status: "draft" | "ready" | "failed";
  sourceEventCount: number;
  acceptedEventCount: number;
  rejectedEventCount: number;
  dedupedEventCount: number;
  replayRecordCount: number;
  trainRecordCount: number;
  validationRecordCount: number;
  tokenEstimate: number;
  datasetFingerprint: string;
  acceptedIdentityHashes: string[];
  privacyReport: {
    rawEventValuesIncluded: false;
    promptContentIncluded: false;
    rejectedByReason: Record<RejectionReason, number>;
    privacyRejectedCount: number;
    sensitiveRejectedCount: number;
  };
  qualityReport: {
    qualityScore: number;
    averageConfidence: number;
    minConfidence: number;
    validationRatio: number;
    acceptedTypes: Record<string, number>;
    acceptedSources: Record<string, number>;
  };
  replayReport: {
    replayRatio: number;
    replayRecordCount: number;
    policy: "preserve_previous_capabilities";
  };
};

export type ContinuousLearningBuildResult =
  | {
      processed: false;
      reason: "disabled" | "already_built";
      runId?: string;
      datasetManifestId?: string | null;
    }
  | {
      processed: true;
      runId: string;
      datasetManifestId: string;
      candidate: ContinuousLearningDatasetCandidate;
      promotionReport: ReturnType<typeof evaluateContinuousLearningPromotion>;
      shadow: boolean;
    };

const PRIVATE_VALUE_PATTERNS = [
  /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i,
  /\b(?:\+?\d[\s().-]?){10,}\b/,
  /\b(?:api[_-]?key|secret|token|bearer|password|jwt)\b/i,
  /\b(?:sk|pk|ghp|glpat|xoxb|xoxp)-[A-Za-z0-9_=-]{12,}\b/i,
  /\b(?:\d[ -]*?){13,19}\b/,
];

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readBoolean(record: Record<string, unknown> | null, key: string): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function sha256(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function increment(record: Record<string, number>, key: string): void {
  record[key] = (record[key] ?? 0) + 1;
}

function clampRatio(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function estimateTokens(value: string): number {
  return Math.max(1, Math.ceil(value.length / 4));
}

function hasSensitiveValue(value: string): boolean {
  return PRIVATE_VALUE_PATTERNS.some((pattern) => pattern.test(value));
}

function isMetadataTrainingEligible(metadata: Record<string, unknown> | null): boolean {
  if (!metadata) {
    return true;
  }

  if (
    readBoolean(metadata, "forgotten") === true ||
    readBoolean(metadata, "tombstone") === true ||
    readBoolean(metadata, "redacted") === true ||
    readBoolean(metadata, "trainingEligible") === false ||
    readBoolean(metadata, "privacyRedacted") === true
  ) {
    return false;
  }

  const approvalState = metadata.approvalState;
  if (approvalState === "pending" || approvalState === "rejected") {
    return false;
  }

  return true;
}

function reject(
  rejectedByReason: Record<RejectionReason, number>,
  reason: RejectionReason,
): void {
  rejectedByReason[reason] = (rejectedByReason[reason] ?? 0) + 1;
}

function buildEventIdentityHash(event: LearningEventRow): string {
  return sha256({
    id: event.id,
    type: event.type,
    key: event.key,
    source: event.source,
    createdAt: event.createdAt.toISOString(),
  });
}

function buildDedupeHash(event: LearningEventRow): string {
  return sha256({
    type: event.type,
    key: event.key,
    value: event.value.trim().toLowerCase(),
    source: event.source,
  });
}

function buildUtcDailyWindow(now: Date): { windowStart: Date; windowEnd: Date } {
  const windowEnd = new Date(Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate(),
  ));
  const windowStart = new Date(windowEnd.getTime() - 86_400_000);
  return { windowStart, windowEnd };
}

export function buildContinuousLearningDatasetCandidate(
  events: LearningEventRow[],
  options: ContinuousLearningDatasetOptions = {},
): ContinuousLearningDatasetCandidate {
  const now = options.now ?? new Date();
  const minConfidence = Math.max(0, Math.min(100, options.minConfidence ?? 60));
  const replayRatio = clampRatio(options.replayRatio ?? 20);
  const validationRatio = Math.max(0.05, Math.min(0.25, options.validationRatio ?? 0.1));
  const rejectedByReason: Record<RejectionReason, number> = {
    privacy_level_not_safe: 0,
    expired: 0,
    metadata_not_training_eligible: 0,
    sensitive_value_detected: 0,
    low_confidence: 0,
    duplicate: 0,
  };
  const dedupeHashes = new Set<string>();
  const acceptedIdentityHashes: string[] = [];
  const acceptedTypes: Record<string, number> = {};
  const acceptedSources: Record<string, number> = {};
  let confidenceTotal = 0;
  let tokenEstimate = 0;

  for (const event of [...events].sort((a, b) => a.createdAt.getTime() - b.createdAt.getTime())) {
    const metadata = readRecord(event.metadata);
    if (event.privacyLevel !== "safe") {
      reject(rejectedByReason, "privacy_level_not_safe");
      continue;
    }
    if (event.expiresAt && event.expiresAt <= now) {
      reject(rejectedByReason, "expired");
      continue;
    }
    if (!isMetadataTrainingEligible(metadata)) {
      reject(rejectedByReason, "metadata_not_training_eligible");
      continue;
    }
    if (hasSensitiveValue(event.value)) {
      reject(rejectedByReason, "sensitive_value_detected");
      continue;
    }
    if (event.confidence < minConfidence) {
      reject(rejectedByReason, "low_confidence");
      continue;
    }

    const dedupeHash = buildDedupeHash(event);
    if (dedupeHashes.has(dedupeHash)) {
      reject(rejectedByReason, "duplicate");
      continue;
    }
    dedupeHashes.add(dedupeHash);
    acceptedIdentityHashes.push(buildEventIdentityHash(event));
    confidenceTotal += event.confidence;
    tokenEstimate += estimateTokens(event.value);
    increment(acceptedTypes, event.type);
    increment(acceptedSources, event.source);
  }

  const acceptedEventCount = acceptedIdentityHashes.length;
  const dedupedEventCount = rejectedByReason.duplicate;
  const rejectedEventCount = events.length - acceptedEventCount - dedupedEventCount;
  const validationRecordCount =
    acceptedEventCount === 0 ? 0 : Math.max(1, Math.ceil(acceptedEventCount * validationRatio));
  const trainRecordCount = Math.max(0, acceptedEventCount - validationRecordCount);
  const replayRecordCount =
    replayRatio <= 0 || acceptedEventCount === 0
      ? 0
      : Math.ceil((acceptedEventCount * replayRatio) / Math.max(1, 100 - replayRatio));
  const averageConfidence = acceptedEventCount > 0 ? confidenceTotal / acceptedEventCount : 0;
  const qualityScore = Math.max(
    0,
    Math.min(
      1,
      Number(
        (
          (averageConfidence / 100) * 0.52 +
          Math.min(acceptedEventCount, 500) / 500 * 0.2 +
          Math.min(Object.keys(acceptedTypes).length, 6) / 6 * 0.16 +
          Math.min(Object.keys(acceptedSources).length, 4) / 4 * 0.12
        ).toFixed(4),
      ),
    ),
  );
  const datasetFingerprint = sha256({
    acceptedIdentityHashes,
    replayRatio,
    validationRatio,
  });

  return {
    status: acceptedEventCount > 0 ? "ready" : "draft",
    sourceEventCount: events.length,
    acceptedEventCount,
    rejectedEventCount,
    dedupedEventCount,
    replayRecordCount,
    trainRecordCount,
    validationRecordCount,
    tokenEstimate,
    datasetFingerprint,
    acceptedIdentityHashes,
    privacyReport: {
      rawEventValuesIncluded: false,
      promptContentIncluded: false,
      rejectedByReason,
      privacyRejectedCount: rejectedByReason.privacy_level_not_safe,
      sensitiveRejectedCount: rejectedByReason.sensitive_value_detected,
    },
    qualityReport: {
      qualityScore,
      averageConfidence: Number(averageConfidence.toFixed(2)),
      minConfidence,
      validationRatio,
      acceptedTypes,
      acceptedSources,
    },
    replayReport: {
      replayRatio,
      replayRecordCount,
      policy: "preserve_previous_capabilities",
    },
  };
}

export function getContinuousLearningDailyWindow(now: Date = new Date()) {
  return buildUtcDailyWindow(now);
}

export async function processContinuousLearningDailyBuild(
  app: FastifyInstance,
  input: {
    now?: Date;
    limit?: number;
  } = {},
): Promise<ContinuousLearningBuildResult> {
  const enabled = app.config?.ELYAN_CONTINUOUS_LEARNING_V2_ENABLED === true;
  const shadow = app.config?.ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED === true;
  if (!enabled && !shadow) {
    return { processed: false, reason: "disabled" };
  }

  const now = input.now ?? new Date();
  const { windowStart, windowEnd } = getContinuousLearningDailyWindow(now);
  const existingRows = await app.db
    .select({
      id: continuousLearningRuns.id,
      datasetManifestId: continuousLearningRuns.datasetManifestId,
    })
    .from(continuousLearningRuns)
    .where(and(
      eq(continuousLearningRuns.scope, "shared"),
      eq(continuousLearningRuns.windowStart, windowStart),
      eq(continuousLearningRuns.windowEnd, windowEnd),
    ))
    .limit(1);

  if (existingRows[0]) {
    return {
      processed: false,
      reason: "already_built",
      runId: existingRows[0].id,
      datasetManifestId: existingRows[0].datasetManifestId,
    };
  }

  const limit = Math.max(
    1,
    Math.min(input.limit ?? app.config?.ELYAN_CONTINUOUS_LEARNING_DAILY_BATCH_LIMIT ?? 2_000, 20_000),
  );
  const events = await app.db
    .select({
      id: learningEvents.id,
      userId: learningEvents.userId,
      taskId: learningEvents.taskId,
      type: learningEvents.type,
      key: learningEvents.key,
      value: learningEvents.value,
      confidence: learningEvents.confidence,
      scope: learningEvents.scope,
      source: learningEvents.source,
      privacyLevel: learningEvents.privacyLevel,
      metadata: learningEvents.metadata,
      expiresAt: learningEvents.expiresAt,
      createdAt: learningEvents.createdAt,
    })
    .from(learningEvents)
    .where(and(
      gte(learningEvents.createdAt, windowStart),
      lt(learningEvents.createdAt, windowEnd),
      or(isNull(learningEvents.expiresAt), gt(learningEvents.expiresAt, now)),
    ))
    .orderBy(asc(learningEvents.createdAt))
    .limit(limit);

  const candidate = buildContinuousLearningDatasetCandidate(events, {
    now,
    replayRatio: app.config?.ELYAN_CONTINUOUS_LEARNING_REPLAY_RATIO ?? 20,
  });
  const datasetStatus = enabled ? candidate.status : "draft";
  const promotionReport = evaluateContinuousLearningPromotion({
    datasetStatus,
    acceptedEventCount: candidate.acceptedEventCount,
    rejectedEventCount: candidate.rejectedEventCount,
    dedupedEventCount: candidate.dedupedEventCount,
    replayRatio: candidate.replayReport.replayRatio,
    validationRecordCount: candidate.validationRecordCount,
    privacyRejectedCount: candidate.privacyReport.privacyRejectedCount,
    sensitiveRejectedCount: candidate.privacyReport.sensitiveRejectedCount,
    qualityScore: candidate.qualityReport.qualityScore,
    securityBenchmarkPassed: null,
    latestBenchmarkScore: null,
    candidateEvaluationScore: null,
    canaryErrorRate: null,
    rollbackSignalCount: 0,
  });
  const datasetVersion = `clv2_${windowEnd.toISOString().slice(0, 10)}_${candidate.datasetFingerprint.slice(0, 12)}`;
  const candidateStatus = shadow
    ? "shadow_report"
    : promotionReport.status === "blocked"
      ? "blocked"
      : "candidate";

  const rows = await app.db.transaction(async (tx) => {
    const datasetRows = await tx
      .insert(datasetManifests)
      .values({
        ownerUserId: null,
        scope: "shared",
        name: `Elyan continuous learning ${windowEnd.toISOString().slice(0, 10)}`,
        source: "task_feedback",
        format: "instruction_jsonl",
        status: datasetStatus,
        description: "Privacy-filtered daily learning manifest; raw event values are not stored in the manifest.",
        locator: `elyan://datasets/continuous-learning/${datasetVersion}`,
        languageTags: [],
        recordCount: candidate.acceptedEventCount + candidate.replayRecordCount,
        tokenEstimate: candidate.tokenEstimate,
        lineage: "privacy_filtered_production_events",
        privacyReport: candidate.privacyReport,
        qualityReport: candidate.qualityReport,
        replayRatio: candidate.replayReport.replayRatio,
        candidateStatus,
        sourceWindowStart: windowStart,
        sourceWindowEnd: windowEnd,
        metadata: {
          sourceKind: "continuous_learning_v2",
          datasetVersion,
          datasetFingerprint: candidate.datasetFingerprint,
          sourceLineage: "privacy_filtered_production_events",
          rawEventValuesIncluded: false,
          promptContentIncluded: false,
          privacyReport: candidate.privacyReport,
          qualityReport: candidate.qualityReport,
          replayReport: candidate.replayReport,
          promotionReport,
          acceptedEventIdentityHashes: candidate.acceptedIdentityHashes.slice(0, 50),
          acceptedEventHashCount: candidate.acceptedIdentityHashes.length,
          windowStart: windowStart.toISOString(),
          windowEnd: windowEnd.toISOString(),
          createdBy: "continuous_learning_pipeline.v2",
        },
      })
      .returning({
        id: datasetManifests.id,
      });
    const datasetId = datasetRows[0]?.id;
    const runRows = await tx
      .insert(continuousLearningRuns)
      .values({
        ownerUserId: null,
        scope: "shared",
        status: promotionReport.status === "blocked" ? "blocked" : "completed",
        windowStart,
        windowEnd,
        datasetManifestId: datasetId,
        sourceEventCount: candidate.sourceEventCount,
        acceptedEventCount: candidate.acceptedEventCount,
        rejectedEventCount: candidate.rejectedEventCount,
        dedupedEventCount: candidate.dedupedEventCount,
        replayRecordCount: candidate.replayRecordCount,
        trainRecordCount: candidate.trainRecordCount,
        validationRecordCount: candidate.validationRecordCount,
        privacyReport: candidate.privacyReport,
        qualityReport: candidate.qualityReport,
        replayReport: candidate.replayReport,
        promotionReport,
        config: {
          enabled,
          shadow,
          replayRatio: candidate.replayReport.replayRatio,
          minConfidence: candidate.qualityReport.minConfidence,
          rawEventValuesIncluded: false,
        },
      })
      .returning({
        id: continuousLearningRuns.id,
      });
    return { datasetId: datasetId ?? "", runId: runRows[0]?.id ?? "" };
  });

  await createAuditLog(app, {
    actorType: "system",
    actorId: "continuous-learning-pipeline",
    action: "brain.continuous_learning.dataset_manifest_built",
    resourceType: "dataset_manifest",
    resourceId: rows.datasetId,
    status: "success",
    payload: {
      runId: rows.runId,
      datasetVersion,
      datasetStatus,
      candidateStatus,
      sourceEventCount: candidate.sourceEventCount,
      acceptedEventCount: candidate.acceptedEventCount,
      rejectedEventCount: candidate.rejectedEventCount,
      dedupedEventCount: candidate.dedupedEventCount,
      replayRecordCount: candidate.replayRecordCount,
      promotionStatus: promotionReport.status,
      promotionReasons: promotionReport.reasons,
      rawEventValuesIncluded: false,
    },
  });

  return {
    processed: true,
    runId: rows.runId,
    datasetManifestId: rows.datasetId,
    candidate,
    promotionReport,
    shadow,
  };
}
