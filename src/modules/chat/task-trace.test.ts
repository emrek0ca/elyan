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

function toolStepOf(block: ReturnType<typeof buildTaskTraceBlock>) {
  return block.steps.find((step) => step.id === "tool");
}

test("buildTaskTraceBlock surfaces server-side connector tool calls", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-tool-1",
      status: "completed",
      payload: {},
      result: {
        toolFlow: {
          count: 1,
          okCount: 1,
          tools: [{ name: "gmail.search", ok: true, resultCount: 3 }],
        },
      },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Son üç e-postan burada.",
  });

  const toolStep = toolStepOf(block);
  assert.equal(toolStep?.status, "completed");
  assert.equal(toolStep?.detail, "Gmail · 3 sonuç");
});

test("buildTaskTraceBlock reads tool flow from feed-shaped brain metadata", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-tool-2",
      status: "completed",
      payload: {},
      result: {
        brain: {
          toolFlow: {
            count: 2,
            okCount: 2,
            tools: [
              { name: "gmail.search", ok: true, resultCount: null },
              { name: "calendar.list_events", ok: true, resultCount: null },
            ],
          },
        },
      },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Hazır.",
  });

  assert.equal(toolStepOf(block)?.detail, "Gmail, Takvim kullanıldı");
});

test("buildTaskTraceBlock reports a tool flow that returned nothing", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-tool-3",
      status: "completed",
      payload: {},
      result: {
        toolFlow: {
          count: 1,
          okCount: 0,
          tools: [{ name: "drive.search", ok: false, resultCount: null }],
        },
      },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Bir şey bulamadım.",
  });

  assert.equal(toolStepOf(block)?.detail, "Drive denendi");
});

test("buildTaskTraceBlock still reports no tool when none ran", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-tool-4",
      status: "completed",
      payload: {},
      result: { text: "Merhaba!" },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Merhaba!",
  });

  const toolStep = toolStepOf(block);
  assert.equal(toolStep?.status, "skipped");
  assert.equal(toolStep?.detail, "Araç gerekmedi.");
});
