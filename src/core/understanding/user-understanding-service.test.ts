import assert from "node:assert/strict";
import test from "node:test";
import {
  buildSynchronousMemoryOpsFromLearningSignals,
  buildTaskUnderstanding,
  emptyUnderstanding,
  persistLearningSignals,
  recordBlockQualityLearning,
  recordBridgeLearningSignals,
  recordTaskFeedback,
  recordTaskLearningFromCompletion,
} from "./user-understanding-service.js";

function createLearningMemoryFakeApp() {
  const learningRows: unknown[] = [];
  const memoryFacts: Array<Record<string, unknown>> = [];

  const db: any = {
    transaction<T>(fn: (tx: typeof db) => Promise<T>) {
      return fn(db);
    },
    insert() {
      return {
        values: async (values: unknown[] | Record<string, unknown>) => {
          if (Array.isArray(values)) {
            learningRows.push(...values);
            return;
          }
          memoryFacts.push(values);
        },
      };
    },
    update() {
      return {
        set(values: Record<string, unknown>) {
          for (const row of memoryFacts) {
            Object.assign(row, values);
          }
          return {
            where: async () => [],
          };
        },
      };
    },
    select() {
      return {
        from() {
          return this;
        },
        where() {
          return this;
        },
        limit: async () => [],
      };
    },
  };

  return {
    app: {
      config: {
        ELYAN_LEARNING_EXTRACTION_ENABLED: true,
        ELYAN_MEMORY_FABRIC_V2_ENABLED: true,
      },
      db,
      log: {
        info: () => undefined,
        warn: () => undefined,
        debug: () => undefined,
      },
    } as never,
    learningRows,
    memoryFacts,
  };
}

test("emptyUnderstanding keeps best-effort answering enabled instead of forcing clarification", () => {
  const result = emptyUnderstanding({
    userId: "00000000-0000-0000-0000-000000000001",
    accountId: "00000000-0000-0000-0000-000000000001",
    message: "z = x^5 - y^2 fonksiyonunun 3 boyutlu grafiğini çiz",
    metadata: {},
  });

  assert.equal(result.intent.taskFrame.shouldClarify, false);
  assert.equal(result.context.taskFrame.shouldClarify, false);
  assert.equal(result.context.clarificationDiagnostics.shouldClarify, false);
  assert.equal(result.context.clarificationDiagnostics.ambiguityKind, "none");
});

test("buildTaskUnderstanding only adds neutral envelope when envelope flags are enabled", async () => {
  const input = {
    userId: "00000000-0000-0000-0000-000000000001",
    accountId: "00000000-0000-0000-0000-000000000001",
    message: "Merhaba",
    metadata: {},
  };
  const log = {
    info: () => undefined,
    warn: () => undefined,
    debug: () => undefined,
  };

  const disabled = await buildTaskUnderstanding({
    config: {
      ELYAN_USER_UNDERSTANDING_ENABLED: false,
      ELYAN_UNDERSTANDING_ENVELOPE_V2_ENABLED: false,
      ELYAN_UNDERSTANDING_ENVELOPE_SHADOW_ENABLED: false,
      ELYAN_UNDERSTANDING_ENVELOPE_MODEL_FALLBACK_ENABLED: false,
    },
    log,
  } as never, input);
  assert.equal(disabled.envelope, undefined);

  const enabled = await buildTaskUnderstanding({
    config: {
      ELYAN_USER_UNDERSTANDING_ENABLED: false,
      ELYAN_UNDERSTANDING_ENVELOPE_V2_ENABLED: true,
      ELYAN_UNDERSTANDING_ENVELOPE_SHADOW_ENABLED: false,
      ELYAN_UNDERSTANDING_ENVELOPE_MODEL_FALLBACK_ENABLED: false,
    },
    log,
  } as never, input);
  assert.equal(enabled.envelope?.schema_version, "2026-07-understanding-envelope-v2");
  assert.equal(enabled.envelopeSource, "legacy_fallback");
});

test("persistLearningSignals stores only policy-approved safe events", async () => {
  const inserted: unknown[] = [];
  const app = {
    config: {
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
    db: {
      insert: () => ({
        values: async (values: unknown[]) => {
          inserted.push(...values);
        },
      }),
    },
    log: {
      info: () => undefined,
      warn: () => undefined,
    },
  };

  const count = await persistLearningSignals(app as never, {
    userId: "00000000-0000-0000-0000-000000000001",
    taskId: "00000000-0000-0000-0000-000000000002",
    signals: [
      {
        type: "style",
        key: "answer_length",
        value: "concise",
        confidence: 0.82,
        scope: "user",
        source: "interaction",
        ttlDays: null,
      },
      {
        type: "preference",
        key: "secret",
        value: "password is hunter2",
        confidence: 0.95,
        scope: "user",
        source: "interaction",
        ttlDays: null,
      },
    ],
    requestId: "req_1",
  });

  assert.equal(count, 1);
  assert.equal(inserted.length, 1);
  assert.equal((inserted[0] as { key: string }).key, "answer_length");
});

test("buildSynchronousMemoryOpsFromLearningSignals keeps explicit durable profile and style facts", () => {
  const ops = buildSynchronousMemoryOpsFromLearningSignals([
    {
      type: "identity",
      key: "preferred_name",
      value: "Emre",
      confidence: 0.96,
      scope: "user",
      source: "interaction",
      ttlDays: null,
      metadata: { explicit: true },
    },
    {
      type: "style",
      key: "answer_length",
      value: "concise",
      confidence: 0.82,
      scope: "user",
      source: "interaction",
      ttlDays: null,
      metadata: { explicit: true },
    },
    {
      type: "identity",
      key: "preferred_language",
      value: "turkish",
      confidence: 0.82,
      scope: "user",
      source: "interaction",
      ttlDays: null,
    },
  ]);

  assert.deepEqual(ops, [
    {
      op: "write",
      kind: "preference",
      key: "preferred_name",
      value: "Emre",
      confidence: 0.96,
      ttl_days: undefined,
    },
    {
      op: "write",
      kind: "preference",
      key: "answer_length",
      value: "concise",
      confidence: 0.82,
      ttl_days: undefined,
    },
  ]);
});

test("persistLearningSignals synchronously writes explicit preferred name and style into memory fabric", async () => {
  const fake = createLearningMemoryFakeApp();

  const count = await persistLearningSignals(fake.app, {
    userId: "00000000-0000-0000-0000-000000000001",
    taskId: "00000000-0000-0000-0000-000000000002",
    signals: [
      {
        type: "identity",
        key: "preferred_name",
        value: "Emre",
        confidence: 0.96,
        scope: "user",
        source: "interaction",
        ttlDays: null,
        metadata: { explicit: true, sourceTurnId: "00000000-0000-0000-0000-000000000002" },
      },
      {
        type: "style",
        key: "brevity_preference",
        value: "short",
        confidence: 0.92,
        scope: "user",
        source: "interaction",
        ttlDays: null,
        metadata: { explicit: true, sourceTurnId: "00000000-0000-0000-0000-000000000002" },
      },
    ],
    requestId: "req_2",
  });

  assert.equal(count, 2);
  assert.equal(fake.learningRows.length, 2);
  assert.equal(fake.memoryFacts.length, 2);
  assert.equal(fake.memoryFacts[0]?.canonicalKey, "preferred_name");
  assert.equal(fake.memoryFacts[0]?.value, "Emre");
  assert.equal(fake.memoryFacts[0]?.confidence, 96);
  assert.equal(fake.memoryFacts[1]?.canonicalKey, "brevity_preference");
  assert.equal(fake.memoryFacts[1]?.value, "short");
  assert.equal(fake.memoryFacts[1]?.confidence, 92);
  assert.equal((fake.memoryFacts[0]?.metadata as { source?: string } | undefined)?.source, "turn_envelope");
});

test("recordBridgeLearningSignals stores safe routing and bridge outcome signals", async () => {
  const inserted: unknown[] = [];
  const app = {
    config: {
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
    db: {
      insert: () => ({
        values: async (values: unknown[]) => {
          inserted.push(...values);
        },
      }),
    },
    log: {
      info: () => undefined,
      warn: () => undefined,
    },
  };

  const count = await recordBridgeLearningSignals(app as never, {
    userId: "00000000-0000-0000-0000-000000000001",
    taskId: "00000000-0000-0000-0000-000000000002",
    target: "server_brain",
    outcome: "completed",
    readiness: "ready",
    routingMode: "server_brain_first",
    requestId: "req_2",
  });

  assert.equal(count, 6);
  assert.equal(inserted.length, 6);
  assert.equal((inserted[0] as { type: string }).type, "routing");
  assert.equal((inserted[1] as { key: string }).key, "routing_outcome");
  assert.equal((inserted[2] as { key: string }).key, "bridge_readiness");
  assert.equal((inserted[3] as { key: string }).key, "routing_mode");
  assert.equal((inserted[4] as { key: string }).key, "task_handoff_state");
  assert.equal((inserted[5] as { key: string }).key, "task_handoff_helpfulness");
});

test("recordTaskLearningFromCompletion stores terminal and completion state signals", async () => {
  const inserted: unknown[] = [];
  const app = {
    config: {
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
    db: {
      insert: () => ({
        values: async (values: unknown[]) => {
          inserted.push(...values);
        },
      }),
    },
    log: {
      info: () => undefined,
      warn: () => undefined,
    },
  };

  const count = await recordTaskLearningFromCompletion(app as never, {
    userId: "00000000-0000-0000-0000-000000000001",
    taskId: "00000000-0000-0000-0000-000000000002",
    title: "Fix auth",
    message: "Task completed successfully with the backend update.",
    status: "completed",
    requestId: "req_3",
  });

  assert.equal(count, inserted.length);
  assert.ok(inserted.some((item) => (item as { key?: string }).key === "task_completed"));
  assert.ok(inserted.some((item) => (item as { key?: string }).key === "task_completion_state"));
});

test("recordBlockQualityLearning stores safe block quality feedback signals", async () => {
  const inserted: unknown[] = [];
  const app = {
    config: {
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
    db: {
      insert: () => ({
        values: async (values: unknown[]) => {
          inserted.push(...values);
        },
      }),
    },
    log: {
      info: () => undefined,
      warn: () => undefined,
    },
  };

  const count = await recordBlockQualityLearning(app as never, {
    userId: "00000000-0000-0000-0000-000000000001",
    taskId: "00000000-0000-0000-0000-000000000002",
    quality: {
      version: "elyan_block_quality.v1",
      score: 66,
      feedbackSignals: [
        "duplicate_table_block",
        "raw_json_leak_prevented",
        "unsupported_signal",
      ],
      blockTypes: ["table", "text"],
      metrics: {
        duplicateTableBlockCount: 1,
        rawJsonLeakPreventedCount: 1,
      },
    },
    requestId: "req_block_quality",
  });

  assert.equal(count, 3);
  assert.equal(inserted.length, 3);
  assert.ok(
    inserted.every((item) => (item as { key?: string }).key === "block_output_quality"),
  );
  assert.deepEqual(
    inserted.map((item) => (item as { value?: string }).value).sort(),
    ["duplicate_table_block", "needs_repair", "raw_json_leak_prevented"],
  );
  assert.ok(
    inserted.every(
      (item) =>
        ((item as { metadata?: Record<string, unknown> }).metadata?.score as number) === 66,
    ),
  );
});

test("recordTaskFeedback stores a compact workflow outcome signal", async () => {
  const inserted: unknown[] = [];
  const app = {
    config: {
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
    db: {
      insert: () => ({
        values: async (values: unknown[]) => {
          inserted.push(...values);
        },
      }),
    },
    log: {
      info: () => undefined,
      warn: () => undefined,
    },
  };

  const count = await recordTaskFeedback(app as never, {
    userId: "00000000-0000-0000-0000-000000000001",
    taskId: "00000000-0000-0000-0000-000000000002",
    feedbackType: "thumbs_down",
    reasonTags: ["too_long", "misunderstood"],
    correction: "Please be shorter and preserve the existing architecture.",
    requestId: "req_4",
  });

  assert.equal(count, inserted.length);
  assert.ok(inserted.some((item) => (item as { key?: string }).key === "feedback_outcome"));
  assert.ok(inserted.some((item) => (item as { key?: string }).key === "negative_feedback"));
});
