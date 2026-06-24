import type { FastifyInstance } from "fastify";

type BrainProfileCacheEntry = {
  value: unknown;
  expiresAt: number;
};

const BRAIN_PROFILE_CACHE_TTL_MS = 30_000;
const brainProfileCache = new WeakMap<FastifyInstance, Map<string, BrainProfileCacheEntry>>();

function getBrainProfileCache(app: FastifyInstance) {
  const cache = brainProfileCache.get(app);
  if (cache) {
    return cache;
  }

  const created = new Map<string, BrainProfileCacheEntry>();
  brainProfileCache.set(app, created);
  return created;
}

export function getBrainProfileCacheKey(userId?: string | null): string {
  return String(userId ?? "").trim() || "anonymous";
}

export function readBrainProfileCache(app: FastifyInstance, userId?: string | null): unknown | null {
  const cache = getBrainProfileCache(app);
  const cacheKey = getBrainProfileCacheKey(userId);
  const cached = cache.get(cacheKey);

  if (!cached) {
    return null;
  }

  if (cached.expiresAt <= Date.now()) {
    cache.delete(cacheKey);
    return null;
  }

  return cached.value;
}

export function writeBrainProfileCache(app: FastifyInstance, userId: string, value: unknown): void {
  const cache = getBrainProfileCache(app);
  cache.set(getBrainProfileCacheKey(userId), {
    value,
    expiresAt: Date.now() + BRAIN_PROFILE_CACHE_TTL_MS,
  });
}

export function invalidateBrainProfileCache(app: FastifyInstance, userId?: string | null): void {
  const cache = brainProfileCache.get(app);
  if (!cache) {
    return;
  }

  if (!userId || !String(userId).trim()) {
    cache.clear();
    return;
  }

  cache.delete(getBrainProfileCacheKey(userId));
}
