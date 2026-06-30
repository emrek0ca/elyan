import { and, asc, desc, eq, inArray, isNull, lt, or, sql } from "drizzle-orm";
import { randomUUID } from "node:crypto";
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
  getSharedBrainWorkloadProfile,
  resolveAttachmentAwareSharedBrainWorkload,
  type SharedBrainWorkload,
} from "../brain/workloads.js";
import { canUseDesktopConnections, normalizePlanBrainProfile } from "../billing/catalog.js";
import {
  createUpgradeOrByokRequiredError,
  getBillingSummary,
  getUserUsageAccessTruth,
  shapePublicUsageSnapshot,
} from "../billing/service.js";
import { calculateBillablePlanTokens, estimateTextTokens } from "../billing/token-metering.js";
import { assertTrialTaskQuotaAllowedFromUsage, getTrialQuotaUsage } from "../quota/service.js";
import { routeChatTurn } from "../routing-policy/service.js";
import { resolveCommandTarget } from "../routing-policy/service.js";
import { createTask, shapeTaskFeedItem } from "../tasks/service.js";
import { normalizeLocalDerivedMetadata } from "../../lib/derived-data.js";
import { listFreshWorldSignals } from "../mobile/service.js";
import {
  type AssistantMessageBlock,
  shapeAssistantMessagePayload,
  withAssistantBlocksMetadata,
} from "./message-blocks.js";
import { buildTaskTraceBlock } from "./task-trace.js";

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
    const createdAtMs = row.createdAt instanceof Date
      ? row.createdAt.getTime()
      : new Date(row.createdAt).getTime();
    if (!Number.isFinite(createdAtMs) || now - createdAtMs > RECENT_DUPLICATE_CHAT_TURN_WINDOW_MS) {
      continue;
    }

    const assistantRow = orderedRows
      .slice(index + 1)
      .find((candidate) => candidate.role === "assistant" && candidate.taskId);
    if (!assistantRow?.taskId) {
      continue;
    }
    const taskRows = await app.db
      .select()
      .from(tasks)
      .where(and(eq(tasks.id, assistantRow.taskId), eq(tasks.userId, input.userId)))
      .limit(1);
    const task = taskRows[0];
    if (!task) {
      continue;
    }
    return {
      userMessage: row,
      assistantMessage: assistantRow,
      task,
    };
  }

  return null;
}

function titleFromChatPreview(title: string | undefined, preview: string) {
  const normalizedTitle = normalizeChatTitle(title);
  if (normalizedTitle && !isGenericChatTitle(normalizedTitle)) {
    return compactSessionPreview(normalizedTitle, preview);
  }
  return compactSessionPreview(preview, "Yeni sohbet");
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

function readArray(record: Record<string, unknown> | null, key: string): unknown[] {
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
        content: clipCompactText(content, 280),
      };
    })
    .filter((item): item is { role: "system" | "user" | "assistant"; content: string } => item != null)
    .slice(-6);
}

function sanitizeStringList(value: unknown, limit = 4, maxLength = 120) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? clipCompactText(item, maxLength) : ""))
    .filter(Boolean)
    .slice(0, limit);
}

function sanitizeRollingSummaryRecord(value: unknown) {
  const record = readRecord(value);
  if (!record) {
    return null;
  }
  const sanitized = {
    ...(readString(record, "userGoal") ? { userGoal: clipCompactText(readString(record, "userGoal")!, 220) } : {}),
    ...(readString(record, "assistantState")
      ? { assistantState: clipCompactText(readString(record, "assistantState")!, 220) }
      : {}),
    ...(sanitizeStringList(record.openLoops, 4, 140).length > 0
      ? { openLoops: sanitizeStringList(record.openLoops, 4, 140) }
      : {}),
    ...(sanitizeStringList(record.contextNotes, 4, 140).length > 0
      ? { contextNotes: sanitizeStringList(record.contextNotes, 4, 140) }
      : {}),
    ...(readString(record, "updatedAt") ? { updatedAt: readString(record, "updatedAt") } : {}),
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
      const createdAt = readString(item, "createdAt");
      const facts = readRecord(item.facts);
      const privacy = readRecord(item.privacy);
      if (!kind || !summary) {
        return null;
      }
      return {
        ...(signalId ? { signalId } : {}),
        kind,
        summary: clipCompactText(summary, 140),
        ...(confidence != null ? { confidence } : {}),
        ...(createdAt ? { createdAt } : {}),
        ...(facts ? { facts } : {}),
        ...(privacy ? { privacy } : {}),
      };
    })
    .filter(Boolean)
    .slice(0, 4);
}

function buildSanitizedCompactContext(value: unknown) {
  const record = readRecord(value);
  if (!record) {
    return null;
  }
  const recentMessages = sanitizeCompactRecentMessages(record.recentMessages);
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
      ? { attachments: sanitizeAttachmentDigest(derivedContextDigestRecord?.attachments) }
      : {}),
    ...(previousDigest ? { previousDigest } : {}),
  };
  const responseVerbosityHint = readString(record, "responseVerbosityHint");
  const wantsLongForm = readBoolean(record, "wantsLongForm");
  const lastAssistantBlocksDigest = readString(record, "lastAssistantBlocksDigest");
  const compactContext = {
    ...(recentMessages.length > 0 ? { recentMessages } : {}),
    ...(rollingSummary ? { rollingSummary } : {}),
    ...(attachmentDigest ? { attachmentDigest } : {}),
    ...(Object.keys(derivedContextDigest).length > 0
      ? { derivedContextDigest }
      : {}),
    ...(responseVerbosityHint ? { responseVerbosityHint } : {}),
    ...(wantsLongForm != null ? { wantsLongForm } : {}),
    ...(lastAssistantBlocksDigest
      ? { lastAssistantBlocksDigest: clipCompactText(lastAssistantBlocksDigest, 280) }
      : {}),
  };
  return Object.keys(compactContext).length > 0 ? compactContext : null;
}

function readChatContextRecord(metadata: Record<string, unknown> | undefined) {
  return readRecord(readRecord(metadata)?.chatContext);
}

function inferCompactContextLongFormHint(metadata: Record<string, unknown> | undefined) {
  const compactContext = buildSanitizedCompactContext(readRecord(metadata)?.compactContext);
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

function buildSessionChatContextMetadata(metadata: Record<string, unknown> | undefined) {
  const compactContext = buildSanitizedCompactContext(readRecord(metadata)?.compactContext);
  const existingChatContext = readChatContextRecord(metadata) ?? {};
  const rollingSummary =
    sanitizeRollingSummaryRecord(compactContext?.rollingSummary) ??
    sanitizeRollingSummaryRecord(existingChatContext.rollingSummary);
  const lastAssistantBlocksDigest =
    readString(compactContext, "lastAssistantBlocksDigest") ??
    readString(existingChatContext, "lastAssistantBlocksDigest");
  const lastDerivedContextDigest = readRecord(compactContext?.derivedContextDigest) ??
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
  const existingDerivedDigest = readRecord(compactContext?.derivedContextDigest);
  let freshWorldSignalDigest: Record<string, unknown>[] = [];
  const freshSignals = await listFreshWorldSignals(app, {
    userId: input.userId,
    limit: 10,
    maxAgeHours: 72,
  });
  freshWorldSignalDigest = freshSignals.map((signal) => ({
    signalId: signal.signalId,
    kind: signal.kind,
    summary: clipCompactText(signal.summary, 220),
    confidence: signal.confidence,
    createdAt: signal.createdAt.toISOString(),
    facts:
      signal.facts && typeof signal.facts === "object" && !Array.isArray(signal.facts)
        ? signal.facts
        : {},
    privacy:
      signal.privacy && typeof signal.privacy === "object" && !Array.isArray(signal.privacy)
        ? signal.privacy
        : {},
  }));

  const mergedDerivedContextDigest = {
    ...(existingDerivedDigest ?? {}),
    ...(freshWorldSignalDigest.length > 0
      ? { worldSignals: freshWorldSignalDigest }
      : {}),
  };
  const chatContext = {
    ...buildSessionChatContextMetadata(base),
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
      (inferCompactContextLongFormHint(base) ? "expanded_when_needed" : "concise"),
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
      ...(input.lastMessageRole ? { lastMessageRole: input.lastMessageRole } : {}),
      ...(input.lastMessageId ? { lastMessageId: input.lastMessageId } : {}),
      ...(input.lastMessageAt ? { lastMessageAt: input.lastMessageAt.toISOString() } : {}),
    },
    ...(input.titleHint ? { titleHint: input.titleHint } : {}),
    ...(input.preview ? { preview: input.preview } : {}),
    ...(input.preview ? { lastMessagePreview: input.preview } : {}),
    ...(input.lastMessageRole ? { lastMessageRole: input.lastMessageRole } : {}),
    ...(input.lastMessageId ? { lastMessageId: input.lastMessageId } : {}),
    ...(input.lastMessageAt ? { lastMessageAt: input.lastMessageAt.toISOString() } : {}),
  });
}

function readChatSessionPreview(metadata: unknown, title: string | null | undefined) {
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
    content: string;
    contentBlobId?: string | null;
  },
) {
  if (!input.contentBlobId) {
    return input.content;
  }

  return (await app.services?.blobs?.hydrateText(input.contentBlobId)) ?? input.content;
}

function shapeChatMessageForResponse<T extends typeof chatMessages.$inferSelect>(
  message: T,
): T & { blocks?: AssistantMessageBlock[]; content?: string } {
  return shapeAssistantMessagePayload(message) as T & {
    blocks?: AssistantMessageBlock[];
    content?: string;
  };
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
    typeof input.requestedLimit === "number" && Number.isFinite(input.requestedLimit)
      ? Math.round(input.requestedLimit)
      : null;
  if (requestedLimit == null || requestedLimit <= 0) {
    return fallbackLimit;
  }

  return Math.max(1, Math.min(requestedLimit, CHAT_MESSAGE_PAGE_LIMIT_MAX));
}

function decodeCursor<T extends ChatSessionCursor | ChatMessageCursor>(
  rawCursor: string | undefined,
): T | null {
  const normalized = rawCursor?.trim() ?? "";
  if (!normalized) {
    return null;
  }
  try {
    const parsed = JSON.parse(Buffer.from(normalized, "base64url").toString("utf8")) as T;
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
  return routeDecision?.route === "server_brain" ? "chat" : "task";
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
  routeDecision: {
    route?: string;
    taskRoute?: {
      needsDesktop?: boolean;
    } | null;
  } | null | undefined,
  requestedTargetDeviceId?: string,
) {
  const needsDesktop =
    routeDecision?.taskRoute?.needsDesktop ??
    (routeDecision?.route === "desktop_runtime" ||
      routeDecision?.route === "pairing_required" ||
      routeDecision?.route === "unavailable");
  return needsDesktop ? requestedTargetDeviceId : undefined;
}

type SharedBrainConversationItem = {
  role: "system" | "user" | "assistant";
  content: string;
};

type ChatAttachmentRow = {
  id?: string;
  role: string;
  content?: string;
  metadata?: unknown;
  createdAt?: Date | string | null;
};

type LoadedChatContext = {
  conversation: SharedBrainConversationItem[];
  attachmentCandidates: AttachmentContextCandidate[];
};

function estimateConversationTokens(text: string) {
  return estimateTextTokens(text);
}

function getEstimatedMaxTokensForChatWorkload(workload: SharedBrainWorkload, brainProfileInput: unknown): number {
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

  if (["completed", "failed", "canceled"].includes(String(input.taskStatus ?? "").trim())) {
    return 0;
  }

  const userInputTokens = estimateConversationTokens(input.content);

  return calculateBillablePlanTokens({
    surface: "chat",
    userInputTokens,
    promptTokens: userInputTokens,
    completionTokens: getEstimatedMaxTokensForChatWorkload(input.workload, input.brainProfile),
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
    if (row.role !== "user") {
      continue;
    }

    const metadata =
      row.metadata && typeof row.metadata === "object" && !Array.isArray(row.metadata)
        ? extractAttachmentMetadataCarrier(row.metadata as Record<string, unknown>)
        : null;
    if (!metadata) {
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
    .orderBy(asc(chatMessages.createdAt))
    .limit(input.limit ?? 32);

  const hydratedRows = await Promise.all(
    rows.map(async (row) => ({
      ...row,
      content: await hydrateMessageContent(app, row),
    })),
  );

  return {
    conversation: trimConversationForSharedBrain(
      hydratedRows
        .map((row) => ({
          role: row.role,
          content: row.content,
        }))
        .filter(
          (
            item,
          ): item is {
            role: "system" | "user" | "assistant";
            content: string;
          } => typeof item.content === "string" && item.content.trim().length > 0,
        ),
    ),
    attachmentCandidates: extractAttachmentCandidatesFromChatRows(
      hydratedRows as ChatAttachmentRow[],
    ),
  };
}

async function assertOwnedChatSession(
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

  if (!session) {
    throw notFound("Chat session not found");
  }

  return session;
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
  const conditions = [eq(chatSessions.userId, input.userId), hasVisibleMessages];
  if (input.status) {
    conditions.push(eq(chatSessions.status, input.status));
  }

  const sortTimestamp = sql<Date>`coalesce(${chatSessions.lastMessageAt}, ${chatSessions.updatedAt})`;
  const decodedCursor = decodeCursor<ChatSessionCursor>(input.cursor);
  if (decodedCursor) {
    const cursorTimestamp = new Date(decodedCursor.timestamp);
    conditions.push(
      sql`(${sortTimestamp} < ${cursorTimestamp} OR (${sortTimestamp} = ${cursorTimestamp} AND ${chatSessions.id} < ${decodedCursor.id}))`,
    );
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
  const nextCursor = hasMore && pageRows.length > 0
    ? encodeCursor({
        timestamp:
          (pageRows[pageRows.length - 1]?.lastMessageAt ??
            pageRows[pageRows.length - 1]?.updatedAt)?.toISOString() ??
          new Date().toISOString(),
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
  },
) {
  const session = await assertOwnedChatSession(app, input.userId, input.sessionId);
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
    const cursorTimestamp = new Date(decodedCursor.timestamp);
    messageConditions.push(
      sql`(${sortTimestamp} < ${cursorTimestamp} OR (${sortTimestamp} = ${cursorTimestamp} AND ${chatMessages.id} < ${decodedCursor.id}))`,
    );
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
  const nextCursor = hasMore && pageMessages.length > 0
    ? encodeCursor({
        timestamp: pageMessages[0]!.createdAt.toISOString(),
        id: pageMessages[0]!.id,
      })
    : null;

  return {
    session,
    messages: pageMessages,
    nextCursor,
    hasMore,
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

  await app.services.eventBus.publish({
    topic: "chat.session.updated",
    userId: input.userId,
    deviceId: session.targetDeviceId,
    payload: {
      session,
    },
  });

  await createAuditLog(app, {
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
    session,
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
    const existing = input.existingMetadata ?? {};
    const existingChatCtx = readRecord(existing.chatContext) ?? {};
    const existingRS = readRecord(existingChatCtx.rollingSummary);

    // Önceki openLoops'ları koru, yenileri ekle
    const prevLoops: string[] = Array.isArray(existingRS?.openLoops)
      ? (existingRS.openLoops as unknown[]).map((l) => String(l ?? "")).filter(Boolean)
      : [];

    // Kullanıcı mesajından hedef ve açık döngüleri derive et
    const userGoal = input.userMessage.length > 180
      ? `${input.userMessage.slice(0, 177)}…`
      : input.userMessage;

    const assistantStateSummary = input.assistantReply.length > 180
      ? `${input.assistantReply.slice(0, 177)}…`
      : input.assistantReply;

    // Açık döngü tespiti: soru işareti veya açık kalan şey sinyali
    const newLoops: string[] = [];
    const OPEN_LOOP_DETECT = /\b(yarın|sonra|daha sonra|follow up|remind me|let's continue|bekliyor|pending|onay bekleniyor)\b|\?$/i;
    if (OPEN_LOOP_DETECT.test(input.userMessage)) {
      const snippet = userGoal.length > 100 ? `${userGoal.slice(0, 97)}…` : userGoal;
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

    await app.db
      .update(chatSessions)
      .set({ metadata: updatedMetadata, updatedAt: new Date() })
      .where(and(eq(chatSessions.id, input.sessionId), eq(chatSessions.userId, input.userId)));
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

  await createAuditLog(app, {
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
    .where(
      and(
        eq(tasks.userId, input.userId),
        or(...taskCleanupConditions),
      ),
    );

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
  });

  await createAuditLog(app, {
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
      metadata: buildChatSessionMetadata(
        buildChatMetadata(input.metadata),
        {
          titleHint: deriveChatTitle(input.title, input.title ?? "Yeni sohbet"),
          preview: compactSessionPreview(input.title ?? "Yeni sohbet", "Yeni sohbet"),
        },
      ),
    })
    .returning();

  const session = rows[0];

  await app.services.eventBus.publish({
    topic: "chat.session.created",
    userId: input.userId,
    deviceId: targetDevice.device.id,
    payload: {
      session,
    },
  });

  await createAuditLog(app, {
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
  });

  return session;
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
    requestId: string;
    ipAddress?: string;
    userAgent?: string;
    idempotencyKey?: string;
  },
) {
  const usageAccess = await getUserUsageAccessTruth(app.db, input.userId);
  const routeDecision = await routeChatTurn(app, {
    userId: input.userId,
    message: input.content,
    source: input.source,
    activeChatSessionId: input.sessionId,
    selectedDeviceId: input.targetDeviceId,
    metadata: input.metadata,
    desktopAllowed: canUseDesktopConnections(usageAccess.planCode),
    requestedCapabilities: input.requestedCapabilities,
    bootstrap: undefined,
    brainProfile: usageAccess.brainProfile,
    quota: undefined,
  });
  const routingMetadata = {
    ...input.metadata,
    routeDecision,
    presentation: presentationForRoute(routeDecision),
  };
  const initialTitle = deriveChatTitle(input.title, input.content);
  const initialPreview = compactSessionPreview(input.content, initialTitle);
  if (routeDecision.route === "server_brain") {
    if (!usageAccess.serverBrainAllowed) {
      throw createUpgradeOrByokRequiredError(usageAccess);
    }
    if (usageAccess.mode === "trial" && usageAccess.planCode === "free") {
      const trialQuota = await getTrialQuotaUsage(app.db, input.userId);
      assertTrialTaskQuotaAllowedFromUsage(trialQuota);
    }
  }
  const sessionTargetDeviceId = resolveChatSessionTargetDeviceId(
    routeDecision,
    input.targetDeviceId,
  );
  const session = input.sessionId
    ? await resolveOwnedOrCreateChatSession(app, {
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
    })
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
  const requestChatMetadata = await enrichChatMetadataForRequest(app, {
    userId: input.userId,
    sessionId: session.id,
    targetDeviceId: session.targetDeviceId ?? input.targetDeviceId,
    metadata: routingMetadata,
  });
  const duplicateTurn = await findRecentDuplicateChatTurn(app, {
    userId: input.userId,
    sessionId: session.id,
    content: input.content,
  });
  if (duplicateTurn) {
    const billing = await getBillingSummary(app, input.userId);
    const shapedTask = shapeTaskFeedItem(duplicateTurn.task);
    const shapedAssistantMessage = {
      ...shapeChatMessageForResponse(duplicateTurn.assistantMessage),
      taskId: duplicateTurn.assistantMessage.taskId,
      status: duplicateTurn.assistantMessage.status,
      content: duplicateTurn.assistantMessage.content,
    };
    const taskBrainRecord = readRecord((shapedTask as Record<string, unknown>).brain);
    const resultRecord = readRecord((duplicateTurn.task as Record<string, unknown>).result);
    const pendingTokenDebit = estimatePendingChatTokenDebit({
      route: routeDecision.route,
      reused: true,
      taskStatus: duplicateTurn.task.status,
      content: input.content,
      workload: routeDecision.selectedWorkload ?? "mobile_chat_fast",
      brainProfile: billing.subscription.brainProfile,
    });
    return {
      session,
      userMessage: shapeChatMessageForResponse(duplicateTurn.userMessage),
      assistantMessage: shapedAssistantMessage,
      task: shapedTask,
      renderRecipe: resultRecord?.renderRecipe ?? null,
      routeDecision,
      delivery: buildChatDispatchDeliverySnapshot({
        task: shapedTask,
        routeDecision,
        requestedTargetDeviceId: input.targetDeviceId,
      }),
      brain: {
        selectedProfile: routeDecision.selectedWorkload ?? "mobile_chat_fast",
        profileMode: "elyan_managed",
        serverBrainReady: routeDecision.route === "server_brain",
        firstDeltaMs: readNumber(taskBrainRecord, "firstDeltaMs"),
        fallbackUsed: readBoolean(taskBrainRecord, "fallbackUsed"),
        groundingUsed: readBoolean(taskBrainRecord, "groundingUsed"),
        documentSourceCount: readNumber(taskBrainRecord, "documentSourceCount"),
        webGroundingUsed: readBoolean(taskBrainRecord, "webGroundingUsed"),
        webSourceCount: readNumber(taskBrainRecord, "webSourceCount"),
      },
      usage: shapePublicUsageSnapshot({
        usage: billing.usage,
        subscription: billing.subscription,
        pendingTokens: pendingTokenDebit,
      }),
      dispatched: false,
      reused: true,
      deduped: true,
    };
  }
  const priorChatContext = await loadChatConversation(app, {
    userId: input.userId,
    sessionId: session.id,
  });
  const attachmentContext =
    routeDecision.route === "server_brain"
      ? await resolveAttachmentContextWithCache(app.services.reliability.store, {
          prompt: input.content,
          metadata: requestChatMetadata,
          sessionAttachmentCandidates: priorChatContext.attachmentCandidates,
        })
      : null;
  const effectiveWorkload = resolveAttachmentAwareSharedBrainWorkload({
    route: routeDecision.route,
    selectedWorkload: routeDecision.selectedWorkload,
    attachmentContextUsed: attachmentContext?.used === true,
    hasVisionImage:
      Array.isArray(attachmentContext?.visionImages) &&
      (attachmentContext!.visionImages!.length ?? 0) > 0,
  });
  const assistantAckText =
    routeDecision.route === "server_brain"
      ? buildSharedBrainAckText(effectiveWorkload)
      : "";
  const assistantAckStatus = assistantAckText ? "running" : "queued";
  const userMessageId = randomUUID();
  const assistantMessageId = randomUUID();
  const userMessageBlob = await app.services?.blobs?.storeText({
    ownerType: "chat_message",
    ownerId: userMessageId,
    slot: "content",
    scope: "chat_message_content",
    value: input.content,
    contentType: "text/plain",
  });
  const assistantAckBlob = await app.services?.blobs?.storeText({
    ownerType: "chat_message",
    ownerId: assistantMessageId,
    slot: "content",
    scope: "chat_message_content",
    value: assistantAckText,
    contentType: "text/plain",
  });

  const userMessageRows = await app.db
    .insert(chatMessages)
    .values({
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
    })
    .returning();

  const userMessage = userMessageRows[0];

  const assistantMessageRows = await app.db
    .insert(chatMessages)
    .values({
      id: assistantMessageId,
      sessionId: session.id,
      userId: input.userId,
      role: "assistant",
      status: assistantAckStatus,
      content: assistantAckText,
      contentBlobId: assistantAckBlob?.blobId ?? null,
      preview: compactMessagePreview(assistantAckText),
      tokenCount: estimateMessageTokens(assistantAckText),
      metadata: withAssistantBlocksMetadata(requestChatMetadata, {
        content: assistantAckText,
        streaming: true,
      }),
    })
    .returning();

  const assistantMessage = assistantMessageRows[0];

  let chatMessageCreatedPublished = false;
  let responseAssistantMessage = {
    ...shapeChatMessageForResponse(assistantMessage),
    taskId: assistantMessage.taskId,
    status: assistantAckStatus,
    content: assistantAckText,
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

    const taskTraceBlock = buildTaskTraceBlock({
      task: inputTask,
      assistantContent: assistantAckText,
    });
    const assistantRows = await app.db
      .update(chatMessages)
      .set({
        taskId: inputTask.id,
        content: assistantAckText,
        preview: compactMessagePreview(assistantAckText),
        tokenCount: estimateMessageTokens(assistantAckText),
        status: assistantAckStatus,
        metadata: sql`${chatMessages.metadata} || ${JSON.stringify(
          withAssistantBlocksMetadata(requestChatMetadata, {
            content: assistantAckText,
            blocks: [taskTraceBlock],
            streaming: true,
          }),
        )}::jsonb`,
        updatedAt: new Date(),
      })
      .where(eq(chatMessages.id, assistantMessage.id))
      .returning();

    responseAssistantMessage =
      (assistantRows[0] ? shapeChatMessageForResponse(assistantRows[0]) : undefined) ??
      ({
        ...shapeChatMessageForResponse(assistantMessage),
        taskId: inputTask.id,
        status: assistantAckStatus,
      } as typeof responseAssistantMessage);

    responseLastMessageAt = new Date();
    await app.db
      .update(chatSessions)
      .set({
        title: titleFromChatPreview(session.title, input.content),
        metadata: buildChatSessionMetadata(
          readRecord((session as Record<string, unknown>).metadata) ?? requestChatMetadata,
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

    responseSession = {
      ...session,
      title: titleFromChatPreview(session.title, input.content),
      metadata: buildChatSessionMetadata(
        readRecord((session as Record<string, unknown>).metadata) ??
          requestChatMetadata,
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

    await app.services.eventBus.publish({
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
    });

    await app.services.eventBus.publishVolatile({
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
    });

    chatMessageCreatedPublished = true;
  };
  const chatContext = await loadChatConversation(app, {
    userId: input.userId,
    sessionId: session.id,
  });
  const taskResult = await createTask(app, {
    userId: input.userId,
    targetDeviceId: session.targetDeviceId,
    requestedTargetDeviceId: input.targetDeviceId,
    title: deriveChatTitle(input.title ?? session.title, input.content),
    payload: {
      prompt: input.content,
      source: input.source,
      metadata: {
        ...requestChatMetadata,
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
        conversation: chatContext.conversation,
        ...(chatContext.attachmentCandidates.length > 0
          ? { attachmentCandidates: chatContext.attachmentCandidates }
          : {}),
      },
    },
    requestedCapabilities: input.requestedCapabilities,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    idempotencyKey: input.idempotencyKey,
    onTaskReady: async ({ task, reused }) => {
      await publishChatMessageCreated(task, { reused });
    },
  });

  await publishChatMessageCreated(taskResult.task, {
    reused: taskResult.reused,
  });

  await createAuditLog(app, {
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
  });

  const billing = await getBillingSummary(app, input.userId);
  const pendingTokenDebit = estimatePendingChatTokenDebit({
    route: routeDecision.route,
    reused: taskResult.reused,
    taskStatus: taskResult.task.status,
    content: input.content,
    workload: effectiveWorkload,
    brainProfile: billing.subscription.brainProfile,
  });
  const taskBrainRecord = readRecord((taskResult.task as Record<string, unknown>).brain);
  return {
    session: {
      ...responseSession,
    },
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
      selectedProfile: effectiveWorkload,
      profileMode: "elyan_managed",
      serverBrainReady: routeDecision.route === "server_brain",
      firstDeltaMs: readNumber(taskBrainRecord, "firstDeltaMs"),
      fallbackUsed: readBoolean(taskBrainRecord, "fallbackUsed"),
      groundingUsed: readBoolean(taskBrainRecord, "groundingUsed"),
      documentSourceCount: readNumber(taskBrainRecord, "documentSourceCount"),
      webGroundingUsed: readBoolean(taskBrainRecord, "webGroundingUsed"),
      webSourceCount: readNumber(taskBrainRecord, "webSourceCount"),
    },
    usage: shapePublicUsageSnapshot({
      usage: billing.usage,
      subscription: billing.subscription,
      pendingTokens: pendingTokenDebit,
    }),
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
