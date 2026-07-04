import assert from "node:assert/strict";
import test from "node:test";
import { ensureElyanServerBrainBootstrap } from "./bootstrap.js";

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

function createInsertBuilder(tableName: string, inserted: Array<{ table: string; values: Record<string, unknown> }>) {
  let currentValues: Record<string, unknown> = {};
  const builder = {
    values(values: Record<string, unknown>) {
      currentValues = values;
      inserted.push({
        table: tableName,
        values,
      });
      return builder;
    },
    returning() {
      return Promise.resolve([
        {
          id: tableName === "training_jobs" ? "training-job-1" : "inserted-row-1",
          ...currentValues,
        },
      ]);
    },
    then<TResult1 = unknown[], TResult2 = never>(
      resolve?: ((value: unknown[]) => TResult1 | PromiseLike<TResult1>) | null,
      reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
    ) {
      return Promise.resolve([] as unknown[]).then(resolve, reject);
    },
  };

  return builder;
}

class FakeDb {
  constructor(
    private readonly results: unknown[],
    private readonly inserted: Array<{ table: string; values: Record<string, unknown> }>,
  ) {}

  select() {
    return new FakeQuery(this.results.shift() ?? []);
  }

  insert(table: { _?: string } | Record<string, unknown>) {
    const tableName = typeof table === "object" && table !== null ? "unknown" : "unknown";
    return createInsertBuilder(tableName, this.inserted);
  }

  update() {
    return {
      set() {
        return {
          where: async () => [],
        };
      },
    };
  }
}

test("ensureElyanServerBrainBootstrap seeds a shared brain device and shared training job", async () => {
  const inserted: Array<{ table: string; values: Record<string, unknown> }> = [];
  const app = {
    db: new FakeDb(
      [
        [],
        [
          {
            id: "shared-brain-device",
            type: "desktop",
            externalDeviceId: "shared-brain",
            label: "Elyan",
            platform: "server",
            runtimeVersion: "server",
            appVersion: null,
            isActive: true,
            pairedAt: new Date("2030-01-01T00:00:00.000Z"),
            lastSeenAt: new Date("2030-01-01T00:00:00.000Z"),
            createdAt: new Date("2030-01-01T00:00:00.000Z"),
            updatedAt: new Date("2030-01-01T00:00:00.000Z"),
          },
        ],
        [],
        [],
        [],
        [
          {
            baseModel: "llama3.2",
          },
        ],
      ],
      inserted,
    ),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
    },
  };

  const result = await ensureElyanServerBrainBootstrap(app as never);

  assert.equal(result.seeded, true);
  assert.equal(result.sharedBrainDevice.id, "shared-brain-device");
  assert.equal(result.trainingJob?.id, "inserted-row-1");
  assert.equal(inserted.length >= 2, true);
  assert.equal(inserted.some((entry) => entry.values["label"] === "Elyan"), true);
  assert.equal(
    inserted.some(
      (entry) =>
        entry.values["config"] &&
        typeof entry.values["config"] === "object" &&
        !Array.isArray(entry.values["config"]) &&
        (entry.values["config"] as Record<string, unknown>).providerStrategy &&
        typeof (entry.values["config"] as Record<string, unknown>).providerStrategy === "object" &&
        !Array.isArray((entry.values["config"] as Record<string, unknown>).providerStrategy) &&
        ((entry.values["config"] as Record<string, unknown>).providerStrategy as Record<string, unknown>).primary ===
          "groq",
    ),
    true,
  );
  assert.equal(
    inserted.some(
      (entry) =>
        entry.values["config"] &&
        typeof entry.values["config"] === "object" &&
        !Array.isArray(entry.values["config"]) &&
        (entry.values["config"] as Record<string, unknown>).providerStrategy &&
        typeof (entry.values["config"] as Record<string, unknown>).providerStrategy === "object" &&
        !Array.isArray((entry.values["config"] as Record<string, unknown>).providerStrategy) &&
        ((entry.values["config"] as Record<string, unknown>).providerStrategy as Record<string, unknown>)
          .learningProvider === "elyan" &&
        Array.isArray(
          ((entry.values["config"] as Record<string, unknown>).providerStrategy as Record<string, unknown>).fallback,
        ) &&
        (((entry.values["config"] as Record<string, unknown>).providerStrategy as Record<string, unknown>).fallback as Array<unknown>).includes(
          "elyan_shadow_until_quality_gate",
        ) &&
        ((entry.values["config"] as Record<string, unknown>).providerStrategy as Record<string, unknown>)
          .retirementPolicy === "operator_approval_after_eval_benchmark_latency_gates",
    ),
    true,
  );
  assert.equal(
    inserted.some(
      (entry) =>
        entry.values["scope"] === "shared" &&
        entry.values["kind"] === "lora" &&
        entry.values["status"] === "queued",
    ),
    true,
  );
  assert.equal(
    inserted.some(
      (entry) =>
        entry.values["config"] &&
        typeof entry.values["config"] === "object" &&
        !Array.isArray(entry.values["config"]) &&
        (entry.values["config"] as Record<string, unknown>).trainingBackend === "pytorch",
    ),
    true,
  );
});
