import type { TaskStatus } from "../../contracts/domain.js";
import { tasks } from "../../db/schema.js";
import {
  shouldAutomaticallyApproveUserTool,
  type ApprovalToolIdempotency,
  type ApprovalToolPermission,
  type UserApprovalMode,
} from "../approval-policy/policy.js";

export function buildTaskRuntimeOwnershipUpdate(input: { runtimeConnectionId: string; now?: Date }) {
  return {
    runtimeConnectionId: input.runtimeConnectionId,
    updatedAt: input.now ?? new Date(),
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export const TASK_DISPATCH_LEASE_MS = 45_000;
export const TASK_APPROVAL_TTL_MS = 10 * 60_000;
export const MAX_ACTIVE_USER_APPROVALS = 8;
export const MAX_TASK_DISPATCH_ATTEMPTS = 5;

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

export function approvalRequestRevision(approvalRequest: unknown): number {
  const request = readRecord(approvalRequest);
  return Math.max(1, Math.floor(readNumber(request?.revision) ?? 1));
}

export function approvalRequestKey(approvalRequest: unknown): string {
  const request = readRecord(approvalRequest);
  return readString(request?.approvalKey) || readString(request?.token);
}

export function approvalRequestExpiresAt(
  approvalRequest: unknown,
  now: Date = new Date(),
): string {
  const request = readRecord(approvalRequest);
  const existing = readString(request?.expiresAt);
  if (existing) return existing;
  return new Date(now.getTime() + TASK_APPROVAL_TTL_MS).toISOString();
}

export function isApprovalRequestExpired(
  approvalRequest: unknown,
  now: Date = new Date(),
): boolean {
  const expiresAt = readString(readRecord(approvalRequest)?.expiresAt);
  if (!expiresAt) return false;
  const parsed = Date.parse(expiresAt);
  return Number.isFinite(parsed) && parsed <= now.getTime();
}

export function isApprovalAlreadyResolved(approvalRequest: unknown): boolean {
  const resolution = readRecord(readRecord(approvalRequest)?.resolution);
  return resolution?.approved === true || resolution?.approved === false;
}

export function normalizeTaskApprovalRequest(
  approvalRequest: unknown,
  input: {
    taskId: string;
    now?: Date;
  },
) {
  const now = input.now ?? new Date();
  const request = readRecord(approvalRequest) ?? {};
  const revision = approvalRequestRevision(request);
  const existingKey = approvalRequestKey(request);
  const taskKey = readString(input.taskId) || "task";
  return {
    ...request,
    source: readString(request.source) || "desktop_runtime",
    approvalKey: existingKey || `${taskKey}:${revision}`,
    revision,
    expiresAt: approvalRequestExpiresAt(request, now),
    surface: "full_computer_access",
    permissionSurface: "full_computer_access",
    permissionSummary:
      readString(request.permissionSummary) ||
      "Elyan bu görevi tamamlamak için bilgisayar erişimini tek onay altında kullanacak.",
  };
}

const trustedDesktopIdempotentWriteCapabilities = new Set([
  "clipboard_write",
  "document_write",
  "spreadsheet_write",
  "presentation_write",
  "canvas_write",
]);

const trustedDesktopReadOnlyCapabilities = new Set([
  "clipboard_read",
  "data_analyze",
  "desktop_os.permissions",
  "desktop_os.status",
  "directory_tree",
  "document_read",
  "email_draft",
  "file_read",
  "file_search",
  "get_calendar_events",
  "get_reminders",
  "get_weather",
  "get_youtube_channel_report",
  "git_diff",
  "git_status",
  "image_read",
  "latex_parse",
  "math_solve",
  "ocr_read",
  "quantum_compare_classical",
  "quantum_generate_report",
  "quantum_model_problem",
  "quantum_run_experiment",
  "retrieve_context",
  "speech_to_text",
  "sys_info",
  "text_analyze",
  "web_research",
]);

function hasOnlyTrustedDesktopApprovalSteps(approvalRequest: Record<string, unknown>) {
  if (!Array.isArray(approvalRequest.steps) || approvalRequest.steps.length === 0) {
    return false;
  }
  let hasIdempotentWrite = false;
  for (const value of approvalRequest.steps) {
    const step = readRecord(value);
    const capability = typeof step?.capability === "string"
      ? step.capability.trim()
      : "";
    if (step?.overwrite === true) {
      return false;
    }
    if (trustedDesktopIdempotentWriteCapabilities.has(capability)) {
      hasIdempotentWrite = true;
      continue;
    }
    if (!trustedDesktopReadOnlyCapabilities.has(capability)) {
      return false;
    }
  }
  return hasIdempotentWrite;
}

export function shouldAutoApproveDesktopTask(input: {
  status: TaskStatus;
  payload: unknown;
  approvalMode: UserApprovalMode;
  approvalRequest: unknown;
}) {
  if (input.status !== "waiting_approval") return false;

  const payload = readRecord(input.payload);
  const metadata = readRecord(payload?.metadata);
  const routeDecision = readRecord(metadata?.routeDecision);
  const taskRoute = readRecord(routeDecision?.taskRoute);
  const approvalRequest = readRecord(input.approvalRequest);
  const permission = approvalRequest?.permission;
  const idempotency = approvalRequest?.idempotency;
  const capability = typeof approvalRequest?.capability === "string"
    ? approvalRequest.capability.trim()
    : "";
  const safelyClassified = shouldAutomaticallyApproveUserTool({
    mode: input.approvalMode,
    permission:
      permission === "read" || permission === "write" || permission === "side_effect"
        ? (permission as ApprovalToolPermission)
        : undefined,
    idempotency:
      idempotency === "read_only" ||
      idempotency === "idempotent_write" ||
      idempotency === "non_idempotent"
        ? (idempotency as ApprovalToolIdempotency)
        : undefined,
  });

  return metadata?.desktopDispatch === true
    && approvalRequest?.source === "desktop_runtime"
    && input.approvalMode === "trusted_idempotent_writes"
    && permission === "write"
    && idempotency === "idempotent_write"
    && trustedDesktopIdempotentWriteCapabilities.has(capability)
    && approvalRequest.manualApprovalRequired !== true
    && hasOnlyTrustedDesktopApprovalSteps(approvalRequest)
    && safelyClassified
    && (routeDecision?.route === "desktop_runtime"
      || taskRoute?.operationalRoute === "desktop_runtime");
}

export function buildTaskDispatchLeaseUpdate(
  input: {
    leaseId: string;
    runtimeConnectionId?: string | null;
    now?: Date;
    leaseMs?: number;
    attemptCount?: number;
  },
) {
  const now = input.now ?? new Date();
  const leaseMs = Math.max(5_000, Math.floor(input.leaseMs ?? TASK_DISPATCH_LEASE_MS));
  return {
    status: "planning" as TaskStatus,
    runtimeConnectionId: input.runtimeConnectionId ?? null,
    dispatchLeaseId: input.leaseId,
    dispatchLeaseIssuedAt: now,
    dispatchLeaseExpiresAt: new Date(now.getTime() + leaseMs),
    dispatchAckAt: null,
    dispatchAttemptCount: input.attemptCount ?? 0,
    error: null,
    updatedAt: now,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskDispatchLeaseAckUpdate(
  input: {
    runtimeConnectionId: string;
    leaseId: string;
    now?: Date;
    acceptedAt?: Date;
  },
) {
  const now = input.now ?? new Date();
  const acceptedAt = input.acceptedAt ?? now;
  return {
    status: "running" as TaskStatus,
    runtimeConnectionId: input.runtimeConnectionId,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: acceptedAt,
    startedAt: acceptedAt,
    updatedAt: now,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskDispatchLeaseReleaseUpdate(
  input: {
    now?: Date;
    clearRuntimeConnection?: boolean;
  } = {},
) {
  const now = input.now ?? new Date();
  return {
    status: "queued" as TaskStatus,
    runtimeConnectionId: input.clearRuntimeConnection ? null : undefined,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    updatedAt: now,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskDispatchExhaustedUpdate(
  input: {
    now?: Date;
    message?: string;
  } = {},
) {
  const now = input.now ?? new Date();
  const message = input.message ?? "Desktop görevi birkaç denemeden sonra teslim edilemedi.";
  return {
    status: "failed" as TaskStatus,
    summary: message,
    error: message,
    completedAt: now,
    updatedAt: now,
    queuePosition: 0,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    runtimeConnectionId: null,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskCancellationUpdate(now = new Date()) {
  return {
    status: "canceled" as TaskStatus,
    queuePosition: 0,
    canceledAt: now,
    updatedAt: now,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskApprovalResolution(
  approvalRequest: unknown,
  input: {
    approved?: boolean;
    notes?: string;
    now?: Date;
  } = {},
) {
  const resolution = {
    approved: input.approved ?? true,
    notes: input.notes ?? null,
    resolvedAt: (input.now ?? new Date()).toISOString(),
    revision: approvalRequestRevision(approvalRequest),
    approvalKey: approvalRequestKey(approvalRequest) || null,
  };

  if (approvalRequest && typeof approvalRequest === "object" && !Array.isArray(approvalRequest)) {
    return {
      ...(approvalRequest as Record<string, unknown>),
      resolution,
    };
  }

  return {
    resolution,
  };
}

export function buildTaskApprovalResumeUpdate(
  task: {
    id?: string;
    startedAt?: Date | null;
    approvalRequest?: unknown;
  },
  input: {
    notes?: string;
    now?: Date;
  } = {},
) {
  const now = input.now ?? new Date();
  const approvalRequest = normalizeTaskApprovalRequest(task.approvalRequest, {
    taskId: readString(task.id),
    now,
  });
  const update: Partial<typeof tasks.$inferInsert> = {
    status: "waiting_approval" as TaskStatus,
    approvalRequest: buildTaskApprovalResolution(approvalRequest, {
      notes: input.notes,
      now,
    }),
    summary: "Onay alındı. Görev devam ediyor.",
    error: null,
    updatedAt: now,
  };

  return update;
}

export function buildTaskRuntimeUpdate(
  task: {
    startedAt?: Date | null;
    summary?: string | null;
    error?: string | null;
    approvalRequest?: unknown;
    result?: unknown;
  },
  input: {
    status: TaskStatus;
    runtimeConnectionId: string;
    summary?: string;
    error?: string;
    approvalRequest?: Record<string, unknown>;
    result?: Record<string, unknown>;
    now?: Date;
  },
) {
  const now = input.now ?? new Date();
  const updates: Partial<typeof tasks.$inferInsert> = {
    status: input.status,
    summary: input.summary ?? task.summary ?? null,
    error: input.error ?? task.error ?? null,
    approvalRequest: input.approvalRequest ?? task.approvalRequest ?? null,
    result: input.result ?? task.result ?? null,
    runtimeConnectionId: input.runtimeConnectionId,
    updatedAt: now,
  };

  if (input.status === "running" && !task.startedAt) {
    updates.startedAt = now;
  }

  if (input.status === "completed") {
    updates.completedAt = now;
    updates.queuePosition = 0;
  }

  if (input.status === "failed") {
    updates.queuePosition = 0;
  }

  if (input.status === "canceled") {
    updates.canceledAt = now;
    updates.queuePosition = 0;
  }

  return updates;
}
