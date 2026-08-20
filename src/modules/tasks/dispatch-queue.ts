import { randomUUID } from "node:crypto";
import { Queue, Worker, type Job } from "bullmq";
import type { FastifyInstance } from "fastify";
import { recordBridgeLearningSignals } from "../../core/understanding/user-understanding-service.js";
import { syncChatTaskLifecycle } from "../chat/task-sync.js";
import { activeTaskStatuses } from "./queue.js";
import {
  markDesktopPlanPrepared,
  maybeMaterializeDesktopPlan,
  maybePauseForDesktopPlanApproval,
} from "./materialize-plan.js";
import {
  failQueuedDesktopPlanTask,
  issueTaskDispatchLease,
  getTaskById,
  releaseUnacceptedTaskDispatchLease,
} from "./service.js";

export type TaskDispatchJobData = {
  taskId: string;
};

type TaskDispatchResources = {
  queue: Queue;
  worker: Worker;
};

const TASK_DISPATCH_QUEUE_NAME = "elyan-task-dispatch";
const dispatchResources = new WeakMap<FastifyInstance, TaskDispatchResources>();
const localDispatches = new WeakMap<FastifyInstance, Set<string>>();

type DispatchTask = NonNullable<Awaited<ReturnType<typeof getTaskById>>>;

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
): Promise<
  "dispatched" | "awaiting_approval" | "planning_failed" | "not_dispatched"
> {
  const materialized = await operations.materialize(app, task);
  await operations.markPrepared(app, task, materialized);

  // ── PLAN ÜRETİLEMEDİ: GÖREVİ ÖLDÜRME, MASAÜSTÜNE DEVRET ─────────────────
  //
  // Eskiden burada `failPlanning` çağrılıyor ve kullanıcı "Görevin güvenilir
  // yürütme planı hazırlanamadı" görüyordu. Canlı örnek (2026-08-20):
  // "Bilgisayarımda arama yap chrome açık mı" — yönlendirme DOĞRU çalışmış,
  // görev desktop_runtime'a gitmiş, ama sunucu plan üretemediği için iş
  // masaüstüne HİÇ ULAŞMADAN öldü.
  //
  // Oysa masaüstü bunu 2026-08-04'te zaten çözmüştü: plan yoksa fail-closed
  // ETMİYOR, görevi YERELDE planlayan çok-turlu ajan döngüsüne delege ediyor
  // (`_runtime_task_preflight_error` → `delegate_to_agent_loop`). Yani
  // masaüstü plansız görevi kabul etmeye HAZIRDI; backend hiç göndermiyordu.
  // Yarım kalmış göç: bir uç güncellendi, diğeri değil.
  //
  // GÜVENLİK AÇILMIYOR: sunucu planı olmadığında sunucu onay kapısı
  // (`gatePlanApproval`) atlanır, ama onay masaüstünde ZATEN uygulanır —
  // ajan döngüsü `require_approval` ile ilk yan etkide durur ve
  // `safety_policy` her adımda çalışır. Onay kaybolmuyor, yeri değişiyor.
  //
  // Görev yalnız GERÇEKTEN gidecek yer yoksa düşer (aşağıdaki lease/sendToRuntime
  // yolları `not_dispatched` döndürür ve çağıran onu ele alır).
  if (!materialized) {
    app.log.warn(
      { taskId: task.id, targetDeviceId: task.targetDeviceId },
      "desktop plan not materialized; delegating planning to the desktop agent loop",
    );
  }

  const approvalTask =
    materialized && operations.gatePlanApproval
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
    const outcome = await dispatchClaimedTask(app, task);
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
  setImmediate(() => {
    void processTaskDispatch(app, taskId, `local:${taskId}:${randomUUID()}`)
      .catch((error) => {
        app.log.warn(
          { taskId, error },
          "local task dispatch attempt failed; runtime polling remains available",
        );
      })
      .finally(() => {
        pending.delete(taskId);
        if (pending.size === 0) {
          localDispatches.delete(app);
        }
      });
  });
  return true;
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
