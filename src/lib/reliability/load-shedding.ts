import { createHash, randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { AppError } from "../errors.js";

export type LoadSheddingPermit = {
  key: string;
  owner: string;
  slot: number;
  release: () => Promise<void>;
};

export type LoadSheddingOptions = {
  namespace: string;
  maxConcurrent: number;
  ttlMs: number;
  salt?: string;
  retryAfterSeconds?: number;
};

function normalizeNamespace(namespace: string): string {
  const compact = namespace.trim().toLowerCase().replace(/[^a-z0-9:_-]+/g, "-");
  return compact || "shared";
}

function hashToSlotIndex(input: string, maxConcurrent: number): number {
  const normalizedMaxConcurrent = Math.max(1, Math.floor(maxConcurrent));
  const digest = createHash("sha256").update(input).digest();
  return digest.readUInt32BE(0) % normalizedMaxConcurrent;
}

function resolveReliabilityStore(app: FastifyInstance) {
  return app.services?.reliability?.store ?? null;
}

function createBypassPermit(namespace: string): LoadSheddingPermit {
  return {
    key: `bypass:${namespace}`,
    owner: "bypass",
    slot: -1,
    release: async () => undefined,
  };
}

function createLoadSheddingError(namespace: string, retryAfterSeconds: number): AppError {
  return new AppError(503, "server_brain_unavailable", "Elyan beyni şu anda yoğun. Lütfen birkaç saniye sonra tekrar dene.", {
    loadShedding: true,
    namespace,
    retryAfterSeconds,
    retrySuggested: true,
    transient: true,
  });
}

async function tryAcquireSlot(
  app: FastifyInstance,
  options: LoadSheddingOptions,
): Promise<LoadSheddingPermit | null> {
  const store = resolveReliabilityStore(app);
  if (!store) {
    return null;
  }

  const namespace = normalizeNamespace(options.namespace);
  const maxConcurrent = Math.max(1, Math.floor(options.maxConcurrent));
  const ttlMs = Math.max(1000, Math.floor(options.ttlMs));
  const slotSeed = hashToSlotIndex(`${namespace}:${options.salt ?? ""}`, maxConcurrent);

  for (let offset = 0; offset < maxConcurrent; offset += 1) {
    const slot = (slotSeed + offset) % maxConcurrent;
    const owner = randomUUID();
    const key = `lock:load:${namespace}:${slot}`;
    const acquired = await store.acquireLock(key, owner, ttlMs);
    if (!acquired) {
      continue;
    }

    return {
      key,
      owner,
      slot,
      release: async () => {
        await store.releaseLock(key, owner);
      },
    };
  }

  return null;
}

export async function acquireLoadSheddingPermit(
  app: FastifyInstance,
  options: LoadSheddingOptions,
): Promise<LoadSheddingPermit> {
  const namespace = normalizeNamespace(options.namespace);
  const store = resolveReliabilityStore(app);
  if (!store) {
    return createBypassPermit(namespace);
  }

  const permit = await tryAcquireLoadSheddingPermit(app, options);
  if (permit) {
    return permit;
  }

  throw createLoadSheddingError(
    namespace,
    options.retryAfterSeconds ?? Math.max(2, Math.ceil(options.ttlMs / 2000)),
  );
}

export async function tryAcquireLoadSheddingPermit(
  app: FastifyInstance,
  options: LoadSheddingOptions,
): Promise<LoadSheddingPermit | null> {
  const namespace = normalizeNamespace(options.namespace);
  const store = resolveReliabilityStore(app);
  if (!store) {
    return createBypassPermit(namespace);
  }

  return tryAcquireSlot(app, options);
}

export async function withLoadSheddingPermit<T>(
  app: FastifyInstance,
  options: LoadSheddingOptions,
  fn: () => Promise<T>,
): Promise<T> {
  const permit = await acquireLoadSheddingPermit(app, options);
  try {
    return await fn();
  } finally {
    await permit.release().catch(() => undefined);
  }
}
