import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTaskApprovalResumeUpdate,
  buildTaskApprovalResolution,
  buildTaskCancellationUpdate,
  buildTaskDispatchLeaseAckUpdate,
  buildTaskRuntimeOwnershipUpdate,
  buildTaskRuntimeUpdate,
  isApprovalAlreadyResolved,
  isApprovalRequestExpired,
  normalizeTaskApprovalRequest,
  shouldAutoApproveDesktopTask,
} from "./service-lifecycle.js";

test("shouldAutoApproveDesktopTask trusts only backend mode plus explicit idempotent classification", () => {
  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "write",
      idempotency: "idempotent_write",
      capability: "document_write",
      steps: [{ capability: "document_write" }],
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        routeDecision: {
          route: "desktop_runtime",
          taskRoute: { operationalRoute: "desktop_runtime" },
        },
      },
    },
  }), true);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "read_only_auto",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "write",
      idempotency: "idempotent_write",
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        desktopFullAuthorityEnabled: true,
        routeDecision: { route: "desktop_runtime" },
      },
    },
  }), false);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "write",
      idempotency: "idempotent_write",
      manualApprovalRequired: true,
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        routeDecision: { route: "desktop_runtime" },
      },
    },
  }), false);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "side_effect",
      idempotency: "non_idempotent",
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        desktopFullAuthorityEnabled: true,
        routeDecision: { route: "desktop_runtime" },
      },
    },
  }), false);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "write",
      idempotency: "idempotent_write",
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        routeDecision: { route: "server_brain" },
      },
    },
  }), false);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        routeDecision: { route: "desktop_runtime" },
      },
    },
  }), false);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "write",
      idempotency: "idempotent_write",
      capability: "unknown.write",
      steps: [{ capability: "unknown.write" }],
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        routeDecision: { route: "desktop_runtime" },
      },
    },
  }), false);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "write",
      idempotency: "idempotent_write",
      capability: "image_generate",
      steps: [{ capability: "image_generate" }],
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        routeDecision: { route: "desktop_runtime" },
      },
    },
  }), false);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "write",
      idempotency: "idempotent_write",
      capability: "document_write",
      steps: [
        { capability: "web_research" },
        { capability: "math_solve" },
        { capability: "text_analyze" },
        { capability: "document_write" },
      ],
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        routeDecision: { route: "desktop_runtime" },
      },
    },
  }), true);

  assert.equal(shouldAutoApproveDesktopTask({
    status: "waiting_approval",
    approvalMode: "trusted_idempotent_writes",
    approvalRequest: {
      source: "desktop_runtime",
      permission: "write",
      idempotency: "idempotent_write",
      capability: "document_write",
      steps: [{ capability: "document_write", overwrite: true }],
    },
    payload: {
      metadata: {
        desktopDispatch: true,
        routeDecision: { route: "desktop_runtime" },
      },
    },
  }), false);
});

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
      revision: 1,
      approvalKey: null,
    },
  });
});

test("normalizeTaskApprovalRequest creates a single expiring full-access surface", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const normalized = normalizeTaskApprovalRequest(
    {
      permission: "write",
      idempotency: "idempotent_write",
      capability: "document_write",
    },
    { taskId: "task-1", now },
  );

  assert.equal(normalized.approvalKey, "task-1:1");
  assert.equal(normalized.revision, 1);
  assert.equal(normalized.permissionSurface, "full_computer_access");
  assert.equal(normalized.surface, "full_computer_access");
  assert.equal(normalized.expiresAt, "2030-01-01T00:10:00.000Z");
  assert.equal(isApprovalRequestExpired(normalized, now), false);
  assert.equal(isApprovalRequestExpired(normalized, new Date("2030-01-01T00:10:00.001Z")), true);
});

test("isApprovalAlreadyResolved detects approved and rejected resolutions", () => {
  assert.equal(isApprovalAlreadyResolved({ resolution: { approved: true } }), true);
  assert.equal(isApprovalAlreadyResolved({ resolution: { approved: false } }), true);
  assert.equal(isApprovalAlreadyResolved({ resolution: { state: "pending" } }), false);
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
    source: "desktop_runtime",
    approvalKey: "task:1",
    revision: 1,
    expiresAt: "2030-01-01T00:10:00.000Z",
    surface: "full_computer_access",
    permissionSurface: "full_computer_access",
    permissionSummary: "Elyan bu görevi tamamlamak için bilgisayar erişimini tek onay altında kullanacak.",
    resolution: {
      approved: true,
      notes: "Approved for execution",
      resolvedAt: now.toISOString(),
      revision: 1,
      approvalKey: "task:1",
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
