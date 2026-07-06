import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { and, eq, inArray } from "drizzle-orm";
import { taskEvents, tasks } from "../../db/schema.js";
import { shapeTaskFeedItem } from "../tasks/service-helpers.js";
import { agentEngineRepository } from "./agent-engine-repository.js";
import { agentPlanEnvelopeSchema, agentVerificationSchema, hardenAgentPlanVerification, type AgentPlanEnvelope } from "./agent-plan.js";
import { canCompleteAgentRun, verifyAgentStep, type AgentEvidenceInput } from "./agent-verifier.js";
import { executeAgentTool, getAgentToolMetadata, type AgentToolContext, type AgentToolResult } from "./tool-registry.js";
import { updateGoal } from "../goals/service.js";

const TERMINAL_RUN_STATES = new Set(["completed", "blocked", "failed", "canceled"]);

export async function blockAgentRun(input: {
  app: FastifyInstance;
  userId: string;
  runId: string;
  failureCode: string;
  eventType: string;
}): Promise<boolean> {
  const repository = agentEngineRepository(input.app);
  const snapshot = await repository.loadRun(input.userId, input.runId);
  if (TERMINAL_RUN_STATES.has(snapshot.run.state)) return snapshot.run.state === "blocked";
  await repository.transitionRun({
    userId: input.userId,
    runId: input.runId,
    expectedRevision: snapshot.run.revision,
    to: "blocked",
    eventType: input.eventType,
    failureCode: input.failureCode,
  });
  const rows = await input.app.db.update(tasks).set({
    status: "failed",
    summary: "Görev doğrulama veya yürütme sınırları içinde tamamlanamadı.",
    error: input.failureCode,
    queuePosition: 0,
    completedAt: new Date(),
    updatedAt: new Date(),
  }).where(and(
    eq(tasks.id, snapshot.run.taskId), eq(tasks.userId, input.userId),
    inArray(tasks.status, ["planning", "running", "waiting_approval"]),
  )).returning();
  const task = rows[0];
  if (task) {
    await input.app.db.insert(taskEvents).values({
      taskId: task.id, status: "failed", message: task.summary,
      payload: { agentRunId: snapshot.run.id, errorCode: input.failureCode },
    });
    await input.app.services.eventBus.publish({
      topic: "task.updated", userId: task.userId, deviceId: task.targetDeviceId, taskId: task.id,
      payload: { task: shapeTaskFeedItem(task), agentEngine: { state: "blocked", errorCode: input.failureCode } },
    });
  }
  return true;
}

async function projectAgentWaitToTask(input: {
  app: FastifyInstance;
  userId: string;
  taskId: string;
  kind: "approval" | "evidence";
  stepCount: number;
  stepIds?: string[];
}): Promise<void> {
  const now = new Date();
  const status = input.kind === "approval" ? "waiting_approval" : "running";
  const summary = input.kind === "approval" ? "Onay bekleniyor." : "Doğrulama kanıtı bekleniyor.";
  const approvalRequest = input.kind === "approval"
    ? { source: "agent_engine_v2", reason: "side_effect", stepCount: input.stepCount, stepIds: input.stepIds ?? [] }
    : undefined;
  const rows = await input.app.db.update(tasks).set({
    status,
    summary,
    ...(approvalRequest ? { approvalRequest } : {}),
    updatedAt: now,
  }).where(and(
    eq(tasks.id, input.taskId), eq(tasks.userId, input.userId),
    inArray(tasks.status, ["planning", "running", "waiting_approval"]),
  )).returning();
  const task = rows[0];
  if (!task) return;
  await input.app.db.insert(taskEvents).values({
    taskId: task.id,
    status,
    message: summary,
    payload: { agentEngine: true, waitKind: input.kind, stepCount: input.stepCount },
  });
  await input.app.services.eventBus.publish({
    topic: "task.updated",
    userId: task.userId,
    deviceId: task.targetDeviceId,
    taskId: task.id,
    payload: { task: shapeTaskFeedItem(task), agentEngine: { state: input.kind === "approval" ? "waiting_approval" : "waiting_evidence" } },
  });
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function dependencyReady(step: { dependsOn: unknown }, verifiedKeys: Set<string>): boolean {
  const dependencies = Array.isArray(step.dependsOn) ? step.dependsOn.map(String) : [];
  return dependencies.every((key) => verifiedKeys.has(key));
}

export function isSideEffectApprovedForStep(input: {
  allowSideEffects?: boolean;
  approvedStepId?: string;
  stepId: string;
}): boolean {
  return input.allowSideEffects === true && input.approvedStepId === input.stepId;
}

function toolEvidence(result: AgentToolResult): AgentEvidenceInput {
  return {
    kind: "tool_result",
    sourceRef: result.tool,
    payload: {
      tool: result.tool,
      ok: result.ok,
      permission: result.permission,
      output: result.output,
      error: result.error,
      durationMs: result.durationMs,
    },
    valid: result.ok,
  };
}

function deriveEvidence(result: AgentToolResult): AgentEvidenceInput[] {
  const evidence: AgentEvidenceInput[] = [toolEvidence(result)];
  if (!result.ok || !result.output) return evidence;
  if (result.permission === "write" || result.permission === "side_effect") {
    evidence.push({
      kind: "state_readback",
      sourceRef: result.tool,
      payload: result.output,
      valid: true,
    });
  }
  const artifacts = Array.isArray(result.output.artifacts) ? result.output.artifacts : [];
  for (const value of artifacts.slice(0, 20)) {
    if (!value || typeof value !== "object" || Array.isArray(value)) continue;
    const artifact = value as Record<string, unknown>;
    const id = typeof artifact.id === "string" ? artifact.id : null;
    const contentHash = typeof artifact.contentHash === "string" ? artifact.contentHash : null;
    if (!id || !contentHash) continue;
    evidence.push({
      kind: "artifact",
      sourceRef: id,
      contentHash,
      payload: { id, contentHash, contentType: artifact.contentType ?? null },
      valid: true,
    });
  }
  return evidence;
}

export async function createAgentRun(input: {
  app: FastifyInstance;
  userId: string;
  taskId: string;
  sessionId?: string | null;
  goalId?: string | null;
  plan: AgentPlanEnvelope;
  shadow?: boolean;
}) {
  const repository = agentEngineRepository(input.app);
  const existing = await repository.findRunByTask(input.userId, input.taskId);
  if (existing) {
    const nextPlan = hardenAgentPlanVerification(agentPlanEnvelopeSchema.parse(input.plan));
    if (
      existing.run.state === "waiting_evidence" &&
      JSON.stringify(existing.plan) !== JSON.stringify(nextPlan) &&
      existing.run.replanCount < existing.run.maxReplans
    ) {
      return repository.applyReplan({
        userId: input.userId,
        runId: existing.run.id,
        expectedRevision: existing.run.revision,
        plan: nextPlan,
      });
    }
    if (
      existing.run.state === "waiting_evidence" &&
      JSON.stringify(existing.plan) !== JSON.stringify(nextPlan) &&
      existing.run.replanCount >= existing.run.maxReplans
    ) {
      await blockAgentRun({
        app: input.app, userId: input.userId, runId: existing.run.id,
        eventType: "agent.replan_budget_exhausted", failureCode: "replan_budget_exhausted",
      });
      return repository.loadRun(input.userId, existing.run.id);
    }
    return existing;
  }
  return repository.createRun({
    userId: input.userId,
    taskId: input.taskId,
    sessionId: input.sessionId,
    goalId: input.goalId,
    plan: hardenAgentPlanVerification(agentPlanEnvelopeSchema.parse(input.plan)),
    shadow: input.shadow,
  });
}

async function moveRun(
  app: FastifyInstance,
  userId: string,
  runId: string,
  to: Parameters<ReturnType<typeof agentEngineRepository>["transitionRun"]>[0]["to"],
  eventType: string,
  payload?: Record<string, unknown>,
) {
  const repository = agentEngineRepository(app);
  const snapshot = await repository.loadRun(userId, runId);
  return repository.transitionRun({
    userId, runId, expectedRevision: snapshot.run.revision, to, eventType, payload,
  });
}

async function executeStep(input: {
  app: FastifyInstance;
  userId: string;
  runId: string;
  step: Awaited<ReturnType<ReturnType<typeof agentEngineRepository>["loadRun"]>>["steps"][number];
  planStep: AgentPlanEnvelope["steps"][number];
  context: AgentToolContext;
}) {
  const repository = agentEngineRepository(input.app);
  const metadata = getAgentToolMetadata(input.planStep.tool_request.tool);
  if (!metadata) {
    await repository.transitionStep({ userId: input.userId, stepId: input.step.id, to: "executing", incrementAttempt: true });
    const result = await executeAgentTool(input.app, input.context, input.planStep.tool_request);
    await repository.transitionStep({ userId: input.userId, stepId: input.step.id, to: "failed", toolResult: result });
    return { verification: null, waitingApproval: false };
  }
  if (metadata.permission === "side_effect" && input.context.allowSideEffects !== true) {
    await repository.transitionStep({ userId: input.userId, stepId: input.step.id, to: "executing", incrementAttempt: false });
    await repository.transitionStep({ userId: input.userId, stepId: input.step.id, to: "waiting_approval" });
    return { verification: null, waitingApproval: true };
  }

  await repository.transitionStep({ userId: input.userId, stepId: input.step.id, to: "executing", incrementAttempt: true });
  const result = await executeAgentTool(input.app, input.context, input.planStep.tool_request);
  await repository.incrementToolCalls(input.userId, input.runId, 1);
  await repository.transitionStep({ userId: input.userId, stepId: input.step.id, to: "observed", toolResult: result });
  const storedEvidence = await repository.recordEvidence({
    userId: input.userId, runId: input.runId, stepId: input.step.id, evidence: deriveEvidence(result),
  });
  const verification = verifyAgentStep({
    step: input.planStep,
    evidence: storedEvidence.map((item) => ({
      id: item.id,
      kind: item.kind as AgentEvidenceInput["kind"],
      sourceRef: item.sourceRef,
      contentHash: item.contentHash,
      payload: asRecord(item.payload),
      valid: item.valid,
    })),
  });
  const canRetry =
    !verification.passed &&
    input.step.attempt + 1 < input.step.maxAttempts &&
    metadata.idempotency === "read_only";
  if (canRetry) {
    await repository.transitionStep({
      userId: input.userId,
      stepId: input.step.id,
      to: "failed",
      verification,
    });
    await repository.transitionStep({ userId: input.userId, stepId: input.step.id, to: "ready" });
    return { verification, waitingApproval: false, retryReady: true };
  }
  await repository.transitionStep({
    userId: input.userId,
    stepId: input.step.id,
    to: verification.passed ? "verified" : "waiting_evidence",
    verification,
  });
  return { verification, waitingApproval: false, retryReady: false };
}

export async function executeAgentRun(input: {
  app: FastifyInstance;
  userId: string;
  runId: string;
  workload: AgentToolContext["workload"];
  allowStateWrites?: boolean;
  allowSideEffects?: boolean;
  approvedStepId?: string;
  leaseOwner?: string;
}) {
  const repository = agentEngineRepository(input.app);
  const leaseOwner = input.leaseOwner ?? `agent:${randomUUID()}`;
  const claimed = await repository.claimRun({ userId: input.userId, runId: input.runId, leaseOwner });
  if (!claimed) return { claimed: false, state: (await repository.loadRun(input.userId, input.runId)).run.state };
  const startedAt = Date.now();
  try {
    let snapshot = await repository.loadRun(input.userId, input.runId);
    if (TERMINAL_RUN_STATES.has(snapshot.run.state)) return { claimed: true, state: snapshot.run.state };
    if (snapshot.run.shadow) return { claimed: true, state: snapshot.run.state, shadow: true };
    if (snapshot.run.activeComputeMs >= snapshot.run.activeComputeBudgetMs) {
      await blockAgentRun({
        app: input.app, userId: input.userId, runId: input.runId,
        eventType: "agent.budget_exhausted", failureCode: "active_compute_budget_exhausted",
      });
      return { claimed: true, state: "blocked" };
    }
    if (snapshot.run.state === "ready") await moveRun(input.app, input.userId, input.runId, "executing", "agent.execution_started");

    snapshot = await repository.loadRun(input.userId, input.runId);
    const verifiedKeys = new Set(snapshot.steps.filter((step) => step.state === "verified").map((step) => step.stepKey));
    const runnable = snapshot.steps.filter((step) =>
      ["ready", "pending"].includes(step.state) && dependencyReady(step, verifiedKeys),
    );
    for (const step of runnable.filter((item) => item.state === "pending")) {
      await repository.transitionStep({ userId: input.userId, stepId: step.id, to: "ready" });
      step.state = "ready";
    }
    const availableCalls = Math.max(0, snapshot.run.maxToolCalls - snapshot.run.toolCallCount);
    const selected = runnable.slice(0, availableCalls);
    const readSteps = selected.filter((step) => getAgentToolMetadata(asRecord(step.toolRequest).tool as string)?.parallelSafe);
    const serialSteps = selected.filter((step) => !readSteps.includes(step));
    const baseContext: AgentToolContext = {
      userId: input.userId,
      sessionId: snapshot.run.sessionId,
      workload: input.workload,
      allowStateWrites: input.allowStateWrites ?? true,
      allowSideEffects: false,
    };
    const results = await Promise.all(readSteps.map((step) => executeStep({
      app: input.app, userId: input.userId, runId: input.runId, step,
      planStep: snapshot.plan.steps.find((item) => item.id === step.stepKey)!,
      context: { ...baseContext, allowSideEffects: isSideEffectApprovedForStep({ ...input, stepId: step.id }) },
    })));
    for (const step of serialSteps) {
      results.push(await executeStep({
        app: input.app, userId: input.userId, runId: input.runId, step,
        planStep: snapshot.plan.steps.find((item) => item.id === step.stepKey)!,
        context: { ...baseContext, allowSideEffects: isSideEffectApprovedForStep({ ...input, stepId: step.id }) },
      }));
      if (results.at(-1)?.waitingApproval) break;
    }

    snapshot = await repository.loadRun(input.userId, input.runId);
    await moveRun(input.app, input.userId, input.runId, "observing", "agent.observed", { executedSteps: selected.length });
    await moveRun(input.app, input.userId, input.runId, "verifying", "agent.verification_started");
    snapshot = await repository.loadRun(input.userId, input.runId);
    const verifications = snapshot.steps
      .map((step) => agentVerificationSchema.safeParse(step.verification))
      .filter((result) => result.success)
      .map((result) => result.data);
    const activeSteps = snapshot.steps.filter((step) => step.state !== "skipped");
    const allVerified = activeSteps.length > 0 && activeSteps.every((step) => step.state === "verified");
    if (allVerified && canCompleteAgentRun(verifications)) {
      await repository.transitionRun({
        userId: input.userId, runId: input.runId, expectedRevision: snapshot.run.revision,
        to: "completed", eventType: "agent.completed",
        terminalResult: { verifiedStepCount: verifications.length, evidenceBacked: true },
        computeMs: Date.now() - startedAt,
      });
      if (snapshot.run.goalId) {
        await updateGoal(input.app, {
          userId: input.userId,
          goalId: snapshot.run.goalId,
          status: "done",
        }).catch((error) => {
          input.app.log.warn?.(
            { runId: input.runId, goalId: snapshot.run.goalId, errorCode: error instanceof Error ? error.name : "goal_update_failed" },
            "verified agent run could not project completion to goal",
          );
        });
      }
      return { claimed: true, state: "completed", verification: verifications };
    }
    const nowVerifiedKeys = new Set(snapshot.steps.filter((step) => step.state === "verified").map((step) => step.stepKey));
    const hasNextWave = snapshot.steps.some((step) =>
      step.state === "ready" || (step.state === "pending" && dependencyReady(step, nowVerifiedKeys)),
    );
    if (hasNextWave) {
      const readyRun = await repository.transitionRun({
        userId: input.userId, runId: input.runId, expectedRevision: snapshot.run.revision,
        to: "ready", eventType: "agent.next_wave_ready",
        payload: { verifiedStepCount: nowVerifiedKeys.size },
        computeMs: Date.now() - startedAt,
      });
      const { enqueueAgentRun } = await import("./agent-engine-queue.js");
      await enqueueAgentRun(input.app, {
        runId: readyRun.id,
        userId: input.userId,
        revision: readyRun.revision,
        workload: input.workload,
        allowSideEffects: input.allowSideEffects,
      });
      return { claimed: true, state: "ready", verification: verifications };
    }
    if (snapshot.steps.some((step) => step.state === "waiting_approval")) {
      const waitingStepCount = snapshot.steps.filter((step) => step.state === "waiting_approval").length;
      const waitingRun = await repository.transitionRun({
        userId: input.userId, runId: input.runId, expectedRevision: snapshot.run.revision,
        to: "waiting_approval", eventType: "agent.waiting_approval",
        payload: { waitingStepCount },
        computeMs: Date.now() - startedAt,
      });
      await projectAgentWaitToTask({
        app: input.app, userId: input.userId, taskId: snapshot.run.taskId,
        kind: "approval", stepCount: waitingStepCount,
        stepIds: snapshot.steps.filter((step) => step.state === "waiting_approval").map((step) => step.id),
      });
      const { enqueueAgentRun } = await import("./agent-engine-queue.js");
      await enqueueAgentRun(input.app, {
        action: "expire", runId: waitingRun.id, userId: input.userId,
        revision: waitingRun.revision, workload: input.workload,
      });
      return { claimed: true, state: "waiting_approval" };
    }
    if (snapshot.run.toolCallCount >= snapshot.run.maxToolCalls) {
      await blockAgentRun({
        app: input.app, userId: input.userId, runId: input.runId,
        eventType: "agent.tool_budget_exhausted", failureCode: "tool_call_budget_exhausted",
      });
      return { claimed: true, state: "blocked", verification: verifications };
    }
    const waitingRun = await repository.transitionRun({
      userId: input.userId, runId: input.runId, expectedRevision: snapshot.run.revision,
      to: "waiting_evidence", eventType: "agent.waiting_evidence",
      payload: { missingStepCount: snapshot.steps.filter((step) => step.state !== "verified").length },
      computeMs: Date.now() - startedAt,
    });
    await projectAgentWaitToTask({
      app: input.app, userId: input.userId, taskId: snapshot.run.taskId,
      kind: "evidence", stepCount: snapshot.steps.filter((step) => step.state !== "verified").length,
    });
    const { enqueueAgentRun } = await import("./agent-engine-queue.js");
    await enqueueAgentRun(input.app, {
      action: "expire", runId: waitingRun.id, userId: input.userId,
      revision: waitingRun.revision, workload: input.workload,
    });
    return { claimed: true, state: "waiting_evidence", verification: verifications };
  } finally {
    await repository.releaseRun(input.userId, input.runId, leaseOwner).catch(() => undefined);
  }
}

export async function applyAgentReplan(input: {
  app: FastifyInstance;
  userId: string;
  runId: string;
  plan: AgentPlanEnvelope;
  workload: AgentToolContext["workload"];
}): Promise<boolean> {
  const repository = agentEngineRepository(input.app);
  const snapshot = await repository.loadRun(input.userId, input.runId);
  const replanned = await repository.applyReplan({
    userId: input.userId,
    runId: input.runId,
    expectedRevision: snapshot.run.revision,
    plan: hardenAgentPlanVerification(input.plan),
  });
  const { enqueueAgentRun } = await import("./agent-engine-queue.js");
  return enqueueAgentRun(input.app, {
    runId: replanned.run.id,
    userId: input.userId,
    revision: replanned.run.revision,
    workload: input.workload,
  });
}

export async function resumeAgentRunAfterApproval(input: {
  app: FastifyInstance;
  userId: string;
  taskId: string;
  workload?: AgentToolContext["workload"];
}): Promise<boolean> {
  const repository = agentEngineRepository(input.app);
  const snapshot = await repository.findRunByTask(input.userId, input.taskId);
  if (!snapshot || snapshot.run.state !== "waiting_approval") return false;
  const waiting = snapshot.steps.filter((item) => item.state === "waiting_approval");
  for (const step of waiting) {
    await repository.transitionStep({ userId: input.userId, stepId: step.id, to: "ready" });
  }
  const run = await repository.transitionRun({
    userId: input.userId,
    runId: snapshot.run.id,
    expectedRevision: snapshot.run.revision,
    to: "ready",
    eventType: "agent.approval_granted",
    payload: { resumedStepCount: waiting.length },
  });
  const { enqueueAgentRun } = await import("./agent-engine-queue.js");
  return enqueueAgentRun(input.app, {
    runId: run.id,
    userId: input.userId,
    revision: run.revision,
    workload: input.workload ?? "planning",
    allowSideEffects: true,
    approvedStepId: waiting[0]?.id,
  });
}

export async function cancelAgentRunForTask(input: {
  app: FastifyInstance;
  userId: string;
  taskId: string;
}): Promise<boolean> {
  const repository = agentEngineRepository(input.app);
  const snapshot = await repository.findRunByTask(input.userId, input.taskId);
  if (!snapshot || TERMINAL_RUN_STATES.has(snapshot.run.state)) return false;
  for (const step of snapshot.steps.filter((item) => !["verified", "failed", "skipped", "canceled"].includes(item.state))) {
    await repository.transitionStep({ userId: input.userId, stepId: step.id, to: "canceled" }).catch(() => undefined);
  }
  await repository.transitionRun({
    userId: input.userId,
    runId: snapshot.run.id,
    expectedRevision: snapshot.run.revision,
    to: "canceled",
    eventType: "agent.canceled",
    failureCode: "user_canceled",
  });
  return true;
}

export async function expireAgentRunWait(input: {
  app: FastifyInstance;
  userId: string;
  runId: string;
}): Promise<boolean> {
  const repository = agentEngineRepository(input.app);
  const snapshot = await repository.loadRun(input.userId, input.runId);
  if (
    !["waiting_approval", "waiting_evidence"].includes(snapshot.run.state) ||
    !snapshot.run.waitingExpiresAt ||
    snapshot.run.waitingExpiresAt.getTime() > Date.now()
  ) return false;
  await repository.transitionRun({
    userId: input.userId,
    runId: input.runId,
    expectedRevision: snapshot.run.revision,
    to: "blocked",
    eventType: "agent.wait_expired",
    failureCode: "agent_wait_expired",
  });
  const rows = await input.app.db.update(tasks).set({
    status: "failed",
    summary: "Görev gerekli onay veya doğrulama kanıtı alınamadığı için durduruldu.",
    error: "agent_wait_expired",
    queuePosition: 0,
    completedAt: new Date(),
    updatedAt: new Date(),
  }).where(and(
    eq(tasks.id, snapshot.run.taskId), eq(tasks.userId, input.userId),
    inArray(tasks.status, ["planning", "running", "waiting_approval"]),
  )).returning();
  const task = rows[0];
  if (task) {
    await input.app.db.insert(taskEvents).values({
      taskId: task.id, status: "failed", message: task.summary,
      payload: { agentRunId: snapshot.run.id, errorCode: "agent_wait_expired" },
    });
    await input.app.services.eventBus.publish({
      topic: "task.updated", userId: task.userId, deviceId: task.targetDeviceId, taskId: task.id,
      payload: { task: shapeTaskFeedItem(task), agentEngine: { state: "blocked", errorCode: "agent_wait_expired" } },
    });
  }
  return true;
}
