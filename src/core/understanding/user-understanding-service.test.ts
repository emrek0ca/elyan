import assert from "node:assert/strict";
import test from "node:test";
import {
  persistLearningSignals,
  recordBridgeLearningSignals,
  recordTaskFeedback,
  recordTaskLearningFromCompletion,
} from "./user-understanding-service.js";

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
