import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTaskApprovalResumeUpdate,
  buildTaskApprovalResolution,
  buildTaskCancellationUpdate,
  buildTaskDispatchLeaseAckUpdate,
  buildTaskRuntimeOwnershipUpdate,
  buildTaskRuntimeUpdate,
} from "./service-lifecycle.js";

test("buildTaskCancellationUpdate clears the queue and stamps canceledAt", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const update = buildTaskCancellationUpdate(now);

  assert.equal(update.status, "canceled");
  assert.equal(update.queuePosition, 0);
  assert.equal(update.canceledAt, now);
  assert.equal(update.updatedAt, now);
});

test("buildTaskApprovalResolution merges the existing request and appends the resolution", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const approvalRequest = {
    title: "Mail gönderilsin mi?",
    message: "Alıcı: ali@example.com\nKonu: Atatürk hakkında notlar",
    summary: "Atatürk araştırması sonrası mail gönderimi onay bekliyor.",
    reason: "Sensitive browser action",
  };

  const resolved = buildTaskApprovalResolution(approvalRequest, {
    notes: "Approved for execution",
    now,
  });

  assert.deepEqual(resolved, {
    title: "Mail gönderilsin mi?",
    message: "Alıcı: ali@example.com\nKonu: Atatürk hakkında notlar",
    summary: "Atatürk araştırması sonrası mail gönderimi onay bekliyor.",
    reason: "Sensitive browser action",
    resolution: {
      approved: true,
      notes: "Approved for execution",
      resolvedAt: now.toISOString(),
    },
  });
});

test("buildTaskApprovalResumeUpdate keeps approved tasks waiting for runtime resume", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const update = buildTaskApprovalResumeUpdate(
    {
      startedAt: null,
      approvalRequest: {
        title: "Mail gönderilsin mi?",
        message: "Alıcı: ali@example.com",
        summary: "Mail gönderimi onay bekliyor.",
      },
    },
    {
      notes: "Approved for execution",
      now,
    },
  );

  assert.equal(update.status, "waiting_approval");
  assert.equal(update.startedAt, undefined);
  assert.equal(update.updatedAt, now);
  assert.equal(update.summary, "Onay alındı. Görev devam ediyor.");
  assert.equal(update.error, null);
  assert.deepEqual(update.approvalRequest, {
    title: "Mail gönderilsin mi?",
    message: "Alıcı: ali@example.com",
    summary: "Mail gönderimi onay bekliyor.",
    resolution: {
      approved: true,
      notes: "Approved for execution",
      resolvedAt: now.toISOString(),
    },
  });
});

test("buildTaskRuntimeOwnershipUpdate stamps the active runtime connection", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const update = buildTaskRuntimeOwnershipUpdate({
    runtimeConnectionId: "runtime-1",
    now,
  });

  assert.equal(update.runtimeConnectionId, "runtime-1");
  assert.equal(update.updatedAt, now);
});

test("buildTaskDispatchLeaseAckUpdate preserves local acceptedAt when provided", () => {
  const now = new Date("2030-01-01T00:00:05.000Z");
  const acceptedAt = new Date("2030-01-01T00:00:03.000Z");
  const update = buildTaskDispatchLeaseAckUpdate({
    runtimeConnectionId: "runtime-1",
    leaseId: "lease-1",
    now,
    acceptedAt,
  });

  assert.equal(update.status, "running");
  assert.equal(update.runtimeConnectionId, "runtime-1");
  assert.equal(update.dispatchAckAt, acceptedAt);
  assert.equal(update.startedAt, acceptedAt);
  assert.equal(update.updatedAt, now);
});

test("buildTaskRuntimeUpdate keeps lifecycle fields aligned with task status", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const runningUpdate = buildTaskRuntimeUpdate(
    {
      startedAt: null,
      summary: null,
      error: null,
      approvalRequest: null,
      result: null,
    },
    {
      status: "running",
      runtimeConnectionId: "runtime-1",
      now,
      summary: "Working",
    },
  );

  const completedUpdate = buildTaskRuntimeUpdate(
    {
      startedAt: now,
      summary: null,
      error: null,
      approvalRequest: null,
      result: null,
    },
    {
      status: "completed",
      runtimeConnectionId: "runtime-1",
      now,
    },
  );

  const canceledUpdate = buildTaskRuntimeUpdate(
    {
      startedAt: now,
      summary: null,
      error: null,
      approvalRequest: null,
      result: null,
    },
    {
      status: "canceled",
      runtimeConnectionId: "runtime-1",
      now,
    },
  );

  assert.equal(runningUpdate.startedAt, now);
  assert.equal(runningUpdate.summary, "Working");
  assert.equal(runningUpdate.runtimeConnectionId, "runtime-1");
  assert.equal(completedUpdate.completedAt, now);
  assert.equal(completedUpdate.queuePosition, 0);
  assert.equal(canceledUpdate.canceledAt, now);
  assert.equal(canceledUpdate.queuePosition, 0);
});
