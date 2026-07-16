import { and, desc, eq, gte, inArray, isNull, sql } from "drizzle-orm";
import type { FastifyInstance, FastifyPluginAsync } from "fastify";
import { forbidden } from "../../lib/errors.js";
import { users, runtimeConnections, tasks, taskEvents } from "../../db/schema.js";
import { getReadiness } from "../health/service.js";
import { activeTaskStatuses } from "../tasks/queue.js";
import { aggregateTaskFailures, deriveTaskFailureSignature } from "../tasks/task-failure-analytics.js";
import { getSemanticComputeMetrics } from "../brain/semantic-compute-client.js";
import { getGeminiFreeBudgetSnapshot } from "../brain/gemini-free-tier-guard.js";

async function assertAdmin(app: FastifyInstance, userId: string): Promise<void> {
  const rows = await app.db.select({ role: users.role }).from(users).where(eq(users.id, userId)).limit(1);
  if (rows[0]?.role !== "admin") {
    throw forbidden("Admin access required");
  }
}

export const adminRoutes: FastifyPluginAsync = async (app) => {
  app.get("/ops/summary", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }

    await assertAdmin(app, request.auth!.sub);
    const readiness = await getReadiness(app);
    const geminiFree = await getGeminiFreeBudgetSnapshot(app);
    const taskStatusRows = await app.db
      .select({
        status: tasks.status,
        count: sql<number>`count(*)::int`,
      })
      .from(tasks)
      .groupBy(tasks.status);
    const runtimeRows = await app.db
      .select({
        status: runtimeConnections.status,
        count: sql<number>`count(*)::int`,
      })
      .from(runtimeConnections)
      .where(isNull(runtimeConnections.disconnectedAt))
      .groupBy(runtimeConnections.status);
    const activeTaskRows = await app.db
      .select({ count: sql<number>`count(*)::int` })
      .from(tasks)
      .where(inArray(tasks.status, activeTaskStatuses));
    const recentErrorRows = await app.db
      .select({
        status: taskEvents.status,
        count: sql<number>`count(*)::int`,
      })
      .from(taskEvents)
      .where(and(inArray(taskEvents.status, ["failed", "canceled"])))
      .groupBy(taskEvents.status)
      .orderBy(desc(sql<number>`count(*)::int`))
      .limit(10);

    return {
      ok: readiness.ok,
      agent: readiness.agent,
      redis: app.services.reliability.store.summary(),
      queue: {
        healthy: readiness.agent.queueHealthy,
        activeTaskCount: Number(activeTaskRows[0]?.count ?? 0),
        staleActiveTaskCount: readiness.agent.staleActiveTaskCount,
        staleBlockingTaskCount: readiness.agent.staleBlockingTaskCount,
        staleApprovalTaskCount: readiness.agent.staleApprovalTaskCount,
        byStatus: Object.fromEntries(taskStatusRows.map((row) => [row.status, Number(row.count)])),
      },
      runtime: {
        activeConnections: readiness.agent.activeRuntimeConnections,
        staleConnections: readiness.agent.staleRuntimeConnections,
        desktopReadyCount: readiness.agent.desktopReadyCount,
        desktopTaskReady: readiness.agent.desktopTaskReady,
        latestDesktopHeartbeatAgeSeconds: readiness.agent.latestDesktopHeartbeatAgeSeconds,
        byStatus: Object.fromEntries(runtimeRows.map((row) => [row.status, Number(row.count)])),
      },
      provider: {
        circuitState: readiness.agent.providerCircuitState,
        serverBrainReady: readiness.agent.serverBrainReady,
        lastChatLatencyMs: readiness.agent.lastChatLatencyMs,
        lastStreamingFirstDeltaMs: readiness.agent.lastStreamingFirstDeltaMs,
        recentTimeoutCount: readiness.agent.recentBrainTimeoutCount,
        geminiFree,
      },
      brain: {
        neuralReady: readiness.agent.neuralReady,
        trainingWorkerReady: readiness.agent.trainingWorkerReady,
        embeddingReady: readiness.agent.embeddingReady,
        evaluationReady: readiness.agent.evaluationReady,
        quantumLearningReady: readiness.agent.quantumLearningReady,
        activeTrainingJobs: readiness.agent.activeTrainingJobs,
        latestEvaluationScore: readiness.agent.latestEvaluationScore,
        latestQuantumBenchmarkScore: readiness.agent.latestQuantumBenchmarkScore,
        mlWorkerMode: readiness.agent.mlWorkerMode,
        mlWorkerLastJobAt: readiness.agent.mlWorkerLastJobAt,
        mlWorkerLastErrorCode: readiness.agent.mlWorkerLastErrorCode,
        optionalLibraries: readiness.agent.optionalLibraries,
        runnerBacklog: readiness.agent.runnerBacklog,
        blockingReasons: readiness.agent.brainBlockingReasons,
        constitutionVersion: readiness.brainControl.constitutionVersion,
        boundaryGateReady: readiness.brainControl.boundaryGateReady,
        latestBenchmarkStatus: readiness.brainControl.latestBenchmarkStatus,
        latestBenchmarkOverallScore: readiness.brainControl.latestBenchmarkOverallScore,
        latestBenchmarkBoundaryScore: readiness.brainControl.latestBenchmarkBoundaryScore,
        correctionDatasetReady: readiness.brainControl.correctionDatasetReady,
        correctionDatasetId: readiness.brainControl.correctionDatasetId,
        activeMobileDefaultProfile: readiness.brainControl.activeMobileDefaultProfile,
        latestLatencyWarning: readiness.brainControl.latestLatencyWarning,
        semanticCompute: getSemanticComputeMetrics(),
      },
      recentSafeEventCodes: recentErrorRows.map((row) => ({
        code: row.status,
        count: Number(row.count),
      })),
      timestamp: new Date().toISOString(),
    };
  });

  // Başarısız görevlerin toplu raporu: hangi hata kodu + görev tipi en çok
  // patlıyor. Kaynak-doğruluk `tasks` tablosu (feature-flag'den bağımsız);
  // ucuz kalması için result blob'u okumaz — imza task.error + payload'dan
  // türetilir (patlayan araç bu görünümde null kalabilir).
  app.get("/ops/task-failures", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) {
      return;
    }
    await assertAdmin(app, request.auth!.sub);

    const query = (request.query ?? {}) as Record<string, unknown>;
    const windowDaysRaw = Number.parseInt(String(query.windowDays ?? "7"), 10);
    const windowDays = Number.isFinite(windowDaysRaw)
      ? Math.min(Math.max(windowDaysRaw, 1), 90)
      : 7;
    const limitRaw = Number.parseInt(String(query.limit ?? "500"), 10);
    const limit = Number.isFinite(limitRaw) ? Math.min(Math.max(limitRaw, 1), 2000) : 500;
    const since = new Date(Date.now() - windowDays * 86_400_000);

    const failedRows = await app.db
      .select({
        id: tasks.id,
        error: tasks.error,
        payload: tasks.payload,
      })
      .from(tasks)
      .where(and(eq(tasks.status, "failed"), gte(tasks.updatedAt, since)))
      .orderBy(desc(tasks.updatedAt))
      .limit(limit);

    const signatures = failedRows.map((row) => ({
      taskId: row.id,
      signature: deriveTaskFailureSignature({ error: row.error, payload: row.payload }),
    }));
    const failuresByCode = aggregateTaskFailures(signatures);

    return {
      windowDays,
      sampledTaskCount: failedRows.length,
      truncated: failedRows.length >= limit,
      failuresByCode,
      timestamp: new Date().toISOString(),
    };
  });
};
