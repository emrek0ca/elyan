import type { FastifyInstance } from "fastify";
import { getSharedBrainWorkloadProfile, type SharedBrainWorkload } from "./workloads.js";

export type ChatGenerationProviderStage = "primary" | "fallback";

export type ChatGenerationQueueLimits = {
  workerConcurrency: number;
  primaryGlobalConcurrency: number;
  fallbackGlobalConcurrency: number;
  globalBacklogMax: number;
  userBacklogMax: number;
  groqRpmLimit: number;
  groqTpmLimit: number;
  geminiRpmLimit: number;
};

export type ChatGenerationTiming = {
  fallbackAfterMs: number;
  deadlineMs: number;
};

export type ChatGenerationAgePhase = "primary" | "fallback" | "deadline";

export type ChatQueueAdmissionDecision = {
  accepted: boolean;
  reason: "accepted" | "global_backpressure" | "user_backpressure";
};

function positiveInt(value: unknown, fallback: number, max: number): number {
  return Math.max(
    1,
    Math.min(
      typeof value === "number" && Number.isFinite(value)
        ? Math.floor(value)
        : fallback,
      max,
    ),
  );
}

export function getChatGenerationQueueLimits(
  app: FastifyInstance,
): ChatGenerationQueueLimits {
  return {
    workerConcurrency: positiveInt(app.config.ELYAN_CHAT_WORKER_CONCURRENCY, 4, 32),
    primaryGlobalConcurrency: positiveInt(
      app.config.ELYAN_CHAT_PRIMARY_GLOBAL_CONCURRENCY,
      6,
      64,
    ),
    fallbackGlobalConcurrency: positiveInt(
      app.config.ELYAN_CHAT_FALLBACK_GLOBAL_CONCURRENCY,
      4,
      64,
    ),
    globalBacklogMax: positiveInt(app.config.ELYAN_CHAT_GLOBAL_BACKLOG_MAX, 1_000, 200_000),
    userBacklogMax: positiveInt(app.config.ELYAN_CHAT_USER_BACKLOG_MAX, 3, 100),
    groqRpmLimit: positiveInt(app.config.ELYAN_GROQ_RPM_LIMIT, 30, 100_000),
    groqTpmLimit: positiveInt(app.config.ELYAN_GROQ_TPM_LIMIT, 8_000, 100_000_000),
    geminiRpmLimit: positiveInt(app.config.ELYAN_GEMINI_RPM_LIMIT, 10, 100_000),
  };
}

/**
 * GROQ_API_KEY accepts a comma-separated pool. Each key has its own provider
 * quota, while the single-key deployment keeps the existing limit unchanged.
 */
export function getGroqProviderKeyCount(app: FastifyInstance): number {
  const raw = String(app.config.GROQ_API_KEY ?? "");
  return countProviderKeys(raw);
}

export function getGeminiProviderKeyCount(app: FastifyInstance): number {
  return countProviderKeys(String(app.config.GEMINI_API_KEY ?? ""));
}

function countProviderKeys(raw: string): number {
  return Math.max(1, raw.split(",").map((entry) => entry.trim()).filter(Boolean).length);
}

export function getChatGenerationTiming(
  workload: SharedBrainWorkload,
): ChatGenerationTiming {
  if (workload === "mobile_chat_fast" || workload === "fast_route") {
    return { fallbackAfterMs: 20_000, deadlineMs: 60_000 };
  }
  if (
    workload === "planning" ||
    workload === "document_generate" ||
    workload === "document_analysis" ||
    workload === "table_generate" ||
    workload === "vision_reasoning" ||
    workload === "image_analyze"
  ) {
    return { fallbackAfterMs: 90_000, deadlineMs: 240_000 };
  }
  return { fallbackAfterMs: 45_000, deadlineMs: 120_000 };
}

export function chatGenerationAgePhase(
  workload: SharedBrainWorkload,
  ageMs: number,
): ChatGenerationAgePhase {
  const timing = getChatGenerationTiming(workload);
  const boundedAgeMs = Math.max(0, ageMs);
  if (boundedAgeMs >= timing.deadlineMs) return "deadline";
  if (boundedAgeMs >= timing.fallbackAfterMs) return "fallback";
  return "primary";
}

export function decideChatQueueAdmission(
  snapshot: { globalActive: number; userActive: number },
  limits: Pick<ChatGenerationQueueLimits, "globalBacklogMax" | "userBacklogMax">,
): ChatQueueAdmissionDecision {
  if (snapshot.globalActive >= limits.globalBacklogMax) {
    return { accepted: false, reason: "global_backpressure" };
  }
  // Bir kullanıcı için bir aktif üretim + belirtilen kadar bekleyen üretim.
  if (snapshot.userActive >= limits.userBacklogMax + 1) {
    return { accepted: false, reason: "user_backpressure" };
  }
  return { accepted: true, reason: "accepted" };
}

export function estimateChatGenerationReservationTokens(input: {
  prompt: string;
  workload: SharedBrainWorkload;
  limit: number;
}): number {
  const userTokens = Math.max(1, Math.ceil(Buffer.byteLength(input.prompt, "utf8") / 4));
  const responseTokens = getSharedBrainWorkloadProfile(input.workload).maxTokens;
  // System policy, kısa geçmiş ve tipli zarf için muhafazakâr sabit pay.
  const estimate = userTokens + responseTokens + 1_200;
  return Math.max(1, Math.min(input.limit, estimate));
}

export function chatGenerationProviderForStage(
  stage: ChatGenerationProviderStage,
): "groq" | "gemini" {
  return stage === "primary" ? "groq" : "gemini";
}

/**
 * BullMQ uses a lower number as a higher priority. Keep short conversational
 * turns ahead of long-running planning and artifact jobs while leaving the
 * provider rate limits and admission gates as the actual capacity boundary.
 */
export function chatGenerationQueuePriority(
  workload?: SharedBrainWorkload,
): number {
  if (workload === "mobile_chat_fast" || workload === "fast_route") return 1;
  if (
    workload === "mobile_chat_balanced" ||
    workload === "mobile_chat_deep_refine"
  ) {
    return 5;
  }
  return 10;
}

/**
 * Sade sohbet turu mu — yani dayanıklı kuyruğa hiç girmeden API sürecinde
 * üretilebilir mi?
 *
 * NEDEN: kuyruk sohbeti DURABLE yapıyor ama ücretini ilk token'dan alıyor.
 * Zincir şu: 202 → Redis publish → BullMQ → worker pickup → task lease +
 * kullanıcı kilidi → görev satırını yeniden oku → üretim. Bunların hepsi
 * gerçek işler, ama "merhaba" için hiçbiri gerekli değil: retry, failover ve
 * çok-adımlı yürütme gibi kuyruğun asıl varlık sebepleri o turda yok.
 *
 * Kapsam BİLEREK dar tutuldu. Görsel, ek dosya, açık yetenek isteği, onay
 * gerektiren ya da masaüstü çalışma zamanı isteyen hiçbir tur buraya girmez —
 * onların hepsi kuyruğun sunduğu yeniden deneme ve devretme garantilerine
 * gerçekten muhtaç.
 *
 * TAKAS (bilinçli): satır iş görürken süreç çökerse inline tur kurtarma
 * taramasına yakalanmaz (`listRecoverableSharedBrainChatTasks` yalnız
 * `chatGeneration.queued = true` satırlarını toplar). Sade bir sohbet turunda
 * doğru davranış zaten yeniden sormaktır; bunun için saniyeler ödemeye
 * değmiyor. Bayrakla kapatılabilir: ELYAN_CHAT_INLINE_FAST_PATH_ENABLED.
 */
export function isInlineChatFastPathEligible(input: {
  workload?: SharedBrainWorkload | null;
  route?: string | null;
  requestedCapabilities?: string[];
  hasEphemeralVision: boolean;
  hasAttachmentContext: boolean;
  requiresApproval?: boolean;
  requiresRuntime?: boolean;
}): boolean {
  if (input.route !== "server_brain") return false;
  if (input.hasEphemeralVision || input.hasAttachmentContext) return false;
  if (input.requiresApproval === true || input.requiresRuntime === true) {
    return false;
  }
  if ((input.requestedCapabilities?.length ?? 0) > 0) return false;
  const workload = input.workload ?? "mobile_chat_fast";
  return (
    workload === "mobile_chat_fast" ||
    workload === "mobile_chat_balanced" ||
    workload === "mobile_chat_deep_refine"
  );
}
