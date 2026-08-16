import { and, asc, eq, inArray, isNull, lt, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { chatMessages, chatSessions } from "../../db/schema.js";
import {
  shapeAssistantMessagePayload,
  withAssistantBlocksMetadata,
} from "./message-blocks.js";

// The acceptance path normally links an assistant row to a task in the same
// request. This is only a backstop for a crashed process or a lost callback;
// keep the grace period aligned with the existing per-session reconciliation.
export const ORPHANED_CHAT_MESSAGE_GRACE_MS = 90_000;
export const ORPHANED_CHAT_MESSAGE_FAILURE_MESSAGE =
  "Yanıt başlatılamadı. Lütfen tekrar dene.";

function normalizeMessageText(value: string | undefined): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function compactMessagePreview(value: string | undefined, maxLength = 320) {
  const normalized = normalizeMessageText(value);
  if (!normalized) return null;
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function estimateMessageTokens(value: string): number {
  const normalized = normalizeMessageText(value);
  return normalized ? Math.max(1, Math.ceil(normalized.length / 4)) : 0;
}

export function shouldReconcileOrphanedChatMessage(input: {
  role: string;
  status: string;
  taskId?: string | null;
  createdAt: Date | string;
  now?: Date;
}): boolean {
  if (input.role !== "assistant" || input.taskId) return false;
  if (input.status !== "queued" && input.status !== "running") return false;
  const createdAt =
    input.createdAt instanceof Date
      ? input.createdAt.getTime()
      : new Date(input.createdAt).getTime();
  const now = (input.now ?? new Date()).getTime();
  return (
    Number.isFinite(createdAt) &&
    now - createdAt >= ORPHANED_CHAT_MESSAGE_GRACE_MS
  );
}

export async function terminalizeChatMessageWithoutTask(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    assistantMessageId: string;
    deviceId?: string | null;
    failure?: { code: string; message: string };
  },
) {
  const failure = input.failure ?? {
    code: "chat_acceptance_timeout",
    message: ORPHANED_CHAT_MESSAGE_FAILURE_MESSAGE,
  };
  const updatedAt = new Date();
  const rows = await app.db
    .update(chatMessages)
    .set({
      status: "failed",
      error: failure.message,
      content: failure.message,
      contentBlobId: null,
      preview: compactMessagePreview(failure.message),
      tokenCount: estimateMessageTokens(failure.message),
      metadata: withAssistantBlocksMetadata(
        {
          failureReason: failure.code,
          streaming: false,
          terminal: true,
        },
        {
          content: failure.message,
          blocks: [],
          streaming: false,
        },
      ),
      updatedAt,
    })
    .where(
      and(
        eq(chatMessages.id, input.assistantMessageId),
        eq(chatMessages.sessionId, input.sessionId),
        eq(chatMessages.userId, input.userId),
        eq(chatMessages.role, "assistant"),
        isNull(chatMessages.taskId),
        sql`${chatMessages.status} not in ('completed', 'failed', 'canceled')`,
      ),
    )
    .returning();

  const assistantMessage = rows[0];
  if (!assistantMessage) return null;

  await app.db
    .update(chatSessions)
    .set({ updatedAt })
    .where(
      and(
        eq(chatSessions.id, input.sessionId),
        eq(chatSessions.userId, input.userId),
      ),
    );

  await app.services.eventBus.publish({
    topic: "chat.message.updated",
    userId: input.userId,
    deviceId: input.deviceId ?? undefined,
    payload: {
      sessionId: input.sessionId,
      assistantMessageId: assistantMessage.id,
      statusRank: 90,
      eventRank: 30,
      messageStatusRank: 90,
      terminal: true,
      presentation: "chat",
      assistantMessage: shapeAssistantMessagePayload(assistantMessage),
      taskStatus: "failed",
      task: null,
    },
  });

  return assistantMessage;
}

export async function reconcileOrphanedChatMessagesForSession(
  app: FastifyInstance,
  input: {
    userId: string;
    session: typeof chatSessions.$inferSelect;
  },
): Promise<number> {
  if (!app.services?.eventBus) return 0;
  const now = new Date();
  const cutoff = new Date(now.getTime() - ORPHANED_CHAT_MESSAGE_GRACE_MS);
  const orphaned = await app.db
    .select()
    .from(chatMessages)
    .where(
      and(
        eq(chatMessages.sessionId, input.session.id),
        eq(chatMessages.userId, input.userId),
        eq(chatMessages.role, "assistant"),
        isNull(chatMessages.taskId),
        inArray(chatMessages.status, ["queued", "running"]),
        lt(chatMessages.createdAt, cutoff),
      ),
    )
    .orderBy(asc(chatMessages.createdAt), asc(chatMessages.id))
    .limit(32);

  let reconciled = 0;
  for (const message of orphaned) {
    if (
      !shouldReconcileOrphanedChatMessage({
        role: message.role,
        status: message.status,
        taskId: message.taskId,
        createdAt: message.createdAt,
        now,
      })
    ) {
      continue;
    }
    if (
      await terminalizeChatMessageWithoutTask(app, {
        userId: input.userId,
        sessionId: input.session.id,
        assistantMessageId: message.id,
        deviceId: input.session.targetDeviceId,
      })
    ) {
      reconciled += 1;
    }
  }
  return reconciled;
}

/**
 * Bounded global sweep for rows that have no task and therefore can never be
 * reached by a task worker. Redis serializes the sweep across chat workers;
 * the CAS in terminalizeChatMessageWithoutTask handles a race with a late
 * task-link callback.
 */
export async function reconcileOrphanedChatMessagesBatch(
  app: FastifyInstance,
  input: { limit?: number } = {},
): Promise<number> {
  if (!app.services?.eventBus) return 0;
  const now = new Date();
  const cutoff = new Date(now.getTime() - ORPHANED_CHAT_MESSAGE_GRACE_MS);
  const orphaned = await app.db
    .select()
    .from(chatMessages)
    .where(
      and(
        eq(chatMessages.role, "assistant"),
        isNull(chatMessages.taskId),
        inArray(chatMessages.status, ["queued", "running"]),
        lt(chatMessages.createdAt, cutoff),
      ),
    )
    .orderBy(asc(chatMessages.createdAt), asc(chatMessages.id))
    .limit(Math.max(1, Math.min(200, Math.trunc(input.limit ?? 100))));

  let reconciled = 0;
  for (const message of orphaned) {
    if (
      !shouldReconcileOrphanedChatMessage({
        role: message.role,
        status: message.status,
        taskId: message.taskId,
        createdAt: message.createdAt,
        now,
      })
    ) {
      continue;
    }
    if (
      await terminalizeChatMessageWithoutTask(app, {
        userId: message.userId,
        sessionId: message.sessionId,
        assistantMessageId: message.id,
      })
    ) {
      reconciled += 1;
    }
  }
  return reconciled;
}
