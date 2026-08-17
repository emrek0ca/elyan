import { and, desc, eq, inArray, isNull, lt, or, sql } from "drizzle-orm";
import { createHash, randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import type {
  ChatSessionSource,
  ChatSessionStatus,
} from "../../contracts/domain.js";
import { chatMessages, chatSessions, tasks } from "../../db/schema.js";
import { AppError, notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import {
  extractAttachmentMetadataCarrier,
  type AttachmentContextCandidate,
  resolveAttachmentContextWithCache,
} from "../brain/attachment-context.js";
import { buildSharedBrainAckText } from "../brain/chat-heuristics.js";
import {
  buildProactiveOpeningCompose,
  processDueProactiveTriggerForSession,
} from "../brain/proactive-engine.js";
import {
  getSharedBrainWorkloadProfile,
  resolveAttachmentAwareSharedBrainWorkload,
  type SharedBrainWorkload,
} from "../brain/workloads.js";
import { logBrainDecisionObservation } from "../brain/decision-observability.js";
import {
  canUseDesktopConnections,
  normalizePlanBrainProfile,
} from "../billing/catalog.js";
import {
  createUpgradeOrByokRequiredError,
  getUserUsageAccessTruth,
} from "../billing/service.js";
import {
  calculateBillablePlanTokens,
  estimateTextTokens,
} from "../billing/token-metering.js";
import {
  assertTrialTaskQuotaAllowedFromUsage,
  getTrialQuotaUsage,
} from "../quota/service.js";
import { routeChatTurn } from "../routing-policy/service.js";
import { resolveCommandTarget } from "../routing-policy/service.js";
import {
  createChatQueueUnavailableError,
  createTask,
  resolveSharedBrainChatDispatchPolicy,
  shapeTaskFeedItem,
} from "../tasks/service.js";
import {
  countDistinctEphemeralImages,
  type EphemeralVisionCarrier,
} from "../brain/ephemeral-vision.js";
import { isDeterministicDesktopFastWorkOrder } from "../tasks/desktop-work-order.js";
import { sanitizePublicInferenceValue } from "../tasks/service-helpers.js";
import { normalizeLocalDerivedMetadata } from "../../lib/derived-data.js";
import { sanitizeInboundContextRecord } from "../../lib/context-text-sanitizer.js";
import { listFreshWorldSignals } from "../mobile/service.js";
import { fuseWorldSignalRecordsByKind } from "../../core/understanding/context-packets.js";
import { resolveRemoteMcpRequest } from "../integrations/service.js";
import {
  type AssistantMessageBlock,
  normalizeAssistantMessageBlocks,
  shapeAssistantMessagePayload,
  withAssistantBlocksMetadata,
} from "./message-blocks.js";
import {
  buildChatContextSnapshot,
  resolveChatTurnKind,
  snapshotConversation,
  type ChatContextSnapshot,
  type ChatContextSnapshotTurn,
} from "./chat-context-snapshot.js";
import {
  reconcileOrphanedChatMessagesForSession,
  terminalizeChatMessageWithoutTask,
} from "./orphan-reconciler.js";
export { shouldReconcileOrphanedChatMessage } from "./orphan-reconciler.js";
import { buildTaskTraceBlock } from "./task-trace.js";
import { materializeLegacyVisionForDurableQueue } from "../tasks/media-inputs.js";
import { normalizeComposerContext } from "./composer-context.js";

const SHARED_BRAIN_CONVERSATION_MAX_MESSAGES = 14;
const SHARED_BRAIN_CONVERSATION_MAX_TOKENS = 3200;

function deriveChatTitle(
  rawTitle: string | undefined,
  message: string,
): string {
  const compact = (rawTitle ?? "").replace(/\s+/g, " ").trim();
  if (compact && !isGenericChatTitle(compact)) {
    return compact.slice(0, 200);
  }

  return normalizeChatTitle(message).slice(0, 96) || "Yeni sohbet";
}

function buildChatMetadata(metadata: Record<string, unknown> | undefined) {
  const base =
    metadata && typeof metadata === "object" && !Array.isArray(metadata)
      ? metadata
      : {};
  return normalizeLocalDerivedMetadata({
    ...base,
    channel: "chat",
  });
}

const CHAT_SESSION_PAGE_LIMIT = 20;
const INITIAL_CHAT_MESSAGE_PAGE_LIMIT = 30;
const OLDER_CHAT_MESSAGE_PAGE_LIMIT = 10;
const CHAT_MESSAGE_PAGE_LIMIT_MAX = 50;
const GENERIC_CHAT_TITLES = new Set(["yeni görev", "yeni sohbet"]);
const RECENT_DUPLICATE_CHAT_TURN_WINDOW_MS = 20_000;
const CHAT_TURN_ADMISSION_LOCK_TTL_MS = 30_000;
const CHAT_TURN_ADMISSION_WAIT_MS = 2_500;
const CHAT_TURN_ADMISSION_POLL_MS = 125;
const CHAT_MESSAGE_INLINE_CONTENT_MAX_BYTES = 64 * 1024;

type ChatSessionCursor = {
  timestamp: string;
  id: string;
};

type ChatMessageCursor = {
  timestamp: string;
  id: string;
};

function normalizeChatTitle(title: string | null | undefined) {
  return String(title ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

export function buildChatTurnAdmissionLockKey(input: {
  userId: string;
  sessionId: string;
  content: string;
  idempotencyKey?: string;
}): string | null {
  // İstemci idempotency anahtarı gönderiyorsa kilidi ona bağla: aynı isteğin
  // yeniden gönderimi kesin olarak yakalanır, kullanıcının bilerek tekrarladığı
  // ("evet", "devam et") turlar ise yeni anahtarla geldiği için engellenmez.
  const idempotencyKey = input.idempotencyKey?.trim();
  const normalizedContent = normalizeChatTitle(input.content).toLowerCase();
  if (!idempotencyKey && !normalizedContent) {
    return null;
  }
  const digest = createHash("sha256")
    .update(input.userId)
    .update("\0")
    .update(input.sessionId)
    .update("\0")
    .update(idempotencyKey ? `idem:${idempotencyKey}` : normalizedContent)
    .digest("hex")
    .slice(0, 32);
  return `lock:chat-turn:${digest}`;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isGenericChatTitle(title: string | undefined) {
  return GENERIC_CHAT_TITLES.has(normalizePlaceholderTitle(title));
}

function normalizePlaceholderTitle(value: string | undefined) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/[.!…]+$/g, "");
}

function compactSessionPreview(value: string | undefined, fallback: string) {
  const text = normalizeChatTitle(value) || fallback;
  if (text.length <= 120) {
    return text;
  }
  return `${text.slice(0, 119).trimEnd()}…`;
}

function compactMessagePreview(value: string | undefined, maxLength = 320) {
  const normalized = normalizeChatTitle(value);
  if (!normalized) {
    return null;
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function estimateMessageTokens(value: string) {
  const normalized = normalizeChatTitle(value);
  if (!normalized) {
    return 0;
  }
  return Math.max(1, Math.ceil(normalized.length / 4));
}

function shouldStoreChatMessageContentBlob(value: string): boolean {
  return Buffer.byteLength(value, "utf8") > CHAT_MESSAGE_INLINE_CONTENT_MAX_BYTES;
}

async function findRecentDuplicateChatTurn(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    content: string;
  },
) {
  const recentRows = await app.db
    .select()
    .from(chatMessages)
    .where(
      and(
        eq(chatMessages.sessionId, input.sessionId),
        eq(chatMessages.userId, input.userId),
      ),
    )
    .orderBy(desc(chatMessages.createdAt))
    .limit(8);
  const orderedRows = [...recentRows].reverse();
  const normalizedContent = normalizeChatTitle(input.content);
  if (!normalizedContent) {
    return null;
  }
  const now = Date.now();

  for (let index = orderedRows.length - 1; index >= 0; index -= 1) {
    const row = orderedRows[index];
    if (
      row.role !== "user" ||
      normalizeChatTitle(row.content) !== normalizedContent
    ) {
      continue;
    }
    const createdAtMs =
      row.createdAt instanceof Date
        ? row.createdAt.getTime()
        : new Date(row.createdAt).getTime();
    if (
      !Number.isFinite(createdAtMs) ||
      now - createdAtMs > RECENT_DUPLICATE_CHAT_TURN_WINDOW_MS
    ) {
      continue;
    }

    // Düz sohbet cevaplarının taskId'si yoktur. Daha önce burada taskId şartı
    // aranıyordu; bu yüzden görev üretmeyen turlarda mükerrer hiç yakalanmıyor
    // ve aynı soru ikinci kez baştan cevaplanıyordu.
    const assistantRow = orderedRows
      .slice(index + 1)
      .find((candidate) => candidate.role === "assistant");
    if (!assistantRow) {
      continue;
    }

    // Görev varsa iliştir; yoksa tur yine de mükerrerdir.
    let task: typeof tasks.$inferSelect | null = null;
    if (assistantRow.taskId) {
      const taskRows = await app.db
        .select()
        .from(tasks)
        .where(
          and(
            eq(tasks.id, assistantRow.taskId),
            eq(tasks.userId, input.userId),
          ),
        )
        .limit(1);
      task = taskRows[0] ?? null;
    }

    return {
      userMessage: row,
      assistantMessage: assistantRow,
      task,
    };
  }

  return null;
}

function shapeDuplicateChatTurnResponse(
  input: {
    userId: string;
    targetDeviceId?: string;
    content: string;
  },
  session: Awaited<ReturnType<typeof createChatSession>>,
  routeDecision: Awaited<ReturnType<typeof routeChatTurn>>,
  duplicateTurn: NonNullable<
    Awaited<ReturnType<typeof findRecentDuplicateChatTurn>>
  >,
) {
  // Görev üretmeyen sohbet turlarında task null olur; yanıt şekli korunur.
  const shapedTask = duplicateTurn.task
    ? shapeTaskFeedItem(duplicateTurn.task)
    : null;
  const shapedAssistantMessage = {
    ...shapeChatMessageForResponse(duplicateTurn.assistantMessage),
    taskId: duplicateTurn.assistantMessage.taskId,
    status: duplicateTurn.assistantMessage.status,
    content: duplicateTurn.assistantMessage.content,
  };
  const taskBrainRecord = readRecord(
    (shapedTask as Record<string, unknown> | null)?.brain,
  );
  const resultRecord = readRecord(
    (duplicateTurn.task as Record<string, unknown> | null)?.result,
  );
  return {
    session,
    userMessage: shapeChatMessageForResponse(duplicateTurn.userMessage),
    assistantMessage: shapedAssistantMessage,
    task: shapedTask,
    renderRecipe: resultRecord?.renderRecipe ?? null,
    routeDecision,
    delivery: buildChatDispatchDeliverySnapshot({
      task: shapedTask ?? {},
      routeDecision,
      requestedTargetDeviceId: input.targetDeviceId,
    }),
    brain: {
      profileMode: "elyan_managed",
      serverBrainReady: routeDecision.route === "server_brain",
      firstDeltaMs: readNumber(taskBrainRecord, "firstDeltaMs"),
      groundingUsed: readBoolean(taskBrainRecord, "groundingUsed"),
      documentSourceCount: readNumber(taskBrainRecord, "documentSourceCount"),
      webGroundingUsed: readBoolean(taskBrainRecord, "webGroundingUsed"),
      webSourceCount: readNumber(taskBrainRecord, "webSourceCount"),
      estimatedCostBucket: "deduped_inflight",
    },
    // Tam kullanım bakiyesi bootstrap/SSE üzerinden güncellenir. Chat POST'u
    // tam billing özetini beklemez; bu, her mesajı çoklu ağır sorguya bağlar.
    usage: null,
    dispatched: false,
    reused: true,
    deduped: true,
  };
}

function titleFromChatPreview(title: string | undefined, preview: string) {
  const normalizedTitle = normalizeChatTitle(title);
  if (normalizedTitle && !isGenericChatTitle(normalizedTitle)) {
    return compactSessionPreview(normalizedTitle, preview);
  }
  return compactSessionPreview(preview, "Yeni sohbet");
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(
  record: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readNumber(
  record: Record<string, unknown> | null,
  key: string,
): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readBoolean(
  record: Record<string, unknown> | null,
  key: string,
): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function readArray(
  record: Record<string, unknown> | null,
  key: string,
): unknown[] {
  const value = record?.[key];
  return Array.isArray(value) ? value : [];
}

function clipCompactText(value: string, maxLength: number) {
  const normalized = normalizeChatTitle(value);
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function scrubCompactText(value: string, maxLength: number) {
  return clipCompactText(value, maxLength)
    .replace(/https?:\/\/\S+/gi, "[url]")
    .replace(/(?:\/Users\/|\/home\/|C:\\Users\\)[^\s]+/gi, "[path]")
    .replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, "[email]")
    .replace(/\b(?:\+?\d[\d\s().-]{7,}\d)\b/g, "[number]");
}

function sanitizeCompactContextRecord(value: unknown) {
  const record = readRecord(value);
  return record
    ? sanitizeInboundContextRecord(record, {
        maxDepth: 2,
        maxStringLength: 120,
      })
    : null;
}

function sanitizeCompactRecentMessages(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null)
    .map((item) => {
      const role = readString(item, "role");
      const content = readString(item, "content");
      if (
        (role !== "user" && role !== "assistant" && role !== "system") ||
        !content
      ) {
        return null;
      }
      return {
        role,
        content: scrubCompactText(content, 280),
      };
    })
    .filter(
      (
        item,
      ): item is { role: "system" | "user" | "assistant"; content: string } =>
        item != null,
    )
    .slice(-10);
}

function sanitizeCompactTurns(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null)
    .map((item) => {
      const at = readString(item, "at");
      const user = readString(item, "user");
      const assistant = readString(item, "assistant");
      const workload = readString(item, "workload");
      if (!user) {
        return null;
      }
      return {
        ...(at ? { at } : {}),
        user: scrubCompactText(user, 280),
        ...(assistant ? { assistant: scrubCompactText(assistant, 320) } : {}),
        ...(workload ? { workload: scrubCompactText(workload, 80) } : {}),
      };
    })
    .filter(
      (
        item,
      ): item is {
        at?: string;
        user: string;
        assistant?: string;
        workload?: string;
      } => item != null,
    )
    .slice(0, 12);
}

function sanitizeCompactSalience(value: unknown) {
  const record = readRecord(value);
  if (!record) {
    return null;
  }
  const topics = sanitizeStringList(record.topics, 8, 80);
  const entities = sanitizeStringList(record.entities, 10, 80);
  const userIntent = readString(record, "userIntent");
  const assistantCommitment = readString(record, "assistantCommitment");
  const emotionalTone = readString(record, "emotionalTone");
  const unresolved = readBoolean(record, "unresolved");
  const updatedAt = readString(record, "updatedAt");
  const sanitized = {
    ...(topics.length > 0 ? { topics } : {}),
    ...(entities.length > 0 ? { entities } : {}),
    ...(userIntent ? { userIntent: scrubCompactText(userIntent, 160) } : {}),
    ...(assistantCommitment
      ? { assistantCommitment: scrubCompactText(assistantCommitment, 160) }
      : {}),
    ...(emotionalTone
      ? { emotionalTone: scrubCompactText(emotionalTone, 80) }
      : {}),
    ...(unresolved != null ? { unresolved } : {}),
    ...(updatedAt ? { updatedAt } : {}),
  };
  return Object.keys(sanitized).length > 0 ? sanitized : null;
}

function sanitizeStringList(value: unknown, limit = 4, maxLength = 120) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) =>
      typeof item === "string" ? scrubCompactText(item, maxLength) : "",
    )
    .filter(Boolean)
    .slice(0, limit);
}

function sanitizeRollingSummaryRecord(value: unknown) {
  const record = readRecord(value);
  if (!record) {
    return null;
  }
  const sanitized = {
    ...(readString(record, "userGoal")
      ? { userGoal: scrubCompactText(readString(record, "userGoal")!, 220) }
      : {}),
    ...(readString(record, "assistantState")
      ? {
          assistantState: scrubCompactText(
            readString(record, "assistantState")!,
            220,
          ),
        }
      : {}),
    ...(sanitizeStringList(record.openLoops, 4, 140).length > 0
      ? { openLoops: sanitizeStringList(record.openLoops, 4, 140) }
      : {}),
    ...(sanitizeStringList(record.contextNotes, 4, 140).length > 0
      ? { contextNotes: sanitizeStringList(record.contextNotes, 4, 140) }
      : {}),
    ...(readString(record, "updatedAt")
      ? { updatedAt: readString(record, "updatedAt") }
      : {}),
  };
  return Object.keys(sanitized).length > 0 ? sanitized : null;
}

function sanitizeAttachmentDigest(value: unknown) {
  const record = readRecord(value);
  if (!record) {
    return null;
  }
  const kinds = sanitizeStringList(record.kinds, 4, 40);
  const intentHints = sanitizeStringList(record.intentHints, 4, 40);
  const summaries = sanitizeStringList(record.summaries, 3, 140);
  const count = readNumber(record, "count");
  const sanitized = {
    ...(count != null ? { count } : {}),
    ...(kinds.length > 0 ? { kinds } : {}),
    ...(intentHints.length > 0 ? { intentHints } : {}),
    ...(summaries.length > 0 ? { summaries } : {}),
  };
  return Object.keys(sanitized).length > 0 ? sanitized : null;
}

function sanitizeWorldSignalDigest(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null)
    .map((item) => {
      const signalId = readString(item, "signalId");
      const kind = readString(item, "kind");
      const summary = readString(item, "summary");
      const confidence = readNumber(item, "confidence");
      const fusionEvidenceCount = readNumber(item, "fusionEvidenceCount");
      const conflictSuppressedCount = readNumber(
        item,
        "conflictSuppressedCount",
      );
      const createdAt = readString(item, "createdAt");
      const facts = sanitizeCompactContextRecord(item.facts);
      const privacy = sanitizeCompactContextRecord(item.privacy);
      if (!kind || !summary) {
        return null;
      }
      return {
        ...(signalId ? { signalId } : {}),
        kind,
        summary: scrubCompactText(summary, 140),
        ...(confidence != null ? { confidence } : {}),
        ...(fusionEvidenceCount != null ? { fusionEvidenceCount } : {}),
        ...(conflictSuppressedCount != null ? { conflictSuppressedCount } : {}),
        ...(createdAt ? { createdAt } : {}),
        ...(facts ? { facts } : {}),
        ...(privacy ? { privacy } : {}),
      };
    })
    .filter(Boolean)
    .slice(0, 10);
}

function sanitizeMobileContextCapabilities(value: unknown) {
  const record = readRecord(value);
  if (!record) return null;
  const capabilities = Object.fromEntries(
    [
      "healthEnabled",
      "locationEnabled",
      "calendarEnabled",
      "healthSignalsAvailable",
      "locationSignalsAvailable",
      "calendarSignalsAvailable",
    ]
      .filter((key) => typeof record[key] === "boolean")
      .map((key) => [key, record[key]]),
  );
  return Object.keys(capabilities).length > 0 ? capabilities : null;
}

function isWorldSignalAllowedByCapabilities(
  kind: string,
  capabilities: Record<string, unknown> | null,
  privacy: Record<string, unknown> | null,
) {
  const normalizedKind = kind.trim().toLowerCase();
  const legacyCapturePermission =
    !capabilities && privacy?.backendPlaintextAllowed === true;
  if (normalizedKind === "health") {
    return capabilities
      ? capabilities.healthEnabled === true
      : legacyCapturePermission;
  }
  if (normalizedKind === "location") {
    return capabilities
      ? capabilities.locationEnabled === true
      : legacyCapturePermission;
  }
  if (normalizedKind === "calendar") {
    return capabilities
      ? capabilities.calendarEnabled === true
      : legacyCapturePermission;
  }
  return true;
}

function buildSanitizedCompactContext(value: unknown) {
  const record = readRecord(value);
  if (!record) {
    return null;
  }
  const recentMessages = sanitizeCompactRecentMessages(record.recentMessages);
  const turns = sanitizeCompactTurns(record.turns);
  const salience = sanitizeCompactSalience(record.salience);
  const rollingSummary = sanitizeRollingSummaryRecord(record.rollingSummary);
  const attachmentDigest = sanitizeAttachmentDigest(record.attachmentDigest);
  const derivedContextDigestRecord = readRecord(record.derivedContextDigest);
  const worldSignals = sanitizeWorldSignalDigest(
    derivedContextDigestRecord?.worldSignals,
  );
  const previousDigest = readRecord(derivedContextDigestRecord?.previousDigest);
  const derivedContextDigest = {
    ...(worldSignals.length > 0 ? { worldSignals } : {}),
    ...(sanitizeAttachmentDigest(derivedContextDigestRecord?.attachments)
      ? {
          attachments: sanitizeAttachmentDigest(
            derivedContextDigestRecord?.attachments,
          ),
        }
      : {}),
    ...(previousDigest ? { previousDigest } : {}),
  };
  const responseVerbosityHint = readString(record, "responseVerbosityHint");
  const wantsLongForm = readBoolean(record, "wantsLongForm");
  const lastAssistantBlocksDigest = readString(
    record,
    "lastAssistantBlocksDigest",
  );
  const mobileContextCapabilities = sanitizeMobileContextCapabilities(
    record.mobileContextCapabilities,
  );
  const compactContext = {
    ...(recentMessages.length > 0 ? { recentMessages } : {}),
    ...(turns.length > 0 ? { turns } : {}),
    ...(salience ? { salience } : {}),
    ...(rollingSummary ? { rollingSummary } : {}),
    ...(attachmentDigest ? { attachmentDigest } : {}),
    ...(Object.keys(derivedContextDigest).length > 0
      ? { derivedContextDigest }
      : {}),
    ...(responseVerbosityHint ? { responseVerbosityHint } : {}),
    ...(wantsLongForm != null ? { wantsLongForm } : {}),
    ...(lastAssistantBlocksDigest
      ? {
          lastAssistantBlocksDigest: scrubCompactText(
            lastAssistantBlocksDigest,
            280,
          ),
        }
      : {}),
    ...(mobileContextCapabilities &&
    Object.keys(mobileContextCapabilities).length > 0
      ? { mobileContextCapabilities }
      : {}),
  };
  return Object.keys(compactContext).length > 0 ? compactContext : null;
}

function readChatContextRecord(metadata: Record<string, unknown> | undefined) {
  return readRecord(readRecord(metadata)?.chatContext);
}

function inferCompactContextLongFormHint(
  metadata: Record<string, unknown> | undefined,
) {
  const compactContext = buildSanitizedCompactContext(
    readRecord(metadata)?.compactContext,
  );
  if (compactContext && compactContext.wantsLongForm === true) {
    return true;
  }
  const responseHint = normalizePlaceholderTitle(
    readString(compactContext, "responseVerbosityHint") ??
      readString(readRecord(metadata), "responseVerbosityHint") ??
      "",
  );
  return responseHint === "expanded_when_needed" || responseHint === "detailed";
}

function buildSessionChatContextMetadata(
  metadata: Record<string, unknown> | undefined,
) {
  const compactContext = buildSanitizedCompactContext(
    readRecord(metadata)?.compactContext,
  );
  const existingChatContext = readChatContextRecord(metadata) ?? {};
  const rollingSummary =
    sanitizeRollingSummaryRecord(compactContext?.rollingSummary) ??
    sanitizeRollingSummaryRecord(existingChatContext.rollingSummary);
  const lastAssistantBlocksDigest =
    readString(compactContext, "lastAssistantBlocksDigest") ??
    readString(existingChatContext, "lastAssistantBlocksDigest");
  const lastDerivedContextDigest =
    readRecord(compactContext?.derivedContextDigest) ??
    readRecord(existingChatContext.lastDerivedContextDigest);
  return {
    ...(rollingSummary ? { rollingSummary } : {}),
    ...(lastAssistantBlocksDigest ? { lastAssistantBlocksDigest } : {}),
    ...(lastDerivedContextDigest ? { lastDerivedContextDigest } : {}),
  };
}

export async function enrichChatMetadataForRequest(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    targetDeviceId?: string;
    metadata?: Record<string, unknown>;
  },
) {
  const base = buildChatMetadata(input.metadata);
  const compactContext = buildSanitizedCompactContext(base.compactContext);
  const existingDerivedDigest = readRecord(
    compactContext?.derivedContextDigest,
  );
  const mobileContextCapabilities = sanitizeMobileContextCapabilities(
    compactContext?.mobileContextCapabilities,
  );
  let freshWorldSignalDigest: Record<string, unknown>[] = [];
  const freshSignals = await listFreshWorldSignals(app, {
    userId: input.userId,
    sessionId: input.sessionId,
    // `targetDeviceId` is the execution target (desktop/shared brain), not the
    // phone that observed the signal. Scope by authenticated user + current
    // session, then admit unscoped account signals only through current
    // per-kind capability truth or legacy capture-time derived-data consent.
    includeUnscopedSession: true,
    limit: 48,
    maxAgeHours: 72,
  });
  freshWorldSignalDigest = fuseWorldSignalRecordsByKind(freshSignals)
    .filter((signal) =>
      isWorldSignalAllowedByCapabilities(
        signal.kind,
        mobileContextCapabilities,
        signal.privacy,
      ),
    )
    .map((signal) => ({
      signalId: signal.signalId,
      kind: signal.kind,
      summary: scrubCompactText(signal.summary, 220),
      confidence: signal.confidence,
      fusionEvidenceCount: signal.fusionEvidenceCount,
      conflictSuppressedCount: signal.conflictSuppressedCount,
      createdAt: signal.createdAt.toISOString(),
      facts: sanitizeCompactContextRecord(signal.facts) ?? {},
      privacy: sanitizeCompactContextRecord(signal.privacy) ?? {},
    }));

  // Current permission/session truth is authoritative. Never carry a prior
  // worldSignals array forward when the fresh authorized set is empty (for
  // example after the user disables Health/Location/Calendar access).
  const existingDerivedDigestWithoutWorldSignals = existingDerivedDigest
    ? Object.fromEntries(
        Object.entries(existingDerivedDigest).filter(
          ([key]) => key !== "worldSignals",
        ),
      )
    : {};
  const mergedDerivedContextDigest = {
    ...existingDerivedDigestWithoutWorldSignals,
    ...(freshWorldSignalDigest.length > 0
      ? { worldSignals: freshWorldSignalDigest }
      : {}),
  };
  const chatContext = {
    ...buildSessionChatContextMetadata(base),
    ...(mobileContextCapabilities ? { mobileContextCapabilities } : {}),
    ...(Object.keys(mergedDerivedContextDigest).length > 0
      ? { lastDerivedContextDigest: mergedDerivedContextDigest }
      : {}),
    updatedAt: new Date().toISOString(),
  };

  return normalizeLocalDerivedMetadata({
    ...base,
    ...(compactContext
      ? {
          compactContext: {
            ...compactContext,
            ...(Object.keys(mergedDerivedContextDigest).length > 0
              ? { derivedContextDigest: mergedDerivedContextDigest }
              : {}),
          },
        }
      : {}),
    responseVerbosityHint:
      readString(compactContext, "responseVerbosityHint") ??
      readString(readRecord(base), "responseVerbosityHint") ??
      (inferCompactContextLongFormHint(base)
        ? "expanded_when_needed"
        : "concise"),
    chatContext,
  });
}

function buildChatSessionMetadata(
  metadata: Record<string, unknown> | undefined,
  input: {
    titleHint?: string;
    preview?: string;
    lastMessageRole?: string;
    lastMessageId?: string;
    lastMessageAt?: Date;
  },
) {
  const base: Record<string, unknown> =
    metadata && typeof metadata === "object" && !Array.isArray(metadata)
      ? (metadata as Record<string, unknown>)
      : {};
  const existingChatHistory = readRecord(base.chatHistory);
  return normalizeLocalDerivedMetadata({
    ...base,
    chatHistory: {
      ...(existingChatHistory ?? {}),
      ...(input.titleHint ? { titleHint: input.titleHint } : {}),
      ...(input.preview ? { preview: input.preview } : {}),
      ...(input.lastMessageRole
        ? { lastMessageRole: input.lastMessageRole }
        : {}),
      ...(input.lastMessageId ? { lastMessageId: input.lastMessageId } : {}),
      ...(input.lastMessageAt
        ? { lastMessageAt: input.lastMessageAt.toISOString() }
        : {}),
    },
    ...(input.titleHint ? { titleHint: input.titleHint } : {}),
    ...(input.preview ? { preview: input.preview } : {}),
    ...(input.preview ? { lastMessagePreview: input.preview } : {}),
    ...(input.lastMessageRole
      ? { lastMessageRole: input.lastMessageRole }
      : {}),
    ...(input.lastMessageId ? { lastMessageId: input.lastMessageId } : {}),
    ...(input.lastMessageAt
      ? { lastMessageAt: input.lastMessageAt.toISOString() }
      : {}),
  });
}

function readChatSessionPreview(
  metadata: unknown,
  title: string | null | undefined,
) {
  const record = readRecord(metadata);
  const chatHistory = readRecord(record?.chatHistory);
  const preview =
    readString(chatHistory, "preview") ??
    readString(record, "preview") ??
    readString(record, "lastMessagePreview") ??
    readString(record, "subtitle") ??
    readString(record, "summary") ??
    normalizeChatTitle(title) ??
    "Yeni sohbet";
  return compactSessionPreview(preview, "Sohbet");
}

async function hydrateMessageContent(
  app: FastifyInstance,
  input: {
    id: string;
    userId: string;
    content: string;
    contentBlobId?: string | null;
  },
) {
  if (!input.contentBlobId) {
    return input.content;
  }

  return (
    (await app.services?.blobs?.hydrateTextForOwner({
      blobId: input.contentBlobId,
      userId: input.userId,
      ownerType: "chat_message",
      ownerId: input.id,
    })) ?? input.content
  );
}

function shapeChatMessageForResponse<
  T extends typeof chatMessages.$inferSelect,
>(message: T): T & { blocks?: AssistantMessageBlock[]; content?: string } {
  const shaped = shapeAssistantMessagePayload(message) as T & {
    blocks?: AssistantMessageBlock[];
    content?: string;
  };
  const record = shaped as Record<string, unknown>;
  if (
    record.metadata &&
    typeof record.metadata === "object" &&
    !Array.isArray(record.metadata)
  ) {
    record.metadata = sanitizePublicInferenceValue(record.metadata);
  }
  return shaped;
}

function resolveChatAcceptanceFailure(error: unknown): {
  code: string;
  message: string;
} {
  if (error instanceof AppError) {
    return {
      code: error.code,
      message: error.message || "Yanıt başlatılamadı. Lütfen tekrar dene.",
    };
  }
  return {
    code: "chat_acceptance_failed",
    message: "Yanıt başlatılamadı. Lütfen tekrar dene.",
  };
}

function shapeChatSessionForResponse<
  T extends typeof chatSessions.$inferSelect,
>(session: T): T {
  const shaped = { ...session } as T;
  const record = shaped as Record<string, unknown>;
  if (
    record.metadata &&
    typeof record.metadata === "object" &&
    !Array.isArray(record.metadata)
  ) {
    record.metadata = sanitizePublicInferenceValue(record.metadata);
  }
  return shaped;
}

function encodeCursor(cursor: ChatSessionCursor | ChatMessageCursor) {
  return Buffer.from(JSON.stringify(cursor), "utf8").toString("base64url");
}

function normalizeChatMessagePageLimit(input: {
  requestedLimit?: number;
  cursor?: string;
}) {
  const fallbackLimit = input.cursor?.trim()
    ? OLDER_CHAT_MESSAGE_PAGE_LIMIT
    : INITIAL_CHAT_MESSAGE_PAGE_LIMIT;
  const requestedLimit =
    typeof input.requestedLimit === "number" &&
    Number.isFinite(input.requestedLimit)
      ? Math.round(input.requestedLimit)
      : null;
  if (requestedLimit == null || requestedLimit <= 0) {
    return fallbackLimit;
  }

  return Math.max(1, Math.min(requestedLimit, CHAT_MESSAGE_PAGE_LIMIT_MAX));
}

/**
 * Ham `sql` şablonunda kullanılabilir keyset zaman damgası.
 *
 * Drizzle, TİPLİ bir kolonla karşılaştırırken kolonun dönüştürücüsünü uygular;
 * ham `sql` parçasında ise tip bilgisi YOKTUR ve `Date` nesnesi doğrudan
 * postgres-js'e gider. Sürücü onu serileştiremez:
 *   TypeError: The "string" argument must be of type string or an instance of
 *   Buffer or ArrayBuffer. Received an instance of Date
 *
 * Canlı sonuç 500'dü (2026-08-13, `GET /v1/chat/sessions?cursor=…`): kullanıcı
 * ilk sayfadan sonrasını HİÇ göremiyordu. Aynı hata eski mesaj sayfalamasında
 * da vardı, yani sohbet geçmişinde yukarı kaydırma da kırıktı.
 *
 * ISO metin + açık `::timestamptz` cast'i hem sürücüyü hem sorgu planlayıcısını
 * belirsizlikte bırakmaz. Bozuk imleçte `null` döner: sayfalama koşulu hiç
 * eklenmez ve kullanıcı boş sayfa yerine ilk sayfayı görür.
 */
function cursorTimestampSql(rawTimestamp: unknown) {
  const parsed = new Date(String(rawTimestamp ?? ""));
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  const iso = parsed.toISOString();
  return sql`${iso}::timestamptz`;
}

function decodeCursor<T extends ChatSessionCursor | ChatMessageCursor>(
  rawCursor: string | undefined,
): T | null {
  const normalized = rawCursor?.trim() ?? "";
  if (!normalized) {
    return null;
  }
  try {
    const parsed = JSON.parse(
      Buffer.from(normalized, "base64url").toString("utf8"),
    ) as T;
    if (
      !parsed ||
      typeof parsed !== "object" ||
      typeof parsed.timestamp !== "string" ||
      typeof parsed.id !== "string"
    ) {
      return null;
    }
    const timestamp = new Date(parsed.timestamp);
    if (Number.isNaN(timestamp.getTime())) {
      return null;
    }
    return {
      timestamp: timestamp.toISOString(),
      id: parsed.id.trim(),
    } as T;
  } catch {
    return null;
  }
}

async function maybeInjectDueProactiveOpeningMessage(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    cursor?: string;
    enabled: boolean;
  },
) {
  if (!input.enabled || input.cursor?.trim()) {
    return;
  }

  await processDueProactiveTriggerForSession(app, {
    userId: input.userId,
    sessionId: input.sessionId,
    compose: async (trigger) => buildProactiveOpeningCompose(trigger),
  }).catch((error) => {
    app.log.debug?.(
      {
        error:
          error instanceof Error
            ? error.message
            : "proactive_opening_injection_failed",
      },
      "proactive opening message injection skipped",
    );
  });
}

function chatPayloadSessionIdCondition(sessionId: string) {
  return sql`${tasks.payload} -> 'metadata' -> 'chat' ->> 'sessionId' = ${sessionId}`;
}

function placeholderMobileChatTaskCondition(before?: Date) {
  const beforeCondition = before
    ? sql`and ${tasks.updatedAt} < ${before}`
    : sql``;
  return sql`
    lower(trim(coalesce(${tasks.title}, ''))) = 'yeni görev'
    and regexp_replace(
      lower(trim(coalesce(${tasks.summary}, ''))),
      '[.!…]+$',
      '',
      'g'
    ) in (
      '',
      'yanıtı hazırlıyorum',
      'hazırlanıyor',
      'beklemede',
      'sırada',
      'son adımı netleştiriyorum',
      'düşünüyorum'
    )
    and ${tasks.error} is null
    and ${tasks.approvalRequest} is null
    ${beforeCondition}
  `;
}

function presentationForRoute(
  routeDecision: { route?: string } | null | undefined,
): "chat" | "task" {
  void routeDecision;
  return "chat";
}

function shouldDeferChatContextHydration(input: {
  routeDecision: { route?: string; selectedWorkload?: string | null };
  metadata: Record<string, unknown>;
  ephemeralVision?: EphemeralVisionCarrier;
}) {
  if (input.routeDecision.route !== "server_brain") return false;

  const workload = String(input.routeDecision.selectedWorkload ?? "").trim();
  const needsVisualContext =
    workload === "image_analyze" || workload === "vision_reasoning";
  const hasEphemeralVision = countDistinctEphemeralImages(input.ephemeralVision) > 0;
  const hasMediaReferences =
    Array.isArray(input.metadata.mediaInputRefs) &&
    input.metadata.mediaInputRefs.length > 0;
  const hasAttachmentMetadata =
    extractAttachmentMetadataCarrier(input.metadata) != null;

  // Plain text turns can use the compact client snapshot immediately and let
  // the generation worker hydrate authoritative history/context in parallel.
  // Any media or structured visual workload keeps the request-time context so
  // attachment and continuation semantics remain exact.
  return !(
    needsVisualContext ||
    hasEphemeralVision ||
    hasMediaReferences ||
    hasAttachmentMetadata
  );
}

export function buildChatDispatchDeliverySnapshot(input: {
  task: {
    id?: string;
    targetDeviceId?: string | null;
    deliveryState?: string | null;
    deliveryAttemptCount?: number | null;
    dispatchLeaseId?: string | null;
    dispatchLeaseExpiresAt?: Date | string | null;
    dispatchAckAt?: Date | string | null;
    lastAckAt?: Date | string | null;
    lastDispatchAttemptAt?: Date | string | null;
  };
  routeDecision: {
    route?: string;
    taskRoute?: {
      needsDesktop?: boolean;
      operationalRoute?: string;
    } | null;
  } | null;
  requestedTargetDeviceId?: string;
}) {
  const route = input.routeDecision?.route ?? "unavailable";
  const requiresDesktopAck =
    input.routeDecision?.taskRoute?.needsDesktop === true ||
    input.routeDecision?.taskRoute?.operationalRoute === "desktop_runtime" ||
    route === "desktop_runtime" ||
    route === "pairing_required" ||
    route === "unavailable";

  return {
    taskId: input.task.id,
    route,
    presentation: presentationForRoute(input.routeDecision),
    targetDeviceId: input.task.targetDeviceId ?? null,
    requestedTargetDeviceId: input.requestedTargetDeviceId ?? null,
    requiresDesktopAck,
    deliveryState: input.task.deliveryState ?? null,
    deliveryAttemptCount: input.task.deliveryAttemptCount ?? 0,
    dispatchLeaseId: input.task.dispatchLeaseId ?? null,
    dispatchLeaseExpiresAt: input.task.dispatchLeaseExpiresAt ?? null,
    dispatchAckAt: input.task.dispatchAckAt ?? null,
    lastAckAt: input.task.lastAckAt ?? input.task.dispatchAckAt ?? null,
    lastDispatchAttemptAt: input.task.lastDispatchAttemptAt ?? null,
  };
}

export function resolveChatSessionTargetDeviceId(
  routeDecision:
    | {
        route?: string;
        targetDeviceId?: string;
        taskRoute?: {
          needsDesktop?: boolean;
        } | null;
      }
    | null
    | undefined,
  requestedTargetDeviceId?: string,
) {
  const needsDesktop =
    routeDecision?.taskRoute?.needsDesktop ??
    (routeDecision?.route === "desktop_runtime" ||
      routeDecision?.route === "pairing_required" ||
      routeDecision?.route === "unavailable");
  if (!needsDesktop) {
    return undefined;
  }
  return routeDecision?.targetDeviceId?.trim() || requestedTargetDeviceId;
}

type SharedBrainConversationItem = {
  role: "system" | "user" | "assistant";
  content: string;
};

type ChatAttachmentRow = {
  id?: string;
  role: string;
  status?: string | null;
  content?: string;
  metadata?: unknown;
  createdAt?: Date | string | null;
};

type LoadedChatContext = {
  conversation: SharedBrainConversationItem[];
  turns: ChatContextSnapshotTurn[];
  attachmentCandidates: AttachmentContextCandidate[];
};

function estimateConversationTokens(text: string) {
  return estimateTextTokens(text);
}

function getEstimatedMaxTokensForChatWorkload(
  workload: SharedBrainWorkload,
  brainProfileInput: unknown,
): number {
  const brainProfile = normalizePlanBrainProfile(brainProfileInput);
  const baseTokens = getSharedBrainWorkloadProfile(workload).maxTokens;
  if (brainProfile.tier !== "premium" && brainProfile.reasoningMultiplier < 5) {
    return baseTokens;
  }

  const scaledTokens = Math.round(baseTokens * brainProfile.maxTokenScale);
  const maxTokensByWorkload =
    workload === "planning"
      ? 640
      : workload === "document_analysis"
        ? 480
        : workload === "mobile_chat_balanced"
          ? 360
          : workload === "mobile_chat_fast"
            ? 220
            : baseTokens;

  return Math.max(baseTokens, Math.min(scaledTokens, maxTokensByWorkload));
}

export function estimatePendingChatTokenDebit(input: {
  route?: string | null;
  reused?: boolean;
  taskStatus?: string | null;
  content: string;
  workload: SharedBrainWorkload;
  brainProfile?: unknown;
}): number {
  if (input.reused || input.route !== "server_brain") {
    return 0;
  }

  if (
    ["completed", "failed", "canceled"].includes(
      String(input.taskStatus ?? "").trim(),
    )
  ) {
    return 0;
  }

  const userInputTokens = estimateConversationTokens(input.content);

  return calculateBillablePlanTokens({
    surface: "chat",
    userInputTokens,
    promptTokens: userInputTokens,
    completionTokens: getEstimatedMaxTokensForChatWorkload(
      input.workload,
      input.brainProfile,
    ),
    workload: input.workload,
  }).billableTokens;
}

export function trimConversationForSharedBrain(
  items: SharedBrainConversationItem[],
  input: {
    maxMessages?: number;
    maxTokens?: number;
  } = {},
) {
  const maxMessages =
    input.maxMessages ?? SHARED_BRAIN_CONVERSATION_MAX_MESSAGES;
  const maxTokens = input.maxTokens ?? SHARED_BRAIN_CONVERSATION_MAX_TOKENS;
  const nonSystem = items.filter((item) => item.role !== "system");
  const recent = nonSystem.slice(-maxMessages);
  const selected: SharedBrainConversationItem[] = [];
  let usedTokens = 0;

  for (let index = recent.length - 1; index >= 0; index -= 1) {
    const item = recent[index];
    const itemTokens = estimateConversationTokens(item.content);
    if (selected.length === 0 && itemTokens > maxTokens) {
      selected.push({
        ...item,
        content: item.content.slice(0, maxTokens * 4),
      });
      break;
    }
    if (selected.length > 0 && usedTokens + itemTokens > maxTokens) {
      continue;
    }
    selected.push(item);
    usedTokens += itemTokens;
  }

  return selected.reverse();
}

function attachmentCandidateTimestamp(value: Date | string | null | undefined) {
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  return undefined;
}

function attachmentCandidateKey(candidate: AttachmentContextCandidate) {
  return JSON.stringify(candidate.metadata);
}

export function extractAttachmentCandidatesFromChatRows(
  rows: ChatAttachmentRow[],
): AttachmentContextCandidate[] {
  const selected: AttachmentContextCandidate[] = [];
  const seen = new Set<string>();

  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index];
    const metadata =
      row.metadata &&
      typeof row.metadata === "object" &&
      !Array.isArray(row.metadata)
        ? extractAttachmentMetadataCarrier(
            row.metadata as Record<string, unknown>,
          )
        : null;
    if (!metadata) {
      continue;
    }
    if (row.role !== "user" && metadata.visionBlock == null) {
      continue;
    }

    const timestamp = attachmentCandidateTimestamp(row.createdAt);
    const candidate: AttachmentContextCandidate = {
      ...(typeof row.id === "string" && row.id.trim()
        ? { messageId: row.id.trim() }
        : {}),
      ...(timestamp ? { createdAt: timestamp } : {}),
      ...(typeof row.content === "string" && row.content.trim()
        ? { prompt: row.content.trim() }
        : {}),
      metadata,
    };
    const key = attachmentCandidateKey(candidate);
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    selected.push(candidate);
    if (selected.length >= 3) {
      break;
    }
  }

  return selected;
}

async function loadChatConversation(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    limit?: number;
  },
): Promise<LoadedChatContext> {
  const rows = await app.db
    .select({
      id: chatMessages.id,
      role: chatMessages.role,
      content: chatMessages.content,
      contentBlobId: chatMessages.contentBlobId,
      status: chatMessages.status,
      metadata: chatMessages.metadata,
      createdAt: chatMessages.createdAt,
    })
    .from(chatMessages)
    .where(
      and(
        eq(chatMessages.sessionId, input.sessionId),
        eq(chatMessages.userId, input.userId),
      ),
    )
    // Read the newest window first. An ascending LIMIT keeps the oldest
    // messages forever and silently drops the active part of long sessions.
    .orderBy(desc(chatMessages.createdAt))
    .limit(input.limit ?? 32);

  const hydratedRows = await Promise.all(
    rows.map(async (row) => ({
      ...row,
      userId: input.userId,
      content: await hydrateMessageContent(app, {
        ...row,
        userId: input.userId,
      }),
    })),
  );
  const chronologicalRows = hydratedRows.reverse();
  const turns = chronologicalRows
    .filter(
      (row): row is typeof row & { role: "user" | "assistant" } =>
        row.role === "user" || row.role === "assistant",
    )
    .map((row) => {
      const metadata = readRecord(row.metadata);
      const rawBlocks = Array.isArray(metadata?.blocks)
        ? metadata.blocks
        : [];
      const normalizedBlocks =
        row.role === "assistant"
          ? normalizeAssistantMessageBlocks({ blocks: rawBlocks })
          : [];
      const blockTypes = Array.from(
        new Set(normalizedBlocks.map((block) => block.type)),
      );
      const blockDigest = rawBlocks.length
        ? createHash("sha256")
            .update(JSON.stringify(rawBlocks))
            .digest("hex")
            .slice(0, 32)
        : null;
      const content =
        row.role === "assistant"
          ? visibleTextFromStoredAssistantBlocks(normalizedBlocks) || row.content
          : row.content;
      return {
        messageId: row.id,
        role: row.role,
        content,
        status: row.status,
        createdAt:
          row.createdAt instanceof Date
            ? row.createdAt.toISOString()
            : new Date(row.createdAt).toISOString(),
        blockDigest,
        blockTypes,
      } satisfies ChatContextSnapshotTurn;
    });

  return {
    conversation: trimConversationForSharedBrain(
      turns.map((turn) => ({
        role: turn.role,
        content: turn.content,
      })),
    ),
    turns,
    attachmentCandidates: extractAttachmentCandidatesFromChatRows(
      chronologicalRows as ChatAttachmentRow[],
    ),
  };
}

function visibleTextFromStoredAssistantBlocks(
  blocks: AssistantMessageBlock[],
): string {
  const visible = blocks
    .filter(
      (block) =>
        (block as { visibility?: unknown }).visibility !==
        "assistant_internal_by_default",
    )
    .map((block) => {
      const record = block as Record<string, unknown>;
      const data = readRecord(record.data) ?? record;
      if (block.type === "text") {
        return String(record.markdown ?? data.markdown ?? "").trim();
      }
      if (block.type === "summary") {
        return String(data.summary ?? record.summary ?? "").trim();
      }
      if (block.type === "status") {
        return String(data.detail ?? record.detail ?? data.title ?? record.title ?? "").trim();
      }
      if (block.type === "next_steps") {
        const items = Array.isArray(data.items) ? data.items : [];
        return items.length > 0
          ? items.map((item) => `• ${String(item)}`).join("\n")
          : String(data.title ?? record.title ?? "").trim();
      }
      return String(
        data.summary ??
          data.title ??
          record.summary ??
          record.title ??
          "",
      ).trim();
    })
    .filter(Boolean);
  return visible.join("\n\n").replace(/\s+/g, " ").trim();
}

async function assertOwnedChatSession(
  app: FastifyInstance,
  userId: string,
  sessionId: string,
) {
  const session = await findOwnedChatSession(app, userId, sessionId);

  if (!session) {
    throw notFound("Chat session not found");
  }

  return session;
}

async function findOwnedChatSession(
  app: FastifyInstance,
  userId: string,
  sessionId: string,
) {
  const rows = await app.db
    .select()
    .from(chatSessions)
    .where(and(eq(chatSessions.id, sessionId), eq(chatSessions.userId, userId)))
    .limit(1);

  const session = rows[0];
  return session ?? null;
}

function readRouteContinuity(
  metadata: unknown,
): "server_brain" | "desktop_runtime" | undefined {
  const routeDecision = readRecord(readRecord(metadata)?.routeDecision);
  const taskRoute = readRecord(routeDecision?.taskRoute);
  const operationalRoute =
    typeof taskRoute?.operationalRoute === "string"
      ? taskRoute.operationalRoute
      : routeDecision?.route;
  return operationalRoute === "desktop_runtime" ||
    operationalRoute === "server_brain"
    ? operationalRoute
    : undefined;
}

function shouldResolveRemoteMcpForChat(input: {
  requestedCapabilities: string[];
  metadata?: Record<string, unknown>;
  targetDeviceId?: string;
  existingSessionMetadata?: unknown;
}): boolean {
  const explicitMcpCapability = input.requestedCapabilities.some((value) =>
    String(value ?? "")
      .trim()
      .toLowerCase()
      .replace(/[\s.-]+/g, "_")
      .startsWith("mcp_"),
  );
  const metadata = input.metadata ?? {};
  return (
    explicitMcpCapability ||
    metadata.desktopDispatch === true ||
    Boolean(input.targetDeviceId?.trim()) ||
    readRouteContinuity(input.existingSessionMetadata) === "desktop_runtime"
  );
}

export async function listChatSessions(
  app: FastifyInstance,
  input: {
    userId: string;
    status?: ChatSessionStatus;
    limit: number;
    cursor?: string;
  },
) {
  const hasVisibleMessages = sql`exists (
    select 1
    from ${chatMessages}
    where ${chatMessages.sessionId} = ${chatSessions.id}
      and ${chatMessages.userId} = ${input.userId}
  )`;
  const conditions = [
    eq(chatSessions.userId, input.userId),
    hasVisibleMessages,
  ];
  if (input.status) {
    conditions.push(eq(chatSessions.status, input.status));
  }

  const sortTimestamp = sql<Date>`coalesce(${chatSessions.lastMessageAt}, ${chatSessions.updatedAt})`;
  const decodedCursor = decodeCursor<ChatSessionCursor>(input.cursor);
  if (decodedCursor) {
    const cursorTimestamp = cursorTimestampSql(decodedCursor.timestamp);
    if (cursorTimestamp) {
      conditions.push(
        sql`(${sortTimestamp} < ${cursorTimestamp} OR (${sortTimestamp} = ${cursorTimestamp} AND ${chatSessions.id} < ${decodedCursor.id}))`,
      );
    }
  }

  const sessions = await app.db
    .select({
      id: chatSessions.id,
      userId: chatSessions.userId,
      title: chatSessions.title,
      metadata: chatSessions.metadata,
      status: chatSessions.status,
      createdAt: chatSessions.createdAt,
      updatedAt: chatSessions.updatedAt,
      lastMessageAt: chatSessions.lastMessageAt,
    })
    .from(chatSessions)
    .where(and(...conditions))
    .orderBy(desc(sortTimestamp), desc(chatSessions.id))
    .limit(input.limit + 1);

  const hasMore = sessions.length > input.limit;
  const pageRows = sessions.slice(0, input.limit);
  const nextCursor =
    hasMore && pageRows.length > 0
      ? encodeCursor({
          timestamp:
            (
              pageRows[pageRows.length - 1]?.lastMessageAt ??
              pageRows[pageRows.length - 1]?.updatedAt
            )?.toISOString() ?? new Date().toISOString(),
          id: pageRows[pageRows.length - 1]!.id,
        })
      : null;

  return {
    sessions: pageRows.map((session) => {
      const preview = readChatSessionPreview(session.metadata, session.title);
      const title = titleFromChatPreview(session.title, preview);
      return {
        id: session.id,
        title,
        preview,
        status: session.status,
        createdAt: session.createdAt,
        updatedAt: session.updatedAt,
        lastMessageAt: session.lastMessageAt,
      };
    }),
    nextCursor,
    hasMore,
    revision: pageRows
      .map((session) => `${session.id}:${(session.lastMessageAt ?? session.updatedAt).toISOString()}`)
      .join("|") || "empty",
  };
}

export async function getChatSessionDetail(
  app: FastifyInstance,
  userId: string,
  sessionId: string,
) {
  const page = await listChatSessionMessages(app, {
    userId,
    sessionId,
    limit: INITIAL_CHAT_MESSAGE_PAGE_LIMIT,
  });

  return {
    session: page.session,
    messages: page.messages,
    nextCursor: page.nextCursor,
    hasMore: page.hasMore,
  };
}

export async function listChatSessionMessages(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    cursor?: string;
    limit?: number;
    processProactiveOpening?: boolean;
  },
) {
  const session = await assertOwnedChatSession(
    app,
    input.userId,
    input.sessionId,
  );
  await reconcileOrphanedChatMessagesForSession(app, {
    userId: input.userId,
    session,
  });
  await maybeInjectDueProactiveOpeningMessage(app, {
    userId: input.userId,
    sessionId: input.sessionId,
    cursor: input.cursor,
    enabled: input.processProactiveOpening !== false,
  });
  const sortTimestamp = chatMessages.createdAt;
  const decodedCursor = decodeCursor<ChatMessageCursor>(input.cursor);
  const limit = normalizeChatMessagePageLimit({
    requestedLimit: input.limit,
    cursor: input.cursor,
  });
  const messageConditions = [
    eq(chatMessages.sessionId, input.sessionId),
    eq(chatMessages.userId, input.userId),
  ];
  if (decodedCursor) {
    const cursorTimestamp = cursorTimestampSql(decodedCursor.timestamp);
    if (cursorTimestamp) {
      messageConditions.push(
        sql`(${sortTimestamp} < ${cursorTimestamp} OR (${sortTimestamp} = ${cursorTimestamp} AND ${chatMessages.id} < ${decodedCursor.id}))`,
      );
    }
  }

  const messages = await app.db
    .select()
    .from(chatMessages)
    .where(and(...messageConditions))
    .orderBy(desc(sortTimestamp), desc(chatMessages.id))
    .limit(limit + 1);

  const hasMore = messages.length > limit;
  const pageMessages = await Promise.all(
    messages
      .slice(0, limit)
      .reverse()
      .map(async (message) =>
        shapeChatMessageForResponse({
          ...message,
          content: await hydrateMessageContent(app, message),
        }),
      ),
  );
  const nextCursor =
    hasMore && pageMessages.length > 0
      ? encodeCursor({
          timestamp: pageMessages[0]!.createdAt.toISOString(),
          id: pageMessages[0]!.id,
        })
      : null;

  return {
    session: shapeChatSessionForResponse(session),
    messages: pageMessages,
    nextCursor,
    hasMore,
    revision: pageMessages
      .map((message) => `${message.id}:${message.updatedAt.toISOString()}`)
      .join("|") || "empty",
  };
}

export async function updateChatSession(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    status?: ChatSessionStatus;
    title?: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  await assertOwnedChatSession(app, input.userId, input.sessionId);

  const updateValues: Partial<typeof chatSessions.$inferInsert> = {
    updatedAt: new Date(),
  };
  if (input.status) {
    updateValues.status = input.status;
  }
  const normalizedTitle = input.title?.replace(/\s+/g, " ").trim();
  if (normalizedTitle) {
    updateValues.title = normalizedTitle.slice(0, 200);
  }

  const rows = await app.db
    .update(chatSessions)
    .set(updateValues)
    .where(
      and(
        eq(chatSessions.id, input.sessionId),
        eq(chatSessions.userId, input.userId),
      ),
    )
    .returning();
  const session = rows[0];

  void app.services.eventBus.publish({
    topic: "chat.session.updated",
    userId: input.userId,
    deviceId: session.targetDeviceId,
    payload: {
      session,
    },
  });

  void createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "chat.session.update",
    resourceType: "chat_session",
    resourceId: session.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      status: input.status,
      titleUpdated: Boolean(normalizedTitle),
    },
  });

  return {
    session: shapeChatSessionForResponse(session),
  };
}

// Rolling summary'yi session metadata'sına yazar
// Her chat tamamlandıktan sonra fire-and-forget olarak çağrılır
export async function persistRollingSummaryToSession(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    userMessage: string;
    assistantReply: string;
    existingMetadata?: Record<string, unknown> | null;
  },
): Promise<void> {
  try {
    await app.db.transaction(async (tx) => {
      // Serialize summary writes per session. Without the row lock, two
      // nearly simultaneous completions can read the same old summary and
      // erase each other's open loops or continuity state.
      const sessionRows = await tx
        .select({ metadata: chatSessions.metadata })
        .from(chatSessions)
        .where(
          and(
            eq(chatSessions.id, input.sessionId),
            eq(chatSessions.userId, input.userId),
          ),
        )
        .for("update");
      const persistedMetadata = readRecord(sessionRows[0]?.metadata) ?? {};
      const existing = {
        ...(input.existingMetadata ?? {}),
        ...persistedMetadata,
      };
      const existingChatCtx = readRecord(existing.chatContext) ?? {};
      const existingRS = readRecord(existingChatCtx.rollingSummary);

      // Önceki openLoops'ları koru, yenileri ekle
      const prevLoops: string[] = Array.isArray(existingRS?.openLoops)
        ? (existingRS.openLoops as unknown[])
            .map((l) => String(l ?? ""))
            .filter(Boolean)
        : [];

      // Kullanıcı mesajından hedef ve açık döngüleri derive et
      const userGoal = scrubCompactText(input.userMessage, 180);

      const assistantStateSummary = scrubCompactText(input.assistantReply, 180);

      // Açık döngü tespiti: soru işareti veya açık kalan şey sinyali
      const newLoops: string[] = [];
      const OPEN_LOOP_DETECT =
        /\b(yarın|sonra|daha sonra|follow up|remind me|let's continue|bekliyor|pending|onay bekleniyor)\b|\?$/i;
      if (OPEN_LOOP_DETECT.test(input.userMessage)) {
        const snippet =
          userGoal.length > 100 ? `${userGoal.slice(0, 97)}…` : userGoal;
        if (!prevLoops.includes(snippet)) newLoops.push(snippet);
      }

      const mergedLoops = [...newLoops, ...prevLoops].slice(0, 3);

      const rollingSummary = {
        userGoal,
        assistantState: assistantStateSummary,
        openLoops: mergedLoops,
        updatedAt: new Date().toISOString(),
      };

      const updatedMetadata = {
        ...existing,
        chatContext: {
          ...existingChatCtx,
          rollingSummary,
        },
      };

      await tx
        .update(chatSessions)
        .set({ metadata: updatedMetadata, updatedAt: new Date() })
        .where(
          and(
            eq(chatSessions.id, input.sessionId),
            eq(chatSessions.userId, input.userId),
          ),
        );
    });
  } catch {
    // Başarısız olursa sessizce geç — kritik değil
  }
}

export async function deleteChatSession(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const session = await assertOwnedChatSession(
    app,
    input.userId,
    input.sessionId,
  );

  await app.db
    .delete(tasks)
    .where(
      and(
        eq(tasks.userId, input.userId),
        chatPayloadSessionIdCondition(input.sessionId),
      ),
    );

  await app.db
    .delete(chatSessions)
    .where(
      and(
        eq(chatSessions.id, input.sessionId),
        eq(chatSessions.userId, input.userId),
      ),
    );

  await app.services.eventBus.publish({
    topic: "chat.session.deleted",
    userId: input.userId,
    deviceId: session.targetDeviceId,
    payload: {
      sessionId: input.sessionId,
    },
  });

  void createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "chat.session.delete",
    resourceType: "chat_session",
    resourceId: input.sessionId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      deletedMessages: true,
    },
  });

  return {
    deleted: true,
    sessionId: input.sessionId,
  };
}

export async function clearChatSessions(
  app: FastifyInstance,
  input: {
    userId: string;
    before?: Date;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const conditions: ReturnType<typeof eq>[] = [
    eq(chatSessions.userId, input.userId),
  ];
  if (input.before) {
    const beforeCondition = or(
      lt(chatSessions.lastMessageAt, input.before),
      and(
        isNull(chatSessions.lastMessageAt),
        lt(chatSessions.updatedAt, input.before),
      ),
    );
    if (beforeCondition) {
      conditions.push(beforeCondition);
    }
  }

  const sessions = await app.db
    .select({
      id: chatSessions.id,
      targetDeviceId: chatSessions.targetDeviceId,
    })
    .from(chatSessions)
    .where(and(...conditions));

  const deletedTaskSessionIds = sessions.map((session) => session.id);
  const taskSessionConditions = deletedTaskSessionIds.map((sessionId) =>
    chatPayloadSessionIdCondition(sessionId),
  );
  const taskCleanupConditions = [
    ...taskSessionConditions,
    placeholderMobileChatTaskCondition(input.before),
  ];

  await app.db
    .delete(tasks)
    .where(and(eq(tasks.userId, input.userId), or(...taskCleanupConditions)));

  if (sessions.length > 0) {
    await app.db.delete(chatSessions).where(and(...conditions));
  }

  await app.services.eventBus.publish({
    topic: "chat.history.cleared",
    userId: input.userId,
    payload: {
      deletedCount: sessions.length,
      before: input.before?.toISOString() ?? null,
      sessionIds: sessions.map((session) => session.id),
    },
  }).catch((error) => {
    app.log.warn({ error, userId: input.userId }, "chat session event deferred");
  });

  void createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: input.before ? "chat.history.prune" : "chat.history.clear",
    resourceType: "chat_history",
    resourceId: input.userId,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      deletedCount: sessions.length,
      before: input.before?.toISOString() ?? null,
    },
  }).catch((error) => {
    app.log.warn({ error, userId: input.userId }, "chat session audit deferred");
  });

  return {
    deleted: true,
    deletedCount: sessions.length,
    before: input.before?.toISOString() ?? null,
  };
}

export async function createChatSession(
  app: FastifyInstance,
  input: {
    id?: string;
    userId: string;
    targetDeviceId?: string;
    source: ChatSessionSource;
    title?: string;
    metadata?: Record<string, unknown>;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const targetDevice = await resolveCommandTarget(
    app,
    input.userId,
    input.targetDeviceId,
    "chat",
  );

  const rows = await app.db
    .insert(chatSessions)
    .values({
      ...(input.id ? { id: input.id } : {}),
      userId: input.userId,
      targetDeviceId: targetDevice.device.id,
      source: input.source,
      title: deriveChatTitle(input.title, input.title ?? "Yeni sohbet"),
      metadata: buildChatSessionMetadata(buildChatMetadata(input.metadata), {
        titleHint: deriveChatTitle(input.title, input.title ?? "Yeni sohbet"),
        preview: compactSessionPreview(
          input.title ?? "Yeni sohbet",
          "Yeni sohbet",
        ),
      }),
    })
    .returning();

  const session = rows[0];

  void app.services.eventBus
    .publish({
      topic: "chat.session.created",
      userId: input.userId,
      deviceId: targetDevice.device.id,
      payload: {
        session,
      },
    })
    .catch((error) => {
      app.log.warn({ error, userId: input.userId }, "chat session event deferred");
    });

  void createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "chat.session.create",
    resourceType: "chat_session",
    resourceId: session.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      source: input.source,
      targetDeviceId: targetDevice.device.id,
    },
  }).catch((error) => {
    app.log.warn({ error, userId: input.userId }, "chat session audit deferred");
  });

  return shapeChatSessionForResponse(session);
}

export async function createChatMessage(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId?: string;
    targetDeviceId?: string;
    source: ChatSessionSource;
    title?: string;
    content: string;
    requestedCapabilities: string[];
    metadata?: Record<string, unknown>;
    ephemeralVision?: EphemeralVisionCarrier;
    requestId: string;
    ipAddress?: string;
    userAgent?: string;
    idempotencyKey?: string;
  },
) {
  const [existingSession, usageAccess] = await Promise.all([
    input.sessionId
      ? findOwnedChatSession(app, input.userId, input.sessionId)
      : Promise.resolve(null),
    getUserUsageAccessTruth(app.db, input.userId),
  ]);
  const composerContext = await normalizeComposerContext({
    app,
    userId: input.userId,
    sessionId: input.sessionId,
    metadata: input.metadata,
  });
  input.metadata = composerContext.metadata;
  if (composerContext.droppedFields.length > 0) {
    app.log.info(
      {
        userId: input.userId,
        droppedFields: composerContext.droppedFields,
      },
      "composer context fields dropped after ownership validation",
    );
  }
  const remoteMcpResolution = await (shouldResolveRemoteMcpForChat({
    requestedCapabilities: input.requestedCapabilities,
    metadata: input.metadata,
    targetDeviceId: input.targetDeviceId,
    existingSessionMetadata: existingSession?.metadata,
  })
    ? resolveRemoteMcpRequest(app, {
        userId: input.userId,
        prompt: input.content,
        requestedCapabilities: input.requestedCapabilities,
      })
    : Promise.resolve({
        requestedCapabilities: input.requestedCapabilities,
        selection: null,
      }));
  const effectiveRequestedCapabilities =
    remoteMcpResolution.requestedCapabilities;
  const routeStartedAt = Date.now();
  const routeDecision = await routeChatTurn(app, {
    userId: input.userId,
    message: input.content,
    source: input.source,
    activeChatSessionId: input.sessionId,
    routeContinuity: readRouteContinuity(existingSession?.metadata),
    selectedDeviceId: input.targetDeviceId,
    metadata: input.metadata,
    desktopAllowed: canUseDesktopConnections(usageAccess.planCode),
    requestedCapabilities: effectiveRequestedCapabilities,
    bootstrap: undefined,
    brainProfile: usageAccess.brainProfile,
    quota: undefined,
  });
  logBrainDecisionObservation(app, {
    taskId: null,
    workload: routeDecision.selectedWorkload,
    route: routeDecision.route,
    model: null,
    responseFormat:
      routeDecision.semanticContract?.artifact &&
      routeDecision.semanticContract.artifact !== "none"
        ? "json_object"
        : "text",
    result: "queued",
    durationMs: Date.now() - routeStartedAt,
    semanticContract: routeDecision.semanticContract,
  });
  const routingMetadata = {
    ...input.metadata,
    routeDecision,
    presentation: presentationForRoute(routeDecision),
    ...(remoteMcpResolution.selection
      ? { remoteMcpSelection: remoteMcpResolution.selection }
      : {}),
  };
  const useDirectDesktopFastPath = isDeterministicDesktopFastWorkOrder(
    routeDecision,
    input.content,
  );
  const initialTitle = deriveChatTitle(input.title, input.content);
  const initialPreview = compactSessionPreview(input.content, initialTitle);
  if (routeDecision.route === "server_brain") {
    if (!usageAccess.serverBrainAllowed) {
      throw createUpgradeOrByokRequiredError(usageAccess);
    }
  }
  // Task admission is authoritative, but chat rows must not be written before
  // this check. Previously a paid mobile user who hit the five-hour window got
  // a 409 from createTask after the assistant row was already persisted; the
  // history screen then rendered that task-less row as an endless spinner.
  const trialQuotaPromise = getTrialQuotaUsage(app.db, input.userId);
  if (routeDecision.route === "server_brain") {
    const dispatchPolicy = resolveSharedBrainChatDispatchPolicy(app, {
      isSharedBrain: true,
      useFastSharedBrainFlow: true,
      ephemeralVision: input.ephemeralVision,
    });
    if (dispatchPolicy === "reject_queue_unavailable") {
      throw createChatQueueUnavailableError();
    }
    if (dispatchPolicy === "reject_legacy_inline_vision") {
      input.ephemeralVision = await materializeLegacyVisionForDurableQueue(
        app,
        input.userId,
        input.ephemeralVision,
      );
    }
  }
  const trialQuota = await trialQuotaPromise;
  if (trialQuota) {
    assertTrialTaskQuotaAllowedFromUsage(trialQuota);
  }
  const sessionTargetDeviceId = resolveChatSessionTargetDeviceId(
    routeDecision,
    input.targetDeviceId,
  );
  const session = input.sessionId
    ? (existingSession ??
      (await resolveOwnedOrCreateChatSession(app, {
        userId: input.userId,
        sessionId: input.sessionId,
        targetDeviceId: sessionTargetDeviceId,
        source: input.source,
        title: deriveChatTitle(input.title, input.content),
        metadata: buildChatSessionMetadata(buildChatMetadata(routingMetadata), {
          titleHint: initialTitle,
          preview: initialPreview,
        }),
        requestId: input.requestId,
        ipAddress: input.ipAddress,
        userAgent: input.userAgent,
      })))
    : await createChatSession(app, {
        userId: input.userId,
        targetDeviceId: sessionTargetDeviceId,
        source: input.source,
        title: deriveChatTitle(input.title, input.content),
        metadata: buildChatSessionMetadata(buildChatMetadata(routingMetadata), {
          titleHint: initialTitle,
          preview: initialPreview,
        }),
        requestId: input.requestId,
        ipAddress: input.ipAddress,
        userAgent: input.userAgent,
      });
  const deferChatContextHydration = shouldDeferChatContextHydration({
    routeDecision,
    metadata: routingMetadata,
    ephemeralVision: input.ephemeralVision,
  });
  const admissionLockKey = buildChatTurnAdmissionLockKey({
    userId: input.userId,
    sessionId: session.id,
    content: input.content,
    idempotencyKey: input.idempotencyKey,
  });
  const admissionLockOwner = randomUUID();
  let admissionLockAcquired = false;
  if (admissionLockKey && app.services?.reliability?.store) {
    admissionLockAcquired = await app.services.reliability.store.acquireLock(
      admissionLockKey,
      admissionLockOwner,
      CHAT_TURN_ADMISSION_LOCK_TTL_MS,
    );
    if (!admissionLockAcquired) {
      const deadline = Date.now() + CHAT_TURN_ADMISSION_WAIT_MS;
      do {
        const lockedDuplicateTurn = await findRecentDuplicateChatTurn(app, {
          userId: input.userId,
          sessionId: session.id,
          content: input.content,
        });
        if (lockedDuplicateTurn) {
          return shapeDuplicateChatTurnResponse(
            input,
            session,
            routeDecision,
            lockedDuplicateTurn,
          );
        }
        await sleep(CHAT_TURN_ADMISSION_POLL_MS);
      } while (Date.now() < deadline);

      throw new AppError(
        429,
        "rate_limited",
        "Elyan bu sohbet turunu zaten işliyor. Birkaç saniye sonra tekrar dene.",
        {
          retryAfterMs: 2_000,
          transient: true,
        },
      );
    }
  }
  const duplicateTurn = await findRecentDuplicateChatTurn(app, {
    userId: input.userId,
    sessionId: session.id,
    content: input.content,
  });
  if (duplicateTurn) {
    if (admissionLockAcquired && admissionLockKey) {
      await app.services.reliability.store.releaseLock(
        admissionLockKey,
        admissionLockOwner,
      );
      admissionLockAcquired = false;
    }
    return shapeDuplicateChatTurnResponse(
      input,
      session,
      routeDecision,
      duplicateTurn,
    );
  }
  // These reads are independent once duplicate admission has succeeded.
  // Running them together removes one full DB/cache round trip from the
  // request-to-queue path without weakening either context source.
  const [requestChatMetadata, priorChatContext] = await Promise.all([
    useDirectDesktopFastPath || deferChatContextHydration
      ? Promise.resolve(
          buildChatMetadata(
            deferChatContextHydration
              ? {
                  ...routingMetadata,
                  chatContextHydration: {
                    mode: "worker",
                    deferred: true,
                    // Conversation history is now snapshotted independently
                    // below. `deferred` only describes richer mobile/world
                    // context hydration; it must never authorize a worker
                    // history reread.
                    conversationSnapshotProvided: true,
                  },
                }
              : routingMetadata,
          ),
        )
      : enrichChatMetadataForRequest(app, {
          userId: input.userId,
          sessionId: session.id,
          targetDeviceId: session.targetDeviceId ?? input.targetDeviceId,
          metadata: routingMetadata,
        }),
    existingSession
      ? loadChatConversation(app, {
          userId: input.userId,
          sessionId: session.id,
        })
      : Promise.resolve({
          conversation: [],
          turns: [],
          attachmentCandidates: [],
        }),
  ]);
  // Skill/tool outcomes are server-owned completion truth. Never let request
  // metadata pre-seed an assistant badge before a verified execution occurs.
  const assistantRequestMetadata = {
    ...requestChatMetadata,
    chatGeneration: {
      generationAttemptId: randomUUID(),
    },
    skillUsed: false,
    skillId: null,
    executedSkillId: null,
  };
  const hasAttachmentContextInput =
    countDistinctEphemeralImages(input.ephemeralVision) > 0 ||
    priorChatContext.attachmentCandidates.length > 0;
  const attachmentContext =
    routeDecision.route === "server_brain" && hasAttachmentContextInput
      ? await resolveAttachmentContextWithCache(
          app.services.reliability.store,
          {
            prompt: input.content,
            metadata: requestChatMetadata,
            sessionAttachmentCandidates: priorChatContext.attachmentCandidates,
            // Flag kapalıysa bypass da kapalı kalır: görsel modele hiç
            // gitmeyecekse "okunabilir veri yok" netleştirmesi dürüst cevaptır.
            hasEphemeralVision:
              app.config?.ELYAN_CLOUD_VISION_ENABLED === true &&
              countDistinctEphemeralImages(input.ephemeralVision) > 0,
          },
        )
      : null;
  const effectiveWorkload = resolveAttachmentAwareSharedBrainWorkload({
    route: routeDecision.route,
    selectedWorkload: routeDecision.selectedWorkload,
    attachmentContextUsed: attachmentContext?.used === true,
    hasVisionImage:
      countDistinctEphemeralImages(input.ephemeralVision) > 0 ||
      (Array.isArray(attachmentContext?.visionImages) &&
        (attachmentContext!.visionImages!.length ?? 0) > 0) ||
      (Array.isArray(attachmentContext?.visionBlocks) &&
        (attachmentContext!.visionBlocks!.length ?? 0) > 0),
  });
  const exposeLiveTaskTrace =
    routeDecision.taskRoute?.needsDesktop === true ||
    routeDecision.taskRoute?.operationalRoute === "desktop_runtime" ||
    routeDecision.route === "desktop_runtime" ||
    routeDecision.route === "pairing_required" ||
    routeDecision.route === "unavailable" ||
    effectiveWorkload === "desktop_handoff";
  const assistantAckText =
    routeDecision.route === "server_brain"
      ? buildSharedBrainAckText(effectiveWorkload)
      : "";
  const assistantAckMetadata =
    assistantAckText.trim().length > 0
      ? {
          transientAck: true,
          ack: {
            transient: true,
            source: "shared_brain_ack",
            workload: effectiveWorkload,
          },
        }
      : {};
  const assistantAckStatus =
    routeDecision.route === "server_brain" || assistantAckText
      ? "running"
      : "queued";
  const userMessageId = randomUUID();
  const assistantMessageId = randomUUID();
  const chatContextSnapshot = buildChatContextSnapshot({
    sessionId: session.id,
    userMessageId,
    assistantMessageId,
    prompt: input.content,
    priorTurns: priorChatContext.turns,
    turnKind: resolveChatTurnKind({
      prompt: input.content,
      hasPriorAssistant: priorChatContext.turns.some(
        (turn) => turn.role === "assistant" && turn.status === "completed",
      ),
    }),
  });
  const [userMessageBlob, assistantAckBlob] = await Promise.all([
    shouldStoreChatMessageContentBlob(input.content)
      ? app.services?.blobs?.storeText({
          ownerType: "chat_message",
          ownerId: userMessageId,
          userId: input.userId,
          slot: "content",
          scope: "chat_message_content",
          value: input.content,
          contentType: "text/plain",
        })
      : Promise.resolve(null),
    assistantAckText.trim().length > 0
      ? app.services?.blobs?.storeText({
          ownerType: "chat_message",
          ownerId: assistantMessageId,
          userId: input.userId,
          slot: "content",
          scope: "chat_message_content",
          value: assistantAckText,
          contentType: "text/plain",
        })
      : undefined,
  ]);

  const messageRows = await app.db
    .insert(chatMessages)
    .values([
      {
        id: userMessageId,
        sessionId: session.id,
        userId: input.userId,
        role: "user",
        status: "completed",
        content: input.content,
        contentBlobId: userMessageBlob?.blobId ?? null,
        preview: compactMessagePreview(input.content),
        tokenCount: estimateMessageTokens(input.content),
        metadata: requestChatMetadata,
      },
      {
        id: assistantMessageId,
        sessionId: session.id,
        userId: input.userId,
        role: "assistant",
        status: assistantAckStatus,
        content: assistantAckText,
        contentBlobId: assistantAckBlob?.blobId ?? null,
        preview: compactMessagePreview(assistantAckText),
        tokenCount: estimateMessageTokens(assistantAckText),
        metadata: {
          ...withAssistantBlocksMetadata(assistantRequestMetadata, {
            content: assistantAckText,
            streaming: true,
          }),
          ...assistantAckMetadata,
        },
      },
    ])
    .returning();

  const userMessage = messageRows.find((message) => message.id === userMessageId);
  const assistantMessage = messageRows.find(
    (message) => message.id === assistantMessageId,
  );
  if (!userMessage || !assistantMessage) {
    throw new AppError(500, "chat_message_insert_failed", "Chat message could not be created");
  }

  let chatMessageCreatedPublished = false;
  let responseAssistantMessage = {
    ...shapeChatMessageForResponse(assistantMessage),
    taskId: assistantMessage.taskId,
    status: assistantAckStatus,
  };
  let responseSession = session;
  let responseLastMessageAt = new Date();

  const publishChatMessageCreated = async (
    inputTask: {
      id: string;
      targetDeviceId?: string | null;
      [key: string]: unknown;
    },
    options: { reused: boolean },
  ) => {
    if (chatMessageCreatedPublished) {
      return;
    }

    const taskTraceBlock = exposeLiveTaskTrace
      ? buildTaskTraceBlock({
          task: inputTask,
          assistantContent: assistantAckText,
        })
      : null;
    const assistantUpdate = app.db
      .update(chatMessages)
      .set({
        taskId: inputTask.id,
        content: assistantAckText,
        preview: compactMessagePreview(assistantAckText),
        tokenCount: estimateMessageTokens(assistantAckText),
        status: assistantAckStatus,
        metadata: sql`${chatMessages.metadata} || ${JSON.stringify(
          {
            ...withAssistantBlocksMetadata(assistantRequestMetadata, {
              content: assistantAckText,
              ...(taskTraceBlock ? { blocks: [taskTraceBlock] } : {}),
              streaming: true,
            }),
            ...assistantAckMetadata,
          },
        )}::jsonb`,
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(chatMessages.id, assistantMessage.id),
          // A very short fast-lane answer can complete before this deferred
          // metadata write. Never let the late ACK move a terminal message
          // back to running.
          sql`${chatMessages.status} not in ('completed', 'failed', 'canceled')`,
        ),
      )
      .returning();

    responseLastMessageAt = new Date();
    const sessionUpdate = app.db
      .update(chatSessions)
      .set({
        title: titleFromChatPreview(session.title, input.content),
        metadata: buildChatSessionMetadata(
          {
            ...(readRecord((session as Record<string, unknown>).metadata) ??
              {}),
            ...requestChatMetadata,
          },
          {
            titleHint: titleFromChatPreview(session.title, input.content),
            preview: initialPreview,
            lastMessageRole: "assistant",
            lastMessageId: assistantMessage.id,
            lastMessageAt: responseLastMessageAt,
          },
        ),
        lastMessageAt: responseLastMessageAt,
        updatedAt: responseLastMessageAt,
      })
      .where(eq(chatSessions.id, session.id));

    const [assistantRows] = await Promise.all([
      assistantUpdate,
      sessionUpdate,
    ]);
    // A fast completion or a queue failure can terminally update the
    // assistant row before this deferred ACK metadata write. Do not publish a
    // stale running snapshot in that race; it can resurrect the mobile
    // loading indicator after the real terminal event.
    if (!assistantRows[0]) {
      chatMessageCreatedPublished = true;
      return;
    }

    responseAssistantMessage =
      shapeChatMessageForResponse(assistantRows[0]);

    responseSession = {
      ...session,
      title: titleFromChatPreview(session.title, input.content),
      metadata: buildChatSessionMetadata(
        {
          ...(readRecord((session as Record<string, unknown>).metadata) ?? {}),
          ...requestChatMetadata,
        },
        {
          titleHint: titleFromChatPreview(session.title, input.content),
          preview: initialPreview,
          lastMessageRole: "assistant",
          lastMessageId: assistantMessage.id,
          lastMessageAt: responseLastMessageAt,
        },
      ),
      lastMessageAt: responseLastMessageAt,
      updatedAt: responseLastMessageAt,
    };

    void app.services.eventBus
      .publish({
        topic: "chat.message.created",
        userId: input.userId,
        deviceId: inputTask.targetDeviceId ?? session.targetDeviceId,
        taskId: inputTask.id,
        payload: {
          sessionId: session.id,
          presentation: presentationForRoute(routeDecision),
          userMessage,
          assistantMessage: responseAssistantMessage,
          task: inputTask,
          dispatched: false,
          reused: options.reused,
        },
      })
      .catch((error) => {
        app.log.warn(
          { error, requestId: input.requestId },
          "chat message realtime persistence deferred",
        );
      });
    void app.services.eventBus
      .publishVolatile({
        topic: "message.created",
        userId: input.userId,
        deviceId: inputTask.targetDeviceId ?? session.targetDeviceId,
        taskId: inputTask.id,
        payload: {
          event: "message.created",
          taskId: inputTask.id,
          sessionId: session.id,
          messageId: responseAssistantMessage.id,
          assistantMessageId: responseAssistantMessage.id,
          seq: 0,
          timestamp: new Date().toISOString(),
          presentation: presentationForRoute(routeDecision),
          userMessage,
          assistantMessage: responseAssistantMessage,
          task: inputTask,
          dispatched: false,
          reused: options.reused,
        },
      })
      .catch((error) => {
        app.log.warn(
          { error, requestId: input.requestId },
          "chat message volatile event failed",
        );
      });

    chatMessageCreatedPublished = true;
  };
  let taskResult: Awaited<ReturnType<typeof createTask>>;
  try {
    taskResult = await createTask(app, {
      userId: input.userId,
      usageAccess,
      targetDeviceId: session.targetDeviceId,
      requestedTargetDeviceId: input.targetDeviceId,
      title: deriveChatTitle(input.title ?? session.title, input.content),
      payload: {
        prompt: input.content,
        source: input.source,
        metadata: {
          ...requestChatMetadata,
          chatGeneration: assistantRequestMetadata.chatGeneration,
          chatContextHydration: {
            mode: "snapshot",
            deferred: deferChatContextHydration,
            conversationSnapshotProvided: true,
            snapshotVersion: chatContextSnapshot.version,
          },
          chatContextSnapshot,
          // Mark this as a chat-channel task so the fast streaming flow
          // (processSharedBrainChatTask + token-by-token SSE deltas) is used
          // instead of the synchronous REST reply. Without this the answer
          // arrives in one shot.
          channel: "chat",
          routeDecision,
          chat: {
            sessionId: session.id,
            userMessageId: userMessage.id,
            assistantMessageId: assistantMessage.id,
          },
        },
        brainContext: {
          conversation: snapshotConversation(chatContextSnapshot),
          ...(priorChatContext.attachmentCandidates.length > 0
            ? { attachmentCandidates: priorChatContext.attachmentCandidates }
            : {}),
        },
      },
      requestedCapabilities: effectiveRequestedCapabilities,
      requestedCapabilitiesResolved: true,
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      idempotencyKey: input.idempotencyKey,
      ephemeralVision: input.ephemeralVision,
      preResolvedChatFast: routeDecision.route === "server_brain",
      onTaskReady: async ({ task, reused }) => {
        if (routeDecision.route === "server_brain") {
          // The fast chat path publishes exactly once after createTask returns.
          // createTask can notify this callback before its durable dispatch
          // branch finishes; publishing here as well creates a race that can
          // duplicate message.created and briefly resurrect the ACK snapshot.
          return;
        }
        await publishChatMessageCreated(task, { reused });
      },
    });
  } catch (error) {
    // createTask can still reject after the precheck (for example a concurrent
    // request consumes the last quota unit). The chat rows are already visible
    // by this point, so terminalize them before returning the HTTP error. The
    // CAS in terminalizeChatMessageWithoutTask protects a task that won a race
    // and was linked just before an unrelated callback failed.
    try {
      await terminalizeChatMessageWithoutTask(app, {
        userId: input.userId,
        sessionId: session.id,
        assistantMessageId: assistantMessage.id,
        deviceId: session.targetDeviceId,
        failure: resolveChatAcceptanceFailure(error),
      });
    } catch (finalizeError) {
      app.log.error(
        { error: finalizeError, requestId: input.requestId },
        "chat acceptance failure finalization failed",
      );
    }
    if (admissionLockAcquired && admissionLockKey) {
      await app.services.reliability.store
        .releaseLock(admissionLockKey, admissionLockOwner)
        .catch((releaseError) => {
          app.log.warn(
            { error: releaseError, requestId: input.requestId },
            "chat admission lock release after failure deferred",
          );
        });
      admissionLockAcquired = false;
    }
    throw error;
  }

  // The task row and chat message rows are already durable at this point. The
  // remaining ACK/session metadata update is not acceptance-critical. Defer it
  // so a Redis retry or a second metadata write cannot hold the mobile POST
  // open while the worker is already able to stream the answer.
  void publishChatMessageCreated(taskResult.task, {
    reused: taskResult.reused,
  }).catch((error) => {
    app.log.warn(
      { error, taskId: taskResult.task.id, requestId: input.requestId },
      "chat acceptance metadata deferred",
    );
  });

  responseAssistantMessage = {
    ...shapeChatMessageForResponse(assistantMessage),
    taskId: taskResult.task.id,
    status: assistantAckStatus,
  };

  void createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "chat.message.create",
    resourceType: "chat_message",
    resourceId: userMessage.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      sessionId: session.id,
      assistantMessageId: responseAssistantMessage.id,
      taskId: taskResult.task.id,
      source: input.source,
    },
  }).catch((error) => {
    app.log.warn(
      { error, requestId: input.requestId },
      "chat audit log deferred",
    );
  });

  const taskBrainRecord = readRecord(
    (taskResult.task as Record<string, unknown>).brain,
  );
  if (admissionLockAcquired && admissionLockKey) {
    void app.services.reliability.store.releaseLock(
      admissionLockKey,
      admissionLockOwner,
    ).catch((error) => {
      app.log.warn(
        { error, requestId: input.requestId },
        "chat admission lock release deferred",
      );
    });
    admissionLockAcquired = false;
  }
  return {
    session: shapeChatSessionForResponse(responseSession),
    userMessage,
    assistantMessage: responseAssistantMessage,
    task: taskResult.task,
    renderRecipe: taskResult.renderRecipe ?? null,
    routeDecision,
    delivery: buildChatDispatchDeliverySnapshot({
      task: taskResult.task,
      routeDecision,
      requestedTargetDeviceId: input.targetDeviceId,
    }),
    brain: {
      profileMode: "elyan_managed",
      serverBrainReady: routeDecision.route === "server_brain",
      firstDeltaMs: readNumber(taskBrainRecord, "firstDeltaMs"),
      groundingUsed: readBoolean(taskBrainRecord, "groundingUsed"),
      documentSourceCount: readNumber(taskBrainRecord, "documentSourceCount"),
      webGroundingUsed: readBoolean(taskBrainRecord, "webGroundingUsed"),
      webSourceCount: readNumber(taskBrainRecord, "webSourceCount"),
    },
    // Tam kullanım bakiyesi bootstrap/SSE üzerinden güncellenir. Chat POST'u
    // tam billing özetini beklemez; bu, yanıt kabulünü ağır raporlama
    // sorgularına bağlamaz.
    usage: null,
    dispatched: taskResult.dispatched,
    reused: taskResult.reused,
  };
}

async function resolveOwnedOrCreateChatSession(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    targetDeviceId?: string;
    source: ChatSessionSource;
    title?: string;
    metadata?: Record<string, unknown>;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  try {
    return await assertOwnedChatSession(app, input.userId, input.sessionId);
  } catch (error) {
    if (
      !(error instanceof AppError) ||
      error.statusCode !== 404 ||
      error.code !== "not_found"
    ) {
      throw error;
    }
  }

  return createChatSession(app, {
    id: input.sessionId,
    userId: input.userId,
    targetDeviceId: input.targetDeviceId,
    source: input.source,
    title: input.title,
    metadata: input.metadata,
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
  });
}
