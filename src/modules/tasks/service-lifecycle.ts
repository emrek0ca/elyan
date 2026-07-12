import type { TaskStatus } from "../../contracts/domain.js";
import { tasks } from "../../db/schema.js";

export function buildTaskRuntimeOwnershipUpdate(input: { runtimeConnectionId: string; now?: Date }) {
  return {
    runtimeConnectionId: input.runtimeConnectionId,
    updatedAt: input.now ?? new Date(),
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export const TASK_DISPATCH_LEASE_MS = 45_000;

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function shouldAutoApproveDesktopTask(input: {
  status: TaskStatus;
  payload: unknown;
}) {
  if (input.status !== "waiting_approval") return false;

  const payload = readRecord(input.payload);
  const metadata = readRecord(payload?.metadata);
  const routeDecision = readRecord(metadata?.routeDecision);
  const taskRoute = readRecord(routeDecision?.taskRoute);

  return metadata?.desktopDispatch === true
    && metadata.desktopFullAuthorityEnabled === true
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
    notes?: string;
    now?: Date;
  } = {},
) {
  const resolution = {
    approved: true,
    notes: input.notes ?? null,
    resolvedAt: (input.now ?? new Date()).toISOString(),
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
    startedAt?: Date | null;
    approvalRequest?: unknown;
  },
  input: {
    notes?: string;
    now?: Date;
  } = {},
) {
  const now = input.now ?? new Date();
  const update: Partial<typeof tasks.$inferInsert> = {
    status: "waiting_approval" as TaskStatus,
    approvalRequest: buildTaskApprovalResolution(task.approvalRequest, {
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
