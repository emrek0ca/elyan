#!/usr/bin/env node
import { performance } from "node:perf_hooks";
import { DelayedError, Queue, Worker } from "bullmq";
import Fastify from "fastify";
import IORedis from "ioredis";

const redisUrl =
  process.env.ELYAN_CHAT_TEST_REDIS_URL ?? "redis://127.0.0.1:6379";
const runId = `${process.pid}-${Date.now()}`;
const prefix = `elyan-chat-load-${runId}`;
const primaryName = "elyan-chat-primary-v1";
const fallbackName = "elyan-chat-fallback-v1";
const connectionUrl = new URL(redisUrl);
const connection = {
  host: connectionUrl.hostname,
  port: Number(connectionUrl.port || 6379),
  ...(connectionUrl.username
    ? { username: decodeURIComponent(connectionUrl.username) }
    : {}),
  ...(connectionUrl.password
    ? { password: decodeURIComponent(connectionUrl.password) }
    : {}),
  ...(connectionUrl.pathname.length > 1
    ? { db: Number(connectionUrl.pathname.slice(1)) }
    : {}),
  maxRetriesPerRequest: null,
};
const redis = new IORedis(redisUrl, {
  enableOfflineQueue: false,
  lazyConnect: true,
  maxRetriesPerRequest: null,
});

let primaryQueue;
let fallbackQueue;
let workers = [];
let crashWorker;
let acceptanceApi;
const scenarios = new Map();
const attempts = new Map();
const attemptTimes = new Map();
const finalCounts = new Map();
const usageCounts = new Map();
const fallbackTasks = new Set();
const canceledTasks = new Set();
const observedCanceledTasks = new Set();
const activeByStage = { primary: 0, fallback: 0 };
const maxActiveByStage = { primary: 0, fallback: 0 };
const activeByUser = new Map();
let maxActivePerUser = 0;
const activeByReplica = [0, 0];
const maxActiveByReplica = [0, 0];
let activeCrashClaims = 0;

function createConcurrencyGate(limit) {
  let active = 0;
  const waiting = [];
  return async (operation) => {
    await new Promise((resolve) => {
      const start = () => {
        active += 1;
        resolve();
      };
      if (active < limit) start();
      else waiting.push(start);
    });
    try {
      return await operation();
    } finally {
      active -= 1;
      waiting.shift()?.();
    }
  };
}

const replicaGates = [createConcurrencyGate(4), createConcurrencyGate(4)];

function queueOptions() {
  return {
    connection,
    prefix,
    defaultJobOptions: {
      attempts: 1,
      removeOnComplete: false,
      removeOnFail: false,
    },
  };
}

async function openQueues() {
  primaryQueue = new Queue(primaryName, queueOptions());
  fallbackQueue = new Queue(fallbackName, queueOptions());
  await Promise.all([
    primaryQueue.waitUntilReady(),
    fallbackQueue.waitUntilReady(),
    primaryQueue.setGlobalConcurrency(6),
    fallbackQueue.setGlobalConcurrency(4),
  ]);
}

function jobId(stage, taskId) {
  return `chat-${stage}-${taskId}`.replace(/[^a-zA-Z0-9_-]+/g, "-");
}

async function addJob(queue, stage, data) {
  const keys = Object.keys(data).sort();
  if (keys.join(",") !== "taskId,userId") {
    throw new Error("queue job payload contains data beyond taskId and userId");
  }
  return queue.add("generate", data, {
    jobId: jobId(stage, data.taskId),
  });
}

function lockKey(userId) {
  return `${prefix}:user-lock:${userId}`;
}

async function acquireUserLock(userId, owner) {
  return (
    (await redis.set(lockKey(userId), owner, "PX", 5_000, "NX")) === "OK"
  );
}

async function releaseUserLock(userId, owner) {
  await redis.eval(
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
    1,
    lockKey(userId),
    owner,
  );
}

function recordAttempt(taskId) {
  attempts.set(taskId, (attempts.get(taskId) ?? 0) + 1);
  const times = attemptTimes.get(taskId) ?? [];
  times.push(performance.now());
  attemptTimes.set(taskId, times);
}

function recordFinal(taskId) {
  finalCounts.set(taskId, (finalCounts.get(taskId) ?? 0) + 1);
  usageCounts.set(taskId, (usageCounts.get(taskId) ?? 0) + 1);
}

async function processJob(stage, worker, job, token) {
  const { taskId, userId } = job.data;
  if (canceledTasks.has(taskId)) {
    observedCanceledTasks.add(taskId);
    return;
  }

  const owner = `${stage}-${taskId}-${job.attemptsStarted}`;
  if (!(await acquireUserLock(userId, owner))) {
    await job.moveToDelayed(Date.now() + 25, token);
    throw new DelayedError();
  }

  activeByStage[stage] += 1;
  maxActiveByStage[stage] = Math.max(
    maxActiveByStage[stage],
    activeByStage[stage],
  );
  const userActive = (activeByUser.get(userId) ?? 0) + 1;
  activeByUser.set(userId, userActive);
  maxActivePerUser = Math.max(maxActivePerUser, userActive);

  try {
    if (canceledTasks.has(taskId)) {
      observedCanceledTasks.add(taskId);
      return;
    }
    recordAttempt(taskId);
    const scenario = scenarios.get(taskId) ?? "success";

    if (stage === "primary" && scenario === "rate_limit_once") {
      if ((attempts.get(taskId) ?? 0) === 1) {
        await worker.rateLimit(120);
        throw Worker.RateLimitError();
      }
    }
    if (
      stage === "primary" &&
      ["http_500", "timeout", "malformed"].includes(scenario)
    ) {
      fallbackTasks.add(taskId);
      await addJob(fallbackQueue, "fallback", { taskId, userId });
      return;
    }

    // Keep fake fallback calls alive long enough to deterministically exercise
    // all four global slots even on a fast local Redis/Mac runner.
    await new Promise((resolve) =>
      setTimeout(resolve, stage === "fallback" ? 50 : 12),
    );
    if (canceledTasks.has(taskId)) {
      observedCanceledTasks.add(taskId);
      return;
    }
    recordFinal(taskId);
  } finally {
    activeByStage[stage] -= 1;
    activeByUser.set(userId, (activeByUser.get(userId) ?? 1) - 1);
    await releaseUserLock(userId, owner);
  }
}

async function startWorkers() {
  for (const stage of ["primary", "fallback"]) {
    const name = stage === "primary" ? primaryName : fallbackName;
    for (let replica = 0; replica < 2; replica += 1) {
      let worker;
      worker = new Worker(
        name,
        (job, token) =>
          replicaGates[replica](async () => {
            activeByReplica[replica] += 1;
            maxActiveByReplica[replica] = Math.max(
              maxActiveByReplica[replica],
              activeByReplica[replica],
            );
            try {
              return await processJob(stage, worker, job, token);
            } finally {
              activeByReplica[replica] -= 1;
            }
          }),
        {
          connection,
          prefix,
          concurrency: 4,
          lockDuration: 5_000,
          stalledInterval: 1_000,
        },
      );
      workers.push(worker);
    }
  }
  await Promise.all(workers.map((worker) => worker.waitUntilReady()));
}

async function stopWorkers() {
  const closing = workers;
  workers = [];
  await Promise.all(closing.map((worker) => worker.close()));
}

async function waitFor(predicate, label, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`timed out waiting for ${label}`);
}

function percentile(values, percent) {
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.max(
    0,
    Math.min(sorted.length - 1, Math.ceil((percent / 100) * sorted.length) - 1),
  );
  return sorted[index] ?? null;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

let exitCode = 0;
try {
  await redis.connect();
  await redis.ping();
  await openQueues();
  acceptanceApi = Fastify({ logger: false });
  acceptanceApi.post("/v1/chat/messages", async (request, reply) => {
    const body = request.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return reply.status(400).send({ accepted: false });
    }
    const { taskId, userId } = body;
    if (typeof taskId !== "string" || typeof userId !== "string") {
      return reply.status(400).send({ accepted: false });
    }
    await addJob(primaryQueue, "primary", { taskId, userId });
    return reply.status(202).send({ accepted: true, taskId });
  });
  await acceptanceApi.ready();

  const acceptanceLatencies = [];
  const initialJobs = Array.from({ length: 100 }, (_, index) => ({
    taskId: `load-${index}`,
    userId: `user-${index}`,
  }));
  scenarios.set("load-0", "rate_limit_once");
  for (let index = 1; index <= 6; index += 1) {
    scenarios.set(
      `load-${index}`,
      ["http_500", "timeout", "malformed"][(index - 1) % 3],
    );
  }

  await Promise.all(
    initialJobs.map(async (data) => {
      const startedAt = performance.now();
      const response = await acceptanceApi.inject({
        method: "POST",
        url: "/v1/chat/messages",
        payload: data,
      });
      assert(response.statusCode === 202, "acceptance API rejected a load job");
      acceptanceLatencies.push(performance.now() - startedAt);
    }),
  );
  await addJob(primaryQueue, "primary", initialJobs[0]);
  const beforeWorkers = await primaryQueue.getJobCounts("waiting");
  assert(beforeWorkers.waiting === 100, "idempotent job ID admitted a duplicate");

  const fairnessJobs = Array.from({ length: 4 }, (_, index) => ({
    taskId: `fair-${index}`,
    userId: "fair-user",
  }));
  await Promise.all(
    fairnessJobs.map((data) => addJob(primaryQueue, "primary", data)),
  );
  canceledTasks.add("cancel-1");
  await addJob(primaryQueue, "primary", {
    taskId: "cancel-1",
    userId: "cancel-user",
  });

  await startWorkers();
  await waitFor(
    () => finalCounts.size === 104 && observedCanceledTasks.has("cancel-1"),
    "initial completions, fallback and cancellation",
  );
  await stopWorkers();

  const activeCrashClaimed = new Promise((resolve) => {
    crashWorker = new Worker(
      primaryName,
      async (job) => {
        if (job.data.taskId === "active-crash-1") {
          activeCrashClaims += 1;
          resolve();
          await new Promise(() => undefined);
        }
      },
      {
        connection,
        prefix,
        concurrency: 1,
        lockDuration: 1_000,
        stalledInterval: 500,
      },
    );
    crashWorker.on("error", () => undefined);
  });
  await crashWorker.waitUntilReady();
  await addJob(primaryQueue, "primary", {
    taskId: "active-crash-1",
    userId: "active-crash-user",
  });
  await activeCrashClaimed;
  await crashWorker.close(true);
  crashWorker = undefined;

  const restartJobs = Array.from({ length: 10 }, (_, index) => ({
    taskId: `restart-${index}`,
    userId: `restart-user-${index}`,
  }));
  await Promise.all(
    restartJobs.map((data) => addJob(primaryQueue, "primary", data)),
  );
  await Promise.all([primaryQueue.close(), fallbackQueue.close()]);
  await openQueues();
  await startWorkers();
  await waitFor(
    () => finalCounts.size === 115,
    "worker restart and active-crash recovery completions",
    30_000,
  );

  const duplicateFinals = [...finalCounts.values()].filter(
    (count) => count !== 1,
  ).length;
  const duplicateUsage = [...usageCounts.values()].filter(
    (count) => count !== 1,
  ).length;
  const rateLimitTimes = attemptTimes.get("load-0") ?? [];
  const retryAfterObservedMs =
    rateLimitTimes.length >= 2 ? rateLimitTimes[1] - rateLimitTimes[0] : 0;
  const p95AcceptanceMs = percentile(acceptanceLatencies, 95);

  assert(finalCounts.size === 115, "not all non-canceled jobs completed");
  assert(duplicateFinals === 0, "duplicate final result detected");
  assert(duplicateUsage === 0, "duplicate usage record detected");
  assert(maxActiveByStage.primary <= 6, "primary global concurrency exceeded");
  assert(maxActiveByStage.fallback <= 4, "fallback global concurrency exceeded");
  assert(maxActivePerUser <= 1, "per-user active concurrency exceeded");
  assert(
    maxActiveByReplica.every((value) => value <= 4),
    "per-replica local concurrency exceeded",
  );
  assert(fallbackTasks.size === 6, "provider fallback scenarios were not preserved");
  assert(maxActiveByStage.fallback === 4, "fallback global concurrency was not exercised");
  assert(retryAfterObservedMs >= 100, "Retry-After delay was not respected");
  assert(observedCanceledTasks.has("cancel-1"), "cancellation was not observed");
  assert(activeCrashClaims === 1, "active worker crash was not exercised once");
  assert(
    finalCounts.get("active-crash-1") === 1,
    "active worker crash did not recover to one final result",
  );
  assert(p95AcceptanceMs != null && p95AcceptanceMs < 500, "accept P95 exceeded 500ms");

  console.log(
    JSON.stringify(
      {
        acceptedConcurrentUsers: 100,
        acceptLatencyMs: {
          p95: Number(p95AcceptanceMs.toFixed(2)),
          max: Number(Math.max(...acceptanceLatencies).toFixed(2)),
        },
        primaryMaxActive: maxActiveByStage.primary,
        fallbackMaxActive: maxActiveByStage.fallback,
        perReplicaMaxActive: maxActiveByReplica,
        perUserMaxActive: maxActivePerUser,
        retryAfterObservedMs: Number(retryAfterObservedMs.toFixed(2)),
        fallbackScenarios: fallbackTasks.size,
        canceled: observedCanceledTasks.size,
        completedAfterWorkerRestart: restartJobs.length,
        completedAfterActiveWorkerCrash: 1,
        duplicateFinals,
        duplicateUsage,
        status: "PASS",
      },
      null,
      2,
    ),
  );
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  exitCode = 1;
} finally {
  await crashWorker?.close(true).catch(() => undefined);
  await stopWorkers().catch(() => undefined);
  await acceptanceApi?.close().catch(() => undefined);
  if (primaryQueue && fallbackQueue) {
    await Promise.all([
      primaryQueue.obliterate({ force: true }).catch(() => undefined),
      fallbackQueue.obliterate({ force: true }).catch(() => undefined),
    ]);
    await Promise.all([
      primaryQueue.close().catch(() => undefined),
      fallbackQueue.close().catch(() => undefined),
    ]);
  }
  await redis.quit().catch(() => redis.disconnect());
}

process.exit(exitCode);
