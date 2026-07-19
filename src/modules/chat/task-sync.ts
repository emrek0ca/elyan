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

// Yönlendirme katmanının iç gerekçe cümleleri ("Kullanıcı dispatch butonu ile
// bu görevi masaüstüne yönlendirdi.") task.summary'ye sızabiliyor; bunlar
// asistan cevabı DEĞİLDİR ve kullanıcıya asla gösterilmez.
const INTERNAL_ROUTING_SUMMARY_PATTERN =
  /dispatch butonu|masaüstüne yönlendir|masaustune yonlendir|desktopa yönlendir|desktopa yonlendir|yönlendirildi|yonlendirildi|açıkça istedi|acikca istedi/i;

export function isInternalRoutingSummary(value: string): boolean {
  return INTERNAL_ROUTING_SUMMARY_PATTERN.test(value);
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

  const summary = typeof input.updatedTask.summary === "string" ? input.updatedTask.summary : "";
  if (summary.trim() && !isInternalRoutingSummary(summary)) {
    return finalize(summary);
  }

  if (input.fallbackMessage?.trim()) {
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
    (block) => block.type !== "text",
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

// Mekanik görev sonuçlarını doğal dile çeviren hafif beyin geçişi. Yalnız
// terminal durum + kısa/terse metin için çalışır; zengin (uzun/markdown)
// cevaplara dokunmaz. Zaman aşımı/başarısızlıkta ham metin döner.
const HUMANIZE_MAX_SOURCE_CHARS = 320;
const HUMANIZE_TIMEOUT_MS = 6_000;

// Jenerik durum/tamamlanma kelimeleri BİLGİ taşımaz. Bunlar dayanak sayılırsa
// "işlem tamam" gibi boş bir sonuç, "Son dört e-postayı okudum, tamamlandı."
// uydurmasını doğrulamış gibi görünür (tamam↔tamamlandı). Kapı yalnız ANLAMLI
// örtüşmeyi kabul etmeli.
const GROUNDING_STOP_STEMS = new Set([
  "tamam", "islem", "basar", "hazir", "gorev", "oldu", "sonuc", "yapil",
  "gerce", "devam", "lutfe", "durum", "bilgi", "asama", "calis", "olust",
  "kayde", "guncel", "verdi", "aldim", "ettim", "edild", "ldi", "sizin",
]);

/** Türkçe ekleri ve aksanları normalleştirerek kaba kök çıkarır. */
function groundingStems(value: string): Set<string> {
  const stems = new Set<string>();
  const normalized = value
    .toLocaleLowerCase("tr")
    .replace(/ı/g, "i")
    .replace(/ş/g, "s")
    .replace(/ç/g, "c")
    .replace(/ğ/g, "g")
    .replace(/ö/g, "o")
    .replace(/ü/g, "u");
  for (const raw of normalized.split(/[^\p{L}\p{N}]+/u)) {
    if (raw.length < 4) continue;
    const stem = raw.slice(0, 5);
    if (GROUNDING_STOP_STEMS.has(stem)) continue;
    stems.add(stem);
  }
  return stems;
}

/**
 * Yeniden ifade, kaynak metne dayanmak ZORUNDA. Kaynakta hiçbir anlamlı kelimeye
 * değmeyen bir çıktı, yeniden ifade değil uydurmadır ("Son dört e-postayı
 * okudum" gibi) ve reddedilir. Kaynakta anlamlı kelime yoksa kapı uygulanmaz.
 */
export function isGroundedRewrite(source: string, rewritten: string): boolean {
  const sourceStems = groundingStems(source);
  // Kaynakta anlamlı hiçbir kelime yoksa ("işlem tamam", "Görev tamamlandı.")
  // yeniden ifade edilecek bir bilgi de yoktur. Bu durumda her türlü zengin
  // çıktı uydurmadır — ham metin aynen korunur. (Eskiden burada true dönülüyordu
  // ve kapı tam da en tehlikeli vakada devre dışı kalıyordu.)
  if (sourceStems.size === 0) return false;
  const rewrittenStems = groundingStems(rewritten);
  for (const stem of rewrittenStems) {
    if (sourceStems.has(stem)) return true;
  }
  return false;
}

export function sanitizeHumanizedTerminalTaskContent(
  value: string | null | undefined,
  fallback: string | null | undefined = "",
): string {
  const safeFallback = sanitizeAssistantVisibleText(fallback);
  return sanitizeAssistantVisibleText(value, { fallback: safeFallback });
}

async function humanizeTerminalTaskContent(
  app: FastifyInstance,
  input: {
    task: typeof tasks.$inferSelect;
    content: string;
  },
): Promise<string> {
  const status = input.task.status;
  const safeInputContent = sanitizeHumanizedTerminalTaskContent(input.content);
  const content = safeInputContent.trim();
  if (!content) return safeInputContent;
  if (status !== "completed" && status !== "failed") return safeInputContent;
  if (content.length > HUMANIZE_MAX_SOURCE_CHARS) return safeInputContent;
  // Markdown/çok satırlı zengin içerik zaten insan elinden çıkmış gibidir.
  if (content.includes("\n") || /[#*`|]/.test(content)) return safeInputContent;

  try {
    const { generateGovernedSharedBrainReply } = await import(
      "../brain/inference.js"
    );
    // KRİTİK: Bu geçişe kullanıcının isteği ve görev durumu VERİLMEZ. Daha önce
    // veriliyordu ve zayıf fast-model, içeriğe hiç bakmadan istekten+durumdan
    // başarı cümlesi uyduruyordu ("Mailleri oku son 4 maili" + "tamamlandı" →
    // "Son dört e-postayı okudum, tamamlandı." — hiç mail verisi olmadan).
    // Model artık YALNIZ ham metni görür; yeniden ifade edebilir, iddia üretemez.
    const inference = await generateGovernedSharedBrainReply(app, {
      userId: input.task.userId,
      taskId: input.task.id,
      title: "Görev sonucu",
      prompt: [
        "Aşağıdaki metni kullanıcıya tek (en fazla iki) cümlelik doğal, samimi Türkçe ile yeniden ifade et.",
        "SADECE bu metinde yazan bilgiyi kullan. Metinde olmayan hiçbir eylem, sonuç, veri veya başarı iddiası EKLEME.",
        "Bir şeyi okuduğunu, getirdiğinin, hazırladığını veya tamamladığını metin bunu söylemiyorsa ASLA yazma.",
        "Teknik jargon ve yol adlarını tekrar etme. SADECE yeniden ifade edilmiş metni yaz.",
        "---",
        content,
      ].join("\n"),
      workload: "mobile_chat_fast",
      route: "task_result_humanize",
      meteringSurface: "task",
      maxCompletionTokensOverride: 120,
      timeoutMsOverride: HUMANIZE_TIMEOUT_MS,
      requestMetadata: { taskResultHumanize: true },
      internalEvaluation: {
        skipUsageValidation: true,
        skipReviewLogging: true,
        refinementPass: true,
      },
    });
    let rewritten = inference.text.trim();
    // Zayıf fast-model bazen prompt etiketlerini ("Görev durumu: tamamlandı",
    // "Ham sonuç: ...", "Görev tamamlandı.") çıktıya papağanlar; bunları
    // temizle. Baştaki bu iskele parçaları soyulunca geriye doğal cevap kalır
    // ("Selam! Görev tamamlandı. Ham sonuç: X" → "X").
    rewritten = rewritten
      .replace(
        /^(?:selam[!.]?\s*)?(?:g[öo]rev\s+(?:durumu\s*:?\s*)?(?:tamamland[ıi]|ba[şs]ar[ıi]s[ıi]z(?:\s+oldu)?)[.:]?\s*)+/i,
        "",
      )
      .replace(/(?:^|\s)ham\s+sonu[çc]\s*:\s*/i, " ")
      .replace(/(?:^|\s)kullan[ıi]c[ıi]n[ıi]n\s+iste[ğg]i\s*:.*$/i, "")
      .trim();
    // Model saçmalarsa (boş, aşırı uzun, JSON/kod döndürmüş) ya da temizleme
    // sonrası hâlâ iskele sızıntısı varsa ham metin kalır — ham içerik zaten
    // masaüstünün ürettiği doğal cümledir ("Merhaba ..., buradayım.").
    if (
      !rewritten ||
      rewritten.length > 400 ||
      rewritten.startsWith("{") ||
      rewritten.includes("```") ||
      /ham\s+sonu[çc]\s*:|g[öo]rev\s+durumu\s*:/i.test(rewritten) ||
      // Kaynağa dayanmayan çıktı = uydurma. Ham içerik her zaman daha dürüst.
      !isGroundedRewrite(content, rewritten)
    ) {
      return safeInputContent;
    }
    return sanitizeHumanizedTerminalTaskContent(rewritten, safeInputContent);
  } catch {
    return safeInputContent;
  }
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
  let assistantContent = deriveAssistantContent({
    updatedTask: input.updatedTask,
    fallbackMessage: input.message,
  });
  // Doğal dil sonuç katmanı: terminal görevlerin kısa/mekanik sonuç metinleri
  // ("Klasör hazır: /Users/…", "Operator doğrulaması başarısız oldu.") beyinden
  // hafif bir insanileştirme geçişiyle 1-2 cümle doğal Türkçeye çevrilir.
  // Herhangi bir hata/gecikmede ham metin aynen kalır (asla bloklamaz).
  assistantContent = await humanizeTerminalTaskContent(app, {
    task: input.updatedTask,
    content: assistantContent,
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
        eq(chatMessages.id, assistantMessageId),
        eq(chatMessages.sessionId, sessionId),
        eq(chatMessages.userId, input.updatedTask.userId),
        sql`${chatMessages.status} <> 'completed'`,
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
