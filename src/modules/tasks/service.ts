import { createHash, createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { unicodeWordPattern } from "../../lib/tr-word-boundary.js";
import { ensureUserFacingMessage } from "../brain/capability-label-guard.js";
import { and, asc, desc, eq, inArray, isNull, lt, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import type { ArtifactInput, TaskStatus } from "../../contracts/domain.js";
import {
  artifacts,
  chatSessions,
  learningEvents,
  runtimeConnections,
  taskEvents,
  tasks,
} from "../../db/schema.js";
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
  recordBlockQualityLearning,
  recordTaskFailureLearning,
} from "../../core/understanding/user-understanding-service.js";
import type {
  FeedbackType,
  UnderstandingEnvelope,
  UserUnderstandingResult,
} from "../../core/understanding/types.js";
import {
  envelopeTelemetrySummary,
  preferredWorkloadFromUnderstandingEnvelope,
} from "../../core/understanding/understanding-envelope.js";
import { selectToolSkillForTurn } from "../../core/understanding/tool-skill-selector.js";
import {
  isExplicitChartRequest,
  isExplicitMathOrLatexRequest,
  isExplicitSvgRequest,
  shouldPromoteMarkdownTableToWidget,
} from "../../core/understanding/structured-output-policy.js";
import { createAuditLog } from "../audit/service.js";
import { getUserApprovalMode } from "../approval-policy/service.js";
import { deriveTaskFailureSignature } from "./task-failure-analytics.js";
import {
  extractAttachmentMetadataCarrier,
  extractAttachmentCandidatesFromBrainContext,
  resolveAttachmentContextWithCache,
} from "../brain/attachment-context.js";
import { buildSharedBrainAckText } from "../brain/chat-heuristics.js";
import { extractClientAttachments } from "../brain/document-types.js";
import {
  clearEphemeralVisionCarrier,
  countDistinctEphemeralImages,
  ephemeralVisionCarrierSchema,
  type EphemeralVisionCarrier,
} from "../brain/ephemeral-vision.js";
import { buildDocumentContextBlock } from "../brain/document-context.js";
import {
  parseVisionEvidence,
  type VisionEvidenceV3,
} from "../brain/vision-evidence-v3.js";
import {
  readVerifiedQuantumBenchmark,
  type VerifiedQuantumBenchmark,
} from "../brain/quantum-benchmark.js";
import {
  buildAssistantCodeBlock,
  buildAssistantDocumentBlock,
  buildAssistantTableBlock,
} from "../chat/message-blocks.js";
import {
  isHostedImageEditIntent,
  isHostedImageEditRequest,
  isHostedImageGenerationRequest,
  maybeGenerateHostedImageArtifact,
  type HostedImageSource,
} from "../brain/image-generation.js";
import { sanitizeFinalAssistantResponse } from "../brain/response-policy.js";
import { generateGovernedSharedBrainReply } from "../brain/inference.js";
import {
  executeAgentTool,
  type AgentToolRequest,
} from "../brain/tool-registry.js";
import {
  connectorWriteTaskIdFromToken,
  readCanonicalConnectorWriteApprovalCall,
} from "../brain/connector-write-approvals.js";
import {
  materializeLegacyVisionForDurableQueue,
  releaseMediaInputsFromMetadata,
  resolveMediaInput,
  resolveMediaInputSources,
  resolveMediaInputVisionCarrier,
} from "./media-inputs.js";
import { validateExecutionPlanWithGeminiFree } from "../brain/gemini-execution-validator.js";
import { normalizeFreshDataEnvelope } from "../brain/fresh-data-policy.js";
import {
  cancelAgentRunForTask,
  resumeAgentRunAfterApproval,
} from "../brain/agent-engine.js";
import { maybeQueueAutomaticSharedBrainRefresh } from "../brain/service.js";
import {
  resolveAttachmentAwareSharedBrainWorkload,
  sharedBrainWorkloadValues,
  type SharedBrainWorkload,
} from "../brain/workloads.js";
import {
  chatGenerationProviderForStage,
  decideChatQueueAdmission,
  getChatGenerationQueueLimits,
  type ChatGenerationProviderStage,
} from "../brain/chat-generation-policy.js";
import {
  enqueueSharedBrainChatTask,
  isChatGenerationQueueEnabled,
  releaseChatGenerationAdmission,
  reserveChatGenerationAdmission,
} from "../brain/chat-generation-queue.js";
import {
  type AssistantMessageBlock,
  applyAssistantBlockSemanticQuality,
  composeAssistantMessageBlocks,
  normalizeAssistantMessageBlocks,
  sanitizeAssistantVisibleText,
  shapeAssistantMessagePayload,
  validateAssistantBlockContract,
  withAssistantBlocksMetadata,
} from "../chat/message-blocks.js";
import { chatMessages } from "../../db/schema.js";
import {
  syncChatTaskLifecycle,
  compactMessagePreview,
} from "../chat/task-sync.js";
import { buildTaskTraceBlock, advanceTaskTraceApproval, enrichTaskTraceWithAgentPlan } from "../chat/task-trace.js";
import {
  chatStreamEventStatusRank,
  isAssistantMessageTerminallyFenced,
  isTerminalChatStreamEvent,
  markAssistantMessageTerminal,
} from "../chat/stream-authority.js";
import {
  persistRollingSummaryToSession,
  listChatSessionMessages,
} from "../chat/service.js";
import { applyGoalProgressBlocks } from "../goals/service.js";
import { startStage } from "../../lib/perf-telemetry.js";
import {
  detectGoalChatCommand,
  executeGoalChatCommand,
} from "../goals/chat-goal-commands.js";
import {
  getUserDevice,
  RUNTIME_CONNECTION_STALE_AFTER_MS,
} from "../devices/service.js";
import {
  decideCommandRoute,
  resolveCommandTarget,
  resolvePendingDesktopQueueTarget,
} from "../routing-policy/service.js";
import type { CommandRouteDecision } from "../routing-policy/service.js";
import {
  recordUsageLedgerEntry,
  BILLING_USAGE_METRICS,
} from "../billing/usage-ledger.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";
import {
  createUpgradeOrByokRequiredError,
  getUserUsageAccessTruth,
} from "../billing/service.js";
import {
  assertAttachmentQuotaAllowedFromUsage,
  assertTrialTaskQuotaAllowedFromUsage,
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
  resolveSafeChatContinuityReply,
  resolveIdempotentTaskMatch,
  sanitizePublicTaskEventPayload,
  sanitizePublicInferenceValue,
  shapeTaskFeedItem,
  shapeTaskArtifact,
} from "./service-helpers.js";
import {
  TASK_DISPATCH_LEASE_MS,
  TASK_APPROVAL_TTL_MS,
  MAX_ACTIVE_USER_APPROVALS,
  MAX_TASK_DISPATCH_ATTEMPTS,
  buildTaskApprovalResumeUpdate,
  buildTaskCancellationUpdate,
  buildTaskDispatchExhaustedUpdate,
  buildTaskDispatchLeaseAckUpdate,
  buildTaskDispatchLeaseReleaseUpdate,
  buildTaskDispatchLeaseUpdate,
  buildTaskRuntimeOwnershipUpdate,
  buildTaskRuntimeUpdate,
  isApprovalAlreadyResolved,
  isApprovalRequestExpired,
  normalizeTaskApprovalRequest,
  shouldAutoApproveDesktopTask,
} from "./service-lifecycle.js";
import {
  buildDesktopWorkOrder,
  isDeterministicDesktopFastWorkOrder,
} from "./desktop-work-order.js";
import { enqueueTaskDispatch } from "./dispatch-queue.js";
import { assertTaskTransition, isTerminalTaskStatus } from "./transitions.js";
import { canUseDesktopConnections } from "../billing/catalog.js";
import {
  normalizeRemoteMcpSelectionMetadata,
  resolveRemoteMcpRequest,
} from "../integrations/service.js";
import { normalizeLocalDerivedMetadata } from "../../lib/derived-data.js";
import {
  buildLocalRenderRecipe,
  type LocalRenderRecipe,
} from "../../core/understanding/render-recipe.js";
import { understandingEnvelopeSchema } from "../../core/understanding/types.js";
import {
  artifactResultForTask,
  buildArtifactPipeline,
  recordArtifactLearningEvent,
} from "../artifacts/service.js";
import { artifactSpecToRenderRecipeBlocks } from "../artifacts/render-recipe-adapter.js";
import type { ArtifactOutput } from "../artifacts/types.js";
export { canonicalTaskTitle, shapeTaskFeedItem } from "./service-helpers.js";

type ShapedTaskFeedItem = ReturnType<typeof shapeTaskFeedItem>;

const STALE_RUNTIME_TASK_AFTER_MS = 120_000;

function visibleTextFromAssistantBlocks(
  blocks: AssistantMessageBlock[] | undefined,
): string {
  if (!Array.isArray(blocks) || blocks.length === 0) {
    return "";
  }
  return blocks
    .filter(
      (
        block,
      ): block is AssistantMessageBlock & { type: "text"; markdown: string } =>
        block.type === "text",
    )
    .map((block) => block.markdown.trim())
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

function normalizePromptEchoText(value: string | null | undefined) {
  return String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase("tr-TR")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Görünür metin politikası. Akış hattı ile nihai hat aynı opsiyonları
 * kullanmazsa kullanıcı akışta bir metin görüp sonra başkasına dönüştüğüne
 * tanık olur ("cevap sonradan değişti"). Bu yüzden opsiyon artık sabit değil,
 * her iki çağıranın da açıkça geçirdiği bir parametre.
 */
export type AssistantVisibleTextPolicy = {
  allowPublicProviderReferences?: boolean;
};

/**
 * "Cevap düzeltildi" sinyali için karşılaştırma normalizasyonu. Nihai hattaki
 * cilalama (fazla boş satır, satır sonu boşluk) her mesajı "düzeltilmiş"
 * göstermesin; yalnızca içerik gerçekten değiştiyse işaretle.
 */
export function normalizeRevisionComparableText(
  value: string | null | undefined,
): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildAssistantRevisionMetadata(input: {
  finalContent: string;
  streamedContent: string;
  transientContent?: string;
}) {
  const previousContent = input.streamedContent.trim().slice(0, 12_000);
  const onlyTransientContent =
    previousContent.length > 0 &&
    normalizeRevisionComparableText(previousContent) ===
      normalizeRevisionComparableText(input.transientContent ?? "");
  const revised =
    previousContent.length > 0 &&
    !onlyTransientContent &&
    normalizeRevisionComparableText(input.finalContent) !==
      normalizeRevisionComparableText(previousContent);
  return revised
    ? { revised: true, previousContent }
    : { revised: false };
}

export function stripPromptEchoFromAssistantText(input: {
  prompt: string;
  responseText: string;
  policy?: AssistantVisibleTextPolicy;
}) {
  const sanitizerOptions = {
    fallback: "",
    allowPublicProviderReferences:
      input.policy?.allowPublicProviderReferences === true,
  };
  const responseText = sanitizeAssistantVisibleText(
    input.responseText,
    sanitizerOptions,
  ).trim();
  const prompt = sanitizeAssistantVisibleText(
    input.prompt,
    sanitizerOptions,
  ).trim();
  if (!prompt || !responseText) {
    return responseText;
  }

  const normalizedPrompt = normalizePromptEchoText(prompt);
  const normalizedResponse = normalizePromptEchoText(responseText);
  if (!normalizedPrompt || !normalizedResponse) {
    return responseText;
  }
  if (normalizedResponse === normalizedPrompt) {
    return "";
  }

  const lowerPrompt = prompt.toLocaleLowerCase("tr-TR");
  const lowerResponse = responseText.toLocaleLowerCase("tr-TR");
  if (lowerResponse.startsWith(lowerPrompt)) {
    return responseText
      .slice(prompt.length)
      .replace(/^[\s:;,.!?'"“”‘’\-–—]+/u, "")
      .trim();
  }

  return responseText;
}

function buildPromptEchoRecoveryAnswer(prompt: string) {
  const normalized = normalizePromptEchoText(prompt);
  if (!normalized) {
    return "";
  }

  const asksAnimalName =
    /\bhayvan\b/u.test(normalized) &&
    unicodeWordPattern(String.raw`\b(isim|ismi|ad|adı|adi|soyle|söyle|oner|öner|bul)\b`, "").test(normalized);
  if (asksAnimalName) {
    return "Yıldız burunlu köstebek. Burnunda yıldız şeklinde 22 dokunaç bulunan, çok az bilinen ve oldukça sıra dışı görünümlü bir memeli.";
  }

  return "";
}

export function resolveNonEchoAssistantText(input: {
  prompt: string;
  responseText: string;
  policy?: AssistantVisibleTextPolicy;
}) {
  const stripped = stripPromptEchoFromAssistantText(input);
  if (stripped) {
    return stripped;
  }

  const recovery = buildPromptEchoRecoveryAnswer(input.prompt);
  if (recovery) {
    return recovery;
  }

  return "Yanıtı düzgün üretemedim. Lütfen tekrar dene.";
}

function conversationTextFromChatMessage(message: {
  role: "user" | "assistant";
  content?: string | null;
  blocks?: AssistantMessageBlock[];
}): string {
  if (message.role === "assistant") {
    const blockText = visibleTextFromAssistantBlocks(message.blocks);
    if (blockText) {
      return blockText;
    }
  }
  return typeof message.content === "string" ? message.content.trim() : "";
}

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

function hostedImageSources(carrier?: EphemeralVisionCarrier): HostedImageSource[] {
  const seen = new Set<string>();
  const result: HostedImageSource[] = [];
  for (const image of carrier?.images ?? []) {
    if (image.kind !== "full_frame" || seen.has(image.imageId)) continue;
    seen.add(image.imageId);
    result.push({ base64Data: image.base64Data, mimeType: image.mimeType });
    if (result.length >= 4) break;
  }
  return result;
}

function bindAuthorizedMediaInputRefs(
  metadata: Record<string, unknown>,
  carrier: EphemeralVisionCarrier | undefined,
): void {
  if (
    carrier?.version === 2 &&
    carrier.privacy.userAuthorizedCloud === true &&
    carrier.privacy.metadataStripped === true
  ) {
    metadata.mediaInputRefs = carrier.inputRefs.map((ref) => ({
      inputRef: ref.inputRef,
      name: ref.name,
      contentType: ref.contentType,
      byteLength: ref.byteLength,
      expiresAt: ref.expiresAt,
    }));
    metadata.mediaInputPrivacy = {
      localSensitivity: carrier.privacy.localSensitivity,
    };
    return;
  }
  delete metadata.mediaInputRefs;
  delete metadata.mediaInputPrivacy;
}

export type SharedBrainChatDispatchPolicy =
  | "not_applicable"
  | "direct"
  | "durable_queue"
  | "reject_queue_unavailable"
  | "reject_legacy_inline_vision";

export function createChatQueueUnavailableError(): AppError {
  return new AppError(
    503,
    "chat_queue_unavailable",
    "Buradayım. Bu isteği güvenli biçimde işleyebilmem için birkaç saniye sonra aynı yerden devam edelim.",
    {
      transient: true,
      retrySuggested: true,
      failureClass: "queue_unavailable",
    },
  );
}

export function createDurableChatMediaInputRequiredError(): AppError {
  return new AppError(
    422,
    "durable_chat_media_input_required",
    "Görseli güvenli medya yükleme akışıyla yeniden ekleyip tekrar dene.",
    {
      acceptedMediaInputVersion: 2,
      transient: false,
      retrySuggested: false,
    },
  );
}

export function resolveSharedBrainChatDispatchPolicy(
  app: FastifyInstance,
  input: {
    isSharedBrain: boolean;
    useFastSharedBrainFlow: boolean;
    ephemeralVision?: EphemeralVisionCarrier;
  },
): SharedBrainChatDispatchPolicy {
  if (!input.isSharedBrain || !input.useFastSharedBrainFlow) {
    return "not_applicable";
  }
  if (app.config.ELYAN_CHAT_QUEUE_ENABLED !== true) {
    return "direct";
  }
  if (!isChatGenerationQueueEnabled(app)) return "reject_queue_unavailable";
  if (input.ephemeralVision?.version === 1) {
    return "reject_legacy_inline_vision";
  }
  return "durable_queue";
}

export function restoreQueuedEphemeralVisionCarrier(
  metadata: Record<string, unknown>,
): EphemeralVisionCarrier | undefined {
  if (!Array.isArray(metadata.mediaInputRefs) || metadata.mediaInputRefs.length === 0) {
    return undefined;
  }
  const privacy = readRecord(metadata.mediaInputPrivacy);
  const sensitivity = String(privacy?.localSensitivity ?? "personal");
  const localSensitivity = (
    ["none", "personal", "sensitive", "restricted"] as const
  ).includes(sensitivity as "none" | "personal" | "sensitive" | "restricted")
    ? (sensitivity as "none" | "personal" | "sensitive" | "restricted")
    : "personal";
  const parsed = ephemeralVisionCarrierSchema.safeParse({
    version: 2,
    retention: "request_ephemeral",
    privacy: {
      metadataStripped: true,
      userAuthorizedCloud: true,
      localSensitivity,
    },
    inputRefs: metadata.mediaInputRefs,
  });
  return parsed.success ? parsed.data : undefined;
}

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
  qualityGuard?: CommandRouteDecision["qualityGuard"];
};

function normalizeRouteOrigin(value: unknown): RouteDecisionLogEntry["origin"] {
  const origin = String(value ?? "")
    .trim()
    .toLowerCase();
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
      value === "mobile_local" ||
      value === "server_brain" ||
      value === "desktop_runtime",
  );

  if (normalized.length > 0) {
    return normalized;
  }

  if (
    routeDecision?.taskRoute?.operationalRoute === "desktop_runtime" ||
    routeDecision?.route === "desktop_runtime"
  ) {
    return ["desktop_runtime"];
  }

  return ["server_brain"];
}

function readInferenceString(
  metadata: Record<string, unknown>,
  key: string,
): string | null {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readInferenceNumber(
  metadata: Record<string, unknown>,
  key: string,
): number | null {
  const value = metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readInferenceStringList(
  metadata: Record<string, unknown>,
  key: string,
): string[] {
  const value = metadata[key];
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "string" ? item.trim() : ""))
        .filter(Boolean)
        .slice(0, 8)
    : [];
}

function readFreshDataDomainString(
  metadata: Record<string, unknown>,
): string | null {
  const value = readInferenceString(metadata, "freshDataDomain");
  return value &&
    [
      "news",
      "market",
      "weather",
      "sports",
      "regulation",
      "software_security",
      "software_release",
      "url_review",
      "general",
    ].includes(value)
    ? value
    : null;
}

function readFreshDataStatusString(
  metadata: Record<string, unknown>,
): string | null {
  const value = readInferenceString(metadata, "freshDataStatus");
  return value &&
    ["fresh", "aging", "stale", "undated", "unavailable"].includes(value)
    ? value
    : null;
}

function readInferenceBoolean(
  metadata: Record<string, unknown>,
  key: string,
): boolean | null {
  const value = metadata[key];
  return typeof value === "boolean" ? value : null;
}

function buildChatStreamEnvelope(input: {
  event:
    | "message.created"
    | "message.delta"
    | "block.preview"
    | "message.completed"
    | "message.error"
    | "usage.final"
    | "heartbeat";
  taskId: string;
  sessionId: string;
  messageId: string;
  seq: number;
  timestamp?: string;
  payload?: Record<string, unknown>;
}) {
  const timestamp = input.timestamp ?? new Date().toISOString();
  // statusRank: consumer tarafındaki terminal fence'in anahtarı. Aynı
  // assistantMessageId için completed (rank 90) görüldükten sonra daha düşük
  // rank'li her event (delta/heartbeat/ACK snapshot) yok sayılmalıdır; seq ve
  // timestamp kaynaklar arası karşılaştırılamaz, rank karşılaştırılır.
  const statusRank = chatStreamEventStatusRank(input.event);
  const terminal = isTerminalChatStreamEvent(input.event);
  return {
    event: input.event,
    taskId: input.taskId,
    sessionId: input.sessionId,
    messageId: input.messageId,
    seq: input.seq,
    statusRank,
    terminal,
    timestamp,
    ...(input.payload ?? {}),
    payload: {
      statusRank,
      terminal,
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
    event:
      | "message.created"
      | "message.delta"
      | "block.preview"
      | "message.completed"
      | "message.error"
      | "usage.final"
      | "heartbeat";
    seq: number;
    payload?: Record<string, unknown>;
  },
) {
  // Terminal fence: kalıcı final (completed/error) yazıldıktan sonra uçuşta
  // kalan heartbeat/delta timer'ları aynı mesaj için volatile event basamaz.
  // Aksi hâlde mobil, final cevabı aldıktan sonra eski "running" snapshot'ıyla
  // geri "Yanıt hazırlanıyor."a döner.
  if (
    !isTerminalChatStreamEvent(input.event) &&
    isAssistantMessageTerminallyFenced(input.messageId)
  ) {
    return;
  }
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
    event:
      "message.created" | "message.completed" | "message.error" | "usage.final";
    seq: number;
    payload?: Record<string, unknown>;
  },
) {
  if (isTerminalChatStreamEvent(input.event)) {
    markAssistantMessageTerminal(input.messageId);
  }
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

export type ToolFlowTraceSummary = {
  count: number;
  okCount: number;
  tools: Array<{
    name: string;
    ok: boolean;
    resultCount: number | null;
    errorCode: string | null;
    durationMs: number | null;
  }>;
};

// Sunucu-taraflı connector/agent araç çağrılarının (Gmail/Takvim/Drive vb.)
// task-trace kartında görünür olması için güvenli, sınırlı bir özet çıkarır.
// Yalnız araç kimliği + ok bayrağı + sonuç sayısı + güvenli hata kodu taşınır — hiçbir araç çıktısı
// (mail içeriği, dosya adı) buraya girmez; kaynak zaten summarizeToolResults-
// ForMetadata ile sadeleştirilmiştir.
export function summarizeToolFlowForTrace(
  value: unknown,
): ToolFlowTraceSummary | null {
  if (!Array.isArray(value) || value.length === 0) {
    return null;
  }
  const tools: ToolFlowTraceSummary["tools"] = [];
  let okCount = 0;
  for (const item of value) {
    const record = readRecord(item);
    if (!record) {
      continue;
    }
    const name = readInferenceString(record, "tool");
    if (!name) {
      continue;
    }
    const ok = record.ok === true;
    if (ok) {
      okCount += 1;
    }
    const output = readRecord(record.output);
    const resultCount =
      output &&
      typeof output.resultCount === "number" &&
      Number.isFinite(output.resultCount)
        ? output.resultCount
        : null;
    const error = readRecord(record.error);
    const errorCode =
      readInferenceString(record, "errorCode") ??
      readInferenceString(error ?? {}, "code");
    const rawDurationMs = readInferenceNumber(record, "durationMs");
    const durationMs = rawDurationMs != null && rawDurationMs >= 0 ? rawDurationMs : null;
    tools.push({ name, ok, resultCount, errorCode, durationMs });
    if (tools.length >= 8) {
      break;
    }
  }
  if (tools.length === 0) {
    return null;
  }
  return { count: tools.length, okCount, tools };
}

// Staged connector-write onay taslağı (gmail.send/calendar.create_event).
// Yalnız onay çipini besleyen güvenli alanlar taşınır — token kullanıcının
// kendi cihazına aittir ve endpoint ayrıca userId doğrular.
export function readConnectorWriteApproval(metadata: Record<string, unknown>) {
  const record = readRecord(metadata.connectorWriteApproval);
  if (!record) {
    return null;
  }
  const token = readInferenceString(record, "token");
  const tool = readInferenceString(record, "tool");
  const title = readInferenceString(record, "title");
  if (!token || !tool || !title) {
    return null;
  }
  const rawLines = Array.isArray(record.lines) ? record.lines : [];
  const lines = rawLines
    .map((item) => {
      const line = readRecord(item);
      if (!line) {
        return null;
      }
      const label = readInferenceString(line, "label");
      const value = readInferenceString(line, "value");
      return label && value != null ? { label, value } : null;
    })
    .filter((item): item is { label: string; value: string } => item != null)
    .slice(0, 8);
  return {
    token,
    tool,
    title,
    appLabel: readInferenceString(record, "appLabel") ?? "",
    expiresAt:
      typeof record.expiresAt === "number" && Number.isFinite(record.expiresAt)
        ? record.expiresAt
        : null,
    lines,
  };
}

export function readServerBrainCompletionMetadata(
  metadata: Record<string, unknown>,
) {
  const documentSourceCount =
    readInferenceNumber(metadata, "documentSourceCount") ?? 0;
  const webSourceCount = readInferenceNumber(metadata, "webSourceCount") ?? 0;
  const webGroundingUsed =
    readInferenceBoolean(metadata, "webGroundingUsed") ?? webSourceCount > 0;
  const groundingUsed =
    readInferenceBoolean(metadata, "groundingUsed") ??
    (documentSourceCount > 0 || webGroundingUsed);
  const freshData = normalizeFreshDataEnvelope(metadata.freshData);
  const parsedVisionEvidence = parseVisionEvidence(metadata.visionBlock);
  const visionBlock =
    parsedVisionEvidence?.version === 3
      ? (parsedVisionEvidence as VisionEvidenceV3)
      : null;

  return {
    firstDeltaMs: readInferenceNumber(metadata, "firstDeltaMs"),
    modelRoute: readRecord(metadata.modelRoute) ?? null,
    fallbackUsed: Boolean(metadata.fallbackUsed),
    fallbackState: readInferenceString(metadata, "fallbackState"),
    groundingUsed,
    documentSourceCount,
    webGroundingUsed,
    webSourceCount,
    attachmentContextUsed: Boolean(metadata.attachmentContextUsed),
    attachmentContextSource: readInferenceString(
      metadata,
      "attachmentContextSource",
    ),
    attachmentDocumentIds: readAttachmentDocumentIds(
      metadata.attachmentDocumentIds,
    ),
    skillUsed: Boolean(metadata.skillUsed),
    skillId: readInferenceString(metadata, "skillId"),
    skillVersion: readInferenceString(metadata, "skillVersion"),
    skillConfidence:
      typeof metadata.skillConfidence === "number" &&
      Number.isFinite(metadata.skillConfidence)
        ? metadata.skillConfidence
        : null,
    selectedChunkHashes: readAttachmentDocumentIds(
      metadata.selectedChunkHashes,
    ),
    validationStatus: readInferenceString(metadata, "validationStatus"),
    cacheHit: Boolean(metadata.cacheHit),
    attachmentCacheHit: Boolean(
      typeof metadata.attachmentCacheHit === "boolean"
        ? metadata.attachmentCacheHit
        : metadata.cacheHit,
    ),
    retrievalMode: readInferenceString(metadata, "retrievalMode"),
    retrievalResultCount: readInferenceNumber(metadata, "retrievalResultCount"),
    retrievalCandidateCount: readInferenceNumber(
      metadata,
      "retrievalCandidateCount",
    ),
    retrievalLexicalCandidateCount: readInferenceNumber(
      metadata,
      "retrievalLexicalCandidateCount",
    ),
    retrievalSemanticCandidateCount: readInferenceNumber(
      metadata,
      "retrievalSemanticCandidateCount",
    ),
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
    dataQualityWarnings: readInferenceStringList(
      metadata,
      "dataQualityWarnings",
    ),
    claimConfidence: readInferenceNumber(metadata, "claimConfidence"),
    claimSourceCounts: readRecord(metadata.claimSourceCounts) ?? null,
    uncertaintyAction: readInferenceString(metadata, "uncertaintyAction"),
    missingEvidenceCount: readInferenceNumber(metadata, "missingEvidenceCount"),
    verifiedEvidenceCount: readInferenceNumber(
      metadata,
      "verifiedEvidenceCount",
    ),
    contestedMemoryCount: readInferenceNumber(metadata, "contestedMemoryCount"),
    lowConfidenceClaims: readInferenceNumber(metadata, "lowConfidenceClaims"),
    selfCheckApplied: readInferenceBoolean(metadata, "selfCheckApplied"),
    toolCalledForUncertainty: readInferenceBoolean(
      metadata,
      "toolCalledForUncertainty",
    ),
    clarificationRequested: readInferenceBoolean(
      metadata,
      "clarificationRequested",
    ),
    responseBudgetState: readInferenceString(metadata, "responseBudgetState"),
    responseBudgetReason: readInferenceString(metadata, "responseBudgetReason"),
    contextPacketCount: readInferenceNumber(metadata, "contextPacketCount"),
    contextPacketKinds: readInferenceStringList(metadata, "contextPacketKinds"),
    healthContextUsed: Boolean(metadata.healthContextUsed),
    contextFreshness: metadata.contextFreshness ?? null,
    freshData,
    freshDataDomain: freshData?.domain ?? readFreshDataDomainString(metadata),
    freshDataStatus: freshData?.status ?? readFreshDataStatusString(metadata),
    freshDataEvidenceSufficient:
      freshData?.evidence.sufficient ??
      readInferenceBoolean(metadata, "freshDataEvidenceSufficient"),
    freshDataStreamPolicy:
      freshData?.freshnessRequired === true &&
      freshData.evidence.sufficient === false
        ? "buffer_until_validated"
        : readInferenceString(metadata, "freshDataStreamPolicy"),
    assistantBlocks: Array.isArray(metadata.blocks) ? metadata.blocks : [],
    authoritativeArtifactData:
      readRecord(metadata.authoritativeArtifactData) ?? null,
    visionBlock,
    toolFlow: summarizeToolFlowForTrace(metadata.toolResults),
    connectorWriteApproval: readConnectorWriteApproval(metadata),
    connectorWriteApprovalRequest: readRecord(
      metadata.connectorWriteApprovalRequest,
    ),
  };
}

function isMarkdownTableDivider(line: string) {
  const normalized = line.trim();
  if (!normalized.includes("|")) {
    return false;
  }
  const cells = normalized
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
  return (
    cells.length > 0 &&
    cells.every((cell) => cell.length > 0 && /^:?-{3,}:?$/.test(cell))
  );
}

function splitMarkdownTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

// Extract the first code fence from response markdown.
// Returns a typed code block AND the matched source span so the caller can
// strip it from the visible text (avoids the "code shown twice" duplication —
// once as markdown, once as the code widget).
function extractMarkdownCodeBlock(responseText: string) {
  const text = String(responseText ?? "");
  const match = /```(\w*)\n([\s\S]+?)```/.exec(text);
  if (!match) return null;
  const language = match[1].trim() || undefined;
  const code = match[2].trim();
  if (!code) return null;
  return {
    block: buildAssistantCodeBlock({ code, language }),
    source: match[0],
  };
}

// Extract structured document sections from responses with 3+ markdown headings.
// This activates the mobile document_block widget (PDF preview + share).
function extractMarkdownDocumentBlock(responseText: string) {
  const text = String(responseText ?? "").replace(/\r\n?/g, "\n");
  const lines = text.split("\n");

  const sections: Array<{ heading?: string; content: string; level: number }> =
    [];
  let currentHeading: string | undefined;
  let currentLevel = 1;
  let currentLines: string[] = [];
  let headingCount = 0;

  const flush = () => {
    const content = currentLines.join("\n").trim();
    if (content || currentHeading) {
      sections.push({ heading: currentHeading, content, level: currentLevel });
    }
    currentLines = [];
  };

  for (const line of lines) {
    const hMatch = /^(#{1,3})\s+(.+)/.exec(line.trim());
    if (hMatch) {
      flush();
      currentLevel = hMatch[1].length;
      currentHeading = hMatch[2].trim();
      headingCount += 1;
    } else {
      currentLines.push(line);
    }
  }
  flush();

  // Only extract when there are enough real sections with content
  const validSections = sections.filter(
    (s) => s.content.length > 0 || s.heading,
  );
  if (headingCount < 2 || validSections.length === 0) return null;

  const totalWords = validSections.reduce(
    (sum, s) => sum + s.content.split(/\s+/).filter(Boolean).length,
    0,
  );
  if (totalWords < 60) return null;

  // Treat the first section without heading as document title if it's short
  let title: string | undefined;
  const firstSection = validSections[0];
  if (
    !firstSection.heading &&
    firstSection.content.length < 120 &&
    validSections.length > 1
  ) {
    title = firstSection.content.split("\n")[0]?.trim();
    validSections.shift();
  } else if (
    firstSection.heading &&
    validSections.every((s) => s.level >= firstSection.level)
  ) {
    title = firstSection.heading;
    firstSection.heading = undefined;
  }

  const wordCount = validSections.reduce(
    (sum, s) =>
      sum +
      (s.heading ?? "").split(/\s+/).length +
      s.content.split(/\s+/).filter(Boolean).length,
    0,
  );

  // Document widget renders the full content — the raw text is redundant
  // alongside it, so signal "consume the whole response".
  return {
    block: buildAssistantDocumentBlock({
      title,
      sections: validSections,
      format: "report",
      wordCount,
    }),
    source: text,
  };
}

function extractMarkdownTableBlock(responseText: string) {
  const normalized = String(responseText ?? "").replace(/\r\n?/g, "\n");
  const lines = normalized.split("\n");
  for (let index = 0; index <= lines.length - 3; index += 1) {
    const headerLine = lines[index]?.trim() ?? "";
    const dividerLine = lines[index + 1]?.trim() ?? "";
    if (!headerLine.includes("|") || !isMarkdownTableDivider(dividerLine)) {
      continue;
    }
    const columns = splitMarkdownTableRow(headerLine);
    if (columns.length === 0) {
      continue;
    }

    const rows: string[][] = [];
    let lastRow = index + 1; // divider line
    for (let rowIndex = index + 2; rowIndex < lines.length; rowIndex += 1) {
      const rowLine = lines[rowIndex]?.trim() ?? "";
      if (!rowLine || !rowLine.includes("|")) {
        break;
      }
      if (isMarkdownTableDivider(rowLine)) {
        lastRow = rowIndex;
        continue;
      }
      const row = splitMarkdownTableRow(rowLine);
      if (row.length !== columns.length) {
        break;
      }
      rows.push(row);
      lastRow = rowIndex;
    }

    if (rows.length === 0) {
      continue;
    }

    // Source span = headerLine .. lastRow (joined back). Caller strips this
    // from the visible text so the table is not also rendered as markdown.
    const source = lines.slice(index, lastRow + 1).join("\n");
    return {
      block: buildAssistantTableBlock({ columns, rows }),
      source,
    };
  }

  return null;
}

// Some model outputs come back as a single bare JSON object whose `type` is
// one of our known structured block types. Render them as a real block widget
// instead of leaking JSON as plain text.
const STRUCTURED_BLOCK_TYPES = new Set<string>([
  "status",
  "summary",
  "next_steps",
  "desktop_suggestion",
  "actionable",
  "attachment_context",
  "context_signal",
  "memory_echo",
  "table",
  "chart",
  "math",
  "svg",
  "document_block",
]);

/**
 * Splits a response that starts with a single typed-block JSON object from any
 * trailing prose. Models prompted with "emit a status block, then write your
 * reply" return both in one turn (e.g.
 *   {"type":"status","status":"needs_desktop",...}\nMasaüstünüzdeki dosya…
 * ). The previous bare-only extractor missed this hybrid shape because the
 * string did not end in "}", and the raw JSON leaked into chat (prod bug).
 *
 * Approach: walk balanced braces from the first "{" to locate the boundary,
 * parse just that slice, and return both the block and any remaining text.
 * Quote/escape aware so braces inside strings cannot fool the depth counter.
 */
function extractLeadingJsonBlock(
  responseText: string,
): { block: Record<string, unknown>; rest: string } | null {
  const text = String(responseText ?? "");
  const start = text.indexOf("{");
  if (start === -1) return null;
  // Only treat it as a leading block when nothing meaningful precedes the "{".
  if (text.slice(0, start).trim().length > 0) return null;

  let depth = 0;
  let inString = false;
  let escape = false;
  let end = -1;
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (ch === "\\") {
      escape = true;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      continue;
    }
    if (inString) continue;
    if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  if (end === -1) return null;

  const candidate = text.slice(start, end + 1);
  try {
    const parsed = JSON.parse(candidate) as Record<string, unknown>;
    const type = String(parsed?.type ?? "")
      .trim()
      .toLowerCase();
    if (!STRUCTURED_BLOCK_TYPES.has(type)) return null;
    return { block: parsed, rest: text.slice(end + 1).trimStart() };
  } catch {
    return null;
  }
}

function shouldAcceptStructuredBlock(input: {
  block: Record<string, unknown>;
  prompt?: string | null;
  selectedWorkload?: string | null;
}) {
  const type = String(input.block.type ?? "")
    .trim()
    .toLowerCase();
  const selectedWorkload = String(input.selectedWorkload ?? "")
    .trim()
    .toLowerCase();
  if (type === "table") {
    return shouldPromoteMarkdownTableToWidget({
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    });
  }
  if (type === "chart") {
    return isExplicitChartRequest(input.prompt ?? "");
  }
  if (type === "svg") {
    return isExplicitSvgRequest(input.prompt ?? "");
  }
  if (type === "math") {
    return isExplicitMathOrLatexRequest(input.prompt ?? "");
  }
  if (type === "document_block") {
    return selectedWorkload === "document_generate";
  }
  return true;
}

function filterAssistantBlocksByIntent(input: {
  blocks: unknown[];
  prompt?: string | null;
  selectedWorkload?: string | null;
}) {
  return input.blocks.filter((block) => {
    if (!block || typeof block !== "object" || Array.isArray(block)) {
      return true;
    }
    return shouldAcceptStructuredBlock({
      block: block as Record<string, unknown>,
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    });
  });
}

function cleanInlineMarkdown(value: unknown, maxLength = 160) {
  return String(value ?? "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
}

function structuredBlockToPlainFallback(
  block: Record<string, unknown>,
): string {
  const type = String(block.type ?? "")
    .trim()
    .toLowerCase();
  if (type !== "table") {
    return "";
  }
  const columns = Array.isArray(block.columns)
    ? block.columns
        .map((column) => cleanInlineMarkdown(column, 80))
        .filter(Boolean)
    : [];
  const rows = Array.isArray(block.rows) ? block.rows.slice(0, 12) : [];
  if (columns.length === 0 || rows.length === 0) {
    return "";
  }
  const title = cleanInlineMarkdown(block.title, 120);
  const lines = title ? [`${title}:`] : [];
  for (const rawRow of rows) {
    const row = Array.isArray(rawRow)
      ? rawRow
      : rawRow && typeof rawRow === "object" && !Array.isArray(rawRow)
        ? Object.values(rawRow as Record<string, unknown>)
        : [];
    const cells = row.map((cell) => cleanInlineMarkdown(cell, 140));
    const head = cells[0];
    if (!head) {
      continue;
    }
    const details = cells
      .slice(1, columns.length)
      .map((cell, index) => {
        const label = columns[index + 1] ?? "";
        return cell ? `${label ? `${label}: ` : ""}${cell}` : "";
      })
      .filter(Boolean)
      .join("; ");
    lines.push(`- ${head}${details ? `: ${details}` : ""}`);
  }
  return lines.join("\n");
}

function stripDanglingStructuredJsonTail(text: string): string {
  const value = String(text ?? "");
  const lastBrace = Math.max(value.lastIndexOf("{"), value.lastIndexOf("["));
  if (lastBrace < 0) {
    return value;
  }

  const tail = value.slice(lastBrace).trim();
  if (!tail || /[}\]]$/.test(tail)) {
    return value;
  }
  const opener = value[lastBrace];
  if (
    (opener === "{" && tail.includes("}")) ||
    (opener === "[" && tail.includes("]"))
  ) {
    return value;
  }

  try {
    JSON.parse(tail);
    return value;
  } catch {
    const prefix = value.slice(0, lastBrace).trimEnd();
    const cleaned = prefix.replace(/[,\s:;]+$/u, "").trimEnd();
    return cleaned || prefix;
  }
}

export function resolveCompletionAssistantBlocks(input: {
  responseText: string;
  assistantBlocks?: unknown[];
  prompt?: string | null;
  selectedWorkload?: string | null;
}): { blocks: unknown[]; text: string } {
  const assistantBlocks = filterAssistantBlocksByIntent({
    blocks: Array.isArray(input.assistantBlocks)
      ? [...input.assistantBlocks]
      : [],
    prompt: input.prompt,
    selectedWorkload: input.selectedWorkload,
  });
  const normalizedBlocks = normalizeAssistantMessageBlocks({
    blocks: assistantBlocks,
  });

  const hasTableBlock = normalizedBlocks.some((b) => b.type === "table");
  const hasCodeBlock = normalizedBlocks.some((b) => b.type === "code");
  const hasDocumentBlock = normalizedBlocks.some(
    (b) => b.type === "document_block",
  );

  // Normalize line endings first — extractor sources are reconstructed from
  // LF-only lines, so `text.split(source)` would never match CRLF content
  // and the duplicate markdown would remain in chat (bug seen in prod).
  let text = String(input.responseText ?? "").replace(/\r\n?/g, "\n");
  const sourcesToStrip: string[] = [];

  // Extract markdown table if model didn't produce a typed table block.
  // The model sometimes emits more than one markdown table in a single reply
  // (e.g. a full data table followed by a truncated variant). Loop until no
  // further table shows up so none stays as raw markdown that would render
  // as a second, duplicate-looking table on the client.
  if (
    !hasTableBlock &&
    shouldPromoteMarkdownTableToWidget({
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    })
  ) {
    let scan = text;
    while (true) {
      const parsedTable = extractMarkdownTableBlock(scan);
      if (!parsedTable) break;
      assistantBlocks.push(parsedTable.block);
      sourcesToStrip.push(parsedTable.source);
      // Continue scanning after the extracted span so a second table on the
      // same page is picked up too, without re-matching the first one.
      const idx = scan.indexOf(parsedTable.source);
      if (idx < 0) break;
      scan = scan.slice(idx + parsedTable.source.length);
    }
  }

  // Extract code fences → syntax-highlighted code block for mobile
  if (!hasCodeBlock) {
    const parsedCode = extractMarkdownCodeBlock(text);
    if (parsedCode) {
      assistantBlocks.push(parsedCode.block);
      sourcesToStrip.push(parsedCode.source);
    }
  }

  // Extract structured headings → document_block (PDF preview + share on mobile)
  // Only when no other rich block is present to avoid double-rendering
  if (!hasDocumentBlock && !hasTableBlock) {
    const parsedDoc = extractMarkdownDocumentBlock(text);
    if (parsedDoc) {
      assistantBlocks.push(parsedDoc.block);
      sourcesToStrip.push(parsedDoc.source);
    }
  }

  // The model often emits a typed-block JSON (e.g. status:needs_desktop) at the
  // start of its turn, sometimes ALONE and sometimes followed by a prose reply.
  // Promote the JSON to a typed block and keep only the trailing prose as
  // visible text — otherwise the raw JSON leaks into chat as plain text.
  const leadingJson = extractLeadingJsonBlock(text);
  if (leadingJson) {
    const acceptLeadingBlock = shouldAcceptStructuredBlock({
      block: leadingJson.block,
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    });
    if (acceptLeadingBlock) {
      assistantBlocks.push(leadingJson.block);
      text = leadingJson.rest;
    } else {
      const fallback = structuredBlockToPlainFallback(leadingJson.block);
      text = [fallback, leadingJson.rest]
        .map((part) => part.trim())
        .filter(Boolean)
        .join("\n\n");
    }
  }

  // Strip every extracted span so the inline text doesn't duplicate the widget.
  for (const span of sourcesToStrip) {
    if (!span) continue;
    text = text.split(span).join("");
  }
  // Collapse leftover blank lines from the strips.
  text = stripDanglingStructuredJsonTail(
    text.replace(/\n{3,}/g, "\n\n").trim(),
  );

  const blocks = normalizeAssistantMessageBlocks({
    blocks: filterAssistantBlocksByIntent({
      blocks: assistantBlocks,
      prompt: input.prompt,
      selectedWorkload: input.selectedWorkload,
    }),
  });
  return {
    blocks,
    text,
  };
}

function summarizeStructuredAssistantBlocks(assistantBlocks: unknown[]) {
  const normalizedBlocks = normalizeAssistantMessageBlocks({
    blocks: assistantBlocks,
  }).filter((block) => block.type !== "text");
  if (normalizedBlocks.length === 0) {
    return null;
  }

  const firstBlock = normalizedBlocks[0];
  if (firstBlock.type === "document_block") {
    return firstBlock.title?.trim()
      ? `${firstBlock.title.trim()} hazır.`
      : "Belge hazır.";
  }
  if (firstBlock.type === "table") {
    return firstBlock.title?.trim()
      ? `${firstBlock.title.trim()} hazır.`
      : "Tablo hazır.";
  }
  if (firstBlock.type === "chart") {
    return firstBlock.title?.trim()
      ? `${firstBlock.title.trim()} hazır.`
      : "Grafik hazır.";
  }
  if (firstBlock.type === "file") {
    return firstBlock.fileName?.trim()
      ? `${firstBlock.fileName.trim()} hazır.`
      : "Dosya hazır.";
  }
  if (firstBlock.type === "web_search") {
    return "Web kaynaklari hazir.";
  }
  return "Yapilandirilmis cikti hazir.";
}

export function resolveVisibleAssistantResponse(input: {
  responseText: string;
  assistantBlocks?: unknown[];
  allowPublicProviderReferences?: boolean;
}) {
  const visibleTextSanitizerOptions = {
    allowPublicProviderReferences: input.allowPublicProviderReferences === true,
  };
  const normalizedBlocks = normalizeAssistantMessageBlocks({
    blocks: input.assistantBlocks,
  });
  const blockVisibleText = normalizedBlocks
    .filter(
      (
        block,
      ): block is Extract<
        (typeof normalizedBlocks)[number],
        { type: "text" }
      > => block.type === "text",
    )
    .map((block) => block.markdown.trim())
    .filter(Boolean)
    .join("\n\n");
  const visibleResponseText =
    sanitizeAssistantVisibleText(
      input.responseText,
      visibleTextSanitizerOptions,
    ) ||
    sanitizeAssistantVisibleText(blockVisibleText, visibleTextSanitizerOptions);
  if (visibleResponseText) {
    return visibleResponseText;
  }
  const hasStructuredBlocks = normalizedBlocks.some(
    (block) => block.type !== "text",
  );
  if (hasStructuredBlocks) {
    return "";
  }
  // Sanitize her şeyi süzse bile ham response'u fallback yap: stub yerine
  // kullanıcı modelin ürettiği ham metni görür. Aşırı-strict dump dedektörü
  // yüzünden düz cevaplar sürekli "temiz biçimde hazırlayamadım" oluyordu.
  return sanitizeAssistantVisibleText(input.responseText, {
    ...visibleTextSanitizerOptions,
    fallback: input.responseText ?? "",
  });
}

function resolveTaskRouteNeedsDesktop(
  routeDecision: CommandRouteDecision | null | undefined,
): boolean {
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
    selectedDeviceIgnored:
      Boolean(String(input.requestedTargetDeviceId ?? "").trim()) &&
      !needsDesktop,
    ...(input.routeDecision?.qualityGuard ? { qualityGuard: input.routeDecision.qualityGuard } : {}),
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

function extractRouteDecision(
  payload: Record<string, unknown>,
): CommandRouteDecision | null {
  const metadata = getPayloadMetadata(payload);
  const routingDecision = metadata.routeDecision ?? metadata.routingDecision;
  if (
    !routingDecision ||
    typeof routingDecision !== "object" ||
    Array.isArray(routingDecision)
  ) {
    return null;
  }

  const typedRoutingDecision = routingDecision as Record<string, unknown>;
  const taskRoute = readRecord(typedRoutingDecision.taskRoute);
  return {
    route:
      typeof typedRoutingDecision.route === "string"
        ? (typedRoutingDecision.route as CommandRouteDecision["route"])
        : "unavailable",
    taskRoute: taskRoute
      ? {
          target:
            typeof taskRoute.target === "string"
              ? (taskRoute.target as NonNullable<
                  CommandRouteDecision["taskRoute"]
                >["target"])
              : "server_brain",
          operationalRoute:
            taskRoute.operationalRoute === "desktop_runtime"
              ? "desktop_runtime"
              : "server_brain",
          executionPlan: Array.isArray(taskRoute.executionPlan)
            ? taskRoute.executionPlan
                .map((value: unknown) => String(value ?? "").trim())
                .filter(
                  (
                    value,
                  ): value is
                    "mobile_local" | "server_brain" | "desktop_runtime" =>
                    value === "mobile_local" ||
                    value === "server_brain" ||
                    value === "desktop_runtime",
                )
            : [],
          reason: typeof taskRoute.reason === "string" ? taskRoute.reason : "",
          needsDesktop: Boolean(taskRoute.needsDesktop),
          needsPrivateDesktopData: Boolean(taskRoute.needsPrivateDesktopData),
          needsUserApproval: Boolean(taskRoute.needsUserApproval),
          requiredCapabilities: Array.isArray(taskRoute.requiredCapabilities)
            ? taskRoute.requiredCapabilities
                .map((value: unknown) => String(value ?? "").trim())
                .filter(Boolean)
            : [],
        }
      : undefined,
    mode:
      typeof typedRoutingDecision.mode === "string"
        ? (typedRoutingDecision.mode as CommandRouteDecision["mode"])
        : "chat",
    capabilities: Array.isArray(typedRoutingDecision.capabilities)
      ? typedRoutingDecision.capabilities
          .map((value: unknown) => String(value ?? "").trim())
          .filter(Boolean)
      : [],
    privacyClass:
      typeof typedRoutingDecision.privacyClass === "string"
        ? (typedRoutingDecision.privacyClass as CommandRouteDecision["privacyClass"])
        : "public_text",
    requiresApproval: Boolean(typedRoutingDecision.requiresApproval),
    reason:
      typeof typedRoutingDecision.reason === "string"
        ? typedRoutingDecision.reason
        : "",
    userFacingMessage:
      typeof typedRoutingDecision.userFacingMessage === "string"
        ? typedRoutingDecision.userFacingMessage
        : undefined,
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
    shouldAskClarification: Boolean(
      typedRoutingDecision.shouldAskClarification,
    ),
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

export function isRemoteMcpRouteDecisionStale(
  routeDecision: CommandRouteDecision | null,
  effectiveRequestedCapabilities: string[],
): boolean {
  if (!effectiveRequestedCapabilities.includes("mcp_call_tool")) return false;
  const routedCapabilities = new Set([
    ...(routeDecision?.capabilities ?? []),
    ...(routeDecision?.taskRoute?.requiredCapabilities ?? []),
  ]);
  return !routedCapabilities.has("mcp_call_tool");
}

function capabilitiesIncludeQuantum(capabilities: string[]): boolean {
  return capabilities.some((capability) =>
    String(capability ?? "")
      .trim()
      .toLowerCase()
      .replace(/[\s_]+/g, ".")
      .startsWith("quantum."),
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

function readOptimizationNumber(record: Record<string, unknown> | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readOptimizationString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function buildQuantumDispatchOptimization(input: {
  brainProfile?: unknown;
  isDesktopRoute: boolean;
}) {
  if (!input.isDesktopRoute) {
    return null;
  }
  const profile = readRecord(input.brainProfile);
  const learning = readRecord(profile?.learning);
  const quantum = readRecord(profile?.quantum);
  const score =
    readOptimizationNumber(learning, "latestQuantumBenchmarkScore") ??
    readOptimizationNumber(quantum, "lastBenchmarkScore");
  const benchmarkSource =
    readOptimizationString(learning, "latestQuantumBenchmarkSource") ??
    readOptimizationString(quantum, "benchmarkSource");
  if (score === null || benchmarkSource !== "measured") {
    return null;
  }
  const classicalBaselineScore =
    readOptimizationNumber(learning, "latestQuantumClassicalBaselineScore") ??
    readOptimizationNumber(quantum, "classicalBaselineScore");
  const advantageScore =
    readOptimizationNumber(learning, "latestQuantumAdvantageScore") ??
    readOptimizationNumber(quantum, "advantageScore");
  const learnedAdmissionWeight =
    readOptimizationNumber(learning, "latestQuantumDispatchAdmissionWeight") ??
    readOptimizationNumber(quantum, "dispatchAdmissionWeight");
  const learnedBoostedStepCount =
    readOptimizationNumber(learning, "latestQuantumDispatchBoostedStepCount") ??
    readOptimizationNumber(quantum, "dispatchBoostedStepCount");
  const learnedDispatchQualified =
    learning?.latestQuantumDispatchFeedbackQualified === true ||
    quantum?.dispatchFeedbackQualified === true;
  const qualified =
    learning?.latestQuantumBenchmarkQualified === true ||
    quantum?.benchmarkQualified === true ||
    (advantageScore !== null && advantageScore > 0);
  const benchmarkWeight = Number(((advantageScore ?? 0.04) / 2).toFixed(4));
  const feedbackWeight =
    learnedDispatchQualified &&
    learnedAdmissionWeight !== null &&
    learnedAdmissionWeight > 0 &&
    learnedAdmissionWeight <= 0.15 &&
    (learnedBoostedStepCount ?? 0) > 0
      ? learnedAdmissionWeight
      : 0;
  const admissionWeight = qualified
    ? Math.max(0.02, Math.min(0.15, Number(Math.max(benchmarkWeight, feedbackWeight).toFixed(4))))
    : 0;

  return {
    strategy: "quantum_guided_dispatch_v1" as const,
    source: "backend_neural_readiness" as const,
    active: qualified,
    score: Number(score.toFixed(4)),
    classicalBaselineScore:
      classicalBaselineScore === null ? null : Number(classicalBaselineScore.toFixed(4)),
    advantageScore: advantageScore === null ? null : Number(advantageScore.toFixed(4)),
    qualified,
    benchmarkSource: "measured" as const,
    admissionWeight,
    metric: "dispatch_schedule_quality",
  };
}

export function buildQuantumResponsiveExecutionPolicy(input: {
  brainProfile?: unknown;
  isDesktopRoute: boolean;
}) {
  if (!input.isDesktopRoute) {
    return null;
  }
  const profile = readRecord(input.brainProfile);
  const learning = readRecord(profile?.learning);
  const quantum = readRecord(profile?.quantum);
  const livenessScore =
    readOptimizationNumber(learning, "latestQuantumDispatchLivenessScore") ??
    readOptimizationNumber(quantum, "dispatchLivenessScore");
  const qualified =
    learning?.latestQuantumDispatchLivenessQualified === true ||
    quantum?.dispatchLivenessQualified === true;
  if (livenessScore === null || livenessScore < 0 || livenessScore > 1) {
    return null;
  }
  const active = qualified && livenessScore < 0.96;
  const urgencyWeight = Number(((1 - livenessScore) / 3).toFixed(4));
  const boostWeight = active
    ? Math.max(0.02, Math.min(0.08, urgencyWeight))
    : 0;

  return {
    strategy: "quantum_liveness_guard_v1" as const,
    source: "backend_neural_readiness" as const,
    active,
    livenessScore: Number(livenessScore.toFixed(4)),
    qualified,
    benchmarkSource: "measured" as const,
    boostWeight,
    metric: "responsive_execution_liveness" as const,
  };
}

export function buildQuantumLivenessGuardPolicy(input: {
  brainProfile?: unknown;
  isDesktopRoute: boolean;
}) {
  if (!input.isDesktopRoute) {
    return null;
  }
  const profile = readRecord(input.brainProfile);
  const learning = readRecord(profile?.learning);
  const quantum = readRecord(profile?.quantum);
  const livenessScore =
    readOptimizationNumber(learning, "latestQuantumDispatchLivenessScore") ??
    readOptimizationNumber(quantum, "dispatchLivenessScore");
  const qualified =
    learning?.latestQuantumDispatchLivenessQualified === true ||
    quantum?.dispatchLivenessQualified === true;
  if (!qualified || livenessScore === null || livenessScore < 0 || livenessScore > 1) {
    return null;
  }
  const learnedTimeoutRiskRaw =
    readOptimizationString(learning, "latestQuantumLivenessGuardTimeoutRisk") ??
    readOptimizationString(quantum, "livenessGuardTimeoutRisk");
  const learnedTimeoutRisk =
    learnedTimeoutRiskRaw === "low" ||
    learnedTimeoutRiskRaw === "medium" ||
    learnedTimeoutRiskRaw === "high"
      ? learnedTimeoutRiskRaw
      : null;
  const learnedRepairAttemptCount =
    readOptimizationNumber(learning, "latestQuantumLivenessRepairAttemptCount") ??
    readOptimizationNumber(quantum, "livenessRepairAttemptCount");
  const scoreTimeoutRisk: "low" | "medium" | "high" =
    livenessScore < 0.72 ? "high" :
      livenessScore < 0.88 ? "medium" :
        "low";
  const timeoutRisk: "low" | "medium" | "high" =
    scoreTimeoutRisk === "high" || learnedTimeoutRisk === "high"
      ? "high"
      : scoreTimeoutRisk === "medium" || learnedTimeoutRisk === "medium" || (learnedRepairAttemptCount ?? 0) > 0
        ? "medium"
        : "low";
  const active = timeoutRisk !== "low";

  return {
    strategy: "quantum_replan_liveness_guard_v1" as const,
    source: "backend_neural_readiness" as const,
    active,
    timeoutRisk,
    maxReplans: active ? 3 : 2,
    earlyProgressCheckpoint: active,
    safeStopOnTimeout: true,
    metric: "responsive_execution_liveness" as const,
  };
}

function compactTextPreview(value: unknown, maxLength = 320): string | null {
  const normalized =
    typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
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
        .filter(
          (item): item is string =>
            typeof item === "string" && item.trim().length > 0,
        )
        .slice(0, 8)
    : [];
  const documentIds = readAttachmentDocumentIds(
    record.attachmentDocumentIds,
  ).slice(0, 8);

  const compact = {
    ...(typeof record.route === "string" ? { route: record.route } : {}),
    ...(typeof record.reason === "string" ? { reason: record.reason } : {}),
    ...(typeof record.workload === "string"
      ? { workload: record.workload }
      : {}),
    ...(typeof record.presentation === "string"
      ? { presentation: record.presentation }
      : {}),
    ...(typeof record.latencyMs === "number"
      ? { latencyMs: record.latencyMs }
      : {}),
    ...(typeof record.promptTokens === "number"
      ? { promptTokens: record.promptTokens }
      : {}),
    ...(typeof record.completionTokens === "number"
      ? { completionTokens: record.completionTokens }
      : {}),
    ...(typeof record.totalTokens === "number"
      ? { totalTokens: record.totalTokens }
      : {}),
    ...(typeof record.firstDeltaMs === "number"
      ? { firstDeltaMs: record.firstDeltaMs }
      : {}),
    ...(typeof record.fallbackUsed === "boolean"
      ? { fallbackUsed: record.fallbackUsed }
      : {}),
    ...(typeof record.groundingUsed === "boolean"
      ? { groundingUsed: record.groundingUsed }
      : {}),
    ...(typeof record.documentSourceCount === "number"
      ? { documentSourceCount: record.documentSourceCount }
      : {}),
    ...(typeof record.webSourceCount === "number"
      ? { webSourceCount: record.webSourceCount }
      : {}),
    ...(typeof record.artifactCount === "number"
      ? { artifactCount: record.artifactCount }
      : {}),
    ...(documentIds.length > 0 ? { attachmentDocumentIds: documentIds } : {}),
    ...(artifactIds.length > 0 ? { artifactIds } : {}),
  };

  return Object.keys(compact).length > 0 ? compact : null;
}

function buildArtifactPreviewPayload(
  artifact: PersistableArtifactInput,
): Record<string, unknown> | null {
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
    userId: string;
    slot: "payload" | "result" | "approval_request";
    scope: "task_payload" | "task_result" | "task_approval_request";
    value: unknown;
  },
) {
  return app.services?.blobs?.storeJson({
    ownerType: "task",
    ownerId: input.taskId,
    userId: input.userId,
    slot: input.slot,
    scope: input.scope,
    value: input.value,
  });
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function resolveImageGenerationFallbackText(
  metadata: Record<string, unknown>,
): string {
  const reason = typeof metadata.imageGenerationBlockedReason === "string"
    ? metadata.imageGenerationBlockedReason
    : "";
  if (reason === "image_generation_limit_reached") {
    return "Bu ayki görsel üretim hakkın doldu. Plan limitin yenilendiğinde tekrar görsel üretebilirsin.";
  }
  return "Görsel üretim şu anda tamamlanamadı. Lütfen biraz sonra tekrar dene.";
}

function readRenderRecipeFromTask(
  value: unknown,
): Record<string, unknown> | null {
  const taskRecord = readRecord(value);
  const renderRecipe = readRecord(taskRecord?.renderRecipe);
  return renderRecipe ?? null;
}

function extractUnderstandingEnvelopeFromMetadata(
  metadata: Record<string, unknown>,
) {
  const understanding = readRecord(metadata.understanding);
  const parsed = understandingEnvelopeSchema.safeParse(understanding?.envelope);
  return parsed.success ? parsed.data : null;
}

function readSafeString(
  record: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim()
    ? value.trim().slice(0, 160)
    : null;
}

function readSafeNumber(
  record: Record<string, unknown> | null,
  key: string,
): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function extractRuntimeQuantumBenchmarkAttestation(
  result: Record<string, unknown> | undefined,
): VerifiedQuantumBenchmark | null {
  const resultRecord = readRecord(result);
  if (!resultRecord) {
    return null;
  }

  const structuredResult = readRecord(resultRecord.structuredResult);
  const executionTrace = readRecord(resultRecord.executionTrace);
  const schedulerTrace = readRecord(executionTrace?.scheduler);
  const candidates = [
    readRecord(resultRecord.quantumBenchmarkAttestation),
    readRecord(resultRecord.quantumOptimization),
    structuredResult,
    readRecord(structuredResult?.quantumBenchmarkAttestation),
    readRecord(schedulerTrace?.quantumOptimization),
  ];

  for (const candidate of candidates) {
    if (!candidate) {
      continue;
    }
    const verified = readVerifiedQuantumBenchmark(
      candidate.quantumBenchmarkAttestation ? candidate : { quantumBenchmarkAttestation: candidate },
    );
    if (verified) {
      return verified;
    }
  }

  return null;
}

function readSafeStringArray(value: unknown, maxItems = 16): string[] {
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "string" ? item.trim().slice(0, 120) : ""))
        .filter(Boolean)
        .slice(0, maxItems)
    : [];
}

function deriveQuantumDispatchPolicyOutcome(input: {
  backendActive: boolean;
  boostedStepCount: number;
  hasBenchmark: boolean;
}) {
  if (input.backendActive && input.boostedStepCount > 0) {
    return "backend_active_boosted" as const;
  }
  if (input.backendActive) {
    return "backend_active_no_boost" as const;
  }
  if (input.boostedStepCount > 0) {
    return "runtime_observed_without_backend" as const;
  }
  return input.hasBenchmark ? "benchmark_only" as const : "no_signal" as const;
}

function deriveQuantumResponsivePolicyOutcome(input: {
  backendActive: boolean;
  responsiveBoostedStepCount: number;
  hasLivenessBenchmark: boolean;
}) {
  if (input.backendActive && input.responsiveBoostedStepCount > 0) {
    return "backend_active_responsive_boosted" as const;
  }
  if (input.backendActive) {
    return "backend_active_no_responsive_boost" as const;
  }
  if (input.responsiveBoostedStepCount > 0) {
    return "runtime_responsive_observed_without_backend" as const;
  }
  return input.hasLivenessBenchmark ? "liveness_benchmark_only" as const : "no_signal" as const;
}

export function extractRuntimeDispatchPolicyFeedback(
  result: Record<string, unknown> | undefined,
) {
  const resultRecord = readRecord(result);
  const executionTrace = readRecord(resultRecord?.executionTrace);
  const scheduler = readRecord(executionTrace?.scheduler);
  if (!scheduler) {
    const progressLiveness = readRecord(executionTrace?.quantumLiveness);
    if (
      readSafeString(progressLiveness, "strategy") !== "quantum_runtime_liveness_snapshot_v1" ||
      readSafeString(progressLiveness, "source") !== "desktop_runtime_progress"
    ) {
      return null;
    }
    const livenessScore = readSafeNumber(progressLiveness, "score");
    const responsiveBoostedStepIds = readSafeStringArray(
      progressLiveness?.responsiveBoostedStepIds,
    );
    const responsiveBoostedStepCount =
      readSafeNumber(progressLiveness, "responsiveBoostedStepCount") ??
      responsiveBoostedStepIds.length;
    const livenessGuardTimeoutRisk = readSafeString(
      progressLiveness,
      "livenessGuardTimeoutRisk",
    );
    return {
      policy: "quantum_guided_dispatch_v1",
      source: "desktop_runtime_progress",
      backendStrategy: null,
      backendActive: false,
      admissionWeight: null,
      policyOutcome: "no_signal",
      boostedStepIds: [],
      boostedStepCount: 0,
      responsivePolicyOutcome: deriveQuantumResponsivePolicyOutcome({
        backendActive: progressLiveness?.backendResponsiveActive === true,
        responsiveBoostedStepCount,
        hasLivenessBenchmark: livenessScore !== null,
      }),
      responsiveBoostedStepIds,
      responsiveBoostedStepCount,
      orderedStepCount: 0,
      orderedStepIds: [],
      quantumBenchmarkScore: null,
      quantumClassicalBaselineScore: null,
      quantumAdvantageScore: null,
      quantumBenchmarkQualified: false,
      quantumBenchmarkMetric: null,
      quantumBenchmarkRunId: null,
      quantumBenchmarkDatasetFingerprint: null,
      livenessScore,
      livenessClassicalBaselineScore: null,
      livenessAdvantageScore: null,
      livenessQualified: progressLiveness?.qualified === true,
      livenessRunId: null,
      parallelReadCandidateCount: null,
      blockedStepCount: null,
      writeStepCount: null,
      deadlinePressureStepCount: null,
      livenessGuardActive: progressLiveness?.livenessGuardActive === true,
      livenessGuardTimeoutRisk:
        livenessGuardTimeoutRisk === "low" ||
        livenessGuardTimeoutRisk === "medium" ||
        livenessGuardTimeoutRisk === "high"
          ? livenessGuardTimeoutRisk
          : null,
      livenessGuardEffectiveMaxReplans: readSafeNumber(
        progressLiveness,
        "livenessGuardEffectiveMaxReplans",
      ),
      livenessGuardMaxReplans: null,
      repairAttemptCount: readSafeNumber(progressLiveness, "repairAttemptCount"),
    };
  }
  const backendOptimization = readRecord(scheduler.backendDispatchOptimization);
  const benchmark =
    readVerifiedQuantumBenchmark(readRecord(scheduler.quantumOptimization)) ??
    extractRuntimeQuantumBenchmarkAttestation(result);
  const livenessRecord = readRecord(scheduler.quantumLivenessOptimization);
  const livenessGuard = readRecord(executionTrace?.livenessGuard);
  const backendLivenessGuard = readRecord(scheduler.backendLivenessGuard);
  const repair = readRecord(executionTrace?.repair);
  const livenessBenchmark = readVerifiedQuantumBenchmark(
    livenessRecord ? { quantumBenchmarkAttestation: livenessRecord } : null,
  );
  const boostedStepIds = readSafeStringArray(scheduler.quantumBoostedStepIds);
  const responsiveBoostedStepIds = readSafeStringArray(scheduler.responsiveBoostedStepIds);
  const orderedStepIds = readSafeStringArray(scheduler.orderedStepIds);
  const backendActive = backendOptimization?.active === true;
  const backendResponsiveExecution = readRecord(scheduler.backendResponsiveExecution);
  const backendResponsiveActive = backendResponsiveExecution?.active === true;
  const backendStrategy = readSafeString(backendOptimization, "strategy");
  const admissionWeight = readSafeNumber(backendOptimization, "admissionWeight");

  if (!benchmark && boostedStepIds.length === 0 && !backendActive) {
    return null;
  }

  return {
    policy: "quantum_guided_dispatch_v1",
    source: "desktop_runtime_scheduler",
    backendStrategy: backendStrategy ?? null,
    backendActive,
    admissionWeight,
    policyOutcome: deriveQuantumDispatchPolicyOutcome({
      backendActive,
      boostedStepCount: boostedStepIds.length,
      hasBenchmark: Boolean(benchmark),
    }),
    boostedStepIds,
    boostedStepCount: boostedStepIds.length,
    responsivePolicyOutcome: deriveQuantumResponsivePolicyOutcome({
      backendActive: backendResponsiveActive,
      responsiveBoostedStepCount: responsiveBoostedStepIds.length,
      hasLivenessBenchmark: livenessBenchmark?.metric === "responsive_execution_liveness",
    }),
    responsiveBoostedStepIds,
    responsiveBoostedStepCount: responsiveBoostedStepIds.length,
    orderedStepCount: orderedStepIds.length,
    orderedStepIds,
    quantumBenchmarkScore: benchmark?.score ?? null,
    quantumClassicalBaselineScore: benchmark?.classicalBaselineScore ?? null,
    quantumAdvantageScore: benchmark?.advantageScore ?? null,
    quantumBenchmarkQualified: benchmark?.qualified ?? false,
    quantumBenchmarkMetric: benchmark?.metric ?? null,
    quantumBenchmarkRunId: benchmark?.runId ?? null,
    quantumBenchmarkDatasetFingerprint: benchmark?.datasetFingerprint ?? null,
    livenessScore:
      livenessBenchmark?.metric === "responsive_execution_liveness"
        ? livenessBenchmark.score
        : null,
    livenessClassicalBaselineScore:
      livenessBenchmark?.metric === "responsive_execution_liveness"
        ? livenessBenchmark.classicalBaselineScore
        : null,
    livenessAdvantageScore:
      livenessBenchmark?.metric === "responsive_execution_liveness"
        ? livenessBenchmark.advantageScore
        : null,
    livenessQualified:
      livenessBenchmark?.metric === "responsive_execution_liveness"
        ? livenessBenchmark.qualified
        : false,
    livenessRunId:
      livenessBenchmark?.metric === "responsive_execution_liveness"
        ? livenessBenchmark.runId
        : null,
    parallelReadCandidateCount: readSafeNumber(livenessRecord, "parallelReadCandidateCount"),
    blockedStepCount: readSafeNumber(livenessRecord, "blockedStepCount"),
    writeStepCount: readSafeNumber(livenessRecord, "writeStepCount"),
    deadlinePressureStepCount: readSafeNumber(livenessRecord, "deadlinePressureStepCount"),
    livenessGuardActive: livenessGuard?.active === true,
    livenessGuardTimeoutRisk:
      readSafeString(livenessGuard, "timeoutRisk") ??
      readSafeString(backendLivenessGuard, "timeoutRisk"),
    livenessGuardEffectiveMaxReplans: readSafeNumber(livenessGuard, "effectiveMaxReplans"),
    livenessGuardMaxReplans:
      readSafeNumber(livenessGuard, "maxReplans") ??
      readSafeNumber(backendLivenessGuard, "maxReplans"),
    repairAttemptCount: readSafeNumber(repair, "repairAttempts"),
  };
}

export function computeRuntimeDispatchPolicyFeedbackConfidence(
  signal: ReturnType<typeof extractRuntimeDispatchPolicyFeedback>,
): number {
  if (!signal) {
    return 0;
  }
  let confidence = 68;
  if (signal.quantumBenchmarkQualified) {
    confidence += 8;
  }
  if (signal.policyOutcome === "backend_active_boosted") {
    confidence += 8;
  } else if (signal.policyOutcome === "backend_active_no_boost") {
    confidence -= 6;
  } else if (signal.policyOutcome === "runtime_observed_without_backend") {
    confidence -= 2;
  }
  if (signal.responsivePolicyOutcome === "backend_active_responsive_boosted") {
    confidence += 5;
  } else if (signal.responsivePolicyOutcome === "backend_active_no_responsive_boost") {
    confidence -= 3;
  }
  if (signal.livenessGuardActive) {
    confidence += 2;
  }
  const repairAttempts = signal.repairAttemptCount ?? 0;
  if (repairAttempts > 0) {
    confidence -= Math.min(8, repairAttempts * 2);
  }
  if (signal.source === "desktop_runtime_progress") {
    confidence = Math.min(confidence, 76);
  }
  return Math.max(50, Math.min(90, confidence));
}

async function resolveTaskAttachmentContext(
  app: FastifyInstance,
  payload: Record<string, unknown>,
  prompt: string,
  ephemeralVision?: EphemeralVisionCarrier,
) {
  return resolveAttachmentContextWithCache(app.services.reliability.store, {
    prompt,
    metadata: getPayloadMetadata(payload),
    sessionAttachmentCandidates: extractAttachmentCandidatesFromBrainContext(
      readRecord(payload.brainContext),
    ),
    hasEphemeralVision:
      app.config?.ELYAN_CLOUD_VISION_ENABLED === true &&
      countDistinctEphemeralImages(ephemeralVision) > 0,
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

  const attachmentItems = Array.isArray(carrier.attachments)
    ? carrier.attachments
    : [];
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
    const mimeType =
      typeof record.mimeType === "string"
        ? record.mimeType.trim().toLowerCase()
        : "";
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

function extractQuantumLearningSignal(
  result: Record<string, unknown> | undefined,
) {
  const benchmark = extractRuntimeQuantumBenchmarkAttestation(result);
  if (benchmark) {
    return {
      mode: "hybrid",
      solver: benchmark.backend,
      problemClass:
        benchmark.metric === "dispatch_schedule_quality"
          ? "dispatch_scheduling"
          : "optimization",
      benchmarkStatus: "measured",
      fallbackReason: null,
      lastBenchmarkScore: benchmark.score,
      classicalBaselineScore: benchmark.classicalBaselineScore,
      benchmarkSource: benchmark.source,
      advantageScore: benchmark.advantageScore,
      benchmarkQualified: benchmark.qualified,
      benchmarkMetric: benchmark.metric,
      benchmarkBackend: benchmark.backend,
      benchmarkRunId: benchmark.runId,
      benchmarkSampleCount: benchmark.sampleCount,
      benchmarkDatasetFingerprint: benchmark.datasetFingerprint,
      benchmarkMeasuredAt: benchmark.measuredAt,
      quantumBenchmarkVersion: benchmark.version,
      quantumBenchmarkProducer: benchmark.producer,
      quantumBenchmarkRunId: benchmark.runId,
      quantumBenchmarkMetric: benchmark.metric,
      quantumBenchmarkDatasetFingerprint: benchmark.datasetFingerprint,
      quantumBenchmarkSampleCount: benchmark.sampleCount,
      quantumBenchmarkScore: benchmark.score,
      quantumBenchmarkSource: benchmark.source,
      quantumClassicalBaselineScore: benchmark.classicalBaselineScore,
      quantumBenchmarkMeasuredAt: benchmark.measuredAt,
      quantumBenchmarkBackend: benchmark.backend,
      quantumAdvantageScore: benchmark.advantageScore,
      quantumBenchmarkQualified: benchmark.qualified,
      quantumBenchmarkAttestation: benchmark,
    };
  }

  const quantum =
    readRecord(result?.quantum) ??
    readRecord(readRecord(result?.metadata)?.quantum) ??
    readRecord(result);
  const mode = readSafeString(quantum, "mode");
  const solver = readSafeString(quantum, "solver");
  const problemClass = readSafeString(quantum, "problemClass");
  const benchmarkStatus = readSafeString(quantum, "benchmarkStatus");
  const fallbackReason = readSafeString(quantum, "fallbackReason");
  const lastBenchmarkScore =
    readSafeNumber(quantum, "lastBenchmarkScore") ??
    readSafeNumber(quantum, "benchmarkScore") ??
    readSafeNumber(quantum, "quantumBenchmarkScore");

  if (
    !mode &&
    !solver &&
    !problemClass &&
    benchmarkStatus !== "completed" &&
    lastBenchmarkScore === null
  ) {
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

async function recordRuntimeDispatchPolicyFeedback(
  app: FastifyInstance,
  input: {
    task: typeof tasks.$inferSelect;
    result?: Record<string, unknown>;
  },
) {
  const signal = extractRuntimeDispatchPolicyFeedback(input.result);
  if (!signal) {
    return;
  }
  const confidence = computeRuntimeDispatchPolicyFeedbackConfidence(signal);

  await app.db.insert(learningEvents).values({
    userId: input.task.userId,
    accountId: input.task.userId,
    taskId: input.task.id,
    type: "routing",
    key: "dispatch_policy_feedback",
    value: JSON.stringify(signal),
    confidence,
    scope: "user",
    source: "runtime",
    privacyLevel: "safe",
    metadata: {
      signal: "runtime_dispatch_policy_feedback",
      route: "desktop_runtime",
      policy: signal.policy,
      policyOutcome: signal.policyOutcome,
      responsivePolicyOutcome: signal.responsivePolicyOutcome,
      boostedStepCount: signal.boostedStepCount,
      responsiveBoostedStepCount: signal.responsiveBoostedStepCount,
      livenessGuardActive: signal.livenessGuardActive,
      repairAttemptCount: signal.repairAttemptCount,
      confidenceStrategy: "runtime_quantum_policy_feedback_v1",
    },
  });
}

async function insertTaskEvent(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId?: string;
    status: TaskStatus;
    message?: string;
    payload?: Record<string, unknown>;
  },
) {
  const eventId = randomUUID();
  const publicPayload = input.payload
    ? sanitizePublicTaskEventPayload(input.payload)
    : null;
  const publicPayloadRecord = readRecord(publicPayload);
  const payloadBlob = input.payload
    ? await app.services?.blobs?.storeJson({
        ownerType: "task_event",
        ownerId: eventId,
        userId: input.userId,
        slot: "payload",
        scope: "task_event_payload",
        value: publicPayloadRecord ?? publicPayload,
      })
    : null;
  await app.db.insert(taskEvents).values({
    id: eventId,
    taskId: input.taskId,
    status: input.status,
    message: input.message,
    payload: compactJsonEnvelope(publicPayloadRecord),
    payloadBlobId: payloadBlob?.blobId ?? null,
  });
}

function isTaskDispatchLeaseActive(
  task: typeof tasks.$inferSelect,
  now = new Date(),
): boolean {
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

async function persistArtifacts(
  app: FastifyInstance,
  taskId: string,
  userId: string,
  items: PersistableArtifactInput[],
) {
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
        userId,
        slot: "body",
        scope: "artifact_body",
        value: item.binaryBody,
        contentType: item.contentType,
      });
      if (!bodyBlob?.blobId) {
        app.log.warn(
          { taskId, artifactId, contentType: item.contentType },
          "artifact binary body could not be persisted",
        );
        continue;
      }
    } else if (item.payload || item.textContent) {
      bodyBlob = await app.services?.blobs?.storeJson({
        ownerType: "artifact",
        ownerId: artifactId,
        userId,
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
        (typeof previewPayload?.previewText === "string"
          ? previewPayload.previewText
          : undefined),
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

function buildArtifactOutputArtifact(
  taskId: string,
  output: ArtifactOutput,
): ArtifactInput {
  return {
    kind: "structured_output",
    name: `artifact-${output.type}.json`,
    contentType: "application/json",
    textContent: JSON.stringify(output, null, 2),
    payload: output as unknown as Record<string, unknown>,
    metadata: normalizeLocalDerivedMetadata({
      taskId,
      artifact_type: output.type,
      artifact_id: output.artifactId,
      validation_ok: output.validation.ok,
      error_codes: output.validation.errors
        .map((error) => error.code)
        .slice(0, 16),
      structured_output: true,
    }),
  };
}

function compactSessionArtifactSnapshot(input: {
  prompt: string;
  artifact: ReturnType<typeof shapeTaskArtifact>;
}): Record<string, unknown> | null {
  const artifact = input.artifact;
  const metadata = readRecord(artifact.metadata);
  const payload = readRecord(artifact.payload);
  const artifactType = String(
    metadata?.artifact_type ??
      payload?.type ??
      artifact.viewerHint ??
      artifact.contentFamily ??
      artifact.kind ??
      "",
  )
    .trim()
    .toLowerCase();
  const contentFamily = String(artifact.contentFamily ?? "").toLowerCase();
  if (!artifactType && !contentFamily) return null;
  return {
    id: artifact.id,
    taskId: artifact.taskId,
    type: artifactType || contentFamily,
    artifactType: artifactType || contentFamily,
    contentFamily,
    name: artifact.name,
    contentType: artifact.contentType,
    viewerHint: artifact.viewerHint,
    prompt: compactTextPreview(input.prompt, 900),
    previewText: compactTextPreview(artifact.previewText, 500),
    revisedPrompt: compactTextPreview(
      metadata?.revisedPrompt ?? payload?.revisedPrompt,
      900,
    ),
    createdAt:
      artifact.createdAt instanceof Date
        ? artifact.createdAt.toISOString()
        : new Date().toISOString(),
  };
}

async function persistSessionArtifactMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string | null | undefined;
    prompt: string;
    artifacts: Array<ReturnType<typeof shapeTaskArtifact>>;
  },
) {
  const sessionId = String(input.sessionId ?? "").trim();
  if (!sessionId || input.artifacts.length === 0) return;
  const snapshots = input.artifacts
    .map((artifact) =>
      compactSessionArtifactSnapshot({ prompt: input.prompt, artifact }),
    )
    .filter((item): item is Record<string, unknown> => item != null)
    .slice(0, 4);
  if (snapshots.length === 0) return;
  await app.db
    .update(chatSessions)
    .set({
      metadata: sql`
        jsonb_set(
          coalesce(${chatSessions.metadata}, '{}'::jsonb),
          '{sessionArtifacts}',
          (
            select jsonb_agg(value)
            from (
              select value
              from (
                select distinct on (value->>'id') value, ord
                from jsonb_array_elements(
                  ${JSON.stringify(snapshots)}::jsonb ||
                  coalesce(${chatSessions.metadata}->'sessionArtifacts', '[]'::jsonb)
                ) with ordinality as items(value, ord)
                order by value->>'id', ord
              ) deduped
              order by ord
              limit 8
            ) ordered
          ),
          true
        )
      `,
      updatedAt: new Date(),
    })
    .where(and(eq(chatSessions.id, sessionId), eq(chatSessions.userId, input.userId)));
}

async function readSessionArtifactMemory(
  app: FastifyInstance,
  input: { userId: string; sessionId: string | null | undefined },
): Promise<Record<string, unknown>[]> {
  const sessionId = String(input.sessionId ?? "").trim();
  if (!sessionId) return [];
  const rows = await app.db
    .select({ metadata: chatSessions.metadata })
    .from(chatSessions)
    .where(and(eq(chatSessions.id, sessionId), eq(chatSessions.userId, input.userId)))
    .limit(1);
  const metadata = readRecord(rows[0]?.metadata);
  const sessionArtifacts = Array.isArray(metadata?.sessionArtifacts)
    ? metadata.sessionArtifacts
    : [];
  return sessionArtifacts
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null)
    .slice(0, 8);
}

async function getTaskForUser(
  app: FastifyInstance,
  taskId: string,
  userId: string,
) {
  const rows = await app.db
    .select()
    .from(tasks)
    .where(and(eq(tasks.id, taskId), eq(tasks.userId, userId)))
    .limit(1);
  const task = rows[0];

  if (!task) {
    throw notFound("Task not found");
  }

  return task;
}

async function getTaskForRuntime(
  app: FastifyInstance,
  taskId: string,
  auth: RuntimeAuthTokenPayload,
) {
  const rows = await app.db
    .select()
    .from(tasks)
    .where(
      and(
        eq(tasks.id, taskId),
        eq(tasks.userId, auth.sub),
        eq(tasks.targetDeviceId, auth.deviceId),
      ),
    )
    .limit(1);

  const task = rows[0];

  if (!task) {
    throw notFound("Task not found for this runtime");
  }

  return task;
}

export async function getTaskById(app: FastifyInstance, taskId: string) {
  const rows = await app.db
    .select()
    .from(tasks)
    .where(eq(tasks.id, taskId))
    .limit(1);
  return rows[0] ?? null;
}

async function hydrateTaskJsonValue<T>(
  app: FastifyInstance,
  inlineValue: T,
  blobId?: string | null,
  owner?: {
    userId: string;
    ownerType: "task" | "task_event";
    ownerId: string;
  },
): Promise<T> {
  if (!blobId) {
    return inlineValue;
  }

  const hydrated = owner
    ? await app.services?.blobs?.hydrateJsonForOwner<T>({
        blobId,
        userId: owner.userId,
        ownerType: owner.ownerType,
        ownerId: owner.ownerId,
      })
    : await app.services?.blobs?.hydrateJson<T>(blobId);

  return (hydrated ?? inlineValue) as T;
}

async function shapePublicArtifactRecord(
  app: FastifyInstance,
  artifact: typeof artifacts.$inferSelect,
  userId?: string,
) {
  const blobDownloadUrl = artifact.bodyBlobId
    ? userId
      ? await app.services?.blobs?.createDownloadUrlForOwner({
          blobId: artifact.bodyBlobId,
          userId,
          ownerType: "artifact",
          ownerId: artifact.id,
          fileName: artifact.name,
          contentType: artifact.contentType,
        })
      : await app.services?.blobs?.createDownloadUrl({
          blobId: artifact.bodyBlobId,
          fileName: artifact.name,
          contentType: artifact.contentType,
        })
    : null;
  const downloadUrl =
    blobDownloadUrl ??
    (artifact.bodyBlobId && userId
      ? createSignedArtifactRawContentUrl(app, artifact, userId)
      : null);

  return shapeTaskArtifact({
    ...artifact,
    payload: sanitizePublicInferenceValue(artifact.payload ?? null),
    metadata: sanitizePublicInferenceValue(artifact.metadata ?? null),
    downloadUrl,
  });
}

function artifactDownloadSecret(app: FastifyInstance): string {
  return String(
    app.config.BLOB_HMAC_SECRET || app.config.JWT_SECRET || "",
  ).trim();
}

function base64UrlEncode(value: string): string {
  return Buffer.from(value, "utf8").toString("base64url");
}

function base64UrlDecode(value: string): string | null {
  try {
    return Buffer.from(value, "base64url").toString("utf8");
  } catch {
    return null;
  }
}

function signArtifactToken(secret: string, payload: string): string {
  return createHmac("sha256", secret).update(payload).digest("base64url");
}

function safeEqualToken(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  if (left.length !== right.length) {
    return false;
  }
  return timingSafeEqual(left, right);
}

function createSignedArtifactRawContentUrl(
  app: FastifyInstance,
  artifact: typeof artifacts.$inferSelect,
  userId: string,
): string | null {
  const secret = artifactDownloadSecret(app);
  if (secret.length < 32) {
    return null;
  }
  const exp =
    Math.floor(Date.now() / 1000) +
    app.config.BLOB_STORAGE_SIGNED_URL_TTL_SECONDS;
  const payload = base64UrlEncode(
    JSON.stringify({
      taskId: artifact.taskId,
      artifactId: artifact.id,
      userId,
      exp,
    }),
  );
  const sig = signArtifactToken(secret, payload);
  const baseUrl = String(app.config.APP_BASE_URL || "").replace(/\/+$/, "");
  if (!baseUrl) {
    return null;
  }
  return `${baseUrl}/v1/tasks/${artifact.taskId}/artifacts/${artifact.id}/content/raw?token=${payload}.${sig}`;
}

function verifyArtifactRawContentToken(
  app: FastifyInstance,
  token: string | null | undefined,
  taskId: string,
  artifactId: string,
): { userId: string } | null {
  const [payload, sig, extra] = String(token ?? "").split(".");
  if (!payload || !sig || extra !== undefined) {
    return null;
  }
  const secret = artifactDownloadSecret(app);
  if (secret.length < 32) {
    return null;
  }
  if (!safeEqualToken(sig, signArtifactToken(secret, payload))) {
    return null;
  }
  const decoded = base64UrlDecode(payload);
  if (!decoded) {
    return null;
  }
  let record: Record<string, unknown> | null = null;
  try {
    record = readRecord(JSON.parse(decoded));
  } catch {
    return null;
  }
  const exp = typeof record?.exp === "number" ? record.exp : 0;
  if (
    record?.taskId !== taskId ||
    record?.artifactId !== artifactId ||
    typeof record?.userId !== "string" ||
    exp < Math.floor(Date.now() / 1000)
  ) {
    return null;
  }
  return { userId: record.userId };
}

function buildGeneratedImageArtifactBlocks(
  shapedArtifacts: Array<ReturnType<typeof shapeTaskArtifact>>,
): AssistantMessageBlock[] {
  return shapedArtifacts
    .filter((artifact) => {
      const contentType = String(artifact.contentType ?? "").toLowerCase();
      const viewerHint = String(artifact.viewerHint ?? "").toLowerCase();
      const family = String(artifact.contentFamily ?? "").toLowerCase();
      return (
        viewerHint === "image" ||
        family === "image" ||
        contentType.startsWith("image/")
      );
    })
    .map((artifact) => {
      const url =
        typeof artifact.downloadUrl === "string" && artifact.downloadUrl.trim()
          ? artifact.downloadUrl.trim()
          : "";
      return {
        type: "artifact",
        artifactType: "image",
        artifactId: artifact.id,
        title: "Görsel",
        url,
        mime: artifact.contentType,
        viewerHint: "image",
        contentFamily: "image",
        loadStrategy: "remote_url",
        visibility: "user_visible",
        stableBlockId: `artifact_image_${artifact.id}`,
        cacheDigest: `artifact_image_${artifact.id}`,
        renderHints: {
          sectionRole: "image_result",
          density: "full",
          generated: true,
        },
        payload: sanitizePublicInferenceValue(artifact.payload ?? null),
        metadata: {
          sourceType: "task_artifact",
          contentFamily: "image",
          viewerHint: "image",
          mimeType: artifact.contentType,
        },
      };
    })
    .filter((block) => block.url);
}

async function getTaskArtifactRecordForUser(
  app: FastifyInstance,
  taskId: string,
  artifactId: string,
  userId: string,
) {
  await getTaskForUser(app, taskId, userId);
  const rows = await app.db
    .select()
    .from(artifacts)
    .where(and(eq(artifacts.id, artifactId), eq(artifacts.taskId, taskId)))
    .limit(1);
  const artifact = rows[0];
  if (!artifact) {
    throw notFound("Artifact not found");
  }
  return artifact;
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
    .where(
      and(
        eq(tasks.userId, input.userId),
        eq(tasks.idempotencyKey, input.idempotencyKey),
      ),
    )
    .limit(1);

  const existingTask = rows[0];
  return resolveIdempotentTaskMatch(existingTask, input);
}

async function getActiveRuntimeConnection(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
) {
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

function isRuntimeConnectionFresh(
  connection: RuntimeConnectionSnapshot | null,
  now = new Date(),
) {
  if (
    !connection ||
    connection.disconnectedAt ||
    connection.status === "offline"
  ) {
    return false;
  }

  return (
    now.getTime() - connection.lastHeartbeatAt.getTime() <=
    RUNTIME_CONNECTION_STALE_AFTER_MS
  );
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
    runtimeConnectionId:
      input.runtimeConnectionId ?? input.task.runtimeConnectionId ?? null,
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

  const dispatched = app.services.realtimeHub.sendToRuntime(
    input.task.targetDeviceId,
    buildRuntimeTaskDispatchEnvelope(leaseResult.task, lease),
  );

  return {
    dispatched,
    task: leaseResult.task,
    lease,
    reused: leaseResult.reused,
  } as const;
}

export function buildRuntimeTaskDispatchEnvelope(
  task: typeof tasks.$inferSelect,
  lease: { leaseId: string; expiresAt: string | null } | null = null,
) {
  return {
    type: "task.dispatch" as const,
    // Runtime execution needs the private task payload/work order.  The
    // public feed shape intentionally omits it and must never be reused for
    // this authenticated desktop channel.
    task,
    ...(lease
      ? {
          leaseId: lease.leaseId,
          leaseExpiresAt: lease.expiresAt,
        }
      : {}),
  };
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
        runtimeConnectionId:
          input.runtimeConnectionId ?? task.runtimeConnectionId ?? null,
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
    userId: updatedTask.userId,
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

  if (
    !ownedTask.dispatchLeaseId ||
    ownedTask.dispatchLeaseId !== input.leaseId
  ) {
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
    userId: updatedTask.userId,
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

  if (
    !task.runtimeConnectionId ||
    task.runtimeConnectionId === activeConnection.id
  ) {
    if (task.runtimeConnectionId === activeConnection.id) {
      return task;
    }

    const rows = await app.db
      .update(tasks)
      .set(
        buildTaskRuntimeOwnershipUpdate({
          runtimeConnectionId: activeConnection.id,
        }),
      )
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
    .set(
      buildTaskRuntimeOwnershipUpdate({
        runtimeConnectionId: activeConnection.id,
      }),
    )
    .where(eq(tasks.id, task.id))
    .returning();

  return (
    reboundRows[0] ?? { ...task, runtimeConnectionId: activeConnection.id }
  );
}

function shouldSkipDuplicateRuntimeTerminalUpdate(
  task: Pick<typeof tasks.$inferSelect, "status">,
  nextStatus: TaskStatus,
): boolean {
  return isTerminalTaskStatus(task.status) && task.status === nextStatus;
}

async function publishTaskEvent(
  app: FastifyInstance,
  task: typeof tasks.$inferSelect,
  topic: string,
  payload: unknown,
): Promise<void> {
  await app.services.eventBus.publish({
    topic,
    userId: task.userId,
    deviceId: task.targetDeviceId,
    taskId: task.id,
    payload: sanitizePublicTaskEventPayload(payload),
  });
}

function staleRuntimeFailureForTarget(
  target: Awaited<ReturnType<typeof getUserDevice>> | null,
) {
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

function isSharedBrainChatTask(
  task: Pick<typeof tasks.$inferSelect, "payload" | "runtimeConnectionId">,
): boolean {
  const payload =
    task.payload &&
    typeof task.payload === "object" &&
    !Array.isArray(task.payload)
      ? (task.payload as Record<string, unknown>)
      : {};
  const metadata = getPayloadMetadata(payload);
  const presentation =
    typeof metadata.presentation === "string"
      ? metadata.presentation.trim().toLowerCase()
      : "";
  const channel =
    typeof metadata.channel === "string"
      ? metadata.channel.trim().toLowerCase()
      : "";
  const routeDecision =
    metadata.routeDecision &&
    typeof metadata.routeDecision === "object" &&
    !Array.isArray(metadata.routeDecision)
      ? (metadata.routeDecision as Record<string, unknown>)
      : metadata.routingDecision &&
          typeof metadata.routingDecision === "object" &&
          !Array.isArray(metadata.routingDecision)
        ? (metadata.routingDecision as Record<string, unknown>)
        : {};
  const route =
    typeof routeDecision.route === "string"
      ? routeDecision.route.trim().toLowerCase()
      : "";
  return (
    task.runtimeConnectionId == null &&
    (extractTaskChatSessionId(payload) !== null ||
      presentation === "chat" ||
      channel === "chat" ||
      route === "server_brain" ||
      route === "shared_brain")
  );
}

function isDurableChatGenerationTask(
  task: Pick<typeof tasks.$inferSelect, "payload">,
): boolean {
  const payload = readRecord(task.payload) ?? {};
  const chatGeneration = readRecord(
    getPayloadMetadata(payload).chatGeneration,
  );
  return chatGeneration?.queued === true;
}

function readAgentRunState(metadata: Record<string, unknown>): string | null {
  return typeof metadata.agentRunState === "string"
    ? metadata.agentRunState
    : null;
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
  const lockAcquired = reliability
    ? await reliability.store.acquireLock(lockKey, lockOwner, 30_000)
    : true;
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
            and(
              isNull(tasks.dispatchLeaseExpiresAt),
              lt(tasks.updatedAt, cutoff),
            ),
          ),
        ),
        and(
          eq(tasks.status, "running" as TaskStatus),
          lt(tasks.updatedAt, cutoff),
        ),
        and(
          eq(tasks.status, "waiting_approval" as TaskStatus),
          lt(tasks.updatedAt, new Date(now.getTime() - TASK_APPROVAL_TTL_MS)),
        ),
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
      if (
        isChatGenerationQueueEnabled(app) &&
        isDurableChatGenerationTask(task)
      ) {
        // Durable chat workers own their workload-aware 60/120/240 second
        // deadlines. The legacy runtime stale cutoff must not preempt them.
        continue;
      }
      const target = await getUserDevice(app, task.userId, task.targetDeviceId);
      const targetStatus = target?.targetStatus ?? "missing";
      const lease = getTaskDispatchLeaseSnapshot(task);
      const reason =
        task.status === "running"
          ? "runtime_execution_stale"
          : task.status === "waiting_approval"
            ? "approval_expired"
            : "dispatch_lease_expired";

      if (task.status === "waiting_approval") {
        const message = "Onay süresi dolduğu için görev kapatıldı.";
        const rows = await app.db
          .update(tasks)
          .set(buildTaskCancellationUpdate(now))
          .where(eq(tasks.id, task.id))
          .returning();
        const canceledTask = rows[0] ?? {
          ...task,
          status: "canceled" as TaskStatus,
          summary: message,
          error: message,
          canceledAt: now,
          updatedAt: now,
          queuePosition: 0,
        };
        await insertTaskEvent(app, {
          taskId: canceledTask.id,
          userId: canceledTask.userId,
          status: "canceled",
          message,
          payload: {
            reconciled: true,
            reason,
            targetStatus,
            lease,
          },
        });
        await publishTaskEvent(app, canceledTask, "task.canceled", {
          task: shapeTaskFeedItem(canceledTask),
          reconciled: true,
          reason,
          targetStatus,
          lease,
        });
        await syncChatTaskLifecycle(app, {
          originalTask: task,
          updatedTask: canceledTask,
          message,
        });
        await reliability?.clearTaskDispatchLock(canceledTask.id);
        await releaseChatGenerationAdmission(app, canceledTask.id);
        reconciled.push(shapeTaskFeedItem(canceledTask));
        continue;
      }

      if ((task.dispatchAttemptCount ?? 0) >= MAX_TASK_DISPATCH_ATTEMPTS) {
        const message = "Desktop görevi birkaç denemeden sonra teslim edilemedi. Lütfen desktop bağlantısını kontrol edip tekrar deneyin.";
        const rows = await app.db
          .update(tasks)
          .set(buildTaskDispatchExhaustedUpdate({ now, message }))
          .where(eq(tasks.id, task.id))
          .returning();
        const failedTask = rows[0] ?? {
          ...task,
          ...buildTaskDispatchExhaustedUpdate({ now, message }),
        };
        await insertTaskEvent(app, {
          taskId: failedTask.id,
          userId: failedTask.userId,
          status: "failed",
          message,
          payload: {
            reconciled: true,
            reason: "dispatch_attempt_budget_exhausted",
            previousReason: reason,
            targetStatus,
            lease,
            attemptCount: task.dispatchAttemptCount ?? 0,
          },
        });
        await publishTaskEvent(app, failedTask, "task.updated", {
          task: shapeTaskFeedItem(failedTask),
          reconciled: true,
          reason: "dispatch_attempt_budget_exhausted",
          targetStatus,
          lease,
        });
        await syncChatTaskLifecycle(app, {
          originalTask: task,
          updatedTask: failedTask,
          message,
        });
        await reliability?.clearTaskDispatchLock(failedTask.id);
        await releaseChatGenerationAdmission(app, failedTask.id);
        reconciled.push(shapeTaskFeedItem(failedTask));
        continue;
      }

      if (task.status === "running" && isSharedBrainChatTask(task)) {
        const message =
          "Bu sohbet yanıtı tamamlanamadı. Lütfen tekrar deneyin.";
        const rows = await app.db
          .update(tasks)
          .set({
            status: "failed",
            summary: message,
            error: message,
            completedAt: now,
            updatedAt: now,
            queuePosition: 0,
            dispatchLeaseId: null,
            dispatchLeaseIssuedAt: null,
            dispatchLeaseExpiresAt: null,
            dispatchAckAt: null,
            runtimeConnectionId: null,
          })
          .where(
            and(
              eq(tasks.id, task.id),
              eq(tasks.status, "running" as TaskStatus),
            ),
          )
          .returning();
        if (rows.length === 0) {
          // A completion worker won the race while the stale reconciler was
          // preparing its fallback. Never emit a second failure transition.
          continue;
        }
        const failedTask = rows[0] ?? {
          ...task,
          status: "failed" as TaskStatus,
          summary: message,
          error: message,
          completedAt: now,
          updatedAt: now,
          queuePosition: 0,
          dispatchLeaseId: null,
          dispatchLeaseIssuedAt: null,
          dispatchLeaseExpiresAt: null,
          dispatchAckAt: null,
          runtimeConnectionId: null,
        };

        await insertTaskEvent(app, {
          taskId: failedTask.id,
          userId: failedTask.userId,
          status: "failed",
          message,
          payload: {
            reconciled: true,
            reason: "server_brain_chat_stale",
            previousReason: reason,
            targetStatus,
            lease,
          },
        });
        await publishTaskEvent(app, failedTask, "task.updated", {
          task: shapeTaskFeedItem(failedTask),
          reconciled: true,
          reason: "server_brain_chat_stale",
          targetStatus,
          lease,
        });
        await syncChatTaskLifecycle(app, {
          originalTask: task,
          updatedTask: failedTask,
          message,
        });
        await reliability?.clearTaskDispatchLock(failedTask.id);
        await releaseChatGenerationAdmission(app, failedTask.id);
        reconciled.push(shapeTaskFeedItem(failedTask));
        continue;
      }

      if (task.status === "running") {
        const owningConnection = await getRuntimeConnectionSnapshot(
          app,
          task.runtimeConnectionId ?? null,
        );
        if (isRuntimeConnectionFresh(owningConnection, now)) {
          continue;
        }
      } else if (target?.canReceiveTasks) {
        const activeConnection =
          await getLatestActiveRuntimeConnectionForDevice(app, {
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
        userId: updatedTask.userId,
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

function isChatGenerationSettled(status: TaskStatus): boolean {
  return isTerminalTaskStatus(status) || status === "waiting_approval";
}

async function completeServerBrainTask(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId: string;
    chatSessionId?: string | null;
    sessionArtifacts?: Record<string, unknown>[];
    responseText: string;
    provider: string;
    model: string;
    route: string;
    workload: string;
    modelRoute?: Record<string, unknown> | null;
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
    freshData?: Record<string, unknown> | null;
    freshDataDomain?: string | null;
    freshDataStatus?: string | null;
    freshDataEvidenceSufficient?: boolean | null;
    freshDataStreamPolicy?: string | null;
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
    claimConfidence?: number | null;
    claimSourceCounts?: Record<string, unknown> | null;
    uncertaintyAction?: string | null;
    missingEvidenceCount?: number | null;
    verifiedEvidenceCount?: number | null;
    contestedMemoryCount?: number | null;
    lowConfidenceClaims?: number | null;
    selfCheckApplied?: boolean | null;
    toolCalledForUncertainty?: boolean | null;
    clarificationRequested?: boolean | null;
    responseBudgetState?: string | null;
    responseBudgetReason?: string | null;
    contextPacketCount?: number | null;
    contextPacketKinds?: string[];
    healthContextUsed?: boolean;
    contextFreshness?: unknown;
    assistantBlocks?: unknown[];
    authoritativeArtifactData?: unknown;
    visionBlock?: VisionEvidenceV3 | null;
    toolFlow?: ToolFlowTraceSummary | null;
    connectorWriteApproval?: ReturnType<typeof readConnectorWriteApproval>;
    connectorWriteApprovalRequest?: Record<string, unknown> | null;
    sourceImages?: HostedImageSource[];
  },
) {
  const task = await getTaskById(app, input.taskId);
  if (!task || task.userId !== input.userId) {
    throw notFound("Task not found");
  }
  if (isChatGenerationSettled(task.status)) {
    await releaseChatGenerationAdmission(app, task.id);
    return Object.assign(task, { completionTransitionOwned: false as const });
  }

  const payload =
    task.payload &&
    typeof task.payload === "object" &&
    !Array.isArray(task.payload)
      ? (task.payload as Record<string, unknown>)
      : {};
  const basePayloadMetadata = getPayloadMetadata(payload);
  const payloadMetadata =
    input.sessionArtifacts && input.sessionArtifacts.length > 0
      ? { ...basePayloadMetadata, sessionArtifacts: input.sessionArtifacts }
      : basePayloadMetadata;
  const prompt = getTaskPrompt(payload);
  const resolved = resolveCompletionAssistantBlocks({
    responseText: input.responseText,
    assistantBlocks: input.assistantBlocks,
    prompt,
    selectedWorkload:
      typeof payloadMetadata.selectedWorkload === "string"
        ? payloadMetadata.selectedWorkload
        : null,
  });
  const tablePolicy = shouldPromoteMarkdownTableToWidget({
    prompt,
    selectedWorkload:
      typeof payloadMetadata.selectedWorkload === "string"
        ? payloadMetadata.selectedWorkload
        : input.workload,
  })
    ? "explicit_only"
    : "forbidden";
  const blockValidation = validateAssistantBlockContract({
    blocks: resolved.blocks,
    content: resolved.text,
    mode: "normalize",
    tablePolicy,
    qualityBlocks: input.assistantBlocks,
  });
  let resolvedAssistantBlocks = blockValidation.blocks;
  let blockQuality = blockValidation.blockQuality;
  let visibleResponseText = resolveVisibleAssistantResponse({
    responseText: resolved.text,
    assistantBlocks: resolvedAssistantBlocks,
    allowPublicProviderReferences:
      input.webGroundingUsed === true || (input.webSourceCount ?? 0) > 0,
  });
  if (visibleResponseText) {
    visibleResponseText = resolveNonEchoAssistantText({
      prompt,
      responseText: visibleResponseText,
    });
  }
  const normalizedFreshData = normalizeFreshDataEnvelope(input.freshData);
  visibleResponseText = sanitizeFinalAssistantResponse({
    prompt,
    text: visibleResponseText,
    workload: input.workload,
    allowVerificationLanguage:
      input.webGroundingUsed === true || (input.webSourceCount ?? 0) > 0,
    freshData: normalizedFreshData
      ? {
          freshnessRequired: normalizedFreshData.freshnessRequired,
          status: normalizedFreshData.status,
          evidence: {
            sufficient: normalizedFreshData.evidence.sufficient,
          },
        }
      : null,
  });
  const artifactPipeline = await buildArtifactPipeline({
    userRequest: prompt,
    responseText: visibleResponseText,
    assistantBlocks: resolvedAssistantBlocks,
    metadata: payloadMetadata,
    understandingEnvelope:
      extractUnderstandingEnvelopeFromMetadata(payloadMetadata),
    userId: input.userId,
    taskId: input.taskId,
    model: input.model,
    provenance: {
      webGroundingUsed: input.webGroundingUsed ?? false,
      webSourceCount: input.webSourceCount ?? 0,
      documentSourceCount: input.documentSourceCount ?? 0,
      retrievalResultCount: input.retrievalResultCount ?? 0,
      skillUsed: input.skillUsed ?? false,
      skillId: input.skillId ?? null,
      toolCallCount: input.toolFlow?.count ?? 0,
    },
    authoritativeData: input.authoritativeArtifactData,
  });
  if (artifactPipeline.kind === "rendered") {
    const suppressBlockTypes = new Set<string>(
      artifactPipeline.output.type === "pdf"
        ? ["document_block", "table"]
        : artifactPipeline.output.type === "table"
          ? ["table"]
          : artifactPipeline.output.type === "chart"
            ? ["chart"]
            : artifactPipeline.output.type === "svg"
              ? ["svg"]
              : artifactPipeline.output.type === "document"
                ? ["document_block"]
                : artifactPipeline.output.type === "image_prompt"
                  ? ["code"]
                  : [],
    );
    const mergedBlocks = [
      ...resolvedAssistantBlocks.filter(
        (block) => !suppressBlockTypes.has(block.type),
      ),
      ...artifactPipeline.assistantBlocks,
    ];
    visibleResponseText = artifactPipeline.ownsVisibleContent
      ? ""
      : artifactPipeline.visibleText || visibleResponseText;
    const mergedValidation = validateAssistantBlockContract({
      blocks: mergedBlocks,
      content: visibleResponseText,
      mode: "normalize",
      tablePolicy,
      qualityBlocks: [
        ...(input.assistantBlocks ?? []),
        ...artifactPipeline.assistantBlocks,
      ],
    });
    resolvedAssistantBlocks = mergedValidation.blocks;
    blockQuality = applyAssistantBlockSemanticQuality(
      mergedValidation.blockQuality,
      {
        sourceAuthority: artifactPipeline.spec.metadata?.sourceAuthority,
        validationOk: true,
        errorCodes: [],
      },
    );
  } else if (artifactPipeline.kind === "evidence_required") {
    visibleResponseText =
      "Araştırma için yeterli doğrulanabilir kaynak veya içerik oluşmadı; bu yüzden belge hazırlanmadı. Lütfen tekrar dene.";
    const evidenceValidation = validateAssistantBlockContract({
      // A failed evidence gate is authoritative terminal truth. Do not retain
      // provisional prose, cards, code, media, or stale artifacts from the
      // model response that preceded it.
      blocks: [],
      content: visibleResponseText,
      mode: "normalize",
      tablePolicy,
      qualityBlocks: input.assistantBlocks,
    });
    resolvedAssistantBlocks = evidenceValidation.blocks;
    blockQuality = evidenceValidation.blockQuality;
  } else if (artifactPipeline.kind === "validation_failed") {
    visibleResponseText =
      artifactPipeline.reason === "authoritative_data_unavailable"
        ? "İstenen çıktıyı güvenilir ve eksiksiz veriye dayandıramadım; bu yüzden hatalı bir widget üretmedim. Veriyi açık eşleşmelerle paylaşabilir veya yeniden deneyebilirsin."
        : "İstenen çıktı doğrulama kontrollerini geçmedi; bu yüzden hatalı sonucu göstermedim. Verileri kontrol edip yeniden deneyebilirsin.";
    const failedValidation = validateAssistantBlockContract({
      blocks: [],
      content: visibleResponseText,
      mode: "normalize",
      tablePolicy,
      qualityBlocks: input.assistantBlocks,
    });
    resolvedAssistantBlocks = failedValidation.blocks;
    blockQuality = applyAssistantBlockSemanticQuality(
      failedValidation.blockQuality,
      {
        sourceAuthority: artifactPipeline.spec?.metadata?.sourceAuthority,
        validationOk: false,
        errorCodes: artifactPipeline.validation.errors.map((error) => error.code),
      },
    );
  }
  // Model zaten bir veri/matematik görseli (chart/math/table/svg) ürettiyse,
  // hosted image üretimi ÇALIŞMAZ ve bu blokları ASLA ezmez. "Grafiğini çiz"
  // gibi isteklerde akıllı inference'ın verdiği doğru grafik korunur; ham
  // görsel-router artık chart kararını bastıramaz.
  const VISUAL_DATA_BLOCK_TYPES = new Set([
    "chart",
    "math",
    "math_surface_3d",
    "table",
    "svg",
  ]);
  const hasVisualDataBlock = resolvedAssistantBlocks.some((block) =>
    VISUAL_DATA_BLOCK_TYPES.has(block.type),
  );
  const referencedSourceImages = await resolveMediaInputSources(app, input.userId, payloadMetadata);
  const effectiveSourceImages = referencedSourceImages.length > 0
    ? referencedSourceImages
    : input.sourceImages;
  const generatedImageArtifact =
    artifactPipeline.kind === "evidence_required" ||
    artifactPipeline.kind === "validation_failed" ||
    hasVisualDataBlock
    ? null
    : await maybeGenerateHostedImageArtifact(app, {
        prompt,
        metadata: payloadMetadata,
        userId: input.userId,
        taskId: input.taskId,
        sourceImages: effectiveSourceImages,
      });
  const imageGenerationRequested =
    artifactPipeline.kind !== "evidence_required" &&
    artifactPipeline.kind !== "validation_failed" &&
    !hasVisualDataBlock && (
      isHostedImageGenerationRequest(prompt) ||
      isHostedImageEditRequest(prompt, effectiveSourceImages?.length ?? 0)
    );
  if (generatedImageArtifact) {
    visibleResponseText = generatedImageArtifact.previewText;
    resolvedAssistantBlocks = [];
  } else if (imageGenerationRequested) {
    visibleResponseText = resolveImageGenerationFallbackText(payloadMetadata);
    resolvedAssistantBlocks = [];
  }
  const renderRecipeMetadata =
    artifactPipeline.kind === "rendered"
      ? {
          ...payloadMetadata,
          artifact: {
            artifactId: artifactPipeline.output.artifactId,
            type: artifactPipeline.output.type,
            validationOk: artifactPipeline.output.validation.ok,
            errorCodes: artifactPipeline.output.validation.errors
              .map((error) => error.code)
              .slice(0, 16),
          },
        }
      : payloadMetadata;
  const renderRecipe =
    artifactPipeline.kind === "evidence_required" ||
    artifactPipeline.kind === "validation_failed"
      ? null
      : generatedImageArtifact
    ? null
    : visibleResponseText || artifactPipeline.kind === "rendered"
      ? buildLocalRenderRecipe({
          prompt,
          responseText: visibleResponseText,
          assistantBlocks: resolvedAssistantBlocks,
          authoritativeTextBlocks:
            artifactPipeline.kind === "rendered"
              ? artifactSpecToRenderRecipeBlocks(artifactPipeline.spec)
              : undefined,
          metadata: renderRecipeMetadata,
          renderOn:
            typeof payload.source === "string" &&
            payload.source.trim().toLowerCase() === "desktop"
              ? "desktop"
              : "mobile",
          taskId: task.id,
        })
      : null;
  const structuredSummary = summarizeStructuredAssistantBlocks(
    resolvedAssistantBlocks,
  );
  let taskSummary = visibleResponseText
    ? visibleResponseText.slice(0, 280)
    : structuredSummary;

  const now = new Date();
  const result: Record<string, unknown> = {
    text: visibleResponseText,
    route: input.route,
    workload: input.workload,
    modelRoute: input.modelRoute ?? null,
    latencyMs: input.latencyMs,
    promptTokens: input.promptTokens,
    completionTokens: input.completionTokens,
    totalTokens: input.totalTokens,
    firstDeltaMs: input.firstDeltaMs ?? null,
    completionLatencyMs: input.completionLatencyMs ?? input.latencyMs,
    responseBytes:
      input.responseBytes ??
      Buffer.byteLength(
        visibleResponseText || JSON.stringify(resolvedAssistantBlocks ?? []),
        "utf8",
      ),
    fallbackUsed: input.fallbackUsed ?? false,
    groundingUsed: input.groundingUsed ?? false,
    documentSourceCount: input.documentSourceCount ?? 0,
    webGroundingUsed: input.webGroundingUsed ?? false,
    webSourceCount: input.webSourceCount ?? 0,
    freshData: normalizedFreshData,
    freshDataDomain:
      normalizedFreshData?.domain ?? input.freshDataDomain ?? null,
    freshDataStatus:
      normalizedFreshData?.status ?? input.freshDataStatus ?? null,
    freshDataEvidenceSufficient:
      normalizedFreshData?.evidence.sufficient ??
      input.freshDataEvidenceSufficient ??
      null,
    freshDataStreamPolicy:
      normalizedFreshData?.freshnessRequired === true &&
      normalizedFreshData.evidence.sufficient === false
        ? "buffer_until_validated"
        : (input.freshDataStreamPolicy ?? null),
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
    claimConfidence: input.claimConfidence ?? null,
    claimSourceCounts: input.claimSourceCounts ?? null,
    uncertaintyAction: input.uncertaintyAction ?? null,
    missingEvidenceCount: input.missingEvidenceCount ?? 0,
    verifiedEvidenceCount: input.verifiedEvidenceCount ?? 0,
    contestedMemoryCount: input.contestedMemoryCount ?? 0,
    lowConfidenceClaims: input.lowConfidenceClaims ?? 0,
    selfCheckApplied: input.selfCheckApplied ?? false,
    toolCalledForUncertainty: input.toolCalledForUncertainty ?? false,
    clarificationRequested: input.clarificationRequested ?? false,
    responseBudgetState: input.responseBudgetState ?? null,
    responseBudgetReason: input.responseBudgetReason ?? null,
    contextPacketCount: input.contextPacketCount ?? 0,
    contextPacketKinds: input.contextPacketKinds ?? [],
    healthContextUsed: input.healthContextUsed ?? false,
    contextFreshness: input.contextFreshness ?? null,
    assistantBlocks: resolvedAssistantBlocks,
    ...(input.visionBlock ? { visionBlock: input.visionBlock } : {}),
    blockQuality,
    ...(artifactPipeline.kind === "rendered"
      ? {
          artifact: artifactResultForTask(
            artifactPipeline.output,
            artifactPipeline.rendererUsed,
            artifactPipeline.latencyMs,
          ),
        }
      : artifactPipeline.kind === "desktop_required"
        ? {
            artifact: {
              type: artifactPipeline.intent.type,
              requiresDesktopRuntime: true,
              reason: artifactPipeline.intent.privateDataReason,
            },
          }
        : artifactPipeline.kind === "evidence_required"
          ? {
              artifact: {
                type: artifactPipeline.intent.type,
                generated: false,
                reason: artifactPipeline.reason,
              },
            }
          : artifactPipeline.kind === "validation_failed"
            ? {
                artifact: {
                  type: artifactPipeline.intent.type,
                  generated: false,
                  reason: artifactPipeline.reason,
                  errorCodes: artifactPipeline.validation.errors
                    .map((error) => error.code)
                    .slice(0, 16),
                },
              }
          : {}),
    imageArtifactGenerated: Boolean(generatedImageArtifact),
    ...(input.toolFlow ? { toolFlow: input.toolFlow } : {}),
    ...(input.connectorWriteApproval
      ? { connectorWriteApproval: input.connectorWriteApproval }
      : {}),
    ...(renderRecipe ? { renderRecipe } : {}),
  };
  const resultBlob = await storeTaskJsonBlob(app, {
    taskId: task.id,
    userId: input.userId,
    slot: "result",
    scope: "task_result",
    value: result,
  });
  const durableConnectorApproval = input.connectorWriteApprovalRequest ?? null;
  const approvalRequestBlob = durableConnectorApproval
    ? await storeTaskJsonBlob(app, {
        taskId: task.id,
        userId: input.userId,
        slot: "approval_request",
        scope: "task_approval_request",
        value: durableConnectorApproval,
      })
    : null;
  const finalTaskStatus: TaskStatus = durableConnectorApproval
    ? "waiting_approval"
    : "completed";

  const rows = await app.db
    .update(tasks)
    .set({
      status: finalTaskStatus,
      summary: taskSummary,
      error: null,
      result,
      resultBlobId: resultBlob?.blobId ?? null,
      approvalRequest: durableConnectorApproval,
      approvalRequestBlobId: approvalRequestBlob?.blobId ?? null,
      completedAt: finalTaskStatus === "completed" ? now : null,
      updatedAt: now,
      queuePosition: 0,
    })
    .where(
      and(
        eq(tasks.id, task.id),
        eq(tasks.userId, input.userId),
        eq(tasks.status, "running"),
      ),
    )
    .returning();

  // Two completion workers can finish at nearly the same time. The first
  // conditional update owns the terminal transition; the loser must return
  // the already-persisted result without emitting another completion event.
  if (rows.length === 0) {
    const currentTask = await getTaskById(app, task.id);
    return Object.assign(currentTask ?? task, {
      completionTransitionOwned: false as const,
    });
  }

  let updatedTask = rows[0] ?? {
    ...task,
    status: finalTaskStatus,
    summary: taskSummary,
    error: null,
    result,
    approvalRequest: durableConnectorApproval,
    approvalRequestBlobId: approvalRequestBlob?.blobId ?? null,
    completedAt: finalTaskStatus === "completed" ? now : null,
    updatedAt: now,
    queuePosition: 0,
  };
  void applyGoalProgressBlocks(app, {
    userId: input.userId,
    blocks: resolvedAssistantBlocks,
  });

  const artifactsToPersist: PersistableArtifactInput[] = [];
  if (artifactPipeline.kind === "rendered") {
    artifactsToPersist.push(
      buildArtifactOutputArtifact(updatedTask.id, artifactPipeline.output),
    );
  }
  if (renderRecipe) {
    artifactsToPersist.push(
      buildStructuredOutputArtifact(updatedTask.id, renderRecipe),
    );
  }
  if (generatedImageArtifact) {
    artifactsToPersist.push({
      ...generatedImageArtifact.artifact,
      binaryBody: generatedImageArtifact.binaryBody,
    });
  }

  let structuredOutputArtifacts: Array<ReturnType<typeof shapeTaskArtifact>> =
    [];
  if (artifactsToPersist.length > 0) {
    const storedArtifacts = await persistArtifacts(
      app,
      updatedTask.id,
      input.userId,
      artifactsToPersist,
    );
    structuredOutputArtifacts = await Promise.all(
      storedArtifacts.map((artifact) =>
        shapePublicArtifactRecord(app, artifact, input.userId),
      ),
    );
  }
  const generatedImageBlocks = generatedImageArtifact
    ? buildGeneratedImageArtifactBlocks(structuredOutputArtifacts)
    : [];
  if (generatedImageBlocks.length > 0) {
    resolvedAssistantBlocks = normalizeAssistantMessageBlocks({
      blocks: [...resolvedAssistantBlocks, ...generatedImageBlocks],
    });
    result.assistantBlocks = resolvedAssistantBlocks;
    result.artifacts = structuredOutputArtifacts;
    result.imageArtifactPersisted = true;
    const finalResultBlob = await storeTaskJsonBlob(app, {
      taskId: task.id,
      userId: input.userId,
      slot: "result",
      scope: "task_result",
      value: result,
    });
    const finalRows = await app.db
      .update(tasks)
      .set({
        result,
        resultBlobId: finalResultBlob?.blobId ?? null,
        updatedAt: now,
      })
      .where(eq(tasks.id, task.id))
      .returning();
    updatedTask = finalRows[0] ?? {
      ...updatedTask,
      result,
      resultBlobId: finalResultBlob?.blobId ?? updatedTask.resultBlobId ?? null,
      updatedAt: now,
    };
  } else if (generatedImageArtifact) {
    visibleResponseText =
      "Görsel üretildi ama dosya hazırlanamadı. Lütfen biraz sonra tekrar dene.";
    resolvedAssistantBlocks = [];
    result.text = visibleResponseText;
    result.assistantBlocks = resolvedAssistantBlocks;
    result.artifacts = [];
    result.imageArtifactGenerated = false;
    result.imageArtifactPersisted = false;
    const finalResultBlob = await storeTaskJsonBlob(app, {
      taskId: task.id,
      userId: input.userId,
      slot: "result",
      scope: "task_result",
      value: result,
    });
    const finalRows = await app.db
      .update(tasks)
      .set({
        summary: visibleResponseText,
        result,
        resultBlobId: finalResultBlob?.blobId ?? null,
        updatedAt: now,
      })
      .where(eq(tasks.id, task.id))
      .returning();
    updatedTask = finalRows[0] ?? {
      ...updatedTask,
      summary: visibleResponseText,
      result,
      resultBlobId: finalResultBlob?.blobId ?? updatedTask.resultBlobId ?? null,
      updatedAt: now,
    };
  }

  const finalVisibleResponseText = sanitizeFinalAssistantResponse({
    prompt,
    text: visibleResponseText,
    workload: input.workload,
    allowVerificationLanguage:
      input.webGroundingUsed === true || (input.webSourceCount ?? 0) > 0,
    imageGenerationRequested,
    hasRenderableOutput:
      resolvedAssistantBlocks.length > 0 ||
      structuredOutputArtifacts.length > 0 ||
      Boolean(renderRecipe),
    freshData: normalizedFreshData
      ? {
          freshnessRequired: normalizedFreshData.freshnessRequired,
          status: normalizedFreshData.status,
          evidence: {
            sufficient: normalizedFreshData.evidence.sufficient,
          },
        }
      : null,
  });
  if (finalVisibleResponseText !== visibleResponseText) {
    visibleResponseText = finalVisibleResponseText;
    result.text = visibleResponseText;
    result.responseBytes = Buffer.byteLength(
      visibleResponseText || JSON.stringify(resolvedAssistantBlocks ?? []),
      "utf8",
    );
    taskSummary = visibleResponseText
      ? visibleResponseText.slice(0, 280)
      : structuredSummary;
    const finalResultBlob = await storeTaskJsonBlob(app, {
      taskId: task.id,
      userId: input.userId,
      slot: "result",
      scope: "task_result",
      value: result,
    });
    const finalRows = await app.db
      .update(tasks)
      .set({
        summary: taskSummary,
        result,
        resultBlobId: finalResultBlob?.blobId ?? null,
        updatedAt: now,
      })
      .where(eq(tasks.id, task.id))
      .returning();
    updatedTask = finalRows[0] ?? {
      ...updatedTask,
      summary: taskSummary,
      result,
      resultBlobId: finalResultBlob?.blobId ?? updatedTask.resultBlobId ?? null,
      updatedAt: now,
    };
  }

  await insertTaskEvent(app, {
    taskId: updatedTask.id,
    userId: updatedTask.userId,
    status: finalTaskStatus,
    message: durableConnectorApproval
      ? "Connector yazma işlemi kullanıcı onayı bekliyor"
      : "Elyan yanıtı hazır",
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
      responseBytes:
        input.responseBytes ?? Buffer.byteLength(visibleResponseText, "utf8"),
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
      retrievalSemanticCandidateCount:
        input.retrievalSemanticCandidateCount ?? 0,
      rerankUsed: input.rerankUsed ?? false,
      rerankDegradedReason: input.rerankDegradedReason ?? null,
      qualityPolicyApplied: input.qualityPolicyApplied ?? false,
      dataGroundingLevel: input.dataGroundingLevel ?? null,
      personalizationScope: input.personalizationScope ?? null,
      responseLanguage: input.responseLanguage ?? null,
      evidenceSufficiency: input.evidenceSufficiency ?? null,
      dataConfidence: input.dataConfidence ?? null,
      dataQualityWarnings: input.dataQualityWarnings ?? [],
      claimConfidence: input.claimConfidence ?? null,
      claimSourceCounts: input.claimSourceCounts ?? null,
      uncertaintyAction: input.uncertaintyAction ?? null,
      missingEvidenceCount: input.missingEvidenceCount ?? 0,
      verifiedEvidenceCount: input.verifiedEvidenceCount ?? 0,
      contestedMemoryCount: input.contestedMemoryCount ?? 0,
      lowConfidenceClaims: input.lowConfidenceClaims ?? 0,
      selfCheckApplied: input.selfCheckApplied ?? false,
      toolCalledForUncertainty: input.toolCalledForUncertainty ?? false,
      clarificationRequested: input.clarificationRequested ?? false,
      responseBudgetState: input.responseBudgetState ?? null,
      responseBudgetReason: input.responseBudgetReason ?? null,
      contextPacketCount: input.contextPacketCount ?? 0,
      contextPacketKinds: input.contextPacketKinds ?? [],
      healthContextUsed: input.healthContextUsed ?? false,
      contextFreshness: input.contextFreshness ?? null,
      blockQuality,
      ...(artifactPipeline.kind === "rendered"
        ? {
            artifact: {
              artifactId: artifactPipeline.output.artifactId,
              type: artifactPipeline.output.type,
              validationOk: artifactPipeline.output.validation.ok,
              errorCodes: artifactPipeline.output.validation.errors
                .map((error) => error.code)
                .slice(0, 16),
              rendererUsed: artifactPipeline.rendererUsed,
              latencyMs: artifactPipeline.latencyMs,
            },
          }
        : artifactPipeline.kind === "desktop_required"
          ? {
              artifact: {
                type: artifactPipeline.intent.type,
                requiresDesktopRuntime: true,
                reason: artifactPipeline.intent.privateDataReason,
              },
            }
          : {}),
      artifactCount: structuredOutputArtifacts.length,
      ...(renderRecipe ? { renderRecipe } : {}),
      ...(structuredOutputArtifacts.length > 0
        ? { artifacts: structuredOutputArtifacts }
        : {}),
    },
  });

  if (structuredOutputArtifacts.length > 0) {
    await persistSessionArtifactMemory(app, {
      userId: input.userId,
      sessionId: input.chatSessionId,
      prompt,
      artifacts: structuredOutputArtifacts,
    }).catch((error) => {
      app.log.warn(
        { taskId: updatedTask.id, error },
        "session artifact memory could not be persisted",
      );
    });

    await insertTaskEvent(app, {
      taskId: updatedTask.id,
      userId: updatedTask.userId,
      status: finalTaskStatus,
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

  if (
    finalTaskStatus === "completed" &&
    input.fallbackState !== "continuity_response"
  ) {
    void recordTaskLearningFromCompletion(app, {
      userId: updatedTask.userId,
      accountId: updatedTask.userId,
      taskId: updatedTask.id,
      title: updatedTask.title,
      message: getTaskPrompt(
        task.payload &&
          typeof task.payload === "object" &&
          !Array.isArray(task.payload)
          ? (task.payload as Record<string, unknown>)
          : {},
      ),
      status: "completed",
    }).catch(() => {
      app.log.warn(
        {
          taskId: updatedTask.id,
          errorClass: "task_learning_store_unavailable",
        },
        "task completion learning persistence skipped",
      );
    });
  }
  void recordBlockQualityLearning(app, {
    userId: updatedTask.userId,
    accountId: updatedTask.userId,
    taskId: updatedTask.id,
    quality: blockQuality,
  }).catch(() => {
    app.log.warn(
      {
        taskId: updatedTask.id,
        errorClass: "block_quality_store_unavailable",
      },
      "block quality learning persistence skipped",
    );
  });
  if (artifactPipeline.kind === "rendered") {
    void recordArtifactLearningEvent(app, {
      userId: updatedTask.userId,
      taskId: updatedTask.id,
      output: artifactPipeline.output,
      rendererUsed: artifactPipeline.rendererUsed,
      latencyMs: artifactPipeline.latencyMs,
    }).catch(() => undefined);
  }
  if (
    finalTaskStatus === "completed" &&
    input.fallbackState !== "continuity_response"
  ) {
    void maybeQueueAutomaticSharedBrainRefresh(app, {
      userId: updatedTask.userId,
      source: "task_completed",
    }).catch(() => undefined);
  }

  await publishTaskEvent(app, updatedTask, "task.updated", {
    task: shapeTaskFeedItem(updatedTask),
  });

  const chatStreamOwnsAssistantFinal =
    finalTaskStatus === "completed" &&
    input.route === "shared_brain" &&
    extractChatStreamingMetadata(task) !== null;
  if (!chatStreamOwnsAssistantFinal) {
    await syncChatTaskLifecycle(app, {
      originalTask: task,
      updatedTask,
      message: input.responseText,
    });
  }

  await releaseChatGenerationAdmission(app, updatedTask.id);
  if (finalTaskStatus === "completed") {
    await releaseMediaInputsFromMetadata(
      app,
      updatedTask.userId,
      payloadMetadata,
    ).catch(() => undefined);
  }

  return Object.assign(updatedTask, {
    completionTransitionOwned: true as const,
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
  if (isTerminalTaskStatus(task.status) || task.status === "waiting_approval") {
    throw new AppError(409, "task_not_processable", "Görev artık çalıştırılamıyor.");
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
    .where(
      and(
        eq(tasks.id, task.id),
        eq(tasks.userId, input.userId),
        inArray(tasks.status, ["queued", "planning"]),
      ),
    )
    .returning();

  if (rows.length === 0) {
    const latestTask = await getTaskById(app, input.taskId);
    if (latestTask?.status === "running") {
      return latestTask;
    }
    throw new AppError(409, "task_not_processable", "Görev artık çalıştırılamıyor.");
  }

  const updatedTask = rows[0];

  await insertTaskEvent(app, {
    taskId: updatedTask.id,
    userId: updatedTask.userId,
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
  const sessionId =
    typeof chatRecord.sessionId === "string" ? chatRecord.sessionId.trim() : "";
  const assistantMessageId =
    typeof chatRecord.assistantMessageId === "string"
      ? chatRecord.assistantMessageId.trim()
      : "";
  if (!sessionId || !assistantMessageId) {
    return null;
  }

  return {
    sessionId,
    assistantMessageId,
  };
}

function buildUnderstandingMetadataForTask(
  understanding: UserUnderstandingResult,
) {
  return {
    intent: understanding.intent,
    context: understanding.context,
    routingHints: understanding.routingHints,
    ...(understanding.envelope
      ? {
          envelope: understanding.envelope,
          envelopeSource:
            understanding.envelopeSource ?? understanding.envelope.source,
          envelopeConfidence:
            understanding.envelopeConfidence ??
            understanding.envelope.confidence,
        }
      : {}),
  };
}

function summarizeUnderstandingForSafeTelemetry(
  understanding: UserUnderstandingResult,
) {
  return {
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
    ...envelopeTelemetrySummary(understanding.envelope),
  };
}

function resolveSharedBrainWorkloadForUnderstanding(input: {
  routeDecision: CommandRouteDecision | null | undefined;
  prompt: string;
  attachmentContextUsed?: boolean;
  hasVisionImage?: boolean;
  envelope?: UnderstandingEnvelope | null;
}) {
  const toolSkillSelection = selectToolSkillForTurn({
    message: input.prompt,
  });
  const selectorWorkload =
    toolSkillSelection.selected.workload &&
    toolSkillSelection.outputContract.requiresArtifact &&
    toolSkillSelection.outputContract.confidence >= 0.68
      ? toolSkillSelection.selected.workload
      : null;
  const envelopeWorkload = preferredWorkloadFromUnderstandingEnvelope(
    input.envelope,
    input.prompt,
  );
  const selectedWorkload =
    (selectorWorkload ?? envelopeWorkload) &&
    (!input.routeDecision?.selectedWorkload ||
      input.routeDecision.selectedWorkload === "mobile_chat_fast" ||
      input.routeDecision.selectedWorkload === "mobile_chat_balanced" ||
      input.routeDecision.selectedWorkload === "fast_route")
      ? (selectorWorkload ?? envelopeWorkload)
      : input.routeDecision?.selectedWorkload;

  return resolveAttachmentAwareSharedBrainWorkload({
    route: input.routeDecision?.route,
    selectedWorkload,
    attachmentContextUsed: input.attachmentContextUsed,
    hasVisionImage: input.hasVisionImage,
  });
}

type SharedBrainChatTaskInput = {
  currentTask: typeof tasks.$inferSelect;
  userId: string;
  requestId: string;
  prompt: string;
  canonicalTitle: string;
  understanding: Awaited<ReturnType<typeof buildTaskUnderstanding>>;
  planCode?: string | null;
  brainProfile?: unknown;
  ephemeralVision?: EphemeralVisionCarrier;
  providerStage?: ChatGenerationProviderStage;
  deferTransientFailure?: boolean;
  shouldAbort?: () => boolean | Promise<boolean>;
};

async function assertSharedBrainExecutionActive(
  input: SharedBrainChatTaskInput,
): Promise<void> {
  if (input.shouldAbort && (await input.shouldAbort())) {
    throw new AppError(
      503,
      "chat_generation_lease_lost",
      "Yanıt güvenli şekilde yeniden deneniyor.",
      {
        transient: true,
        retrySuggested: true,
        failureClass: "queue_lease_lost",
      },
    );
  }
}

async function processSharedBrainChatTask(
  app: FastifyInstance,
  input: SharedBrainChatTaskInput,
) {
  const resumedQueueAttempt =
    input.providerStage != null && input.currentTask.startedAt != null;
  let hydratedEphemeralVision: EphemeralVisionCarrier | undefined;
  try {
    /* Per-plan in-process rate check — C daemon token bucket, zero DB.
     * On limit: fail fast with rate_limited before expensive processing. */
    if (!resumedQueueAttempt && nlpDaemon.isAvailable()) {
      const rateResult = await nlpDaemon
        .rateCheck(input.userId, String(input.planCode ?? "free"))
        .catch(() => ({ allowed: true, retryAfterMs: 0 }));
      if (!rateResult.allowed) {
        throw new AppError(
          429,
          "rate_limited",
          "Çok fazla istek gönderildi. Lütfen bekleyin.",
          {
            retryAfterMs: rateResult.retryAfterMs,
          },
        );
      }
    }

    const runningTask = await markServerBrainTaskRunning(app, {
      taskId: input.currentTask.id,
      userId: input.userId,
    });
    await assertSharedBrainExecutionActive(input);
    if (!resumedQueueAttempt) {
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
          typeof (input.currentTask.payload as Record<string, unknown>)
            .source === "string"
            ? ((input.currentTask.payload as Record<string, unknown>)
                .source as string)
            : undefined,
        deviceId: input.currentTask.targetDeviceId,
        metadata:
          input.currentTask.payload &&
          typeof input.currentTask.payload === "object" &&
          !Array.isArray(input.currentTask.payload)
            ? getPayloadMetadata(
                input.currentTask.payload as Record<string, unknown>,
              )
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
    }
    const chatStreaming = extractChatStreamingMetadata(runningTask);
    const sessionArtifacts = chatStreaming?.sessionId
      ? await readSessionArtifactMemory(app, {
          userId: input.userId,
          sessionId: chatStreaming.sessionId,
        }).catch(() => [])
      : [];
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
    try {
      hydratedEphemeralVision = await resolveMediaInputVisionCarrier(
        app,
        input.userId,
        input.ephemeralVision,
      );
    } catch (error) {
      if (error instanceof AppError && error.statusCode >= 500) throw error;
      throw new AppError(
        410,
        "media_input_unavailable",
        "Görselin süresi dolmuş veya artık kullanılamıyor. Lütfen yeniden ekle.",
        {
          transient: false,
          retrySuggested: false,
          failureClass: "invalid_input",
        },
      );
    }
    const attachmentContext = await resolveTaskAttachmentContext(
      app,
      runningPayload,
      input.prompt,
      hydratedEphemeralVision,
    );

    /* İstemciden gelen yapılandırılmış ek dosya verilerini çıkar */
    const clientAttachments = extractClientAttachments(
      getPayloadMetadata(runningPayload),
    );
    const clientDocCtx =
      clientAttachments.length > 0
        ? await buildDocumentContextBlock(app, clientAttachments).catch(
            () => null,
          )
        : null;

    // Mobil metadata.selectedWorkload düz olarak gönderiyorsa routeDecision yokken de oku
    const metadataSelectedWorkload = (() => {
      const v = getPayloadMetadata(runningPayload).selectedWorkload;
      return typeof v === "string" && v.trim()
        ? (v.trim() as import("../brain/workloads.js").SharedBrainWorkload)
        : null;
    })();
    const effectiveRouteDecision: CommandRouteDecision | null =
      routeDecision ??
      (metadataSelectedWorkload
        ? ({
            selectedWorkload: metadataSelectedWorkload,
            route: "server_brain",
          } as CommandRouteDecision)
        : null);

    const selectedWorkload = resolveSharedBrainWorkloadForUnderstanding({
      routeDecision: effectiveRouteDecision,
      prompt: input.prompt,
      attachmentContextUsed:
        attachmentContext?.used === true || clientDocCtx?.hasContent === true,
      hasVisionImage:
        countDistinctEphemeralImages(hydratedEphemeralVision) > 0 ||
        Boolean(attachmentContext?.visionBlocks?.length),
      envelope: input.understanding.envelope,
    });
    /* İstemciden gelen yapılandırılmış ek dosya verilerini çıkar */
    // Prettier-ignore -- a source-level regression contract verifies this fast-path seam.
    const sourceImages = hostedImageSources(hydratedEphemeralVision);
    const imageEditIntent = isHostedImageEditIntent(input.prompt);
    const imageEditHasSessionImage = sessionArtifacts.some((artifact) => {
      const type = String(artifact.artifactType ?? artifact.type ?? "").toLowerCase();
      const family = String(artifact.contentFamily ?? "").toLowerCase();
      return type === "image" || family === "image";
    });
    const imageEditNeedsSource =
      imageEditIntent &&
      countDistinctEphemeralImages(hydratedEphemeralVision) === 0 &&
      !imageEditHasSessionImage;
    const imageGenerationRequested =
      isHostedImageGenerationRequest(input.prompt) ||
      imageEditIntent;

    if (imageGenerationRequested) {
      await assertSharedBrainExecutionActive(input);
      const startedAtMs = Date.now();
      let imageStreamSeq = 0;
      let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
      if (chatStreaming) {
        const hbSessionId = chatStreaming.sessionId;
        const hbMessageId = chatStreaming.assistantMessageId;
        const now = new Date().toISOString();
        await publishVolatileChatStreamEvent(app, {
          userId: input.userId,
          deviceId: runningTask.targetDeviceId,
          taskId: runningTask.id,
          sessionId: hbSessionId,
          messageId: hbMessageId,
          event: "message.delta",
          seq: ++imageStreamSeq,
          payload: {
            delta: "",
            assistantMessage: shapeAssistantMessagePayload({
              id: hbMessageId,
              role: "assistant",
              status: "running",
              content: "",
              taskId: runningTask.id,
              createdAt: runningTask.createdAt.toISOString(),
              updatedAt: now,
            }),
            streaming: {
              firstDeltaMs: null,
              reset: true,
            },
          },
        });
        heartbeatTimer = setInterval(() => {
          publishVolatileChatStreamEvent(app, {
            userId: input.userId,
            deviceId: runningTask.targetDeviceId,
            taskId: runningTask.id,
            sessionId: hbSessionId,
            messageId: hbMessageId,
            event: "heartbeat",
            seq: ++imageStreamSeq,
            payload: {
              status: "generating_image",
              elapsedMs: Date.now() - startedAtMs,
            },
          }).catch(() => undefined);
        }, 5_000);
      }

      let completedTask: Awaited<ReturnType<typeof completeServerBrainTask>>;
      try {
        completedTask = await completeServerBrainTask(app, {
          taskId: input.currentTask.id,
          userId: input.userId,
          chatSessionId: chatStreaming?.sessionId ?? null,
          sessionArtifacts,
          responseText: imageEditNeedsSource
            ? "Düzenlememi istediğin görseli yüklemen gerekiyor. Görseli ekleyip değiştirmemi istediğin kısmı tekrar yaz."
            : "",
          provider: "elyan_image",
          model: "elyan_image",
          route: "shared_brain",
          workload: selectedWorkload,
          latencyMs: Math.max(1, Date.now() - startedAtMs),
          promptTokens: 0,
          completionTokens: 0,
          totalTokens: 0,
          firstDeltaMs: null,
          completionLatencyMs: null,
          responseBytes: 0,
          attachmentContextUsed:
            attachmentContext?.used === true ||
            clientDocCtx?.hasContent === true,
          attachmentContextSource: attachmentContext?.source ?? null,
          sourceImages,
        });
      } finally {
        if (heartbeatTimer) clearInterval(heartbeatTimer);
      }
      if (!completedTask.completionTransitionOwned) {
        return;
      }

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

      const completedResultRecord = readRecord(
        (completedTask as { result?: unknown }).result,
      );
      const completedResultBlocks = Array.isArray(
        completedResultRecord?.assistantBlocks,
      )
        ? completedResultRecord.assistantBlocks
        : [];
      const completedResultText =
        typeof completedResultRecord?.text === "string" &&
        completedResultRecord.text.trim()
          ? completedResultRecord.text.trim()
          : completedResultBlocks.length > 0
            ? "Görsel hazır."
            : "Görsel şu anda üretilemedi. Lütfen biraz sonra tekrar dene.";

      void recordConversationExchangeLearning(app, {
        userId: input.userId,
        taskId: completedTask.id,
        userMessage: input.prompt,
        assistantReply: completedResultText,
        intent: input.understanding.intent.primaryIntent,
        requestId: input.requestId,
      }).catch(() => undefined);

      if (chatStreaming?.sessionId) {
        void persistRollingSummaryToSession(app, {
          userId: input.userId,
          sessionId: chatStreaming.sessionId,
          userMessage: input.prompt,
          assistantReply: completedResultText,
        }).catch(() => undefined);
      }

      if (chatStreaming) {
        const imageResultBlocks = normalizeAssistantMessageBlocks({
          blocks: completedResultBlocks,
        });
        // Prettier-ignore -- source-level regression contract verifies this render seam.
        const visibleText = imageResultBlocks.length > 0 ? "" : ensureUserFacingMessage(completedResultText);
        const finalBlocks = composeAssistantMessageBlocks({
          content: visibleText,
          blocks: imageResultBlocks,
        });
        const finalizedRows = await app.db
          .update(chatMessages)
          .set({
            status: "completed",
            content: visibleText,
            preview: compactMessagePreview(visibleText),
            metadata: sql`${chatMessages.metadata} || ${JSON.stringify(
              withAssistantBlocksMetadata(
                {},
                {
                  content: visibleText,
                  blocks: finalBlocks,
                },
              ),
            )}::jsonb`,
            updatedAt: new Date(),
          })
          .where(
            and(
              eq(chatMessages.id, chatStreaming.assistantMessageId),
              eq(chatMessages.sessionId, chatStreaming.sessionId),
              eq(chatMessages.userId, input.userId),
              sql`${chatMessages.status} <> 'completed'`,
            ),
          )
          .returning({ id: chatMessages.id });
        if (finalizedRows.length === 0) {
          return;
        }
        // Fence'i publish'ten önce kur: DB'de final yazıldı; bu andan itibaren
        // uçuştaki hiçbir volatile event bu mesajı temsil edemez.
        markAssistantMessageTerminal(chatStreaming.assistantMessageId);
        await publishPersistedChatStreamEvent(app, {
          userId: input.userId,
          deviceId: completedTask.targetDeviceId,
          taskId: completedTask.id,
          sessionId: chatStreaming.sessionId,
          messageId: chatStreaming.assistantMessageId,
          event: "message.completed",
          seq: ++imageStreamSeq,
          payload: {
            content: visibleText,
            blocks: finalBlocks,
            assistantMessage: shapeAssistantMessagePayload({
              id: chatStreaming.assistantMessageId,
              role: "assistant",
              status: "completed",
              content: visibleText,
              blocks: finalBlocks,
              taskId: completedTask.id,
              createdAt: completedTask.createdAt.toISOString(),
              updatedAt: completedTask.updatedAt.toISOString(),
            }),
            task: shapeTaskFeedItem(completedTask),
            usage: {
              inputTokens: 0,
              outputTokens: 0,
              totalTokens: 0,
            },
            streaming: {
              firstDeltaMs: null,
            },
          },
        });
      }
      return;
    }
    // Deterministik hedef komutu: "hedef oluştur/tamamla" model beklemeden
    // sunucuda uygulanır. Model yolu (turn envelope goal_ops) bunu dışlamaz;
    // bu yol flag'siz, her mesajda mikrosaniyede çalışan garanti halka.
    const goalCommand = detectGoalChatCommand(input.prompt);
    const goalCommandResult = goalCommand
      ? await executeGoalChatCommand(app, {
          userId: input.userId,
          sessionId: chatStreaming?.sessionId ?? null,
          taskId: runningTask.id,
          command: goalCommand,
        })
      : null;
    if (goalCommandResult && input.understanding.context) {
      // Modele yeni hedefi [GOAL] bloğu üzerinden duyur — cevap metni hedefi
      // isim ve adım sayısıyla referans alabilsin.
      input.understanding.context.activeGoal = goalCommandResult.goal;
    }
    const ackText = buildSharedBrainAckText(selectedWorkload);
    const ackTaskTrace = buildTaskTraceBlock({
      task: runningTask,
      assistantContent: ackText,
    });
    let streamSeq = 0;

    if (chatStreaming && !resumedQueueAttempt) {
      const now = new Date().toISOString();
      const visibleAckText = sanitizeAssistantVisibleText(ackText, {
        fallback: ackText,
      });
      const ackBlocks = composeAssistantMessageBlocks({
        content: visibleAckText,
        blocks: [ackTaskTrace],
        streaming: true,
      });
      if (visibleAckText) {
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
            },
          },
        });
      }
    }

    // Only sanitized visible content streams to chat; provider reasoning stays internal.
    // Akış ve nihai metin aynı politikayı paylaşır; aksi halde iki hat farklı
    // metin üretir ve cevap tamamlanınca kullanıcının gözü önünde değişir.
    // Grounding sinyali ancak inference metadata'sıyla kesinleştiği için akış
    // sırasında muhafazakâr (kapalı) başlar.
    const visibleTextPolicy: AssistantVisibleTextPolicy = {
      allowPublicProviderReferences: false,
    };
    let lastVisibleStreamingContent = resumedQueueAttempt
      ? ""
      : sanitizeAssistantVisibleText(ackText, {
          fallback: ackText,
          allowPublicProviderReferences:
            visibleTextPolicy.allowPublicProviderReferences,
        });

    // Session varsa önceki mesajları DB'den yükle — inference'ı bloke etmemek için 1.5s timeout
    const payloadConversation = extractSharedBrainConversation(runningPayload);
    let conversationHistory = payloadConversation;
    if (!payloadConversation?.length && chatStreaming?.sessionId) {
      const sessionIdForHistory = chatStreaming.sessionId;
      const historyPromise = listChatSessionMessages(app, {
        userId: input.userId,
        sessionId: sessionIdForHistory,
        limit: 20,
      })
        .then((page) =>
          page.messages
            .map((m) => {
              if (m.role !== "user" && m.role !== "assistant") {
                return null;
              }
              const content = conversationTextFromChatMessage({
                role: m.role,
                content: m.content,
                blocks: m.blocks,
              });
              return content
                ? { role: m.role as "user" | "assistant", content }
                : null;
            })
            .filter(
              (m): m is { role: "user" | "assistant"; content: string } =>
                m != null,
            )
            .slice(-16),
        )
        .catch(() => null);
      const timeoutPromise = new Promise<null>((resolve) =>
        setTimeout(() => resolve(null), 1_500),
      );
      const result = await Promise.race([historyPromise, timeoutPromise]);
      if (result && result.length > 0) {
        conversationHistory = result;
      }
    }

    // Inference sırasında heartbeat — mobil "hâlâ çalışıyor" bilgisi alır, asma yapmaz
    const inferenceStartedAt = Date.now();
    let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
    if (chatStreaming) {
      const hbSessionId = chatStreaming.sessionId;
      const hbMessageId = chatStreaming.assistantMessageId;
      heartbeatTimer = setInterval(() => {
        publishVolatileChatStreamEvent(app, {
          userId: input.userId,
          deviceId: runningTask.targetDeviceId,
          taskId: runningTask.id,
          sessionId: hbSessionId,
          messageId: hbMessageId,
          event: "heartbeat",
          seq: ++streamSeq,
          payload: {
            status: "thinking",
            elapsedMs: Date.now() - inferenceStartedAt,
          },
        }).catch(() => undefined);
      }, 5_000);
    }

    const endInferenceStage = startStage("inference_total");
    const inferenceVision = hydratedEphemeralVision;
    let queuedTaskAbortCached = false;
    let queuedTaskAbortCheckedAt = 0;
    const shouldAbortQueuedTask = input.providerStage
      ? async () => {
          if (input.shouldAbort && (await input.shouldAbort())) {
            return true;
          }
          if (queuedTaskAbortCached) {
            return true;
          }
          const now = Date.now();
          if (now - queuedTaskAbortCheckedAt < 250) {
            return false;
          }
          queuedTaskAbortCheckedAt = now;
          const latestTask = await getTaskById(app, runningTask.id);
          queuedTaskAbortCached =
            !latestTask ||
            latestTask.userId !== input.userId ||
            isTerminalTaskStatus(latestTask.status);
          return queuedTaskAbortCached;
        }
      : undefined;
    const inference = await generateGovernedSharedBrainReply(app, {
      userId: input.userId,
      taskId: runningTask.id,
      prompt: input.prompt,
      title: input.canonicalTitle,
      conversation: conversationHistory,
      attachmentContext,
      clientAttachments:
        clientAttachments.length > 0 ? clientAttachments : null,
      requestMetadata:
        sessionArtifacts.length > 0
          ? { ...getPayloadMetadata(runningPayload), sessionArtifacts }
          : getPayloadMetadata(runningPayload),
      route: "shared_brain",
      routeDecision,
      workload: selectedWorkload,
      meteringSurface: "chat",
      planCode: input.planCode,
      understandingContext: input.understanding.context,
      brainProfile: input.brainProfile,
      ...(input.providerStage
        ? {
            providerAllowlist: [
              chatGenerationProviderForStage(input.providerStage),
            ],
            loadSheddingConcurrencyOverride:
              input.providerStage === "primary"
                ? getChatGenerationQueueLimits(app)
                    .primaryGlobalConcurrency
                : getChatGenerationQueueLimits(app)
                    .fallbackGlobalConcurrency,
          }
        : {}),
      shouldAbort: shouldAbortQueuedTask,
      ephemeralVision: inferenceVision,
      onDelta: chatStreaming
        ? async (delta) => {
            if (shouldAbortQueuedTask && (await shouldAbortQueuedTask())) {
              throw new AppError(
                409,
                "task_canceled",
                "Görev iptal edildi.",
                { transient: false, retrySuggested: false },
              );
            }
            // Provider reasoning is internal-only; only content can stream to chat.
            const incomingVisibleContent = sanitizeAssistantVisibleText(
              delta.content,
              {
                fallback: "",
                allowPublicProviderReferences:
                  visibleTextPolicy.allowPublicProviderReferences,
              },
            );
            const nonEchoVisibleContent = incomingVisibleContent
              ? stripPromptEchoFromAssistantText({
                  prompt: input.prompt,
                  responseText: incomingVisibleContent,
                  policy: visibleTextPolicy,
                })
              : "";
            const visibleContent = ensureUserFacingMessage(
              nonEchoVisibleContent || lastVisibleStreamingContent,
            );
            const contentChanged =
              visibleContent !== lastVisibleStreamingContent;
            if (!contentChanged) {
              return;
            }
            // Monotonic delta rule: only emit an append-delta when the new
            // sanitized snapshot EXTENDS what was already streamed. The
            // sanitizer can legitimately shrink/reshape the snapshot mid-stream
            // (a line becomes "internal-looking" only once it completes, or a
            // provider retry restarts the stream). Re-sending the full snapshot
            // as a delta made mobile append it after the old text — the
            // "…User- LanguageHere's a thinking process:…" duplication. On
            // divergence we send delta:"" and let assistantMessage.content
            // carry the authoritative snapshot instead.
            const visibleDelta = resumedQueueAttempt
              ? ""
              : contentChanged
                ? visibleContent.startsWith(lastVisibleStreamingContent)
                  ? visibleContent.slice(lastVisibleStreamingContent.length)
                  : ""
                : "";
            if (contentChanged) {
              lastVisibleStreamingContent = visibleContent;
            }
            const now = new Date().toISOString();
            const streamingBlocks = composeAssistantMessageBlocks({
              content: visibleContent,
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
                delta: visibleDelta,
                ...(streamingBlocks.length > 0
                  ? { blocks: streamingBlocks }
                  : {}),
                assistantMessage: shapeAssistantMessagePayload({
                  id: chatStreaming.assistantMessageId,
                  role: "assistant",
                  status: "running",
                  content: visibleContent,
                  ...(streamingBlocks.length > 0
                    ? { blocks: streamingBlocks }
                    : {}),
                  taskId: runningTask.id,
                  createdAt: runningTask.createdAt.toISOString(),
                  updatedAt: now,
                }),
                streaming: {
                  firstDeltaMs: delta.firstDeltaMs,
                },
              },
            });
          }
        : undefined,
    }).finally(() => {
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      if (inferenceVision !== input.ephemeralVision) {
        clearEphemeralVisionCarrier(inferenceVision);
      }
    });
    await assertSharedBrainExecutionActive(input);
    endInferenceStage();
    // Grounding sonucu ancak burada kesinleşir. Politikayı güncelle ki nihai
    // metin ile akış metni aynı kurallardan geçsin.
    visibleTextPolicy.allowPublicProviderReferences =
      inference.metadata.webGroundingUsed === true ||
      Number(inference.metadata.webSourceCount ?? 0) > 0;
    const agentRunState = readAgentRunState(inference.metadata);
    if (agentRunState && agentRunState !== "completed") {
      app.log.info?.(
        { taskId: runningTask.id, agentRunState },
        "task completion deferred until agent verification passes",
      );
      return;
    }
    const completedTask = await completeServerBrainTask(app, {
      taskId: input.currentTask.id,
      userId: input.userId,
      chatSessionId: chatStreaming?.sessionId ?? null,
      sessionArtifacts,
      responseText: resolveNonEchoAssistantText({
        prompt: input.prompt,
        responseText: inference.text,
          policy: visibleTextPolicy,
      }),
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
    if (!completedTask.completionTransitionOwned) {
      return;
    }
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
      assistantReply: resolveNonEchoAssistantText({
        prompt: input.prompt,
        responseText: inference.text,
          policy: visibleTextPolicy,
      }),
      intent: input.understanding.intent.primaryIntent,
      requestId: input.requestId,
      volatileExternalData:
        typeof inference.metadata.freshDataDomain === "string" &&
        !["general", "url_review"].includes(inference.metadata.freshDataDomain),
    }).catch(() => undefined);
    // Rolling summary'yi session'a yaz (fire-and-forget)
    if (chatStreaming?.sessionId) {
      void persistRollingSummaryToSession(app, {
        userId: input.userId,
        sessionId: chatStreaming.sessionId,
        userMessage: input.prompt,
        assistantReply: resolveNonEchoAssistantText({
          prompt: input.prompt,
          responseText: inference.text,
            policy: visibleTextPolicy,
        }),
      }).catch(() => undefined);
    }
    if (chatStreaming) {
      const completionMetadata = readServerBrainCompletionMetadata(
        inference.metadata,
      );
      const completedResultRecord = readRecord(
        (completedTask as { result?: unknown }).result,
      );
      const completedResultText =
        typeof completedResultRecord?.text === "string" &&
        completedResultRecord.text.trim()
          ? completedResultRecord.text.trim()
          : inference.text;
      const taskTrace = buildTaskTraceBlock({
        task: completedTask,
        assistantContent: completedResultText,
      });
      const completedResultBlocks = Array.isArray(
        completedResultRecord?.assistantBlocks,
      )
        ? completedResultRecord.assistantBlocks
        : completionMetadata.assistantBlocks;
      const inferenceResolved = resolveCompletionAssistantBlocks({
        responseText: completedResultText,
        assistantBlocks: completedResultBlocks,
        prompt: input.prompt,
        selectedWorkload,
      });
      const inferenceBlocks = inferenceResolved.blocks;
      const goalProgressBlocks = inferenceBlocks.filter(
        (block) => readRecord(block)?.type === "goal_progress",
      );
      const visibleInferenceBlocks = inferenceBlocks.filter(
        (block) => readRecord(block)?.type !== "goal_progress",
      );
      const unifiedTaskTrace = enrichTaskTraceWithAgentPlan({
        trace: taskTrace,
        agentPlan: inference.metadata.agentPlan,
        toolFlow: completionMetadata.toolFlow,
        approval: completionMetadata.connectorWriteApproval,
      });
      // Use the cleaned text everywhere so the inline prose doesn't repeat a
      // table/code/document that a widget block is already rendering.
      // TEK KAPI: yetenek etiketi ("Klasör ağacı", "Belge okuma") cevap olarak
      // teslim edilemez. Masaüstü tarafında bu metin onlarca yoldan üretilebiliyor;
      // denetim mobilin okuduğu mesajın MUTLAKA geçtiği bu sınırda yapılır.
      const visibleText = ensureUserFacingMessage(
        inferenceResolved.text || completedResultText,
      );
      // Deterministik hedef bloğu: model kendi goal_progress bloğunu ürettiyse
      // duplike etme — aynı goalId için tek kart.
      const goalBlock =
        goalCommandResult &&
        !inferenceBlocks.some(
          (block) =>
            block &&
            typeof block === "object" &&
            (block as Record<string, unknown>).type === "goal_progress" &&
            (block as Record<string, unknown>).goalId ===
              goalCommandResult.block.goalId,
        )
          ? [goalCommandResult.block]
          : [];
      const finalBlocks = composeAssistantMessageBlocks({
        content: visibleText,
        blocks: [unifiedTaskTrace, ...visibleInferenceBlocks],
      });
      const revision = buildAssistantRevisionMetadata({
        finalContent: visibleText,
        streamedContent: lastVisibleStreamingContent,
        transientContent: ackText,
      });
      void applyGoalProgressBlocks(app, {
        userId: input.userId,
        blocks: [...goalBlock, ...goalProgressBlocks],
      });
      // Persist final blocks + cleaned content to the chat_messages row so a
      // later GET /messages (user leaves and reopens) returns the same
      // widget-only view, not the duplicated markdown.
      const finalizedRows = await app.db
        .update(chatMessages)
        .set({
          status: "completed",
          content: visibleText,
          preview: compactMessagePreview(visibleText),
          metadata: sql`${chatMessages.metadata} || ${JSON.stringify(
            withAssistantBlocksMetadata(
              { revision },
              {
                content: visibleText,
                blocks: finalBlocks,
              },
            ),
          )}::jsonb`,
          updatedAt: new Date(),
        })
        .where(
          and(
            eq(chatMessages.id, chatStreaming.assistantMessageId),
            eq(chatMessages.sessionId, chatStreaming.sessionId),
            eq(chatMessages.userId, input.userId),
            sql`${chatMessages.status} <> 'completed'`,
          ),
        )
        .returning({ id: chatMessages.id });
      if (finalizedRows.length === 0) {
        return;
      }
      // Fence'i publish'ten önce kur: DB'de final yazıldı; bu andan itibaren
      // uçuştaki hiçbir volatile event bu mesajı temsil edemez.
      markAssistantMessageTerminal(chatStreaming.assistantMessageId);
      await publishPersistedChatStreamEvent(app, {
        userId: input.userId,
        deviceId: completedTask.targetDeviceId,
        taskId: completedTask.id,
        sessionId: chatStreaming.sessionId,
        messageId: chatStreaming.assistantMessageId,
        event: "message.completed",
        seq: ++streamSeq,
        payload: {
          content: visibleText,
          blocks: finalBlocks,
          // Nihai metin akışta gösterilenden farklıysa bunu sessizce değiştirme:
          // istemci "cevap düzeltildi" göstergesi sunabilsin. Fark kaçınılmaz
          // olabilir (düzeltici, yarım yanıt tamamlama, blok çıkarımı ancak
          // metin bitince bilinir) ama sessiz olmamalı.
          revised: revision.revised,
          ...(revision.revised
            ? { previousContent: revision.previousContent }
            : {}),
          assistantMessage: shapeAssistantMessagePayload({
            id: chatStreaming.assistantMessageId,
            role: "assistant",
            status: "completed",
            content: visibleText,
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
          },
        },
      });
    }
  } catch (error) {
    const latestTask = await getTaskById(app, input.currentTask.id);
    if (!latestTask) {
      return;
    }
    if (isChatGenerationSettled(latestTask.status)) {
      if (latestTask.status === "completed" && input.deferTransientFailure) {
        const result = readRecord(latestTask.result);
        try {
          await syncChatTaskLifecycle(app, {
            originalTask: latestTask,
            updatedTask: latestTask,
            message: typeof result?.text === "string" ? result.text : undefined,
          });
        } catch {
          // Keep the BullMQ job retryable until the durable assistant row has
          // caught up with the already-owned terminal task claim.
          throw new AppError(
            503,
            "chat_terminal_sync_pending",
            "Yanıt güvenli şekilde tamamlanıyor.",
            {
              transient: true,
              retrySuggested: true,
              failureClass: "queue_unavailable",
            },
          );
        }
      }
      return;
    }
    if (input.deferTransientFailure && isTransientSharedBrainFailure(error)) {
      throw error;
    }
    await finalizeSharedBrainChatFailure(app, input, error);
  } finally {
    if (hydratedEphemeralVision !== input.ephemeralVision) {
      clearEphemeralVisionCarrier(hydratedEphemeralVision);
    }
    clearEphemeralVisionCarrier(input.ephemeralVision);
  }
}

function isTransientSharedBrainFailure(error: unknown): boolean {
  if (error instanceof AppError) {
    const details = readRecord(error.details);
    if (
      details?.retrySuggested === false ||
      details?.transient === false
    ) {
      return false;
    }
    return (
      error.code === "server_brain_unavailable" ||
      error.code === "rate_limited" ||
      error.statusCode === 429 ||
      error.statusCode >= 500 ||
      details?.transient === true
    );
  }
  return (
    error instanceof TypeError ||
    (error instanceof DOMException && error.name === "AbortError")
  );
}

async function finalizeSharedBrainChatFailure(
  app: FastifyInstance,
  input: Pick<
    SharedBrainChatTaskInput,
    "currentTask" | "userId" | "requestId"
  >,
  error: unknown,
) {
  if (await completeSafeChatContinuityFallback(app, input, error)) {
    return;
  }
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
    .where(
      and(
        eq(tasks.id, input.currentTask.id),
        eq(tasks.userId, input.userId),
        inArray(tasks.status, ["queued", "planning", "running"]),
      ),
    )
    .returning();
  if (rows.length === 0) {
    const currentTask = await getTaskById(app, input.currentTask.id);
    await releaseChatGenerationAdmission(
      app,
      currentTask?.id ?? input.currentTask.id,
    );
    return;
  }
  const failedTask = rows[0];
  await releaseChatGenerationAdmission(app, failedTask.id);
  await insertTaskEvent(app, {
    taskId: failedTask.id,
    userId: failedTask.userId,
    status: "failed",
    message: fallbackMessage,
    payload: {
      route: "shared_brain",
      failureClass:
        readRecord(error instanceof AppError ? error.details : null)
          ?.failureClass ?? "unavailable",
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
  await releaseMediaInputsFromMetadata(
    app,
    input.userId,
    getPayloadMetadata(readRecord(input.currentTask.payload) ?? {}),
  ).catch(() => undefined);
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
          error instanceof AppError
            ? readRecord(error.details)?.retrySuggested !== false
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
      errorCode:
        error instanceof AppError
          ? error.code
          : error instanceof Error
            ? error.name
            : "unknown",
    },
    "shared brain chat dispatch failed asynchronously",
  );
}

async function completeSafeChatContinuityFallback(
  app: FastifyInstance,
  input: Pick<
    SharedBrainChatTaskInput,
    "currentTask" | "userId" | "requestId"
  >,
  error: unknown,
): Promise<boolean> {
  const task = (await getTaskById(app, input.currentTask.id)) ?? input.currentTask;
  if (task.userId !== input.userId || isChatGenerationSettled(task.status)) {
    return false;
  }
  const payload = readRecord(task.payload) ?? {};
  const metadata = getPayloadMetadata(payload);
  const routeDecision = extractRouteDecision(payload);
  const understanding = readRecord(metadata.understanding);
  const details = readRecord(error instanceof AppError ? error.details : null);
  const errorCode =
    error instanceof AppError ? error.code : "server_brain_unavailable";
  const workload = String(
    routeDecision?.selectedWorkload ?? metadata.selectedWorkload ?? "mobile_chat_fast",
  );
  const responseText = resolveSafeChatContinuityReply({
    prompt: getTaskPrompt(payload),
    channel: metadata.channel,
    route: routeDecision?.route,
    mode: routeDecision?.mode,
    privacyClass: routeDecision?.privacyClass,
    requiresApproval: routeDecision?.requiresApproval,
    intent: routeDecision?.intent,
    requiredRuntime: routeDecision?.requiredRuntime,
    shouldAskClarification: routeDecision?.shouldAskClarification,
    failClosedReason: routeDecision?.failClosedReason,
    workload,
    taskRoute: routeDecision?.taskRoute,
    routeCapabilities: routeDecision?.capabilities,
    requestedCapabilities: task.requestedCapabilities,
    metadata,
    understandingEnvelope: understanding?.envelope,
    errorCode,
    failureClass: details?.failureClass,
  });
  if (!responseText || extractChatStreamingMetadata(task) == null) {
    return false;
  }

  const runningTask = await markServerBrainTaskRunning(app, {
    taskId: task.id,
    userId: input.userId,
  });
  const completedTask = await completeServerBrainTask(app, {
    taskId: runningTask.id,
    userId: input.userId,
    responseText,
    provider: "backend_gate",
    model: "elyan.continuity_fallback",
    route: "shared_brain",
    workload,
    latencyMs: 0,
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    fallbackUsed: true,
    fallbackState: "continuity_response",
    responseBytes: Buffer.byteLength(responseText, "utf8"),
    validationStatus: "degraded_continuity",
    qualityPolicyApplied: true,
    evidenceSufficiency: "insufficient",
    clarificationRequested: true,
    dataQualityWarnings: ["provider_continuity_fallback"],
  });
  if (completedTask.status === "completed") {
    await syncChatTaskLifecycle(app, {
      originalTask: runningTask,
      updatedTask: completedTask,
      message: responseText,
    });
  }
  void recordTaskFailureLearning(app, {
    userId: task.userId,
    accountId: task.userId,
    taskId: task.id,
    errorCode: "provider_continuity_fallback",
    capabilities: [],
    requestId: input.requestId,
  }).catch(() => undefined);
  app.log.warn(
    {
      taskId: task.id,
      requestId: input.requestId,
      errorCode,
      failureClass: String(details?.failureClass ?? "unavailable"),
      outcome: "continuity_completed",
    },
    "shared brain provider exhaustion completed with safe continuity",
  );
  return true;
}

export type QueuedSharedBrainChatTaskSnapshot = {
  task: typeof tasks.$inferSelect;
  prompt: string;
  workload: SharedBrainWorkload;
  requestId: string;
  understanding: UserUnderstandingResult;
  terminal: boolean;
};

export async function listRecoverableSharedBrainChatTasks(
  app: FastifyInstance,
  input: { limit: number },
): Promise<
  Array<{
    taskId: string;
    userId: string;
    createdAt: Date;
    workload: SharedBrainWorkload;
  }>
> {
  const limit = Math.max(1, Math.min(10_000, Math.trunc(input.limit)));
  const rows = await app.db
    .select({
      id: tasks.id,
      userId: tasks.userId,
      createdAt: tasks.createdAt,
      payload: tasks.payload,
    })
    .from(tasks)
    .where(
      and(
        inArray(tasks.status, ["queued", "planning", "running"]),
        sql`${tasks.payload}->'metadata'->'chatGeneration'->>'queued' = 'true'`,
      ),
    )
    .orderBy(asc(tasks.createdAt))
    .limit(limit);
  return rows.map((row) => {
    const metadata = getPayloadMetadata(readRecord(row.payload) ?? {});
    const selectedWorkload =
      typeof metadata.selectedWorkload === "string" &&
      sharedBrainWorkloadValues.includes(
        metadata.selectedWorkload as SharedBrainWorkload,
      )
        ? (metadata.selectedWorkload as SharedBrainWorkload)
        : "mobile_chat_fast";
    return {
      taskId: row.id,
      userId: row.userId,
      createdAt: row.createdAt,
      workload: selectedWorkload,
    };
  });
}

function readPersistedTaskUnderstanding(
  payload: Record<string, unknown>,
): UserUnderstandingResult | null {
  const metadata = getPayloadMetadata(payload);
  const understanding = readRecord(metadata.understanding);
  const intent = readRecord(understanding?.intent);
  const context = readRecord(understanding?.context);
  const routingHints = readRecord(understanding?.routingHints);
  if (!intent || !context || !routingHints) {
    return null;
  }
  const envelopeResult = understandingEnvelopeSchema.safeParse(
    understanding?.envelope,
  );
  const envelope = envelopeResult.success ? envelopeResult.data : undefined;
  return {
    intent: intent as UserUnderstandingResult["intent"],
    context: context as UserUnderstandingResult["context"],
    routingHints: routingHints as UserUnderstandingResult["routingHints"],
    ...(envelope
      ? {
          envelope,
          envelopeSource:
            typeof understanding?.envelopeSource === "string"
              ? (understanding.envelopeSource as UserUnderstandingResult["envelopeSource"])
              : envelope.source,
          envelopeConfidence:
            typeof understanding?.envelopeConfidence === "number"
              ? understanding.envelopeConfidence
              : envelope.confidence,
        }
      : {}),
  };
}

export async function getQueuedSharedBrainChatTask(
  app: FastifyInstance,
  input: { taskId: string; userId: string },
): Promise<QueuedSharedBrainChatTaskSnapshot | null> {
  const row = await getTaskById(app, input.taskId);
  if (!row || row.userId !== input.userId) {
    return null;
  }
  const hydratedPayload = await hydrateTaskJsonValue(
    app,
    row.payload,
    row.payloadBlobId,
    {
      userId: row.userId,
      ownerType: "task",
      ownerId: row.id,
    },
  );
  const payload = readRecord(hydratedPayload) ?? {};
  const task = { ...row, payload };
  const prompt = getTaskPrompt(payload);
  const metadata = getPayloadMetadata(payload);
  const routeDecision = extractRouteDecision(payload);
  const persistedUnderstanding = readPersistedTaskUnderstanding(payload);
  const understanding =
    persistedUnderstanding ??
    (await buildTaskUnderstanding(app, {
      userId: row.userId,
      accountId: row.userId,
      taskId: row.id,
      title: row.title,
      message: prompt,
      routeContext: "tasks.chat_queue",
      source:
        typeof payload.source === "string" ? payload.source : undefined,
      deviceId: row.targetDeviceId,
      metadata,
    }).catch(() =>
      emptyUnderstanding({
        userId: row.userId,
        accountId: row.userId,
        taskId: row.id,
        title: row.title,
        message: prompt,
        routeContext: "tasks.chat_queue",
        source:
          typeof payload.source === "string" ? payload.source : undefined,
        deviceId: row.targetDeviceId,
        metadata,
      }),
    ));
  const workload = resolveSharedBrainWorkloadForUnderstanding({
    routeDecision,
    prompt,
    envelope: understanding.envelope,
  });
  const chatGeneration = readRecord(metadata.chatGeneration);
  const requestId =
    typeof chatGeneration?.requestId === "string" &&
    chatGeneration.requestId.trim()
      ? chatGeneration.requestId.trim()
      : row.id;

  return {
    task,
    prompt,
    workload,
    requestId,
    understanding,
    terminal: isChatGenerationSettled(row.status),
  };
}

export async function processQueuedSharedBrainChatTask(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId: string;
    providerStage: ChatGenerationProviderStage;
    shouldAbort?: () => boolean | Promise<boolean>;
  },
) {
  const snapshot = await getQueuedSharedBrainChatTask(app, input);
  if (!snapshot) {
    return { processed: false, reason: "terminal_or_missing" as const };
  }
  if (snapshot.terminal) {
    // A worker can crash after the task's terminal CAS but before the chat row
    // is finalized. A BullMQ redelivery repairs that durable handoff without
    // rerunning inference or producing a second assistant answer.
    if (snapshot.task.status === "completed") {
      const result = readRecord(snapshot.task.result);
      await syncChatTaskLifecycle(app, {
        originalTask: snapshot.task,
        updatedTask: snapshot.task,
        message: typeof result?.text === "string" ? result.text : undefined,
      });
    }
    return { processed: false, reason: "terminal_or_missing" as const };
  }
  const usageAccess = await getUserUsageAccessTruth(app.db, input.userId);
  const queuedPayload = readRecord(snapshot.task.payload) ?? {};
  const queuedVision = restoreQueuedEphemeralVisionCarrier(
    getPayloadMetadata(queuedPayload),
  );
  await processSharedBrainChatTask(app, {
    currentTask: snapshot.task,
    userId: input.userId,
    requestId: snapshot.requestId,
    prompt: snapshot.prompt,
    canonicalTitle: snapshot.task.title,
    understanding: snapshot.understanding,
    planCode: usageAccess.planCode,
    brainProfile: usageAccess.brainProfile,
    ephemeralVision: queuedVision,
    providerStage: input.providerStage,
    deferTransientFailure: true,
    shouldAbort: input.shouldAbort,
  });
  return { processed: true, reason: "completed" as const };
}

export async function markQueuedSharedBrainChatPhase(
  app: FastifyInstance,
  input: {
    taskId: string;
    userId: string;
    phase: "queued" | "retrying" | "provider_failover";
    message: string;
  },
) {
  const originalTask = await getTaskById(app, input.taskId);
  if (
    !originalTask ||
    originalTask.userId !== input.userId ||
    isChatGenerationSettled(originalTask.status)
  ) {
    return originalTask;
  }
  // "queued" fazı lease alamayan (yani BAŞKA bir worker'ın aktif işlediği)
  // job'dan gelir; running bir görevi geri "queued" + "Yanıt hazırlanıyor."a
  // çevirmesi, stream'i süren worker'ın final cevabıyla yarışan eski ACK
  // snapshot'ının kaynağıdır. Running görevi yalnız görevi sahiplenen
  // retry/failover fazları resetleyebilir.
  const allowedStatuses: Array<typeof originalTask.status> =
    input.phase === "queued"
      ? ["queued", "planning"]
      : ["queued", "planning", "running"];
  const rows = await app.db
    .update(tasks)
    .set({
      status: "queued",
      summary: input.message,
      error: null,
      updatedAt: new Date(),
    })
    .where(
      and(
        eq(tasks.id, input.taskId),
        eq(tasks.userId, input.userId),
        inArray(tasks.status, allowedStatuses),
      ),
    )
    .returning();
  const updatedTask = rows[0];
  if (!updatedTask) {
    return originalTask;
  }
  await insertTaskEvent(app, {
    taskId: updatedTask.id,
    userId: updatedTask.userId,
    status: "queued",
    message: input.message,
    payload: {
      route: "shared_brain",
      generationPhase: input.phase,
    },
  });
  await publishTaskEvent(app, updatedTask, "task.updated", {
    task: shapeTaskFeedItem(updatedTask),
  });
  await syncChatTaskLifecycle(app, {
    originalTask,
    updatedTask,
    message: input.message,
  });
  return updatedTask;
}

export async function failQueuedSharedBrainChatTask(
  app: FastifyInstance,
  input: { taskId: string; userId: string; error: unknown },
) {
  const snapshot = await getQueuedSharedBrainChatTask(app, input);
  if (!snapshot || snapshot.terminal) {
    return;
  }
  await finalizeSharedBrainChatFailure(
    app,
    {
      currentTask: snapshot.task,
      userId: input.userId,
      requestId: snapshot.requestId,
    },
    input.error,
  );
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
    /** Internal callers may pass capabilities already resolved against grants. */
    requestedCapabilitiesResolved?: boolean;
    ipAddress?: string;
    userAgent?: string;
    requestId: string;
    idempotencyKey?: string;
    ephemeralVision?: EphemeralVisionCarrier;
    onTaskReady?: TaskReadyCallback;
  },
) {
  const prompt = getTaskPrompt(input.payload);
  const payloadMetadata = getPayloadMetadata(input.payload);
  bindAuthorizedMediaInputRefs(payloadMetadata, input.ephemeralVision);
  const [usageAccess, remoteMcpResolution] = await Promise.all([
    getUserUsageAccessTruth(app.db, input.userId),
    input.requestedCapabilitiesResolved
      ? Promise.resolve({
          requestedCapabilities: input.requestedCapabilities,
          selection: normalizeRemoteMcpSelectionMetadata(
            payloadMetadata.remoteMcpSelection,
          ),
        })
      : resolveRemoteMcpRequest(app, {
          userId: input.userId,
          prompt,
          requestedCapabilities: input.requestedCapabilities,
        }),
  ]);
  const effectiveRequestedCapabilities =
    remoteMcpResolution.requestedCapabilities;
  const remoteMcpSelection = remoteMcpResolution.selection;
  const remoteMcpRequested = effectiveRequestedCapabilities.includes(
    "mcp_call_tool",
  );
  const extractedRouteDecision = extractRouteDecision(input.payload);
  const extractedRouteIsStale = isRemoteMcpRouteDecisionStale(
    extractedRouteDecision,
    effectiveRequestedCapabilities,
  );
  const routeDecision =
    (!extractedRouteIsStale ? extractedRouteDecision : null) ??
    (await decideCommandRoute(app, {
      userId: input.userId,
      message: prompt,
      source:
        typeof input.payload.source === "string" &&
        input.payload.source === "desktop"
          ? "desktop"
          : "mobile",
      activeChatSessionId:
        typeof payloadMetadata.chat === "object" &&
        payloadMetadata.chat !== null
          ? String(
              (payloadMetadata.chat as Record<string, unknown>).sessionId ?? "",
            )
          : undefined,
      selectedDeviceId: input.targetDeviceId,
      metadata: payloadMetadata,
      desktopAllowed: canUseDesktopConnections(usageAccess.planCode),
      requestedCapabilities: effectiveRequestedCapabilities,
      bootstrap: undefined,
      brainProfile: usageAccess.brainProfile,
      quota: undefined,
    }));
  const routeCapabilities = routeDecision?.capabilities?.length
    ? routeDecision.capabilities
    : effectiveRequestedCapabilities;
  const routeOrigin = normalizeRouteOrigin(input.payload.source);
  const routeSelectedTargetDeviceId =
    input.requestedTargetDeviceId ?? input.targetDeviceId;
  const needsDesktop = resolveTaskRouteNeedsDesktop(routeDecision);
  const routeBlocked =
    needsDesktop &&
    (routeDecision.route === "pairing_required" ||
      routeDecision.route === "unavailable");
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
  const targetDevice = needsDesktop
    ? routeBlocked
      ? (pendingDesktopTarget ??
        (await resolveCommandTarget(app, input.userId, undefined, "chat")))
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
  const selectedDesktopOnline = isSharedBrain
    ? true
    : Boolean(targetDevice.device.isOnline);
  let chatDispatchPolicy = resolveSharedBrainChatDispatchPolicy(app, {
    isSharedBrain,
    useFastSharedBrainFlow,
    ephemeralVision: input.ephemeralVision,
  });
  if (chatDispatchPolicy === "reject_legacy_inline_vision") {
    input.ephemeralVision = await materializeLegacyVisionForDurableQueue(
      app,
      input.userId,
      input.ephemeralVision,
    );
    bindAuthorizedMediaInputRefs(payloadMetadata, input.ephemeralVision);
    chatDispatchPolicy = resolveSharedBrainChatDispatchPolicy(app, {
      isSharedBrain,
      useFastSharedBrainFlow,
      ephemeralVision: input.ephemeralVision,
    });
  }
  if (chatDispatchPolicy === "reject_queue_unavailable") {
    clearEphemeralVisionCarrier(input.ephemeralVision);
    throw createChatQueueUnavailableError();
  }
  const useDurableChatQueue = chatDispatchPolicy === "durable_queue";
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
    const requeued =
      isSharedBrain &&
      useFastSharedBrainFlow &&
      (["queued", "planning", "running"] as TaskStatus[]).includes(
        existingTask.status,
      ) &&
      isDurableChatGenerationTask(existingTask)
        ? await enqueueSharedBrainChatTask(app, {
            taskId: existingTask.id,
            userId: input.userId,
          })
        : false;
    clearEphemeralVisionCarrier(input.ephemeralVision);
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
      dispatched: requeued,
      reused: true,
      selectedDesktopOnline,
      renderRecipe: null,
    };
  }

  const isDesktopRoute =
    routeDecision.route === "desktop_runtime" ||
    routeDecision.taskRoute?.operationalRoute === "desktop_runtime";
  const dispatchOptimization = buildQuantumDispatchOptimization({
    brainProfile: usageAccess.brainProfile,
    isDesktopRoute,
  });
  const responsiveExecution = buildQuantumResponsiveExecutionPolicy({
    brainProfile: usageAccess.brainProfile,
    isDesktopRoute,
  });
  const livenessGuard = buildQuantumLivenessGuardPolicy({
    brainProfile: usageAccess.brainProfile,
    isDesktopRoute,
  });
  const useDirectDesktopFastPath = isDeterministicDesktopFastWorkOrder(
    routeDecision,
    prompt,
  );
  const understandingInput = {
    userId: input.userId,
    accountId: input.userId,
    title: canonicalTitle,
    message: prompt,
    routeContext: "tasks.create" as const,
    source:
      typeof input.payload.source === "string"
        ? input.payload.source
        : undefined,
    deviceId: targetDeviceId,
    metadata: {
      ...payloadMetadata,
      routeDecision,
      requestId: input.requestId,
      ...(remoteMcpSelection ? { remoteMcpSelection } : {}),
    },
  };
  const understanding = useDirectDesktopFastPath
    ? emptyUnderstanding(understandingInput)
    : await buildTaskUnderstanding(app, understandingInput).catch(() =>
        emptyUnderstanding(understandingInput),
      );
  const desktopWorkOrder = isDesktopRoute
    ? buildDesktopWorkOrder({
        message: prompt,
        title: canonicalTitle,
        routeDecision,
        requestedCapabilities: routeCapabilities,
        remoteMcpSelection: remoteMcpSelection ?? undefined,
        dispatchOptimization: dispatchOptimization ?? undefined,
        responsiveExecution: responsiveExecution ?? undefined,
        livenessGuard: livenessGuard ?? undefined,
        understandingEnvelope: understanding.envelope,
        inputRefs: (
          Array.isArray(payloadMetadata.mediaInputRefs)
            ? payloadMetadata.mediaInputRefs
            : []
        )
          .map((item) => readRecord(item)?.inputRef)
          .filter((value): value is string =>
            typeof value === "string" && value.length > 0
          )
          .slice(0, 4),
        source:
          typeof payloadMetadata.chat === "object" &&
          payloadMetadata.chat !== null
            ? "mobile_chat_dispatch"
            : "backend_task_route",
      })
    : null;
  const taskTitle = desktopWorkOrder?.goal.summary ?? canonicalTitle;
  const geminiExecutionValidation = desktopWorkOrder
    ? await validateExecutionPlanWithGeminiFree(app, {
        userId: input.userId,
        taskId: input.requestId,
        workOrder: desktopWorkOrder,
      }).catch(() => null)
    : null;
  const desktopContext = isDesktopRoute
    ? {
        intent: routeDecision.taskRoute?.target ?? "desktop_runtime",
        requiresCapabilities:
          desktopWorkOrder?.requiredCapabilities ?? routeCapabilities,
        naturalLanguageGoal: prompt,
        workOrderSchema: desktopWorkOrder?.schema ?? null,
        structuredSteps: desktopWorkOrder?.planPreview.steps ?? null,
        ...(remoteMcpSelection ? { remoteMcpSelection } : {}),
      }
    : null;
  const enrichedPayload = {
    ...input.payload,
    ...(desktopWorkOrder
      ? {
          // Preserve the user's complete bounded goal for runtime semantic
          // planning. The typed work order remains the authority for allowed
          // capabilities, steps, privacy and approval policy.
          prompt,
          desktopWorkOrder,
          planPreview: desktopWorkOrder.planPreview,
        }
      : {}),
    ...(buildQuantumTaskSnapshot({
      capabilities: routeCapabilities,
      status: "pending",
      ready: !routeBlocked,
    })
      ? {
          quantum: buildQuantumTaskSnapshot({
            capabilities: routeCapabilities,
            status: "pending",
            ready: !routeBlocked,
          }),
        }
      : {}),
    ...(desktopContext ? { desktopContext } : {}),
    ...(dispatchOptimization ? { dispatchOptimization } : {}),
    ...(responsiveExecution ? { responsiveExecution } : {}),
    ...(livenessGuard ? { livenessGuard } : {}),
    metadata: {
      ...payloadMetadata,
      routeDecision,
      ...(remoteMcpSelection ? { remoteMcpSelection } : {}),
      ...(dispatchOptimization ? { dispatchOptimization } : {}),
      ...(responsiveExecution ? { responsiveExecution } : {}),
      ...(livenessGuard ? { livenessGuard } : {}),
      ...(buildQuantumTaskSnapshot({
        capabilities: routeCapabilities,
        status: "pending",
        ready: !routeBlocked,
      })
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
        ...buildUnderstandingMetadataForTask(understanding),
      },
      ...(useFastSharedBrainFlow
        ? {
            chatGeneration: {
              requestId: input.requestId,
              queued: useDurableChatQueue,
            },
          }
        : {}),
      ...(geminiExecutionValidation ? { geminiExecutionValidation } : {}),
    },
  };
  if (routeBlocked) {
    const blockedReason =
      routeDecision.userFacingMessage ||
      "Bu görev için önce bir masaüstü eşleştirmen gerekiyor.";
    const taskResult = await app.db
      .transaction(async (tx) => {
        await tx.execute(
          sql`select pg_advisory_xact_lock(hashtextextended(${input.userId}, 0))`,
        );

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
          userId: input.userId,
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
            title: taskTitle,
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
          throw new AppError(
            500,
            "task_insert_failed",
            "Task could not be created",
          );
        }

        return {
          task: insertedTask,
          reused: false,
        } as const;
      })
      .catch((error) => {
        clearEphemeralVisionCarrier(input.ephemeralVision);
        throw error;
      });
    clearEphemeralVisionCarrier(input.ephemeralVision);

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
      userId: blockedTask.userId,
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

  const taskAttachmentUsage = summarizeTaskAttachmentUsage(
    getPayloadMetadata(enrichedPayload),
  );

  let reservedChatTaskId: string | null = null;
  const taskResult = await app.db
    .transaction(async (tx) => {
      await tx.execute(
        sql`select pg_advisory_xact_lock(hashtextextended(${input.userId}, 0))`,
      );

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

      if (
        taskAttachmentUsage.documentUploads > 0 ||
        taskAttachmentUsage.imageUploads > 0
      ) {
        const trialQuota = await getTrialQuotaUsage(tx, input.userId);
        assertAttachmentQuotaAllowedFromUsage(trialQuota, {
          requiredDocumentUploads: taskAttachmentUsage.documentUploads,
          requiredImageUploads: taskAttachmentUsage.imageUploads,
        });
      }

      const taskQuota = await getTrialQuotaUsage(tx, input.userId);
      assertTrialTaskQuotaAllowedFromUsage(taskQuota);

      const chatQueueAdmissionRequired =
        sharedBrainRoute && useDurableChatQueue;

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
      const createdTaskId = randomUUID();

      if (chatQueueAdmissionRequired) {
        const userActiveCounts = await tx
          .select({ count: sql<number>`count(*)` })
          .from(tasks)
          .where(
            and(
              eq(tasks.userId, input.userId),
              eq(tasks.targetDeviceId, targetDeviceId),
              inArray(tasks.status, ["queued", "planning", "running"]),
            ),
          );
        const admission = decideChatQueueAdmission(
          {
            // The global limit is reserved atomically in the reliability store;
            // this transaction lock makes the per-user count authoritative.
            globalActive: 0,
            userActive: Number(userActiveCounts[0]?.count ?? 0),
          },
          getChatGenerationQueueLimits(app),
        );
        if (!admission.accepted) {
          throw new AppError(
            429,
            "chat_queue_full",
            "Bu hesapta çok sayıda yanıt bekliyor. Mevcut yanıt tamamlandıktan sonra tekrar dene.",
            {
              retryAfterMs: 5_000,
              retrySuggested: true,
              queueReason: "user_backpressure",
            },
          );
        }
        const globalAdmission = await reserveChatGenerationAdmission(
          app,
          createdTaskId,
        );
        if (globalAdmission !== "accepted") {
          throw new AppError(
            globalAdmission === "full" ? 429 : 503,
            globalAdmission === "full"
              ? "chat_queue_full"
              : "chat_queue_unavailable",
            globalAdmission === "full"
              ? "Yanıt sırası dolu. Lütfen biraz sonra yeniden dene."
              : "Yanıt sıraya alınamadı. Lütfen biraz sonra yeniden dene.",
            {
              retryAfterMs: 5_000,
              retrySuggested: true,
              queueReason:
                globalAdmission === "full"
                  ? "global_backpressure"
                  : "queue_unavailable",
            },
          );
        }
        reservedChatTaskId = createdTaskId;
      }

      const queuePosition = Number(activeCounts[0]?.count ?? 0) + 1;
      const payloadBlob = await storeTaskJsonBlob(app, {
        taskId: createdTaskId,
        userId: input.userId,
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
          title: taskTitle,
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
        throw new AppError(
          500,
          "task_insert_failed",
          "Task could not be created",
        );
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
    })
    .catch(async (error) => {
      if (reservedChatTaskId) {
        await releaseChatGenerationAdmission(app, reservedChatTaskId);
        reservedChatTaskId = null;
      }
      clearEphemeralVisionCarrier(input.ephemeralVision);
      throw error;
    });

  if (taskResult.reused) {
    const requeued =
      isSharedBrain &&
      useFastSharedBrainFlow &&
      (["queued", "planning", "running"] as TaskStatus[]).includes(
        taskResult.task.status,
      ) &&
      isDurableChatGenerationTask(taskResult.task)
        ? await enqueueSharedBrainChatTask(app, {
            taskId: taskResult.task.id,
            userId: input.userId,
          })
        : false;
    clearEphemeralVisionCarrier(input.ephemeralVision);
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
      dispatched: requeued,
      reused: true,
      selectedDesktopOnline,
      renderRecipe: null,
    };
  }

  const task = taskResult.task;
  let currentTask: typeof task;
  try {
    if (!useDurableChatQueue) {
      await resequenceDeviceQueue(app, targetDeviceId);
    }
    currentTask = (await getTaskById(app, task.id)) ?? task;
    await notifyTaskReady(input.onTaskReady, {
      rawTask: currentTask,
      reused: false,
      routeDecision,
      isSharedBrain,
    });
  } catch (error) {
    clearEphemeralVisionCarrier(input.ephemeralVision);
    throw error;
  }
  if (isSharedBrain && useFastSharedBrainFlow) {
    let dispatchedTask = currentTask;
    if (useDurableChatQueue) {
      try {
        const enqueued = await enqueueSharedBrainChatTask(app, {
          taskId: currentTask.id,
          userId: input.userId,
        });
        if (!enqueued) {
          throw new Error("chat_queue_unavailable");
        }
        dispatchedTask =
          (await markQueuedSharedBrainChatPhase(app, {
            taskId: currentTask.id,
            userId: input.userId,
            phase: "queued",
            message: "Yanıt hazırlanıyor.",
          })) ?? currentTask;
        clearEphemeralVisionCarrier(input.ephemeralVision);
      } catch {
        const queueError = new AppError(
          503,
          "chat_queue_unavailable",
          "Yanıt sıraya alınamadı. Lütfen biraz sonra yeniden dene.",
          {
            transient: true,
            retrySuggested: true,
            failureClass: "queue_unavailable",
          },
        );
        await finalizeSharedBrainChatFailure(
          app,
          {
            currentTask,
            userId: input.userId,
            requestId: input.requestId,
          },
          queueError,
        );
        clearEphemeralVisionCarrier(input.ephemeralVision);
        throw queueError;
      }
    } else {
      void processSharedBrainChatTask(app, {
        currentTask,
        userId: input.userId,
        requestId: input.requestId,
        prompt,
        canonicalTitle,
        understanding,
        planCode: usageAccess.planCode,
        brainProfile: usageAccess.brainProfile,
        ephemeralVision: input.ephemeralVision,
      });
    }
    await logRouteDecision(app, {
      taskId: dispatchedTask.id,
      routeDecision,
      requestedTargetDeviceId: routeSelectedTargetDeviceId,
      origin: routeOrigin,
    });

    return {
      task: shapeTaskFeedItem(dispatchedTask, { selectedDesktopOnline }),
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
    title: taskTitle,
    message: prompt,
    routeContext: "tasks.create",
    source:
      typeof input.payload.source === "string"
        ? input.payload.source
        : undefined,
    deviceId: targetDeviceId,
    metadata: {
      ...payloadMetadata,
      ...(taskResult.reused
        ? {}
        : { sourceBlobHash: taskResult.payloadBlobHash ?? undefined }),
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
    readiness: isSharedBrain
      ? "ready"
      : targetDevice.device.targetStatus === "ready"
        ? "ready"
        : "degraded",
    routingMode: isSharedBrain
      ? "server_brain_first"
      : "desktop_first_when_available",
    requestId: input.requestId,
  });

  await insertTaskEvent(app, {
    taskId: currentTask.id,
    userId: currentTask.userId,
    status: "queued",
    message: "Task queued",
    payload: {
      understanding: summarizeUnderstandingForSafeTelemetry(understanding),
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
      understanding: summarizeUnderstandingForSafeTelemetry(understanding),
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
      const attachmentContext = await resolveTaskAttachmentContext(
        app,
        runningPayload,
        prompt,
        input.ephemeralVision,
      );
      const selectedWorkload = resolveSharedBrainWorkloadForUnderstanding({
        routeDecision,
        prompt,
        attachmentContextUsed: attachmentContext?.used === true,
        envelope: understanding.envelope,
      });
      const sourceImages = hostedImageSources(input.ephemeralVision);
      const imageEditIntent = isHostedImageEditIntent(prompt);
      const imageEditNeedsSource =
        imageEditIntent && countDistinctEphemeralImages(input.ephemeralVision) === 0;
      if (
        isHostedImageGenerationRequest(prompt) ||
        imageEditIntent
      ) {
        const startedAtMs = Date.now();
        const completedTask = await completeServerBrainTask(app, {
          taskId: runningTask.id,
          userId: input.userId,
          responseText: imageEditNeedsSource
            ? "Düzenlememi istediğin görseli yüklemen gerekiyor. Görseli ekleyip değiştirmemi istediğin kısmı tekrar yaz."
            : "",
          provider: "elyan_image",
          model: "elyan_image",
          route: "shared_brain",
          workload: selectedWorkload,
          latencyMs: Math.max(1, Date.now() - startedAtMs),
          promptTokens: 0,
          completionTokens: 0,
          totalTokens: 0,
          firstDeltaMs: null,
          completionLatencyMs: null,
          responseBytes: 0,
          attachmentContextUsed: attachmentContext?.used === true,
          attachmentContextSource: attachmentContext?.source ?? null,
          sourceImages,
        });
        if (!completedTask.completionTransitionOwned) {
          return {
            task: shapeTaskFeedItem(completedTask, {
              selectedDesktopOnline,
            }),
            dispatched: true,
            reused: false,
            selectedDesktopOnline,
            renderRecipe: readRenderRecipeFromTask(completedTask),
          };
        }
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
          renderRecipe: readRenderRecipeFromTask(completedTask),
        };
      }
      const inferenceVision = await resolveMediaInputVisionCarrier(
        app,
        input.userId,
        input.ephemeralVision,
      ).catch(() => undefined);
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
        workload: selectedWorkload,
        meteringSurface: runningMetadata.channel === "chat" ? "chat" : "task",
        planCode: usageAccess.planCode,
        understandingContext: understanding.context,
        brainProfile: usageAccess.brainProfile,
        ephemeralVision: inferenceVision,
      }).finally(() => {
        if (inferenceVision !== input.ephemeralVision) {
          clearEphemeralVisionCarrier(inferenceVision);
        }
      });
      const agentRunState = readAgentRunState(inference.metadata);
      if (agentRunState && agentRunState !== "completed") {
        const deferredTask =
          (await getTaskById(app, runningTask.id)) ?? runningTask;
        return {
          task: shapeTaskFeedItem(deferredTask, { selectedDesktopOnline }),
          dispatched: true,
          reused: false,
          selectedDesktopOnline,
          renderRecipe: null,
        };
      }
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
      if (!completedTask.completionTransitionOwned) {
        return {
          task: shapeTaskFeedItem(completedTask, { selectedDesktopOnline }),
          dispatched: true,
          reused: false,
          selectedDesktopOnline,
          renderRecipe: readRenderRecipeFromTask(completedTask),
        };
      }
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
        renderRecipe: readRenderRecipeFromTask(completedTask),
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
        .where(
          and(
            eq(tasks.id, currentTask.id),
            eq(tasks.userId, input.userId),
            inArray(tasks.status, ["queued", "planning", "running"]),
          ),
        )
        .returning();
      if (rows.length === 0) {
        const latestTask = await getTaskById(app, currentTask.id);
        if (latestTask && isChatGenerationSettled(latestTask.status)) {
          return {
            task: shapeTaskFeedItem(latestTask, { selectedDesktopOnline }),
            dispatched: true,
            reused: false,
            selectedDesktopOnline,
            renderRecipe: readRenderRecipeFromTask(latestTask),
          };
        }
      }
      const failedTask = rows[0] ?? currentTask;
      await insertTaskEvent(app, {
        taskId: failedTask.id,
        userId: failedTask.userId,
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
      await releaseMediaInputsFromMetadata(
        app,
        input.userId,
        getPayloadMetadata(readRecord(currentTask.payload) ?? {}),
      ).catch(() => undefined);
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
    } finally {
      clearEphemeralVisionCarrier(input.ephemeralVision);
    }
  }

  // Desktop dispatch never receives the cloud-only ephemeral carrier.
  clearEphemeralVisionCarrier(input.ephemeralVision);

  const dispatchOwner = `backend:ws:${input.requestId}`;
  const dispatchLockAcquired =
    await app.services.reliability.acquireTaskDispatchLock(
      currentTask.id,
      dispatchOwner,
    );
  let dispatched = true;
  if (dispatchLockAcquired) {
    const leaseResult = await issueTaskDispatchLease(app, {
      taskId: currentTask.id,
      runtimeConnectionId: currentTask.runtimeConnectionId ?? null,
      leaseMs: TASK_DISPATCH_LEASE_MS,
    });
    const lease = leaseResult?.lease ?? null;
    const taskForDispatch = leaseResult?.task ?? currentTask;
    const payload = buildRuntimeTaskDispatchEnvelope(taskForDispatch, lease);
    dispatched = app.services.realtimeHub.sendToRuntime(
      currentTask.targetDeviceId,
      payload,
    );
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
        userId: releasedTask.userId,
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
      await app.services.reliability.releaseTaskDispatchLock(
        currentTask.id,
        dispatchOwner,
      );
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
  clearEphemeralVisionCarrier(input.ephemeralVision);

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

  const now = new Date();
  let visibleApprovals = 0;
  return rows
    .filter((task) => {
      if (task.status !== "waiting_approval") return true;
      if (isApprovalAlreadyResolved(task.approvalRequest)) return false;
      if (isApprovalRequestExpired(task.approvalRequest, now)) return false;
      visibleApprovals += 1;
      return visibleApprovals <= MAX_ACTIVE_USER_APPROVALS;
    })
    .map((task) => shapeTaskFeedItem(task));
}

export async function getTaskDetail(
  app: FastifyInstance,
  taskId: string,
  userId: string,
) {
  await reconcileStaleRuntimeTasks(app, {
    userId,
    limit: 50,
  });

  const task = await getTaskForUser(app, taskId, userId);
  const scalableStateReads =
    app.config.ELYAN_SCALABLE_STATE_READS_ENABLED === true;
  const eventQuery = app.db
    .select()
    .from(taskEvents)
    .where(eq(taskEvents.taskId, task.id));
  const eventWindowRows = scalableStateReads
    ? await eventQuery.orderBy(desc(taskEvents.createdAt)).limit(201)
    : null;
  const events = scalableStateReads
    ? (eventWindowRows ?? []).slice(0, 200).reverse()
    : await eventQuery.orderBy(taskEvents.createdAt);
  const taskArtifacts = await app.db
    .select()
    .from(artifacts)
    .where(eq(artifacts.taskId, task.id))
    .orderBy(artifacts.createdAt);
  const hydratedTask = {
    ...task,
    payload: await hydrateTaskJsonValue(app, task.payload, task.payloadBlobId, {
      userId,
      ownerType: "task",
      ownerId: task.id,
    }),
    result: await hydrateTaskJsonValue(app, task.result, task.resultBlobId, {
      userId,
      ownerType: "task",
      ownerId: task.id,
    }),
    approvalRequest: await hydrateTaskJsonValue(
      app,
      task.approvalRequest,
      task.approvalRequestBlobId,
      {
        userId,
        ownerType: "task",
        ownerId: task.id,
      },
    ),
  };

  return {
    task: {
      ...hydratedTask,
      payload: sanitizePublicTaskEventPayload(hydratedTask.payload),
      result: sanitizePublicInferenceValue(hydratedTask.result),
      approvalRequest: sanitizePublicInferenceValue(
        hydratedTask.approvalRequest,
      ),
      chatSessionId: extractTaskChatSessionId(hydratedTask.payload),
    },
    events: await Promise.all(
      events.map(async (event) => ({
        ...event,
        payload: sanitizePublicInferenceValue(
          await hydrateTaskJsonValue(app, event.payload, event.payloadBlobId, {
            userId,
            ownerType: "task_event",
            ownerId: event.id,
          }),
        ),
      })),
    ),
    eventWindow: scalableStateReads
      ? {
          limit: 200,
          returned: events.length,
          truncated: (eventWindowRows?.length ?? 0) > 200,
          order: "ascending",
        }
      : undefined,
    artifacts: await Promise.all(
      taskArtifacts.map((artifact) =>
        shapePublicArtifactRecord(app, artifact, userId),
      ),
    ),
  };
}

export async function getTaskArtifact(
  app: FastifyInstance,
  taskId: string,
  artifactId: string,
  userId: string,
) {
  const artifact = await getTaskArtifactRecordForUser(
    app,
    taskId,
    artifactId,
    userId,
  );
  return {
    artifact: await shapePublicArtifactRecord(app, artifact, userId),
  };
}

export async function getTaskArtifactContent(
  app: FastifyInstance,
  taskId: string,
  artifactId: string,
  userId: string,
) {
  const artifact = await getTaskArtifactRecordForUser(
    app,
    taskId,
    artifactId,
    userId,
  );
  const shapedArtifact = await shapePublicArtifactRecord(app, artifact, userId);
  const hydratedBody = artifact.bodyBlobId
    ? await app.services?.blobs?.hydrateJsonForOwner<Record<string, unknown>>({
        blobId: artifact.bodyBlobId,
        userId,
        ownerType: "artifact",
        ownerId: artifact.id,
      })
    : null;
  const bodyRecord =
    hydratedBody &&
    typeof hydratedBody === "object" &&
    !Array.isArray(hydratedBody)
      ? (hydratedBody as Record<string, unknown>)
      : null;
  return {
    artifact: shapedArtifact,
    content: {
      textContent:
        typeof bodyRecord?.textContent === "string"
          ? sanitizePublicInferenceValue(bodyRecord.textContent)
          : artifact.textContent,
      payload: sanitizePublicInferenceValue(
        bodyRecord?.payload ?? artifact.payload ?? null,
      ),
      metadata: sanitizePublicInferenceValue(
        bodyRecord?.metadata ?? artifact.metadata ?? null,
      ),
      downloadUrl: shapedArtifact.downloadUrl,
      downloadable: shapedArtifact.downloadable,
    },
  };
}

export async function getTaskArtifactRawContent(
  app: FastifyInstance,
  taskId: string,
  artifactId: string,
  token: string | null | undefined,
) {
  const verified = verifyArtifactRawContentToken(
    app,
    token,
    taskId,
    artifactId,
  );
  if (!verified) {
    throw notFound("Artifact not found");
  }
  const artifact = await getTaskArtifactRecordForUser(
    app,
    taskId,
    artifactId,
    verified.userId,
  );
  if (!artifact.bodyBlobId) {
    throw notFound("Artifact content not found");
  }
  const body = await app.services?.blobs?.hydrateBytesForOwner({
    blobId: artifact.bodyBlobId,
    userId: verified.userId,
    ownerType: "artifact",
    ownerId: artifact.id,
  });
  if (!body) {
    throw notFound("Artifact content not found");
  }
  return {
    body: Buffer.from(body),
    contentType: artifact.contentType || "application/octet-stream",
    fileName: artifact.name || artifact.id,
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
  const approvalRequest = readRecord(task.approvalRequest);
  const approvalResolution = readRecord(approvalRequest?.resolution);
  if (
    approvalRequest?.kind === "connector_write" &&
    approvalResolution?.state === "executing"
  ) {
    throw conflict("Approved connector action is already executing");
  }

  const rows = await app.db
    .update(tasks)
    .set(buildTaskCancellationUpdate())
    .where(
      and(
        eq(tasks.id, task.id),
        eq(tasks.userId, userId),
        eq(tasks.status, task.status),
      ),
    )
    .returning();

  const updatedTask = rows[0];
  if (!updatedTask) {
    throw conflict("Task state changed before cancellation");
  }
  await resequenceDeviceQueue(app, updatedTask.targetDeviceId);

  await insertTaskEvent(app, {
    taskId: task.id,
    userId: task.userId,
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
  await releaseChatGenerationAdmission(app, updatedTask.id);
  await cancelAgentRunForTask({ app, userId, taskId: updatedTask.id }).catch(
    () => false,
  );
  const canceledPayload = readRecord(task.payload) ?? {};
  await releaseMediaInputsFromMetadata(
    app,
    task.userId,
    readRecord(canceledPayload.metadata) ?? {},
  ).catch(() => undefined);

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
  if (isApprovalAlreadyResolved(task.approvalRequest)) {
    const resolution = readRecord(readRecord(task.approvalRequest)?.resolution);
    return {
      taskId: task.id,
      status: task.status,
      approved: resolution?.approved === true,
      duplicate: true,
      task: shapeTaskFeedItem(task),
    };
  }
  if (isApprovalRequestExpired(task.approvalRequest)) {
    return cancelTask(app, task.id, task.userId, {
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
    });
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
    .where(
      and(
        eq(tasks.id, task.id),
        eq(tasks.status, "waiting_approval" as TaskStatus),
      ),
    )
    .returning();

  const updatedTask = approvalRows[0];
  if (!updatedTask) {
    const latest = await getTaskForUser(app, input.taskId, input.userId);
    if (isApprovalAlreadyResolved(latest.approvalRequest)) {
      const resolution = readRecord(readRecord(latest.approvalRequest)?.resolution);
      return {
        taskId: latest.id,
        status: latest.status,
        approved: resolution?.approved === true,
        duplicate: true,
        task: shapeTaskFeedItem(latest),
      };
    }
    throw conflict("Task approval changed before resolution");
  }

  await insertTaskEvent(app, {
    taskId: task.id,
    userId: task.userId,
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

  await resumeAgentRunAfterApproval({
    app,
    userId: input.userId,
    taskId: updatedTask.id,
  }).catch(() => false);

  return {
    taskId: updatedTask.id,
    status: updatedTask.status,
    approved: true,
    task: shapeTaskFeedItem(updatedTask),
  };
}

export type ConnectorWriteApprovalOutcome =
  | { status: "not_found" }
  | { status: "rejected"; tool: string }
  | {
      status: "executed";
      tool: string;
      result: Awaited<ReturnType<typeof executeAgentTool>>;
    };

/** Resolve a server connector write through the durable task approval row. */
export async function resolveConnectorWriteApproval(
  app: FastifyInstance,
  input: {
    userId: string;
    token: string;
    approved: boolean;
    requestId?: string;
  },
): Promise<ConnectorWriteApprovalOutcome> {
  const taskId = connectorWriteTaskIdFromToken(input.token);
  if (!taskId) return { status: "not_found" };
  const task = await getTaskById(app, taskId);
  if (
    !task ||
    task.userId !== input.userId ||
    task.status !== "waiting_approval"
  ) {
    return { status: "not_found" };
  }
  const approval = readRecord(task.approvalRequest);
  const canonicalCall = readCanonicalConnectorWriteApprovalCall(approval);
  const tool = canonicalCall?.tool ?? "";
  const args = canonicalCall?.args ?? null;
  const expiresAt =
    typeof approval?.expiresAt === "number" ? approval.expiresAt : 0;
  if (
    approval?.kind !== "connector_write" ||
    !canonicalCall ||
    approval.token !== input.token ||
    approval.userId !== input.userId ||
    approval.taskId !== task.id ||
    !tool ||
    !args
  ) {
    return { status: "not_found" };
  }
  if (expiresAt <= Date.now()) {
    const expiredAt = new Date();
    await app.db
      .update(tasks)
      .set({
        status: "completed",
        approvalRequest: {
          ...approval,
          resolution: {
            state: "expired",
            approved: false,
            resolvedAt: expiredAt.toISOString(),
          },
        },
        approvalRequestBlobId: null,
        completedAt: expiredAt,
        updatedAt: expiredAt,
        queuePosition: 0,
      })
      .where(
        and(
          eq(tasks.id, task.id),
          eq(tasks.userId, input.userId),
          eq(tasks.status, "waiting_approval"),
          sql`${tasks.approvalRequest}->>'token' = ${input.token}`,
        ),
      );
    await releaseChatGenerationAdmission(app, task.id);
    return { status: "not_found" };
  }

  const now = new Date();
  const resolution = {
    state: input.approved ? "executing" : "rejected",
    approved: input.approved,
    resolvedAt: now.toISOString(),
  };
  const claimedRows = await app.db
    .update(tasks)
    .set({
      status: input.approved ? "running" : "completed",
      approvalRequest: { ...approval, resolution },
      // The JSON row is now authoritative; clearing the old blob avoids
      // hydrating the pre-resolution approval after a restart.
      approvalRequestBlobId: null,
      completedAt: input.approved ? null : now,
      updatedAt: now,
      queuePosition: 0,
    })
    .where(
      and(
        eq(tasks.id, task.id),
        eq(tasks.userId, input.userId),
        eq(tasks.status, "waiting_approval"),
        sql`${tasks.approvalRequest}->>'token' = ${input.token}`,
        sql`coalesce(${tasks.approvalRequest}->'resolution'->>'state', 'pending') = 'pending'`,
      ),
    )
    .returning();
  const claimed = claimedRows[0];
  if (!claimed) return { status: "not_found" };

  if (!input.approved) {
    await releaseChatGenerationAdmission(app, claimed.id);
    await insertTaskEvent(app, {
      taskId: task.id,
      userId: task.userId,
      status: "completed",
      message: "Connector yazma taslağı kullanıcı tarafından reddedildi",
      payload: { tool, approved: false },
    });
    await publishTaskEvent(app, claimed, "task.updated", {
      task: shapeTaskFeedItem(claimed),
    });
    await syncChatTaskLifecycle(app, {
      originalTask: task,
      updatedTask: claimed,
      message: "İşlem iptal edildi.",
    });
    return { status: "rejected", tool };
  }

  const result = await executeAgentTool(
    app,
    {
      userId: input.userId,
      taskId: task.id,
      sessionId:
        typeof approval.sessionId === "string" ? approval.sessionId : null,
      workload:
        typeof approval.workload === "string"
          ? (approval.workload as SharedBrainWorkload)
          : "mobile_chat_balanced",
      allowStateWrites: true,
      allowSideEffects: true,
    },
    { tool, args } as AgentToolRequest,
  );
  const finishedAt = new Date();
  const previousResult = readRecord(task.result) ?? {};
  const remainingApprovals = Array.isArray(approval.remainingApprovals)
    ? approval.remainingApprovals.map(readRecord).filter((item): item is Record<string, unknown> => item != null)
    : [];
  const nextApprovalCandidate = result.ok ? (remainingApprovals[0] ?? null) : null;
  const nextCall = readCanonicalConnectorWriteApprovalCall(nextApprovalCandidate);
  const nextApproval: Record<string, unknown> | null = nextApprovalCandidate && nextCall &&
    nextApprovalCandidate.userId === input.userId && nextApprovalCandidate.taskId === task.id
    ? { ...nextApprovalCandidate, ...(remainingApprovals.length > 1 ? { remainingApprovals: remainingApprovals.slice(1) } : {}) }
    : null;
  const finalStatus: TaskStatus = result.ok ? (nextApproval ? "waiting_approval" : "completed") : "failed";
  const safeError = result.ok
    ? null
    : (result.error?.message ?? "Connector işlemi tamamlanamadı.");
  const finalApproval = {
    ...approval,
    resolution: {
      state: result.ok ? "executed" : "failed",
      approved: true,
      resolvedAt: finishedAt.toISOString(),
      errorCode: result.error?.code ?? null,
    },
  };
  const nextDraft = readRecord(nextApproval?.draft);
  const nextPublicApproval = nextApproval && nextCall && nextDraft ? {
    token: nextApproval.token,
    tool: nextCall.tool,
    title: nextDraft.title,
    appLabel: nextDraft.appLabel,
    expiresAt: nextApproval.expiresAt,
    lines: nextDraft.lines,
  } : null;
  const updatedAssistantBlocks = advanceTaskTraceApproval({
    blocks: previousResult.assistantBlocks,
    completedTool: tool,
    nextApproval: nextPublicApproval,
  });
  const finalRows = await app.db
    .update(tasks)
    .set({
      status: finalStatus,
      approvalRequest: nextApproval ?? finalApproval,
      approvalRequestBlobId: null,
      result: {
        ...previousResult,
        assistantBlocks: updatedAssistantBlocks,
        connectorWriteExecution: {
          tool,
          ok: result.ok,
          errorCode: result.error?.code ?? null,
          completedAt: finishedAt.toISOString(),
        },
      },
      error: safeError,
      completedAt: finalStatus === "completed" ? finishedAt : null,
      updatedAt: finishedAt,
      queuePosition: 0,
    })
    .where(
      and(
        eq(tasks.id, task.id),
        eq(tasks.userId, input.userId),
        eq(tasks.status, "running"),
        sql`${tasks.approvalRequest}->>'token' = ${input.token}`,
        sql`${tasks.approvalRequest}->'resolution'->>'state' = 'executing'`,
      ),
    )
    .returning();
  const updated = finalRows[0];
  if (!updated) {
    // The external call has already finished and must never be retried merely
    // because another transition won the task-row CAS. Preserve that truth in
    // the audit trail without publishing a stale completion snapshot.
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "connector.write.approval.finalize_conflict",
      resourceType: "task",
      resourceId: task.id,
      status: "failure",
      requestId: input.requestId,
      payload: {
        tool,
        executionOk: result.ok,
        errorCode: result.error?.code ?? "approval_state_changed_after_execution",
      },
    });
    return { status: "executed", tool, result };
  }
  if (finalStatus === "completed" || finalStatus === "failed") {
    await releaseChatGenerationAdmission(app, updated.id);
  }
  await insertTaskEvent(app, {
    taskId: task.id,
    userId: task.userId,
    status: finalStatus,
    message: result.ok
      ? "Onaylanan connector işlemi tamamlandı"
      : (safeError ?? undefined),
    payload: {
      tool,
      approved: true,
      ok: result.ok,
      errorCode: result.error?.code ?? null,
    },
  });
  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "connector.write.approval.resolve",
    resourceType: "task",
    resourceId: task.id,
    status: result.ok ? "success" : "failure",
    requestId: input.requestId,
    payload: { tool, approved: true, errorCode: result.error?.code ?? null },
  });
  await publishTaskEvent(app, updated, "task.updated", {
    task: shapeTaskFeedItem(updated),
  });
  await syncChatTaskLifecycle(app, {
    originalTask: task,
    updatedTask: updated,
    message: result.ok
      ? "Onaylanan işlem tamamlandı."
      : (safeError ?? "İşlem başarısız."),
  });
  return { status: "executed", tool, result };
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
  if (input.approvalRequest?.kind === "connector_write") {
    throw new AppError(
      400,
      "runtime_connector_write_forbidden",
      "Server connector approvals cannot originate from a desktop runtime",
    );
  }
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
  const normalizedApprovalRequest = input.status === "waiting_approval" && input.approvalRequest
    ? normalizeTaskApprovalRequest(input.approvalRequest, {
        taskId: ownedTask.id,
      })
    : input.approvalRequest;
  const runtimeResult = input.operator
    ? {
        ...(input.result ?? {}),
        operator: input.operator,
      }
    : input.result;
  const approvalRequestBlob =
    normalizedApprovalRequest === undefined
      ? null
      : await storeTaskJsonBlob(app, {
          taskId: ownedTask.id,
          userId: ownedTask.userId,
          slot: "approval_request",
          scope: "task_approval_request",
          value: normalizedApprovalRequest,
        });
  const runtimeResultBlob =
    runtimeResult === undefined
      ? null
      : await storeTaskJsonBlob(app, {
          taskId: ownedTask.id,
          userId: ownedTask.userId,
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
      approvalRequest: normalizedApprovalRequest,
      result: runtimeResult,
    }),
    ...(normalizedApprovalRequest !== undefined
      ? { approvalRequestBlobId: approvalRequestBlob?.blobId ?? null }
      : {}),
    ...(runtimeResult !== undefined
      ? { resultBlobId: runtimeResultBlob?.blobId ?? null }
      : {}),
  };

  const rows = await app.db
    .update(tasks)
    .set(updates)
    .where(eq(tasks.id, ownedTask.id))
    .returning();
  let updatedTask = rows[0];
  const storedArtifacts = await persistArtifacts(
    app,
    ownedTask.id,
    ownedTask.userId,
    input.artifacts,
  );
  const shapedArtifacts = await Promise.all(
    storedArtifacts.map((artifact) =>
      shapePublicArtifactRecord(app, artifact, ownedTask.userId),
    ),
  );

  // Backend-owned user policy is read at the approval boundary, so a mode
  // change takes effect mid-session. Client metadata is never authority.
  const existingApprovalRequest = readRecord(
    normalizedApprovalRequest ?? updatedTask.approvalRequest,
  );
  const existingApprovalResolution = readRecord(
    existingApprovalRequest?.resolution,
  );
  const approvalMode = input.status === "waiting_approval"
    ? await getUserApprovalMode(app, ownedTask.userId)
    : null;
  const trustedIdempotentDesktopTask = approvalMode != null &&
    shouldAutoApproveDesktopTask({
      status: input.status,
      payload: ownedTask.payload,
      approvalMode,
      approvalRequest: existingApprovalRequest,
    }) && existingApprovalResolution?.approved !== true;

  if (trustedIdempotentDesktopTask) {
    const approvalRows = await app.db
      .update(tasks)
      .set(
        buildTaskApprovalResumeUpdate(updatedTask, {
          notes:
            "Güvenli yazma modu: idempotent işlem otomatik onaylandı.",
        }),
      )
      .where(eq(tasks.id, updatedTask.id))
      .returning();
    updatedTask = approvalRows[0] ?? updatedTask;
  }
  await resequenceDeviceQueue(app, updatedTask.targetDeviceId);

  await insertTaskEvent(app, {
    taskId: ownedTask.id,
    userId: ownedTask.userId,
    status: input.status,
    message: input.message,
    payload: {
      summary: input.summary,
      error: input.error,
      approvalRequest: input.approvalRequest,
      normalizedApprovalRequest,
      operator: input.operator,
      artifactCount: shapedArtifacts.length,
      artifacts: shapedArtifacts,
    },
  });

  if (trustedIdempotentDesktopTask) {
    await insertTaskEvent(app, {
      taskId: ownedTask.id,
      userId: ownedTask.userId,
      status: "waiting_approval",
      message: "Güvenli yazma modu etkin; idempotent işlem otomatik onaylandı.",
      payload: {
        approved: true,
        source: "trusted_idempotent_write",
      },
    });
    await publishTaskEvent(app, updatedTask, "task.approval_granted", {
      task: shapeTaskFeedItem(updatedTask),
      taskId: updatedTask.id,
      approved: true,
      source: "trusted_idempotent_write",
    });
    app.services.realtimeHub.sendToRuntime(updatedTask.targetDeviceId, {
      type: "task.approval",
      taskId: updatedTask.id,
      approved: true,
      notes: "Güvenli yazma modu: idempotent işlem otomatik onaylandı.",
    });
    await resumeAgentRunAfterApproval({
      app,
      userId: updatedTask.userId,
      taskId: updatedTask.id,
    }).catch(() => false);
  }

  if (isTerminalTaskStatus(input.status)) {
    await app.services.reliability.clearTaskDispatchLock(ownedTask.id);
    const payload =
      ownedTask.payload &&
      typeof ownedTask.payload === "object" &&
      !Array.isArray(ownedTask.payload)
        ? (ownedTask.payload as Record<string, unknown>)
        : {};
    await releaseMediaInputsFromMetadata(
      app,
      ownedTask.userId,
      readRecord(payload.metadata) ?? {},
    ).catch(() => undefined);

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
        result: runtimeResult,
      });
      await recordRuntimeDispatchPolicyFeedback(app, {
        task: ownedTask,
        result: runtimeResult,
      });
    } else if (input.status === "failed") {
      const failureSignature = deriveTaskFailureSignature({
        error: input.error,
        result: runtimeResult,
        payload,
      });
      void recordTaskFailureLearning(app, {
        userId: ownedTask.userId,
        accountId: ownedTask.userId,
        taskId: ownedTask.id,
        errorCode: failureSignature.errorCode,
        failedTool: failureSignature.failedTool,
        capabilities: failureSignature.capabilities,
      }).catch(() => undefined);
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
    userId: task.userId,
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
  const storedArtifacts = await persistArtifacts(
    app,
    ownedTask.id,
    ownedTask.userId,
    items,
  );
  const shapedArtifacts = await Promise.all(
    storedArtifacts.map((artifact) =>
      shapePublicArtifactRecord(app, artifact, ownedTask.userId),
    ),
  );

  await insertTaskEvent(app, {
    taskId: ownedTask.id,
    userId: ownedTask.userId,
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

export async function appendTaskBinaryArtifact(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  taskId: string,
  input: { body: Uint8Array; name: string; contentType: string; sha256: string },
) {
  const task = await getTaskForRuntime(app, taskId, auth);
  const ownedTask = await ensureTaskRuntimeOwnership(app, task, auth);
  const contentType = input.contentType.toLowerCase().split(";", 1)[0]!.trim();
  if (!["image/png", "image/jpeg", "image/webp"].includes(contentType)) {
    throw new AppError(400, "artifact_type_invalid", "Only PNG, JPEG and WebP image artifacts are accepted");
  }
  if (!input.body.byteLength || input.body.byteLength > 25 * 1024 * 1024) {
    throw new AppError(400, "artifact_size_invalid", "Artifact must be between 1 byte and 25 MB");
  }
  try {
    const { default: sharp } = await import("sharp");
    const metadata = await sharp(Buffer.from(input.body), {
      failOn: "warning",
      limitInputPixels: 150_000_000,
    }).metadata();
    const detectedType = metadata.format === "png"
      ? "image/png"
      : metadata.format === "webp"
        ? "image/webp"
        : metadata.format === "jpeg"
          ? "image/jpeg"
          : "";
    if (detectedType !== contentType || !metadata.width || !metadata.height) {
      throw new Error("artifact image type mismatch");
    }
  } catch {
    throw new AppError(400, "artifact_image_invalid", "Artifact is not a valid declared image");
  }
  const digest = createHash("sha256").update(input.body).digest("hex");
  if (!/^[a-f0-9]{64}$/i.test(input.sha256) || digest !== input.sha256.toLowerCase()) {
    throw new AppError(400, "artifact_hash_mismatch", "Artifact hash verification failed");
  }
  const name = String(input.name || "elyan-image.png")
    .replace(/[\\/\0\r\n]/g, "_")
    .trim()
    .slice(0, 255) || "elyan-image.png";
  const storedArtifacts = await persistArtifacts(app, ownedTask.id, ownedTask.userId, [{
    kind: "file",
    name,
    contentType,
    textContent: "Görsel hazır.",
    payload: { previewText: "Görsel hazır.", mimeType: contentType, source: "elyan_desktop_image" },
    metadata: { sourceType: "task_artifact", contentFamily: "image", viewerHint: "image", mimeType: contentType },
    binaryBody: input.body,
  }]);
  const shapedArtifacts = await Promise.all(
    storedArtifacts.map((artifact) => shapePublicArtifactRecord(app, artifact, ownedTask.userId)),
  );
  await insertTaskEvent(app, {
    taskId: ownedTask.id,
    userId: ownedTask.userId,
    status: ownedTask.status,
    message: "Binary artifact appended",
    payload: { artifactCount: shapedArtifacts.length, artifacts: shapedArtifacts },
  });
  await publishTaskEvent(app, ownedTask, "task.artifacts", {
    taskId: ownedTask.id,
    artifacts: shapedArtifacts,
  });
  return { taskId: ownedTask.id, artifacts: shapedArtifacts };
}

export async function getTaskMediaInputForRuntime(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  taskId: string,
  inputRef: string,
) {
  const task = await getTaskForRuntime(app, taskId, auth);
  const ownedTask = await ensureTaskRuntimeOwnership(app, task, auth);
  const payload = readRecord(ownedTask.payload) ?? {};
  const metadata = readRecord(payload.metadata) ?? {};
  const refs = Array.isArray(metadata.mediaInputRefs) ? metadata.mediaInputRefs : [];
  const belongsToTask = refs.some((item) =>
    readRecord(item)?.inputRef === inputRef
  );
  if (!belongsToTask) {
    throw new AppError(404, "media_input_not_found", "Media input not found");
  }
  return resolveMediaInput(app, inputRef, ownedTask.userId);
}
