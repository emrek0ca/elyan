import type { FastifyBaseLogger } from "fastify";
import { createHash } from "node:crypto";
import { Worker } from "node:worker_threads";
import { LRUCache } from "lru-cache";

export type SemanticComputeLogger = Pick<FastifyBaseLogger, "warn" | "debug">;

type PendingRequest = {
  resolve: (vectors: number[][] | null) => void;
  timer: ReturnType<typeof setTimeout>;
};

type WorkerResponse = {
  id: number;
  ok: boolean;
  vectors?: number[][];
  error?: string;
};

type QueuedText = {
  cacheKey: string;
  modelName: string;
  text: string;
  timeoutMs: number;
  deadlineAt: number;
  cacheable: boolean;
  state: "queued" | "active";
  logger?: SemanticComputeLogger;
  resolve: (vector: number[] | null) => void;
  promise: Promise<number[] | null>;
};

export type SemanticComputeMetricsSnapshot = {
  requests: number;
  workerRequests: number;
  cacheHits: number;
  cacheMisses: number;
  coalescedTexts: number;
  batches: number;
  computedTexts: number;
  failedBatches: number;
  timeouts: number;
  overloadFallbacks: number;
  activeBatches: number;
  queuedTexts: number;
  inFlightTexts: number;
  cacheEntries: number;
  latencyMs: {
    p50: number;
    p95: number;
    max: number;
  };
};

type SemanticComputeDispatcher = (input: {
  modelName: string;
  texts: string[];
  timeoutMs: number;
  logger?: SemanticComputeLogger;
}) => Promise<number[][] | null>;

const DEFAULT_TIMEOUT_MS = 8_000;
const FAILURE_THRESHOLD = 5;
const COOLDOWN_MS = 60_000;
const BATCH_WAIT_MS = 2;
const MAX_BATCH_TEXTS = 32;
const MAX_ACTIVE_BATCHES = 2;
const MAX_QUEUED_TEXTS = 512;
const MAX_CACHE_ENTRIES = 1_024;
const MAX_LATENCY_SAMPLES = 512;

let worker: Worker | null = null;
let workerWarm = false;
let nextRequestId = 1;
let consecutiveFailures = 0;
let cooldownUntil = 0;
let queuedTextCount = 0;
let activeBatchCount = 0;
let nextUncachedScopeId = 1;
let testDispatcher: SemanticComputeDispatcher | null = null;
const pending = new Map<number, PendingRequest>();
const queuedByBatchKey = new Map<string, QueuedText[]>();
const computationsByCacheKey = new Map<string, Set<QueuedText>>();
let schedulerTimer: ReturnType<typeof setTimeout> | null = null;
let schedulerDueAt: number | null = null;
let schedulerGeneration = 0;
const vectorCache = new LRUCache<string, number[]>({ max: MAX_CACHE_ENTRIES });
const latencySamples: number[] = [];
const metricCounts = {
  requests: 0,
  workerRequests: 0,
  cacheHits: 0,
  cacheMisses: 0,
  coalescedTexts: 0,
  batches: 0,
  computedTexts: 0,
  failedBatches: 0,
  timeouts: 0,
  overloadFallbacks: 0,
};

function workerEnabled(): boolean {
  return process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED !== "false";
}

function inCooldown(): boolean {
  return Date.now() < cooldownUntil;
}

function recordSuccess(): void {
  consecutiveFailures = 0;
}

function recordFailure(): void {
  consecutiveFailures += 1;
  if (consecutiveFailures >= FAILURE_THRESHOLD) {
    cooldownUntil = Date.now() + COOLDOWN_MS;
    consecutiveFailures = 0;
  }
}

function recordLatency(startedAt: number): void {
  latencySamples.push(Math.max(0, performance.now() - startedAt));
  if (latencySamples.length > MAX_LATENCY_SAMPLES) {
    latencySamples.splice(0, latencySamples.length - MAX_LATENCY_SAMPLES);
  }
}

function percentile(values: number[], ratio: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * ratio) - 1));
  return Number(sorted[index].toFixed(2));
}

function buildCacheKey(cacheScope: string, modelName: string, text: string): string {
  // Raw private text is never retained as a cache key or metric label.
  return createHash("sha256")
    .update(cacheScope)
    .update("\0")
    .update(modelName)
    .update("\0")
    .update(text)
    .digest("hex");
}

function resolveAllPending(value: number[][] | null): void {
  for (const [id, entry] of pending) {
    clearTimeout(entry.timer);
    pending.delete(id);
    entry.resolve(value);
  }
}

function stopWorker(): void {
  const current = worker;
  worker = null;
  workerWarm = false;
  if (current) {
    void current.terminate().catch(() => undefined);
  }
}

function getWorker(logger?: SemanticComputeLogger): Worker | null {
  if (!workerEnabled() || inCooldown()) return null;
  if (worker) return worker;

  try {
    const created = new Worker(new URL("./semantic-compute-worker.js", import.meta.url));
    created.unref();
    created.on("message", (message: WorkerResponse) => {
      const entry = pending.get(message.id);
      if (!entry) return;
      clearTimeout(entry.timer);
      pending.delete(message.id);
      if (message.ok && Array.isArray(message.vectors)) {
        recordSuccess();
        entry.resolve(message.vectors);
      } else {
        recordFailure();
        logger?.warn?.(
          { error: message.error ?? "semantic_compute_failed" },
          "semantic compute worker request failed",
        );
        entry.resolve(null);
      }
    });
    created.on("error", (error) => {
      logger?.warn?.({ error }, "semantic compute worker crashed");
      recordFailure();
      resolveAllPending(null);
      stopWorker();
    });
    created.on("exit", (code) => {
      workerWarm = false;
      if (code !== 0) {
        logger?.warn?.({ code }, "semantic compute worker exited unexpectedly");
        recordFailure();
      }
      resolveAllPending(null);
      worker = null;
    });
    worker = created;
    return created;
  } catch (error) {
    logger?.warn?.({ error }, "semantic compute worker unavailable");
    recordFailure();
    return null;
  }
}

async function requestWorkerEmbeddings(input: {
  modelName: string;
  texts: string[];
  timeoutMs: number;
  logger?: SemanticComputeLogger;
}): Promise<number[][] | null> {
  metricCounts.workerRequests += 1;
  if (testDispatcher) {
    return testDispatcher(input);
  }

  const activeWorker = getWorker(input.logger);
  if (!activeWorker) return null;

  const id = nextRequestId;
  nextRequestId += 1;
  return new Promise<number[][] | null>((resolve) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      metricCounts.timeouts += 1;
      recordFailure();
      input.logger?.warn?.(
        { modelName: input.modelName },
        "semantic compute worker request timed out",
      );
      resolve(null);
    }, input.timeoutMs);
    timer.unref?.();
    pending.set(id, { resolve, timer });
    activeWorker.postMessage({
      id,
      task: "embed",
      modelName: input.modelName,
      texts: input.texts,
    });
  });
}

function scheduleScheduler(delayMs = BATCH_WAIT_MS): void {
  const dueAt = Date.now() + Math.max(0, delayMs);
  if (schedulerTimer) {
    if (schedulerDueAt !== null && schedulerDueAt <= dueAt) return;
    clearTimeout(schedulerTimer);
  }
  schedulerDueAt = dueAt;
  schedulerTimer = setTimeout(() => {
    schedulerTimer = null;
    schedulerDueAt = null;
    runScheduler();
  }, Math.max(0, delayMs));
}

function addComputation(entry: QueuedText): void {
  const entries = computationsByCacheKey.get(entry.cacheKey) ?? new Set<QueuedText>();
  entries.add(entry);
  computationsByCacheKey.set(entry.cacheKey, entries);
}

function removeComputation(entry: QueuedText): void {
  const entries = computationsByCacheKey.get(entry.cacheKey);
  if (!entries) return;
  entries.delete(entry);
  if (entries.size === 0) computationsByCacheKey.delete(entry.cacheKey);
}

function expireQueuedTexts(now: number): void {
  for (const [batchKey, queue] of queuedByBatchKey) {
    for (let index = queue.length - 1; index >= 0; index -= 1) {
      const entry = queue[index];
      if (entry.deadlineAt > now) continue;
      queue.splice(index, 1);
      queuedTextCount -= 1;
      metricCounts.timeouts += 1;
      removeComputation(entry);
      entry.resolve(null);
    }
    if (queue.length === 0) queuedByBatchKey.delete(batchKey);
  }
}

function takeNextBatch(): QueuedText[] | null {
  const next = queuedByBatchKey.entries().next();
  if (next.done) return null;
  const [batchKey, queue] = next.value;
  const entries = queue.splice(0, MAX_BATCH_TEXTS);
  queuedTextCount -= entries.length;
  queuedByBatchKey.delete(batchKey);
  if (queue.length > 0) queuedByBatchKey.set(batchKey, queue);
  for (const entry of entries) entry.state = "active";
  return entries;
}

function earliestQueuedDeadline(): number | null {
  let earliest: number | null = null;
  for (const queue of queuedByBatchKey.values()) {
    for (const entry of queue) {
      earliest = earliest === null ? entry.deadlineAt : Math.min(earliest, entry.deadlineAt);
    }
  }
  return earliest;
}

function runScheduler(): void {
  expireQueuedTexts(Date.now());
  while (activeBatchCount < MAX_ACTIVE_BATCHES) {
    const entries = takeNextBatch();
    if (!entries) break;
    activeBatchCount += 1;
    void dispatchBatch(entries, schedulerGeneration);
  }
  if (queuedTextCount > 0) {
    const earliest = earliestQueuedDeadline();
    if (earliest !== null) scheduleScheduler(earliest - Date.now());
  }
}

async function dispatchBatch(entries: QueuedText[], generation: number): Promise<void> {
  metricCounts.batches += 1;
  const first = entries[0];
  const vectors = await requestWorkerEmbeddings({
    modelName: first.modelName,
    texts: entries.map((entry) => entry.text),
    timeoutMs: Math.max(1, Math.min(...entries.map((entry) => entry.deadlineAt - Date.now()))),
    logger: first.logger,
  }).catch(() => null);
  if (generation !== schedulerGeneration) return;
  const valid = Array.isArray(vectors) && vectors.length === entries.length;
  if (!valid) metricCounts.failedBatches += 1;

  entries.forEach((entry, index) => {
    const vector = valid && Array.isArray(vectors[index]) && vectors[index].length > 0
      ? vectors[index]
      : null;
    if (vector) {
      const stableVector = [...vector];
      if (entry.cacheable) vectorCache.set(entry.cacheKey, stableVector);
      metricCounts.computedTexts += 1;
      entry.resolve([...stableVector]);
    } else {
      entry.resolve(null);
    }
    removeComputation(entry);
  });
  activeBatchCount -= 1;
  scheduleScheduler(0);
}

function waitForCallerDeadline(
  promise: Promise<number[] | null>,
  timeoutMs: number,
): Promise<number[] | null> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (vector: number[] | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(vector ? [...vector] : null);
    };
    const timer = setTimeout(() => {
      metricCounts.timeouts += 1;
      finish(null);
    }, timeoutMs);
    void promise.then(finish, () => finish(null));
  });
}

function queueText(input: {
  modelName: string;
  text: string;
  timeoutMs: number;
  cacheScope: string;
  cacheable: boolean;
  logger?: SemanticComputeLogger;
}): Promise<number[] | null> {
  const cacheKey = buildCacheKey(input.cacheScope, input.modelName, input.text);
  if (input.cacheable) {
    const cached = vectorCache.get(cacheKey);
    if (cached) {
      metricCounts.cacheHits += 1;
      return Promise.resolve([...cached]);
    }
    metricCounts.cacheMisses += 1;
  }

  const callerDeadline = Date.now() + input.timeoutMs;
  const existingComputations = computationsByCacheKey.get(cacheKey);
  const queuedEntry = existingComputations
    ? [...existingComputations].find((entry) =>
        entry.state === "queued" || entry.deadlineAt >= callerDeadline)
    : undefined;
  if (queuedEntry) {
    metricCounts.coalescedTexts += 1;
    if (queuedEntry.state === "queued") {
      queuedEntry.deadlineAt = Math.max(queuedEntry.deadlineAt, callerDeadline);
    }
    return waitForCallerDeadline(queuedEntry.promise, input.timeoutMs);
  }
  if (queuedTextCount >= MAX_QUEUED_TEXTS) {
    metricCounts.overloadFallbacks += 1;
    return Promise.resolve(null);
  }

  let resolveVector: (vector: number[] | null) => void = () => undefined;
  const result = new Promise<number[] | null>((resolve) => {
    resolveVector = resolve;
  });

  const batchKey = `${input.modelName}\0${input.timeoutMs}`;
  const queue = queuedByBatchKey.get(batchKey) ?? [];
  const entry: QueuedText = {
    ...input,
    cacheKey,
    deadlineAt: callerDeadline,
    state: "queued",
    resolve: resolveVector,
    promise: result,
  };
  queue.push(entry);
  addComputation(entry);
  queuedByBatchKey.set(batchKey, queue);
  queuedTextCount += 1;
  if (queue.length >= MAX_BATCH_TEXTS) {
    scheduleScheduler(0);
  } else {
    scheduleScheduler();
  }
  return waitForCallerDeadline(result, input.timeoutMs);
}

export async function embedTextsWithSemanticWorker(input: {
  modelName: string;
  texts: string[];
  cacheScope?: string;
  timeoutMs?: number;
  logger?: SemanticComputeLogger;
}): Promise<number[][] | null> {
  if (input.texts.length === 0) return [];
  if (!testDispatcher && (!workerEnabled() || inCooldown())) return null;

  metricCounts.requests += 1;
  const startedAt = performance.now();
  const requestedCacheScope = input.cacheScope?.trim() ?? "";
  const cacheable = requestedCacheScope.length > 0;
  const cacheScope = cacheable
    ? requestedCacheScope
    : `uncached:${nextUncachedScopeId++}`;
  const vectors = await Promise.all(
    input.texts.map((text) => queueText({
      modelName: input.modelName,
      text,
      cacheScope,
      cacheable,
      timeoutMs: input.timeoutMs ?? DEFAULT_TIMEOUT_MS,
      logger: input.logger,
    })),
  );
  recordLatency(startedAt);
  return vectors.every((vector): vector is number[] => Array.isArray(vector)) ? vectors : null;
}

let warmupPromise: Promise<boolean> | null = null;

/**
 * Modeli AÇILIŞTA belleğe yükler.
 *
 * NEDEN
 * -----
 * Model imaja gömülü (Dockerfile `local_files_only=true` ile doğruluyor), yani
 * indirme yok. Ama ONNX oturumu ilk `embed` isteğinde kuruluyordu ve o maliyeti
 * ilk KULLANICI turu ödüyordu. Canlıda ölçüldü: yükleme çağıranın 8 sn'lik
 * bütçesini aşıyor, arka arkaya 5 timeout `FAILURE_THRESHOLD`'u tetikliyor,
 * 60 sn `COOLDOWN_MS` boyunca `isSemanticComputeWorkerUnavailable()` true
 * kalıyor ve TÜM semantik kararlar hash yedeğine düşüyordu. Saatte 15 timeout
 * ölçüldü — yani semantik katman prodüksiyonda çoğunlukla hiç çalışmıyordu.
 *
 * Isıtmanın çağıran zaman aşımı YOK ve başarısızlığı cooldown sayacına
 * İŞLENMEZ: açılışta bir kez denenir, tutmazsa sistem eskisi gibi hash'e
 * düşer — yani bu ekleme hiçbir yolu kötüleştiremez.
 */
export function primeSemanticComputeWorker(input: {
  modelName: string;
  logger?: SemanticComputeLogger;
}): Promise<boolean> {
  if (warmupPromise) return warmupPromise;
  if (testDispatcher || !workerEnabled()) return Promise.resolve(false);

  workerWarm = false;
  warmupPromise = new Promise<boolean>((resolve) => {
    const activeWorker = getWorker(input.logger);
    if (!activeWorker) {
      resolve(false);
      return;
    }
    const id = nextRequestId;
    nextRequestId += 1;
    // Isıtma için zamanlayıcı kurulmuyor; `pending` girdisi yanıt gelince
    // temizleniyor. Yanıt hiç gelmezse süreç zaten hash yolunda çalışır.
    pending.set(id, {
      resolve: (vectors) => {
        // Isıtma başarısı cooldown'u SIFIRLAR: soğuk başlangıçta birikmiş
        // sahte başarısızlıklar gerçek trafiği cezalandırmasın.
        const warmed = Array.isArray(vectors);
        if (warmed) {
          recordSuccess();
          workerWarm = true;
        }
        resolve(warmed);
      },
      timer: setTimeout(() => undefined, 0),
    });
    activeWorker.postMessage({
      id,
      task: "warmup",
      modelName: input.modelName,
      texts: [],
    });
  });
  return warmupPromise;
}

export function resetSemanticComputeWarmupForTests(): void {
  warmupPromise = null;
  workerWarm = false;
}

export function getSemanticComputeMetrics(): SemanticComputeMetricsSnapshot {
  return {
    ...metricCounts,
    activeBatches: activeBatchCount,
    queuedTexts: queuedTextCount,
    inFlightTexts: [...computationsByCacheKey.values()].reduce((sum, entries) => sum + entries.size, 0),
    cacheEntries: vectorCache.size,
    latencyMs: {
      p50: percentile(latencySamples, 0.5),
      p95: percentile(latencySamples, 0.95),
      max: percentile(latencySamples, 1),
    },
  };
}

export function isSemanticComputeWorkerUnavailable(): boolean {
  return !workerEnabled() || inCooldown();
}

/**
 * Request paths that cannot pay the cold-start cost use this readiness gate.
 * App startup owns the asynchronous warmup; callers fall back until it is
 * complete instead of waiting for the worker's first model load.
 */
export function isSemanticComputeWorkerWarm(): boolean {
  return testDispatcher !== null || workerWarm;
}

export function setSemanticComputeDispatcherForTests(dispatcher: SemanticComputeDispatcher | null): void {
  testDispatcher = dispatcher;
}

export function resetSemanticComputeWorkerForTests(): void {
  warmupPromise = null;
  workerWarm = false;
  resolveAllPending(null);
  stopWorker();
  schedulerGeneration += 1;
  if (schedulerTimer) clearTimeout(schedulerTimer);
  schedulerTimer = null;
  schedulerDueAt = null;
  for (const entries of computationsByCacheKey.values()) {
    for (const entry of entries) entry.resolve(null);
  }
  queuedByBatchKey.clear();
  queuedTextCount = 0;
  activeBatchCount = 0;
  computationsByCacheKey.clear();
  vectorCache.clear();
  latencySamples.length = 0;
  Object.keys(metricCounts).forEach((key) => {
    metricCounts[key as keyof typeof metricCounts] = 0;
  });
  testDispatcher = null;
  consecutiveFailures = 0;
  cooldownUntil = 0;
  nextRequestId = 1;
  nextUncachedScopeId = 1;
}
