import { randomUUID } from "node:crypto";
import { Queue, Worker, type Job } from "bullmq";
import type { FastifyInstance } from "fastify";
import { activeTaskStatuses } from "./queue.js";
import { maybeMaterializeDesktopPlan } from "./materialize-plan.js";
import { issueTaskDispatchLease, getTaskById } from "./service.js";

export type TaskDispatchJobData = {
  taskId: string;
};

type TaskDispatchResources = {
  queue: Queue;
  worker: Worker;
};

const TASK_DISPATCH_QUEUE_NAME = "elyan-task-dispatch";
const dispatchResources = new WeakMap<FastifyInstance, TaskDispatchResources>();

function createRedisConnectionOptions(redisUrl: string) {
  return {
    url: redisUrl,
    enableOfflineQueue: false,
    lazyConnect: true,
    maxRetriesPerRequest: null,
  };
}

async function processTaskDispatchJob(app: FastifyInstance, job: Job<TaskDispatchJobData>) {
  const task = await getTaskById(app, job.data.taskId);
  if (!task || task.status !== "queued" || !activeTaskStatuses.includes(task.status)) {
    return;
  }

  const claimOwner = `bullmq:${job.id ?? job.data.taskId}:${randomUUID()}`;
  const acquired = await app.services.reliability.acquireTaskDispatchLock(task.id, claimOwner);
  if (!acquired) {
    return;
  }

  // Hibrit sunucu-materyalizasyonu: karmaşık desktop görevlerinde work-order
  // planını dispatch'ten HEMEN önce (create yolundan uzak) tam bağımlılık-graflı
  // veriye derleyip task satırına persist eder → issueTaskDispatchLease güncel
  // planı DB'den okur ve dispatch envelope'u taşır. Fail-safe: hata → heuristik.
  await maybeMaterializeDesktopPlan(app, task);

  const leaseResult = await issueTaskDispatchLease(app, {
    taskId: task.id,
    runtimeConnectionId: task.runtimeConnectionId ?? null,
  });
  if (!leaseResult || leaseResult.reused) {
    await app.services.reliability.releaseTaskDispatchLock(task.id, claimOwner);
    return;
  }

  const dispatched = app.services.realtimeHub.sendToRuntime(task.targetDeviceId, {
    type: "task.dispatch",
    task: leaseResult.task,
    leaseId: leaseResult.lease.leaseId,
    leaseExpiresAt: leaseResult.lease.expiresAt,
  });

  if (dispatched) {
    return;
  }

  await app.services.reliability.releaseTaskDispatchLock(task.id, claimOwner);
  throw new Error("runtime_offline");
}

export async function ensureTaskDispatchWorker(app: FastifyInstance): Promise<void> {
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
      concurrency: 2,
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

export async function enqueueTaskDispatch(app: FastifyInstance, taskId: string): Promise<boolean> {
  const resources = dispatchResources.get(app);
  if (!resources) {
    return false;
  }

  await resources.queue.add(
    TASK_DISPATCH_QUEUE_NAME,
    {
      taskId,
    },
    {
      jobId: taskId,
    },
  );

  return true;
}
