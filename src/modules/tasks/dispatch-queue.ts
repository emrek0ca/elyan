import { randomUUID } from "node:crypto";
import { Queue, Worker, type Job } from "bullmq";
import { asc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { tasks } from "../../db/schema.js";
import { recordBridgeLearningSignals } from "../../core/understanding/user-understanding-service.js";
import { syncChatTaskLifecycle } from "../chat/task-sync.js";
import { activeTaskStatuses } from "./queue.js";
import {
  markDesktopPlanPrepared,
  maybeMaterializeDesktopPlan,
  maybePauseForDesktopPlanApproval,
} from "./materialize-plan.js";
import { isDesktopPlanPreparationPending } from "./desktop-work-order.js";
import {
  failQueuedDesktopPlanTask,
  issueTaskDispatchLease,
  getTaskById,
  releaseUnacceptedTaskDispatchLease,
} from "./service.js";
import { extractTaskRouteDecision } from "./service-helpers.js";

export type TaskDispatchJobData = {
  taskId: string;
};

type TaskDispatchResources = {
  queue: Queue;
  worker: Worker;
};

const TASK_DISPATCH_QUEUE_NAME = "elyan-task-dispatch";
const MAX_PLAN_MATERIALIZATION_ATTEMPTS = 3;
const LOCAL_DISPATCH_RETRY_DELAYS_MS = [5_000, 10_000] as const;
const QUEUED_DISPATCH_RECOVERY_LIMIT = 100;
const dispatchResources = new WeakMap<FastifyInstance, TaskDispatchResources>();
const localDispatches = new WeakMap<FastifyInstance, Set<string>>();

type DispatchTask = NonNullable<Awaited<ReturnType<typeof getTaskById>>>;

export async function sendPendingDesktopPlanStatus(
  app: FastifyInstance,
  task: Pick<DispatchTask, "id" | "title" | "status" | "updatedAt" | "targetDeviceId">,
  sendToRuntime: (
    deviceId: string,
    message: unknown,
  ) => boolean | Promise<boolean> =
    app.services.realtimeHub.sendToRuntimeDistributed.bind(
      app.services.realtimeHub,
    ),
): Promise<boolean> {
  return Promise.resolve(
    sendToRuntime(task.targetDeviceId, {
      type: "task.plan_pending",
      task: {
        id: task.id,
        title: task.title,
        status: task.status,
        summary: "Görev planlanıyor; masaüstü yürütmesi plan hazır olunca başlayacak.",
        updatedAt: task.updatedAt?.toISOString?.() ?? null,
        planPreparationPending: true,
      },
    }),
  )
    .then((sent) => sent === true)
    .catch((error) => {
      app.log.debug?.(
        { taskId: task.id, error },
        "pending plan status was not delivered to runtime",
      );
      return false;
    });
}

type ClaimedDispatchOperations = {
  materialize: typeof maybeMaterializeDesktopPlan;
  markPrepared: typeof markDesktopPlanPrepared;
  gatePlanApproval?: typeof maybePauseForDesktopPlanApproval;
  failPlanning: typeof failQueuedDesktopPlanTask;
  syncLifecycle: typeof syncChatTaskLifecycle;
  issueLease: typeof issueTaskDispatchLease;
  releaseLease: typeof releaseUnacceptedTaskDispatchLease;
  sendToRuntime: (
    deviceId: string,
    message: unknown,
  ) => boolean | Promise<boolean>;
};

type DispatchAttemptOptions = {
  planningAttempt?: number;
};

function createRedisConnectionOptions(redisUrl: string) {
  return {
    url: redisUrl,
    enableOfflineQueue: false,
    lazyConnect: true,
    maxRetriesPerRequest: null,
  };
}

export async function dispatchClaimedTask(
  app: FastifyInstance,
  task: DispatchTask,
  operations: ClaimedDispatchOperations = {
    materialize: maybeMaterializeDesktopPlan,
    markPrepared: markDesktopPlanPrepared,
    gatePlanApproval: maybePauseForDesktopPlanApproval,
    failPlanning: failQueuedDesktopPlanTask,
    syncLifecycle: syncChatTaskLifecycle,
    issueLease: issueTaskDispatchLease,
    releaseLease: releaseUnacceptedTaskDispatchLease,
    sendToRuntime: app.services.realtimeHub.sendToRuntimeDistributed.bind(
      app.services.realtimeHub,
    ),
  },
  options: DispatchAttemptOptions = {},
): Promise<
  "dispatched" | "awaiting_approval" | "planning_failed" | "not_dispatched"
> {
  let planPendingStatusAttempted = false;
  const announcePlanPending = async (): Promise<void> => {
    if (planPendingStatusAttempted) return;
    planPendingStatusAttempted = true;
    // Bu bir dispatch değildir: lease üretmeden yalnızca paired runtime'ın
    // görev paneline planlama durumunu taşır. Böylece kullanıcı desktop'ta
    // "Aktif görev yok" görmez; runtime bu frame'i çalıştırılabilir iş olarak
    // kabul etmez ve backend planını beklemeye devam eder.
    await sendPendingDesktopPlanStatus(app, task, operations.sendToRuntime);
  };

  // Plan zaten pending olarak işaretliyse, yavaş model materyalizasyonu
  // başlamadan önce tray'e görünür durum gönder. Bu frame çalıştırılabilir
  // iş değildir; scheduler yine yalnız hazır planı kabul eder.
  if (isDesktopPlanPreparationPending(task.payload)) {
    await announcePlanPending();
  }

  const materialized = await operations.materialize(app, task);
  await operations.markPrepared(app, task, materialized);

  // Sunucu planı hazır değilse desktop'a çalıştırılabilir step gönderme.
  // Queue retry'si plan materyalizasyonunu yeniden dener; task terminal hata
  // durumuna geçirilmez ve runtime preflight'ına ulaşmadan bekler.
  if (!materialized) {
    await announcePlanPending();
    const planningAttempt = Math.max(0, Math.floor(options.planningAttempt ?? 0));
    if (planningAttempt + 1 >= MAX_PLAN_MATERIALIZATION_ATTEMPTS) {
      const failedTask = await operations.failPlanning(app, { task });
      if (failedTask) return "planning_failed";
    }
    await operations
      .syncLifecycle(app, {
        originalTask: task,
        updatedTask: task,
        message: "Görev planlanıyor; masaüstü yürütmesi plan hazır olunca başlayacak.",
      })
      .catch((error) => {
        app.log.warn(
          { taskId: task.id, error },
          "pending desktop plan could not be synced to chat",
        );
      });
    return "not_dispatched";
  }

  const approvalTask = operations.gatePlanApproval
    ? await operations.gatePlanApproval(app, task)
    : null;
  if (approvalTask) {
    await operations
      .syncLifecycle(app, {
        originalTask: task,
        updatedTask: approvalTask,
        message: "Masaüstü planı hazır. Devam etmek için onay gerekiyor.",
      })
      .catch((error) => {
        app.log.warn(
          { taskId: task.id, error },
          "desktop plan approval could not be synced to chat",
        );
      });
    return "awaiting_approval";
  }
  if (materialized) {
    await operations
      .syncLifecycle(app, {
        originalTask: task,
        updatedTask: task,
        message: "Plan hazır. Masaüstü yürütmeye geçiliyor.",
      })
      .catch((error) => {
        app.log.warn(
          { taskId: task.id, error },
          "materialized desktop plan could not be synced to chat",
        );
      });
  }

  const leaseResult = await operations.issueLease(app, {
    taskId: task.id,
    runtimeConnectionId: task.runtimeConnectionId ?? null,
  });
  if (!leaseResult) {
    return "not_dispatched";
  }
  const lease = leaseResult.lease;
  if (!lease) {
    return "not_dispatched";
  }

  const sent = await operations.sendToRuntime(task.targetDeviceId, {
    type: "task.dispatch",
    task: leaseResult.task,
    leaseId: lease.leaseId,
    leaseExpiresAt: lease.expiresAt,
  });
  if (sent) {
    return "dispatched";
  }
  await operations.releaseLease(app, {
    taskId: task.id,
    leaseId: lease.leaseId,
  });
  return "not_dispatched";
}

async function processTaskDispatch(
  app: FastifyInstance,
  taskId: string,
  claimOwner: string,
  planningAttempt = 0,
): Promise<void> {
  const task = await getTaskById(app, taskId);
  if (
    !task ||
    task.status !== "queued" ||
    !activeTaskStatuses.includes(task.status)
  ) {
    return;
  }

  const acquired = await app.services.reliability.acquireTaskDispatchLock(
    task.id,
    claimOwner,
  );
  if (!acquired) {
    return;
  }

  let keepClaim = false;
  try {
    // Tek dispatch sahibi: plan önce model tarafından kalıcılaştırılır, canlı
    // chat izi güncellenir, lease bundan sonra üretilir. Böylece çevrimiçi
    // runtime bile başlangıç/heuristik planı yarışla alamaz.
    const outcome = await dispatchClaimedTask(app, task, undefined, {
      planningAttempt,
    });
    keepClaim = outcome === "dispatched";
    if (outcome === "dispatched") {
      await recordBridgeLearningSignals(app, {
        userId: task.userId,
        accountId: task.userId,
        taskId: task.id,
        target: "desktop",
        outcome: "dispatched",
        readiness: "ready",
        routingMode: "desktop_first_when_available",
      }).catch((error) => {
        app.log.warn(
          { taskId: task.id, error },
          "desktop dispatch learning signal could not be recorded",
        );
      });
    }
    if (outcome === "not_dispatched") {
      throw new Error("runtime_offline_or_lease_unavailable");
    }
  } finally {
    if (!keepClaim) {
      await app.services.reliability.releaseTaskDispatchLock(
        task.id,
        claimOwner,
      );
    }
  }
}

async function processTaskDispatchJob(
  app: FastifyInstance,
  job: Job<TaskDispatchJobData>,
) {
  await processTaskDispatch(
    app,
    job.data.taskId,
    `bullmq:${job.id ?? job.data.taskId}:${randomUUID()}`,
    job.attemptsMade,
  );
}

function scheduleLocalTaskDispatch(
  app: FastifyInstance,
  taskId: string,
): boolean {
  const pending = localDispatches.get(app) ?? new Set<string>();
  if (pending.has(taskId)) {
    return true;
  }
  pending.add(taskId);
  localDispatches.set(app, pending);
  const finish = () => {
    pending.delete(taskId);
    if (pending.size === 0) {
      localDispatches.delete(app);
    }
  };
  const run = async (planningAttempt: number): Promise<void> => {
    try {
      await processTaskDispatch(
        app,
        taskId,
        `local:${taskId}:${randomUUID()}`,
        planningAttempt,
      );
      finish();
    } catch (error) {
      const nextAttempt = planningAttempt + 1;
      const delay = LOCAL_DISPATCH_RETRY_DELAYS_MS[planningAttempt];
      if (delay !== undefined && nextAttempt < MAX_PLAN_MATERIALIZATION_ATTEMPTS) {
        app.log.warn(
          {
            taskId,
            planningAttempt,
            nextAttempt,
            retryInMs: delay,
            // Ham `error` nesnesi pino tarafından `{}` olarak yazılıyordu:
            // canlıda 5sn'lik geri çekilmenin NEDENİ hiç görünmedi.
            errorMessage:
              error instanceof Error ? error.message : String(error),
            errorName: error instanceof Error ? error.name : undefined,
            error,
          },
          "local task dispatch attempt failed; scheduling bounded retry",
        );
        const timer = setTimeout(() => {
          void run(nextAttempt);
        }, delay);
        timer.unref?.();
        return;
      }
      app.log.warn(
        { taskId, planningAttempt, error },
        "local task dispatch attempts exhausted; runtime polling remains available",
      );
      finish();
    }
  };
  setImmediate(() => {
    void run(0);
  });
  return true;
}

async function recoverQueuedDesktopDispatches(
  app: FastifyInstance,
  queue: Queue<TaskDispatchJobData>,
): Promise<void> {
  const queued = await app.db
    .select({ id: tasks.id, payload: tasks.payload })
    .from(tasks)
    .where(eq(tasks.status, "queued"))
    .orderBy(asc(tasks.createdAt))
    .limit(QUEUED_DISPATCH_RECOVERY_LIMIT);
  let recovered = 0;
  for (const row of queued) {
    const route = extractTaskRouteDecision(row.payload);
    const desktopRequired =
      route?.requiredRuntime === "desktop" ||
      route?.taskRoute?.needsDesktop === true ||
      route?.route === "desktop_runtime";
    if (!desktopRequired) continue;
    await queue.add(
      TASK_DISPATCH_QUEUE_NAME,
      { taskId: row.id },
      { jobId: row.id },
    );
    recovered += 1;
  }
  if (recovered > 0) {
    app.log.info(
      { recovered, scanned: queued.length },
      "queued desktop dispatches recovered after worker startup",
    );
  }
}

export async function ensureTaskDispatchWorker(
  app: FastifyInstance,
): Promise<void> {
  if (dispatchResources.has(app) || !app.config.REDIS_URL) {
    return;
  }

  const queue = new Queue<TaskDispatchJobData>(TASK_DISPATCH_QUEUE_NAME, {
    connection: createRedisConnectionOptions(app.config.REDIS_URL) as never,
    defaultJobOptions: {
      attempts: 12,
      backoff: {
        type: "exponential",
        delay: 5_000,
      },
      removeOnComplete: true,
      removeOnFail: false,
    },
  });

  const worker = new Worker<TaskDispatchJobData>(
    TASK_DISPATCH_QUEUE_NAME,
    async (job) => processTaskDispatchJob(app, job as Job<TaskDispatchJobData>),
    {
      connection: createRedisConnectionOptions(app.config.REDIS_URL) as never,
      concurrency: app.config.ELYAN_TASK_DISPATCH_WORKER_CONCURRENCY,
    },
  );

  try {
    await Promise.all([queue.waitUntilReady(), worker.waitUntilReady()]);
  } catch (error) {
    app.log.warn(
      {
        error,
      },
      "task dispatch worker unavailable; continuing without bullmq retry",
    );
    await worker.close().catch(() => undefined);
    await queue.close().catch(() => undefined);
    return;
  }

  worker.on("failed", (job, error) => {
    app.log.warn(
      {
        taskId: job?.data.taskId,
        jobId: job?.id,
        error,
      },
      "task dispatch job failed",
    );
  });

  worker.on("error", (error) => {
    app.log.warn(
      {
        errorMessage: error instanceof Error ? error.message : String(error),
        errorStack: error instanceof Error ? error.stack : undefined,
        errorCode: (error as NodeJS.ErrnoException).code,
      },
      "task dispatch worker error",
    );
  });

  queue.on("error", (error) => {
    app.log.warn(
      {
        error,
      },
      "task dispatch queue error",
    );
  });

  dispatchResources.set(app, {
    queue,
    worker,
  });

  app.addHook("onClose", async () => {
    const resources = dispatchResources.get(app);
    if (!resources) {
      return;
    }

    dispatchResources.delete(app);

    await resources.worker.close().catch(() => undefined);
    await resources.queue.close().catch(() => undefined);
  });

  await recoverQueuedDesktopDispatches(app, queue).catch((error) => {
    app.log.warn(
      { error },
      "queued desktop dispatch recovery failed; new dispatches remain available",
    );
  });
}

export async function enqueueTaskDispatch(
  app: FastifyInstance,
  taskId: string,
  options: { jobId?: string } = {},
): Promise<boolean> {
  const resources = dispatchResources.get(app);
  if (!resources) {
    return scheduleLocalTaskDispatch(app, taskId);
  }

  try {
    await resources.queue.add(
      TASK_DISPATCH_QUEUE_NAME,
      {
        taskId,
      },
      {
        jobId: options.jobId?.trim() || taskId,
      },
    );
  } catch (error) {
    app.log.warn(
      { taskId, error },
      "task dispatch queue unavailable; using local async dispatch",
    );
    return scheduleLocalTaskDispatch(app, taskId);
  }

  return true;
}
