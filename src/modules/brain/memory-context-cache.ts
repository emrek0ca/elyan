import type { FastifyInstance } from "fastify";

const CANONICAL_MEMORY_CACHE_TTL_MS = 20_000;

type MemoryContextCacheStore = {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlMs?: number): Promise<void>;
  del(key: string): Promise<unknown>;
};

function cacheStore(app: FastifyInstance): MemoryContextCacheStore | null {
  const store = app.services?.reliability?.store as
    | Partial<MemoryContextCacheStore>
    | undefined;
  return store &&
    typeof store.get === "function" &&
    typeof store.set === "function" &&
    typeof store.del === "function"
    ? (store as MemoryContextCacheStore)
    : null;
}

export function canonicalMemoryCacheKey(userId: string): string {
  return `understanding:canonical-memory:v2:${userId}`;
}

export async function readCanonicalMemoryCache(
  app: FastifyInstance,
  userId: string,
): Promise<unknown | undefined> {
  const store = cacheStore(app);
  if (!store) return undefined;
  const raw = await store
    .get(canonicalMemoryCacheKey(userId))
    .catch(() => null);
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw) as { version?: unknown; value?: unknown };
    return parsed.version === 2 ? parsed.value : undefined;
  } catch {
    return undefined;
  }
}

export async function writeCanonicalMemoryCache(
  app: FastifyInstance,
  userId: string,
  value: unknown,
): Promise<void> {
  const store = cacheStore(app);
  if (!store) return;
  await store
    .set(
      canonicalMemoryCacheKey(userId),
      JSON.stringify({ version: 2, value }),
      CANONICAL_MEMORY_CACHE_TTL_MS,
    )
    .catch(() => undefined);
}

export async function invalidateCanonicalMemoryCache(
  app: FastifyInstance,
  userId: string,
): Promise<void> {
  const store = cacheStore(app);
  if (!store) return;
  await store.del(canonicalMemoryCacheKey(userId)).catch(() => undefined);
}
