import { createHash, randomUUID } from "node:crypto";
import {
  DelayedError,
  Queue,
  Worker,
  type Job,
} from "bullmq";
import type { FastifyInstance } from "fastify";
import { AppError } from "../../lib/errors.js";
import {
  chatGenerationAgePhase,
  estimateChatGenerationReservationTokens,
  getChatGenerationQueueLimits,
  getChatGenerationTiming,
  type ChatGenerationProviderStage,
} from "./chat-generation-policy.js";

export type ChatGenerationJobData = {
  taskId: string;
  userId: string;
};

export type ChatGenerationQueueFailure = {
  retryable: boolean;
  rateLimited: boolean;
  retryAfterMs: number | null;
  failureClass: string;
};

const PRIMARY_QUEUE_NAME = "elyan-chat-primary-v1";
const FALLBACK_QUEUE_NAME = "elyan-chat-fallback-v1";
const WORKER_HEARTBEAT_KEY = "elyan:chat-generation:worker-ready";
const WORKER_HEARTBEAT_TTL_MS = 45_000;
const WORKER_HEARTBEAT_INTERVAL_MS = 15_000;
const QUEUE_RECOVERY_INTERVAL_MS = 30_000;
const QUEUE_DEADLINE_SWEEP_INTERVAL_MS = 5_000;
const QUEUE_OPERATION_TIMEOUT_MS = 3_000;
const CHAT_ADMISSION_SLOT_KEY = "chat-generation:admission:active-v1";
// Backstop for a slot whose task crashed without releasing. Kept well above any
// single chat generation but far below the previous 60 min, so a stuck task
// frees its slot in minutes instead of locking capacity for an hour.
const CHAT_ADMISSION_SLOT_TTL_MS = 10 * 60_000;

type QueueResources = {
  primary: Queue<ChatGenerationJobData>;
  fallback: Queue<ChatGenerationJobData>;
};

type WorkerResources = {
  primary: Worker<ChatGenerationJobData>;
  fallback: Worker<ChatGenerationJobData>;
  heartbeat: ReturnType<typeof setInterval>;
  recovery: ReturnType<typeof setInterval>;
  deadlineSweep: ReturnType<typeof setInterval>;
};

const queues = new WeakMap<FastifyInstance, QueueResources>();
const workers = new WeakMap<FastifyInstance, WorkerResources>();
const queueLifecycleRegistered = new WeakSet<FastifyInstance>();

async function closeChatGenerationQueues(app: FastifyInstance): Promise<void> {
  const resources = queues.get(app);
  if (!resources) return;
  queues.delete(app);
  await Promise.all([
    resources.primary.close().catch(() => undefined),
    resources.fallback.close().catch(() => undefined),
  ]);
}

export function registerChatGenerationQueueLifecycle(
  app: FastifyInstance,
): void {
  if (queueLifecycleRegistered.has(app)) return;
  queueLifecycleRegistered.add(app);
  app.addHook("onClose", async () => {
    queueLifecycleRegistered.delete(app);
    await closeChatGenerationQueues(app);
  });
}

export function createChatGenerationLeaseFence() {
  let lost = false;
  return {
    markLost(): void {
      lost = true;
    },
    shouldAbort(): boolean {
      return lost;
    },
  };
}

export function createLocalConcurrencyGate(limit: number) {
  const maxActive = Math.max(1, Math.trunc(limit));
  let active = 0;
  const waiting: Array<() => void> = [];

  return async function withLocalConcurrency<T>(
    operation: () => Promise<T>,
  ): Promise<T> {
    await new Promise<void>((resolve) => {
      const start = () => {
        active += 1;
        resolve();
      };
      if (active < maxActive) {
        start();
      } else {
        waiting.push(start);
      }
    });
    try {
      return await operation();
    } finally {
      active -= 1;
      waiting.shift()?.();
    }
  };
}

async function withQueueTimeout<T>(operation: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | null = null;
  try {
    return await Promise.race([
      operation,
      new Promise<T>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error("chat_queue_operation_timeout")),
          QUEUE_OPERATION_TIMEOUT_MS,
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function connection(redisUrl: string) {
  return {
    url: redisUrl,
    enableOfflineQueue: false,
    lazyConnect: true,
    maxRetriesPerRequest: null,
  };
}

function queueName(stage: ChatGenerationProviderStage): string {
  return stage === "primary" ? PRIMARY_QUEUE_NAME : FALLBACK_QUEUE_NAME;
}

export function chatGenerationJobId(
  stage: ChatGenerationProviderStage,
  taskId: string,
): string {
  return `chat-${stage}-${taskId}`.replace(/[^a-zA-Z0-9_-]+/g, "-");
}

export function isChatGenerationQueueEnabled(app: FastifyInstance): boolean {
  return (
    app.config.ELYAN_CHAT_QUEUE_ENABLED === true &&
    Boolean(app.config.REDIS_URL)
  );
}

export function isGeminiFallbackQueueConfigured(
  app: FastifyInstance,
): boolean {
  return Boolean(String(app.config.GEMINI_API_KEY || "").trim());
}

async function queueResourcesFor(
  app: FastifyInstance,
): Promise<QueueResources | null> {
  if (!isChatGenerationQueueEnabled(app) || !app.config.REDIS_URL) {
    return null;
  }
  const existing = queues.get(app);
  if (existing) return existing;
  const options = {
    connection: connection(app.config.REDIS_URL) as never,
    defaultJobOptions: {
      attempts: 1,
      removeOnComplete: true,
      removeOnFail: { age: 86_400, count: 1_000 },
    },
  };
  const resources = {
    primary: new Queue<ChatGenerationJobData>(PRIMARY_QUEUE_NAME, options),
    fallback: new Queue<ChatGenerationJobData>(FALLBACK_QUEUE_NAME, options),
  };
  try {
    await withQueueTimeout(
      Promise.all([
        resources.primary.waitUntilReady(),
        resources.fallback.waitUntilReady(),
      ]),
    );
  } catch (error) {
    await Promise.all([
      resources.primary.close().catch(() => undefined),
      resources.fallback.close().catch(() => undefined),
    ]);
    throw error;
  }
  queues.set(app, resources);
  return resources;
}

export async function enqueueSharedBrainChatTask(
  app: FastifyInstance,
  input: ChatGenerationJobData,
  stage: ChatGenerationProviderStage = "primary",
): Promise<boolean> {
  const resources = await queueResourcesFor(app);
  if (!resources) return false;
  const queue = stage === "primary" ? resources.primary : resources.fallback;
  const jobId = chatGenerationJobId(stage, input.taskId);
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      await withQueueTimeout(
        queue.add("generate", input, {
          jobId,
        }),
      );
      return true;
    } catch (error) {
      if (attempt >= 2) throw error;
      const errorRecord = readRecord(error);
      app.log.warn(
        {
          taskId: input.taskId,
          stage,
          attempt,
          errorClass: error instanceof Error ? error.name : "queue_error",
          errorCode:
            typeof errorRecord?.code === "string"
              ? errorRecord.code.slice(0, 80)
              : null,
        },
        "chat generation enqueue retry",
      );
      await new Promise((resolve) =>
        setTimeout(resolve, 50 + Math.floor(Math.random() * 100)),
      );
      await withQueueTimeout(queue.waitUntilReady());
    }
  }
  return false;
}

export async function reserveChatGenerationAdmission(
  app: FastifyInstance,
  taskId: string,
): Promise<"accepted" | "full" | "unavailable"> {
  // Admission is soft backpressure, not a correctness gate: the BullMQ queue and
  // worker concurrency are the real limits. A transient Redis blip must never
  // deny a chat. So we degrade gracefully — when Redis is momentarily
  // unusable we fall back to the store's per-process in-memory slot pool
  // (requireRedis=false) instead of failing closed, and any hard error or
  // missing store admits the request rather than returning "unavailable".
  const store = app.services?.reliability?.store;
  if (!store) return "accepted";
  const reservation = await store
    .tryAcquireExpiringSlot(
      CHAT_ADMISSION_SLOT_KEY,
      taskId,
      getChatGenerationQueueLimits(app).globalBacklogMax,
      CHAT_ADMISSION_SLOT_TTL_MS,
      false,
    )
    .catch((error) => {
      app.log.warn(
        { error: error instanceof Error ? error.message : "admission_error", taskId },
        "chat admission slot check failed; admitting request (fail-open)",
      );
      return null;
    });
  if (!reservation) return "accepted";
  return reservation.allowed ? "accepted" : "full";
}

export async function releaseChatGenerationAdmission(
  app: FastifyInstance,
  taskId: string,
): Promise<void> {
  const store = app.services?.reliability?.store;
  if (!store) return;
  await store
    .releaseExpiringSlot(CHAT_ADMISSION_SLOT_KEY, taskId)
    .catch(() => undefined);
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function readChatGenerationQueueFailure(
  error: unknown,
): ChatGenerationQueueFailure {
  const details = readRecord(error instanceof AppError ? error.details : null);
  const attempts = Array.isArray(details?.attemptFailures)
    ? details.attemptFailures
        .map(readRecord)
        .filter((value): value is Record<string, unknown> => value != null)
    : [];
  const lastAttempt = attempts.at(-1) ?? null;
  const failureClass = String(
    details?.failureClass ?? lastAttempt?.failureClass ?? "unavailable",
  );
  const retryAfterValue =
    details?.retryAfterMs ?? lastAttempt?.retryAfterMs ?? null;
  const retryAfterMs =
    typeof retryAfterValue === "number" &&
    Number.isFinite(retryAfterValue) &&
    retryAfterValue >= 0
      ? Math.trunc(retryAfterValue)
      : null;
  const explicitlyNonRetryable = new Set([
    "policy_blocked",
    "invalid_output",
    "rejected",
  ]).has(failureClass);
  const transientFailureClass = new Set([
    "rate_limited",
    "timeout",
    "unavailable",
    "queue_unavailable",
    "queue_deadline",
    "fallback_unavailable",
  ]).has(failureClass);
  const retryable =
    error instanceof AppError
      ? details?.retrySuggested === false
        ? false
        : error.statusCode === 429
          ? true
          : explicitlyNonRetryable
            ? false
            : error.statusCode >= 400 && error.statusCode < 500
              ? false
              : transientFailureClass ||
                error.statusCode >= 500 ||
                details?.transient === true
      : error instanceof TypeError ||
        (error instanceof DOMException && error.name === "AbortError");
  return {
    retryable,
    rateLimited:
      failureClass === "rate_limited" ||
      (error instanceof AppError && error.statusCode === 429),
    retryAfterMs,
    failureClass,
  };
}

async function delayJob(
  job: Job<ChatGenerationJobData>,
  token: string | undefined,
  delayMs: number,
): Promise<never> {
  await job.moveToDelayed(Date.now() + Math.max(250, delayMs), token);
  throw new DelayedError();
}

function taskAgeMs(createdAt: Date): number {
  return Math.max(0, Date.now() - createdAt.getTime());
}

function userLockKey(userId: string): string {
  const digest = createHash("sha256").update(userId).digest("hex").slice(0, 24);
  return `lock:chat-generation:user:${digest}`;
}

function taskLeaseKey(taskId: string): string {
  const digest = createHash("sha256").update(taskId).digest("hex").slice(0, 24);
  return `lock:chat-generation:task:${digest}`;
}

function retryCounterKey(
  stage: ChatGenerationProviderStage,
  taskId: string,
): string {
  return `chat-generation:retry:${stage}:${taskId}`;
}

async function enqueueFallback(
  app: FastifyInstance,
  input: ChatGenerationJobData,
) {
  const service = await import("../tasks/service.js");
  if (!isGeminiFallbackQueueConfigured(app)) {
    await service.failQueuedSharedBrainChatTask(app, {
      ...input,
      error: new AppError(
        503,
        "server_brain_unavailable",
        "Buradayım. Bunu birlikte ilerletelim; beklediğin sonucu bir cümleyle netleştirir misin?",
        {
          transient: false,
          retrySuggested: false,
          failureClass: "fallback_unconfigured",
        },
      ),
    });
    return;
  }
  await service.markQueuedSharedBrainChatPhase(app, {
    ...input,
    phase: "provider_failover",
    message: "Yanıt yeniden deneniyor.",
  });
  await enqueueSharedBrainChatTask(app, input, "fallback");
}

async function processGenerationJob(
  app: FastifyInstance,
  stage: ChatGenerationProviderStage,
  worker: Worker<ChatGenerationJobData>,
  job: Job<ChatGenerationJobData>,
  token?: string,
) {
  const service = await import("../tasks/service.js");
  const snapshot = await service.getQueuedSharedBrainChatTask(app, job.data);
  if (!snapshot) return;
  if (snapshot.terminal) {
    await service.processQueuedSharedBrainChatTask(app, {
      ...job.data,
      providerStage: stage,
    });
    return;
  }
  const timing = getChatGenerationTiming(snapshot.workload);
  const ageMs = taskAgeMs(snapshot.task.createdAt);
  const agePhase = chatGenerationAgePhase(snapshot.workload, ageMs);
  if (agePhase === "deadline") {
    await service.failQueuedSharedBrainChatTask(app, {
      ...job.data,
      error: new AppError(
        503,
        "server_brain_unavailable",
        "Buradayım. Kaldığımız yerden devam edelim; önce hangi kısmı ele almamı istersin?",
        {
          transient: true,
          retrySuggested: true,
          failureClass: "queue_deadline",
        },
      ),
    });
    return;
  }
  if (stage === "primary" && agePhase === "fallback") {
    await enqueueFallback(app, job.data);
    return;
  }

  const lockOwner = randomUUID();
  const lockTtlMs = 30_000;
  const taskLeaseAcquired = await app.services.reliability.store.acquireLock(
    taskLeaseKey(job.data.taskId),
    lockOwner,
    lockTtlMs,
    true,
  );
  if (!taskLeaseAcquired) {
    // Lease başka bir worker'da: görev zaten işleniyor. Chat satırına/faz
    // durumuna DOKUNMA — buradaki "Yanıt hazırlanıyor." yeniden-yayını, akan
    // cevabın üstüne yazan eski ACK snapshot'larının kaynağıydı. Sadece bekle.
    return delayJob(job, token, 750 + Math.floor(Math.random() * 500));
  }

  const userLockAcquired = await app.services.reliability.store.acquireLock(
    userLockKey(job.data.userId),
    lockOwner,
    lockTtlMs,
    true,
  );
  if (!userLockAcquired) {
    await app.services.reliability.store
      .releaseLock(taskLeaseKey(job.data.taskId), lockOwner)
      .catch(() => undefined);
    // Kullanıcının başka bir turu işleniyor: faz/chat satırı yeniden yazılmaz
    // (yukarıdaki lease yorumuyla aynı gerekçe). Sadece bekle.
    return delayJob(job, token, 750 + Math.floor(Math.random() * 500));
  }

  const leaseFence = createChatGenerationLeaseFence();
  let lockRenewalPending: Promise<void> | null = null;
  const lockRenewal = setInterval(() => {
    if (lockRenewalPending) return;
    lockRenewalPending = Promise.all([
      app.services.reliability.store.renewLock(
        taskLeaseKey(job.data.taskId),
        lockOwner,
        lockTtlMs,
      ),
      app.services.reliability.store.renewLock(
        userLockKey(job.data.userId),
        lockOwner,
        lockTtlMs,
      ),
    ])
      .then(([taskLeaseRenewed, userLockRenewed]) => {
        if (!taskLeaseRenewed || !userLockRenewed) {
          leaseFence.markLost();
          app.log.warn(
            { taskId: job.data.taskId },
            "chat generation lease renewal was not confirmed",
          );
        }
      })
      .catch(() => {
        leaseFence.markLost();
      })
      .finally(() => {
        lockRenewalPending = null;
      });
  }, 10_000);

  try {
    if (stage === "primary") {
      const limits = getChatGenerationQueueLimits(app);
      const now = Date.now();
      const windowStartedAt = Math.floor(now / 60_000) * 60_000;
      const ttlMs = windowStartedAt + 65_000 - now;
      const reservation = estimateChatGenerationReservationTokens({
        prompt: snapshot.prompt,
        workload: snapshot.workload,
        limit: limits.groqTpmLimit,
      });
      const budget = await app.services.reliability.store.tryConsumeBudget(
        `chat-generation:groq-tokens:${windowStartedAt}`,
        reservation,
        limits.groqTpmLimit,
        ttlMs,
        true,
      );
      if (!budget.allowed) {
        const waitMs = Math.max(500, windowStartedAt + 60_000 - now);
        if (ageMs + waitMs >= timing.fallbackAfterMs) {
          await enqueueFallback(app, job.data);
          return;
        }
        await service.markQueuedSharedBrainChatPhase(app, {
          ...job.data,
          phase: "retrying",
          message: "Yanıt yeniden deneniyor.",
        });
        return delayJob(job, token, waitMs + Math.floor(Math.random() * 250));
      }
    }

    try {
      await service.processQueuedSharedBrainChatTask(app, {
        ...job.data,
        providerStage: stage,
        shouldAbort: leaseFence.shouldAbort,
      });
      return;
    } catch (error) {
      const failure = readChatGenerationQueueFailure(error);
      const currentAgeMs = taskAgeMs(snapshot.task.createdAt);
      if (!failure.retryable) {
        await service.failQueuedSharedBrainChatTask(app, {
          ...job.data,
          error,
        });
        return;
      }
      if (stage === "primary") {
        const retryAfterMs = Math.max(500, failure.retryAfterMs ?? 1_000);
        if (
          failure.rateLimited &&
          currentAgeMs + retryAfterMs < timing.fallbackAfterMs
        ) {
          await service.markQueuedSharedBrainChatPhase(app, {
            ...job.data,
            phase: "retrying",
            message: "Yanıt yeniden deneniyor.",
          });
          await worker.rateLimit(retryAfterMs);
          throw Worker.RateLimitError();
        }
        await enqueueFallback(app, job.data);
        return;
      }

      const remainingMs = timing.deadlineMs - currentAgeMs;
      const retryAfterMs = Math.max(500, failure.retryAfterMs ?? 0);
      if (remainingMs <= retryAfterMs) {
        await service.failQueuedSharedBrainChatTask(app, {
          ...job.data,
          error: new AppError(
            503,
            "server_brain_unavailable",
            "Yanıt zamanında tamamlanamadı. Lütfen yeniden dene.",
            {
              transient: true,
              retrySuggested: true,
              failureClass: failure.failureClass,
            },
          ),
        });
        return;
      }
      await service.markQueuedSharedBrainChatPhase(app, {
        ...job.data,
        phase: "retrying",
        message: "Yanıt yeniden deneniyor.",
      });
      if (failure.rateLimited) {
        await worker.rateLimit(retryAfterMs);
        throw Worker.RateLimitError();
      }
      const retryCount = await app.services.reliability.store.increment(
        retryCounterKey(stage, job.data.taskId),
        timing.deadlineMs,
      );
      const delayMs = Math.min(5_000, 500 * 2 ** Math.min(4, retryCount - 1));
      return delayJob(
        job,
        token,
        Math.min(remainingMs - 1, delayMs + Math.floor(Math.random() * 500)),
      );
    }
  } finally {
    clearInterval(lockRenewal);
    await (lockRenewalPending as Promise<void> | null)?.catch(
      () => undefined,
    );
    await Promise.all([
      app.services.reliability.store
        .releaseLock(userLockKey(job.data.userId), lockOwner)
        .catch(() => undefined),
      app.services.reliability.store
        .releaseLock(taskLeaseKey(job.data.taskId), lockOwner)
        .catch(() => undefined),
    ]);
  }
}

async function recoverQueuedChatTasks(app: FastifyInstance): Promise<number> {
  const service = await import("../tasks/service.js");
  const resources = await queueResourcesFor(app);
  if (!resources) return 0;
  const recoverable = await service.listRecoverableSharedBrainChatTasks(app, {
    limit: getChatGenerationQueueLimits(app).globalBacklogMax,
  });
  let recovered = 0;
  for (let offset = 0; offset < recoverable.length; offset += 50) {
    await Promise.all(
      recoverable
        .slice(offset, offset + 50)
        .map(async (job) => {
          const [primaryJob, fallbackJob] = await Promise.all([
            resources.primary.getJob(chatGenerationJobId("primary", job.taskId)),
            resources.fallback.getJob(
              chatGenerationJobId("fallback", job.taskId),
            ),
          ]);
          const represented = await Promise.all(
            [primaryJob, fallbackJob]
              .filter((value): value is Job<ChatGenerationJobData> => value != null)
              .map(async (value) => {
                const state = String(await value.getState());
                if (state === "failed" || state === "completed") {
                  await value.remove().catch(() => undefined);
                  return false;
                }
                return state !== "completed" && state !== "unknown";
              }),
          );
          if (represented.some(Boolean)) return;
          const admission = await reserveChatGenerationAdmission(
            app,
            job.taskId,
          );
          if (admission !== "accepted") return;
          try {
            await enqueueSharedBrainChatTask(
              app,
              { taskId: job.taskId, userId: job.userId },
              "primary",
            );
          } catch (error) {
            await releaseChatGenerationAdmission(app, job.taskId);
            throw error;
          }
          recovered += 1;
        }),
    );
  }
  return recovered;
}

async function sweepOverdueQueuedChatTasks(
  app: FastifyInstance,
): Promise<number> {
  const service = await import("../tasks/service.js");
  const resources = await queueResourcesFor(app);
  if (!resources) return 0;
  const candidates = await service.listRecoverableSharedBrainChatTasks(app, {
    limit: getChatGenerationQueueLimits(app).globalBacklogMax,
  });
  const now = Date.now();
  const overdue = candidates.filter(
    (candidate) =>
      chatGenerationAgePhase(
        candidate.workload,
        now - candidate.createdAt.getTime(),
      ) === "deadline",
  );
  for (let offset = 0; offset < overdue.length; offset += 25) {
    await Promise.all(
      overdue.slice(offset, offset + 25).map(async (candidate) => {
        await service.failQueuedSharedBrainChatTask(app, {
          taskId: candidate.taskId,
          userId: candidate.userId,
          error: new AppError(
            503,
            "server_brain_unavailable",
            "Yanıt zamanında tamamlanamadı. Lütfen yeniden dene.",
            {
              transient: true,
              retrySuggested: true,
              failureClass: "queue_deadline",
            },
          ),
        });
        const jobs = await Promise.all([
          resources.primary.getJob(
            chatGenerationJobId("primary", candidate.taskId),
          ),
          resources.fallback.getJob(
            chatGenerationJobId("fallback", candidate.taskId),
          ),
        ]);
        await Promise.all(
          jobs
            .filter(
              (value): value is Job<ChatGenerationJobData> => value != null,
            )
            .map((value) => value.remove().catch(() => undefined)),
        );
      }),
    );
  }

  const failoverCandidates = candidates.filter(
    (candidate) =>
      chatGenerationAgePhase(
        candidate.workload,
        now - candidate.createdAt.getTime(),
      ) === "fallback",
  );
  for (let offset = 0; offset < failoverCandidates.length; offset += 25) {
    await Promise.all(
      failoverCandidates.slice(offset, offset + 25).map(async (candidate) => {
        const lockOwner = randomUUID();
        const taskLeaseAcquired = await app.services.reliability.store
          .acquireLock(
            taskLeaseKey(candidate.taskId),
            lockOwner,
            10_000,
            true,
          )
          .catch(() => false);
        if (!taskLeaseAcquired) return;
        try {
          const snapshot = await service.getQueuedSharedBrainChatTask(app, {
            taskId: candidate.taskId,
            userId: candidate.userId,
          });
          if (!snapshot || snapshot.terminal) return;

          const [primaryJob, fallbackJob] = await Promise.all([
            resources.primary.getJob(
              chatGenerationJobId("primary", candidate.taskId),
            ),
            resources.fallback.getJob(
              chatGenerationJobId("fallback", candidate.taskId),
            ),
          ]);
          const fallbackState = fallbackJob
            ? String(await fallbackJob.getState())
            : "unknown";
          if (
            fallbackJob &&
            fallbackState !== "completed" &&
            fallbackState !== "failed" &&
            fallbackState !== "unknown"
          ) {
            await primaryJob?.remove().catch(() => undefined);
            return;
          }
          if (fallbackJob) {
            await fallbackJob.remove().catch(() => undefined);
          }

          const primaryState = primaryJob
            ? String(await primaryJob.getState())
            : "unknown";
          // Acquiring the task lease proves an "active" Bull job is only
          // waiting on this replica's shared local gate; a provider call that
          // is truly running owns the lease and prevents this sweep. Enqueue
          // fallback now, but let Bull retire the active primary naturally.
          await enqueueFallback(app, {
            taskId: candidate.taskId,
            userId: candidate.userId,
          });
          if (primaryState !== "active") {
            await primaryJob?.remove().catch(() => undefined);
          }
        } finally {
          await app.services.reliability.store
            .releaseLock(taskLeaseKey(candidate.taskId), lockOwner)
            .catch(() => undefined);
        }
      }),
    );
  }
  return overdue.length;
}

export async function ensureChatGenerationWorkers(
  app: FastifyInstance,
): Promise<void> {
  if (workers.has(app) || !isChatGenerationQueueEnabled(app) || !app.config.REDIS_URL) {
    return;
  }
  const resources = await queueResourcesFor(app);
  if (!resources) return;
  const limits = getChatGenerationQueueLimits(app);
  const withLocalConcurrency = createLocalConcurrencyGate(
    limits.workerConcurrency,
  );
  await Promise.all([
    resources.primary.setGlobalConcurrency(limits.primaryGlobalConcurrency),
    resources.fallback.setGlobalConcurrency(limits.fallbackGlobalConcurrency),
  ]);

  let primaryWorker: Worker<ChatGenerationJobData>;
  let fallbackWorker: Worker<ChatGenerationJobData>;
  primaryWorker = new Worker<ChatGenerationJobData>(
    PRIMARY_QUEUE_NAME,
    (job, token) =>
      withLocalConcurrency(() =>
        processGenerationJob(app, "primary", primaryWorker, job, token),
      ),
    {
      connection: connection(app.config.REDIS_URL) as never,
      concurrency: limits.workerConcurrency,
      lockDuration: 30_000,
      stalledInterval: 5_000,
      limiter: { max: limits.groqRpmLimit, duration: 60_000 },
    },
  );
  fallbackWorker = new Worker<ChatGenerationJobData>(
    FALLBACK_QUEUE_NAME,
    (job, token) =>
      withLocalConcurrency(() =>
        processGenerationJob(app, "fallback", fallbackWorker, job, token),
      ),
    {
      connection: connection(app.config.REDIS_URL) as never,
      concurrency: limits.workerConcurrency,
      lockDuration: 30_000,
      stalledInterval: 5_000,
      limiter: { max: limits.geminiRpmLimit, duration: 60_000 },
    },
  );
  await Promise.all([
    primaryWorker.waitUntilReady(),
    fallbackWorker.waitUntilReady(),
  ]);
  await sweepOverdueQueuedChatTasks(app);
  await recoverQueuedChatTasks(app);

  const writeHeartbeat = () =>
    app.services.reliability.store.set(
      WORKER_HEARTBEAT_KEY,
      "ready",
      WORKER_HEARTBEAT_TTL_MS,
    );
  await writeHeartbeat();
  const heartbeat = setInterval(() => {
    void writeHeartbeat().catch(() => undefined);
  }, WORKER_HEARTBEAT_INTERVAL_MS);
  const recovery = setInterval(() => {
    void recoverQueuedChatTasks(app).catch((error) => {
      app.log.warn(
        { errorCode: error instanceof Error ? error.name : "unknown" },
        "chat generation queue recovery failed",
      );
    });
  }, QUEUE_RECOVERY_INTERVAL_MS);
  const deadlineSweep = setInterval(() => {
    void sweepOverdueQueuedChatTasks(app).catch((error) => {
      app.log.warn(
        { errorCode: error instanceof Error ? error.name : "unknown" },
        "chat generation deadline sweep failed",
      );
    });
  }, QUEUE_DEADLINE_SWEEP_INTERVAL_MS);

  for (const worker of [primaryWorker, fallbackWorker]) {
    worker.on("failed", (job, error) => {
      app.log.warn(
        {
          taskId: job?.data.taskId,
          queue: worker.name,
          errorCode: error.name,
        },
        "chat generation job failed",
      );
    });
    worker.on("error", (error) => {
      app.log.error(
        { queue: worker.name, errorCode: error.name },
        "chat generation worker error",
      );
    });
  }
  const workerResources = {
    primary: primaryWorker,
    fallback: fallbackWorker,
    heartbeat,
    recovery,
    deadlineSweep,
  };
  workers.set(app, workerResources);
  app.addHook("onClose", async () => {
    if (workers.get(app) !== workerResources) return;
    workers.delete(app);
    clearInterval(heartbeat);
    clearInterval(recovery);
    clearInterval(deadlineSweep);
    await Promise.all([
      primaryWorker.close().catch(() => undefined),
      fallbackWorker.close().catch(() => undefined),
    ]);
  });
}

export async function isChatGenerationWorkerReady(
  app: FastifyInstance,
): Promise<boolean> {
  if (!isChatGenerationQueueEnabled(app)) return true;
  return (
    (await app.services.reliability.store
      .get(WORKER_HEARTBEAT_KEY)
      .catch(() => null)) === "ready"
  );
}

export async function getChatGenerationQueueCounts(
  app: FastifyInstance,
): Promise<{ waiting: number; active: number; delayed: number } | null> {
  const resources = await queueResourcesFor(app);
  if (!resources) return null;
  const [primary, fallback] = await Promise.all([
    resources.primary.getJobCounts("waiting", "active", "delayed"),
    resources.fallback.getJobCounts("waiting", "active", "delayed"),
  ]);
  return {
    waiting: primary.waiting + fallback.waiting,
    active: primary.active + fallback.active,
    delayed: primary.delayed + fallback.delayed,
  };
}

export const CHAT_GENERATION_QUEUE_NAMES = {
  primary: PRIMARY_QUEUE_NAME,
  fallback: FALLBACK_QUEUE_NAME,
} as const;
