import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";

const CANONICAL_MEMORY_CACHE_TTL_MS = 20_000;
const COGNITIVE_RETRIEVAL_CACHE_TTL_MS = 20_000;

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

function normalizeRetrievalQuery(query: string): string {
  return query
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("tr-TR");
}

export function cognitiveRetrievalCacheKey(
  userId: string,
  memoryRevision: number,
  query: string,
  namespace = "memory",
): string {
  const queryHash = createHash("sha256")
    .update(normalizeRetrievalQuery(query))
    .digest("hex")
    .slice(0, 32);
  const normalizedNamespace = namespace
    .normalize("NFKC")
    .replace(/[^a-zA-Z0-9_.-]+/g, "_")
    .slice(0, 80) || "memory";
  return `understanding:cognitive-retrieval:v3:${userId}:${memoryRevision}:${normalizedNamespace}:${queryHash}`;
}

export async function readCognitiveRetrievalCache(
  app: FastifyInstance,
  userId: string,
  memoryRevision: number,
  query: string,
  namespace = "memory",
): Promise<unknown | undefined> {
  const store = cacheStore(app);
  if (!store || !normalizeRetrievalQuery(query)) return undefined;
  const raw = await store
    .get(cognitiveRetrievalCacheKey(userId, memoryRevision, query, namespace))
    .catch(() => null);
  if (!raw) return undefined;
  try {
    const parsed = JSON.parse(raw) as { version?: unknown; value?: unknown };
    return parsed.version === 2 ? parsed.value : undefined;
  } catch {
    return undefined;
  }
}

export async function writeCognitiveRetrievalCache(
  app: FastifyInstance,
  userId: string,
  memoryRevision: number,
  query: string,
  value: unknown,
  namespace = "memory",
): Promise<void> {
  const store = cacheStore(app);
  if (!store || !normalizeRetrievalQuery(query)) return;
  await store
    .set(
      cognitiveRetrievalCacheKey(userId, memoryRevision, query, namespace),
      JSON.stringify({ version: 2, value }),
      COGNITIVE_RETRIEVAL_CACHE_TTL_MS,
    )
    .catch(() => undefined);
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
