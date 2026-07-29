import { createHash, randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { AppError } from "../../lib/errors.js";

const PLAN_REVISION_GLOBAL_SLOT_KEY = "task-control:plan-revision:active:v1";
const PLAN_REVISION_SLOT_TTL_MS = 60_000;

export type PlanRevisionAdmission = {
  release: () => Promise<void>;
};

export async function reservePlanRevisionAdmission(
  app: FastifyInstance,
  userId: string,
): Promise<PlanRevisionAdmission> {
  const store = app.services?.reliability?.store;
  if (!store) throw planRevisionBusyError();

  const member = randomUUID();
  const userHash = createHash("sha256")
    .update(userId)
    .digest("hex")
    .slice(0, 24);
  const userKey = `task-control:plan-revision:user:${userHash}:active:v1`;
  const requireRedis = app.config.RELIABILITY_REDIS_REQUIRED === true;
  let globalAcquired = false;
  try {
    const global = await store.tryAcquireExpiringSlot(
      PLAN_REVISION_GLOBAL_SLOT_KEY,
      member,
      app.config.ELYAN_PLAN_REVISION_GLOBAL_CONCURRENCY,
      PLAN_REVISION_SLOT_TTL_MS,
      requireRedis,
    );
    if (!global?.allowed) throw planRevisionBusyError();
    globalAcquired = true;

    const user = await store.tryAcquireExpiringSlot(
      userKey,
      member,
      app.config.ELYAN_PLAN_REVISION_USER_CONCURRENCY,
      PLAN_REVISION_SLOT_TTL_MS,
      requireRedis,
    );
    if (!user?.allowed) {
      await store
        .releaseExpiringSlot(PLAN_REVISION_GLOBAL_SLOT_KEY, member)
        .catch(() => false);
      globalAcquired = false;
      throw planRevisionBusyError();
    }
  } catch (error) {
    if (globalAcquired) {
      await store
        .releaseExpiringSlot(PLAN_REVISION_GLOBAL_SLOT_KEY, member)
        .catch(() => false);
    }
    if (error instanceof AppError) throw error;
    throw planRevisionBusyError();
  }

  let released = false;
  return {
    release: async () => {
      if (released) return;
      released = true;
      await Promise.all([
        store.releaseExpiringSlot(PLAN_REVISION_GLOBAL_SLOT_KEY, member),
        store.releaseExpiringSlot(userKey, member),
      ]).catch(() => undefined);
    },
  };
}

function planRevisionBusyError(): AppError {
  return new AppError(
    503,
    "task_control_busy",
    "Canlı planlama şu anda yoğun. Talimat taslakta korunuyor.",
    { retryAfterMs: 1_500, transient: true },
  );
}
