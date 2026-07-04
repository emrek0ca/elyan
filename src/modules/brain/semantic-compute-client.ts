import type { FastifyBaseLogger } from "fastify";
import { Worker } from "node:worker_threads";

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

const DEFAULT_TIMEOUT_MS = 8_000;
const FAILURE_THRESHOLD = 5;
const COOLDOWN_MS = 60_000;

let worker: Worker | null = null;
let nextRequestId = 1;
let consecutiveFailures = 0;
let cooldownUntil = 0;
const pending = new Map<number, PendingRequest>();

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

export async function embedTextsWithSemanticWorker(input: {
  modelName: string;
  texts: string[];
  timeoutMs?: number;
  logger?: SemanticComputeLogger;
}): Promise<number[][] | null> {
  if (input.texts.length === 0) return [];
  const activeWorker = getWorker(input.logger);
  if (!activeWorker) return null;

  const id = nextRequestId;
  nextRequestId += 1;

  return new Promise<number[][] | null>((resolve) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      recordFailure();
      input.logger?.warn?.(
        { modelName: input.modelName },
        "semantic compute worker request timed out",
      );
      resolve(null);
    }, input.timeoutMs ?? DEFAULT_TIMEOUT_MS);
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

export function isSemanticComputeWorkerUnavailable(): boolean {
  return !workerEnabled() || inCooldown();
}

export function resetSemanticComputeWorkerForTests(): void {
  resolveAllPending(null);
  stopWorker();
  consecutiveFailures = 0;
  cooldownUntil = 0;
  nextRequestId = 1;
}
