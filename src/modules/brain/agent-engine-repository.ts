import { and, asc, eq, gt, inArray, isNull, lt, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { agentEvidence, agentEvents, agentRuns, agentSteps } from "../../db/schema.js";
import { withTenantTransaction, type TenantDb } from "../../db/tenant-context.js";
import {
  agentPlanEnvelopeSchema,
  agentRunStateSchema,
  agentStepIdempotencyKey,
  agentStepStateSchema,
  agentVerificationSchema,
  type AgentPlanEnvelope,
  type AgentRunState,
  type AgentStepState,
  type AgentVerification,
} from "./agent-plan.js";
import { assertAgentRunTransition, assertAgentStepTransition } from "./agent-state-machine.js";
import type { AgentEvidenceInput } from "./agent-verifier.js";

export type AgentRunSnapshot = {
  run: typeof agentRuns.$inferSelect;
  plan: AgentPlanEnvelope;
  steps: Array<typeof agentSteps.$inferSelect>;
  evidence: Array<typeof agentEvidence.$inferSelect>;
};

function safeEventPayload(payload: Record<string, unknown> = {}): Record<string, unknown> {
  return Object.fromEntries(Object.entries(payload).filter(([key]) =>
    !["prompt", "message", "content", "toolResult", "tool_result"].includes(key),
  ));
}

export class AgentEngineRepository {
  constructor(private readonly app: FastifyInstance) {}

  async createRun(input: {
    userId: string;
    taskId: string;
    sessionId?: string | null;
    goalId?: string | null;
    plan: AgentPlanEnvelope;
    shadow?: boolean;
  }): Promise<AgentRunSnapshot> {
    const plan = agentPlanEnvelopeSchema.parse(input.plan);
    return withTenantTransaction(this.app, input.userId, async (db) => {
      const inserted = await db.insert(agentRuns).values({
        userId: input.userId,
        taskId: input.taskId,
        sessionId: input.sessionId ?? null,
        goalId: input.goalId ?? null,
        state: "ready",
        revision: 3,
        plan,
        maxSteps: Math.min(8, plan.steps.length),
        shadow: input.shadow ?? false,
      }).onConflictDoNothing({ target: agentRuns.taskId }).returning();

      const run = inserted[0] ?? (await db.select().from(agentRuns)
        .where(and(eq(agentRuns.taskId, input.taskId), eq(agentRuns.userId, input.userId))).limit(1))[0];
      if (!run) throw new Error("agent_run_create_failed");

      if (inserted[0]) {
        await db.insert(agentSteps).values(plan.steps.map((step, sequence) => ({
          runId: run.id,
          userId: input.userId,
          stepKey: step.id,
          sequence,
          state: step.depends_on.length === 0 ? "ready" : "pending",
          dependsOn: step.depends_on,
          expectedOutcome: step.expected_outcome,
          toolRequest: step.tool_request,
          maxAttempts: step.max_attempts,
          idempotencyKey: agentStepIdempotencyKey(run.id, step.id),
        })));
        await db.insert(agentEvents).values([
          { runId: run.id, userId: input.userId, revision: 1, eventType: "agent.understood", fromState: null, toState: "understanding", payload: {} },
          { runId: run.id, userId: input.userId, revision: 2, eventType: "agent.planned", fromState: "understanding", toState: "planning", payload: { stepCount: plan.steps.length } },
          { runId: run.id, userId: input.userId, revision: 3, eventType: "agent.ready", fromState: "planning", toState: "ready", payload: { shadow: input.shadow ?? false } },
        ]);
      }
      return this.loadRunOnDb(db, input.userId, run.id);
    });
  }

  async loadRun(userId: string, runId: string): Promise<AgentRunSnapshot> {
    return withTenantTransaction(this.app, userId, (db) => this.loadRunOnDb(db, userId, runId));
  }

  async findRunByTask(userId: string, taskId: string): Promise<AgentRunSnapshot | null> {
    return withTenantTransaction(this.app, userId, async (db) => {
      const row = (await db.select({ id: agentRuns.id }).from(agentRuns).where(and(
        eq(agentRuns.taskId, taskId), eq(agentRuns.userId, userId),
      )).limit(1))[0];
      return row ? this.loadRunOnDb(db, userId, row.id) : null;
    });
  }

  private async loadRunOnDb(db: TenantDb, userId: string, runId: string): Promise<AgentRunSnapshot> {
    const [runRows, steps, evidence] = await Promise.all([
      db.select().from(agentRuns).where(and(eq(agentRuns.id, runId), eq(agentRuns.userId, userId))).limit(1),
      db.select().from(agentSteps).where(and(eq(agentSteps.runId, runId), eq(agentSteps.userId, userId))).orderBy(asc(agentSteps.sequence)),
      db.select().from(agentEvidence).where(and(eq(agentEvidence.runId, runId), eq(agentEvidence.userId, userId))),
    ]);
    const run = runRows[0];
    if (!run) throw new Error("agent_run_not_found");
    return { run, plan: agentPlanEnvelopeSchema.parse(run.plan), steps, evidence };
  }

  async claimRun(input: { userId: string; runId: string; leaseOwner: string; leaseMs?: number }): Promise<boolean> {
    const now = new Date();
    const expiresAt = new Date(now.getTime() + Math.max(5_000, Math.min(input.leaseMs ?? 30_000, 120_000)));
    return withTenantTransaction(this.app, input.userId, async (db) => {
      const rows = await db.update(agentRuns).set({ leaseOwner: input.leaseOwner, leaseExpiresAt: expiresAt, updatedAt: now })
        .where(and(
          eq(agentRuns.id, input.runId), eq(agentRuns.userId, input.userId),
          or(isNull(agentRuns.leaseExpiresAt), lt(agentRuns.leaseExpiresAt, now), eq(agentRuns.leaseOwner, input.leaseOwner)),
          inArray(agentRuns.state, ["ready", "executing", "observing", "verifying", "replanning"]),
        )).returning({ id: agentRuns.id });
      return rows.length === 1;
    });
  }

  async releaseRun(userId: string, runId: string, leaseOwner: string): Promise<void> {
    await withTenantTransaction(this.app, userId, async (db) => {
      await db.update(agentRuns).set({ leaseOwner: null, leaseExpiresAt: null, updatedAt: new Date() })
        .where(and(eq(agentRuns.id, runId), eq(agentRuns.userId, userId), eq(agentRuns.leaseOwner, leaseOwner)));
    });
  }

  async transitionRun(input: {
    userId: string; runId: string; expectedRevision: number; to: AgentRunState;
    eventType: string; payload?: Record<string, unknown>; failureCode?: string | null;
    terminalResult?: Record<string, unknown> | null; computeMs?: number;
  }): Promise<typeof agentRuns.$inferSelect> {
    return withTenantTransaction(this.app, input.userId, async (db) => {
      const current = (await db.select().from(agentRuns).where(and(
        eq(agentRuns.id, input.runId), eq(agentRuns.userId, input.userId), eq(agentRuns.revision, input.expectedRevision),
      )).limit(1))[0];
      if (!current) throw new Error("agent_run_revision_conflict");
      const from = agentRunStateSchema.parse(current.state);
      assertAgentRunTransition(from, input.to);
      const revision = current.revision + 1;
      const terminal = ["completed", "blocked", "failed", "canceled"].includes(input.to);
      const waiting = input.to === "waiting_approval" || input.to === "waiting_evidence";
      const rows = await db.update(agentRuns).set({
        state: input.to, revision, failureCode: input.failureCode ?? current.failureCode,
        terminalResult: input.terminalResult ?? current.terminalResult,
        activeComputeMs: current.activeComputeMs + Math.max(0, input.computeMs ?? 0),
        waitingExpiresAt: waiting ? new Date(Date.now() + 86_400_000) : null,
        startedAt: current.startedAt ?? new Date(), completedAt: terminal ? new Date() : null, updatedAt: new Date(),
      }).where(and(eq(agentRuns.id, input.runId), eq(agentRuns.userId, input.userId), eq(agentRuns.revision, input.expectedRevision))).returning();
      if (!rows[0]) throw new Error("agent_run_revision_conflict");
      await db.insert(agentEvents).values({
        runId: input.runId, userId: input.userId, revision, eventType: input.eventType,
        fromState: from, toState: input.to, payload: safeEventPayload(input.payload),
      });
      return rows[0];
    });
  }

  async transitionStep(input: {
    userId: string; stepId: string; to: AgentStepState;
    toolResult?: Record<string, unknown> | null; verification?: AgentVerification | null;
    incrementAttempt?: boolean;
  }): Promise<typeof agentSteps.$inferSelect> {
    return withTenantTransaction(this.app, input.userId, async (db) => {
      const current = (await db.select().from(agentSteps).where(and(eq(agentSteps.id, input.stepId), eq(agentSteps.userId, input.userId))).limit(1))[0];
      if (!current) throw new Error("agent_step_not_found");
      const from = agentStepStateSchema.parse(current.state);
      assertAgentStepTransition(from, input.to);
      const now = new Date();
      const rows = await db.update(agentSteps).set({
        state: input.to,
        attempt: input.incrementAttempt ? current.attempt + 1 : current.attempt,
        toolResult: input.toolResult ?? current.toolResult,
        verification: input.verification ? agentVerificationSchema.parse(input.verification) : current.verification,
        startedAt: input.to === "executing" ? current.startedAt ?? now : current.startedAt,
        observedAt: input.to === "observed" ? now : current.observedAt,
        verifiedAt: input.to === "verified" || input.to === "waiting_evidence" ? now : current.verifiedAt,
        completedAt: ["verified", "failed", "skipped", "canceled"].includes(input.to) ? now : current.completedAt,
        updatedAt: now,
      }).where(and(eq(agentSteps.id, input.stepId), eq(agentSteps.userId, input.userId))).returning();
      if (!rows[0]) throw new Error("agent_step_update_failed");
      return rows[0];
    });
  }

  async recordEvidence(input: { userId: string; runId: string; stepId: string; evidence: AgentEvidenceInput[] }): Promise<Array<typeof agentEvidence.$inferSelect>> {
    if (input.evidence.length === 0) return [];
    return withTenantTransaction(this.app, input.userId, async (db) => db.insert(agentEvidence).values(
      input.evidence.map((item) => ({
        runId: input.runId, stepId: input.stepId, userId: input.userId, kind: item.kind,
        sourceRef: item.sourceRef ?? null, contentHash: item.contentHash ?? null,
        payload: item.payload, valid: item.valid ?? true,
      })),
    ).returning());
  }

  async incrementToolCalls(userId: string, runId: string, amount: number): Promise<void> {
    await withTenantTransaction(this.app, userId, async (db) => {
      await db.update(agentRuns).set({
        toolCallCount: sql`${agentRuns.toolCallCount} + ${Math.max(0, amount)}`,
        updatedAt: new Date(),
      }).where(and(eq(agentRuns.id, runId), eq(agentRuns.userId, userId)));
    });
  }

  async applyReplan(input: {
    userId: string;
    runId: string;
    expectedRevision: number;
    plan: AgentPlanEnvelope;
  }): Promise<AgentRunSnapshot> {
    const plan = agentPlanEnvelopeSchema.parse(input.plan);
    return withTenantTransaction(this.app, input.userId, async (db) => {
      const current = (await db.select().from(agentRuns).where(and(
        eq(agentRuns.id, input.runId), eq(agentRuns.userId, input.userId), eq(agentRuns.revision, input.expectedRevision),
      )).limit(1))[0];
      if (!current) throw new Error("agent_run_revision_conflict");
      if (current.state !== "waiting_evidence") throw new Error("agent_replan_requires_waiting_evidence");
      if (current.replanCount >= current.maxReplans) throw new Error("agent_replan_budget_exhausted");
      const existing = await db.select({ key: agentSteps.stepKey }).from(agentSteps).where(eq(agentSteps.runId, input.runId));
      const existingKeys = new Set(existing.map((item) => item.key));
      if (plan.steps.some((step) => existingKeys.has(step.id))) throw new Error("agent_replan_step_id_reused");

      const replanRevision = current.revision + 1;
      const readyRevision = current.revision + 2;
      const claimed = await db.update(agentRuns).set({
        state: "ready", revision: readyRevision, plan,
        replanCount: current.replanCount + 1, updatedAt: new Date(),
      }).where(and(
        eq(agentRuns.id, input.runId), eq(agentRuns.userId, input.userId),
        eq(agentRuns.revision, input.expectedRevision), eq(agentRuns.state, "waiting_evidence"),
      )).returning({ id: agentRuns.id });
      if (!claimed[0]) throw new Error("agent_run_revision_conflict");
      await db.update(agentSteps).set({ state: "skipped", completedAt: new Date(), updatedAt: new Date() }).where(and(
        eq(agentSteps.runId, input.runId), eq(agentSteps.userId, input.userId),
        inArray(agentSteps.state, ["waiting_evidence", "failed", "pending", "ready"]),
      ));
      const sequenceStart = existing.length;
      await db.insert(agentSteps).values(plan.steps.map((step, index) => ({
        runId: input.runId, userId: input.userId, stepKey: step.id, sequence: sequenceStart + index,
        state: step.depends_on.length === 0 ? "ready" : "pending", dependsOn: step.depends_on,
        expectedOutcome: step.expected_outcome, toolRequest: step.tool_request,
        maxAttempts: step.max_attempts, idempotencyKey: agentStepIdempotencyKey(input.runId, step.id),
      })));
      await db.insert(agentEvents).values([
        { runId: input.runId, userId: input.userId, revision: replanRevision, eventType: "agent.replanning", fromState: "waiting_evidence", toState: "replanning", payload: { replanCount: current.replanCount + 1 } },
        { runId: input.runId, userId: input.userId, revision: readyRevision, eventType: "agent.replanned", fromState: "replanning", toState: "ready", payload: { stepCount: plan.steps.length } },
      ]);
      return this.loadRunOnDb(db, input.userId, input.runId);
    });
  }
}

export function agentEngineRepository(app: FastifyInstance): AgentEngineRepository {
  return new AgentEngineRepository(app);
}
