import { randomUUID } from "node:crypto";
import type { AppEnv } from "../../config/env.js";
import { ReliabilityStore } from "./redis.js";

export type ReliabilityServices = {
  store: ReliabilityStore;
  requestBudgetReady: () => boolean;
  acquireTaskDispatchLock: (taskId: string, owner: string, ttlMs?: number) => Promise<boolean>;
  releaseTaskDispatchLock: (taskId: string, owner: string) => Promise<boolean>;
  clearTaskDispatchLock: (taskId: string) => Promise<void>;
  withLock: <T>(key: string, ttlMs: number, fn: () => Promise<T>, owner?: string) => Promise<T | null>;
};

export function createReliabilityServices(env: AppEnv): ReliabilityServices {
  const store = new ReliabilityStore(env);

  return {
    store,
    requestBudgetReady: () => {
      const summary = store.summary();
      return summary.ready || !summary.required;
    },
    acquireTaskDispatchLock: (taskId, owner, ttlMs = env.TASK_DISPATCH_LOCK_TTL_MS) =>
      store.acquireLock(`lock:task-dispatch:${taskId}`, owner, ttlMs),
    releaseTaskDispatchLock: (taskId, owner) => store.releaseLock(`lock:task-dispatch:${taskId}`, owner),
    clearTaskDispatchLock: (taskId) => store.del(`lock:task-dispatch:${taskId}`),
    withLock: async (key, ttlMs, fn, owner = randomUUID()) => {
      const acquired = await store.acquireLock(`lock:${key}`, owner, ttlMs);
      if (!acquired) {
        return null;
      }

      try {
        return await fn();
      } finally {
        await store.releaseLock(`lock:${key}`, owner);
      }
    },
  };
}
