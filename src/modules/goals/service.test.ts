import assert from "node:assert/strict";
import test from "node:test";
import { goalEvents, proactiveTriggers } from "../../db/schema.js";
import {
  applyGoalProgressBlocks,
  createGoal,
  getActiveGoalForContext,
  listGoals,
  updateGoal,
} from "./service.js";

class Query<T> {
  constructor(
    private readonly result: T,
    private readonly onLimit?: (value: number | undefined) => void,
  ) {}

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  limit(value?: number) {
    this.onLimit?.(value);
    return this;
  }

  then<TResult1 = T, TResult2 = never>(
    resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.result).then(resolve, reject);
  }
}

type GoalRow = {
  id: string;
  userId: string;
  sessionId: string | null;
  taskId: string | null;
  title: string;
  description: string;
  status: "draft" | "active" | "paused" | "done" | "canceled";
  currentStep: number;
  maxSteps: number;
  progress: Record<string, unknown>;
  scheduleHint: "on_next_message" | "daily_08_00" | "every_15m" | null;
  dueAt: Date | null;
  createdAt: Date;
  updatedAt: Date;
};

class GoalsDb {
  readonly rows: GoalRow[] = [];
  readonly events: Array<Record<string, unknown>> = [];

  select() {
    return {
      from: (table: unknown) => new Query(table === proactiveTriggers ? [] : this.rows),
    };
  }

  insert(table?: unknown) {
    const rows = this.rows;
    const events = this.events;
    return {
      values(values: Partial<GoalRow>) {
        if (table === goalEvents) {
          events.push(values as Record<string, unknown>);
          return Promise.resolve();
        }
        const now = new Date("2030-01-01T00:00:00.000Z");
        const row = {
          id: `goal-${rows.length + 1}`,
          taskId: null,
          sessionId: null,
          status: "active",
          currentStep: 0,
          maxSteps: 20,
          progress: {},
          scheduleHint: null,
          dueAt: null,
          createdAt: now,
          updatedAt: now,
          ...values,
        } as GoalRow;
        rows.unshift(row);
        return {
          returning: async () => [row],
        };
      },
    };
  }

  update() {
    const rows = this.rows;
    return {
      set(values: Partial<GoalRow>) {
        return {
          where() {
            return {
              returning: async () => {
                if (!rows[0]) return [];
                rows[0] = { ...rows[0], ...values };
                return [rows[0]];
              },
            };
          },
        };
      },
    };
  }
}

test("goals service creates, reads, and advances a durable session goal", async () => {
  const db = new GoalsDb();
  const app = { db, config: { ELYAN_GOAL_STATE_V2_ENABLED: true } } as never;

  const created = await createGoal(app, {
    userId: "user-1",
    title: "Haftalık çalışma planı",
    description: "Planı gün gün tamamla",
    maxSteps: 8,
  });

  assert.equal(created.goal.id, "goal-1");
  assert.equal(created.goal.status, "active");
  assert.equal(created.goal.maxSteps, 8);

  const listed = await listGoals(app, {
    userId: "user-1",
    status: "active",
    limit: 20,
  });
  assert.equal(listed.goals[0]?.title, "Haftalık çalışma planı");

  const active = await getActiveGoalForContext(app, {
    userId: "user-1",
  });
  assert.equal(active?.id, "goal-1");

  await applyGoalProgressBlocks(app, {
    userId: "user-1",
    blocks: [
      {
        type: "goal_progress",
        goalId: "goal-1",
        step: 1,
        ofSteps: 8,
        advancedTo: "Gün 1 planı tamamlandı.",
        blocker: null,
        done: false,
      },
    ],
  });

  assert.equal(db.rows[0]?.currentStep, 1);
  assert.equal(db.rows[0]?.status, "active");
  assert.deepEqual(db.rows[0]?.progress.completedSteps, ["Gün 1 planı tamamlandı."]);
  assert.deepEqual(db.events.map((event) => event.eventType), ["goal.opened", "goal.advanced"]);
});

test("goals service bounds steps and maps progress blocks to terminal statuses", async () => {
  const db = new GoalsDb();
  const app = { db, config: { ELYAN_GOAL_STATE_V2_ENABLED: true } } as never;

  const created = await createGoal(app, {
    userId: "user-1",
    title: "Uzun hedef",
    maxSteps: 99,
  });

  assert.equal(created.goal.maxSteps, 20);

  await applyGoalProgressBlocks(app, {
    userId: "user-1",
    blocks: [
      {
        type: "goal_progress",
        goalId: "goal-1",
        step: 20,
        ofSteps: 20,
        advancedTo: "Sınır adımı tamamlandı.",
        blocker: null,
        done: false,
      },
    ],
  });
  assert.equal(db.rows[0]?.status, "paused");
  assert.equal(db.rows[0]?.currentStep, 20);

  await applyGoalProgressBlocks(app, {
    userId: "user-1",
    blocks: [
      {
        type: "goal_progress",
        goalId: "goal-1",
        step: 20,
        ofSteps: 20,
        advancedTo: "Kullanıcı yanıtı gerekiyor.",
        blocker: "Eksik bilgi var.",
        done: false,
      },
    ],
  });
  assert.equal(db.rows[0]?.status, "paused");
  assert.deepEqual(db.rows[0]?.progress.blockers, ["Eksik bilgi var."]);

  await applyGoalProgressBlocks(app, {
    userId: "user-1",
    blocks: [
      {
        type: "goal_progress",
        goalId: "goal-1",
        step: 20,
        ofSteps: 20,
        advancedTo: "Hedef tamamlandı.",
        blocker: null,
        done: true,
      },
    ],
  });
  assert.equal(db.rows[0]?.status, "done");
  assert.equal(db.rows[0]?.progress.nextAction, null);
});

test("goal state v2 flag off preserves legacy writes without event records", async () => {
  const db = new GoalsDb();
  const app = { db, config: { ELYAN_GOAL_STATE_V2_ENABLED: false } } as never;
  await createGoal(app, { userId: "user-1", title: "Legacy goal" });
  assert.equal(db.rows[0]?.status, "active");
  assert.deepEqual(db.events, []);
});

test("updateGoal records terminal transitions in the append-only event stream", async () => {
  const db = new GoalsDb();
  const app = { db, config: { ELYAN_GOAL_STATE_V2_ENABLED: true } } as never;
  const created = await createGoal(app, { userId: "user-1", title: "Ship" });
  await updateGoal(app, { userId: "user-1", goalId: created.goal.id, status: "done" });
  assert.equal(db.rows[0]?.status, "done");
  assert.equal(db.rows[0]?.progress.engineState, "completed");
  assert.equal(db.events.at(-1)?.eventType, "goal.completed");
  assert.equal(db.events.at(-1)?.fromState, "open");
});
