import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import {
  decideStructuredResponseDecision,
  type StructuredResponseDecision,
} from "./structured-output-policy.js";
import { decideCommandRoute } from "../../modules/routing-policy/service.js";

type ExpectedFixture = {
  workload: string;
  primaryShape: StructuredResponseDecision["primaryShape"];
  tablePolicy: StructuredResponseDecision["tablePolicy"];
  expectedBlockTypes: StructuredResponseDecision["primaryBlockType"][];
};

type BlockOutputFixture = {
  id: string;
  message: string;
  expected: ExpectedFixture;
};

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

  groupBy() {
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
  constructor(private readonly results: unknown[]) {}

  select() {
    return new FakeQuery(this.results.shift() ?? []);
  }
}

function createApp() {
  return {
    db: new FakeDb([
      [
        {
          planCode: "pro",
          status: "active",
          trialEndsAt: null,
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        isRuntimeConnected: () => false,
      },
    },
  };
}

async function loadFixtures(): Promise<BlockOutputFixture[]> {
  const raw = await readFile(
    path.join(process.cwd(), "benchmarks", "block-output-policy.jsonl"),
    "utf8",
  );
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as BlockOutputFixture);
}

test("block output policy fixtures keep intent to workload and block shape deterministic", async () => {
  const fixtures = await loadFixtures();
  assert.equal(fixtures.length, 55);

  for (const fixture of fixtures) {
    const route = await decideCommandRoute(createApp() as never, {
      userId: "user-1",
      message: fixture.message,
      source: "mobile",
    });
    const decision = decideStructuredResponseDecision({
      prompt: fixture.message,
      selectedWorkload: route.selectedWorkload,
    });

    assert.equal(
      route.selectedWorkload,
      fixture.expected.workload,
      `${fixture.id}: workload`,
    );
    assert.equal(
      decision.primaryShape,
      fixture.expected.primaryShape,
      `${fixture.id}: primaryShape`,
    );
    assert.equal(
      decision.tablePolicy,
      fixture.expected.tablePolicy,
      `${fixture.id}: tablePolicy`,
    );
    assert.deepEqual(
      [decision.primaryBlockType],
      fixture.expected.expectedBlockTypes,
      `${fixture.id}: expectedBlockTypes`,
    );
  }
});
