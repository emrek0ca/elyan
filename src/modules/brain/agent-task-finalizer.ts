import { and, eq, inArray } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { taskEvents, tasks } from "../../db/schema.js";
import { syncChatTaskLifecycle } from "../chat/task-sync.js";
import { shapeTaskFeedItem } from "../tasks/service-helpers.js";
import { agentEngineRepository } from "./agent-engine-repository.js";

export async function finalizeVerifiedAgentTask(input: {
  app: FastifyInstance;
  userId: string;
  runId: string;
}): Promise<boolean> {
  const snapshot = await agentEngineRepository(input.app).loadRun(input.userId, input.runId);
  if (snapshot.run.state !== "completed" && snapshot.run.state !== "blocked") return false;
  const original = (await input.app.db.select().from(tasks).where(and(
    eq(tasks.id, snapshot.run.taskId), eq(tasks.userId, input.userId),
  )).limit(1))[0];
  if (!original || ["completed", "failed", "canceled"].includes(original.status)) return false;
  const now = new Date();
  const completed = snapshot.run.state === "completed";
  const message = completed
    ? "Görev doğrulandı ve tamamlandı."
    : "Görev doğrulama veya yürütme sınırları içinde tamamlanamadı.";
  const rows = await input.app.db.update(tasks).set({
    status: completed ? "completed" : "failed",
    summary: message,
    error: completed ? null : snapshot.run.failureCode ?? "agent_blocked",
    result: completed ? {
      agentRunId: snapshot.run.id,
      verification: snapshot.run.terminalResult,
      evidenceBacked: true,
    } : original.result,
    queuePosition: 0,
    completedAt: now,
    updatedAt: now,
  }).where(and(
    eq(tasks.id, snapshot.run.taskId), eq(tasks.userId, input.userId),
    inArray(tasks.status, ["planning", "running", "waiting_approval"]),
  )).returning();
  const task = rows[0];
  if (!task) return false;
  await input.app.db.insert(taskEvents).values({
    taskId: task.id,
    status: completed ? "completed" : "failed",
    message,
    payload: { agentRunId: snapshot.run.id, evidenceBacked: completed, errorCode: snapshot.run.failureCode },
  });
  await input.app.services.eventBus.publish({
    topic: "task.updated",
    userId: task.userId,
    deviceId: task.targetDeviceId,
    taskId: task.id,
    payload: { task: shapeTaskFeedItem(task), agentEngine: { state: snapshot.run.state, evidenceBacked: completed } },
  });
  await syncChatTaskLifecycle(input.app, {
    originalTask: original,
    updatedTask: task,
    message,
  });
  return true;
}
