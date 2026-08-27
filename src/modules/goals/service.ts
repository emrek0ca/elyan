import { and, asc, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { chatSessions, goalEvents, sessionGoals } from "../../db/schema.js";
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
};

export type ActiveGoalContext = {
  id: string;
  title: string;
  description: string;
  status: SessionGoalStatus;
  currentStep: number;
  maxSteps: number;
  progress: GoalProgress;
  scheduleHint: SessionGoalScheduleHint | null;
  dueAt: Date | null;
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
  };
}

function shapeGoal(row: typeof sessionGoals.$inferSelect): ActiveGoalContext {
  return {
    id: row.id,
    title: row.title,
    description: row.description,
    status: row.status,
    currentStep: row.currentStep,
    maxSteps: row.maxSteps,
    progress: normalizeProgress(row.progress),
    scheduleHint: row.scheduleHint,
    dueAt: row.dueAt,
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
  return { goal: shapeGoal(rows[0]) };
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
  return { goals: rows.map(shapeGoal) };
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
  return { goal: shapeGoal(rows[0]) };
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

  return { goal: shapeGoal(updated[0]) };
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
