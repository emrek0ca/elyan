import { and, eq, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { chatMessages, chatSessions, tasks } from "../../db/schema.js";
import type { TaskStatus } from "../../contracts/domain.js";
import {
  extractTaskPresentation,
  extractTaskRouteDecision,
  shapeTaskFeedItem,
} from "../tasks/service-helpers.js";
import { applyGoalProgressBlocks } from "../goals/service.js";
import {
  type AssistantMessageBlock,
  buildAssistantActionableBlock,
  composeAssistantMessageBlocks,
  buildAssistantStatusBlock,
  buildAssistantSummaryBlock,
  normalizeAssistantMessageBlocks,
  sanitizeAssistantVisibleText,
  shapeAssistantMessagePayload,
  withAssistantBlocksMetadata,
} from "./message-blocks.js";
import { buildTaskTraceBlock } from "./task-trace.js";

type ChatMetadata = {
  sessionId?: string;
  userMessageId?: string;
  assistantMessageId?: string;
};

function extractChatMetadata(task: typeof tasks.$inferSelect): ChatMetadata | null {
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

  const value = chat as Record<string, unknown>;
  return {
    sessionId: typeof value.sessionId === "string" ? value.sessionId : undefined,
    userMessageId: typeof value.userMessageId === "string" ? value.userMessageId : undefined,
    assistantMessageId: typeof value.assistantMessageId === "string" ? value.assistantMessageId : undefined,
  };
}

function mapTaskStatusToChatStatus(status: TaskStatus) {
  switch (status) {
    case "queued":
    case "planning":
      return "queued";
    case "running":
      return "running";
    case "waiting_approval":
      return "waiting_approval";
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    case "canceled":
      return "canceled";
  }
}

export function compactMessagePreview(value: string, maxLength = 320) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return null;
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function estimateMessageTokens(value: string) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return 0;
  }
  return Math.max(1, Math.ceil(normalized.length / 4));
}

function deriveAssistantContent(input: {
  updatedTask: typeof tasks.$inferSelect;
  fallbackMessage?: string;
}): string {
  const finalize = (value: string | null | undefined) => {
    const sanitized = sanitizeAssistantVisibleText(value);
    return sanitized.trim();
  };

  if (input.updatedTask.status === "waiting_approval") {
    const approvalRequest = input.updatedTask.approvalRequest;
    if (approvalRequest && typeof approvalRequest === "object" && !Array.isArray(approvalRequest)) {
      const approvalRecord = approvalRequest as Record<string, unknown>;
      const resolution = approvalRecord.resolution;
      const resolutionRecord =
        resolution && typeof resolution === "object" && !Array.isArray(resolution)
          ? (resolution as Record<string, unknown>)
          : null;
      const resolutionStatus = String(resolutionRecord?.status ?? "").trim().toLowerCase();
      const resolutionApproved =
        resolutionRecord?.approved === true ||
        resolutionStatus === "approved" ||
        resolutionStatus === "accepted" ||
        resolutionStatus === "confirmed";
      if (!resolutionApproved) {
        const approvalText =
          typeof approvalRecord.message === "string" && approvalRecord.message.trim()
            ? approvalRecord.message
            : typeof approvalRecord.summary === "string" && approvalRecord.summary.trim()
              ? approvalRecord.summary
              : "";
        if (approvalText.trim()) {
          return finalize(approvalText);
        }
      }
    }
  }

  const result = input.updatedTask.result;
  if (result && typeof result === "object" && !Array.isArray(result)) {
    const resultRecord = result as Record<string, unknown>;
    const text: string | null =
      typeof resultRecord.final === "string"
        ? resultRecord.final
        : typeof resultRecord.finalAnswer === "string"
          ? resultRecord.finalAnswer
          : typeof resultRecord.answer === "string"
            ? resultRecord.answer
            : typeof resultRecord.text === "string"
              ? resultRecord.text
              : typeof resultRecord.message === "string"
                ? resultRecord.message
                : null;
    if (text?.trim()) {
      return finalize(text);
    }
  }

  const summary = typeof input.updatedTask.summary === "string" ? input.updatedTask.summary : "";
  if (summary.trim()) {
    return finalize(summary);
  }

  if (input.fallbackMessage?.trim()) {
    return finalize(input.fallbackMessage);
  }

  const error = typeof input.updatedTask.error === "string" ? input.updatedTask.error : "";
  if (error.trim()) {
    return finalize(error);
  }

  return "";
}

function buildAssistantMetadataFromTask(task: typeof tasks.$inferSelect): Record<string, unknown> {
  const result =
    task.result && typeof task.result === "object" && !Array.isArray(task.result)
      ? (task.result as Record<string, unknown>)
      : {};
  const renderRecipe =
    result.renderRecipe && typeof result.renderRecipe === "object" && !Array.isArray(result.renderRecipe)
      ? result.renderRecipe
      : null;
  const metadata: Record<string, unknown> = {
    task: {
      id: task.id,
      status: task.status,
    },
  };

  if (renderRecipe) {
    metadata.renderRecipe = renderRecipe;
    metadata.generatedOutput = {
      type: "render_recipe",
      format:
        typeof (renderRecipe as Record<string, unknown>).format === "string"
          ? (renderRecipe as Record<string, unknown>).format
          : null,
      outputType:
        typeof (renderRecipe as Record<string, unknown>).output_type === "string"
          ? (renderRecipe as Record<string, unknown>).output_type
          : null,
    };
  }

  return metadata;
}

function extractResultAssistantBlocks(task: typeof tasks.$inferSelect): AssistantMessageBlock[] {
  const result =
    task.result && typeof task.result === "object" && !Array.isArray(task.result)
      ? (task.result as Record<string, unknown>)
      : {};
  return normalizeAssistantMessageBlocks({
    blocks: Array.isArray(result.assistantBlocks) ? result.assistantBlocks : [],
  }).filter((block) => block.type !== "text");
}

function clipSummaryText(value: string | null | undefined, maxLength: number) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function buildRollingSummaryFromTask(input: {
  task: typeof tasks.$inferSelect;
  assistantContent: string;
}) {
  const openLoops: string[] = [];
  if (input.task.status === "waiting_approval") {
    openLoops.push("Kullanıcı onayı bekleniyor.");
  }
  if (input.task.status === "failed" && input.task.error?.trim()) {
    openLoops.push(clipSummaryText(input.task.error, 140));
  }
  const contextNotes = [input.task.summary, input.task.title]
    .map((value) => (typeof value === "string" ? clipSummaryText(value, 160) : ""))
    .filter(Boolean)
    .slice(0, 2);

  return {
    userGoal: clipSummaryText(input.task.title, 180) || "Sohbet hedefi",
    assistantState: clipSummaryText(input.assistantContent, 220),
    ...(openLoops.length > 0 ? { openLoops } : {}),
    ...(contextNotes.length > 0 ? { contextNotes } : {}),
    updatedAt: new Date().toISOString(),
  };
}

function buildShortSummary(value: string): string | null {
  const compact = sanitizeAssistantVisibleText(value).replace(/\s+/g, " ").trim();
  if (!compact) {
    return null;
  }
  const sentence = compact.split(/(?<=[.!?])\s+/)[0]?.trim() ?? compact;
  const summary = sentence.length <= 180 ? sentence : `${sentence.slice(0, 179).trimEnd()}…`;
  return summary || null;
}

function buildLifecycleBlocks(
  app: FastifyInstance,
  input: {
    task: typeof tasks.$inferSelect;
    assistantContent: string;
    taskTraceBlock: ReturnType<typeof buildTaskTraceBlock>;
    resultBlocks?: AssistantMessageBlock[];
  },
) {
  const blocks: AssistantMessageBlock[] = [];
  if (!app.config.ELYAN_BLOCKS_V11_ENABLED) {
    return [...(input.resultBlocks ?? []), input.taskTraceBlock];
  }
  const routeDecision = extractTaskRouteDecision(input.task.payload);
  const normalizedError = String(input.task.error ?? "").trim().toLowerCase();
  const summary = buildShortSummary(input.assistantContent);

  if (input.task.status === "waiting_approval") {
    blocks.push(
      buildAssistantStatusBlock({
        status: "waiting_approval",
        title: "Onay bekleniyor",
        detail: "Devam etmek için kullanıcı onayı gerekiyor.",
      }),
    );
    blocks.push(
      buildAssistantActionableBlock({
        kind: "approval_needed",
        title: "Onayı aç",
        detail: "İlgili onayı verdikten sonra görev devam eder.",
      }),
    );
  } else if (
    routeDecision?.route === "pairing_required" ||
    normalizedError.includes("pairing_required") ||
    normalizedError.includes("desktop_required")
  ) {
    blocks.push(
      buildAssistantStatusBlock({
        status: "needs_desktop",
        title: "Masaüstü gerekiyor",
        detail: "Bu iş için bağlı bir masaüstü seçilmeli.",
      }),
    );
    blocks.push(
      buildAssistantActionableBlock({
        kind: "choose_device",
        title: "Cihaz seç",
        detail: "Bağlı masaüstü seçildikten sonra yeniden deneyebilirsin.",
      }),
    );
  } else if (input.task.status === "failed") {
    blocks.push(
      buildAssistantStatusBlock({
        status: "failed",
        title: "İşlem tamamlanamadı",
        detail: input.task.error ?? "Görev güvenli biçimde durduruldu.",
      }),
    );
    blocks.push(
      buildAssistantActionableBlock({
        kind: "retry_option",
        title: "Yeniden dene",
        detail: "Bağlantıyı veya cihaz durumunu kontrol edip tekrar gönderebilirsin.",
      }),
    );
  } else if (input.task.status === "running") {
    // While running, the only running-state UI is the quiet wave carried by the
    // task trace block. No "İşlem sürüyor / Cevap hazırlanıyor" status card — it
    // just clutters the surface while the answer is already streaming in.
  } else if (input.task.status === "completed" && summary) {
    blocks.push(
      buildAssistantSummaryBlock(summary, {
        title: "Sonuç",
      }),
    );
  }

  if (
    summary &&
    input.task.status !== "completed" &&
    input.task.status !== "running"
  ) {
    blocks.push(
      buildAssistantSummaryBlock(summary, {
        title: "Kısa sonuç",
        priority: 1,
      }),
    );
  }

  blocks.push(...(input.resultBlocks ?? []));
  blocks.push(input.taskTraceBlock);
  return blocks.filter(Boolean);
}

export async function syncChatTaskLifecycle(
  app: FastifyInstance,
  input: {
    originalTask: typeof tasks.$inferSelect;
    updatedTask: typeof tasks.$inferSelect;
    message?: string;
  },
) {
  const metadata = extractChatMetadata(input.originalTask);
  if (!metadata?.sessionId || !metadata.assistantMessageId) {
    return;
  }

  const assistantStatus = mapTaskStatusToChatStatus(input.updatedTask.status);
  const assistantContent = deriveAssistantContent({
    updatedTask: input.updatedTask,
    fallbackMessage: input.message,
  });
  const taskTraceBlock = buildTaskTraceBlock({
    task: input.updatedTask,
    assistantContent,
  });
  const assistantMetadata = buildAssistantMetadataFromTask(input.updatedTask);
  const assistantBlocks = composeAssistantMessageBlocks({
    content: assistantContent,
    blocks: buildLifecycleBlocks(app, {
      task: input.updatedTask,
      assistantContent,
      taskTraceBlock,
      resultBlocks: extractResultAssistantBlocks(input.updatedTask),
    }),
  });
  if (input.updatedTask.status === "completed") {
    void applyGoalProgressBlocks(app, {
      userId: input.updatedTask.userId,
      blocks: assistantBlocks,
    });
  }
  const contentBlob = await app.services?.blobs?.storeText({
    ownerType: "chat_message",
    ownerId: metadata.assistantMessageId,
    userId: input.updatedTask.userId,
    slot: "content",
    scope: "chat_message_content",
    value: assistantContent,
    contentType: "text/plain",
  });

  const rows = await app.db
    .update(chatMessages)
    .set({
      status: assistantStatus,
      content: assistantContent,
      contentBlobId: contentBlob?.blobId ?? null,
      preview: compactMessagePreview(assistantContent),
      tokenCount: estimateMessageTokens(assistantContent),
      error: input.updatedTask.error,
      metadata: sql`${chatMessages.metadata} || ${JSON.stringify(
        withAssistantBlocksMetadata(assistantMetadata, {
          content: assistantContent,
          blocks: assistantBlocks,
        }),
      )}::jsonb`,
      updatedAt: new Date(),
    })
    .where(
      and(
        eq(chatMessages.id, metadata.assistantMessageId),
        eq(chatMessages.sessionId, metadata.sessionId),
        eq(chatMessages.userId, input.updatedTask.userId),
      ),
    )
    .returning();

  const assistantMessage = rows[0];
  if (!assistantMessage) {
    return;
  }

  const sessionUpdateTime = new Date();
  const rollingSummary = buildRollingSummaryFromTask({
    task: input.updatedTask,
    assistantContent,
  });
  await app.db
    .update(chatSessions)
    .set({
      metadata: sql`${chatSessions.metadata} || ${JSON.stringify({
        chatContext: {
          rollingSummary,
          lastAssistantBlocksDigest: clipSummaryText(assistantContent, 280),
          updatedAt: sessionUpdateTime.toISOString(),
        },
      })}::jsonb`,
      lastMessageAt: sessionUpdateTime,
      updatedAt: sessionUpdateTime,
    })
    .where(and(eq(chatSessions.id, metadata.sessionId), eq(chatSessions.userId, input.updatedTask.userId)));

  await app.services.eventBus.publish({
    topic: "chat.message.updated",
    userId: input.updatedTask.userId,
    deviceId: input.updatedTask.targetDeviceId,
    taskId: input.updatedTask.id,
    payload: {
      sessionId: metadata.sessionId,
      presentation: extractTaskPresentation(input.updatedTask.payload),
      assistantMessage: shapeAssistantMessagePayload({
        ...assistantMessage,
        metadata: withAssistantBlocksMetadata(assistantMetadata, {
          content: assistantContent,
          blocks: assistantBlocks,
        }),
      }),
      taskStatus: input.updatedTask.status,
      task: shapeTaskFeedItem(input.updatedTask),
    },
  });
}
