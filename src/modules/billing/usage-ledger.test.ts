import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import {
  assertMonthlyAiUsageAllowed,
  getBillingUsageSummary,
  recordUsageLedgerEntry,
} from "./usage-ledger.js";

class FakeQuery<T> {
  constructor(private readonly result: T) {}

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

  then<TResult1 = T, TResult2 = never>(
    resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.result).then(resolve, reject);
  }
}

class FakeDb {
  constructor(
    private readonly selectResults: unknown[],
    public readonly inserted: Array<Record<string, unknown>> = [],
  ) {}

  select() {
    return new FakeQuery(this.selectResults.shift() ?? []);
  }

  insert() {
    const inserted = this.inserted;
    let currentValues: Record<string, unknown> = {};
    const builder = {
      values(values: Record<string, unknown>) {
        currentValues = values;
        inserted.push(values);
        return builder;
      },
      onConflictDoNothing() {
        return Promise.resolve();
      },
      then<TResult1 = unknown, TResult2 = never>(
        resolve?: ((value: unknown) => TResult1 | PromiseLike<TResult1>) | null,
        reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
      ) {
        return Promise.resolve(currentValues).then(resolve, reject);
      },
    } as const;

    return builder;
  }
}

test("getBillingUsageSummary reads monthly usage from usage_records only", async () => {
  const app = {
    db: new FakeDb([
      [],
      [{ used: 7 }],
      [{ used: 3 }],
      [{ granted: 0, used: 0 }],
      [],
    ]),
  };

  const summary = await getBillingUsageSummary(app.db as never, "user-1");

  assert.equal(summary.taskUsage.used, 7);
  assert.equal(summary.aiUsage.used, 3);
  assert.equal(summary.subscriptionStatus, "free");
  assert.equal(summary.taskLimitMonthly, 50);
  assert.equal(summary.aiCreditsMonthly, 120);
  assert.equal(summary.aiUsage.remaining, 117);
});

test("getBillingUsageSummary upgrades legacy zero-credit free rows to catalog allowance", async () => {
  const app = {
    db: new FakeDb([
      [
        {
          userId: "user-1",
          planCode: "free",
          status: "free",
          taskLimitMonthly: 0,
          aiCreditsMonthly: 0,
          currentPeriodStartedAt: new Date("2030-01-01T00:00:00.000Z"),
          periodEndsAt: new Date("2030-02-01T00:00:00.000Z"),
        },
      ],
      [{ used: 0 }],
      [{ used: 0 }],
      [{ granted: 0, used: 0 }],
      [],
    ]),
  };

  const summary = await getBillingUsageSummary(app.db as never, "user-1");

  assert.equal(summary.taskLimitMonthly, 50);
  assert.equal(summary.aiCreditsMonthly, 120);
  assert.equal(summary.aiUsage.granted, 120);
  assert.equal(summary.aiUsage.remaining, 120);
});

test("getBillingUsageSummary keeps free remaining credits on usage_records when no grant ledger exists", async () => {
  const app = {
    db: new FakeDb([
      [],
      [{ used: 1 }],
      [{ used: 1 }],
      [{ granted: 0, used: 1 }],
      [{ balanceAfter: 0 }],
    ]),
  };

  const summary = await getBillingUsageSummary(app.db as never, "user-1");

  assert.equal(summary.taskUsage.used, 1);
  assert.equal(summary.aiUsage.used, 1);
  assert.equal(summary.aiUsage.granted, 120);
  assert.equal(summary.aiUsage.remaining, 119);
});

test("assertMonthlyAiUsageAllowed fails closed when free plan credits are exhausted", async () => {
  const app = {
    db: new FakeDb([
      [],
      [{ used: 0 }],
      [{ used: 120 }],
      [{ granted: 0, used: 0 }],
      [],
    ]),
  };

  await assert.rejects(
    async () => assertMonthlyAiUsageAllowed(app.db as never, "user-1", 1),
    (error: unknown) => {
      assert.ok(error instanceof AppError);
      assert.equal(error.code, "ai_credit_limit_reached");
      assert.equal(error.statusCode, 409);
      return true;
    },
  );
});

test("recordUsageLedgerEntry appends a usage row", async () => {
  const db = new FakeDb([]);

  await recordUsageLedgerEntry(db as never, {
    userId: "user-1",
    taskId: "task-1",
    metric: "subscription_task",
    quantity: 2,
  });

  assert.deepEqual(db.inserted[0], {
    userId: "user-1",
    identityId: null,
    taskId: "task-1",
    metric: "subscription_task",
    quantity: 2,
    budgetUnits: 0,
    documentUnits: 0,
    imageUnits: 0,
    toolUnits: 0,
    qualityProfile: null,
    planSnapshot: {},
  });
});
