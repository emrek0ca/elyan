import assert from "node:assert/strict";
import test from "node:test";
import { chatMessages, chatSessions, proactiveTriggers } from "../../db/schema.js";
import {
  BRAIN_WORKER_HEARTBEAT_KEY,
  processBrainWorkerIteration,
  processDueProactiveTriggers,
  processNextQueuedTrainingJob,
  startInProcessMemoryWorker,
} from "./worker.js";

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

function waitForWorkerTick(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 20);
  });
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

class FakeProactiveDb {
  readonly insertedRows: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  readonly updates: Array<{ table: unknown; values: Record<string, unknown> }> = [];
  private claimConsumed = false;

  constructor(
    private readonly trigger: Record<string, unknown> | null,
    private readonly session: Record<string, unknown> | null,
  ) {}

  select() {
    const db = this;
    return {
      from(table: unknown) {
        return {
          where() {
            return this;
          },
          orderBy() {
            return this;
          },
          limit() {
            if (table === proactiveTriggers) {
              if (db.claimConsumed || !db.trigger) return Promise.resolve([]);
              return Promise.resolve([db.trigger]);
            }
            if (table === chatSessions) {
              return Promise.resolve(db.session ? [db.session] : []);
            }
            return Promise.resolve([]);
          },
        };
      },
    };
  }

  update(table: unknown) {
    const db = this;
    let values: Record<string, unknown> = {};
    const builder = {
      set(next: Record<string, unknown>) {
        values = next;
        db.updates.push({ table, values });
        return builder;
      },
      where() {
        return builder;
      },
      returning() {
        if (table === proactiveTriggers && db.trigger && values.status === "running") {
          db.claimConsumed = true;
          return Promise.resolve([{ ...db.trigger, ...values }]);
        }
        return Promise.resolve([]);
      },
      then<TResult1 = unknown, TResult2 = never>(
        resolve?: ((value: unknown) => TResult1 | PromiseLike<TResult1>) | null,
        reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
      ) {
        return Promise.resolve([]).then(resolve, reject);
      },
    };
    return builder;
  }

  insert(table: unknown) {
    const db = this;
    const builder = {
      values(values: Record<string, unknown>) {
        db.insertedRows.push({ table, values });
        return builder;
      },
      returning() {
        const values = db.insertedRows[db.insertedRows.length - 1]?.values ?? {};
        return Promise.resolve([
          {
            id: values.id,
            createdAt: values.createdAt,
            updatedAt: values.updatedAt,
          },
        ]);
      },
    };
    return builder;
  }
}

test("startInProcessMemoryWorker skips API drainer when brain-worker heartbeat is fresh", async () => {
  const logs: string[] = [];
  const stop = startInProcessMemoryWorker({
    services: {
      reliability: {
        store: {
          get: async (key: string) =>
            key === BRAIN_WORKER_HEARTBEAT_KEY
              ? JSON.stringify({
                  timestamp: new Date().toISOString(),
                  mode: "brain_worker",
                })
              : null,
        },
      },
    },
    log: {
      info: (message: string) => {
        logs.push(message);
      },
      error: () => {
        throw new Error("in-process drainer should not run");
      },
    },
  } as never);

  await waitForWorkerTick();
  stop();

  assert.ok(
    logs.some((message) =>
      message.includes("external brain worker heartbeat is fresh"),
    ),
  );
});

test("processBrainWorkerIteration runs continuous learning only behind its flags", async () => {
  const result = await processBrainWorkerIteration(
    {
      config: {
        ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED: false,
        ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT: 0,
        ELYAN_CONTINUOUS_LEARNING_V2_ENABLED: false,
        ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED: false,
      },
    } as never,
    {
      processMemoryJob: async () => false,
      processDecay: async () => ({ status: "completed", processedCount: 0, updatedCount: 0 }),
      processProactive: async () => ({
        processed: 0,
        fired: 0,
        expired: 0,
        deferred: 0,
        failed: 0,
      }),
      processContinuousLearning: async () => {
        throw new Error("continuous learning should be flag-gated");
      },
    },
  );

  assert.equal(result.continuousLearning, undefined);

  const enabledResult = await processBrainWorkerIteration(
    {
      config: {
        ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED: false,
        ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT: 0,
        ELYAN_CONTINUOUS_LEARNING_V2_ENABLED: true,
        ELYAN_CONTINUOUS_LEARNING_SHADOW_ENABLED: false,
      },
    } as never,
    {
      processMemoryJob: async () => false,
      processDecay: async () => ({ status: "completed", processedCount: 0, updatedCount: 0 }),
      processProactive: async () => ({
        processed: 0,
        fired: 0,
        expired: 0,
        deferred: 0,
        failed: 0,
      }),
      processContinuousLearning: async () => ({
        processed: true,
        runId: "run-1",
        datasetManifestId: "dataset-1",
        shadow: false,
        candidate: {
          status: "ready",
          sourceEventCount: 40,
          acceptedEventCount: 36,
          rejectedEventCount: 4,
          dedupedEventCount: 0,
          replayRecordCount: 9,
          trainRecordCount: 32,
          validationRecordCount: 4,
          tokenEstimate: 120,
          datasetFingerprint: "abc",
          acceptedIdentityHashes: [],
          privacyReport: {
            rawEventValuesIncluded: false,
            promptContentIncluded: false,
            rejectedByReason: {
              privacy_level_not_safe: 0,
              expired: 0,
              metadata_not_training_eligible: 0,
              sensitive_value_detected: 0,
              low_confidence: 4,
              duplicate: 0,
            },
            privacyRejectedCount: 0,
            sensitiveRejectedCount: 0,
          },
          qualityReport: {
            qualityScore: 0.7,
            averageConfidence: 82,
            minConfidence: 60,
            validationRatio: 0.1,
            acceptedTypes: { task_feedback: 36 },
            acceptedSources: { task_feedback: 36 },
          },
          replayReport: {
            replayRatio: 20,
            replayRecordCount: 9,
            policy: "preserve_previous_capabilities",
          },
        },
        promotionReport: {
          status: "training_eligible",
          nextAction: "run_candidate_training",
          reasons: ["candidate_training_required_before_security_benchmarks"],
          gates: {
            minAcceptedEvents: 32,
            minReplayRatio: 10,
            minValidationRecords: 3,
            minQualityScore: 0.62,
            minBenchmarkScoreForCanary: 0.78,
            minEvaluationScoreForCanary: 0.72,
            minBenchmarkScoreForPromotion: 0.9,
            minEvaluationScoreForPromotion: 0.88,
            maxCanaryErrorRate: 0.02,
          },
        },
      }),
    },
  );

  assert.equal(enabledResult.continuousLearning?.processed, true);
});

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

test("processDueProactiveTriggers is inert while the proactive engine flag is disabled", async () => {
  let composeCalls = 0;
  const result = await processDueProactiveTriggers(
    {
      config: { ELYAN_PROACTIVE_ENGINE_ENABLED: false },
    } as never,
    {
      compose: async () => {
        composeCalls += 1;
        return { text: "should not run" };
      },
    },
  );

  assert.deepEqual(result, { processed: 0, fired: 0, expired: 0, deferred: 0, failed: 0 });
  assert.equal(composeCalls, 0);
});

test("processDueProactiveTriggers composes and publishes a due proactive chat message", async () => {
  const now = new Date("2030-01-01T09:00:00.000Z");
  const userId = "22222222-2222-4222-8222-222222222222";
  const sessionId = "11111111-1111-4111-8111-111111111111";
  const db = new FakeProactiveDb(
    {
      id: "44444444-4444-4444-8444-444444444444",
      userId,
      sessionId,
      kind: "follow_up",
      due: now,
      payload: {
        source: "turn_envelope",
        topic: "deploy",
        nudge: "Deploy nasil gitti?",
        dueHint: "tomorrow",
      },
      status: "pending",
      createdBy: "model",
      firedAt: null,
      canceledAt: null,
      createdAt: now,
      updatedAt: now,
    },
    {
      id: sessionId,
      userId,
      targetDeviceId: "33333333-3333-4333-8333-333333333333",
    },
  );
  const events: Array<Record<string, unknown>> = [];
  const app = {
    config: { ELYAN_PROACTIVE_ENGINE_ENABLED: true },
    db,
    services: {
      eventBus: {
        publishVolatile(event: Record<string, unknown>) {
          events.push(event);
          return Promise.resolve(event);
        },
      },
    },
  };

  const result = await processDueProactiveTriggers(app as never, {
    limit: 1,
    now,
    compose: async () => ({
      text: "Dunku deploy nasil gitti? Bir sorun varsa beraber toparlayalim.",
    }),
  });

  assert.deepEqual(result, { processed: 1, fired: 1, expired: 0, deferred: 0, failed: 0 });
  assert.equal(db.insertedRows[0]?.table, chatMessages);
  assert.equal(db.insertedRows[0]?.values.userId, userId);
  assert.equal(db.insertedRows[0]?.values.sessionId, sessionId);
  assert.equal(db.insertedRows[0]?.values.role, "assistant");
  assert.equal(
    db.updates.some((entry) => entry.table === proactiveTriggers && entry.values.status === "fired"),
    true,
  );
  assert.deepEqual(
    events.map((event) => event.topic),
    ["message.created", "message.completed"],
  );
});

test("processBrainWorkerIteration drains memory jobs before decay and still processes proactive triggers", async () => {
  let memoryCalls = 0;
  let decayCalls = 0;
  let proactiveCalls = 0;

  const result = await processBrainWorkerIteration({} as never, {
    memoryBatch: 5,
    processMemoryJob: async () => {
      memoryCalls += 1;
      return memoryCalls <= 2;
    },
    processDecay: async () => {
      decayCalls += 1;
      return {
        status: "completed" as const,
        processedCount: 10,
        updatedCount: 10,
      };
    },
    processProactive: async () => {
      proactiveCalls += 1;
      return { processed: 1, fired: 1, expired: 0, deferred: 0, failed: 0 };
    },
  });

  assert.equal(memoryCalls, 3);
  assert.equal(decayCalls, 0);
  assert.equal(proactiveCalls, 1);
  assert.deepEqual(result, {
    memoryJobsProcessed: 2,
    memoryDecayProcessed: 0,
    memoryDecayUpdated: 0,
    proactive: { processed: 1, fired: 1, expired: 0, deferred: 0, failed: 0 },
  });
});

test("processBrainWorkerIteration runs decay when no memory job is queued", async () => {
  const result = await processBrainWorkerIteration({} as never, {
    processMemoryJob: async () => false,
    processDecay: async () => ({
      status: "completed" as const,
      processedCount: 8,
      updatedCount: 3,
    }),
    processProactive: async () => ({ processed: 0, fired: 0, expired: 0, deferred: 0, failed: 0 }),
  });

  assert.deepEqual(result, {
    memoryJobsProcessed: 0,
    memoryDecayProcessed: 8,
    memoryDecayUpdated: 3,
    proactive: { processed: 0, fired: 0, expired: 0, deferred: 0, failed: 0 },
  });
});
