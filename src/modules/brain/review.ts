import { createHash } from "node:crypto";
import { and, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { auditLogs, datasetManifests, learningEvents } from "../../db/schema.js";
import { createAuditLog } from "../audit/service.js";
import { ELYAN_CONSTITUTION_VERSION, ELYAN_PROMPT_PROFILE_VERSION, constitutionRuleCount } from "./constitution.js";
import { invalidateBrainProfileCache } from "./profile-cache.js";
import type { BrainEvalResult } from "./evaluator.js";

type RouteDecisionSnapshot = {
  route: string;
  mode?: string;
  privacyClass?: string;
  requiresApproval?: boolean;
  reason?: string;
  userFacingMessage?: string;
};

type BrainInteractionReviewRecord = {
  prompt: string;
  promptPreview: string;
  modelResponse: string;
  routeDecision: RouteDecisionSnapshot | null;
  expectedBehavior: string;
  evaluatorScore: number;
  boundaryScore: number;
  failureType: string | null;
  correctedAnswer: string | null;
  approvedByHuman: boolean;
  approvalState: "not_needed" | "pending" | "approved" | "rejected";
  answerSource: "model" | "backend_gate";
  gateRuleIds: string[];
  boundaryOutcome: string | null;
  selectedProfile: string;
  latencyMs: number;
  toolCalls: string[];
  success: boolean;
  constitutionVersion: string;
  promptProfileVersion: string;
  outputQuality?: BrainEvalResult["outputQuality"];
  correctionApplied?: boolean;
  repairAttempted?: boolean;
  repairApplied?: boolean;
  selectedProvider?: string | null;
  selectedModel?: string | null;
  budgetReason?: string | null;
  budgetState?: string | null;
  qualityEscalated?: boolean;
  promptTokens?: number | null;
  completionTokens?: number | null;
  firstDeltaMs?: number | null;
  reasoningPasses?: number | null;
  refinementApplied?: boolean;
  memoryUsed?: boolean;
  personalizationScope?: string | null;
  clarificationDecision?: string | null;
};

type ApprovedCorrectionDatasetExportRecord = {
  row: typeof learningEvents.$inferSelect;
  review: BrainInteractionReviewRecord;
  approvedAt: string | null;
  fingerprint: string;
  signalScore: number;
  freshnessScore: number;
  compactedRank: number;
  isFreshSignal: boolean;
};

type ApprovedCorrectionDatasetExportSummary = {
  compactionMode: "approved_corrections_compact_v1" | "sft_ready_corrections_compact_v1";
  sourceLineage: "approved_corrections";
  approvedCorrectionCount: number;
  compactedRecordCount: number;
  freshSignalCount: number;
  correctionDensity: number;
  freshSignalRatio: number;
  signalFreshnessScore: number;
  lineageScore: number;
  compactionQualityScore: number;
  compactDatasetEligible: boolean;
  freshnessWindowDays: number;
  highSignalThreshold: number;
  generatedAt: string;
  latestApprovedAt: string | null;
  oldestApprovedAt: string | null;
};

function compactText(value: string, maxLength = 280): string {
  return value.replace(/\s+/g, " ").trim().slice(0, maxLength);
}

function redactPrivatePrompt(prompt: string, routeDecision: RouteDecisionSnapshot | null): string {
  if (routeDecision?.privacyClass === "local_private" || routeDecision?.route === "pairing_required") {
    return `[redacted:${createHash("sha256").update(prompt).digest("hex").slice(0, 16)}] ${compactText(prompt, 96)}`;
  }
  return prompt;
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readNumber(record: Record<string, unknown> | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readBoolean(record: Record<string, unknown> | null, key: string): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function reviewRecordFromMetadata(metadata: Record<string, unknown>): BrainInteractionReviewRecord | null {
  const review = readRecord(metadata.review);
  if (!review) {
    return null;
  }
  return {
    prompt: readString(review, "prompt") ?? "",
    promptPreview: readString(review, "promptPreview") ?? "",
    modelResponse: readString(review, "modelResponse") ?? "",
    routeDecision: (readRecord(review.routeDecision) as RouteDecisionSnapshot | null) ?? null,
    expectedBehavior: readString(review, "expectedBehavior") ?? "",
    evaluatorScore: readNumber(review, "evaluatorScore") ?? 0,
    boundaryScore: readNumber(review, "boundaryScore") ?? 0,
    failureType: readString(review, "failureType"),
    correctedAnswer: readString(review, "correctedAnswer"),
    approvedByHuman: Boolean(review.approvedByHuman),
    approvalState:
      readString(review, "approvalState") === "approved" ||
      readString(review, "approvalState") === "rejected" ||
      readString(review, "approvalState") === "pending"
        ? (readString(review, "approvalState") as BrainInteractionReviewRecord["approvalState"])
        : "not_needed",
    answerSource: readString(review, "answerSource") === "backend_gate" ? "backend_gate" : "model",
    gateRuleIds: Array.isArray(review.gateRuleIds)
      ? review.gateRuleIds.map((item) => String(item ?? "").trim()).filter(Boolean)
      : [],
    boundaryOutcome: readString(review, "boundaryOutcome"),
    selectedProfile: readString(review, "selectedProfile") ?? "mobile_chat_fast",
    latencyMs: readNumber(review, "latencyMs") ?? 0,
    toolCalls: Array.isArray(review.toolCalls)
      ? review.toolCalls.map((item) => String(item ?? "").trim()).filter(Boolean)
      : [],
    success: review.success !== false,
    constitutionVersion: readString(review, "constitutionVersion") ?? ELYAN_CONSTITUTION_VERSION,
    promptProfileVersion: readString(review, "promptProfileVersion") ?? ELYAN_PROMPT_PROFILE_VERSION,
    outputQuality: readRecord(review.outputQuality) as BrainEvalResult["outputQuality"] | undefined,
    correctionApplied: readBoolean(review, "correctionApplied") ?? undefined,
    repairAttempted: readBoolean(review, "repairAttempted") ?? undefined,
    repairApplied: readBoolean(review, "repairApplied") ?? undefined,
    selectedProvider: readString(review, "selectedProvider"),
    selectedModel: readString(review, "selectedModel"),
    budgetReason: readString(review, "budgetReason"),
    budgetState: readString(review, "budgetState"),
    qualityEscalated: readBoolean(review, "qualityEscalated") ?? undefined,
    promptTokens: readNumber(review, "promptTokens"),
    completionTokens: readNumber(review, "completionTokens"),
    firstDeltaMs: readNumber(review, "firstDeltaMs"),
    reasoningPasses: readNumber(review, "reasoningPasses"),
    refinementApplied: readBoolean(review, "refinementApplied") ?? undefined,
    memoryUsed: readBoolean(review, "memoryUsed") ?? undefined,
    personalizationScope: readString(review, "personalizationScope"),
    clarificationDecision: readString(review, "clarificationDecision"),
  };
}

function clampRate(value: number): number {
  return Math.max(0, Math.min(1, Number(value.toFixed(4))));
}

function normalizeExportText(value: string): string {
  return compactText(value, 800).toLowerCase();
}

function parseExportTimestamp(value: string | null): Date | null {
  if (!value) {
    return null;
  }
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? new Date(timestamp) : null;
}

function buildApprovedCorrectionFingerprint(review: BrainInteractionReviewRecord): string {
  return createHash("sha256")
    .update(
      [
        normalizeExportText(review.prompt),
        normalizeExportText(review.correctedAnswer ?? review.modelResponse),
        normalizeExportText(review.failureType ?? "none"),
        normalizeExportText(review.answerSource),
        normalizeExportText(review.selectedProfile),
      ].join("\u241f"),
    )
    .digest("hex");
}

function scoreApprovedCorrectionRecord(input: {
  review: BrainInteractionReviewRecord;
  approvedAt: string | null;
  now: Date;
  mode: ApprovedCorrectionDatasetExportSummary["compactionMode"];
}) {
  const approvedAt = parseExportTimestamp(input.approvedAt);
  const ageDays = approvedAt ? Math.max(0, (input.now.getTime() - approvedAt.getTime()) / 86_400_000) : 999;
  const freshnessWindowDays = input.mode === "sft_ready_corrections_compact_v1" ? 21 : 30;
  const freshnessScore = clampRate(1 - Math.min(1, ageDays / freshnessWindowDays));
  const evaluatorScore = clampRate(input.review.evaluatorScore);
  const boundaryScore = clampRate(input.review.boundaryScore);
  const approvalSignal = input.review.approvedByHuman ? 1 : 0.5;
  const signalScore = clampRate(evaluatorScore * 0.5 + boundaryScore * 0.2 + freshnessScore * 0.2 + approvalSignal * 0.1);
  const isFreshSignal = freshnessScore >= 0.7 && evaluatorScore >= 0.75;

  return {
    approvedAt,
    freshnessScore,
    signalScore,
    isFreshSignal,
    freshnessWindowDays,
  };
}

export function buildApprovedCorrectionDatasetExport(
  records: Array<{
    row: typeof learningEvents.$inferSelect;
    review: BrainInteractionReviewRecord | null;
  }>,
  mode: ApprovedCorrectionDatasetExportSummary["compactionMode"],
  now = new Date(),
): {
  records: ApprovedCorrectionDatasetExportRecord[];
  summary: ApprovedCorrectionDatasetExportSummary;
} {
  const scored = records
    .filter((item): item is { row: typeof learningEvents.$inferSelect; review: BrainInteractionReviewRecord } => Boolean(item.review))
    .map((item) => {
      const approvedAt = readString(readRecord(item.row.metadata) ?? {}, "reviewedAt");
      const score = scoreApprovedCorrectionRecord({
        review: item.review,
        approvedAt,
        now,
        mode,
      });
      return {
        row: item.row,
        review: item.review,
        approvedAt,
        fingerprint: buildApprovedCorrectionFingerprint(item.review),
        signalScore: score.signalScore,
        freshnessScore: score.freshnessScore,
        compactedRank: 0,
        isFreshSignal: score.isFreshSignal,
      } satisfies ApprovedCorrectionDatasetExportRecord;
    })
    .sort((left, right) => {
      const scoreDelta = right.signalScore - left.signalScore;
      if (scoreDelta !== 0) {
        return scoreDelta;
      }
      const leftApproved = parseExportTimestamp(left.approvedAt)?.getTime() ?? 0;
      const rightApproved = parseExportTimestamp(right.approvedAt)?.getTime() ?? 0;
      if (rightApproved !== leftApproved) {
        return rightApproved - leftApproved;
      }
      return right.row.id.localeCompare(left.row.id);
    });

  const deduped: ApprovedCorrectionDatasetExportRecord[] = [];
  const seen = new Set<string>();
  for (const item of scored) {
    if (seen.has(item.fingerprint)) {
      continue;
    }
    seen.add(item.fingerprint);
    deduped.push(item);
  }

  const compactionCap = mode === "sft_ready_corrections_compact_v1" ? 160 : 200;
  const compacted = deduped.slice(0, compactionCap).map((item, index) => ({
    ...item,
    compactedRank: index + 1,
  }));

  const approvedCorrectionCount = records.filter((item) => Boolean(item.review)).length;
  const compactedRecordCount = compacted.length;
  const freshSignalCount = compacted.filter((item) => item.isFreshSignal).length;
  const correctionDensity =
    approvedCorrectionCount <= 0 ? 0 : clampRate(compactedRecordCount / approvedCorrectionCount);
  const freshSignalRatio = compactedRecordCount <= 0 ? 0 : clampRate(freshSignalCount / compactedRecordCount);
  const signalFreshnessScore =
    compactedRecordCount <= 0
      ? 0
      : clampRate(compacted.reduce((sum, item) => sum + item.freshnessScore, 0) / compactedRecordCount);
  const lineageScore = 1;
  const compactionQualityScore = clampRate(
    correctionDensity * 0.38 + freshSignalRatio * 0.32 + signalFreshnessScore * 0.18 + lineageScore * 0.12,
  );
  const compactDatasetEligible = compactedRecordCount > 0 && freshSignalCount > 0 && compactionQualityScore >= 0.55;
  const approvedAtTimes = compacted
    .map((item) => parseExportTimestamp(item.approvedAt))
    .filter((item): item is Date => item instanceof Date);

  return {
    records: compacted,
    summary: {
      compactionMode: mode,
      sourceLineage: "approved_corrections",
      approvedCorrectionCount,
      compactedRecordCount,
      freshSignalCount,
      correctionDensity,
      freshSignalRatio,
      signalFreshnessScore,
      lineageScore,
      compactionQualityScore,
      compactDatasetEligible,
      freshnessWindowDays: mode === "sft_ready_corrections_compact_v1" ? 21 : 30,
      highSignalThreshold: 0.75,
      generatedAt: now.toISOString(),
      latestApprovedAt:
        approvedAtTimes.length > 0
          ? approvedAtTimes.reduce((latest, current) => (current > latest ? current : latest)).toISOString()
          : null,
      oldestApprovedAt:
        approvedAtTimes.length > 0
          ? approvedAtTimes.reduce((oldest, current) => (current < oldest ? current : oldest)).toISOString()
          : null,
    },
  };
}

export async function recordBrainInteractionReview(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId?: string;
    prompt: string;
    routeDecision: RouteDecisionSnapshot | null;
    modelResponse: string;
    evaluation: BrainEvalResult;
    answerSource: "model" | "backend_gate";
    gateRuleIds?: string[];
    boundaryOutcome?: string | null;
    selectedProfile: string;
    latencyMs: number;
    toolCalls?: string[];
    requestId?: string;
    responseMetadata?: Record<string, unknown>;
  },
) {
  const promptValue = redactPrivatePrompt(input.prompt, input.routeDecision);
  const failureType =
    input.evaluation.failureTypes.find((item) => item !== "none") ?? null;
  const approvalState =
    failureType && input.evaluation.correctedAnswer ? "pending" : "not_needed";
  const review = {
    prompt: promptValue,
    promptPreview: compactText(promptValue, 140),
    modelResponse: compactText(input.modelResponse, 2_000),
    routeDecision: input.routeDecision,
    expectedBehavior: input.evaluation.expectedBehavior,
    evaluatorScore: input.evaluation.overallScore,
    boundaryScore: input.evaluation.subscores.boundary,
    failureType,
    correctedAnswer: input.evaluation.correctedAnswer,
    approvedByHuman: false,
    approvalState,
    answerSource: input.answerSource,
    gateRuleIds: input.gateRuleIds ?? [],
    boundaryOutcome: input.boundaryOutcome ?? null,
    selectedProfile: input.selectedProfile,
    latencyMs: Math.max(0, Math.round(input.latencyMs)),
    toolCalls: input.toolCalls ?? [],
    success: !failureType,
    constitutionVersion: ELYAN_CONSTITUTION_VERSION,
    promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
    outputQuality: input.evaluation.outputQuality,
    correctionApplied: Boolean(input.evaluation.correctedAnswer),
    repairAttempted: typeof input.responseMetadata?.repairAttempted === "boolean" ? input.responseMetadata.repairAttempted : undefined,
    repairApplied: typeof input.responseMetadata?.repairApplied === "boolean" ? input.responseMetadata.repairApplied : undefined,
    selectedProvider: typeof input.responseMetadata?.provider === "string" ? input.responseMetadata.provider : null,
    selectedModel: typeof input.responseMetadata?.model === "string" ? input.responseMetadata.model : null,
    budgetReason: typeof input.responseMetadata?.responseBudgetReason === "string" ? input.responseMetadata.responseBudgetReason : null,
    budgetState: typeof input.responseMetadata?.responseBudgetState === "string" ? input.responseMetadata.responseBudgetState : null,
    qualityEscalated: input.responseMetadata?.tokenBudget && typeof input.responseMetadata.tokenBudget === "object"
      ? Boolean((input.responseMetadata.tokenBudget as Record<string, unknown>).qualityEscalated)
      : undefined,
    promptTokens: typeof input.responseMetadata?.promptTokens === "number" ? input.responseMetadata.promptTokens : undefined,
    completionTokens: typeof input.responseMetadata?.completionTokens === "number" ? input.responseMetadata.completionTokens : undefined,
    firstDeltaMs: typeof input.responseMetadata?.firstDeltaMs === "number" ? input.responseMetadata.firstDeltaMs : undefined,
    reasoningPasses: typeof input.responseMetadata?.reasoningPasses === "number" ? input.responseMetadata.reasoningPasses : undefined,
    refinementApplied: typeof input.responseMetadata?.refinementApplied === "boolean" ? input.responseMetadata.refinementApplied : undefined,
    memoryUsed: typeof input.responseMetadata?.memoryUsed === "boolean" ? input.responseMetadata.memoryUsed : undefined,
    personalizationScope: typeof input.responseMetadata?.personalizationScope === "string" ? input.responseMetadata.personalizationScope : null,
    clarificationDecision: typeof input.responseMetadata?.clarificationDecision === "string" ? input.responseMetadata.clarificationDecision : null,
  } satisfies BrainInteractionReviewRecord;

  const [row] = await app.db
    .insert(learningEvents)
    .values({
      userId: input.userId,
      accountId: input.userId,
      taskId: input.taskId ?? null,
      type: "brain_interaction",
      key: "response_scored",
      value: review.modelResponse,
      confidence: Math.round(input.evaluation.overallScore * 100),
      scope: "user",
      source: "brain_eval",
      privacyLevel: "safe",
      metadata: {
        requestId: input.requestId,
        review,
        routeDecision: input.routeDecision,
        evaluatorScore: input.evaluation.overallScore,
        failureType,
        correctedAnswer: input.evaluation.correctedAnswer,
        approvedByHuman: false,
        approvalState,
        selectedProfile: input.selectedProfile,
        latencyMs: review.latencyMs,
        toolCalls: review.toolCalls,
        success: review.success,
        outputQuality: review.outputQuality,
        correctionApplied: review.correctionApplied,
        repairAttempted: review.repairAttempted,
        repairApplied: review.repairApplied,
        selectedProvider: review.selectedProvider,
        selectedModel: review.selectedModel,
        budgetReason: review.budgetReason,
        budgetState: review.budgetState,
        qualityEscalated: review.qualityEscalated,
        promptTokens: review.promptTokens,
        completionTokens: review.completionTokens,
        firstDeltaMs: review.firstDeltaMs,
        reasoningPasses: review.reasoningPasses,
        refinementApplied: review.refinementApplied,
        memoryUsed: review.memoryUsed,
        personalizationScope: review.personalizationScope,
        clarificationDecision: review.clarificationDecision,
        constitutionVersion: ELYAN_CONSTITUTION_VERSION,
        promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
      },
    })
    .returning({
      id: learningEvents.id,
    });

  if (approvalState === "pending") {
    await app.db.insert(learningEvents).values({
      userId: input.userId,
      accountId: input.userId,
      taskId: input.taskId ?? null,
      type: "brain_interaction",
      key: "correction_proposed",
      value: input.evaluation.correctedAnswer ?? "",
      confidence: Math.round(input.evaluation.overallScore * 100),
      scope: "user",
      source: "brain_eval",
      privacyLevel: "safe",
      metadata: {
        parentInteractionId: row?.id ?? null,
        failureType,
        constitutionRuleIds: input.evaluation.constitutionRuleIds,
        constitutionVersion: ELYAN_CONSTITUTION_VERSION,
        promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
      },
    });
  }

  return row?.id ?? null;
}

export async function listPendingBrainInteractionReviews(
  app: FastifyInstance,
  input: {
    limit: number;
  },
) {
  const rows = await app.db
    .select()
    .from(learningEvents)
    .where(and(eq(learningEvents.type, "brain_interaction"), eq(learningEvents.key, "response_scored")))
    .orderBy(desc(learningEvents.createdAt))
    .limit(input.limit);

  return rows
    .map((row) => ({
      id: row.id,
      createdAt: row.createdAt,
      userId: row.userId,
      taskId: row.taskId,
      review: reviewRecordFromMetadata(readRecord(row.metadata) ?? {}),
    }))
    .filter((row) => row.review && row.review.approvalState === "pending");
}

async function updateInteractionApprovalState(
  app: FastifyInstance,
  input: {
    interactionId: string;
    actorUserId: string;
    approved: boolean;
    correctedAnswer?: string | null;
    reason?: string | null;
    requestId?: string;
  },
) {
  const rows = await app.db
    .select()
    .from(learningEvents)
    .where(eq(learningEvents.id, input.interactionId))
    .limit(1);
  const interaction = rows[0];
  if (!interaction) {
    return null;
  }

  const metadata = readRecord(interaction.metadata) ?? {};
  const review = reviewRecordFromMetadata(metadata);
  if (!review) {
    return null;
  }

  const nextReview = {
    ...review,
    approvedByHuman: input.approved,
    approvalState: input.approved ? "approved" : "rejected",
    correctedAnswer: compactText(input.correctedAnswer ?? review.correctedAnswer ?? "", 2_000) || review.correctedAnswer,
  };
  const nextMetadata = {
    ...metadata,
    review: nextReview,
    approvedByHuman: input.approved,
    approvalState: nextReview.approvalState,
    correctedAnswer: nextReview.correctedAnswer,
    reviewedAt: new Date().toISOString(),
    reviewedBy: input.actorUserId,
    reviewReason: input.reason ?? null,
  };

  await app.db
    .update(learningEvents)
    .set({
      metadata: nextMetadata,
      confidence: Math.round(review.evaluatorScore * 100),
    })
    .where(eq(learningEvents.id, input.interactionId));

  await app.db.insert(learningEvents).values({
    userId: interaction.userId,
    accountId: interaction.accountId,
    taskId: interaction.taskId,
    type: "brain_interaction",
    key: input.approved ? "correction_approved" : "correction_rejected",
    value: nextReview.correctedAnswer ?? review.modelResponse,
    confidence: Math.round(review.evaluatorScore * 100),
    scope: "user",
    source: "admin_review",
    privacyLevel: "safe",
    metadata: {
      parentInteractionId: interaction.id,
      reviewedBy: input.actorUserId,
      reviewReason: input.reason ?? null,
      constitutionVersion: nextReview.constitutionVersion,
      promptProfileVersion: nextReview.promptProfileVersion,
    },
  });

  await createAuditLog(app, {
    userId: interaction.userId,
    actorType: "user",
    actorId: input.actorUserId,
    action: input.approved ? "brain.review.approve" : "brain.review.reject",
    resourceType: "learning_event",
    resourceId: interaction.id,
    status: "success",
    requestId: input.requestId,
    payload: {
      previousState: review.approvalState,
      newState: nextReview.approvalState,
      failureType: review.failureType,
      reason: input.reason ?? null,
    },
  });

  invalidateBrainProfileCache(app, interaction.userId);
  return {
    id: interaction.id,
    review: nextReview,
  };
}

export async function approveBrainInteractionCorrection(
  app: FastifyInstance,
  input: {
    interactionId: string;
    actorUserId: string;
    correctedAnswer?: string | null;
    reason?: string | null;
    requestId?: string;
  },
) {
  return updateInteractionApprovalState(app, {
    interactionId: input.interactionId,
    actorUserId: input.actorUserId,
    approved: true,
    correctedAnswer: input.correctedAnswer,
    reason: input.reason,
    requestId: input.requestId,
  });
}

export async function rejectBrainInteractionCorrection(
  app: FastifyInstance,
  input: {
    interactionId: string;
    actorUserId: string;
    reason?: string | null;
    requestId?: string;
  },
) {
  return updateInteractionApprovalState(app, {
    interactionId: input.interactionId,
    actorUserId: input.actorUserId,
    approved: false,
    reason: input.reason,
    requestId: input.requestId,
  });
}

async function listApprovedInteractions(app: FastifyInstance) {
  const rows = await app.db
    .select()
    .from(learningEvents)
    .where(and(eq(learningEvents.type, "brain_interaction"), eq(learningEvents.key, "response_scored")))
    .orderBy(desc(learningEvents.createdAt));
  return rows
    .map((row) => ({
      row,
      review: reviewRecordFromMetadata(readRecord(row.metadata) ?? {}),
    }))
    .filter((item) => item.review?.approvalState === "approved");
}

function buildDatasetJsonlLines(
  records: ApprovedCorrectionDatasetExportRecord[],
  mode: "approved_corrections_jsonl" | "sft_ready_corrections_jsonl",
  summary: ApprovedCorrectionDatasetExportSummary,
) {
  return records
    .map((item) => {
      const review = item.review;
      const metadata = readRecord(item.row.metadata);
      const approvedBy = readString(metadata, "reviewedBy");
      const approvedAt = item.approvedAt;
      if (mode === "sft_ready_corrections_jsonl") {
        return JSON.stringify({
          instruction: "Follow Elyan Constitution and return the corrected bounded answer.",
          input: review.prompt,
          expected_output: review.correctedAnswer ?? review.modelResponse,
          policy_tags: review.gateRuleIds,
          failure_type: review.failureType,
          source_event_id: item.row.id,
          approved_by: approvedBy,
          approved_at: approvedAt,
          dataset_quality: {
            compactionMode: summary.compactionMode,
            compactedRank: item.compactedRank,
            compactDatasetEligible: summary.compactDatasetEligible,
            correctionDensity: summary.correctionDensity,
            freshSignalRatio: summary.freshSignalRatio,
            signalFreshnessScore: summary.signalFreshnessScore,
            compactionQualityScore: summary.compactionQualityScore,
            lineageScore: summary.lineageScore,
            sourceLineage: summary.sourceLineage,
          },
          metadata: {
            routeDecision: review.routeDecision,
            evaluatorScore: review.evaluatorScore,
            constitutionVersion: review.constitutionVersion,
            promptProfileVersion: review.promptProfileVersion,
            compactionMode: summary.compactionMode,
            compactedRank: item.compactedRank,
            freshSignal: item.isFreshSignal,
          },
        });
      }
      return JSON.stringify({
        instruction: "Review and correct the Elyan answer so it matches backend policy and Constitution.",
        input: review.prompt,
        expected_output: review.correctedAnswer ?? review.modelResponse,
        policy_tags: review.gateRuleIds,
        failure_type: review.failureType,
        source_event_id: item.row.id,
        approved_by: approvedBy,
        approved_at: approvedAt,
        dataset_quality: {
          compactionMode: summary.compactionMode,
          compactedRank: item.compactedRank,
          compactDatasetEligible: summary.compactDatasetEligible,
          correctionDensity: summary.correctionDensity,
          freshSignalRatio: summary.freshSignalRatio,
          signalFreshnessScore: summary.signalFreshnessScore,
          compactionQualityScore: summary.compactionQualityScore,
          lineageScore: summary.lineageScore,
          sourceLineage: summary.sourceLineage,
        },
        prompt: review.prompt,
        routeDecision: review.routeDecision,
        modelResponse: review.modelResponse,
        expectedBehavior: review.expectedBehavior,
        evaluatorScore: review.evaluatorScore,
        boundaryScore: review.boundaryScore,
        failureType: review.failureType,
        correctedAnswer: review.correctedAnswer,
        approvedByHuman: review.approvedByHuman,
        answerSource: review.answerSource,
        gateRuleIds: review.gateRuleIds,
        boundaryOutcome: review.boundaryOutcome,
        selectedProfile: review.selectedProfile,
        latencyMs: review.latencyMs,
        toolCalls: review.toolCalls,
        success: review.success,
        constitutionVersion: review.constitutionVersion,
        promptProfileVersion: review.promptProfileVersion,
      });
    });
}

async function createDatasetExportManifest(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    datasetRole: "approved_corrections_jsonl" | "sft_ready_corrections_jsonl";
    lines: string[];
    summary: ApprovedCorrectionDatasetExportSummary;
    requestId?: string;
  },
) {
  const jsonl = input.lines.join("\n");
  const contentHash = createHash("sha256").update(jsonl).digest("hex");
  const [manifest] = await app.db
    .insert(datasetManifests)
    .values({
      ownerUserId: null,
      scope: "shared",
      name:
        input.datasetRole === "approved_corrections_jsonl"
          ? "Elyan approved corrections export"
          : "Elyan SFT-ready approved corrections export",
      source: "manual_curation",
      format: "instruction_jsonl",
      status: "ready",
      description:
        input.datasetRole === "approved_corrections_jsonl"
          ? "Versioned export of human-approved Elyan correction reviews."
          : "Versioned SFT-ready export derived only from human-approved Elyan corrections.",
      locator: `brain://datasets/${input.datasetRole}/${contentHash}.jsonl`,
      languageTags: ["tr", "en"],
      recordCount: input.lines.length,
      tokenEstimate: Math.max(1, Math.ceil(jsonl.length / 4)),
      metadata: {
        datasetRole: input.datasetRole,
        datasetVersion: contentHash,
        constitutionVersion: ELYAN_CONSTITUTION_VERSION,
        promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
        approvedCorrectionsOnly: true,
        sourceLineage: input.summary.sourceLineage,
        compactionMode: input.summary.compactionMode,
        approvedCorrectionCount: input.summary.approvedCorrectionCount,
        compactedRecordCount: input.summary.compactedRecordCount,
        freshSignalCount: input.summary.freshSignalCount,
        correctionDensity: input.summary.correctionDensity,
        freshSignalRatio: input.summary.freshSignalRatio,
        signalFreshnessScore: input.summary.signalFreshnessScore,
        lineageScore: input.summary.lineageScore,
        compactionQualityScore: input.summary.compactionQualityScore,
        compactDatasetEligible: input.summary.compactDatasetEligible,
        freshnessWindowDays: input.summary.freshnessWindowDays,
        highSignalThreshold: input.summary.highSignalThreshold,
        latestApprovedAt: input.summary.latestApprovedAt,
        oldestApprovedAt: input.summary.oldestApprovedAt,
        generatedAt: input.summary.generatedAt,
      },
    })
    .returning();

  await createAuditLog(app, {
    actorType: "user",
    actorId: input.actorUserId,
    action: "brain.dataset.export",
    resourceType: "dataset_manifest",
    resourceId: manifest?.id ?? null,
    status: "success",
    requestId: input.requestId,
    payload: {
      datasetRole: input.datasetRole,
      datasetVersion: contentHash,
      recordCount: input.lines.length,
      compactedRecordCount: input.summary.compactedRecordCount,
      approvedCorrectionCount: input.summary.approvedCorrectionCount,
      compactionQualityScore: input.summary.compactionQualityScore,
    },
  });

  invalidateBrainProfileCache(app);
  return {
    manifest,
    datasetVersion: contentHash,
    jsonl,
  };
}

export async function exportApprovedCorrectionsDataset(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    requestId?: string;
  },
) {
  const records = await listApprovedInteractions(app);
  const exported = buildApprovedCorrectionDatasetExport(records, "approved_corrections_compact_v1");
  const lines = buildDatasetJsonlLines(exported.records, "approved_corrections_jsonl", exported.summary);
  return createDatasetExportManifest(app, {
    actorUserId: input.actorUserId,
    datasetRole: "approved_corrections_jsonl",
    lines,
    summary: exported.summary,
    requestId: input.requestId,
  });
}

export async function exportSftReadyCorrectionsDataset(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    requestId?: string;
  },
) {
  const records = await listApprovedInteractions(app);
  const exported = buildApprovedCorrectionDatasetExport(records, "sft_ready_corrections_compact_v1");
  const lines = buildDatasetJsonlLines(exported.records, "sft_ready_corrections_jsonl", exported.summary);
  return createDatasetExportManifest(app, {
    actorUserId: input.actorUserId,
    datasetRole: "sft_ready_corrections_jsonl",
    lines,
    summary: exported.summary,
    requestId: input.requestId,
  });
}

export async function getLatestBrainBenchmarkSummary(app: FastifyInstance) {
  const rows = await app.db
    .select()
    .from(auditLogs)
    .where(eq(auditLogs.action, "brain.benchmark.completed"))
    .orderBy(desc(auditLogs.createdAt))
    .limit(1);
  const row = rows[0];
  const payload = readRecord(row?.payload) ?? {};
  return {
    latestRunAt: row?.createdAt?.toISOString() ?? null,
    latestStatus: readString(payload, "status") ?? null,
    latestOverallScore: readNumber(payload, "overallScore"),
    latestBoundaryScore: readNumber(payload, "boundaryScore"),
    latestReasoningScore: readNumber(payload, "reasoningScore"),
    latestClarificationScore: readNumber(payload, "clarificationScore"),
    latestToolUseScore: readNumber(payload, "toolUseScore"),
    latestLatencyScore: readNumber(payload, "latencyScore"),
    caseCount: readNumber(payload, "caseCount") ?? 0,
    constitutionVersion: readString(payload, "constitutionVersion") ?? ELYAN_CONSTITUTION_VERSION,
  };
}

export async function recordBrainBenchmarkSummary(
  app: FastifyInstance,
  input: {
    actorUserId?: string | null;
    overallScore: number;
    boundaryScore: number;
    reasoningScore: number;
    clarificationScore: number;
    toolUseScore: number;
    latencyScore: number;
    caseCount: number;
    status: "pass" | "warn";
    cases: Array<Record<string, unknown>>;
    requestId?: string;
  },
) {
  await createAuditLog(app, {
    userId: input.actorUserId ?? null,
    actorType: input.actorUserId ? "user" : "system",
    actorId: input.actorUserId ?? "brain-benchmark-runner",
    action: "brain.benchmark.completed",
    resourceType: "benchmark",
    resourceId: null,
    status: "success",
    requestId: input.requestId,
    payload: {
      status: input.status,
      overallScore: input.overallScore,
      boundaryScore: input.boundaryScore,
      reasoningScore: input.reasoningScore,
      clarificationScore: input.clarificationScore,
      toolUseScore: input.toolUseScore,
      latencyScore: input.latencyScore,
      caseCount: input.caseCount,
      constitutionVersion: ELYAN_CONSTITUTION_VERSION,
      constitutionRuleCount: constitutionRuleCount(),
      promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
      cases: input.cases,
    },
  });
}

export async function getApprovedCorrectionDatasetState(app: FastifyInstance) {
  const rows = await app.db
    .select()
    .from(datasetManifests)
    .where(eq(datasetManifests.status, "ready"))
    .orderBy(desc(datasetManifests.createdAt));
  const ready = rows.find((row) => readString(readRecord(row.metadata), "datasetRole") === "sft_ready_corrections_jsonl") ?? null;
  const metadata = readRecord(ready?.metadata);
  return {
    ready: Boolean(ready),
    datasetId: ready?.id ?? null,
    datasetVersion: readString(metadata, "datasetVersion"),
    compactionMode: readString(metadata, "compactionMode"),
    approvedCorrectionCount: readNumber(metadata, "approvedCorrectionCount"),
    compactedRecordCount: readNumber(metadata, "compactedRecordCount"),
    freshSignalCount: readNumber(metadata, "freshSignalCount"),
    correctionDensity: readNumber(metadata, "correctionDensity"),
    freshSignalRatio: readNumber(metadata, "freshSignalRatio"),
    signalFreshnessScore: readNumber(metadata, "signalFreshnessScore"),
    lineageScore: readNumber(metadata, "lineageScore"),
    compactionQualityScore: readNumber(metadata, "compactionQualityScore"),
    compactDatasetEligible: readBoolean(metadata, "compactDatasetEligible"),
    sourceLineage: readString(metadata, "sourceLineage"),
    freshnessWindowDays: readNumber(metadata, "freshnessWindowDays"),
    highSignalThreshold: readNumber(metadata, "highSignalThreshold"),
    latestApprovedAt: readString(metadata, "latestApprovedAt"),
    oldestApprovedAt: readString(metadata, "oldestApprovedAt"),
  };
}
