import assert from "node:assert/strict";
import test from "node:test";
import { processNextQueuedTrainingJob } from "./worker.js";

class FakeSelectQuery<T> {
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
  readonly insertedRows: Array<{ table: unknown; values: unknown }> = [];

  constructor(
    private readonly selectResults: unknown[],
    private readonly trainingJobsRows: Array<Record<string, unknown>>,
  ) {}

  select() {
    return new FakeSelectQuery(this.selectResults.shift() ?? []);
  }

  update() {
    const rows = this.trainingJobsRows;
    let currentValues: Record<string, unknown> = {};
    const builder = {
      set(values: Record<string, unknown>) {
        currentValues = values;
        return builder;
      },
      where() {
        return builder;
      },
      returning() {
        rows[0] = {
          ...rows[0],
          ...currentValues,
        };
        return Promise.resolve([rows[0]]);
      },
    } as const;

    return builder;
  }

  insert(table?: unknown) {
    const insertedRows = this.insertedRows;
    const builder = {
      values(values: unknown) {
        insertedRows.push({ table, values });
        return builder;
      },
      then<TResult1 = unknown, TResult2 = never>(
        resolve?: ((value: unknown) => TResult1 | PromiseLike<TResult1>) | null,
        reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
      ) {
        return Promise.resolve(undefined).then(resolve, reject);
      },
    } as const;

    return builder;
  }
}

test("processNextQueuedTrainingJob completes shared jobs with bounded neural evaluation metadata", async () => {
  const trainingJobsRows = [
    {
      id: "job-1",
      ownerUserId: "user-1",
      scope: "shared",
      name: "Continuous refresh",
      kind: "lora",
      status: "queued",
      baseModel: "llama3.2",
      datasetManifestId: "dataset-1",
      config: {
        learningSnapshot: {
          qualityGate: {
            status: "ready_for_queue",
            reasons: [],
            thumbsDownRate: 0.1,
            regenerateRate: 0.05,
            qualityCompositeScore: 0.81,
            thresholds: {
              minSafeLearningEvents: 32,
              minTotalQualitySignals: 8,
              minHelpfulnessSignals: 2,
              minBrevityToneSignals: 3,
              minTaskRoutingSignals: 1,
              maxThumbsDownRate: 0.45,
              maxRegenerateRate: 0.35,
            },
          },
        },
        datasetSnapshot: {
          approvedCorrectionCount: 160,
          compactedRecordCount: 128,
          freshSignalCount: 96,
          correctionDensity: 0.8,
          freshSignalRatio: 0.75,
          signalFreshnessScore: 0.82,
          lineageScore: 1,
          compactionQualityScore: 0.83,
          compactDatasetEligible: true,
          sourceLineage: "approved_corrections",
          compactionMode: "approved_corrections_compact_v1",
        },
        qualitySignalSummary: {
          toneSignals: 3,
          humorSignals: 1,
          brevitySignals: 2,
          helpfulnessSignals: 4,
          taskRoutingSignals: 2,
        },
      },
      metadata: {},
      metrics: {},
      error: null,
      startedAt: null,
      completedAt: null,
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      updatedAt: new Date("2030-01-01T00:00:00.000Z"),
    },
  ];

  const app = {
    db: new FakeDb(
      [
        [trainingJobsRows[0]],
        [
          {
            id: "dataset-1",
            status: "ready",
            scope: "shared",
            recordCount: 128,
            tokenEstimate: 12_000,
            metadata: {
              problemClass: "quantum_optimization",
              quantumBenchmarkScore: 0.81,
            },
          },
        ],
      ],
      trainingJobsRows,
    ),
    log: {
      error() {},
      info() {},
      warn() {},
    },
  };

  const processed = await processNextQueuedTrainingJob(app as never);

  assert.equal(processed, true);
  assert.equal(trainingJobsRows[0].status, "completed");
  assert.equal(trainingJobsRows[0].error, null);
  assert.equal((trainingJobsRows[0].metadata as Record<string, unknown>).trainingMode, "bounded_cpu_eval");
  assert.equal((trainingJobsRows[0].metadata as Record<string, unknown>).workerStatus, "completed");
  assert.equal((trainingJobsRows[0].metadata as Record<string, unknown>).phase, "evaluation");
  assert.equal((trainingJobsRows[0].metadata as Record<string, unknown>).evaluationState, "bounded_offline_eval");
  assert.equal((trainingJobsRows[0].metadata as Record<string, unknown>).promotionGate, "ready");
  assert.equal((trainingJobsRows[0].metadata as Record<string, unknown>).qualityGateStatus, "ready_for_queue");
  assert.equal(typeof (trainingJobsRows[0].metadata as Record<string, unknown>).datasetFingerprint, "string");

  const metrics = trainingJobsRows[0].metrics as Record<string, unknown>;
  assert.equal(typeof metrics.evaluationScore, "number");
  assert.equal(typeof metrics.neuralEvalScore, "number");
  assert.equal(metrics.quantumBenchmarkScore, 0.81);
  const datasetQualityScore = metrics.datasetQualityScore as number;
  assert.equal(typeof datasetQualityScore, "number");
  assert.equal(datasetQualityScore >= 0.7, true);
  assert.equal(metrics.promotionGate, "ready");

  assert.equal((app.db as FakeDb).insertedRows.length, 2);
});

test("processNextQueuedTrainingJob keeps artifact draft when quality gate blocks promotion", async () => {
  const trainingJobsRows = [
    {
      id: "job-2",
      ownerUserId: "user-1",
      scope: "shared",
      name: "Continuous refresh blocked",
      kind: "lora",
      status: "queued",
      baseModel: "llama3.2",
      datasetManifestId: "dataset-2",
      config: {
        learningSnapshot: {
          qualityGate: {
            status: "blocked_quality_regression",
            reasons: ["thumbs_down_rate_too_high"],
            thumbsDownRate: 0.7,
            regenerateRate: 0.2,
            qualityCompositeScore: 0.31,
            thresholds: {
              minSafeLearningEvents: 32,
              minTotalQualitySignals: 8,
              minHelpfulnessSignals: 2,
              minBrevityToneSignals: 3,
              minTaskRoutingSignals: 1,
              maxThumbsDownRate: 0.45,
              maxRegenerateRate: 0.35,
            },
          },
        },
        datasetSnapshot: {
          approvedCorrectionCount: 24,
          compactedRecordCount: 12,
          freshSignalCount: 1,
          correctionDensity: 0.5,
          freshSignalRatio: 0.0833,
          signalFreshnessScore: 0.22,
          lineageScore: 1,
          compactionQualityScore: 0.31,
          compactDatasetEligible: false,
          sourceLineage: "approved_corrections",
          compactionMode: "approved_corrections_compact_v1",
        },
        qualitySignalSummary: {
          toneSignals: 3,
          humorSignals: 1,
          brevitySignals: 2,
          helpfulnessSignals: 4,
          taskRoutingSignals: 2,
        },
      },
      metadata: {},
      metrics: {},
      error: null,
      startedAt: null,
      completedAt: null,
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      updatedAt: new Date("2030-01-01T00:00:00.000Z"),
    },
  ];

  const app = {
    db: new FakeDb(
      [
        [trainingJobsRows[0]],
        [
          {
            id: "dataset-2",
            status: "ready",
            scope: "shared",
            recordCount: 128,
            tokenEstimate: 12_000,
            metadata: {},
          },
        ],
      ],
      trainingJobsRows,
    ),
    log: {
      error() {},
      info() {},
      warn() {},
    },
  };

  const processed = await processNextQueuedTrainingJob(app as never);

  assert.equal(processed, true);
  assert.equal(
    String((trainingJobsRows[0].metadata as Record<string, unknown>).promotionGate).startsWith("blocked_"),
    true,
  );
  assert.equal((trainingJobsRows[0].metadata as Record<string, unknown>).qualityGateStatus, "blocked_quality_regression");
  const artifactInsert = (app.db as FakeDb).insertedRows.find((entry) => {
    const value = entry.values as Record<string, unknown>;
    return value["storageUri"] === "elyan://model-artifacts/job-2";
  });
  assert.equal((artifactInsert?.values as Record<string, unknown> | undefined)?.status, "draft");
  assert.equal(((trainingJobsRows[0].metrics as Record<string, unknown>).datasetQualityScore as number) < 0.6, true);
});

test("processNextQueuedTrainingJob completes memory extraction jobs and queues follow-up memory work", async () => {
  const trainingJobsRows = [
    {
      id: "job-memory-1",
      ownerUserId: "user-1",
      scope: "user",
      name: "Memory extraction",
      kind: "memory_extraction",
      status: "queued",
      baseModel: "llama3.2",
      datasetManifestId: null,
      config: {
        trigger: "learning_events_persisted",
      },
      metadata: {},
      metrics: {},
      error: null,
      startedAt: null,
      completedAt: null,
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      updatedAt: new Date("2030-01-01T00:00:00.000Z"),
    },
  ];

  const app = {
    db: new FakeDb(
      [
        [trainingJobsRows[0]],
        [],
        [],
      ],
      trainingJobsRows,
    ),
    log: {
      error() {},
      info() {},
      warn() {},
    },
  };

  const processed = await processNextQueuedTrainingJob(app as never);

  assert.equal(processed, true);
  assert.equal((app.db as FakeDb).insertedRows.length > 0, true);
});
