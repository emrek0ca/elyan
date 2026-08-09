import { and, desc, eq, sql } from "drizzle-orm";
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
import {
  chatMessageStatusRank,
  chatStreamEventStatusRank,
  isTerminalChatMessageStatus,
} from "./stream-authority.js";

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

// Yönlendirme katmanının iç gerekçe cümleleri ("Kullanıcı dispatch butonu ile
// bu görevi masaüstüne yönlendirdi.") task.summary'ye sızabiliyor; bunlar
// asistan cevabı DEĞİLDİR ve kullanıcıya asla gösterilmez.
const INTERNAL_ROUTING_SUMMARY_PATTERN =
  /dispatch butonu|masaüstüne yönlendir|masaustune yonlendir|desktopa yönlendir|desktopa yonlendir|yönlendirildi|yonlendirildi|açıkça istedi|acikca istedi/i;

export function isInternalRoutingSummary(value: string): boolean {
  return INTERNAL_ROUTING_SUMMARY_PATTERN.test(value);
}

// Kuyruk/faz katmanının geçici ilerleme metinleri ("Yanıt hazırlanıyor.")
// task.summary'ye yazılır; görev terminal duruma geldiğinde bunlar asistan
// cevabı DEĞİLDİR ve kalıcı içerik/history'ye canonical metin olarak
// dönmemelidir. ("Yanıt sıraya alınamadı…" gibi gerçek hata metinleri bu
// kalıba girmez — onlar failed durumda kullanıcıya gösterilir.)
const TRANSIENT_PROGRESS_MESSAGE_PATTERN =
  /^yan[ıi]t (haz[ıi]rlan[ıi]yor|yeniden deneniyor|g[üu]venli (?:ş|s)ekilde tamamlan[ıi]yor)\.?$/i;

export function isTransientChatProgressMessage(value: string): boolean {
  return TRANSIENT_PROGRESS_MESSAGE_PATTERN.test(value.trim());
}

function deriveAssistantContent(input: {
  updatedTask: typeof tasks.$inferSelect;
  fallbackMessage?: string;
}): string {
  const finalize = (value: string | null | undefined) => {
    const sanitized = sanitizeAssistantVisibleText(value);
    return sanitized.trim();
  };
  const desktopTranscript = buildDesktopExecutionTranscript(input.updatedTask);
  if (desktopTranscript) {
    return finalize(desktopTranscript);
  }

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
              : typeof resultRecord.assistantMessage === "string"
                ? resultRecord.assistantMessage
                : typeof resultRecord.message === "string"
                  ? resultRecord.message
                  : typeof resultRecord.safeSummary === "string"
                    ? resultRecord.safeSummary
                    : null;
    if (text?.trim()) {
      return finalize(text);
    }
    const blockText = extractResultAssistantText(input.updatedTask);
    if (blockText) {
      return finalize(blockText);
    }
  }

  const terminalTask = ["completed", "failed", "canceled"].includes(
    input.updatedTask.status,
  );
  const summary = typeof input.updatedTask.summary === "string" ? input.updatedTask.summary : "";
  if (
    summary.trim() &&
    !isInternalRoutingSummary(summary) &&
    !isTransientChatProgressMessage(summary)
  ) {
    return finalize(summary);
  }

  if (
    input.fallbackMessage?.trim() &&
    !(terminalTask && isTransientChatProgressMessage(input.fallbackMessage))
  ) {
    return finalize(input.fallbackMessage);
  }

  const error = typeof input.updatedTask.error === "string" ? input.updatedTask.error : "";
  if (error.trim()) {
    return finalize(error);
  }

  // Terminal duruma gelmiş ama hiç kullanıcıya gösterilebilir metin
  // üretememiş görev: sessiz kalma ya da iç log basma — dürüst bir durum
  // cümlesi göster.
  if (input.updatedTask.status === "completed") {
    return "Görev masaüstünde tamamlandı ama sonuç metni iletilmedi. Ayrıntı için görev geçmişine bakabilirsin.";
  }
  if (input.updatedTask.status === "failed") {
    return "Görev masaüstünde tamamlanamadı. Tekrar denemek istersen görevi yeniden gönderebilirsin.";
  }

  return "";
}

function readExecutionStepText(
  step: Record<string, unknown>,
  keys: string[],
  maxLength: number,
): string | null {
  for (const key of keys) {
    const value = step[key];
    if (typeof value !== "string") {
      continue;
    }
    const compact = sanitizeAssistantVisibleText(value)
      .replace(/\s+/g, " ")
      .trim();
    if (!compact) {
      continue;
    }
    return compact.length <= maxLength
      ? compact
      : `${compact.slice(0, maxLength - 1).trimEnd()}…`;
  }
  return null;
}

function buildDesktopExecutionTranscript(
  task: typeof tasks.$inferSelect,
): string | null {
  const result =
    task.result && typeof task.result === "object" && !Array.isArray(task.result)
      ? (task.result as Record<string, unknown>)
      : null;
  if (!result) {
    return null;
  }
  const executionTrace =
    result.executionTrace &&
    typeof result.executionTrace === "object" &&
    !Array.isArray(result.executionTrace)
      ? (result.executionTrace as Record<string, unknown>)
      : null;
  const rawSteps = Array.isArray(executionTrace?.steps)
    ? executionTrace.steps
    : Array.isArray(executionTrace?.stepStates)
      ? executionTrace.stepStates
      : [];
  if (rawSteps.length === 0) {
    return null;
  }

  const stepLines: string[] = [];
  const seen = new Set<string>();
  for (const rawStep of rawSteps) {
    if (!rawStep || typeof rawStep !== "object" || Array.isArray(rawStep)) {
      continue;
    }
    const step = rawStep as Record<string, unknown>;
    const id = String(step.id ?? step.capability ?? `step_${stepLines.length + 1}`)
      .trim()
      .slice(0, 80);
    if (id && seen.has(id)) {
      continue;
    }
    if (id) {
      seen.add(id);
    }
    const status = String(step.status ?? "")
      .trim()
      .toLowerCase();
    if (
      status !== "completed" &&
      status !== "running" &&
      status !== "waiting_approval" &&
      status !== "failed" &&
      status !== "canceled" &&
      status !== "cancelled"
    ) {
      continue;
    }
    const label =
      readExecutionStepText(step, ["label", "capability"], 120) ??
      `Adım ${stepLines.length + 1}`;
    const detail = readExecutionStepText(
      step,
      [
        "resultSummary",
        "outputPreview",
        "detail",
        "stopReason",
        "errorCode",
      ],
      220,
    );
    const suffix = detail ? `: ${detail}` : "";
    const statusLabel =
      status === "completed"
        ? "tamamlandı"
        : status === "running"
          ? "yürütülüyor"
          : status === "waiting_approval"
            ? "onay bekliyor"
            : status === "failed"
              ? "tamamlanamadı"
              : "iptal edildi";
    stepLines.push(`${stepLines.length + 1}. ${label} ${statusLabel}${suffix}`);
    if (stepLines.length >= 16) {
      break;
    }
  }
  if (stepLines.length === 0) {
    return null;
  }

  const finalText =
    typeof result.final === "string"
      ? result.final
      : typeof result.finalAnswer === "string"
        ? result.finalAnswer
        : typeof result.answer === "string"
          ? result.answer
          : typeof result.text === "string"
            ? result.text
            : typeof result.assistantMessage === "string"
              ? result.assistantMessage
              : typeof result.message === "string"
                ? result.message
                : "";
  const safeFinal = sanitizeAssistantVisibleText(finalText)
    .replace(/\s+/g, " ")
    .trim();
  if (safeFinal) {
    return safeFinal.length <= 500 ? safeFinal : `${safeFinal.slice(0, 499).trimEnd()}…`;
  }
  return ["Adımlar:", ...stepLines].join("\n");
}

function hasDesktopExecutionTrace(task: typeof tasks.$inferSelect): boolean {
  const result =
    task.result && typeof task.result === "object" && !Array.isArray(task.result)
      ? (task.result as Record<string, unknown>)
      : null;
  const executionTrace =
    result?.executionTrace &&
    typeof result.executionTrace === "object" &&
    !Array.isArray(result.executionTrace)
      ? (result.executionTrace as Record<string, unknown>)
      : null;
  return Array.isArray(executionTrace?.steps) || Array.isArray(executionTrace?.stepStates);
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
  if (result.visionBlock && typeof result.visionBlock === "object" && !Array.isArray(result.visionBlock)) {
    metadata.visionBlock = result.visionBlock;
  }
  if (hasDesktopExecutionTrace(task)) {
    metadata.desktopExecution = {
      transcript: true,
      source: "executionTrace",
      appendMode: "cumulative",
    };
  }

  // Skill selection is backend truth. Carry only the public, bounded identity
  // into the chat message so mobile can render the existing skill indicator;
  // prompts, tool arguments and raw retrieval content remain task-internal.
  const skillId =
    typeof result.skillId === "string" ? result.skillId.trim() : "";
  const safeSkillId = /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$/.test(skillId)
    ? skillId
    : null;
  metadata.skillUsed = result.skillUsed === true && safeSkillId != null;
  metadata.skillId = metadata.skillUsed ? safeSkillId : null;

  return metadata;
}

function normalizeResultAssistantBlocks(
  task: typeof tasks.$inferSelect,
): AssistantMessageBlock[] {
  const result =
    task.result && typeof task.result === "object" && !Array.isArray(task.result)
      ? (task.result as Record<string, unknown>)
      : {};
  const rawBlocks = Array.isArray(result.assistantBlocks)
    ? result.assistantBlocks
    : Array.isArray(result.blocks)
      ? result.blocks
      : [];
  return normalizeAssistantMessageBlocks({
    blocks: rawBlocks,
  });
}

function extractResultAssistantText(task: typeof tasks.$inferSelect): string {
  return normalizeResultAssistantBlocks(task)
    .map((block) => (block.type === "text" ? block.markdown.trim() : ""))
    .filter(Boolean)
    .join("\n\n");
}

function extractResultAssistantBlocks(
  task: typeof tasks.$inferSelect,
): AssistantMessageBlock[] {
  return normalizeResultAssistantBlocks(task).filter(
    (block) => block.type !== "text" && block.type !== "task_trace",
  );
}

function extractConnectorTaskTraceBlock(
  task: typeof tasks.$inferSelect,
): AssistantMessageBlock | null {
  const result =
    task.result && typeof task.result === "object" && !Array.isArray(task.result)
      ? (task.result as Record<string, unknown>)
      : null;
  const approval =
    task.approvalRequest &&
    typeof task.approvalRequest === "object" &&
    !Array.isArray(task.approvalRequest)
      ? (task.approvalRequest as Record<string, unknown>)
      : null;
  const connectorTraceIsAuthoritative =
    (task.status === "waiting_approval" &&
      approval?.kind === "connector_write") ||
    (result?.connectorWriteExecution != null &&
      typeof result.connectorWriteExecution === "object" &&
      !Array.isArray(result.connectorWriteExecution));
  if (!connectorTraceIsAuthoritative) {
    return null;
  }
  return (
    normalizeResultAssistantBlocks(task).find(
      (block) => block.type === "task_trace",
    ) ?? null
  );
}

function clipSummaryText(value: string | null | undefined, maxLength: number) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function scrubSummaryText(value: string | null | undefined, maxLength: number) {
  return clipSummaryText(value, maxLength)
    .replace(/https?:\/\/\S+/gi, "[url]")
    .replace(/(?:\/Users\/|\/home\/|C:\\Users\\)[^\s]+/gi, "[path]")
    .replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, "[email]")
    .replace(/\b(?:\+?\d[\d\s().-]{7,}\d)\b/g, "[number]");
}

function buildRollingSummaryFromTask(input: {
  task: typeof tasks.$inferSelect;
  assistantContent: string;
  previousRollingSummary?: Record<string, unknown> | null;
}) {
  const openLoops: string[] = Array.isArray(input.previousRollingSummary?.openLoops)
    ? input.previousRollingSummary.openLoops
        .map((value) => scrubSummaryText(String(value ?? ""), 140))
        .filter(Boolean)
    : [];
  if (input.task.status === "waiting_approval") {
    if (!openLoops.includes("Kullanıcı onayı bekleniyor.")) {
      openLoops.unshift("Kullanıcı onayı bekleniyor.");
    }
  }
  if (input.task.status === "failed" && input.task.error?.trim()) {
    const failureLoop = scrubSummaryText(input.task.error, 140);
    if (failureLoop && !openLoops.includes(failureLoop)) {
      openLoops.unshift(failureLoop);
    }
  }
  const previousContextNotes = Array.isArray(input.previousRollingSummary?.contextNotes)
    ? input.previousRollingSummary.contextNotes
        .map((value) => scrubSummaryText(String(value ?? ""), 160))
        .filter(Boolean)
    : [];
  const contextNotes = [input.task.summary, input.task.title, ...previousContextNotes]
    .map((value) => (typeof value === "string" ? scrubSummaryText(value, 160) : ""))
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index)
    .slice(0, 4);

  return {
    userGoal: scrubSummaryText(input.task.title, 180) || "Sohbet hedefi",
    assistantState: scrubSummaryText(input.assistantContent, 220),
    ...(openLoops.length > 0 ? { openLoops: openLoops.slice(0, 6) } : {}),
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
    taskTraceBlock: ReturnType<typeof buildTaskTraceBlock> | null;
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
  const desktopTranscriptOwnsText = hasDesktopExecutionTrace(input.task);

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
  } else if (
    input.task.status === "completed" &&
    summary &&
    !desktopTranscriptOwnsText
  ) {
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

function shouldExposeTaskTrace(task: typeof tasks.$inferSelect): boolean {
  const routeDecision = extractTaskRouteDecision(task.payload);
  if (routeDecision?.route !== "server_brain") {
    return true;
  }
  return (
    routeDecision.taskRoute?.needsDesktop === true ||
    routeDecision.taskRoute?.operationalRoute === "desktop_runtime"
  );
}

export function sanitizeHumanizedTerminalTaskContent(
  value: string | null | undefined,
  fallback: string | null | undefined = "",
): string {
  const safeFallback = sanitizeAssistantVisibleText(fallback);
  return sanitizeAssistantVisibleText(value, { fallback: safeFallback });
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
  const sessionId = metadata?.sessionId;
  const assistantMessageId = metadata?.assistantMessageId;
  if (!sessionId || !assistantMessageId) {
    return;
  }

  const assistantStatus = mapTaskStatusToChatStatus(input.updatedTask.status);
  // Chat cevabı tek kaynaklıdır. Task lifecycle sync burada ikinci bir LLM
  // "humanize" çağrısı yapmaz; sadece görünür metni güvenli şekilde normalize
  // eder. Böylece ana cevap geldikten sonra başka bir katman aynı mesajı
  // değiştiremez veya "servis yok" hatasıyla ezemez.
  const assistantContent = sanitizeHumanizedTerminalTaskContent(
    deriveAssistantContent({
      updatedTask: input.updatedTask,
      fallbackMessage: input.message,
    }),
  );
  const generatedTaskTraceBlock = shouldExposeTaskTrace(input.updatedTask)
    ? buildTaskTraceBlock({
        task: input.updatedTask,
        assistantContent,
      })
    : null;
  const taskTraceBlock =
    extractConnectorTaskTraceBlock(input.updatedTask) ??
    generatedTaskTraceBlock;
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
  const nextAssistantMetadata = withAssistantBlocksMetadata(assistantMetadata, {
    content: assistantContent,
    blocks: assistantBlocks,
  });
  if (input.updatedTask.status === "completed") {
    void applyGoalProgressBlocks(app, {
      userId: input.updatedTask.userId,
      blocks: assistantBlocks,
    });
  }
  // Cevap TEK kaynaktan gelir: inference'ın kalıcı finali. "Yanıt
  // hazırlanıyor." / "Yanıt yeniden deneniyor." gibi kuyruk/faz metinleri
  // non-terminal güncellemelerde chat satırının content'ine ASLA yazılmaz —
  // aksi hâlde REST history/dispatch cevabı bu metni "cevap" olarak taşır ve
  // eski istemciler akan cevabın üstüne yazar. Satırda content ve preview
  // korunur; canlı task-trace blokları ise metadata üzerinden ilerlemeye devam
  // eder.
  const preserveExistingContent =
    !isTerminalChatMessageStatus(assistantStatus) &&
    isTransientChatProgressMessage(assistantContent);
  const contentBlob = preserveExistingContent
    ? null
    : await app.services?.blobs?.storeText({
        ownerType: "chat_message",
        ownerId: assistantMessageId,
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
      error: input.updatedTask.error,
      updatedAt: new Date(),
      metadata: sql`${chatMessages.metadata} || ${JSON.stringify(
        nextAssistantMetadata,
      )}::jsonb`,
      ...(preserveExistingContent
        ? {}
        : {
            content: assistantContent,
            contentBlobId: contentBlob?.blobId ?? null,
            preview: compactMessagePreview(assistantContent),
            tokenCount: estimateMessageTokens(assistantContent),
          }),
    })
    .where(
      and(
        eq(chatMessages.id, assistantMessageId),
        eq(chatMessages.sessionId, sessionId),
        eq(chatMessages.userId, input.updatedTask.userId),
        sql`${chatMessages.status} not in ('completed', 'failed', 'canceled')`,
      ),
    )
    .returning();

  const assistantMessage = rows[0];
  if (!assistantMessage) {
    return;
  }

  const sessionUpdateTime = new Date();
  const updateSessionContext = async (tx: typeof app.db) => {
    if (typeof tx.select !== "function" || typeof tx.update !== "function") {
      await tx
        .update(chatSessions)
        .set({ lastMessageAt: sessionUpdateTime, updatedAt: sessionUpdateTime })
        .where(and(eq(chatSessions.id, sessionId), eq(chatSessions.userId, input.updatedTask.userId)));
      return;
    }
    const sessionQuery = tx
      .select({ metadata: chatSessions.metadata })
      .from(chatSessions)
      .where(and(eq(chatSessions.id, sessionId), eq(chatSessions.userId, input.updatedTask.userId)));
    const queryWithOptionalLock = sessionQuery as unknown as {
      for?: (mode: "update") => Promise<Array<{ metadata: unknown }>>;
    };
    const lockedSessionRows = typeof queryWithOptionalLock.for === "function"
      ? await queryWithOptionalLock.for("update")
      : await sessionQuery;
    const sessionMetadata = lockedSessionRows[0]?.metadata;
    const existingChatContext =
      sessionMetadata && typeof sessionMetadata === "object" && !Array.isArray(sessionMetadata)
        ? (sessionMetadata as Record<string, unknown>).chatContext
        : null;
    const previousRollingSummary =
      existingChatContext && typeof existingChatContext === "object" && !Array.isArray(existingChatContext)
        ? (existingChatContext as Record<string, unknown>).rollingSummary
        : null;
    const rollingSummary = buildRollingSummaryFromTask({
      task: input.updatedTask,
      assistantContent,
      previousRollingSummary:
        previousRollingSummary && typeof previousRollingSummary === "object" && !Array.isArray(previousRollingSummary)
          ? previousRollingSummary as Record<string, unknown>
          : null,
    });
    await tx
      .update(chatSessions)
      .set({
        metadata: sql`
          coalesce(${chatSessions.metadata}, '{}'::jsonb) ||
          jsonb_build_object(
            'chatContext',
            coalesce(${chatSessions.metadata}->'chatContext', '{}'::jsonb) ||
            ${JSON.stringify({
              rollingSummary,
              lastAssistantBlocksDigest: scrubSummaryText(assistantContent, 280),
              updatedAt: sessionUpdateTime.toISOString(),
            })}::jsonb
          )
        `,
        lastMessageAt: sessionUpdateTime,
        updatedAt: sessionUpdateTime,
      })
      .where(and(eq(chatSessions.id, sessionId), eq(chatSessions.userId, input.updatedTask.userId)));
  };
  if (typeof app.db.transaction === "function") {
    await app.db.transaction(updateSessionContext);
  } else {
    // Small unit-test doubles and legacy adapters may not expose transactions;
    // the production Drizzle database always takes the transactional branch.
    await updateSessionContext(app.db);
  }

  await app.services.eventBus.publish({
    topic: "chat.message.updated",
    userId: input.updatedTask.userId,
    deviceId: input.updatedTask.targetDeviceId,
    taskId: input.updatedTask.id,
    payload: {
      sessionId,
      assistantMessageId,
      // Event sırası ile mesaj lifecycle durumu ayrı eksenlerdir. Eski
      // istemciler için statusRank lifecycle değerini korurken yeni istemci
      // eventRank'i metin deltası fence'i olarak kullanır.
      statusRank: chatMessageStatusRank(assistantStatus),
      eventRank: chatStreamEventStatusRank("chat.message.updated"),
      messageStatusRank: chatMessageStatusRank(assistantStatus),
      terminal: isTerminalChatMessageStatus(assistantStatus),
      presentation: extractTaskPresentation(input.updatedTask.payload),
      assistantMessage: shapeAssistantMessagePayload({
        ...assistantMessage,
        metadata: nextAssistantMetadata,
      }),
      taskStatus: input.updatedTask.status,
      task: shapeTaskFeedItem(input.updatedTask),
    },
  });
}

/**
 * Bir sohbet oturumundaki son ASİSTAN cevabının metnini döndürür.
 *
 * NEDEN: mobilde "bunu belge yap" dendiğinde belgelenecek içerik önceki
 * cevaptır — ama o cevap mobilde de masaüstünde de değil, BURADA durur.
 * `understanding_envelope.conversation_state.lastAssistantSummary` alanı
 * yıllardır şemada vardı, `contextPack` ile masaüstüne dispatch ediliyordu ve
 * masaüstü artık onu okuyor; fakat alanı DOLDURAN kimse yoktu — ne mobil
 * istemci gönderiyordu ne backend türetiyordu. Zincirin kaynak ucu buydu.
 *
 * Uydurma yok: gerçekten kaydedilmiş bir asistan mesajı yoksa null döner ve
 * çağıran mevcut davranışını (sorma) sürdürür.
 */
export async function getLastAssistantMessageText(
  app: FastifyInstance,
  input: { userId: string; sessionId: string },
): Promise<string | null> {
  const sessionId = String(input.sessionId ?? "").trim();
  const userId = String(input.userId ?? "").trim();
  if (!sessionId || !userId) return null;
  try {
    const rows = await app.db
      .select({ content: chatMessages.content, preview: chatMessages.preview })
      .from(chatMessages)
      .where(
        and(
          eq(chatMessages.sessionId, sessionId),
          eq(chatMessages.userId, userId),
          eq(chatMessages.role, "assistant"),
          eq(chatMessages.status, "completed"),
        ),
      )
      .orderBy(desc(chatMessages.createdAt))
      .limit(1);
    const row = rows[0];
    if (!row) return null;
    const text = String(row.content ?? "").trim() || String(row.preview ?? "").trim();
    return text ? text : null;
  } catch {
    // Süreklilik bir kolaylıktır, bir bağımlılık değil: sorgu patlarsa görev
    // oluşturma düşmez, yalnız taşınan içerik olmaz.
    return null;
  }
}
