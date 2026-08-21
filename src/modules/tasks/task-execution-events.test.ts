import assert from "node:assert/strict";
import test from "node:test";
import { buildTaskExecutionEvent } from "./task-execution-events.js";

test("task execution event has stable replay/fencing fields", () => {
  const event = buildTaskExecutionEvent({
    type: "step.started",
    taskId: "task-1",
    turnId: "turn-1",
    planRevision: 3,
    stepId: "step-2",
    attempt: 2,
    eventId: "event-1",
    evidenceRefs: ["evidence-1", "evidence-1"],
  });

  assert.deepEqual(event, {
    eventId: "event-1",
    type: "step.started",
    taskId: "task-1",
    turnId: "turn-1",
    planRevision: 3,
    stepId: "step-2",
    attempt: 2,
    occurredAt: event.occurredAt,
    payload: {},
    evidenceRefs: ["evidence-1"],
  });
});
