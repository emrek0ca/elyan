import { and, asc, desc, eq, or } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { chatSessions, goalEvents, proactiveTriggers, sessionGoals } from "../../db/schema.js";
import type {
  SessionGoalScheduleHint,
  SessionGoalStatus,
} from "../../contracts/domain.js";
import { elyanAssistantGoalProgressBlockSchema } from "../../contracts/domain.js";
import { forbidden, notFound } from "../../lib/errors.js";
import {
  assertGoalTransition,
  mergeGoalEngineState,
  readGoalEngineState,
  type GoalEngineState,
} from "./state-machine.js";
import { truncateText as compactText } from "../../lib/text.js";

const DEFAULT_MAX_STEPS = 20;
const ACTIVE_GOAL_LIMIT = 5;

export type GoalProgress = {
  completedSteps?: string[];
  nextAction?: string | null;
  blockers?: string[];
  waitingOn?: "user" | "desktop" | "tool" | "verification" | null;
  evidenceRefs?: string[];
  lastVerifiedAt?: string | null;
  source?: "user" | "model" | "task" | "tool";
  confidence?: number;
};

export type ActiveGoalContext = {
  id: string;
  sessionId: string | null;
  taskId: string | null;
  title: string;
  description: string;
  status: SessionGoalStatus;
  currentStep: number;
  maxSteps: number;
  progress: GoalProgress;
  scheduleHint: SessionGoalScheduleHint | null;
  dueAt: Date | null;
  resourceRevision: number;
  waitingOn: GoalProgress["waitingOn"];
  nextAction: string | null;
  evidenceState: "none" | "observed" | "verified";
};

export type ContinuityState = {
  contract: "elyan.continuity_state.v1";
  resourceRevision: number;
  activeGoal: ActiveGoalContext | null;
  waitingOn: GoalProgress["waitingOn"];
  nextAction: string | null;
  openLoops: string[];
  scheduledFollowUps: Array<{
    id: string;
    revision: number;
    dueAt: string;
    topic: string;
    status: string;
  }>;
  evidenceState: "none" | "observed" | "verified";
};

export type GoalExecutionEvent = {
  id: string;
  eventType: string;
  fromState: string | null;
  toState: string;
  payload: Record<string, unknown>;
  createdAt: Date;
};

function clampMaxSteps(value: number | undefined): number {
  if (!Number.isInteger(value)) {
    return DEFAULT_MAX_STEPS;
  }
  return Math.max(1, Math.min(DEFAULT_MAX_STEPS, value ?? DEFAULT_MAX_STEPS));
}

function normalizeProgress(value: unknown): GoalProgress {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const record = value as Record<string, unknown>;
  return {
    completedSteps: Array.isArray(record.completedSteps)
      ? record.completedSteps.map(String).filter(Boolean).slice(0, DEFAULT_MAX_STEPS)
      : undefined,
    nextAction:
      typeof record.nextAction === "string" && record.nextAction.trim()
        ? compactText(record.nextAction, 400)
        : null,
    blockers: Array.isArray(record.blockers)
      ? record.blockers.map(String).filter(Boolean).slice(0, DEFAULT_MAX_STEPS)
      : undefined,
    waitingOn: ["user", "desktop", "tool", "verification"].includes(String(record.waitingOn))
      ? record.waitingOn as GoalProgress["waitingOn"]
      : null,
    evidenceRefs: Array.isArray(record.evidenceRefs)
      ? [...new Set(record.evidenceRefs.map(String).filter(Boolean))].slice(0, 20)
      : [],
    lastVerifiedAt:
      typeof record.lastVerifiedAt === "string" && Number.isFinite(Date.parse(record.lastVerifiedAt))
        ? record.lastVerifiedAt
        : null,
    source: ["user", "model", "task", "tool"].includes(String(record.source))
      ? record.source as GoalProgress["source"]
      : undefined,
    confidence:
      typeof record.confidence === "number" && Number.isFinite(record.confidence)
        ? Math.max(0, Math.min(1, record.confidence))
        : undefined,
  };
}

function shapeGoal(row: typeof sessionGoals.$inferSelect): ActiveGoalContext {
  const progress = normalizeProgress(row.progress);
  return {
    id: row.id,
    sessionId: row.sessionId ?? null,
    taskId: row.taskId ?? null,
    title: row.title,
    description: row.description,
    status: row.status,
    currentStep: row.currentStep,
    maxSteps: row.maxSteps,
    progress,
    scheduleHint: row.scheduleHint,
    dueAt: row.dueAt,
    resourceRevision: row.updatedAt.getTime(),
    waitingOn: progress.waitingOn ?? null,
    nextAction: progress.nextAction ?? null,
    evidenceState: progress.lastVerifiedAt
      ? "verified"
      : (progress.evidenceRefs?.length ?? 0) > 0
        ? "observed"
        : "none",
  };
}

async function publishGoalRevision(
  app: FastifyInstance,
  userId: string,
  goal: ActiveGoalContext,
): Promise<void> {
  if (!app.services?.eventBus) return;
  await app.services.eventBus.publish({
    topic: "goal.updated",
    userId,
    taskId: goal.taskId ?? undefined,
    payload: {
      contract: "elyan.continuity_event.v1",
      resourceRevision: goal.resourceRevision,
      sessionId: goal.sessionId,
      goal,
    },
  });
  await publishContinuityRevision(app, {
    userId,
    sessionId: goal.sessionId ?? undefined,
  });
}

function readTriggerPayload(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function triggerRevision(updatedAt: Date): number {
  return updatedAt.getTime();
}

async function buildContinuityState(
  app: FastifyInstance,
  input: { userId: string; sessionId?: string; goals: ActiveGoalContext[] },
): Promise<ContinuityState> {
  const conditions = [
    eq(proactiveTriggers.userId, input.userId),
    eq(proactiveTriggers.status, "pending"),
  ];
  if (input.sessionId) conditions.push(eq(proactiveTriggers.sessionId, input.sessionId));
  const triggerRows = await app.db
    .select()
    .from(proactiveTriggers)
    .where(and(...conditions))
    .orderBy(asc(proactiveTriggers.due))
    .limit(20);
  const activeGoal = input.goals.find((goal) => goal.status === "active") ?? null;
  const scheduledFollowUps = triggerRows.map((row) => {
    const payload = readTriggerPayload(row.payload);
    return {
      id: row.id,
      revision: triggerRevision(row.updatedAt),
      dueAt: row.due.toISOString(),
      topic: compactText(String(payload.topic ?? "Takip"), 240),
      status: row.status,
    };
  });
  const resourceRevision = Math.max(
    0,
    ...input.goals.map((goal) => goal.resourceRevision),
    ...triggerRows.map((row) => triggerRevision(row.updatedAt)),
  );
  const progress = activeGoal?.progress ?? {};
  return {
    contract: "elyan.continuity_state.v1",
    resourceRevision,
    activeGoal,
    waitingOn: progress.waitingOn ?? null,
    nextAction: progress.nextAction ?? null,
    openLoops: [...new Set([...(progress.blockers ?? []), ...(progress.nextAction ? [progress.nextAction] : [])])].slice(0, 12),
    scheduledFollowUps,
    evidenceState: progress.lastVerifiedAt
      ? "verified"
      : (progress.evidenceRefs?.length ?? 0) > 0
        ? "observed"
        : "none",
  };
}

async function appendGoalEvent(app: FastifyInstance, input: {
  goalId: string;
  userId: string;
  eventType: string;
  fromState: GoalEngineState | null;
  toState: GoalEngineState;
  payload?: Record<string, unknown>;
}) {
  await app.db.insert(goalEvents).values({
    goalId: input.goalId,
    userId: input.userId,
    eventType: input.eventType,
    fromState: input.fromState,
    toState: input.toState,
    payload: input.payload ?? {},
  });
}

async function assertOwnedSession(
  app: FastifyInstance,
  input: { userId: string; sessionId: string },
) {
  const rows = await app.db
    .select({ id: chatSessions.id })
    .from(chatSessions)
    .where(and(eq(chatSessions.id, input.sessionId), eq(chatSessions.userId, input.userId)))
    .limit(1);
  if (!rows[0]) {
    throw forbidden("Chat session is not available for this user.");
  }
}

async function pauseOverflowActiveGoals(app: FastifyInstance, userId: string) {
  const activeRows = await app.db
    .select({ id: sessionGoals.id })
    .from(sessionGoals)
    .where(and(eq(sessionGoals.userId, userId), eq(sessionGoals.status, "active")))
    .orderBy(desc(sessionGoals.updatedAt))
    .limit(ACTIVE_GOAL_LIMIT + 1);

  const overflow = activeRows.slice(ACTIVE_GOAL_LIMIT);
  if (overflow.length === 0) return;
  const now = new Date();
  for (const row of overflow) {
    await app.db
      .update(sessionGoals)
      .set({
        status: "paused",
        updatedAt: now,
      })
      .where(and(eq(sessionGoals.id, row.id), eq(sessionGoals.userId, userId)));
  }
}

export async function createGoal(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId?: string;
    taskId?: string;
    title: string;
    description?: string;
    maxSteps?: number;
    scheduleHint?: SessionGoalScheduleHint | null;
    dueAt?: Date | null;
  },
) {
  if (input.sessionId) {
    await assertOwnedSession(app, { userId: input.userId, sessionId: input.sessionId });
  }
  const rows = await app.db
    .insert(sessionGoals)
    .values({
      userId: input.userId,
      sessionId: input.sessionId ?? null,
      taskId: input.taskId ?? null,
      title: compactText(input.title, 200),
      description: compactText(input.description ?? "", 4_000),
      status: "active",
      currentStep: 0,
      maxSteps: clampMaxSteps(input.maxSteps),
      progress: {
        completedSteps: [],
        nextAction: null,
        blockers: [],
        engineState: "open",
      },
      scheduleHint: input.scheduleHint ?? "on_next_message",
      dueAt: input.dueAt ?? null,
    })
    .returning();

  await pauseOverflowActiveGoals(app, input.userId);
  if (app.config?.ELYAN_GOAL_STATE_V2_ENABLED === true) {
    await appendGoalEvent(app, {
      goalId: rows[0].id, userId: input.userId, eventType: "goal.opened",
      fromState: null, toState: "open",
    });
  }
  const goal = shapeGoal(rows[0]);
  await publishGoalRevision(app, input.userId, goal);
  return { goal };
}

export async function listGoals(
  app: FastifyInstance,
  input: {
    userId: string;
    status?: SessionGoalStatus;
    sessionId?: string;
    limit: number;
  },
) {
  const conditions = [eq(sessionGoals.userId, input.userId)];
  if (input.status) conditions.push(eq(sessionGoals.status, input.status));
  if (input.sessionId) conditions.push(eq(sessionGoals.sessionId, input.sessionId));

  const rows = await app.db
    .select()
    .from(sessionGoals)
    .where(and(...conditions))
    .orderBy(desc(sessionGoals.updatedAt))
    .limit(input.limit);
  const goals = rows.map(shapeGoal);
  const continuity = await buildContinuityState(app, {
    userId: input.userId,
    sessionId: input.sessionId,
    goals,
  });
  return {
    goals,
    continuity,
    resourceRevision: continuity.resourceRevision,
  };
}

export async function publishContinuityRevision(
  app: FastifyInstance,
  input: { userId: string; sessionId?: string },
): Promise<ContinuityState> {
  const snapshot = await listGoals(app, {
    userId: input.userId,
    sessionId: input.sessionId,
    limit: 50,
  });
  if (!app.services?.eventBus) return snapshot.continuity;
  await app.services.eventBus.publish({
    topic: "continuity.updated",
    userId: input.userId,
    payload: {
      contract: "elyan.continuity_event.v1",
      resourceRevision: snapshot.resourceRevision,
      sessionId: input.sessionId ?? null,
      continuity: snapshot.continuity,
    },
  });
  return snapshot.continuity;
}

export async function syncGoalFromTaskLifecycle(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId: string;
    goalId?: string | null;
    status: string;
    artifactIds?: string[];
    summary?: string | null;
    verified?: boolean;
    checkpointRevision?: number | null;
    now?: Date;
  },
): Promise<ActiveGoalContext | null> {
  const rows = await app.db
    .select()
    .from(sessionGoals)
    .where(and(
      eq(sessionGoals.userId, input.userId),
      input.goalId
        ? or(eq(sessionGoals.id, input.goalId), eq(sessionGoals.taskId, input.taskId))
        : eq(sessionGoals.taskId, input.taskId),
    ))
    .orderBy(desc(sessionGoals.updatedAt))
    .limit(1);
  const goal = rows[0];
  if (!goal || goal.status === "done" || goal.status === "canceled") return null;

  const now = input.now ?? new Date();
  const previous = normalizeProgress(goal.progress);
  const evidenceRefs = [...new Set([
    ...(previous.evidenceRefs ?? []),
    `task:${input.taskId}`,
    ...(input.artifactIds ?? []).map((id) => `artifact:${id}`),
    ...(input.checkpointRevision && input.checkpointRevision > 0
      ? [`checkpoint:${input.taskId}:${input.checkpointRevision}`]
      : []),
  ])].slice(-20);
  const terminal = ["completed", "failed", "canceled"].includes(input.status);
  const completed = input.status === "completed" && input.verified === true;
  const waitingOn: GoalProgress["waitingOn"] = input.status === "waiting_approval"
    ? "user"
    : ["queued", "assigned", "running"].includes(input.status)
      ? "desktop"
      : input.status === "completed" && !completed
        ? "verification"
        : null;
  const nextAction = completed
    ? null
    : input.status === "waiting_approval"
      ? "Kullanıcı yanıtını bekle"
      : input.status === "completed"
        ? "Çıktıyı doğrula"
        : input.checkpointRevision && input.checkpointRevision > 0
          ? "Kaydedilen noktadan devam et"
        : terminal
          ? compactText(input.summary ?? "Görevi gözden geçir", 400)
          : "Görev sonucunu bekle";
  const nextStatus: SessionGoalStatus = completed
    ? "done"
    : terminal
      ? "paused"
      : "active";
  const progress: GoalProgress = {
    ...previous,
    nextAction,
    waitingOn,
    evidenceRefs,
    lastVerifiedAt: completed ? now.toISOString() : previous.lastVerifiedAt ?? null,
    source: "task",
    confidence: 1,
  };
  const updated = await app.db
    .update(sessionGoals)
    .set({
      taskId: input.taskId,
      status: nextStatus,
      progress: mergeGoalEngineState(
        progress,
        completed ? "completed" : terminal ? "waiting" : waitingOn ? "waiting" : "executing",
      ),
      updatedAt: now,
    })
    .where(and(
      eq(sessionGoals.id, goal.id),
      eq(sessionGoals.userId, input.userId),
      eq(sessionGoals.status, goal.status),
      eq(sessionGoals.updatedAt, goal.updatedAt),
    ))
    .returning();
  if (!updated[0]) return null;
  if (app.config?.ELYAN_GOAL_STATE_V2_ENABLED === true) {
    const from = readGoalEngineState(goal.progress);
    const to = completed ? "completed" : terminal || waitingOn ? "waiting" : "executing";
    await appendGoalEvent(app, {
      goalId: goal.id,
      userId: input.userId,
      eventType: `task.${input.status}`,
      fromState: from,
      toState: to,
      payload: {
        taskId: input.taskId,
        evidenceRefs,
        verified: completed,
      },
    });
  }
  const shaped = shapeGoal(updated[0]);
  await publishGoalRevision(app, input.userId, shaped);
  return shaped;
}

export async function getActiveGoalForContext(
  app: FastifyInstance,
  input: { userId: string; sessionId?: string | null },
): Promise<ActiveGoalContext | null> {
  const sessionScoped = input.sessionId
    ? await app.db
        .select()
        .from(sessionGoals)
        .where(
          and(
            eq(sessionGoals.userId, input.userId),
            eq(sessionGoals.sessionId, input.sessionId),
            eq(sessionGoals.status, "active"),
          ),
        )
        .orderBy(desc(sessionGoals.updatedAt))
        .limit(1)
    : [];
  if (sessionScoped[0]) return shapeGoal(sessionScoped[0]);

  const rows = await app.db
    .select()
    .from(sessionGoals)
    .where(and(eq(sessionGoals.userId, input.userId), eq(sessionGoals.status, "active")))
    .orderBy(desc(sessionGoals.updatedAt))
    .limit(1);
  return rows[0] ? shapeGoal(rows[0]) : null;
}

export async function getGoalExecutionContext(
  app: FastifyInstance,
  input: {
    userId: string;
    goalId?: string;
    sessionId?: string | null;
    eventLimit?: number;
  },
): Promise<{ goal: ActiveGoalContext | null; events: GoalExecutionEvent[] }> {
  const eventLimit = Math.max(1, Math.min(input.eventLimit ?? 12, 50));
  const goalRows = input.goalId
    ? await app.db
        .select()
        .from(sessionGoals)
        .where(and(eq(sessionGoals.id, input.goalId), eq(sessionGoals.userId, input.userId)))
        .limit(1)
    : input.sessionId
      ? await app.db
          .select()
          .from(sessionGoals)
          .where(
            and(
              eq(sessionGoals.userId, input.userId),
              eq(sessionGoals.sessionId, input.sessionId),
              eq(sessionGoals.status, "active"),
            ),
          )
          .orderBy(desc(sessionGoals.updatedAt))
          .limit(1)
      : await app.db
          .select()
          .from(sessionGoals)
          .where(and(eq(sessionGoals.userId, input.userId), eq(sessionGoals.status, "active")))
          .orderBy(desc(sessionGoals.updatedAt))
          .limit(1);
  const goal = goalRows[0];
  if (!goal) {
    return { goal: null, events: [] };
  }

  const eventRows = await app.db
    .select()
    .from(goalEvents)
    .where(and(eq(goalEvents.goalId, goal.id), eq(goalEvents.userId, input.userId)))
    .orderBy(desc(goalEvents.createdAt))
    .limit(eventLimit);
  return {
    goal: shapeGoal(goal),
    events: eventRows.reverse().map((event) => ({
      id: event.id,
      eventType: event.eventType,
      fromState: event.fromState,
      toState: event.toState,
      payload:
        event.payload && typeof event.payload === "object" && !Array.isArray(event.payload)
          ? event.payload as Record<string, unknown>
          : {},
      createdAt: event.createdAt,
    })),
  };
}

export async function updateGoal(
  app: FastifyInstance,
  input: {
    userId: string;
    goalId: string;
    status?: SessionGoalStatus;
    title?: string;
    description?: string;
    scheduleHint?: SessionGoalScheduleHint | null;
    dueAt?: Date | null;
  },
) {
  const existingRows = await app.db
    .select()
    .from(sessionGoals)
    .where(and(eq(sessionGoals.id, input.goalId), eq(sessionGoals.userId, input.userId)))
    .limit(1);
  const existing = existingRows[0];
  if (!existing) {
    throw notFound("Goal not found.");
  }
  const values: Partial<typeof sessionGoals.$inferInsert> = {
    updatedAt: new Date(),
  };
  if (input.status) values.status = input.status;
  if (input.title) values.title = compactText(input.title, 200);
  if (input.description != null) values.description = compactText(input.description, 4_000);
  if ("scheduleHint" in input) values.scheduleHint = input.scheduleHint ?? null;
  if ("dueAt" in input) values.dueAt = input.dueAt ?? null;

  let transition: { from: GoalEngineState; to: GoalEngineState; eventType: string } | null = null;
  if (app.config?.ELYAN_GOAL_STATE_V2_ENABLED === true && input.status) {
    const from = readGoalEngineState(existing.progress);
    const to: GoalEngineState = input.status === "done" || input.status === "canceled"
      ? "completed"
      : input.status === "paused"
        ? "waiting"
        : input.status === "draft"
          ? "planned"
          : "executing";
    assertGoalTransition(from, to);
    values.progress = mergeGoalEngineState(existing.progress, to);
    transition = { from, to, eventType: `goal.${to}` };
  }

  const rows = await app.db
    .update(sessionGoals)
    .set(values)
    .where(and(eq(sessionGoals.id, input.goalId), eq(sessionGoals.userId, input.userId)))
    .returning();
  if (transition) {
    await appendGoalEvent(app, {
      goalId: input.goalId,
      userId: input.userId,
      eventType: transition.eventType,
      fromState: transition.from,
      toState: transition.to,
      payload: { status: input.status },
    });
  }
  const goal = shapeGoal(rows[0]);
  await publishGoalRevision(app, input.userId, goal);
  return { goal };
}

export async function advanceGoal(
  app: FastifyInstance,
  input: {
    userId: string;
    goalId: string;
    step: number;
    ofSteps: number;
    advancedTo: string;
    blocker?: string | null;
    done?: boolean;
  },
) {
  const rows = await app.db
    .select()
    .from(sessionGoals)
    .where(and(eq(sessionGoals.id, input.goalId), eq(sessionGoals.userId, input.userId)))
    .limit(1);
  const existing = rows[0];
  if (!existing) {
    throw notFound("Goal not found.");
  }

  const maxSteps = clampMaxSteps(Math.min(existing.maxSteps, input.ofSteps));
  const nextStep = Math.max(existing.currentStep, Math.min(input.step, maxSteps));
  const progress = normalizeProgress(existing.progress);
  const previousEngineState = readGoalEngineState(existing.progress);
  const advancedTo = compactText(input.advancedTo, 400);
  const completedSteps = Array.from(
    new Set([...(progress.completedSteps ?? []), advancedTo]),
  ).slice(-maxSteps);
  const blockers = input.blocker
    ? [...(progress.blockers ?? []), compactText(input.blocker, 400)].slice(-maxSteps)
    : (progress.blockers ?? []);
  const reachedStepLimit = nextStep >= maxSteps;
  const status: SessionGoalStatus = input.done
    ? "done"
    : input.blocker
      ? "paused"
      : reachedStepLimit
        ? "paused"
        : "active";
  const nextEngineState: GoalEngineState = input.done
    ? "completed"
    : input.blocker
      ? "blocked"
      : reachedStepLimit
        ? "waiting"
      : "executing";
  if (app.config?.ELYAN_GOAL_STATE_V2_ENABLED === true) {
    assertGoalTransition(previousEngineState, nextEngineState);
  }

  const updated = await app.db
    .update(sessionGoals)
    .set({
      currentStep: nextStep,
      maxSteps,
      status,
      progress: mergeGoalEngineState({
        completedSteps,
        nextAction: input.done ? null : advancedTo,
        blockers,
      }, nextEngineState),
      updatedAt: new Date(),
    })
    .where(and(eq(sessionGoals.id, input.goalId), eq(sessionGoals.userId, input.userId)))
    .returning();

  if (app.config?.ELYAN_GOAL_STATE_V2_ENABLED === true) {
    await appendGoalEvent(app, {
      goalId: input.goalId, userId: input.userId,
      eventType: input.done ? "goal.completed" : input.blocker ? "goal.blocked" : "goal.advanced",
      fromState: previousEngineState, toState: nextEngineState,
      payload: { step: nextStep, advancedTo, blocker: input.blocker ?? null },
    });
  }

  const goal = shapeGoal(updated[0]);
  await publishGoalRevision(app, input.userId, goal);
  return { goal };
}

function flattenBlocks(blocks: unknown[]): unknown[] {
  const flattened: unknown[] = [];
  for (const block of blocks) {
    flattened.push(block);
    if (block && typeof block === "object" && !Array.isArray(block)) {
      const children = (block as Record<string, unknown>).children;
      if (Array.isArray(children)) {
        flattened.push(...flattenBlocks(children));
      }
    }
  }
  return flattened;
}

export async function applyGoalProgressBlocks(
  app: FastifyInstance,
  input: {
    userId: string;
    blocks: unknown[];
  },
) {
  const block = flattenBlocks(input.blocks)
    .map((item) => elyanAssistantGoalProgressBlockSchema.safeParse(item))
    .find((result) => result.success)?.data;
  if (!block) {
    return null;
  }

  return advanceGoal(app, {
    userId: input.userId,
    goalId: block.goalId,
    step: block.step,
    ofSteps: block.ofSteps,
    advancedTo: block.advancedTo,
    blocker: block.blocker,
    done: block.done,
  }).catch(() => null);
}
