import { createHash, randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { AppError } from "../../lib/errors.js";

const MEDIA_NORMALIZE_GLOBAL_SLOT_KEY = "media-input:normalize:active:v1";
const MEDIA_NORMALIZE_SLOT_TTL_MS = 60_000;

export type MediaNormalizationAdmission = {
  release: () => Promise<void>;
};

export async function reserveMediaNormalizationAdmission(
  app: FastifyInstance,
  userId: string,
): Promise<MediaNormalizationAdmission> {
  const store = app.services?.reliability?.store;
  if (!store) throw mediaBusyError();

  const member = randomUUID();
  const userKey = `media-input:normalize:user:${stableUserHash(userId)}:active:v1`;
  const requireRedis = app.config.RELIABILITY_REDIS_REQUIRED === true;
  let globalAcquired = false;

  try {
    const global = await store.tryAcquireExpiringSlot(
      MEDIA_NORMALIZE_GLOBAL_SLOT_KEY,
      member,
      app.config.ELYAN_MEDIA_NORMALIZE_GLOBAL_CONCURRENCY,
      MEDIA_NORMALIZE_SLOT_TTL_MS,
      requireRedis,
    );
    if (!global?.allowed) throw mediaBusyError();
    globalAcquired = true;

    const user = await store.tryAcquireExpiringSlot(
      userKey,
      member,
      app.config.ELYAN_MEDIA_NORMALIZE_USER_CONCURRENCY,
      MEDIA_NORMALIZE_SLOT_TTL_MS,
      requireRedis,
    );
    if (!user?.allowed) {
      await store
        .releaseExpiringSlot(MEDIA_NORMALIZE_GLOBAL_SLOT_KEY, member)
        .catch(() => false);
      globalAcquired = false;
      throw mediaBusyError();
    }
  } catch (error) {
    if (globalAcquired) {
      await store
        .releaseExpiringSlot(MEDIA_NORMALIZE_GLOBAL_SLOT_KEY, member)
        .catch(() => false);
    }
    if (error instanceof AppError) throw error;
    throw mediaBusyError();
  }

  let released = false;
  return {
    release: async () => {
      if (released) return;
      released = true;
      await Promise.all([
        store.releaseExpiringSlot(MEDIA_NORMALIZE_GLOBAL_SLOT_KEY, member),
        store.releaseExpiringSlot(userKey, member),
      ]).catch(() => undefined);
    },
  };
}

function stableUserHash(userId: string): string {
  return createHash("sha256").update(userId).digest("hex").slice(0, 24);
}

function mediaBusyError(): AppError {
  return new AppError(
    503,
    "media_input_busy",
    "Görsel işleme şu anda yoğun. Lütfen kısa süre sonra tekrar dene.",
    { retryAfterMs: 1_500 },
  );
}
