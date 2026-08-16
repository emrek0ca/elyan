import assert from "node:assert/strict";
import test from "node:test";
import {
  reconcileOrphanedChatMessagesBatch,
  shouldReconcileOrphanedChatMessage,
} from "./orphan-reconciler.js";

class SelectQuery<T> {
  constructor(private readonly rows: T[]) {}
  from() {
    return this;
  }
  where() {
    return this;
  }
  orderBy() {
    return this;
  }
  limit() {
    return this;
  }
  then<TResult1 = T[], TResult2 = never>(
    resolve?: ((value: T[]) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.rows).then(resolve, reject);
  }
}

test("global orphan sweep terminalizes only stale task-less assistant rows", async () => {
  const oldMessage = {
    id: "message-old",
    sessionId: "session-1",
    userId: "user-1",
    taskId: null,
    role: "assistant",
    status: "queued",
    content: "",
    createdAt: new Date(Date.now() - 91_000),
  };
  const recentMessage = {
    ...oldMessage,
    id: "message-recent",
    createdAt: new Date(Date.now() - 1_000),
  };
  const updates: Array<Record<string, unknown>> = [];
  const published: unknown[] = [];
  const db = {
    select: () => new SelectQuery([oldMessage, recentMessage]),
    update: () => ({
      set(values: Record<string, unknown>) {
        updates.push(values);
        return {
          where: () => ({
            returning: async () => [{ ...oldMessage, ...values }],
          }),
        };
      },
    }),
  };
  const app = {
    db,
    services: { eventBus: { publish: async (event: unknown) => published.push(event) } },
  };

  const reconciled = await reconcileOrphanedChatMessagesBatch(app as never, {
    limit: 100,
  });

  assert.equal(reconciled, 1);
  assert.equal(updates.length, 2);
  assert.equal(updates[0]?.status, "failed");
  assert.ok(updates[1]?.updatedAt instanceof Date);
  assert.equal(published.length, 1);
});

test("orphan eligibility keeps the 90 second grace period and task link gate", () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  assert.equal(
    shouldReconcileOrphanedChatMessage({
      role: "assistant",
      status: "running",
      taskId: null,
      createdAt: new Date(now.getTime() - 90_000),
      now,
    }),
    true,
  );
  assert.equal(
    shouldReconcileOrphanedChatMessage({
      role: "assistant",
      status: "queued",
      taskId: "task-1",
      createdAt: new Date(now.getTime() - 120_000),
      now,
    }),
    false,
  );
});
