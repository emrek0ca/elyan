import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTaskApprovalResumeUpdate,
  extractPublicInteraction,
  buildTaskApprovalResolution,
  buildTaskCancellationUpdate,
  buildTaskDispatchLeaseAckUpdate,
  buildTaskRuntimeOwnershipUpdate,
  buildTaskRuntimeUpdate,
  buildPublicTaskApprovalEventFields,
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
      action: "approve",
      state: "approved",
      resolvedAt: now.toISOString(),
      revision: 1,
      approvalKey: null,
    },
  });
});

test("buildPublicTaskApprovalEventFields exposes identity without approval secrets", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const fields = buildPublicTaskApprovalEventFields(
    {
      approvalKey: "task-1:2",
      token: "secret-token-must-not-leak",
      revision: 2,
      resolution: {
        approved: true,
        notes: "private approval note",
        resolvedAt: now.toISOString(),
        revision: 2,
      },
    },
    { status: "queued", updatedAt: now },
  );

  assert.deepEqual(fields, {
    approvalKey: "task-1:2",
    approvalRevision: 2,
    status: "queued",
    resolution: {
      approved: true,
      state: "approved",
      resolvedAt: now.toISOString(),
      revision: 2,
    },
    updatedAt: now.toISOString(),
  });
  assert.equal("token" in fields, false);
  assert.equal("notes" in (fields.resolution ?? {}), false);
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
  assert.equal(normalized.interaction.contract, "elyan.interaction.v1");
  assert.equal(normalized.interaction.taskId, "task-1");
  assert.equal(normalized.interaction.taskRunId, "task-1");
  assert.equal(normalized.interaction.kind, "permission");
  assert.deepEqual(normalized.interaction.availableActions, ["approve", "reject"]);
  assert.deepEqual(normalized.availableActions, ["approve", "reject"]);
  assert.equal(normalized.expiresAt, "2030-01-01T00:01:00.000Z");
  assert.equal(isApprovalRequestExpired(normalized, now), false);
  assert.equal(isApprovalRequestExpired(normalized, new Date("2030-01-01T00:10:00.001Z")), true);
});

test("nested interaction expiry is authoritative during the migration", () => {
  const request = {
    interaction: {
      contract: "elyan.interaction.v1",
      id: "interaction-1",
      taskId: "task-1",
      taskRunId: "run-1",
      kind: "clarification",
      revision: 4,
      availableActions: ["answer"],
      question: "Hangi klasöre kaydedeyim?",
      expiresAt: "2030-01-01T00:01:00.000Z",
      resolution: null,
    },
  };

  assert.equal(
    isApprovalRequestExpired(request, new Date("2030-01-01T00:01:00.001Z")),
    true,
  );
  const normalized = normalizeTaskApprovalRequest(request, {
    taskId: "task-1",
    now: new Date("2030-01-01T00:00:00.000Z"),
  });
  assert.equal(normalized.interaction.id, "interaction-1");
  assert.equal(normalized.interaction.revision, 4);
  assert.equal(normalized.expiresAt, "2030-01-01T00:01:00.000Z");
});

test("normalizeTaskApprovalRequest keeps clarification separate from permissions", () => {
  const normalized = normalizeTaskApprovalRequest(
    {
      kind: "clarification",
      question: "Hangi klasörü kullanayım?",
      surface: "full_computer_access",
      permissionSurface: "full_computer_access",
      permissionSummary: "Yanlış izin özeti",
    },
    { taskId: "task-clarification", now: new Date("2030-01-01T00:00:00.000Z") },
  );

  assert.equal(normalized.kind, "clarification");
  assert.equal(normalized.surface, "clarification");
  assert.equal(normalized.interaction.contract, "elyan.interaction.v1");
  assert.equal(normalized.interaction.taskId, "task-clarification");
  assert.equal(normalized.interaction.kind, "clarification");
  assert.equal(normalized.interaction.question, "Hangi klasörü kullanayım?");
  assert.deepEqual(normalized.interaction.availableActions, ["answer"]);
  assert.deepEqual(normalized.availableActions, ["answer"]);
  assert.equal("permissionSurface" in normalized, false);
  assert.equal("permissionSummary" in normalized, false);
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
  const updatedApproval = update.approvalRequest as Record<string, unknown>;
  const { interaction, ...legacyApproval } = updatedApproval;
  assert.deepEqual(legacyApproval, {
    title: "Mail gönderilsin mi?",
    message: "Alıcı: ali@example.com",
    summary: "Mail gönderimi onay bekliyor.",
    kind: "permission",
    source: "desktop_runtime",
    approvalKey: "task:1",
    revision: 1,
    expiresAt: "2030-01-01T00:01:00.000Z",
    surface: "full_computer_access",
    permissionSurface: "full_computer_access",
    availableActions: ["approve", "reject"],
    permissionSummary: "Elyan bu görevi tamamlamak için bilgisayar erişimini tek onay altında kullanacak.",
    resolution: {
      approved: true,
      notes: "Approved for execution",
      action: "approve",
      state: "approved",
      resolvedAt: now.toISOString(),
      revision: 1,
      approvalKey: "task:1",
    },
  });
  assert.deepEqual(interaction, {
    contract: "elyan.interaction.v1",
    id: "task:interaction:1",
    taskId: "task",
    taskRunId: "task",
    kind: "permission",
    revision: 1,
    availableActions: ["approve", "reject"],
    question: "Alıcı: ali@example.com",
    summary: "Mail gönderimi onay bekliyor.",
    expiresAt: "2030-01-01T00:01:00.000Z",
    resolution: {
      approved: true,
      notes: "Approved for execution",
      action: "approve",
      state: "approved",
      resolvedAt: now.toISOString(),
      revision: 1,
      approvalKey: "task:1",
    },
  });
});

test("buildTaskApprovalResumeUpdate labels a clarification answer as information, not approval", () => {
  const update = buildTaskApprovalResumeUpdate(
    {
      id: "task-clarification",
      startedAt: null,
      approvalRequest: {
        kind: "clarification",
        question: "Hangi klasöre kaydedeyim?",
      },
    },
    { notes: "~/Desktop", now: new Date("2030-01-01T00:00:00.000Z") },
  );

  assert.equal(update.summary, "Bilgi yanıtı alındı. Görev devam ediyor.");
  const approval = update.approvalRequest as Record<string, unknown>;
  const interaction = approval.interaction as Record<string, unknown>;
  assert.equal(interaction.kind, "clarification");
  assert.deepEqual(interaction.availableActions, ["answer"]);
  assert.equal((interaction.resolution as Record<string, unknown>).approved, true);
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

// ── Kanonik etkileşim zarfı: expiry ve iç içe çözüm ─────────────────────────
// Zarf ve eski düz alanlar aynı gerçeği iki yerde taşır. Süre ve çözüm
// bilgisi hangisinde yazılıysa oradan okunmalı; aksi halde çözülmüş bir
// etkileşim yeniden "bekliyor" gibi görünür.

test("expiry is read from the nested interaction envelope, not only the flat field", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const expired = {
    kind: "permission",
    interaction: {
      contract: "elyan.interaction.v1",
      id: "task-x:interaction:1",
      taskId: "task-x",
      taskRunId: "run-x",
      kind: "permission",
      revision: 1,
      availableActions: ["approve", "reject"],
      expiresAt: "2029-12-31T23:59:00.000Z",
      resolution: null,
    },
  };
  assert.equal(isApprovalRequestExpired(expired, now), true);

  const live = {
    ...expired,
    interaction: { ...expired.interaction, expiresAt: "2030-01-01T00:05:00.000Z" },
  };
  assert.equal(isApprovalRequestExpired(live, now), false);

  // Süresi geçmiş bir zarf normalize edilirken yeniden canlandırılır; onay
  // penceresi sunucunun TTL'ine göre yeniden açılır, bayat değere sabitlenmez.
  const normalized = normalizeTaskApprovalRequest(expired, { taskId: "task-x", now });
  assert.equal(Date.parse(normalized.expiresAt) > now.getTime(), true);
  assert.equal(normalized.interaction.expiresAt, normalized.expiresAt);
});

test("a resolution stored inside the interaction envelope still counts as resolved", () => {
  const nested = {
    kind: "clarification",
    interaction: {
      contract: "elyan.interaction.v1",
      id: "task-y:interaction:2",
      taskId: "task-y",
      taskRunId: "run-y",
      kind: "clarification",
      revision: 2,
      availableActions: ["answer"],
      question: "Hangi klasöre kaydedeyim?",
      expiresAt: "2030-01-01T00:05:00.000Z",
      resolution: {
        approved: true,
        action: "answer",
        state: "answered",
        answer: "Masaüstüne",
        revision: 2,
      },
    },
  };

  assert.equal(isApprovalAlreadyResolved(nested), true);

  const fields = buildPublicTaskApprovalEventFields(nested, {
    status: "running",
    updatedAt: new Date("2030-01-01T00:00:00.000Z"),
  });
  assert.equal(fields.interactionKind, "clarification");
  assert.equal(fields.interactionRevision, 2);
  assert.equal(fields.resolution?.state, "answered");
  assert.equal(fields.resolution?.approved, true);
  // Serbest metin yanıtı public event alanlarına sızmaz.
  assert.equal("answer" in (fields.resolution ?? {}), false);
});

test("extractPublicInteraction reports pending, resolved and expired without guessing from status", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const pending = extractPublicInteraction(
    { kind: "permission", summary: "Dosya yazılacak.", expiresAt: "2030-01-01T00:05:00.000Z" },
    "task-z",
    now,
  );
  assert.equal(pending?.state, "pending");
  assert.equal(pending?.kind, "permission");
  assert.deepEqual(pending?.availableActions, ["approve", "reject"]);

  const resolved = extractPublicInteraction(
    {
      kind: "clarification",
      question: "Hangi klasör?",
      expiresAt: "2030-01-01T00:05:00.000Z",
      resolution: { approved: true, action: "answer", state: "answered" },
    },
    "task-z",
    now,
  );
  assert.equal(resolved?.state, "resolved");
  assert.deepEqual(resolved?.availableActions, ["answer"]);

  // Boş approval alanı bir etkileşim değildir.
  assert.equal(extractPublicInteraction(null, "task-z", now), null);
  assert.equal(extractPublicInteraction({}, "task-z", now), null);
});

test("a rejected clarification is recorded as a reject, not as an unanswered approval", () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const resolved = buildTaskApprovalResolution(
    { kind: "clarification", interaction: { kind: "clarification" } },
    { approved: false, now },
  ) as Record<string, unknown>;
  const resolution = resolved.resolution as Record<string, unknown>;
  assert.equal(resolution.action, "reject");
  assert.equal(resolution.state, "rejected");
  assert.equal(resolution.approved, false);
  assert.equal("answer" in resolution, false);
});
