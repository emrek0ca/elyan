import { randomUUID } from "node:crypto";
import { and, desc, eq, inArray, isNull, lt, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import type { ArtifactInput, TaskStatus } from "../../contracts/domain.js";
import { artifacts, learningEvents, runtimeConnections, taskEvents, tasks } from "../../db/schema.js";
import { compactStructuredPayloadPreview } from "../../lib/blob/blob-service.js";
import { AppError, conflict, notFound } from "../../lib/errors.js";
import type { RuntimeAuthTokenPayload } from "../../types/auth.js";
import {
  recordBridgeLearningSignals,
  buildTaskUnderstanding,
  emptyUnderstanding,
  recordTaskFeedback,
  recordTaskLearningFromCompletion,
  recordTaskLearningFromCreation,
  recordConversationExchangeLearning,
} from "../../core/understanding/user-understanding-service.js";
import type { FeedbackType } from "../../core/understanding/types.js";
import { createAuditLog } from "../audit/service.js";
import {
  extractAttachmentMetadataCarrier,
  extractAttachmentCandidatesFromBrainContext,
  resolveAttachmentContextWithCache,
} from "../brain/attachment-context.js";
import { buildSharedBrainAckText } from "../brain/chat-heuristics.js";
import { maybeGenerateHostedImageArtifact } from "../brain/image-generation.js";
import { generateGovernedSharedBrainReply } from "../brain/inference.js";
import { maybeQueueAutomaticSharedBrainRefresh } from "../brain/service.js";
import { resolveAttachmentAwareSharedBrainWorkload } from "../brain/workloads.js";
import {
  composeAssistantMessageBlocks,
  sanitizeAssistantVisibleText,
  shapeAssistantMessagePayload,
} from "../chat/message-blocks.js";
import { syncChatTaskLifecycle } from "../chat/task-sync.js";
import { buildTaskTraceBlock } from "../chat/task-trace.js";
import { persistRollingSummaryToSession } from "../chat/service.js";
import { getUserDevice, RUNTIME_CONNECTION_STALE_AFTER_MS } from "../devices/service.js";
import { decideCommandRoute, resolveCommandTarget, resolvePendingDesktopQueueTarget } from "../routing-policy/service.js";
import type { CommandRouteDecision } from "../routing-policy/service.js";
import { assertMonthlyTaskUsageAllowed, recordUsageLedgerEntry, BILLING_USAGE_METRICS } from "../billing/usage-ledger.js";
import { createUpgradeOrByokRequiredError, getUserUsageAccessTruth } from "../billing/service.js";
import {
  assertAttachmentQuotaAllowedFromUsage,
  getTrialQuotaUsage,
  resolveUsageIdentityContext,
} from "../quota/service.js";
import { activeTaskStatuses, resequenceDeviceQueue } from "./queue.js";
import {
  canonicalTaskTitle,
  createStaleRuntimeConnectionError,
  createTaskFingerprint,
  createTaskRuntimeOwnershipConflictError,
  extractSharedBrainConversation,
  extractTaskChatSessionId,
  getPayloadMetadata,
  getSharedBrainFallbackMessage,
  getTaskPrompt,
  resolveIdempotentTaskMatch,
  sanitizePublicInferenceValue,
  shapeTaskFeedItem,
  shapeTaskArtifact,
} from "./service-helpers.js";
import {
  TASK_DISPATCH_LEASE_MS,
  buildTaskApprovalResumeUpdate,
  buildTaskCancellationUpdate,
  buildTaskDispatchLeaseAckUpdate,
  buildTaskDispatchLeaseReleaseUpdate,
  buildTaskDispatchLeaseUpdate,
  buildTaskRuntimeOwnershipUpdate,
  buildTaskRuntimeUpdate,
} from "./service-lifecycle.js";
import { enqueueTaskDispatch } from "./dispatch-queue.js";
import { assertTaskTransition, isTerminalTaskStatus } from "./transitions.js";
import { canUseDesktopConnections } from "../billing/catalog.js";
import { normalizeLocalDerivedMetadata } from "../../lib/derived-data.js";
import { buildLocalRenderRecipe, type LocalRenderRecipe } from "../../core/understanding/render-recipe.js";
export { canonicalTaskTitle, shapeTaskFeedItem } from "./service-helpers.js";

type ShapedTaskFeedItem = ReturnType<typeof shapeTaskFeedItem>;

const STALE_RUNTIME_TASK_AFTER_MS = 120_000;
type RuntimeConnectionSnapshot = {
  id: string;
  deviceId: string;
  userId: string;
  status: "online" | "busy" | "idle" | "offline";
  connectedAt: Date;
  lastHeartbeatAt: Date;
  disconnectedAt: Date | null;
};

type PersistableArtifactInput = ArtifactInput & {
  binaryBody?: Uint8Array;
};

type TaskReadyCallback = (input: {
  task: ShapedTaskFeedItem;
  rawTask: typeof tasks.$inferSelect;
  reused: boolean;
  routeDecision: CommandRouteDecision;
  isSharedBrain: boolean;
  blocked: boolean;
}) => Promise<void> | void;

export type RouteDecisionLogEntry = {
  taskId: string;
  origin: "mobile" | "desktop" | "unknown";
  operationalRoute: "server_brain" | "desktop_runtime";
  executionPlan: Array<"mobile_local" | "server_brain" | "desktop_runtime">;
  needsDesktop: boolean;
  selectedDeviceIgnored: boolean;
};

function normalizeRouteOrigin(value: unknown): RouteDecisionLogEntry["origin"] {
  const origin = String(value ?? "").trim().toLowerCase();
  if (origin === "mobile" || origin === "desktop") {
    return origin;
  }
  return "unknown";
}

function normalizeTaskRouteExecutionPlan(
  routeDecision: CommandRouteDecision | null | undefined,
): Array<"mobile_local" | "server_brain" | "desktop_runtime"> {
  const executionPlan = routeDecision?.taskRoute?.executionPlan ?? [];
  const normalized = executionPlan.filter(
    (value): value is "mobile_local" | "server_brain" | "desktop_runtime" =>
      value === "mobile_local" || value === "server_brain" || value === "desktop_runtime",
  );

  if (normalized.length > 0) {
    return normalized;
  }

  if (routeDecision?.taskRoute?.operationalRoute === "desktop_runtime" || routeDecision?.route === "desktop_runtime") {
    return ["desktop_runtime"];
  }

  return ["server_brain"];
}

function readInferenceString(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readInferenceNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readInferenceStringList(metadata: Record<string, unknown>, key: string): string[] {
  const value = metadata[key];
  return Array.isArray(value)
    ? value.map((item) => (typeof item === "string" ? item.trim() : "")).filter(Boolean).slice(0, 8)
    : [];
}

function readInferenceBoolean(metadata: Record<string, unknown>, key: string): boolean | null {
  const value = metadata[key];
  return typeof value === "boolean" ? value : null;
}

function buildChatStreamEnvelope(input: {
  event: "message.created" | "message.delta" | "block.preview" | "message.completed" | "message.error" | "usage.final" | "heartbeat";
  taskId: string;
  sessionId: string;
  messageId: string;
  seq: number;
  timestamp?: string;
  payload?: Record<string, unknown>;
}) {
  const timestamp = input.timestamp ?? new Date().toISOString();
  return {
    event: input.event,
    taskId: input.taskId,
    sessionId: input.sessionId,
    messageId: input.messageId,
    seq: input.seq,
    timestamp,
    ...(input.payload ?? {}),
    payload: {
      ...(input.payload ?? {}),
    },
  };
}

async function publishVolatileChatStreamEvent(
  app: FastifyInstance,
  input: {
    userId: string;
    deviceId: string;
    taskId: string;
    sessionId: string;
    messageId: string;
    event: "message.created" | "message.delta" | "block.preview" | "message.completed" | "message.error" | "usage.final" | "heartbeat";
    seq: number;
    payload?: Record<string, unknown>;
  },
) {
  await app.services.eventBus.publishVolatile({
    topic: input.event,
    userId: input.userId,
    deviceId: input.deviceId,
    taskId: input.taskId,
    payload: buildChatStreamEnvelope({
      event: input.event,
      taskId: input.taskId,
      sessionId: input.sessionId,
      messageId: input.messageId,
      seq: input.seq,
      payload: {
        sessionId: input.sessionId,
        assistantMessageId: input.messageId,
        presentation: "chat",
        ...(input.payload ?? {}),
      },
    }),
  });
}

async function publishPersistedChatStreamEvent(
  app: FastifyInstance,
  input: {
    userId: string;
    deviceId: string;
    taskId: string;
    sessionId: string;
    messageId: string;
    event: "message.created" | "message.completed" | "message.error" | "usage.final";
    seq: number;
    payload?: Record<string, unknown>;
  },
) {
  await app.services.eventBus.publishVolatile({
    topic: input.event,
    userId: input.userId,
    deviceId: input.deviceId,
    taskId: input.taskId,
    payload: buildChatStreamEnvelope({
      event: input.event,
      taskId: input.taskId,
      sessionId: input.sessionId,
      messageId: input.messageId,
      seq: input.seq,
      payload: {
        sessionId: input.sessionId,
        assistantMessageId: input.messageId,
        presentation: "chat",
        ...(input.payload ?? {}),
      },
    }),
  });
}

export function readServerBrainCompletionMetadata(metadata: Record<string, unknown>) {
  const documentSourceCount = readInferenceNumber(metadata, "documentSourceCount") ?? 0;
  const webSourceCount = readInferenceNumber(metadata, "webSourceCount") ?? 0;
  const webGroundingUsed = readInferenceBoolean(metadata, "webGroundingUsed") ?? webSourceCount > 0;
  const groundingUsed =
    readInferenceBoolean(metadata, "groundingUsed") ?? (documentSourceCount > 0 || webGroundingUsed);

  return {
    firstDeltaMs: readInferenceNumber(metadata, "firstDeltaMs"),
    fallbackUsed: Boolean(metadata.fallbackUsed),
    fallbackState: readInferenceString(metadata, "fallbackState"),
    groundingUsed,
    documentSourceCount,
    webGroundingUsed,
    webSourceCount,
    attachmentContextUsed: Boolean(metadata.attachmentContextUsed),
    attachmentContextSource: readInferenceString(metadata, "attachmentContextSource"),
    attachmentDocumentIds: readAttachmentDocumentIds(metadata.attachmentDocumentIds),
    skillUsed: Boolean(metadata.skillUsed),
    skillId: readInferenceString(metadata, "skillId"),
    skillVersion: readInferenceString(metadata, "skillVersion"),
    skillConfidence:
      typeof metadata.skillConfidence === "number" && Number.isFinite(metadata.skillConfidence)
        ? metadata.skillConfidence
        : null,
    selectedChunkHashes: readAttachmentDocumentIds(metadata.selectedChunkHashes),
    validationStatus: readInferenceString(metadata, "validationStatus"),
    cacheHit: Boolean(metadata.cacheHit),
    attachmentCacheHit: Boolean(
      typeof metadata.attachmentCacheHit === "boolean"
        ? metadata.attachmentCacheHit
        : metadata.cacheHit,
    ),
    retrievalMode: readInferenceString(metadata, "retrievalMode"),
    retrievalResultCount: readInferenceNumber(metadata, "retrievalResultCount"),
    retrievalCandidateCount: readInferenceNumber(metadata, "retrievalCandidateCount"),
    retrievalLexicalCandidateCount: readInferenceNumber(metadata, "retrievalLexicalCandidateCount"),
    retrievalSemanticCandidateCount: readInferenceNumber(metadata, "retrievalSemanticCandidateCount"),
    rerankUsed: readInferenceBoolean(metadata, "rerankUsed") ?? undefined,
    rerankDegradedReason: readInferenceString(metadata, "rerankDegradedReason"),
    completionLatencyMs: readInferenceNumber(metadata, "completionLatencyMs"),
    responseBytes: readInferenceNumber(metadata, "responseBytes"),
    qualityPolicyApplied: Boolean(metadata.qualityPolicyApplied),
    dataGroundingLevel: readInferenceString(metadata, "dataGroundingLevel"),
    personalizationScope: readInferenceString(metadata, "personalizationScope"),
    responseLanguage: readInferenceString(metadata, "responseLanguage"),
    evidenceSufficiency: readInferenceString(metadata, "evidenceSufficiency"),
    dataConfidence: readInferenceString(metadata, "dataConfidence"),
    dataQualityWarnings: readInferenceStringList(metadata, "dataQualityWarnings"),
    responseBudgetState: readInferenceString(metadata, "responseBudgetState"),
    responseBudgetReason: readInferenceString(metadata, "responseBudgetReason"),
    contextPacketCount: readInferenceNumber(metadata, "contextPacketCount"),
    contextPacketKinds: readInferenceStringList(metadata, "contextPacketKinds"),
    healthContextUsed: Boolean(metadata.healthContextUsed),
    contextFreshness: metadata.contextFreshness ?? null,
    assistantBlocks: Array.isArray(metadata.blocks) ? metadata.blocks : [],
  };
}

function resolveTaskRouteNeedsDesktop(routeDecision: CommandRouteDecision | null | undefined): boolean {
  const fallback =
    routeDecision?.route === "desktop_runtime" ||
    routeDecision?.route === "pairing_required" ||
    routeDecision?.route === "unavailable";
  return routeDecision?.taskRoute?.needsDesktop ?? fallback;
}

export function buildRouteDecisionLogEntry(input: {
  taskId: string;
  routeDecision: CommandRouteDecision | null | undefined;
  requestedTargetDeviceId?: string;
  origin?: unknown;
}): RouteDecisionLogEntry {
  const needsDesktop = resolveTaskRouteNeedsDesktop(input.routeDecision);
  return {
    taskId: input.taskId,
    origin: normalizeRouteOrigin(input.origin),
    operationalRoute:
      input.routeDecision?.taskRoute?.operationalRoute === "desktop_runtime" ||
      input.routeDecision?.route === "desktop_runtime"
        ? "desktop_runtime"
        : "server_brain",
    executionPlan: normalizeTaskRouteExecutionPlan(input.routeDecision),
    needsDesktop,
    selectedDeviceIgnored: Boolean(String(input.requestedTargetDeviceId ?? "").trim()) && !needsDesktop,
  };
}

async function logRouteDecision(
  app: FastifyInstance,
  input: {
    taskId: string;
    routeDecision: CommandRouteDecision | null | undefined;
    requestedTargetDeviceId?: string;
    origin?: unknown;
  },
) {
  if (typeof app.log?.info !== "function") {
    return;
  }

  app.log.info(buildRouteDecisionLogEntry(input), "task route decision");
}

async function notifyTaskReady(
  callback: TaskReadyCallback | undefined,
  input: {
    rawTask: typeof tasks.$inferSelect;
    reused: boolean;
    routeDecision: CommandRouteDecision;
    isSharedBrain: boolean;
    blocked?: boolean;
  },
) {
  if (!callback) {
    return;
  }

  await callback({
    task: shapeTaskFeedItem(input.rawTask),
    rawTask: input.rawTask,
    reused: input.reused,
    routeDecision: input.routeDecision,
    isSharedBrain: input.isSharedBrain,
    blocked: input.blocked ?? false,
  });
}

function extractRouteDecision(payload: Record<string, unknown>): CommandRouteDecision | null {
  const metadata = getPayloadMetadata(payload);
  const routingDecision = metadata.routeDecision ?? metadata.routingDecision;
  if (!routingDecision || typeof routingDecision !== "object" || Array.isArray(routingDecision)) {
    return null;
  }

  const typedRoutingDecision = routingDecision as Record<string, unknown>;
  const taskRoute = readRecord(typedRoutingDecision.taskRoute);
  return {
    route: typeof typedRoutingDecision.route === "string" ? (typedRoutingDecision.route as CommandRouteDecision["route"]) : "unavailable",
    taskRoute: taskRoute
      ? {
          target:
            typeof taskRoute.target === "string"
              ? (taskRoute.target as NonNullable<CommandRouteDecision["taskRoute"]>["target"])
              : "server_brain",
          operationalRoute:
            taskRoute.operationalRoute === "desktop_runtime"
              ? "desktop_runtime"
              : "server_brain",
          executionPlan: Array.isArray(taskRoute.executionPlan)
            ? taskRoute.executionPlan
                .map((value: unknown) => String(value ?? "").trim())
                .filter((value): value is "mobile_local" | "server_brain" | "desktop_runtime" =>
                  value === "mobile_local" || value === "server_brain" || value === "desktop_runtime",
                )
            : [],
          reason: typeof taskRoute.reason === "string" ? taskRoute.reason : "",
          needsDesktop: Boolean(taskRoute.needsDesktop),
          needsPrivateDesktopData: Boolean(taskRoute.needsPrivateDesktopData),
          needsUserApproval: Boolean(taskRoute.needsUserApproval),
          requiredCapabilities: Array.isArray(taskRoute.requiredCapabilities)
            ? taskRoute.requiredCapabilities.map((value: unknown) => String(value ?? "").trim()).filter(Boolean)
            : [],
        }
      : undefined,
    mode: typeof typedRoutingDecision.mode === "string" ? (typedRoutingDecision.mode as CommandRouteDecision["mode"]) : "chat",
    capabilities: Array.isArray(typedRoutingDecision.capabilities)
      ? typedRoutingDecision.capabilities.map((value: unknown) => String(value ?? "").trim()).filter(Boolean)
      : [],
    privacyClass: typeof typedRoutingDecision.privacyClass === "string"
      ? (typedRoutingDecision.privacyClass as CommandRouteDecision["privacyClass"])
      : "public_text",
    requiresApproval: Boolean(typedRoutingDecision.requiresApproval),
    reason: typeof typedRoutingDecision.reason === "string" ? typedRoutingDecision.reason : "",
    userFacingMessage: typeof typedRoutingDecision.userFacingMessage === "string" ? typedRoutingDecision.userFacingMessage : undefined,
    intent:
      typeof typedRoutingDecision.intent === "string"
        ? (typedRoutingDecision.intent as CommandRouteDecision["intent"])
        : "unsupported_request",
    confidence:
      typeof typedRoutingDecision.confidence === "number"
        ? typedRoutingDecision.confidence
        : 0,
    requiredRuntime:
      typeof typedRoutingDecision.requiredRuntime === "string"
        ? (typedRoutingDecision.requiredRuntime as CommandRouteDecision["requiredRuntime"])
        : "server",
    privacyLevel:
      typeof typedRoutingDecision.privacyLevel === "string"
        ? (typedRoutingDecision.privacyLevel as CommandRouteDecision["privacyLevel"])
        : "low",
    shouldAskClarification: Boolean(typedRoutingDecision.shouldAskClarification),
    failClosedReason:
      typeof typedRoutingDecision.failClosedReason === "string"
        ? typedRoutingDecision.failClosedReason
        : null,
    selectedWorkload:
      typeof typedRoutingDecision.selectedWorkload === "string"
        ? (typedRoutingDecision.selectedWorkload as CommandRouteDecision["selectedWorkload"])
        : "mobile_chat_fast",
  };
}

function capabilitiesIncludeQuantum(capabilities: string[]): boolean {
  return capabilities.some((capability) =>
    String(capability ?? "").trim().toLowerCase().replace(/[\s_]+/g, ".").startsWith("quantum."),
  );
}

function buildQuantumTaskSnapshot(input: {
  capabilities: string[];
  status?: TaskStatus | "pending";
  ready?: boolean;
  fallbackReason?: string;
}) {
  if (!capabilitiesIncludeQuantum(input.capabilities)) {
    return null;
  }
  return {
    mode: "hybrid",
    ready: input.ready ?? input.status !== "failed",
    supportedProblemClasses: ["qubo", "ising", "qaoa", "vqe"],
    solver: "qiskit_simulator",
    problemClass: "optimization",
    benchmarkStatus:
      input.status === "completed"
        ? "completed"
        : input.status === "failed"
          ? "failed"
          : "pending",
    fallbackReason: input.fallbackReason,
    lastBenchmarkScore: undefined,
  };
}

function compactTextPreview(value: unknown, maxLength = 320): string | null {
  const normalized = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  if (!normalized) {
    return null;
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function estimateTokenCount(value: string): number {
  const normalized = value.trim();
  if (!normalized) {
    return 0;
  }
  return Math.max(1, Math.ceil(normalized.length / 4));
}

function compactJsonEnvelope(value: unknown): Record<string, unknown> | null {
  const record = readRecord(value);
  if (!record) {
    return null;
  }

  const artifactIds = Array.isArray(record.artifacts)
    ? record.artifacts
        .map((item) => readRecord(item)?.id)
        .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        .slice(0, 8)
    : [];
  const documentIds = readAttachmentDocumentIds(record.attachmentDocumentIds).slice(0, 8);

  const compact = {
    ...(typeof record.route === "string" ? { route: record.route } : {}),
    ...(typeof record.reason === "string" ? { reason: record.reason } : {}),
    ...(typeof record.workload === "string" ? { workload: record.workload } : {}),
    ...(typeof record.presentation === "string" ? { presentation: record.presentation } : {}),
    ...(typeof record.latencyMs === "number" ? { latencyMs: record.latencyMs } : {}),
    ...(typeof record.promptTokens === "number" ? { promptTokens: record.promptTokens } : {}),
    ...(typeof record.completionTokens === "number" ? { completionTokens: record.completionTokens } : {}),
    ...(typeof record.totalTokens === "number" ? { totalTokens: record.totalTokens } : {}),
    ...(typeof record.firstDeltaMs === "number" ? { firstDeltaMs: record.firstDeltaMs } : {}),
    ...(typeof record.fallbackUsed === "boolean" ? { fallbackUsed: record.fallbackUsed } : {}),
    ...(typeof record.groundingUsed === "boolean" ? { groundingUsed: record.groundingUsed } : {}),
    ...(typeof record.documentSourceCount === "number" ? { documentSourceCount: record.documentSourceCount } : {}),
    ...(typeof record.webSourceCount === "number" ? { webSourceCount: record.webSourceCount } : {}),
    ...(typeof record.artifactCount === "number" ? { artifactCount: record.artifactCount } : {}),
    ...(documentIds.length > 0 ? { attachmentDocumentIds: documentIds } : {}),
    ...(artifactIds.length > 0 ? { artifactIds } : {}),
  };

  return Object.keys(compact).length > 0 ? compact : null;
}

function buildArtifactPreviewPayload(artifact: PersistableArtifactInput): Record<string, unknown> | null {
  const compactPayload = compactStructuredPayloadPreview(artifact.payload);
  if (compactPayload) {
    return compactPayload;
  }

  const previewText = compactTextPreview(artifact.textContent);
  return previewText ? { previewText } : null;
}

async function storeTaskJsonBlob(
  app: FastifyInstance,
  input: {
    taskId: string;
    slot: "payload" | "result" | "approval_request";
    scope: "task_payload" | "task_result" | "task_approval_request";
    value: unknown;
  },
) {
  return app.services?.blobs?.storeJson({
    ownerType: "task",
    ownerId: input.taskId,
    slot: input.slot,
    scope: input.scope,
    value: input.value,
  });
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readSafeString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim().slice(0, 160) : null;
}

function readSafeNumber(record: Record<string, unknown> | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

async function resolveTaskAttachmentContext(
  app: FastifyInstance,
  payload: Record<string, unknown>,
  prompt: string,
) {
  return resolveAttachmentContextWithCache(app.services.reliability.store, {
    prompt,
    metadata: getPayloadMetadata(payload),
    sessionAttachmentCandidates: extractAttachmentCandidatesFromBrainContext(
      readRecord(payload.brainContext),
    ),
  });
}

function readAttachmentDocumentIds(value: unknown): string[] {
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "string" ? item.trim() : ""))
        .filter(Boolean)
    : [];
}

function summarizeTaskAttachmentUsage(metadata: Record<string, unknown>): {
  documentUploads: number;
  imageUploads: number;
} {
  const carrier = extractAttachmentMetadataCarrier(metadata);
  if (!carrier) {
    return {
      documentUploads: 0,
      imageUploads: 0,
    };
  }

  const attachmentItems = Array.isArray(carrier.attachments) ? carrier.attachments : [];
  const records =
    attachmentItems.length > 0
      ? attachmentItems.filter(
          (item): item is Record<string, unknown> =>
            item != null && typeof item === "object" && !Array.isArray(item),
        )
      : [carrier];

  let documentUploads = 0;
  let imageUploads = 0;

  for (const record of records) {
    const mimeType = typeof record.mimeType === "string" ? record.mimeType.trim().toLowerCase() : "";
    if (mimeType.startsWith("image/")) {
      imageUploads += 1;
      continue;
    }

    if (
      mimeType ||
      record.document_analysis != null ||
      record.documentAnalysis != null ||
      record.compactDocument != null ||
      record.documentEnvelope != null ||
      record.envelope != null ||
      record.fastPreview != null ||
      record.deepContext != null
    ) {
      documentUploads += 1;
    }
  }

  return {
    documentUploads,
    imageUploads,
  };
}

function extractQuantumLearningSignal(result: Record<string, unknown> | undefined) {
  const quantum = readRecord(result?.quantum) ?? readRecord(readRecord(result?.metadata)?.quantum) ?? readRecord(result);
  const mode = readSafeString(quantum, "mode");
  const solver = readSafeString(quantum, "solver");
  const problemClass = readSafeString(quantum, "problemClass");
  const benchmarkStatus = readSafeString(quantum, "benchmarkStatus");
  const fallbackReason = readSafeString(quantum, "fallbackReason");
  const lastBenchmarkScore =
    readSafeNumber(quantum, "lastBenchmarkScore") ??
    readSafeNumber(quantum, "benchmarkScore") ??
    readSafeNumber(quantum, "quantumBenchmarkScore");

  if (!mode && !solver && !problemClass && benchmarkStatus !== "completed" && lastBenchmarkScore === null) {
    return null;
  }

  return {
    mode: mode ?? "hybrid",
    solver: solver ?? "unknown",
    problemClass: problemClass ?? "optimization",
    benchmarkStatus: benchmarkStatus ?? "completed",
    fallbackReason,
    lastBenchmarkScore,
  };
}

async function recordQuantumLearningSignal(
  app: FastifyInstance,
  input: {
    task: typeof tasks.$inferSelect;
    result?: Record<string, unknown>;
  },
) {
  const signal = extractQuantumLearningSignal(input.result);
  if (!signal) {
    return;
  }

  await app.db.insert(learningEvents).values({
    userId: input.task.userId,
    accountId: input.task.userId,
    taskId: input.task.id,
    type: "quantum",
    key: "benchmark",
    value: JSON.stringify(signal),
    confidence: signal.lastBenchmarkScore !== null ? 82 : 68,
    scope: "user",
    source: "runtime",
    privacyLevel: "safe",
    metadata: {
      signal: "quantum_task_result",
      route: "desktop_runtime",
      benchmarkStatus: signal.benchmarkStatus,
    },
  });
}

async function insertTaskEvent(
  app: FastifyInstance,
  input: {
    taskId: string;
    status: TaskStatus;
    message?: string;
    payload?: Record<string, unknown>;
  },
) {
  const eventId = randomUUID();
  const payloadBlob = input.payload
    ? await app.services?.blobs?.storeJson({
        ownerType: "task_event",
        ownerId: eventId,
        slot: "payload",
        scope: "task_event_payload",
        value: input.payload,
      })
    : null;
  await app.db.insert(taskEvents).values({
    id: eventId,
    taskId: input.taskId,
    status: input.status,
    message: input.message,
    payload: compactJsonEnvelope(input.payload),
    payloadBlobId: payloadBlob?.blobId ?? null,
  });
}

function isTaskDispatchLeaseActive(task: typeof tasks.$inferSelect, now = new Date()): boolean {
  if (!task.dispatchLeaseExpiresAt || !task.dispatchLeaseId) {
    return false;
  }
  return task.dispatchLeaseExpiresAt.getTime() > now.getTime();
}

function getTaskDispatchLeaseSnapshot(task: typeof tasks.$inferSelect) {
  if (!task.dispatchLeaseId) {
    return null;
  }
  return {
    leaseId: task.dispatchLeaseId,
    issuedAt: task.dispatchLeaseIssuedAt?.toISOString() ?? null,
    expiresAt: task.dispatchLeaseExpiresAt?.toISOString() ?? null,
    ackAt: task.dispatchAckAt?.toISOString() ?? null,
    attemptCount: task.dispatchAttemptCount ?? 0,
    runtimeConnectionId: task.runtimeConnectionId ?? null,
  };
}

async function persistArtifacts(app: FastifyInstance, taskId: string, items: PersistableArtifactInput[]) {
  if (!items.length) {
    return [];
  }

  const rows: Array<typeof artifacts.$inferSelect> = [];

  for (const item of items) {
    const artifactId = randomUUID();
    const metadata = normalizeLocalDerivedMetadata(item.metadata ?? {});
    let bodyBlob = null;

    if (item.binaryBody && item.binaryBody.byteLength > 0) {
      bodyBlob = await app.services?.blobs?.storeBinary({
        ownerType: "artifact",
        ownerId: artifactId,
        slot: "body",
        scope: "artifact_body",
        value: item.binaryBody,
        contentType: item.contentType,
      });
    } else if (item.payload || item.textContent) {
      bodyBlob = await app.services?.blobs?.storeJson({
        ownerType: "artifact",
        ownerId: artifactId,
        slot: "body",
        scope: "artifact_body",
        value: {
          kind: item.kind,
          name: item.name,
          contentType: item.contentType,
          storageKey: item.storageKey ?? null,
          textContent: item.textContent ?? null,
          payload: item.payload ?? null,
          metadata,
        },
      });
    }

    const previewPayload = buildArtifactPreviewPayload(item);
    const inlinePreviewText = compactTextPreview(
      item.textContent ??
        (typeof previewPayload?.previewText === "string" ? previewPayload.previewText : undefined),
    );

    const insertedRows = await app.db
      .insert(artifacts)
      .values({
        id: artifactId,
        taskId,
        kind: item.kind,
        name: item.name,
        contentType: item.contentType,
        storageKey: bodyBlob?.storageKey ?? item.storageKey ?? null,
        textContent: inlinePreviewText,
        payload: previewPayload,
        bodyBlobId: bodyBlob?.blobId ?? null,
        contentHash: bodyBlob?.contentHash ?? null,
        byteLength: bodyBlob?.byteLength ?? null,
        contentEncoding:
          bodyBlob?.contentEncoding && bodyBlob.contentEncoding !== "identity"
            ? bodyBlob.contentEncoding
            : null,
        downloadable: Boolean(bodyBlob?.blobId || item.storageKey),
        viewerHint: null,
        metadata,
      })
      .returning();
    if (insertedRows[0]) {
      rows.push(insertedRows[0]);
    }
  }

  return rows;
}

function buildStructuredOutputArtifact(
  taskId: string,
  recipe: LocalRenderRecipe,
): ArtifactInput {
  return {
    kind: "structured_output",
    name: `${recipe.output_type}.json`,
    contentType: "application/json",
    textContent: JSON.stringify(recipe, null, 2),
    payload: recipe as unknown as Record<string, unknown>,
    metadata: normalizeLocalDerivedMetadata({
      taskId,
      output_type: recipe.output_type,
      format: recipe.format,
      render_on: recipe.render_on,
      structured_output: true,
    }),
  };
}

async function getTaskForUser(app: FastifyInstance, taskId: string, userId: string) {
  const rows = await app.db.select().from(tasks).where(and(eq(tasks.id, taskId), eq(tasks.userId, userId))).limit(1);
  const task = rows[0];

  if (!task) {
    throw notFound("Task not found");
  }

  return task;
}

async function getTaskForRuntime(app: FastifyInstance, taskId: string, auth: RuntimeAuthTokenPayload) {
  const rows = await app.db
    .select()
    .from(tasks)
    .where(and(eq(tasks.id, taskId), eq(tasks.userId, auth.sub), eq(tasks.targetDeviceId, auth.deviceId)))
    .limit(1);

  const task = rows[0];

  if (!task) {
    throw notFound("Task not found for this runtime");
  }

  return task;
}

export async function getTaskById(app: FastifyInstance, taskId: string) {
  const rows = await app.db.select().from(tasks).where(eq(tasks.id, taskId)).limit(1);
  return rows[0] ?? null;
}

async function hydrateTaskJsonValue<T>(
  app: FastifyInstance,
  inlineValue: T,
  blobId?: string | null,
): Promise<T> {
  if (!blobId) {
    return inlineValue;
  }

  return ((await app.services?.blobs?.hydrateJson<T>(blobId)) ?? inlineValue) as T;
}

async function shapePublicArtifactRecord(
  app: FastifyInstance,
  artifact: typeof artifacts.$inferSelect,
) {
  const downloadUrl = artifact.bodyBlobId
    ? await app.services?.blobs?.createDownloadUrl({
        blobId: artifact.bodyBlobId,
        fileName: artifact.name,
        contentType: artifact.contentType,
      })
    : null;

  return shapeTaskArtifact({
    ...artifact,
    downloadUrl,
  });
}

async function getExistingTaskForIdempotency(
  db: Pick<FastifyInstance["db"], "select">,
  input: {
    userId: string;
    idempotencyKey?: string;
    fingerprint?: string;
  },
) {
  if (!input.idempotencyKey || !input.fingerprint) {
    return null;
  }

  const rows = await db
    .select()
    .from(tasks)
    .where(and(eq(tasks.userId, input.userId), eq(tasks.idempotencyKey, input.idempotencyKey)))
    .limit(1);

  const existingTask = rows[0];
  return resolveIdempotentTaskMatch(existingTask, input);
}

async function getActiveRuntimeConnection(app: FastifyInstance, auth: RuntimeAuthTokenPayload) {
  const rows = await app.db
    .select({
      id: runtimeConnections.id,
    })
    .from(runtimeConnections)
    .where(
      and(
        eq(runtimeConnections.id, auth.connectionId),
        eq(runtimeConnections.deviceId, auth.deviceId),
        eq(runtimeConnections.userId, auth.sub),
        isNull(runtimeConnections.disconnectedAt),
      ),
    )
    .limit(1);

  const connection = rows[0];

  if (!connection) {
    throw createStaleRuntimeConnectionError();
  }

  return connection;
}

async function getRuntimeConnectionSnapshot(
  app: FastifyInstance,
  runtimeConnectionId?: string | null,
): Promise<RuntimeConnectionSnapshot | null> {
  if (!runtimeConnectionId) {
    return null;
  }

  const rows = await app.db
    .select({
      id: runtimeConnections.id,
      deviceId: runtimeConnections.deviceId,
      userId: runtimeConnections.userId,
      status: runtimeConnections.status,
      connectedAt: runtimeConnections.connectedAt,
      lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
      disconnectedAt: runtimeConnections.disconnectedAt,
    })
    .from(runtimeConnections)
    .where(eq(runtimeConnections.id, runtimeConnectionId))
    .limit(1);

  return rows[0] ?? null;
}

async function getLatestActiveRuntimeConnectionForDevice(
  app: FastifyInstance,
  input: {
    userId: string;
    deviceId: string;
  },
): Promise<RuntimeConnectionSnapshot | null> {
  const rows = await app.db
    .select({
      id: runtimeConnections.id,
      deviceId: runtimeConnections.deviceId,
      userId: runtimeConnections.userId,
      status: runtimeConnections.status,
      connectedAt: runtimeConnections.connectedAt,
      lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
      disconnectedAt: runtimeConnections.disconnectedAt,
    })
    .from(runtimeConnections)
    .where(
      and(
        eq(runtimeConnections.userId, input.userId),
        eq(runtimeConnections.deviceId, input.deviceId),
        isNull(runtimeConnections.disconnectedAt),
      ),
    )
    .orderBy(desc(runtimeConnections.connectedAt))
    .limit(1);

  return rows[0] ?? null;
}

function isRuntimeConnectionFresh(connection: RuntimeConnectionSnapshot | null, now = new Date()) {
  if (!connection || connection.disconnectedAt || connection.status === "offline") {
    return false;
  }

  return now.getTime() - connection.lastHeartbeatAt.getTime() <= RUNTIME_CONNECTION_STALE_AFTER_MS;
}

async function dispatchRuntimeTaskLease(
  app: FastifyInstance,
  input: {
    task: typeof tasks.$inferSelect;
    runtimeConnectionId?: string | null;
    leaseMs?: number;
    now?: Date;
  },
) {
  const leaseResult = await issueTaskDispatchLease(app, {
    taskId: input.task.id,
    runtimeConnectionId: input.runtimeConnectionId ?? input.task.runtimeConnectionId ?? null,
    leaseMs: input.leaseMs,
    now: input.now,
  });

  const lease = leaseResult?.lease ?? null;
  if (!leaseResult || !lease) {
    return {
      dispatched: false,
      task: input.task,
      lease: null,
      reused: leaseResult?.reused ?? false,
    } as const;
  }

  const dispatched = app.services.realtimeHub.sendToRuntime(input.task.targetDeviceId, {
    type: "task.dispatch",
    task: leaseResult.task,
    leaseId: lease.leaseId,
    leaseExpiresAt: lease.expiresAt,
  });

  return {
    dispatched,
    task: leaseResult.task,
    lease,
    reused: leaseResult.reused,
  } as const;
}

export async function issueTaskDispatchLease(
  app: FastifyInstance,
  input: {
    taskId: string;
    runtimeConnectionId?: string | null;
    leaseMs?: number;
    now?: Date;
  },
) {
  const task = await getTaskById(app, input.taskId);
  if (!task) {
    throw notFound("Task not found");
  }

  if (!activeTaskStatuses.includes(task.status)) {
    return null;
  }

  const now = input.now ?? new Date();
  if (task.dispatchLeaseId && isTaskDispatchLeaseActive(task, now)) {
    return {
      task,
      lease: getTaskDispatchLeaseSnapshot(task),
      reused: true,
    } as const;
  }

  const leaseId = randomUUID();
  const rows = await app.db
    .update(tasks)
    .set(
      buildTaskDispatchLeaseUpdate({
        leaseId,
        runtimeConnectionId: input.runtimeConnectionId ?? task.runtimeConnectionId ?? null,
        now,
        leaseMs: input.leaseMs ?? TASK_DISPATCH_LEASE_MS,
        attemptCount: (task.dispatchAttemptCount ?? 0) + 1,
      }),
    )
    .where(eq(tasks.id, task.id))
    .returning();
  const updatedTask = rows[0] ?? task;
  const lease = getTaskDispatchLeaseSnapshot(updatedTask);
  if (!lease) {
    return null;
  }

  await insertTaskEvent(app, {
    taskId: updatedTask.id,
    status: updatedTask.status,
    message: "Runtime lease issued",
    payload: {
      lease,
      routedAt: now.toISOString(),
    },
  });

  await publishTaskEvent(app, updatedTask, "runtime.leased", {
    task: shapeTaskFeedItem(updatedTask),
    lease,
  });

  return {
    task: updatedTask,
    lease,
    reused: false,
  } as const;
}

export async function acknowledgeTaskDispatchLease(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  input: {
    taskId: string;
    leaseId: string;
    acceptedAt?: string;
  },
) {
  const task = await getTaskForRuntime(app, input.taskId, auth);
  const ownedTask = await ensureTaskRuntimeOwnership(app, task, auth);

  if (!ownedTask.dispatchLeaseId || ownedTask.dispatchLeaseId !== input.leaseId) {
    throw conflict("Task dispatch lease is not active for this runtime");
  }

  if (!isTaskDispatchLeaseActive(ownedTask)) {
    throw conflict("Task dispatch lease has expired");
  }

  const acceptedAt = parseRuntimeAcceptedAt(input.acceptedAt);

  const rows = await app.db
    .update(tasks)
    .set(
      buildTaskDispatchLeaseAckUpdate({
        runtimeConnectionId: auth.connectionId,
        leaseId: input.leaseId,
        acceptedAt,
      }),
    )
    .where(eq(tasks.id, ownedTask.id))
    .returning();
  const updatedTask = rows[0] ?? ownedTask;
  const effectiveAcceptedAt =
    updatedTask.dispatchAckAt?.toISOString() ??
    acceptedAt?.toISOString() ??
    new Date().toISOString();

  await insertTaskEvent(app, {
    taskId: updatedTask.id,
    status: "running",
    message: "Runtime lease accepted after local journal persistence",
    payload: {
      leaseId: input.leaseId,
      runtimeConnectionId: auth.connectionId,
      acceptedAt: effectiveAcceptedAt,
      acceptanceMode: "local_journal_persisted",
    },
  });

  await publishTaskEvent(app, updatedTask, "runtime.acked", {
    task: shapeTaskFeedItem(updatedTask),
    leaseId: input.leaseId,
    acceptedAt: effectiveAcceptedAt,
    acceptanceMode: "local_journal_persisted",
  });

  return {
    task: updatedTask,
    leaseId: input.leaseId,
    acceptedAt: effectiveAcceptedAt,
  };
}

function parseRuntimeAcceptedAt(value: string | undefined): Date | undefined {
  const normalized = String(value ?? "").trim();
  if (!normalized) {
    return undefined;
  }
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) {
    return undefined;
  }
  return parsed;
}

async function ensureTaskRuntimeOwnership(
  app: FastifyInstance,
  task: typeof tasks.$inferSelect,
  auth: RuntimeAuthTokenPayload,
) {
  const activeConnection = await getActiveRuntimeConnection(app, auth);

  if (!task.runtimeConnectionId || task.runtimeConnectionId === activeConnection.id) {
    if (task.runtimeConnectionId === activeConnection.id) {
      return task;
    }

    const rows = await app.db
      .update(tasks)
      .set(buildTaskRuntimeOwnershipUpdate({ runtimeConnectionId: activeConnection.id }))
      .where(eq(tasks.id, task.id))
      .returning();

    return rows[0] ?? { ...task, runtimeConnectionId: activeConnection.id };
  }

  const previousRows = await app.db
    .select({
      id: runtimeConnections.id,
      disconnectedAt: runtimeConnections.disconnectedAt,
    })
    .from(runtimeConnections)
    .where(eq(runtimeConnections.id, task.runtimeConnectionId))
    .limit(1);

  const previousConnection = previousRows[0];

  if (previousConnection && !previousConnection.disconnectedAt) {
    throw createTaskRuntimeOwnershipConflictError({
      taskId: task.id,
      activeConnectionId: activeConnection.id,
      owningConnectionId: previousConnection.id,
    });
  }

  const reboundRows = await app.db
    .update(tasks)
    .set(buildTaskRuntimeOwnershipUpdate({ runtimeConnectionId: activeConnection.id }))
    .where(eq(tasks.id, task.id))
    .returning();

  return reboundRows[0] ?? { ...task, runtimeConnectionId: activeConnection.id };
}

function shouldSkipDuplicateRuntimeTerminalUpdate(
  task: Pick<typeof tasks.$inferSelect, "status">,
  nextStatus: TaskStatus,
): boolean {
  return isTerminalTaskStatus(task.status) && task.status === nextStatus;
}

async function publishTaskEvent(app: FastifyInstance, task: typeof tasks.$inferSelect, topic: string, payload: unknown): Promise<void> {
  await app.services.eventBus.publish({
    topic,
    userId: task.userId,
    deviceId: task.targetDeviceId,
    taskId: task.id,
    payload,
  });
}

function staleRuntimeFailureForTarget(target: Awaited<ReturnType<typeof getUserDevice>> | null) {
  const targetStatus = target?.targetStatus ?? "missing";
  const code =
    targetStatus === "offline" || targetStatus === "runtime_stale"
      ? "runtime_unavailable"
      : targetStatus === "inactive"
        ? "pairing_required"
        : targetStatus === "backend_unreachable"
          ? "backend_unreachable"
          : "runtime_unavailable";
  const message =
    code === "pairing_required"
      ? "Bu görev için önce masaüstünü yeniden eşleştirmen gerekiyor."
      : code === "backend_unreachable"
        ? "Backend şu anda masaüstü runtime'a güvenli şekilde görev iletemiyor."
        : "Masaüstü runtime şu anda görev alamıyor. Lütfen Elyan Desktop'ı açıp tekrar deneyin.";

  return {
    code,
    message,
    targetStatus,
  };
}

export async function reconcileStaleRuntimeTasks(
  app: FastifyInstance,
  input: {
    userId: string;
    targetDeviceId?: string;
    limit?: number;
    now?: Date;
  },
) {
  const lockKey = `lock:task-reconcile:${input.userId}:${input.targetDeviceId ?? "all"}`;
  const lockOwner = `backend:${input.now?.getTime() ?? Date.now()}`;
  const reliability = app.services?.reliability;
  const lockAcquired = reliability ? await reliability.store.acquireLock(lockKey, lockOwner, 30_000) : true;
  if (!lockAcquired) {
    return {
      reconciled: [],
    };
  }

  const now = input.now ?? new Date();
  try {
    const cutoff = new Date(now.getTime() - STALE_RUNTIME_TASK_AFTER_MS);
    const conditions = [
      eq(tasks.userId, input.userId),
      or(
        and(
          eq(tasks.status, "planning" as TaskStatus),
          or(
            lt(tasks.dispatchLeaseExpiresAt, now),
            and(isNull(tasks.dispatchLeaseExpiresAt), lt(tasks.updatedAt, cutoff)),
          ),
        ),
        and(eq(tasks.status, "running" as TaskStatus), lt(tasks.updatedAt, cutoff)),
      ),
    ];

    if (input.targetDeviceId) {
      conditions.push(eq(tasks.targetDeviceId, input.targetDeviceId));
    }

    const candidates = await app.db
      .select()
      .from(tasks)
      .where(and(...conditions))
      .orderBy(tasks.updatedAt)
      .limit(input.limit ?? 50);

    const reconciled: Array<ReturnType<typeof shapeTaskFeedItem>> = [];
    const resequenceTargets = new Set<string>();

    for (const task of candidates) {
      const target = await getUserDevice(app, task.userId, task.targetDeviceId);
      const targetStatus = target?.targetStatus ?? "missing";
      const lease = getTaskDispatchLeaseSnapshot(task);
      const reason = task.status === "running" ? "runtime_execution_stale" : "dispatch_lease_expired";

      if (task.status === "running") {
        const owningConnection = await getRuntimeConnectionSnapshot(app, task.runtimeConnectionId ?? null);
        if (isRuntimeConnectionFresh(owningConnection, now)) {
          continue;
        }
      } else if (target?.canReceiveTasks) {
        const activeConnection = await getLatestActiveRuntimeConnectionForDevice(app, {
          userId: task.userId,
          deviceId: task.targetDeviceId,
        });
        if (isRuntimeConnectionFresh(activeConnection, now)) {
          const redispatch = await dispatchRuntimeTaskLease(app, {
            task,
            runtimeConnectionId: activeConnection?.id ?? null,
            leaseMs: TASK_DISPATCH_LEASE_MS,
            now,
          });
          if (redispatch.dispatched) {
            continue;
          }
        }
      }

      const rows = await app.db
        .update(tasks)
        .set(
          buildTaskDispatchLeaseReleaseUpdate({
            now,
            clearRuntimeConnection: true,
          }),
        )
        .where(eq(tasks.id, task.id))
        .returning();
      const updatedTask = rows[0] ?? {
        ...task,
        status: "queued" as TaskStatus,
        dispatchLeaseId: null,
        dispatchLeaseIssuedAt: null,
        dispatchLeaseExpiresAt: null,
        dispatchAckAt: null,
        runtimeConnectionId: null,
        updatedAt: now,
      };

      await insertTaskEvent(app, {
        taskId: updatedTask.id,
        status: "queued",
        message: "Task returned to queue",
        payload: {
          reconciled: true,
          reason,
          targetStatus,
          lease,
        },
      });
      await publishTaskEvent(app, updatedTask, "command.queued", {
        task: shapeTaskFeedItem(updatedTask),
        reconciled: true,
        reason,
        targetStatus,
        lease,
      });
      await syncChatTaskLifecycle(app, {
        originalTask: task,
        updatedTask,
        message: "Task returned to queue",
      });

      await reliability?.clearTaskDispatchLock(updatedTask.id);
      resequenceTargets.add(updatedTask.targetDeviceId);
      reconciled.push(shapeTaskFeedItem(updatedTask));
    }

    for (const targetDeviceId of resequenceTargets) {
      await resequenceDeviceQueue(app, targetDeviceId);
    }

    return {
      reconciled,
    };
  } finally {
    if (reliability) {
      await reliability.store.releaseLock(lockKey, lockOwner);
    }
  }
}

async function completeServerBrainTask(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId: string;
    responseText: string;
    provider: string;
    model: string;
    route: string;
    workload: string;
    latencyMs: number;
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
    firstDeltaMs?: number | null;
    completionLatencyMs?: number | null;
    responseBytes?: number | null;
    fallbackUsed?: boolean;
    fallbackState?: string | null;
    groundingUsed?: boolean;
    documentSourceCount?: number;
    webGroundingUsed?: boolean;
    webSourceCount?: number;
    attachmentContextUsed?: boolean;
    attachmentContextSource?: string | null;
    attachmentDocumentIds?: string[];
    skillUsed?: boolean;
    skillId?: string | null;
    skillVersion?: string | null;
    skillConfidence?: number | null;
    selectedChunkHashes?: string[];
    validationStatus?: string | null;
    cacheHit?: boolean;
    attachmentCacheHit?: boolean;
    retrievalMode?: string | null;
    retrievalResultCount?: number | null;
    retrievalCandidateCount?: number | null;
    retrievalLexicalCandidateCount?: number | null;
    retrievalSemanticCandidateCount?: number | null;
    rerankUsed?: boolean;
    rerankDegradedReason?: string | null;
    qualityPolicyApplied?: boolean;
    dataGroundingLevel?: string | null;
    personalizationScope?: string | null;
    responseLanguage?: string | null;
    evidenceSufficiency?: string | null;
    dataConfidence?: string | null;
    dataQualityWarnings?: string[];
    responseBudgetState?: string | null;
    responseBudgetReason?: string | null;
    contextPacketCount?: number | null;
    contextPacketKinds?: string[];
    healthContextUsed?: boolean;
    contextFreshness?: unknown;
    assistantBlocks?: unknown[];
  },
) {
  const task = await getTaskById(app, input.taskId);
  if (!task || task.userId !== input.userId) {
    throw notFound("Task not found");
  }

  const payload =
    task.payload && typeof task.payload === "object" && !Array.isArray(task.payload)
      ? (task.payload as Record<string, unknown>)
      : {};
  const payloadMetadata = getPayloadMetadata(payload);
  const prompt = getTaskPrompt(payload);
  const visibleTextSanitizerOptions = {
    allowPublicProviderReferences:
      input.webGroundingUsed === true || (input.webSourceCount ?? 0) > 0,
  };
  const visibleResponseText =
    sanitizeAssistantVisibleText(input.responseText, visibleTextSanitizerOptions) ||
    sanitizeAssistantVisibleText(input.responseText, {
      ...visibleTextSanitizerOptions,
      fallback: "Yanıtı temiz biçimde hazırlayamadım. İstersen aynı isteği tekrar deneyelim.",
    });
  const generatedImageArtifact = await maybeGenerateHostedImageArtifact(app, {
    prompt,
    responseText: visibleResponseText,
    metadata: payloadMetadata,
  });
  const renderRecipe = generatedImageArtifact
    ? null
    : buildLocalRenderRecipe({
        prompt,
        responseText: visibleResponseText,
        metadata: payloadMetadata,
        renderOn:
          typeof payload.source === "string" && payload.source.trim().toLowerCase() === "desktop"
            ? "desktop"
            : "mobile",
        taskId: task.id,
      });

  const now = new Date();
  const result = {
    text: visibleResponseText,
    route: input.route,
    workload: input.workload,
    latencyMs: input.latencyMs,
    promptTokens: input.promptTokens,
    completionTokens: input.completionTokens,
    totalTokens: input.totalTokens,
    firstDeltaMs: input.firstDeltaMs ?? null,
    completionLatencyMs: input.completionLatencyMs ?? input.latencyMs,
    responseBytes: input.responseBytes ?? Buffer.byteLength(visibleResponseText, "utf8"),
    fallbackUsed: input.fallbackUsed ?? false,
    groundingUsed: input.groundingUsed ?? false,
    documentSourceCount: input.documentSourceCount ?? 0,
    webGroundingUsed: input.webGroundingUsed ?? false,
    webSourceCount: input.webSourceCount ?? 0,
    attachmentContextUsed: input.attachmentContextUsed ?? false,
    attachmentContextSource: input.attachmentContextSource ?? null,
    attachmentDocumentIds: input.attachmentDocumentIds ?? [],
    skillUsed: input.skillUsed ?? false,
    skillId: input.skillId ?? null,
    skillVersion: input.skillVersion ?? null,
    skillConfidence: input.skillConfidence ?? null,
    selectedChunkHashes: input.selectedChunkHashes ?? [],
    validationStatus: input.validationStatus ?? null,
    cacheHit: input.cacheHit ?? false,
    attachmentCacheHit: input.attachmentCacheHit ?? input.cacheHit ?? false,
    retrievalMode: input.retrievalMode ?? null,
    retrievalResultCount: input.retrievalResultCount ?? 0,
    retrievalCandidateCount: input.retrievalCandidateCount ?? 0,
    retrievalLexicalCandidateCount: input.retrievalLexicalCandidateCount ?? 0,
    retrievalSemanticCandidateCount: input.retrievalSemanticCandidateCount ?? 0,
    rerankUsed: input.rerankUsed ?? false,
    rerankDegradedReason: input.rerankDegradedReason ?? null,
    qualityPolicyApplied: input.qualityPolicyApplied ?? false,
    dataGroundingLevel: input.dataGroundingLevel ?? null,
    personalizationScope: input.personalizationScope ?? null,
    responseLanguage: input.responseLanguage ?? null,
    evidenceSufficiency: input.evidenceSufficiency ?? null,
    dataConfidence: input.dataConfidence ?? null,
    dataQualityWarnings: input.dataQualityWarnings ?? [],
    responseBudgetState: input.responseBudgetState ?? null,
    responseBudgetReason: input.responseBudgetReason ?? null,
    contextPacketCount: input.contextPacketCount ?? 0,
    contextPacketKinds: input.contextPacketKinds ?? [],
    healthContextUsed: input.healthContextUsed ?? false,
    contextFreshness: input.contextFreshness ?? null,
    assistantBlocks: Array.isArray(input.assistantBlocks) ? input.assistantBlocks : [],
    imageArtifactGenerated: Boolean(generatedImageArtifact),
    ...(renderRecipe ? { renderRecipe } : {}),
  };
  const resultBlob = await storeTaskJsonBlob(app, {
    taskId: task.id,
    slot: "result",
    scope: "task_result",
    value: result,
  });

  const rows = await app.db
    .update(tasks)
    .set({
      status: "completed",
      summary: visibleResponseText.slice(0, 280),
      error: null,
      result,
      resultBlobId: resultBlob?.blobId ?? null,
      completedAt: now,
      updatedAt: now,
      queuePosition: 0,
    })
    .where(eq(tasks.id, task.id))
    .returning();

  const updatedTask = rows[0] ?? {
    ...task,
    status: "completed" as const,
    summary: visibleResponseText.slice(0, 280),
    error: null,
    result,
    completedAt: now,
    updatedAt: now,
    queuePosition: 0,
  };

  const artifactsToPersist: PersistableArtifactInput[] = [];
  if (renderRecipe) {
    artifactsToPersist.push(buildStructuredOutputArtifact(updatedTask.id, renderRecipe));
  }
  if (generatedImageArtifact) {
    artifactsToPersist.push({
      ...generatedImageArtifact.artifact,
      binaryBody: generatedImageArtifact.binaryBody,
    });
  }

  let structuredOutputArtifacts: Array<ReturnType<typeof shapeTaskArtifact>> = [];
  if (artifactsToPersist.length > 0) {
    const storedArtifacts = await persistArtifacts(app, updatedTask.id, artifactsToPersist);
    structuredOutputArtifacts = await Promise.all(
      storedArtifacts.map((artifact) => shapePublicArtifactRecord(app, artifact)),
    );
  }

  await insertTaskEvent(app, {
    taskId: updatedTask.id,
    status: "completed",
    message: "Elyan yanıtı hazır",
    payload: {
      route: input.route,
      workload: input.workload,
      presentation: input.route === "shared_brain" ? "chat" : "task",
      latencyMs: input.latencyMs,
      promptTokens: input.promptTokens,
      completionTokens: input.completionTokens,
      totalTokens: input.totalTokens,
      firstDeltaMs: input.firstDeltaMs ?? null,
      completionLatencyMs: input.completionLatencyMs ?? input.latencyMs,
      responseBytes: input.responseBytes ?? Buffer.byteLength(visibleResponseText, "utf8"),
      fallbackUsed: input.fallbackUsed ?? false,
      groundingUsed: input.groundingUsed ?? false,
      documentSourceCount: input.documentSourceCount ?? 0,
      webGroundingUsed: input.webGroundingUsed ?? false,
      webSourceCount: input.webSourceCount ?? 0,
      attachmentContextUsed: input.attachmentContextUsed ?? false,
      attachmentContextSource: input.attachmentContextSource ?? null,
      attachmentDocumentIds: input.attachmentDocumentIds ?? [],
      skillUsed: input.skillUsed ?? false,
      skillId: input.skillId ?? null,
      skillVersion: input.skillVersion ?? null,
      skillConfidence: input.skillConfidence ?? null,
      selectedChunkHashes: input.selectedChunkHashes ?? [],
      validationStatus: input.validationStatus ?? null,
      cacheHit: input.cacheHit ?? false,
      attachmentCacheHit: input.attachmentCacheHit ?? input.cacheHit ?? false,
      retrievalMode: input.retrievalMode ?? null,
      retrievalResultCount: input.retrievalResultCount ?? 0,
      retrievalCandidateCount: input.retrievalCandidateCount ?? 0,
      retrievalLexicalCandidateCount: input.retrievalLexicalCandidateCount ?? 0,
      retrievalSemanticCandidateCount: input.retrievalSemanticCandidateCount ?? 0,
      rerankUsed: input.rerankUsed ?? false,
      rerankDegradedReason: input.rerankDegradedReason ?? null,
      qualityPolicyApplied: input.qualityPolicyApplied ?? false,
      dataGroundingLevel: input.dataGroundingLevel ?? null,
      personalizationScope: input.personalizationScope ?? null,
      responseLanguage: input.responseLanguage ?? null,
      evidenceSufficiency: input.evidenceSufficiency ?? null,
      dataConfidence: input.dataConfidence ?? null,
      dataQualityWarnings: input.dataQualityWarnings ?? [],
      responseBudgetState: input.responseBudgetState ?? null,
      responseBudgetReason: input.responseBudgetReason ?? null,
      contextPacketCount: input.contextPacketCount ?? 0,
      contextPacketKinds: input.contextPacketKinds ?? [],
      healthContextUsed: input.healthContextUsed ?? false,
      contextFreshness: input.contextFreshness ?? null,
      artifactCount: structuredOutputArtifacts.length,
      ...(renderRecipe ? { renderRecipe } : {}),
      ...(structuredOutputArtifacts.length > 0 ? { artifacts: structuredOutputArtifacts } : {}),
    },
  });

  if (structuredOutputArtifacts.length > 0) {
    await insertTaskEvent(app, {
      taskId: updatedTask.id,
      status: "completed",
      message: "Structured render recipe ready",
      payload: {
        artifactCount: structuredOutputArtifacts.length,
        artifacts: structuredOutputArtifacts,
      },
    });

    await publishTaskEvent(app, updatedTask, "task.artifacts", {
      taskId: updatedTask.id,
      artifacts: structuredOutputArtifacts,
    });
  }

  await recordTaskLearningFromCompletion(app, {
    userId: updatedTask.userId,
    accountId: updatedTask.userId,
    taskId: updatedTask.id,
    title: updatedTask.title,
    message: getTaskPrompt(
      task.payload && typeof task.payload === "object" && !Array.isArray(task.payload)
        ? (task.payload as Record<string, unknown>)
        : {},
    ),
    status: "completed",
  });
  void maybeQueueAutomaticSharedBrainRefresh(app, {
    userId: updatedTask.userId,
    source: "task_completed",
  }).catch(() => undefined);

  await publishTaskEvent(app, updatedTask, "task.updated", {
    task: shapeTaskFeedItem(updatedTask),
  });

  await syncChatTaskLifecycle(app, {
    originalTask: task,
    updatedTask,
    message: input.responseText,
  });

  return Object.assign(updatedTask, {
    renderRecipe: renderRecipe ?? null,
    structuredOutputArtifacts,
  });
}

async function markServerBrainTaskRunning(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId: string;
  },
) {
  const task = await getTaskById(app, input.taskId);
  if (!task || task.userId !== input.userId) {
    throw notFound("Task not found");
  }

  if (task.status === "running") {
    return task;
  }

  const now = new Date();
  const rows = await app.db
    .update(tasks)
    .set({
      status: "running",
      error: null,
      startedAt: task.startedAt ?? now,
      updatedAt: now,
      queuePosition: 0,
    })
    .where(eq(tasks.id, task.id))
    .returning();

  const updatedTask = rows[0] ?? {
    ...task,
    status: "running" as const,
    error: null,
    startedAt: task.startedAt ?? now,
    updatedAt: now,
    queuePosition: 0,
  };

  await insertTaskEvent(app, {
    taskId: updatedTask.id,
    status: "running",
    message: "running",
    payload: {
      route: "shared_brain",
      presentation: "chat",
    },
  });

  await publishTaskEvent(app, updatedTask, "task.updated", {
    task: shapeTaskFeedItem(updatedTask),
  });

  await syncChatTaskLifecycle(app, {
    originalTask: task,
    updatedTask,
  });

  return updatedTask;
}

function extractChatStreamingMetadata(task: typeof tasks.$inferSelect): {
  sessionId: string;
  assistantMessageId: string;
} | null {
  const payload = task.payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }

  const metadata = (payload as Record<string, unknown>).metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return null;
  }

  const chat = (metadata as Record<string, unknown>).chat;
  if (!chat || typeof chat !== "object" || Array.isArray(chat)) {
    return null;
  }

  const chatRecord = chat as Record<string, unknown>;
  const sessionId = typeof chatRecord.sessionId === "string" ? chatRecord.sessionId.trim() : "";
  const assistantMessageId =
    typeof chatRecord.assistantMessageId === "string" ? chatRecord.assistantMessageId.trim() : "";
  if (!sessionId || !assistantMessageId) {
    return null;
  }

  return {
    sessionId,
    assistantMessageId,
  };
}

function resolveSharedBrainWorkloadForRouteDecision(
  routeDecision: CommandRouteDecision | null | undefined,
  attachmentContextUsed = false,
) {
  return resolveAttachmentAwareSharedBrainWorkload({
    route: routeDecision?.route,
    selectedWorkload: routeDecision?.selectedWorkload,
    attachmentContextUsed,
  });
}

async function processSharedBrainChatTask(
  app: FastifyInstance,
  input: {
    currentTask: typeof tasks.$inferSelect;
    userId: string;
    requestId: string;
    prompt: string;
    canonicalTitle: string;
    understanding: Awaited<ReturnType<typeof buildTaskUnderstanding>>;
    planCode?: string | null;
    brainProfile?: unknown;
  },
) {
  try {
    await recordTaskLearningFromCreation(app, {
      userId: input.userId,
      accountId: input.userId,
      taskId: input.currentTask.id,
      title: input.canonicalTitle,
      message: input.prompt,
      routeContext: "tasks.create",
      source:
        input.currentTask.payload &&
        typeof input.currentTask.payload === "object" &&
        !Array.isArray(input.currentTask.payload) &&
        typeof (input.currentTask.payload as Record<string, unknown>).source === "string"
          ? ((input.currentTask.payload as Record<string, unknown>).source as string)
          : undefined,
      deviceId: input.currentTask.targetDeviceId,
      metadata:
        input.currentTask.payload &&
        typeof input.currentTask.payload === "object" &&
        !Array.isArray(input.currentTask.payload)
          ? getPayloadMetadata(input.currentTask.payload as Record<string, unknown>)
          : {},
      intent: input.understanding.intent,
      requestId: input.requestId,
    });
    await recordBridgeLearningSignals(app, {
      userId: input.userId,
      accountId: input.userId,
      taskId: input.currentTask.id,
      target: "server_brain",
      outcome: "created",
      readiness: "ready",
      routingMode: "server_brain_first",
      requestId: input.requestId,
    });
    const runningTask = await markServerBrainTaskRunning(app, {
      taskId: input.currentTask.id,
      userId: input.userId,
    });
    const chatStreaming = extractChatStreamingMetadata(runningTask);
    const routeDecision = extractRouteDecision(
      runningTask.payload &&
        typeof runningTask.payload === "object" &&
        !Array.isArray(runningTask.payload)
        ? (runningTask.payload as Record<string, unknown>)
        : {},
    );
    const runningPayload =
      runningTask.payload &&
      typeof runningTask.payload === "object" &&
      !Array.isArray(runningTask.payload)
        ? (runningTask.payload as Record<string, unknown>)
        : {};
    const attachmentContext = await resolveTaskAttachmentContext(app, runningPayload, input.prompt);
    const selectedWorkload = resolveSharedBrainWorkloadForRouteDecision(
      routeDecision,
      attachmentContext?.used === true,
    );
    const ackText = buildSharedBrainAckText(selectedWorkload);
    const ackTaskTrace = buildTaskTraceBlock({
      task: runningTask,
      assistantContent: ackText,
    });
    let streamSeq = 0;

    if (chatStreaming) {
      const now = new Date().toISOString();
      const visibleAckText = sanitizeAssistantVisibleText(ackText, {
        fallback: ackText,
      });
      const ackBlocks = composeAssistantMessageBlocks({
        content: visibleAckText,
        blocks: [ackTaskTrace],
        streaming: true,
      });
      await publishVolatileChatStreamEvent(app, {
        userId: input.userId,
        deviceId: runningTask.targetDeviceId,
        taskId: runningTask.id,
        sessionId: chatStreaming.sessionId,
        messageId: chatStreaming.assistantMessageId,
        event: "message.delta",
        seq: ++streamSeq,
        payload: {
          delta: visibleAckText,
          // content is omitted — mobile accumulates from delta.
          // blocks are included so the task-trace card renders immediately.
          assistantMessage: shapeAssistantMessagePayload({
            id: chatStreaming.assistantMessageId,
            role: "assistant",
            status: "running",
            ...(ackBlocks.length > 0 ? { blocks: ackBlocks } : {}),
            taskId: runningTask.id,
            createdAt: runningTask.createdAt.toISOString(),
            updatedAt: now,
          }),
          streaming: {
            firstDeltaMs: 0,
            selectedProfile: selectedWorkload,
            answerSource: "backend_ack",
          },
        },
      });
    }

    let lastVisibleStreamingContent = sanitizeAssistantVisibleText(ackText, {
      fallback: ackText,
    });
    const inference = await generateGovernedSharedBrainReply(app, {
      userId: input.userId,
      taskId: runningTask.id,
      prompt: input.prompt,
      title: input.canonicalTitle,
      conversation: extractSharedBrainConversation(runningPayload),
      attachmentContext,
      requestMetadata: getPayloadMetadata(runningPayload),
      route: "shared_brain",
      routeDecision,
      workload: selectedWorkload,
      meteringSurface: "chat",
      planCode: input.planCode,
      understandingContext: input.understanding.context,
      brainProfile: input.brainProfile,
      onDelta: chatStreaming
        ? async (delta) => {
            const now = new Date().toISOString();
            const rawContent =
              ackText && delta.content.trim()
                  ? `${ackText}\n\n${delta.content}`
                  : delta.content || ackText;
            const visibleContent =
              sanitizeAssistantVisibleText(rawContent, { fallback: ackText }) ||
              lastVisibleStreamingContent;
            if (visibleContent === lastVisibleStreamingContent) {
              return;
            }
            const visibleDelta = visibleContent.startsWith(lastVisibleStreamingContent)
              ? visibleContent.slice(lastVisibleStreamingContent.length)
              : visibleContent;
            lastVisibleStreamingContent = visibleContent;
            const taskTrace = buildTaskTraceBlock({
              task: runningTask,
              assistantContent: visibleContent,
            });
            const blocks = composeAssistantMessageBlocks({
              content: visibleContent,
              blocks: [taskTrace],
              streaming: true,
            });
            await publishVolatileChatStreamEvent(app, {
              userId: input.userId,
              deviceId: runningTask.targetDeviceId,
              taskId: runningTask.id,
              sessionId: chatStreaming.sessionId,
              messageId: chatStreaming.assistantMessageId,
              event: "message.delta",
              seq: ++streamSeq,
              payload: {
                delta: visibleDelta,
                // content is omitted — mobile accumulates text from delta.
                // blocks update the task-trace card but do not carry the full text.
                assistantMessage: shapeAssistantMessagePayload({
                  id: chatStreaming.assistantMessageId,
                  role: "assistant",
                  status: "running",
                  ...(blocks.length > 0 ? { blocks: blocks } : {}),
                  taskId: runningTask.id,
                  createdAt: runningTask.createdAt.toISOString(),
                  updatedAt: now,
                }),
                streaming: {
                  firstDeltaMs: delta.firstDeltaMs,
                  selectedProfile: selectedWorkload,
                  answerSource: "model",
                },
              },
            });
          }
        : undefined,
    });
    const completedTask = await completeServerBrainTask(app, {
      taskId: input.currentTask.id,
      userId: input.userId,
      responseText: inference.text,
      provider: inference.provider,
      model: inference.model,
      route: inference.metadata.route as string,
      workload: inference.metadata.workload as string,
      latencyMs: inference.latencyMs,
      promptTokens: inference.promptTokens,
      completionTokens: inference.completionTokens,
      totalTokens: inference.totalTokens,
      ...readServerBrainCompletionMetadata(inference.metadata),
    });
    await recordBridgeLearningSignals(app, {
      userId: input.userId,
      accountId: input.userId,
      taskId: completedTask.id,
      target: "server_brain",
      outcome: "completed",
      readiness: "ready",
      routingMode: "server_brain_first",
      requestId: input.requestId,
    });
    // Konuşma değişiminden gerçek zamanlı öğrenme (fire-and-forget)
    void recordConversationExchangeLearning(app, {
      userId: input.userId,
      taskId: completedTask.id,
      userMessage: input.prompt,
      assistantReply: inference.text,
      intent: input.understanding.intent.primaryIntent,
      requestId: input.requestId,
    }).catch(() => undefined);
    // Rolling summary'yi session'a yaz (fire-and-forget)
    if (chatStreaming?.sessionId) {
      void persistRollingSummaryToSession(app, {
        userId: input.userId,
        sessionId: chatStreaming.sessionId,
        userMessage: input.prompt,
        assistantReply: inference.text,
      }).catch(() => undefined);
    }
    if (chatStreaming) {
      const completionMetadata = readServerBrainCompletionMetadata(inference.metadata);
      const taskTrace = buildTaskTraceBlock({
        task: completedTask,
        assistantContent: inference.text,
      });
      const finalBlocks = composeAssistantMessageBlocks({
        content: inference.text,
        blocks: [taskTrace, ...completionMetadata.assistantBlocks],
      });
      await publishPersistedChatStreamEvent(app, {
        userId: input.userId,
        deviceId: completedTask.targetDeviceId,
        taskId: completedTask.id,
        sessionId: chatStreaming.sessionId,
        messageId: chatStreaming.assistantMessageId,
        event: "message.completed",
        seq: ++streamSeq,
        payload: {
          content: inference.text,
          blocks: finalBlocks,
          assistantMessage: shapeAssistantMessagePayload({
            id: chatStreaming.assistantMessageId,
            role: "assistant",
            status: "completed",
            content: inference.text,
            blocks: finalBlocks,
            taskId: completedTask.id,
            createdAt: completedTask.createdAt.toISOString(),
            updatedAt: completedTask.updatedAt.toISOString(),
          }),
          task: shapeTaskFeedItem(completedTask),
          usage: {
            inputTokens: inference.promptTokens,
            outputTokens: inference.completionTokens,
            totalTokens: inference.totalTokens,
          },
          streaming: {
            firstDeltaMs: inference.metadata.firstDeltaMs,
            selectedProfile: selectedWorkload,
            answerSource: "model",
            fallbackUsed: Boolean(inference.metadata.fallbackUsed),
            cached: Boolean(inference.metadata.cached),
          },
        },
      });
    }
  } catch (error) {
    const fallbackMessage = getSharedBrainFallbackMessage(error);
    const rows = await app.db
      .update(tasks)
      .set({
        status: "failed",
        error: fallbackMessage,
        summary: fallbackMessage,
        completedAt: new Date(),
        updatedAt: new Date(),
        queuePosition: 0,
      })
      .where(eq(tasks.id, input.currentTask.id))
      .returning();
    const failedTask = rows[0] ?? input.currentTask;
    await insertTaskEvent(app, {
      taskId: failedTask.id,
      status: "failed",
      message: fallbackMessage,
      payload: {
        route: "shared_brain",
      },
    });
      await publishTaskEvent(app, failedTask, "task.updated", {
        task: shapeTaskFeedItem(failedTask),
      });
    await syncChatTaskLifecycle(app, {
      originalTask: input.currentTask,
      updatedTask: failedTask,
      message: fallbackMessage,
    });
    const chatStreaming = extractChatStreamingMetadata(input.currentTask);
    if (chatStreaming) {
      await publishPersistedChatStreamEvent(app, {
        userId: input.userId,
        deviceId: failedTask.targetDeviceId,
        taskId: failedTask.id,
        sessionId: chatStreaming.sessionId,
        messageId: chatStreaming.assistantMessageId,
        event: "message.error",
        seq: 1,
        payload: {
          error: fallbackMessage,
          code: error instanceof AppError ? error.code : "shared_brain_failed",
          retryable:
            error instanceof AppError &&
            error.details &&
            typeof error.details === "object" &&
            !Array.isArray(error.details)
              ? Boolean((error.details as Record<string, unknown>).retrySuggested)
              : true,
          assistantMessage: shapeAssistantMessagePayload({
            id: chatStreaming.assistantMessageId,
            role: "assistant",
            status: "failed",
            content: fallbackMessage,
            taskId: failedTask.id,
            error: fallbackMessage,
            createdAt: failedTask.createdAt.toISOString(),
            updatedAt: failedTask.updatedAt.toISOString(),
          }),
          task: shapeTaskFeedItem(failedTask),
        },
      });
    }
    await recordBridgeLearningSignals(app, {
      userId: input.userId,
      accountId: input.userId,
      taskId: failedTask.id,
      target: "server_brain",
      outcome:
        error instanceof AppError && error.code === "server_brain_unavailable"
          ? "unavailable"
          : "failed",
      readiness: "unavailable",
      routingMode: "server_brain_first",
      requestId: input.requestId,
    });

    app.log.warn(
      {
        taskId: failedTask.id,
        requestId: input.requestId,
        reason: error instanceof Error ? error.message : "unknown",
      },
      "shared brain chat dispatch failed asynchronously",
    );
  }
}

export async function createTask(
  app: FastifyInstance,
  input: {
    userId: string;
    targetDeviceId?: string;
    requestedTargetDeviceId?: string;
    title: string;
    payload: Record<string, unknown>;
    requestedCapabilities: string[];
    ipAddress?: string;
    userAgent?: string;
    requestId: string;
    idempotencyKey?: string;
    onTaskReady?: TaskReadyCallback;
  },
) {
  const prompt = getTaskPrompt(input.payload);
  const payloadMetadata = getPayloadMetadata(input.payload);
  const usageAccess = await getUserUsageAccessTruth(app.db, input.userId);
  const routeDecision =
    extractRouteDecision(input.payload) ??
    (await decideCommandRoute(app, {
      userId: input.userId,
      message: prompt,
      source: typeof input.payload.source === "string" && input.payload.source === "desktop" ? "desktop" : "mobile",
      activeChatSessionId: typeof payloadMetadata.chat === "object" && payloadMetadata.chat !== null
        ? String((payloadMetadata.chat as Record<string, unknown>).sessionId ?? "")
        : undefined,
      selectedDeviceId: input.targetDeviceId,
      metadata: payloadMetadata,
      desktopAllowed: canUseDesktopConnections(usageAccess.planCode),
      requestedCapabilities: input.requestedCapabilities,
      bootstrap: undefined,
      brainProfile: usageAccess.brainProfile,
      quota: undefined,
  }));
  const routeCapabilities = routeDecision?.capabilities?.length ? routeDecision.capabilities : input.requestedCapabilities;
  const routeOrigin = normalizeRouteOrigin(input.payload.source);
  const routeSelectedTargetDeviceId = input.requestedTargetDeviceId ?? input.targetDeviceId;
  const needsDesktop = resolveTaskRouteNeedsDesktop(routeDecision);
  const routeBlocked = needsDesktop && (routeDecision.route === "pairing_required" || routeDecision.route === "unavailable");
  const useFastSharedBrainFlow =
    routeDecision.route === "server_brain" &&
    typeof payloadMetadata.channel === "string" &&
    payloadMetadata.channel === "chat";
  const canonicalTitle = canonicalTaskTitle({
    title: input.title,
    prompt,
  });
  const pendingDesktopTarget = routeBlocked
    ? await resolvePendingDesktopQueueTarget(
        app,
        input.userId,
        input.targetDeviceId,
        routeCapabilities,
      )
    : null;
  const targetDevice =
    needsDesktop
      ? routeBlocked
        ? pendingDesktopTarget ?? await resolveCommandTarget(app, input.userId, undefined, "chat")
        : await resolveCommandTarget(
            app,
            input.userId,
            input.targetDeviceId,
            "task",
            routeCapabilities,
          )
      : await resolveCommandTarget(app, input.userId, undefined, "chat");
  const targetDeviceId = targetDevice.device.id;
  const { isSharedBrain } = targetDevice;
  const selectedDesktopOnline = isSharedBrain ? true : Boolean(targetDevice.device.isOnline);
  const idempotencyFingerprint = input.idempotencyKey
    ? createTaskFingerprint({
        targetDeviceId,
        title: canonicalTitle,
        payload: input.payload,
        requestedCapabilities: routeCapabilities,
      })
    : undefined;
  const existingTask = await getExistingTaskForIdempotency(app.db, {
    userId: input.userId,
    idempotencyKey: input.idempotencyKey,
    fingerprint: idempotencyFingerprint,
  });

  if (existingTask) {
    await notifyTaskReady(input.onTaskReady, {
      rawTask: existingTask,
      reused: true,
      routeDecision,
      isSharedBrain,
    });
    await logRouteDecision(app, {
      taskId: existingTask.id,
      routeDecision,
      requestedTargetDeviceId: routeSelectedTargetDeviceId,
      origin: routeOrigin,
    });
    return {
      task: shapeTaskFeedItem(existingTask, { selectedDesktopOnline }),
      dispatched: false,
      reused: true,
      selectedDesktopOnline,
      renderRecipe: null,
    };
  }

  const understandingInput = {
    userId: input.userId,
    accountId: input.userId,
    title: canonicalTitle,
    message: prompt,
    routeContext: "tasks.create" as const,
    source: typeof input.payload.source === "string" ? input.payload.source : undefined,
    deviceId: targetDeviceId,
    metadata: {
      ...payloadMetadata,
      routeDecision,
      requestId: input.requestId,
    },
  };
  const understanding = await buildTaskUnderstanding(app, understandingInput).catch(() =>
    emptyUnderstanding(understandingInput),
  );
  const isDesktopRoute =
    routeDecision.route === "desktop_runtime" ||
    routeDecision.taskRoute?.operationalRoute === "desktop_runtime";
  const desktopContext = isDesktopRoute
    ? {
        intent: routeDecision.taskRoute?.target ?? "desktop_runtime",
        requiresCapabilities: routeCapabilities,
        naturalLanguageGoal: prompt,
        structuredSteps: null,
      }
    : null;
  const enrichedPayload = {
    ...input.payload,
    ...(buildQuantumTaskSnapshot({ capabilities: routeCapabilities, status: "pending", ready: !routeBlocked })
      ? { quantum: buildQuantumTaskSnapshot({ capabilities: routeCapabilities, status: "pending", ready: !routeBlocked }) }
      : {}),
    ...(desktopContext ? { desktopContext } : {}),
    metadata: {
      ...payloadMetadata,
      routeDecision,
      ...(buildQuantumTaskSnapshot({ capabilities: routeCapabilities, status: "pending", ready: !routeBlocked })
        ? {
            quantum: buildQuantumTaskSnapshot({
              capabilities: routeCapabilities,
              status: "pending",
              ready: !routeBlocked,
              fallbackReason: routeBlocked ? routeDecision.reason : undefined,
            }),
          }
        : {}),
      understanding: {
        intent: understanding.intent,
        context: understanding.context,
        routingHints: understanding.routingHints,
      },
    },
  };
  if (routeBlocked) {
    const blockedReason = routeDecision.userFacingMessage || "Bu görev için önce bir masaüstü eşleştirmen gerekiyor.";
    const taskResult = await app.db.transaction(async (tx) => {
      await tx.execute(sql`select pg_advisory_xact_lock(hashtextextended(${input.userId}, 0))`);

      const racedTask = await getExistingTaskForIdempotency(tx, {
        userId: input.userId,
        idempotencyKey: input.idempotencyKey,
        fingerprint: idempotencyFingerprint,
      });

      if (racedTask) {
        return {
          task: racedTask,
          reused: true,
        } as const;
      }

      const activeCounts = await tx
        .select({
          count: sql<number>`count(*)`,
        })
        .from(tasks)
        .where(
          and(
            eq(tasks.targetDeviceId, targetDeviceId),
            inArray(tasks.status, activeTaskStatuses),
          ),
        );

      const queuePosition = Number(activeCounts[0]?.count ?? 0) + 1;
      const blockedTaskId = randomUUID();
      const blockedPayload = {
        ...enrichedPayload,
        metadata: {
          ...enrichedPayload.metadata,
          routeDecision,
          blocked: true,
        },
      };
      const blockedPayloadBlob = await storeTaskJsonBlob(app, {
        taskId: blockedTaskId,
        slot: "payload",
        scope: "task_payload",
        value: blockedPayload,
      });
      const rows = await tx
        .insert(tasks)
        .values({
          id: blockedTaskId,
          userId: input.userId,
          targetDeviceId,
          title: canonicalTitle,
          payload: blockedPayload,
          payloadBlobId: blockedPayloadBlob?.blobId ?? null,
          requestedCapabilities: routeCapabilities,
          idempotencyKey: input.idempotencyKey,
          idempotencyFingerprint,
          queuePosition,
          status: "queued",
          summary: blockedReason,
          error: null,
        })
        .returning();

      const insertedTask = rows[0];
      if (!insertedTask) {
        throw new AppError(500, "task_insert_failed", "Task could not be created");
      }

      return {
        task: insertedTask,
        reused: false,
      } as const;
    });

    if (taskResult.reused) {
      await notifyTaskReady(input.onTaskReady, {
        rawTask: taskResult.task,
        reused: true,
        routeDecision,
        isSharedBrain,
        blocked: true,
      });
      await logRouteDecision(app, {
        taskId: taskResult.task.id,
        routeDecision,
        requestedTargetDeviceId: routeSelectedTargetDeviceId,
        origin: routeOrigin,
      });
      return {
        task: shapeTaskFeedItem(taskResult.task, { selectedDesktopOnline }),
        dispatched: false,
        reused: true,
        selectedDesktopOnline,
        renderRecipe: null,
      };
    }

    const blockedTask = taskResult.task;
    await notifyTaskReady(input.onTaskReady, {
      rawTask: blockedTask,
      reused: false,
      routeDecision,
      isSharedBrain,
      blocked: true,
    });
    await insertTaskEvent(app, {
      taskId: blockedTask.id,
      status: "queued",
      message: blockedReason,
      payload: {
        route: routeDecision.route,
        reason: routeDecision.reason,
      },
    });
    await syncChatTaskLifecycle(app, {
      originalTask: blockedTask,
      updatedTask: blockedTask,
      message: blockedReason,
    });
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "task.create",
      resourceType: "task",
      resourceId: blockedTask.id,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        targetDeviceId,
        requestedCapabilities: routeCapabilities,
        idempotencyKey: input.idempotencyKey ?? null,
        routeDecision,
      },
    });
    await logRouteDecision(app, {
      taskId: blockedTask.id,
      routeDecision,
      requestedTargetDeviceId: routeSelectedTargetDeviceId,
      origin: routeOrigin,
    });

    return {
      task: shapeTaskFeedItem(blockedTask, { selectedDesktopOnline }),
      dispatched: false,
      reused: false,
      selectedDesktopOnline,
      renderRecipe: null,
    };
  }

  await reconcileStaleRuntimeTasks(app, {
    userId: input.userId,
    targetDeviceId,
  });

  const taskAttachmentUsage = summarizeTaskAttachmentUsage(getPayloadMetadata(enrichedPayload));

  const taskResult = await app.db.transaction(async (tx) => {
    await tx.execute(sql`select pg_advisory_xact_lock(hashtextextended(${input.userId}, 0))`);

    const racedTask = await getExistingTaskForIdempotency(tx, {
      userId: input.userId,
      idempotencyKey: input.idempotencyKey,
      fingerprint: idempotencyFingerprint,
    });

    if (racedTask) {
      return {
        task: racedTask,
        reused: true,
      } as const;
    }

    const sharedBrainRoute = routeDecision.route === "server_brain";

    if (sharedBrainRoute && !usageAccess.serverBrainAllowed) {
      throw createUpgradeOrByokRequiredError(usageAccess);
    }

    if (taskAttachmentUsage.documentUploads > 0 || taskAttachmentUsage.imageUploads > 0) {
      const trialQuota = await getTrialQuotaUsage(tx, input.userId);
      assertAttachmentQuotaAllowedFromUsage(trialQuota, {
        requiredDocumentUploads: taskAttachmentUsage.documentUploads,
        requiredImageUploads: taskAttachmentUsage.imageUploads,
      });
    }

    await assertMonthlyTaskUsageAllowed(tx, input.userId);

    const activeCounts = await tx
      .select({
        count: sql<number>`count(*)`,
      })
      .from(tasks)
      .where(
        and(
          eq(tasks.targetDeviceId, targetDeviceId),
          inArray(tasks.status, activeTaskStatuses),
        ),
      );

    const queuePosition = Number(activeCounts[0]?.count ?? 0) + 1;
    const createdTaskId = randomUUID();
    const payloadBlob = await storeTaskJsonBlob(app, {
      taskId: createdTaskId,
      slot: "payload",
      scope: "task_payload",
      value: enrichedPayload,
    });
    const rows = await tx
      .insert(tasks)
        .values({
          id: createdTaskId,
          userId: input.userId,
          targetDeviceId,
          title: canonicalTitle,
          payload: enrichedPayload,
          payloadBlobId: payloadBlob?.blobId ?? null,
          requestedCapabilities: routeCapabilities,
          idempotencyKey: input.idempotencyKey,
          idempotencyFingerprint,
          queuePosition,
        })
        .returning();

    const insertedTask = rows[0];
    if (!insertedTask) {
      throw new AppError(500, "task_insert_failed", "Task could not be created");
    }

    if (sharedBrainRoute && usageAccess.serverBrainAllowed) {
      const usageIdentity = await resolveUsageIdentityContext(tx, {
        userId: input.userId,
      });
      await recordUsageLedgerEntry(tx, {
        userId: input.userId,
        identityId: usageIdentity.identityId,
        taskId: insertedTask.id,
        metric: BILLING_USAGE_METRICS.subscriptionTask,
        quantity: 1,
        documentUnits: taskAttachmentUsage.documentUploads,
        imageUnits: taskAttachmentUsage.imageUploads,
        qualityProfile: usageIdentity.qualityProfile,
        planSnapshot: {
          planCode: usageIdentity.planCode,
          qualityProfile: usageIdentity.qualityProfile,
          route: routeDecision.route,
          usageSurface: "task_create",
        },
      });
    }

    return {
      task: insertedTask,
      reused: false,
      payloadBlobHash: payloadBlob?.contentHash ?? null,
    } as const;
  });

  if (taskResult.reused) {
    await notifyTaskReady(input.onTaskReady, {
      rawTask: taskResult.task,
      reused: true,
      routeDecision,
      isSharedBrain,
    });
    await logRouteDecision(app, {
      taskId: taskResult.task.id,
      routeDecision,
      requestedTargetDeviceId: routeSelectedTargetDeviceId,
      origin: routeOrigin,
    });
    return {
      task: shapeTaskFeedItem(taskResult.task, { selectedDesktopOnline }),
      dispatched: false,
      reused: true,
      selectedDesktopOnline,
      renderRecipe: null,
    };
  }

  const task = taskResult.task;
  await resequenceDeviceQueue(app, targetDeviceId);
  const currentTask = (await getTaskById(app, task.id)) ?? task;
  await notifyTaskReady(input.onTaskReady, {
    rawTask: currentTask,
    reused: false,
    routeDecision,
    isSharedBrain,
  });
  if (isSharedBrain && useFastSharedBrainFlow) {
    void processSharedBrainChatTask(app, {
      currentTask,
      userId: input.userId,
      requestId: input.requestId,
      prompt,
      canonicalTitle,
      understanding,
      planCode: usageAccess.planCode,
      brainProfile: usageAccess.brainProfile,
    });
    await logRouteDecision(app, {
      taskId: currentTask.id,
      routeDecision,
      requestedTargetDeviceId: routeSelectedTargetDeviceId,
      origin: routeOrigin,
    });

    return {
      task: shapeTaskFeedItem(currentTask, { selectedDesktopOnline }),
      dispatched: true,
      reused: false,
      selectedDesktopOnline,
      renderRecipe: null,
    };
  }

  await recordTaskLearningFromCreation(app, {
    userId: input.userId,
    accountId: input.userId,
    taskId: currentTask.id,
    title: canonicalTitle,
    message: prompt,
    routeContext: "tasks.create",
    source: typeof input.payload.source === "string" ? input.payload.source : undefined,
    deviceId: targetDeviceId,
    metadata: {
      ...payloadMetadata,
      ...(taskResult.reused ? {} : { sourceBlobHash: taskResult.payloadBlobHash ?? undefined }),
    },
    intent: understanding.intent,
    requestId: input.requestId,
  });
  await recordBridgeLearningSignals(app, {
    userId: input.userId,
    accountId: input.userId,
    taskId: currentTask.id,
    target: isSharedBrain ? "server_brain" : "desktop",
    outcome: "created",
    readiness: isSharedBrain ? "ready" : targetDevice.device.targetStatus === "ready" ? "ready" : "degraded",
    routingMode: isSharedBrain ? "server_brain_first" : "desktop_first_when_available",
    requestId: input.requestId,
  });

  await insertTaskEvent(app, {
    taskId: currentTask.id,
    status: "queued",
    message: "Task queued",
    payload: {
      understanding: {
        intent: understanding.intent.primaryIntent,
        confidence: understanding.intent.confidence,
        privacyRisk: understanding.intent.privacyRisk,
        routingMode: understanding.routingHints.mode,
        hintCount:
          understanding.context.personalizationHints.length +
          understanding.context.projectHints.length +
          understanding.context.styleHints.length +
          understanding.context.technicalHints.length +
          understanding.context.safetyHints.length,
      },
    },
  });

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "task.create",
    resourceType: "task",
    resourceId: currentTask.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      targetDeviceId,
      requestedCapabilities: routeCapabilities,
      idempotencyKey: input.idempotencyKey ?? null,
      understanding: {
        intent: understanding.intent.primaryIntent,
        routingMode: understanding.routingHints.mode,
        hintCount:
          understanding.context.personalizationHints.length +
          understanding.context.projectHints.length +
          understanding.context.styleHints.length +
          understanding.context.technicalHints.length +
          understanding.context.safetyHints.length,
      },
    },
  });

  await publishTaskEvent(app, currentTask, "task.queued", {
    task: shapeTaskFeedItem(currentTask),
  });

  if (isSharedBrain) {
    try {
      const runningTask = await markServerBrainTaskRunning(app, {
        taskId: currentTask.id,
        userId: input.userId,
      });
      const runningPayload =
        runningTask.payload &&
            typeof runningTask.payload === "object" &&
            !Array.isArray(runningTask.payload)
        ? (runningTask.payload as Record<string, unknown>)
        : input.payload;
      const runningMetadata = getPayloadMetadata(runningPayload);
      const attachmentContext = await resolveTaskAttachmentContext(app, runningPayload, prompt);
      const inference = await generateGovernedSharedBrainReply(app, {
        userId: input.userId,
        taskId: runningTask.id,
        prompt,
        title: canonicalTitle,
        conversation: extractSharedBrainConversation(runningPayload),
        attachmentContext,
        requestMetadata: runningMetadata,
        route: "shared_brain",
        routeDecision,
        workload: resolveSharedBrainWorkloadForRouteDecision(
          routeDecision,
          attachmentContext?.used === true,
        ),
        meteringSurface: runningMetadata.channel === "chat" ? "chat" : "task",
        planCode: usageAccess.planCode,
        understandingContext: understanding.context,
        brainProfile: usageAccess.brainProfile,
      });
      const completedTask = await completeServerBrainTask(app, {
        taskId: runningTask.id,
        userId: input.userId,
        responseText: inference.text,
        provider: inference.provider,
        model: inference.model,
        route: inference.metadata.route as string,
        workload: inference.metadata.workload as string,
        latencyMs: inference.latencyMs,
        promptTokens: inference.promptTokens,
        completionTokens: inference.completionTokens,
        totalTokens: inference.totalTokens,
        ...readServerBrainCompletionMetadata(inference.metadata),
      });
      await recordBridgeLearningSignals(app, {
        userId: input.userId,
        accountId: input.userId,
        taskId: completedTask.id,
        target: "server_brain",
        outcome: "completed",
        readiness: "ready",
        routingMode: "server_brain_first",
        requestId: input.requestId,
      });

      return {
        task: shapeTaskFeedItem(completedTask, { selectedDesktopOnline }),
        dispatched: true,
        reused: false,
        selectedDesktopOnline,
        renderRecipe: completedTask.renderRecipe ?? null,
      };
    } catch (error) {
      const fallbackMessage = getSharedBrainFallbackMessage(error);
      const rows = await app.db
        .update(tasks)
        .set({
          status: "failed",
          error: fallbackMessage,
          summary: fallbackMessage,
          completedAt: new Date(),
          updatedAt: new Date(),
          queuePosition: 0,
        })
        .where(eq(tasks.id, currentTask.id))
        .returning();
      const failedTask = rows[0] ?? currentTask;
      await insertTaskEvent(app, {
        taskId: failedTask.id,
        status: "failed",
        message: fallbackMessage,
        payload: {
          route: "shared_brain",
        },
      });
      await publishTaskEvent(app, failedTask, "task.updated", {
        task: shapeTaskFeedItem(failedTask),
      });
      await syncChatTaskLifecycle(app, {
        originalTask: currentTask,
        updatedTask: failedTask,
        message: fallbackMessage,
      });
      await recordBridgeLearningSignals(app, {
        userId: input.userId,
        accountId: input.userId,
        taskId: failedTask.id,
        target: "server_brain",
        outcome: error instanceof AppError && error.code === "server_brain_unavailable" ? "unavailable" : "failed",
        readiness: "unavailable",
        routingMode: "server_brain_first",
        requestId: input.requestId,
      });
      await logRouteDecision(app, {
        taskId: failedTask.id,
        routeDecision,
        requestedTargetDeviceId: routeSelectedTargetDeviceId,
        origin: routeOrigin,
      });

      if (error instanceof AppError) {
        throw error;
      }

      return {
        task: shapeTaskFeedItem(failedTask, { selectedDesktopOnline }),
        dispatched: false,
        reused: false,
        selectedDesktopOnline,
        renderRecipe: null,
      };
    }
  }

  const dispatchOwner = `backend:ws:${input.requestId}`;
  const dispatchLockAcquired = await app.services.reliability.acquireTaskDispatchLock(currentTask.id, dispatchOwner);
  let dispatched = true;
  if (dispatchLockAcquired) {
    const leaseResult = await issueTaskDispatchLease(app, {
      taskId: currentTask.id,
      runtimeConnectionId: currentTask.runtimeConnectionId ?? null,
      leaseMs: TASK_DISPATCH_LEASE_MS,
    });
    const lease = leaseResult?.lease ?? null;
    const taskForDispatch = leaseResult?.task ?? currentTask;
    const payload =
      lease
        ? {
            type: "task.dispatch",
            task: shapeTaskFeedItem(taskForDispatch),
            leaseId: lease.leaseId,
            leaseExpiresAt: lease.expiresAt,
          }
        : {
            type: "task.dispatch",
            task: shapeTaskFeedItem(taskForDispatch),
          };
    dispatched = app.services.realtimeHub.sendToRuntime(currentTask.targetDeviceId, payload);
    if (!dispatched) {
      const rows = await app.db
        .update(tasks)
        .set(
          buildTaskDispatchLeaseReleaseUpdate({
            clearRuntimeConnection: true,
          }),
        )
        .where(eq(tasks.id, currentTask.id))
        .returning();
      const releasedTask = rows[0] ?? currentTask;
      await insertTaskEvent(app, {
        taskId: releasedTask.id,
        status: "queued",
        message: "Runtime offline; task returned to queue",
        payload: {
          reason: "runtime_offline",
          lease,
        },
      });
      await publishTaskEvent(app, releasedTask, "command.queued", {
        task: shapeTaskFeedItem(releasedTask),
        reason: "runtime_offline",
        lease,
      });
      await syncChatTaskLifecycle(app, {
        originalTask: currentTask,
        updatedTask: releasedTask,
        message: "Runtime offline; task returned to queue",
      });
      await app.services.reliability.releaseTaskDispatchLock(currentTask.id, dispatchOwner);
      await enqueueTaskDispatch(app, releasedTask.id);
    } else {
      await publishTaskEvent(app, taskForDispatch, "command.routed", {
        task: shapeTaskFeedItem(taskForDispatch),
        lease,
        route: "desktop_runtime",
      });
    }
  }
  await recordBridgeLearningSignals(app, {
    userId: input.userId,
    accountId: input.userId,
    taskId: currentTask.id,
    target: "desktop",
    outcome: dispatched ? "dispatched" : "failed",
    readiness: dispatched ? "ready" : "degraded",
    routingMode: "desktop_first_when_available",
    requestId: input.requestId,
  });

  if (!isSharedBrain) {
    await enqueueTaskDispatch(app, currentTask.id);
  }
  await logRouteDecision(app, {
    taskId: currentTask.id,
    routeDecision,
    requestedTargetDeviceId: routeSelectedTargetDeviceId,
    origin: routeOrigin,
  });

  return {
    task: shapeTaskFeedItem(currentTask, { selectedDesktopOnline }),
    dispatched,
    reused: false,
    selectedDesktopOnline,
    renderRecipe: null,
  };
}

export async function listTasks(
  app: FastifyInstance,
  input: {
    userId: string;
    targetDeviceId?: string;
    statuses?: TaskStatus[];
    limit: number;
  },
) {
  await reconcileStaleRuntimeTasks(app, {
    userId: input.userId,
    targetDeviceId: input.targetDeviceId,
  });

  const conditions = [eq(tasks.userId, input.userId)];

  if (input.targetDeviceId) {
    conditions.push(eq(tasks.targetDeviceId, input.targetDeviceId));
  }

  if (input.statuses?.length) {
    conditions.push(inArray(tasks.status, input.statuses));
  }

  const rows = await app.db
    .select({
      id: tasks.id,
      title: tasks.title,
      status: tasks.status,
      targetDeviceId: tasks.targetDeviceId,
      payload: tasks.payload,
      queuePosition: tasks.queuePosition,
      requestedCapabilities: tasks.requestedCapabilities,
      result: tasks.result,
      summary: tasks.summary,
      error: tasks.error,
      approvalRequest: tasks.approvalRequest,
      createdAt: tasks.createdAt,
      startedAt: tasks.startedAt,
      completedAt: tasks.completedAt,
      canceledAt: tasks.canceledAt,
      updatedAt: tasks.updatedAt,
    })
    .from(tasks)
    .where(and(...conditions))
    .orderBy(desc(tasks.createdAt))
    .limit(input.limit);

  return rows.map((task) => shapeTaskFeedItem(task));
}

export async function getTaskDetail(app: FastifyInstance, taskId: string, userId: string) {
  await reconcileStaleRuntimeTasks(app, {
    userId,
    limit: 50,
  });

  const task = await getTaskForUser(app, taskId, userId);
  const events = await app.db
    .select()
    .from(taskEvents)
    .where(eq(taskEvents.taskId, task.id))
    .orderBy(taskEvents.createdAt);
  const taskArtifacts = await app.db
    .select()
    .from(artifacts)
    .where(eq(artifacts.taskId, task.id))
    .orderBy(artifacts.createdAt);
  const hydratedTask = {
    ...task,
    payload: await hydrateTaskJsonValue(app, task.payload, task.payloadBlobId),
    result: await hydrateTaskJsonValue(app, task.result, task.resultBlobId),
    approvalRequest: await hydrateTaskJsonValue(app, task.approvalRequest, task.approvalRequestBlobId),
  };

  return {
    task: {
      ...hydratedTask,
      result: sanitizePublicInferenceValue(hydratedTask.result),
      chatSessionId: extractTaskChatSessionId(hydratedTask.payload),
    },
    events: await Promise.all(
      events.map(async (event) => ({
        ...event,
        payload: sanitizePublicInferenceValue(
          await hydrateTaskJsonValue(app, event.payload, event.payloadBlobId),
        ),
      })),
    ),
    artifacts: await Promise.all(taskArtifacts.map((artifact) => shapePublicArtifactRecord(app, artifact))),
  };
}

export async function cancelTask(
  app: FastifyInstance,
  taskId: string,
  userId: string,
  context?: { ipAddress?: string; userAgent?: string; requestId?: string },
) {
  const task = await getTaskForUser(app, taskId, userId);

  if (isTerminalTaskStatus(task.status)) {
    throw conflict("Task is already terminal");
  }

  const rows = await app.db
    .update(tasks)
    .set(buildTaskCancellationUpdate())
    .where(eq(tasks.id, task.id))
    .returning();

  const updatedTask = rows[0];
  await resequenceDeviceQueue(app, updatedTask.targetDeviceId);

  await insertTaskEvent(app, {
    taskId: task.id,
    status: "canceled",
    message: "Task canceled by user",
  });

  await createAuditLog(app, {
    userId,
    actorType: "user",
    actorId: userId,
    action: "task.cancel",
    resourceType: "task",
    resourceId: updatedTask.id,
    status: "success",
    ipAddress: context?.ipAddress,
    userAgent: context?.userAgent,
    requestId: context?.requestId,
    payload: {
      previousStatus: task.status,
    },
  });

  await publishTaskEvent(app, updatedTask, "task.canceled", {
    task: shapeTaskFeedItem(updatedTask),
  });

  await syncChatTaskLifecycle(app, {
    originalTask: task,
    updatedTask,
    message: "Task canceled by user",
  });
  await app.services.reliability.clearTaskDispatchLock(updatedTask.id);

  app.services.realtimeHub.sendToRuntime(updatedTask.targetDeviceId, {
    type: "task.cancel",
    taskId: updatedTask.id,
  });

  return {
    task: shapeTaskFeedItem(updatedTask),
  };
}

export async function resolveTaskApproval(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId: string;
    approved: boolean;
    notes?: string;
    ipAddress?: string;
    userAgent?: string;
    requestId: string;
  },
) {
  const task = await getTaskForUser(app, input.taskId, input.userId);

  if (task.status !== "waiting_approval") {
    throw conflict("Task is not waiting for approval");
  }

  if (!input.approved) {
    return cancelTask(app, task.id, task.userId, {
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
    });
  }

  const approvalRows = await app.db
    .update(tasks)
    .set(buildTaskApprovalResumeUpdate(task, { notes: input.notes }))
    .where(eq(tasks.id, task.id))
    .returning();

  const updatedTask = approvalRows[0] ?? task;

  await insertTaskEvent(app, {
    taskId: task.id,
    status: "waiting_approval",
    message: "Onay alındı. Görev devam ediyor.",
    payload: {
      notes: input.notes,
    },
  });

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "task.approval.resolve",
    resourceType: "task",
    resourceId: task.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      approved: true,
      notes: input.notes ?? null,
    },
    requestId: input.requestId,
  });

  await publishTaskEvent(app, updatedTask, "task.approval_granted", {
    task: shapeTaskFeedItem(updatedTask),
    taskId: updatedTask.id,
    approved: true,
    notes: input.notes,
  });

  await syncChatTaskLifecycle(app, {
    originalTask: task,
    updatedTask,
    message: "Onay alındı. Görev devam ediyor.",
  });

  app.services.realtimeHub.sendToRuntime(updatedTask.targetDeviceId, {
    type: "task.approval",
    taskId: updatedTask.id,
    approved: true,
    notes: input.notes,
  });

  return {
    taskId: updatedTask.id,
    status: updatedTask.status,
    approved: true,
    task: shapeTaskFeedItem(updatedTask),
  };
}

export async function updateTaskFromRuntime(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  taskId: string,
  input: {
    status: TaskStatus;
    message?: string;
    summary?: string;
    error?: string;
    approvalRequest?: Record<string, unknown>;
    result?: Record<string, unknown>;
    operator?: Record<string, unknown>;
    artifacts: ArtifactInput[];
  },
) {
  const task = await getTaskForRuntime(app, taskId, auth);
  if (shouldSkipDuplicateRuntimeTerminalUpdate(task, input.status)) {
    return {
      task,
      storedArtifacts: [],
      replaySkipped: true,
    };
  }
  const ownedTask = await ensureTaskRuntimeOwnership(app, task, auth);
  assertTaskTransition(ownedTask.status, input.status);
  const runtimeResult = input.operator
    ? {
        ...(input.result ?? {}),
        operator: input.operator,
      }
    : input.result;
  const approvalRequestBlob =
    input.approvalRequest === undefined
      ? null
      : await storeTaskJsonBlob(app, {
          taskId: ownedTask.id,
          slot: "approval_request",
          scope: "task_approval_request",
          value: input.approvalRequest,
        });
  const runtimeResultBlob =
    runtimeResult === undefined
      ? null
      : await storeTaskJsonBlob(app, {
          taskId: ownedTask.id,
          slot: "result",
          scope: "task_result",
          value: runtimeResult,
        });

  const updates: Partial<typeof tasks.$inferInsert> = {
    ...buildTaskRuntimeUpdate(ownedTask, {
      status: input.status,
      runtimeConnectionId: auth.connectionId,
      summary: input.summary,
      error: input.error,
      approvalRequest: input.approvalRequest,
      result: runtimeResult,
    }),
    ...(input.approvalRequest !== undefined ? { approvalRequestBlobId: approvalRequestBlob?.blobId ?? null } : {}),
    ...(runtimeResult !== undefined ? { resultBlobId: runtimeResultBlob?.blobId ?? null } : {}),
  };

  const rows = await app.db.update(tasks).set(updates).where(eq(tasks.id, ownedTask.id)).returning();
  const updatedTask = rows[0];
  const storedArtifacts = await persistArtifacts(app, ownedTask.id, input.artifacts);
  const shapedArtifacts = await Promise.all(
    storedArtifacts.map((artifact) => shapePublicArtifactRecord(app, artifact)),
  );
  await resequenceDeviceQueue(app, updatedTask.targetDeviceId);

  await insertTaskEvent(app, {
    taskId: ownedTask.id,
    status: input.status,
    message: input.message,
    payload: {
      summary: input.summary,
      error: input.error,
      approvalRequest: input.approvalRequest,
      operator: input.operator,
      artifactCount: shapedArtifacts.length,
      artifacts: shapedArtifacts,
    },
  });

  if (isTerminalTaskStatus(input.status)) {
    await app.services.reliability.clearTaskDispatchLock(ownedTask.id);
    const payload = ownedTask.payload && typeof ownedTask.payload === "object" && !Array.isArray(ownedTask.payload)
      ? (ownedTask.payload as Record<string, unknown>)
      : {};

    await recordTaskLearningFromCompletion(app, {
      userId: ownedTask.userId,
      accountId: ownedTask.userId,
      taskId: ownedTask.id,
      title: ownedTask.title,
      message: getTaskPrompt(payload),
      status: input.status as "completed" | "failed" | "canceled",
    });
    void maybeQueueAutomaticSharedBrainRefresh(app, {
      userId: ownedTask.userId,
      source: `runtime_task_${input.status}`,
    }).catch(() => undefined);

    if (input.status === "completed") {
      await recordQuantumLearningSignal(app, {
        task: ownedTask,
        result: input.result,
      });
    }
  }

  await publishTaskEvent(app, updatedTask, "task.updated", {
    task: shapeTaskFeedItem(updatedTask),
    artifactCount: shapedArtifacts.length,
  });

  if (shapedArtifacts.length > 0) {
    await publishTaskEvent(app, updatedTask, "task.artifacts", {
      taskId: updatedTask.id,
      artifacts: shapedArtifacts,
    });
  }

  await syncChatTaskLifecycle(app, {
    originalTask: ownedTask,
    updatedTask,
    message: input.message,
  });

  return {
    task: updatedTask,
    storedArtifacts: shapedArtifacts,
  };
}

export async function submitTaskFeedback(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId: string;
    feedbackType: FeedbackType;
    reasonTags?: string[];
    correction?: string;
    preferredAnswer?: string;
    ipAddress?: string;
    userAgent?: string;
    requestId: string;
  },
) {
  const task = await getTaskForUser(app, input.taskId, input.userId);
  const persistedCount = await recordTaskFeedback(app, {
    userId: input.userId,
    accountId: input.userId,
    taskId: task.id,
    feedbackType: input.feedbackType,
    reasonTags: input.reasonTags,
    correction: input.correction,
    preferredAnswer: input.preferredAnswer,
    requestId: input.requestId,
  });
  void maybeQueueAutomaticSharedBrainRefresh(app, {
    userId: input.userId,
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    source: "task_feedback",
  }).catch(() => undefined);

  await insertTaskEvent(app, {
    taskId: task.id,
    status: task.status,
    message: "Task feedback received",
    payload: {
      feedbackType: input.feedbackType,
      reasonTags: input.reasonTags ?? [],
      persistedLearningEvents: persistedCount,
    },
  });

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "task.feedback",
    resourceType: "task",
    resourceId: task.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      feedbackType: input.feedbackType,
      reasonTags: input.reasonTags ?? [],
      persistedLearningEvents: persistedCount,
    },
  });

  return {
    ok: true,
    taskId: task.id,
    persistedLearningEvents: persistedCount,
  };
}

export async function appendTaskArtifacts(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  taskId: string,
  items: ArtifactInput[],
) {
  const task = await getTaskForRuntime(app, taskId, auth);
  const ownedTask = await ensureTaskRuntimeOwnership(app, task, auth);
  const storedArtifacts = await persistArtifacts(app, ownedTask.id, items);
  const shapedArtifacts = await Promise.all(
    storedArtifacts.map((artifact) => shapePublicArtifactRecord(app, artifact)),
  );

  await insertTaskEvent(app, {
    taskId: ownedTask.id,
    status: ownedTask.status,
    message: "Artifacts appended",
    payload: {
      artifactCount: shapedArtifacts.length,
      artifacts: shapedArtifacts,
    },
  });

  await publishTaskEvent(app, ownedTask, "task.artifacts", {
    taskId: ownedTask.id,
    artifacts: shapedArtifacts,
  });

  return {
    taskId: ownedTask.id,
    artifacts: shapedArtifacts,
  };
}
