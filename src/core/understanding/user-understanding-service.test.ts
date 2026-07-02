import assert from "node:assert/strict";
import test from "node:test";
import {
  emptyUnderstanding,
  persistLearningSignals,
  recordBlockQualityLearning,
  recordBridgeLearningSignals,
  recordTaskFeedback,
  recordTaskLearningFromCompletion,
} from "./user-understanding-service.js";

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
