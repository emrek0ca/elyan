import { and, desc, eq, inArray, isNull, sql } from "drizzle-orm";
import type { FastifyInstance, FastifyPluginAsync } from "fastify";
import { forbidden } from "../../lib/errors.js";
import { users, runtimeConnections, tasks, taskEvents } from "../../db/schema.js";
import { getReadiness } from "../health/service.js";
import { activeTaskStatuses } from "../tasks/queue.js";

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
      },
      recentSafeEventCodes: recentErrorRows.map((row) => ({
        code: row.status,
        count: Number(row.count),
      })),
      timestamp: new Date().toISOString(),
    };
  });
};
