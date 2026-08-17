import { and, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { artifacts, chatMessages, chatSessions, tasks } from "../../db/schema.js";
import {
  MOBILE_QUICK_ACTION_IDS,
  type MobileQuickActionContext,
  type MobileQuickActionSource,
} from "../../contracts/mobile-quick-actions.js";

const MAX_CONTEXT_ID_LENGTH = 255;
const MAX_QUOTE_PREVIEW_LENGTH = 800;
const SOURCE_ARTIFACT_SENTINEL = "last_image";

type JsonRecord = Record<string, unknown>;

export type ParsedComposerQuote = {
  messageId: string;
  role?: "user" | "assistant";
  taskId?: string;
  text?: string;
};

export type ParsedComposerQuickAction = {
  id: string;
  source: MobileQuickActionSource;
  context?: MobileQuickActionContext;
};

export type ParsedComposerContext = {
  quote?: ParsedComposerQuote;
  quickAction?: ParsedComposerQuickAction;
  sourceArtifactId?: string;
};

export type ComposerContextNormalization = {
  metadata: Record<string, unknown>;
  parsed: ParsedComposerContext;
  droppedFields: string[];
};

export type ResolvedComposerQuote = {
  messageId: string;
  sessionId: string;
  role: "user" | "assistant";
  taskId: string | null;
  text: string;
  preview: string;
};

function readRecord(value: unknown): JsonRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function readBoundedId(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized && normalized.length <= MAX_CONTEXT_ID_LENGTH
    ? normalized
    : null;
}

function readPreview(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.replace(/\s+/gu, " ").trim();
  return normalized
    ? normalized.slice(0, MAX_QUOTE_PREVIEW_LENGTH)
    : null;
}

function compactPreview(value: string, maxLength = 320): string {
  const normalized = value.replace(/\s+/gu, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(value);
}

function readSourceArtifactId(metadata: JsonRecord): string | null {
  const visualIntent = readRecord(metadata.visualIntent);
  return (
    readBoundedId(visualIntent?.sourceArtifactId) ??
    readBoundedId(metadata.sourceArtifactId)
  );
}

function readQuickActionContext(value: unknown): MobileQuickActionContext | undefined {
  const record = readRecord(value);
  if (!record) return undefined;
  const sessionId = readBoundedId(record.sessionId);
  const messageId = readBoundedId(record.messageId);
  const taskId = readBoundedId(record.taskId);
  if (!sessionId && !messageId && !taskId) return undefined;
  return {
    ...(sessionId ? { sessionId } : {}),
    ...(messageId ? { messageId } : {}),
    ...(taskId ? { taskId } : {}),
  };
}

function readQuickAction(value: unknown): ParsedComposerQuickAction | null {
  const record = readRecord(value);
  const id = readBoundedId(record?.id);
  if (!id || !MOBILE_QUICK_ACTION_IDS.some((candidate) => candidate === id)) return null;
  const source: MobileQuickActionSource = record?.source === "semantic"
    ? "semantic"
    : "catalog";
  const context = readQuickActionContext(record?.context);
  return {
    id,
    source,
    ...(context ? { context } : {}),
  };
}

function readQuote(value: unknown): ParsedComposerQuote | null {
  const record = readRecord(value);
  const messageId = readBoundedId(record?.messageId);
  if (!messageId) return null;
  const role = record?.role === "user" || record?.role === "assistant"
    ? record.role
    : undefined;
  const taskId = readBoundedId(record?.taskId);
  const text = readPreview(record?.text ?? record?.preview);
  return {
    messageId,
    ...(role ? { role } : {}),
    ...(taskId ? { taskId } : {}),
    ...(text ? { text } : {}),
  };
}

export function parseComposerContext(metadata: Record<string, unknown> | undefined): {
  context: ParsedComposerContext;
  invalidFields: string[];
} {
  const root = readRecord(metadata?.composerContext);
  const invalidFields: string[] = [];
  if (!root) {
    return { context: {}, invalidFields };
  }

  const context: ParsedComposerContext = {};
  if (root.quote !== undefined) {
    const quote = readQuote(root.quote);
    if (quote) context.quote = quote;
    else invalidFields.push("quote");
  }
  if (root.quickAction !== undefined) {
    const quickAction = readQuickAction(root.quickAction);
    if (quickAction) context.quickAction = quickAction;
    else invalidFields.push("quickAction");
  }
  const sourceArtifactId = readSourceArtifactId(metadata ?? {});
  if (sourceArtifactId) context.sourceArtifactId = sourceArtifactId;

  return { context, invalidFields };
}

function buildQuickActionContext(
  context: MobileQuickActionContext | undefined,
): JsonRecord | undefined {
  if (!context) return undefined;
  return {
    ...(context.sessionId ? { sessionId: context.sessionId } : {}),
    ...(context.messageId ? { messageId: context.messageId } : {}),
    ...(context.taskId ? { taskId: context.taskId } : {}),
  };
}

export function buildNormalizedComposerContext(input: {
  quote?: ResolvedComposerQuote;
  quickAction?: ParsedComposerQuickAction;
}): JsonRecord | undefined {
  const value: JsonRecord = {};
  if (input.quote) {
    value.quote = {
      messageId: input.quote.messageId,
      role: input.quote.role,
      ...(input.quote.taskId ? { taskId: input.quote.taskId } : {}),
      text: input.quote.preview,
    };
  }
  if (input.quickAction) {
    const context = buildQuickActionContext(input.quickAction.context);
    value.quickAction = {
      id: input.quickAction.id,
      source: input.quickAction.source,
      ...(context ? { context } : {}),
    };
  }
  return Object.keys(value).length > 0 ? value : undefined;
}

function replaceVisualSourceArtifactId(
  metadata: Record<string, unknown>,
  sourceArtifactId: string | null,
): Record<string, unknown> {
  const next = { ...metadata };
  if (sourceArtifactId) next.sourceArtifactId = sourceArtifactId;
  else delete next.sourceArtifactId;
  const visualIntent = readRecord(next.visualIntent);
  if (visualIntent) {
    const nextVisualIntent = { ...visualIntent };
    if (sourceArtifactId) nextVisualIntent.sourceArtifactId = sourceArtifactId;
    else delete nextVisualIntent.sourceArtifactId;
    next.visualIntent = nextVisualIntent;
  } else if (sourceArtifactId) {
    next.visualIntent = { sourceArtifactId };
  }
  return next;
}

async function hasOwnedSourceArtifact(
  app: FastifyInstance,
  input: { userId: string; sessionId?: string; sourceArtifactId: string },
): Promise<boolean> {
  if (input.sourceArtifactId === SOURCE_ARTIFACT_SENTINEL) return true;
  if (!isUuid(input.sourceArtifactId)) return false;
  const rows = await app.db
    .select({
      artifactId: artifacts.id,
      taskId: artifacts.taskId,
      taskPayload: tasks.payload,
    })
    .from(artifacts)
    .innerJoin(tasks, eq(tasks.id, artifacts.taskId))
    .where(
      and(
        eq(artifacts.id, input.sourceArtifactId),
        eq(tasks.userId, input.userId),
      ),
    )
    .limit(1);
  const artifact = rows[0];
  if (!artifact) return false;
  if (!input.sessionId) return true;
  const payload = readRecord(artifact.taskPayload);
  const metadata = readRecord(payload?.metadata);
  const chat = readRecord(metadata?.chat);
  const sourceSessionId = readBoundedId(chat?.sessionId);
  if (sourceSessionId) return sourceSessionId === input.sessionId;

  // Older task payloads may not carry chat.sessionId. Fall back to the
  // authoritative assistant/user message relation before accepting an
  // artifact in the current session.
  const messageRows = await app.db
    .select({ id: chatMessages.id })
    .from(chatMessages)
    .where(
      and(
        eq(chatMessages.taskId, artifact.taskId),
        eq(chatMessages.userId, input.userId),
        eq(chatMessages.sessionId, input.sessionId),
      ),
    )
    .limit(1);
  return messageRows.length > 0;
}

export async function normalizeComposerContext(input: {
  app: FastifyInstance;
  userId: string;
  sessionId?: string;
  metadata?: Record<string, unknown>;
}): Promise<ComposerContextNormalization> {
  const metadata = { ...(input.metadata ?? {}) };
  const parsed = parseComposerContext(metadata);
  const droppedFields = [...parsed.invalidFields];
  let resolvedQuote: ResolvedComposerQuote | undefined;
  let quickAction = parsed.context.quickAction;

  if (parsed.context.quote) {
    const rows = input.sessionId
      ? await input.app.db
          .select()
          .from(chatMessages)
          .where(
            and(
              eq(chatMessages.id, parsed.context.quote.messageId),
              eq(chatMessages.userId, input.userId),
              eq(chatMessages.sessionId, input.sessionId),
            ),
          )
          .limit(1)
      : [];
    const message = rows[0];
    if (message) {
      const text = message.contentBlobId
        ? (await input.app.services?.blobs?.hydrateTextForOwner({
            blobId: message.contentBlobId,
            userId: input.userId,
            ownerType: "chat_message",
            ownerId: message.id,
          })) ?? message.content
        : message.content;
      const role = message.role === "assistant" ? "assistant" : "user";
      resolvedQuote = {
        messageId: message.id,
        sessionId: message.sessionId,
        role,
        taskId: message.taskId,
        text,
        preview: compactPreview(text),
      };
    } else {
      droppedFields.push("quote");
    }
  }

  if (quickAction?.context) {
    const context = quickAction.context;
    let valid = true;
    if (context.sessionId) {
      const sessionRows = await input.app.db
        .select({ id: chatSessions.id })
        .from(chatSessions)
        .where(and(eq(chatSessions.id, context.sessionId), eq(chatSessions.userId, input.userId)))
        .limit(1);
      valid = sessionRows.length > 0;
      if (valid && input.sessionId && context.sessionId !== input.sessionId) valid = false;
    }
    let linkedMessage: typeof chatMessages.$inferSelect | undefined;
    if (valid && context.messageId) {
      const messageRows = await input.app.db
        .select()
        .from(chatMessages)
        .where(and(eq(chatMessages.id, context.messageId), eq(chatMessages.userId, input.userId)))
        .limit(1);
      linkedMessage = messageRows[0];
      valid = Boolean(linkedMessage);
      if (valid && context.sessionId && linkedMessage?.sessionId !== context.sessionId) valid = false;
      if (valid && input.sessionId && linkedMessage?.sessionId !== input.sessionId) valid = false;
      if (valid && context.taskId && linkedMessage?.taskId !== context.taskId) valid = false;
    }
    if (valid && context.taskId) {
      const taskRows = await input.app.db
        .select({ id: tasks.id, payload: tasks.payload })
        .from(tasks)
        .where(and(eq(tasks.id, context.taskId), eq(tasks.userId, input.userId)))
        .limit(1);
      const task = taskRows[0];
      valid = Boolean(task);
      if (valid && linkedMessage && linkedMessage.taskId && linkedMessage.taskId !== context.taskId) valid = false;
      if (valid && context.sessionId) {
        const payload = readRecord(task?.payload);
        const taskMetadata = readRecord(payload?.metadata);
        const chat = readRecord(taskMetadata?.chat);
        const taskSessionId = readBoundedId(chat?.sessionId);
        if (taskSessionId && taskSessionId !== context.sessionId) valid = false;
      }
      if (valid && input.sessionId) {
        const payload = readRecord(task?.payload);
        const taskMetadata = readRecord(payload?.metadata);
        const chat = readRecord(taskMetadata?.chat);
        const taskSessionId = readBoundedId(chat?.sessionId);
        if (taskSessionId && taskSessionId !== input.sessionId) {
          valid = false;
        } else if (!taskSessionId) {
          const taskMessageRows = await input.app.db
            .select({ id: chatMessages.id })
            .from(chatMessages)
            .where(
              and(
                eq(chatMessages.taskId, context.taskId),
                eq(chatMessages.userId, input.userId),
                eq(chatMessages.sessionId, input.sessionId),
              ),
            )
            .limit(1);
          if (taskMessageRows.length === 0) valid = false;
        }
      }
    }
    if (!valid) {
      droppedFields.push("quickAction.context");
      quickAction = { id: quickAction.id, source: "catalog" };
    }
  }

  let nextMetadata = { ...metadata };
  // Authorized v2 refs are request input, not chat/session metadata. The
  // durable task binder re-attaches them to the task payload from the
  // top-level carrier; keeping client-supplied refs here would leak an
  // unauthorised source contract into history.
  if ("mediaInputRefs" in nextMetadata || "mediaInputPrivacy" in nextMetadata) {
    droppedFields.push("metadata.mediaInputRefs");
    delete nextMetadata.mediaInputRefs;
    delete nextMetadata.mediaInputPrivacy;
  }
  const normalizedComposerContext = buildNormalizedComposerContext({
    quote: resolvedQuote,
    quickAction,
  });
  if (normalizedComposerContext) nextMetadata.composerContext = normalizedComposerContext;
  else delete nextMetadata.composerContext;

  const sourceArtifactId = parsed.context.sourceArtifactId;
  let validatedSourceArtifactId: string | undefined;
  if (sourceArtifactId) {
    const sourceIsOwned = await hasOwnedSourceArtifact(input.app, {
      userId: input.userId,
      sessionId: input.sessionId,
      sourceArtifactId,
    });
    if (sourceIsOwned) {
      validatedSourceArtifactId = sourceArtifactId;
    } else {
      droppedFields.push("sourceArtifactId");
      nextMetadata = replaceVisualSourceArtifactId(nextMetadata, null);
    }
  }

  return {
    metadata: nextMetadata,
    parsed: {
      ...(resolvedQuote ? { quote: {
        messageId: resolvedQuote.messageId,
        role: resolvedQuote.role,
        ...(resolvedQuote.taskId ? { taskId: resolvedQuote.taskId } : {}),
        text: resolvedQuote.preview,
      } } : {}),
      ...(quickAction ? { quickAction } : {}),
      ...(validatedSourceArtifactId ? { sourceArtifactId: validatedSourceArtifactId } : {}),
    },
    droppedFields: [...new Set(droppedFields)],
  };
}

export async function resolveComposerQuoteForTask(
  app: FastifyInstance,
  input: { userId: string; sessionId: string; messageId: string },
): Promise<ResolvedComposerQuote | null> {
  const rows = await app.db
    .select()
    .from(chatMessages)
    .where(
      and(
        eq(chatMessages.id, input.messageId),
        eq(chatMessages.sessionId, input.sessionId),
        eq(chatMessages.userId, input.userId),
      ),
    )
    .limit(1);
  const message = rows[0];
  if (!message) return null;
  const text = message.contentBlobId
    ? (await app.services?.blobs?.hydrateTextForOwner({
        blobId: message.contentBlobId,
        userId: input.userId,
        ownerType: "chat_message",
        ownerId: message.id,
      })) ?? message.content
    : message.content;
  return {
    messageId: message.id,
    sessionId: message.sessionId,
    role: message.role === "assistant" ? "assistant" : "user",
    taskId: message.taskId,
    text,
    preview: compactPreview(text),
  };
}
