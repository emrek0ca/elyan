import { Queue, Worker, type Job } from "bullmq";
import type { FastifyInstance } from "fastify";
import { executeAgentRun } from "./agent-engine.js";
import {
  decideAgentEngineQueueAdmission,
  getAgentEngineQueueLimits,
} from "./agent-engine-policy.js";
import type { SharedBrainWorkload } from "./workloads.js";

export type AgentEngineJobData = {
  action?: "execute" | "finalize" | "expire";
  runId: string;
  userId: string;
  revision: number;
  workload: SharedBrainWorkload;
  allowSideEffects?: boolean;
  approvedStepId?: string;
};

const QUEUE_NAME = "elyan-agent-engine-v2";
const queues = new WeakMap<FastifyInstance, Queue<AgentEngineJobData>>();
const workers = new WeakMap<FastifyInstance, Worker<AgentEngineJobData>>();

function connection(redisUrl: string) {
  return { url: redisUrl, enableOfflineQueue: false, lazyConnect: true, maxRetriesPerRequest: null };
}

async function queueFor(app: FastifyInstance): Promise<Queue<AgentEngineJobData> | null> {
  if (!app.config.REDIS_URL) return null;
  const existing = queues.get(app);
  if (existing) return existing;
  const queue = new Queue<AgentEngineJobData>(QUEUE_NAME, {
    connection: connection(app.config.REDIS_URL) as never,
    defaultJobOptions: {
      attempts: 3,
      backoff: { type: "exponential", delay: 1_000 },
      removeOnComplete: 1_000,
      removeOnFail: 5_000,
    },
  });
  await queue.waitUntilReady();
  queues.set(app, queue);
  app.addHook("onClose", async () => {
    queues.delete(app);
    await queue.close().catch(() => undefined);
  });
  return queue;
}

async function countUserBacklog(
  queue: Queue<AgentEngineJobData>,
  userId: string,
  scanLimit: number,
): Promise<number> {
  const jobs = await queue.getJobs(["waiting", "delayed", "prioritized"] as never, 0, Math.max(0, scanLimit - 1), false);
  return jobs.filter((job) => job.data.userId === userId).length;
}

export async function enqueueAgentRun(app: FastifyInstance, data: AgentEngineJobData): Promise<boolean> {
  const queue = await queueFor(app).catch(() => null);
  if (!queue) return false;
  const limits = getAgentEngineQueueLimits(app);
  const counts = await queue.getJobCounts("waiting", "delayed", "prioritized", "active");
  const globalWaiting =
    (counts.waiting ?? 0) +
    (counts.delayed ?? 0) +
    (counts.prioritized ?? 0) +
    (counts.active ?? 0);
  const userWaiting = await countUserBacklog(
    queue,
    data.userId,
    Math.min(limits.globalBackpressureMax, 5_000),
  );
  const admission = decideAgentEngineQueueAdmission(
    { globalWaiting, userWaiting },
    limits,
  );
  if (!admission.accepted) {
    app.log.warn?.(
      {
        reason: admission.reason,
        userId: data.userId,
        runId: data.runId,
        globalWaiting,
        userWaiting,
      },
      "agent engine enqueue rejected by backpressure",
    );
    return false;
  }
  // Tenant namespace is part of every queue identity; runId + revision remains
  // the idempotent execution coordinate.
  const action = data.action ?? "execute";
  const actionKey = action === "finalize" ? `f${data.revision}` : action === "expire" ? `x${data.revision}` : String(data.revision);
  await queue.add(QUEUE_NAME, { ...data, action }, {
    jobId: `${data.userId}:${data.runId}:${actionKey}`,
    ...(action === "finalize" ? { delay: 120_000 } : action === "expire" ? { delay: 86_400_000 } : {}),
  });
  return true;
}

export async function ensureAgentEngineWorker(app: FastifyInstance): Promise<void> {
  if (workers.has(app) || !app.config.REDIS_URL) return;
  const queue = await queueFor(app);
  if (!queue) return;
  const worker = new Worker<AgentEngineJobData>(
    QUEUE_NAME,
    async (job: Job<AgentEngineJobData>) => {
      if (job.data.action === "finalize") {
        const { finalizeVerifiedAgentTask } = await import("./agent-task-finalizer.js");
        return finalizeVerifiedAgentTask({ app, userId: job.data.userId, runId: job.data.runId });
      }
      if (job.data.action === "expire") {
        const { expireAgentRunWait } = await import("./agent-engine.js");
        return expireAgentRunWait({ app, userId: job.data.userId, runId: job.data.runId });
      }
      const result = await executeAgentRun({
        app,
        userId: job.data.userId,
        runId: job.data.runId,
        workload: job.data.workload,
        allowStateWrites: true,
        allowSideEffects: job.data.allowSideEffects === true,
        approvedStepId: job.data.approvedStepId,
        leaseOwner: `bullmq:${job.id ?? job.data.runId}`,
      });
      if (result.state === "waiting_evidence") {
        const { attemptAgentReplan } = await import("./agent-planner.js");
        await attemptAgentReplan({
          app,
          userId: job.data.userId,
          runId: job.data.runId,
          workload: job.data.workload,
        }).catch(() => false);
        const latest = await (await import("./agent-engine-repository.js"))
          .agentEngineRepository(app)
          .loadRun(job.data.userId, job.data.runId);
        if (latest.run.state === "blocked") {
          await enqueueAgentRun(app, { ...job.data, action: "finalize", revision: latest.run.revision });
        }
      }
      if (result.state === "completed" || result.state === "blocked") {
        await enqueueAgentRun(app, {
          ...job.data,
          action: "finalize",
          revision: job.data.revision,
        });
      }
      return result;
    },
    {
      connection: connection(app.config.REDIS_URL) as never,
      concurrency: getAgentEngineQueueLimits(app).globalConcurrency,
      lockDuration: 120_000,
    },
  );
  await worker.waitUntilReady();
  worker.on("failed", (job, error) => {
    app.log.warn({ runId: job?.data.runId, errorCode: error.name }, "agent engine job failed");
  });
  worker.on("error", (error) => {
    app.log.error({ errorCode: error.name }, "agent engine worker error");
  });
  workers.set(app, worker);
  app.addHook("onClose", async () => {
    workers.delete(app);
    await worker.close().catch(() => undefined);
  });
}
