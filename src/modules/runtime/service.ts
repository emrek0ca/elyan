import { createHash, randomUUID } from "node:crypto";
import { and, eq, inArray, isNull, ne } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { devices, runtimeConnections, tasks } from "../../db/schema.js";
import { signRuntimeAccessToken } from "../../lib/auth-tokens.js";
import { AppError, conflict, notFound, unauthorized } from "../../lib/errors.js";
import { verifySecret } from "../../lib/auth-crypto.js";
import type { RuntimeAuthTokenPayload } from "../../types/auth.js";
import { assertDesktopPairingAllowed } from "../billing/service.js";
import {
  normalizeRuntimeCapabilityHandshake,
  preflightRequestedRuntimeCapabilities,
  summarizeRuntimeCapabilities,
  summarizeRuntimeCapabilityReadiness,
} from "./capabilities.js";
import { activeTaskStatuses } from "../tasks/queue.js";
import { isDesktopPlanPreparationPending } from "../tasks/desktop-work-order.js";
import { deriveTaskDeliveryState, extractTaskRouteDecision } from "../tasks/service-helpers.js";
import { getUserDevice } from "../devices/service.js";

function stableRuntimeJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableRuntimeJson(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableRuntimeJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function runtimeCapabilityHash(input: {
  capabilities: unknown;
  capabilityStates: unknown;
}): string {
  return createHash("sha256")
    .update(
      stableRuntimeJson({
        capabilities: Array.isArray(input.capabilities)
          ? [...input.capabilities].map(String).sort()
          : [],
        capabilityStates: input.capabilityStates ?? {},
      }),
    )
    .digest("hex");
}

type AssignedRuntimeTaskResponseItem = {
  id: string;
  status: string;
  updatedAt?: Date | null;
  dispatchLeaseId?: string | null;
  dispatchLeaseExpiresAt?: Date | null;
};

function assignedTasksHash(
  tasksInput: AssignedRuntimeTaskResponseItem[],
): string {
  return createHash("sha256")
    .update(
      stableRuntimeJson(
        tasksInput.map((task) => ({
          id: task.id,
          status: task.status,
          updatedAt: task.updatedAt?.toISOString() ?? null,
          dispatchLeaseId: task.dispatchLeaseId ?? null,
          dispatchLeaseExpiresAt:
            task.dispatchLeaseExpiresAt?.toISOString() ?? null,
        })),
      ),
    )
    .digest("hex");
}

export function shapeAssignedRuntimeTaskResponse<
  TaskItem extends AssignedRuntimeTaskResponseItem,
>(tasksInput: TaskItem[]) {
  const cursor =
    tasksInput
      .map((task) => task.updatedAt?.toISOString() ?? "")
      .sort()
      .at(-1) ?? null;
  return {
    tasks: tasksInput,
    cursor,
    assignmentHash: assignedTasksHash(tasksInput),
    leases: tasksInput
      .filter((task) => task.dispatchLeaseId || task.dispatchLeaseExpiresAt)
      .map((task) => ({
        taskId: task.id,
        leaseId: task.dispatchLeaseId ?? null,
        expiresAt: task.dispatchLeaseExpiresAt ?? null,
      })),
  };
}

export async function getRuntimeConnectionByAuth(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
) {
  const rows = await app.db
    .select({
      id: runtimeConnections.id,
      status: runtimeConnections.status,
      socketSessionId: runtimeConnections.socketSessionId,
      currentTaskId: runtimeConnections.currentTaskId,
      capabilities: runtimeConnections.capabilities,
      capabilityStates: runtimeConnections.capabilityStates,
      connectedAt: runtimeConnections.connectedAt,
      lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
    })
    .from(runtimeConnections)
    .innerJoin(devices, eq(runtimeConnections.deviceId, devices.id))
    .where(
      and(
        eq(runtimeConnections.id, auth.connectionId),
        eq(runtimeConnections.deviceId, auth.deviceId),
        eq(runtimeConnections.userId, auth.sub),
        eq(devices.isActive, true),
        isNull(runtimeConnections.disconnectedAt),
      ),
    )
    .limit(1);

  const connection = rows[0];

  if (!connection) {
    throw unauthorized("Runtime connection is stale or has been replaced");
  }

  return connection;
}

export async function registerRuntime(
  app: FastifyInstance,
  input: {
    deviceId: string;
    deviceSecret: string;
    runtimeVersion?: string;
    capabilities: string[];
    capabilityStates?: Record<string, unknown>;
    capabilityHandshake?: unknown[];
  },
) {
  const handshake = normalizeRuntimeCapabilityHandshake({
    capabilities: input.capabilities,
    capabilityStates: input.capabilityStates,
    capabilityHandshake: input.capabilityHandshake,
  });
  const normalizedCapabilities = handshake.capabilities;
  const normalizedCapabilityStates = handshake.capabilityStates;
  const rows = await app.db
    .select({
      id: devices.id,
      userId: devices.userId,
      label: devices.label,
      type: devices.type,
      isActive: devices.isActive,
      deviceKeyHash: devices.deviceKeyHash,
      platform: devices.platform,
    })
    .from(devices)
    .where(eq(devices.id, input.deviceId))
    .limit(1);

  const device = rows[0];

  if (!device || device.type !== "desktop") {
    throw notFound("Desktop runtime device not found");
  }

  // Deactivated device: deviceKeyHash is wiped on deactivation so the secret
  // check below would fail anyway, but we give a clearer error code here.
  if (!device.isActive) {
    throw unauthorized("Device has been deactivated");
  }

  if (!device.userId || !device.deviceKeyHash) {
    throw new AppError(
      409,
      "pairing_pending",
      "Desktop runtime has not completed pairing",
    );
  }

  const secretMatches = await verifySecret(input.deviceSecret, device.deviceKeyHash);

  if (!secretMatches) {
    throw unauthorized("Device secret is invalid");
  }

  await assertDesktopPairingAllowed(app, device.userId, device.id);

  await app.db
    .update(runtimeConnections)
    .set({
      status: "offline",
      disconnectedAt: new Date(),
    })
    .where(and(eq(runtimeConnections.deviceId, device.id), isNull(runtimeConnections.disconnectedAt)));

  app.services.realtimeHub.closeRuntime(device.id, 4001, "runtime_replaced");

  await app.db
    .update(devices)
    .set({
      runtimeVersion: input.runtimeVersion,
      lastSeenAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(devices.id, device.id));

  const socketSessionId = randomUUID();

  const connectionRows = await app.db
    .insert(runtimeConnections)
    .values({
      deviceId: device.id,
      userId: device.userId,
      status: "offline",
      socketSessionId,
      capabilities: normalizedCapabilities,
      capabilityStates: normalizedCapabilityStates,
    })
    .returning({
      id: runtimeConnections.id,
    });
  const connection = connectionRows[0];

  const tokenPayload: RuntimeAuthTokenPayload = {
    kind: "runtime",
    sub: device.userId,
    deviceId: device.id,
    deviceType: "desktop",
    connectionId: connection.id,
  };
  const accessToken = await signRuntimeAccessToken(app, tokenPayload);

  return {
    runtime: {
      deviceId: device.id,
      label: device.label,
      platform: device.platform,
      connectionId: connection.id,
    },
    capabilities: normalizedCapabilities,
    capabilityStates: normalizedCapabilityStates,
    capabilityHandshake: handshake.descriptors,
    capabilitySummary: summarizeRuntimeCapabilities(normalizedCapabilities),
    capabilityReadinessSummary: summarizeRuntimeCapabilityReadiness(
      normalizedCapabilityStates,
    ),
    tokens: {
      accessToken,
      accessTokenTtl: app.config.RUNTIME_TOKEN_TTL,
    },
    realtime: {
      websocketPath: "/v1/realtime/runtime",
      ssePath: "/v1/realtime/stream",
    },
  };
}

export async function markRuntimeConnected(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  socketSessionId?: string,
): Promise<void> {
  // Allow reconnecting a recently-disconnected session (e.g. brief network drop)
  // by updating the row regardless of disconnectedAt, as long as the JWT is valid.
  const rows = await app.db
    .select({ id: runtimeConnections.id })
    .from(runtimeConnections)
    .where(
      and(
        eq(runtimeConnections.id, auth.connectionId),
        eq(runtimeConnections.deviceId, auth.deviceId),
        eq(runtimeConnections.userId, auth.sub),
      ),
    )
    .limit(1);

  if (!rows[0]) {
    throw unauthorized("Runtime connection not found");
  }

  await app.db
    .update(runtimeConnections)
    .set({
      status: "online",
      socketSessionId,
      lastHeartbeatAt: new Date(),
      disconnectedAt: null,
    })
    .where(eq(runtimeConnections.id, auth.connectionId));

  await app.db
    .update(devices)
    .set({
      lastSeenAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(devices.id, auth.deviceId));

  // Notify mobile that the desktop is now online.
  await app.services.eventBus.publishVolatile({
    topic: "device.status_changed",
    userId: auth.sub,
    deviceId: auth.deviceId,
    payload: {
      deviceId: auth.deviceId,
      isOnline: true,
      reason: "runtime_connected",
    },
  });
}

export async function heartbeatRuntime(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  input: {
    status: "online" | "busy" | "idle";
    currentTaskId?: string;
    capabilities?: string[];
    capabilityStates?: Record<string, unknown>;
    capabilityHandshake?: unknown[];
  },
) {
  await getRuntimeConnectionByAuth(app, auth);
  const handshake =
    input.capabilities !== undefined ||
    input.capabilityStates !== undefined ||
    input.capabilityHandshake !== undefined
      ? normalizeRuntimeCapabilityHandshake({
          capabilities: input.capabilities,
          capabilityStates: input.capabilityStates,
          capabilityHandshake: input.capabilityHandshake,
        })
      : null;
  const shouldUpdateCapabilities =
    input.capabilities !== undefined || input.capabilityHandshake !== undefined;

  await app.db
    .update(runtimeConnections)
    .set({
      status: input.status,
      currentTaskId: input.currentTaskId,
      ...(handshake && shouldUpdateCapabilities
        ? { capabilities: handshake.capabilities }
        : {}),
      ...(handshake ? { capabilityStates: handshake.capabilityStates } : {}),
      lastHeartbeatAt: new Date(),
      disconnectedAt: null,
    })
    .where(eq(runtimeConnections.id, auth.connectionId));

  await app.db
    .update(devices)
    .set({
      lastSeenAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(devices.id, auth.deviceId));

  return {
    ok: true,
    deviceId: auth.deviceId,
    status: input.status,
    capabilityStates: handshake?.capabilityStates ?? {},
    capabilityHandshake: handshake?.descriptors ?? [],
    capabilitySummary: summarizeRuntimeCapabilities(handshake?.capabilities ?? []),
    capabilityReadinessSummary: summarizeRuntimeCapabilityReadiness(
      handshake?.capabilityStates ?? {},
    ),
  };
}

export async function disconnectRuntime(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  options: { closeSocket?: boolean } = {},
): Promise<void> {
  const ownedRows = await app.db
    .select({ id: runtimeConnections.id })
    .from(runtimeConnections)
    .where(
      and(
        eq(runtimeConnections.id, auth.connectionId),
        eq(runtimeConnections.deviceId, auth.deviceId),
        eq(runtimeConnections.userId, auth.sub),
      ),
    )
    .limit(1);
  if (!ownedRows[0]) {
    throw unauthorized("Runtime connection not found");
  }

  await app.db
    .update(runtimeConnections)
    .set({
      status: "offline",
      disconnectedAt: new Date(),
    })
    .where(
      and(
        eq(runtimeConnections.id, auth.connectionId),
        isNull(runtimeConnections.disconnectedAt),
      ),
    );

  const replacementRows = await app.db
    .select({ id: runtimeConnections.id })
    .from(runtimeConnections)
    .where(
      and(
        eq(runtimeConnections.deviceId, auth.deviceId),
        eq(runtimeConnections.userId, auth.sub),
        ne(runtimeConnections.id, auth.connectionId),
        isNull(runtimeConnections.disconnectedAt),
      ),
    )
    .limit(1);
  if (replacementRows[0]) {
    return;
  }

  if (options.closeSocket !== false) {
    app.services.realtimeHub.closeRuntime(
      auth.deviceId,
      4000,
      "runtime_disconnect",
    );
  }

  // Notify mobile so it refreshes device status immediately.
  await app.services.eventBus.publishVolatile({
    topic: "device.status_changed",
    userId: auth.sub,
    deviceId: auth.deviceId,
    payload: {
      deviceId: auth.deviceId,
      isOnline: false,
      reason: "runtime_disconnect",
    },
  });
}

export async function listAssignedRuntimeTasks(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  options: { includePlanPending?: boolean } = {},
) {
  const connection = await getRuntimeConnectionByAuth(app, auth);

  const rows = await app.db
    .select({
      id: tasks.id,
      title: tasks.title,
      targetDeviceId: tasks.targetDeviceId,
      queuePosition: tasks.queuePosition,
      payload: tasks.payload,
      requestedCapabilities: tasks.requestedCapabilities,
      dispatchAttemptCount: tasks.dispatchAttemptCount,
      status: tasks.status,
      summary: tasks.summary,
      error: tasks.error,
      approvalRequest: tasks.approvalRequest,
      runtimeConnectionId: tasks.runtimeConnectionId,
      dispatchLeaseId: tasks.dispatchLeaseId,
      dispatchLeaseIssuedAt: tasks.dispatchLeaseIssuedAt,
      dispatchLeaseExpiresAt: tasks.dispatchLeaseExpiresAt,
      dispatchAckAt: tasks.dispatchAckAt,
      createdAt: tasks.createdAt,
      updatedAt: tasks.updatedAt,
    })
    .from(tasks)
    .where(
      and(
        eq(tasks.userId, auth.sub),
        eq(tasks.targetDeviceId, auth.deviceId),
        inArray(tasks.status, activeTaskStatuses),
      ),
    )
    .orderBy(tasks.queuePosition, tasks.createdAt);

  const claimOwner = `runtime:${auth.connectionId}:poll`;
  const claimable: Array<(typeof rows)[number] & { planPreparationPending?: boolean }> = [];
  for (const row of rows) {
    // Only v1.7 tasks carry this gate. Legacy rows remain claimable. Pending
    // model plans are never executable, even after a backend restart. The
    // websocket reconnect path may ask for these rows explicitly so it can
    // enqueue plan materialization instead of silently leaving them queued.
    if (isDesktopPlanPreparationPending(row.payload)) {
      if (options.includePlanPending === true) {
        claimable.push({ ...row, planPreparationPending: true });
      }
      continue;
    }
    if (row.status !== "queued") {
      claimable.push(row);
      continue;
    }
    const acquired = await app.services.reliability.acquireTaskDispatchLock(row.id, claimOwner);
    if (acquired) {
      claimable.push(row);
    }
  }

  return claimable.map((row) => {
    const requestedCapabilities = Array.isArray(row.requestedCapabilities)
      ? row.requestedCapabilities.filter(
          (capability): capability is string => typeof capability === "string",
        )
      : [];
    const capabilityPreflight = preflightRequestedRuntimeCapabilities({
      availableCapabilities: connection.capabilities,
      capabilityStates: connection.capabilityStates,
      requestedCapabilities,
    });
    return {
      ...row,
      ...(row.planPreparationPending
        ? { planPreparationPending: true }
        : {}),
      routeDecision: extractTaskRouteDecision(row.payload),
      deliveryState: deriveTaskDeliveryState(row),
      deliveryAttemptCount: row.dispatchAttemptCount ?? 0,
      lastAckAt: row.dispatchAckAt ?? null,
      lastDispatchAttemptAt: row.dispatchLeaseIssuedAt ?? row.dispatchAckAt ?? null,
      capabilityPreflight,
      canAcceptNow: capabilityPreflight.ok,
    };
  });
}

export async function getRuntimeSessionSnapshot(app: FastifyInstance, auth: RuntimeAuthTokenPayload) {
  const connection = await getRuntimeConnectionByAuth(app, auth);
  const deviceTruth = await getUserDevice(app, auth.sub, auth.deviceId);
  const deviceRows = await app.db
    .select({
      id: devices.id,
      label: devices.label,
      platform: devices.platform,
      runtimeVersion: devices.runtimeVersion,
      lastSeenAt: devices.lastSeenAt,
    })
    .from(devices)
    .where(eq(devices.id, auth.deviceId))
    .limit(1);
  return {
    device: deviceRows[0] ?? null,
    readiness: deviceTruth
      ? {
          isOnline: deviceTruth.isOnline,
          canReceiveTasks: deviceTruth.canReceiveTasks,
          targetStatus: deviceTruth.targetStatus,
          targetErrorCode: deviceTruth.targetErrorCode,
          transportReady: deviceTruth.canReceiveTasks && deviceTruth.targetStatus === "ready",
          taskAcceptanceReady: deviceTruth.canReceiveTasks && deviceTruth.targetStatus === "ready",
          realtimeReady: deviceTruth.canReceiveTasks && deviceTruth.targetStatus === "ready",
          runtime: deviceTruth.runtime,
        }
      : null,
    connection: {
      id: connection.id,
      status: connection.status,
      socketSessionId: connection.socketSessionId,
      currentTaskId: connection.currentTaskId,
      connectedAt: connection.connectedAt,
      lastHeartbeatAt: connection.lastHeartbeatAt,
    },
    lastHeartbeatAt: connection.lastHeartbeatAt,
    capabilityHash: runtimeCapabilityHash({
      capabilities: connection.capabilities,
      capabilityStates: connection.capabilityStates,
    }),
    capabilitySummary: summarizeRuntimeCapabilities(connection.capabilities),
    capabilityReadinessSummary: summarizeRuntimeCapabilityReadiness(
      connection.capabilityStates,
    ),
  };
}
