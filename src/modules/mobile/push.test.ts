import assert from "node:assert/strict";
import test from "node:test";
import { buildPushMessage } from "./push.js";

function taskEvent(status: string, approvalRequest?: Record<string, unknown>) {
  return {
    id: 42,
    topic: "task.updated",
    userId: "user_1",
    taskId: "task_1",
    createdAt: "2030-01-01T00:00:00.000Z",
    payload: {
      task: {
        id: "task_1",
        title: "Rapor",
        status,
        approvalRequest,
      },
    },
  };
}

test("mobile push suppresses non-actionable task and chat updates", () => {
  assert.equal(buildPushMessage(taskEvent("planning")), null);
  assert.equal(buildPushMessage(taskEvent("running")), null);
  assert.equal(
    buildPushMessage({
      topic: "chat.message.created",
      userId: "user_1",
      createdAt: "2030-01-01T00:00:00.000Z",
      payload: {},
    }),
    null,
  );
});

test("mobile push identifies one actionable approval revision", () => {
  const message = buildPushMessage(
    taskEvent("waiting_approval", {
      kind: "desktop_action",
      approvalKey: "approval_1",
      revision: 2,
      resolution: { state: "pending" },
    }),
  );

  assert.equal(message?.body, "Rapor onay bekliyor.");
  assert.equal(message?.collapseId, "task-task_1-approval");
  assert.equal(message?.dedupeKey, "waiting:approval_1");
});

test("mobile push labels clarification separately from permission approval", () => {
  const message = buildPushMessage(
    taskEvent("waiting_approval", {
      kind: "clarification",
      approvalKey: "question_1",
      resolution: { state: "pending" },
    }),
  );

  assert.equal(message?.body, "Rapor için ek bilgi gerekiyor.");
  assert.equal(message?.collapseId, "task-task_1-question");
});

test("mobile push emits terminal results once per status identity", () => {
  const message = buildPushMessage(taskEvent("completed"));

  assert.equal(message?.body, "Rapor tamamlandı.");
  assert.equal(message?.collapseId, "task-task_1-result");
  assert.equal(message?.dedupeKey, "terminal:task_1:completed");
});
