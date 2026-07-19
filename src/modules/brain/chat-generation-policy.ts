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
