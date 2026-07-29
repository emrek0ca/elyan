import { createHash, randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { AppError } from "../../lib/errors.js";

const SPEECH_GLOBAL_SLOT_KEY = "speech:transcription:active:v1";
const SPEECH_SLOT_TTL_MS = 40_000;

export type SpeechAdmission = {
  release: () => Promise<void>;
};

export async function reserveSpeechAdmission(
  app: FastifyInstance,
  userId: string,
): Promise<SpeechAdmission> {
  const store = app.services?.reliability?.store;
  if (!store) {
    throw speechUnavailableError();
  }
  const member = randomUUID();
  const requireRedis = app.config.RELIABILITY_REDIS_REQUIRED === true;
  const userKey = `speech:transcription:user:${stableUserHash(userId)}:v1`;
  let globalAcquired = false;

  try {
    const global = await store.tryAcquireExpiringSlot(
      SPEECH_GLOBAL_SLOT_KEY,
      member,
      app.config.ELYAN_SPEECH_GLOBAL_CONCURRENCY,
      SPEECH_SLOT_TTL_MS,
      requireRedis,
    );
    if (!global?.allowed) {
      throw speechUnavailableError();
    }
    globalAcquired = true;

    const user = await store.tryAcquireExpiringSlot(
      userKey,
      member,
      app.config.ELYAN_SPEECH_USER_CONCURRENCY,
      SPEECH_SLOT_TTL_MS,
      requireRedis,
    );
    if (!user?.allowed) {
      await store
        .releaseExpiringSlot(SPEECH_GLOBAL_SLOT_KEY, member)
        .catch(() => false);
      globalAcquired = false;
      throw speechUnavailableError();
    }
  } catch (error) {
    if (globalAcquired) {
      await store
        .releaseExpiringSlot(SPEECH_GLOBAL_SLOT_KEY, member)
        .catch(() => false);
    }
    if (error instanceof AppError) throw error;
    throw speechUnavailableError();
  }

  let released = false;
  return {
    release: async () => {
      if (released) return;
      released = true;
      await Promise.all([
        store.releaseExpiringSlot(SPEECH_GLOBAL_SLOT_KEY, member),
        store.releaseExpiringSlot(userKey, member),
      ]).catch(() => undefined);
    },
  };
}

const STREAMING_GLOBAL_SLOT_KEY = "speech:streaming:active:v1";
/**
 * A live socket outlives any single request, so its slot TTL is refreshed by
 * the session heartbeat instead of covering the whole call up front.
 */
const STREAMING_SLOT_TTL_MS = 60_000;
const STREAMING_BUDGET_WINDOW_MS = 60 * 60 * 1000;

export type StreamingSpeechAdmission = {
  /**
   * Charge audio seconds as they are consumed. Returns false once the user is
   * out of budget — the caller must stop transcribing and close the socket.
   */
  consumeSeconds: (seconds: number) => Promise<boolean>;
  /** Keep the concurrency slot alive while the mic is open. */
  touch: () => Promise<void>;
  release: () => Promise<void>;
};

/**
 * Admission for a live speech socket.
 *
 * The turn-based route meters a finished upload by its byte length. Streaming
 * has no file to measure and no natural end, so the meter here is audio
 * seconds, charged incrementally while the session runs. Concurrency is still
 * slot-based — that gate limits how much provider work can be in flight at
 * once, which is a different failure than a user talking too long.
 */
export async function reserveStreamingSpeechAdmission(
  app: FastifyInstance,
  userId: string,
): Promise<StreamingSpeechAdmission> {
  const store = app.services?.reliability?.store;
  if (!store) {
    throw speechUnavailableError();
  }
  const member = randomUUID();
  const requireRedis = app.config.RELIABILITY_REDIS_REQUIRED === true;
  const userHash = stableUserHash(userId);
  const userSlotKey = `speech:streaming:user:${userHash}:v1`;
  const budgetKey = `speech:streaming:seconds:${userHash}:v1`;
  let globalAcquired = false;

  try {
    const global = await store.tryAcquireExpiringSlot(
      STREAMING_GLOBAL_SLOT_KEY,
      member,
      app.config.ELYAN_VOICE_STREAMING_GLOBAL_CONCURRENCY,
      STREAMING_SLOT_TTL_MS,
      requireRedis,
    );
    if (!global?.allowed) {
      throw speechUnavailableError();
    }
    globalAcquired = true;

    const user = await store.tryAcquireExpiringSlot(
      userSlotKey,
      member,
      app.config.ELYAN_VOICE_STREAMING_USER_CONCURRENCY,
      STREAMING_SLOT_TTL_MS,
      requireRedis,
    );
    if (!user?.allowed) {
      throw speechUnavailableError();
    }
  } catch (error) {
    if (globalAcquired) {
      await store
        .releaseExpiringSlot(STREAMING_GLOBAL_SLOT_KEY, member)
        .catch(() => false);
    }
    if (error instanceof AppError) throw error;
    throw speechUnavailableError();
  }

  // Opening the mic with nothing left in the budget should fail here, not
  // after the first window has already been billed.
  const opening = await store
    .tryConsumeBudget(
      budgetKey,
      1,
      app.config.ELYAN_VOICE_STREAMING_USER_SECONDS_PER_HOUR,
      STREAMING_BUDGET_WINDOW_MS,
      requireRedis,
    )
    .catch(() => ({ allowed: false, used: 0 }));
  if (!opening.allowed) {
    await Promise.all([
      store.releaseExpiringSlot(STREAMING_GLOBAL_SLOT_KEY, member),
      store.releaseExpiringSlot(userSlotKey, member),
    ]).catch(() => undefined);
    throw speechQuotaExhaustedError();
  }

  let released = false;
  return {
    consumeSeconds: async (seconds) => {
      const amount = Math.max(1, Math.round(seconds));
      const result = await store
        .tryConsumeBudget(
          budgetKey,
          amount,
          app.config.ELYAN_VOICE_STREAMING_USER_SECONDS_PER_HOUR,
          STREAMING_BUDGET_WINDOW_MS,
          requireRedis,
        )
        .catch(() => ({ allowed: false, used: 0 }));
      return result.allowed;
    },
    touch: async () => {
      if (released) return;
      await Promise.all([
        store.tryAcquireExpiringSlot(
          STREAMING_GLOBAL_SLOT_KEY,
          member,
          app.config.ELYAN_VOICE_STREAMING_GLOBAL_CONCURRENCY,
          STREAMING_SLOT_TTL_MS,
          requireRedis,
        ),
        store.tryAcquireExpiringSlot(
          userSlotKey,
          member,
          app.config.ELYAN_VOICE_STREAMING_USER_CONCURRENCY,
          STREAMING_SLOT_TTL_MS,
          requireRedis,
        ),
      ]).catch(() => undefined);
    },
    release: async () => {
      if (released) return;
      released = true;
      await Promise.all([
        store.releaseExpiringSlot(STREAMING_GLOBAL_SLOT_KEY, member),
        store.releaseExpiringSlot(userSlotKey, member),
      ]).catch(() => undefined);
    },
  };
}

function stableUserHash(userId: string): string {
  return createHash("sha256").update(userId).digest("hex").slice(0, 24);
}

function speechQuotaExhaustedError(): AppError {
  return new AppError(
    429,
    "speech_quota_exhausted",
    "Sesli mod için saatlik konuşma süreniz doldu.",
    { retryAfterMs: 60_000 },
  );
}

function speechUnavailableError(): AppError {
  return new AppError(
    503,
    "speech_provider_unavailable",
    "Sesli giriş şu anda yoğun. Lütfen kısa süre sonra tekrar deneyin.",
    { retryAfterMs: 2_000 },
  );
}
