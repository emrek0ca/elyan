import assert from "node:assert/strict";
import test from "node:test";
import { buildTaskTraceBlock } from "./task-trace.js";

test("buildTaskTraceBlock adds human-readable phase metadata", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-1",
      status: "completed",
      payload: {
        metadata: {
          understanding: {
            intent: {
              primaryIntent: "chat",
            },
          },
        },
      },
      result: {
        brain: {
          qualityPolicyApplied: true,
        },
      },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Hazır.",
  });

  assert.equal(block.progressLabel, "Yanıt hazır");
  assert.equal(block.phase, "response");
  assert.equal(block.summary, "Kontrol tamam.");
  assert.equal(block.activeStepId, undefined);
});

test("buildTaskTraceBlock describes the active running phase", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-2",
      status: "running",
      payload: {},
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:01.000Z"),
    },
    assistantContent: "",
  });

  assert.equal(block.status, "running");
  assert.equal(block.progressLabel, "İsteği okuyor");
  assert.equal(block.phase, "intent");
  assert.equal(block.activeStepId, "intent");
  assert.equal(block.summary, "İstek netleşiyor.");
});
