import { and, desc, eq, inArray, isNull, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { devices, runtimeConnections, tasks } from "../../db/schema.js";
import { getBaseUrlReachability } from "../../config/env.js";
import { conflict, notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import { canUseDesktopConnections } from "../billing/catalog.js";
import { getUserUsageAccessTruth } from "../billing/service.js";
import { invalidateBrainProfileCache } from "../brain/profile-cache.js";
import {
  normalizeRuntimeCapabilities,
  summarizeRuntimeCapabilities,
} from "../runtime/capabilities.js";

export const RUNTIME_CONNECTION_STALE_AFTER_MS = 300_000; // 5 minutes — relay sends heartbeats every 2-5s so this is very forgiving

type DeviceRow = {
  id: string;
  type: "mobile" | "desktop";
  externalDeviceId: string | null;
  label: string;
  platform: string;
  runtimeVersion: string | null;
  appVersion: string | null;
  isActive: boolean;
  pairedAt: Date | null;
  lastSeenAt: Date | null;
  createdAt: Date;
  updatedAt: Date;
};

type RuntimeConnectionRow = {
  id: string;
  deviceId: string;
  status: "online" | "busy" | "idle" | "offline";
  capabilities: unknown;
  capabilityStates: unknown;
  currentTaskId: string | null;
  connectedAt: Date;
  lastHeartbeatAt: Date;
};

const deviceRegistrationReturning = {
  id: devices.id,
  userId: devices.userId,
  type: devices.type,
  externalDeviceId: devices.externalDeviceId,
  label: devices.label,
  platform: devices.platform,
  appVersion: devices.appVersion,
  isActive: devices.isActive,
  pairedAt: devices.pairedAt,
  lastSeenAt: devices.lastSeenAt,
  createdAt: devices.createdAt,
  updatedAt: devices.updatedAt,
};

type MobileRegistrationMetadataInput = {
  pushToken?: string;
  pushProvider?: string;
  notificationAuthorizationStatus?: string;
  supportsLiveActivities?: boolean;
  supportsDynamicIsland?: boolean;
  backgroundRefreshEnabled?: boolean;
};

export function mobileRegistrationAuditMetadata(
  input: MobileRegistrationMetadataInput,
) {
  return {
    pushConfigured: Boolean(input.pushToken),
    pushProvider: input.pushProvider ?? null,
    notificationAuthorizationStatus:
      input.notificationAuthorizationStatus ?? null,
    supportsLiveActivities: input.supportsLiveActivities ?? false,
    supportsDynamicIsland: input.supportsDynamicIsland ?? false,
    backgroundRefreshEnabled: input.backgroundRefreshEnabled ?? false,
  };
}

function isRuntimeConnectionFresh(
  runtime: RuntimeConnectionRow,
  now = Date.now(),
): boolean {
  return (
    now - runtime.lastHeartbeatAt.getTime() <= RUNTIME_CONNECTION_STALE_AFTER_MS
  );
}

export function shapeUserDevice(
  device: DeviceRow,
  runtime: RuntimeConnectionRow | null,
  externalClientsCanReachAdvertisedBaseUrl = true,
  optionsOrNow?:
    | {
        queuedTaskCount?: number;
        desktopAllowed?: boolean;
        wsConnected?: boolean; // live WebSocket in realtimeHub — overrides DB stale check
      }
    | number,
  now = Date.now(),
) {
  const options = typeof optionsOrNow === "number" ? undefined : optionsOrNow;
  const effectiveNow = typeof optionsOrNow === "number" ? optionsOrNow : now;
  const desktopAllowed = options?.desktopAllowed ?? true;
  const wsConnected = options?.wsConnected ?? false; // in-memory hub says WS is OPEN
  const runtimeFresh = runtime
    ? isRuntimeConnectionFresh(runtime, effectiveNow)
    : false;
  // If the WebSocket is live in the hub, treat the connection as fresh regardless of DB timestamp
  const runtimeConnected = (runtimeFresh || wsConnected) && runtime?.status !== "offline";
  const runtimeStale =
    Boolean(runtime) && runtime?.status !== "offline" && !runtimeFresh && !wsConnected;
  const normalizedCapabilities = runtime
    ? normalizeRuntimeCapabilities(runtime.capabilities)
    : [];
  const isDesktop = device.type === "desktop";
  // When WS is live and the connection row exists (even with disconnectedAt), treat as online
  const isOnline = isDesktop && (runtimeConnected || (wsConnected && Boolean(runtime)));
  const canReceiveTasks =
    isDesktop &&
    device.isActive &&
    isOnline &&
    externalClientsCanReachAdvertisedBaseUrl &&
    desktopAllowed;
  const targetStatus = !isDesktop
    ? "not_desktop"
    : !desktopAllowed
      ? "plan_restricted"
    : !device.isActive
      ? "inactive"
      : !externalClientsCanReachAdvertisedBaseUrl
        ? "backend_unreachable"
        : runtimeStale
          ? "runtime_stale"
          : isOnline
            ? "ready"
            : "offline";
  const targetErrorCode =
    targetStatus === "ready"
      ? null
      : targetStatus === "plan_restricted"
        ? "desktop_plan_required"
      : targetStatus === "backend_unreachable"
        ? "backend_unreachable"
      : targetStatus === "offline"
        ? "device_offline"
          : targetStatus === "runtime_stale"
            ? "runtime_stale"
            : targetStatus === "inactive"
              ? "device_inactive"
              : "invalid_target";
  const queuedTaskCountValue =
    typeof options === "number" ? options : options?.queuedTaskCount;
  const queuedTaskCount = Math.max(0, queuedTaskCountValue ?? 0);
  const realtimeReady = canReceiveTasks && targetStatus === "ready";
  const transportMode = realtimeReady
    ? "websocket"
    : runtimeStale
      ? "degraded_polling"
      : "queued_only";
  const deliveryStatus =
    queuedTaskCount > 0 && !realtimeReady
      ? "queued_remote_work"
      : realtimeReady
        ? "ready"
        : targetStatus;

  return {
    ...device,
    isOnline,
    canReceiveTasks,
    realtimeReady,
    queuedTaskCount,
    transportMode,
    deliveryStatus,
    targetStatus,
    targetErrorCode,
    runtime:
      runtime && runtimeConnected
        ? {
            isConnected: true,
            status: runtime.status,
            capabilities: normalizedCapabilities,
            capabilityStates: runtime.capabilityStates,
            capabilitySummary: summarizeRuntimeCapabilities(
              normalizedCapabilities,
            ),
            currentTaskId: runtime.currentTaskId,
            connectedAt: runtime.connectedAt,
            lastHeartbeatAt: runtime.lastHeartbeatAt,
            stale: false,
            transportMode,
            queuedTaskCount,
            realtimeReady,
          }
        : {
            isConnected: false,
            status: (runtime?.status ?? "offline") as
              | "online"
              | "busy"
              | "idle"
              | "offline",
            capabilities: normalizedCapabilities,
            capabilityStates: runtime?.capabilityStates ?? {},
            capabilitySummary: summarizeRuntimeCapabilities(
              normalizedCapabilities,
            ),
            currentTaskId: runtime?.currentTaskId ?? null,
            connectedAt: runtime?.connectedAt ?? null,
            lastHeartbeatAt: runtime?.lastHeartbeatAt ?? null,
            stale: runtimeStale,
            transportMode,
            queuedTaskCount,
            realtimeReady,
          },
  };
}

async function listQueuedTaskCountsByDevice(
  app: FastifyInstance,
  deviceIds: string[],
) {
  if (!deviceIds.length) {
    return new Map<string, number>();
  }
  try {
    const rows = await app.db
      .select({
        deviceId: tasks.targetDeviceId,
        queuedTaskCount: sql<number>`count(*)`,
      })
      .from(tasks)
      .where(
        and(
          inArray(tasks.targetDeviceId, deviceIds),
          inArray(tasks.status, ["queued", "planning"]),
        ),
      )
      .groupBy(tasks.targetDeviceId);
    return new Map(
      rows.map((row) => [row.deviceId, Number(row.queuedTaskCount ?? 0)]),
    );
  } catch {
    return new Map<string, number>();
  }
}

export async function getSharedBrainTargetDevice(app: FastifyInstance) {
  const deviceRows = await app.db
    .select({
      id: devices.id,
      type: devices.type,
      externalDeviceId: devices.externalDeviceId,
      label: devices.label,
      platform: devices.platform,
      runtimeVersion: devices.runtimeVersion,
      appVersion: devices.appVersion,
      isActive: devices.isActive,
      pairedAt: devices.pairedAt,
      lastSeenAt: devices.lastSeenAt,
      createdAt: devices.createdAt,
      updatedAt: devices.updatedAt,
    })
    .from(devices)
    .where(
      and(
        isNull(devices.userId),
        eq(devices.type, "desktop"),
        eq(devices.isActive, true),
      ),
    )
    .orderBy(desc(devices.updatedAt), desc(devices.createdAt));

  const sharedBrainDevice =
    deviceRows.find((device) => device.externalDeviceId === "shared-brain") ??
    deviceRows.find((device) =>
      (device.label ?? "").trim().toLowerCase().startsWith("elyan"),
    ) ??
    deviceRows[0] ??
    null;

  if (!sharedBrainDevice) {
    return null;
  }

  const runtimeRows = await app.db
    .select({
      id: runtimeConnections.id,
      deviceId: runtimeConnections.deviceId,
      status: runtimeConnections.status,
      capabilities: runtimeConnections.capabilities,
      capabilityStates: runtimeConnections.capabilityStates,
      currentTaskId: runtimeConnections.currentTaskId,
      connectedAt: runtimeConnections.connectedAt,
      lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
    })
    .from(runtimeConnections)
    .where(
      and(
        eq(runtimeConnections.deviceId, sharedBrainDevice.id),
        isNull(runtimeConnections.disconnectedAt),
      ),
    )
    .orderBy(desc(runtimeConnections.connectedAt))
    .limit(1);
  const reachability = getBaseUrlReachability(app.config);
  const runtime = runtimeRows[0] ?? null;

  return {
    ...shapeUserDevice(
      sharedBrainDevice,
      runtime,
      reachability.externalClientsCanReachAdvertisedBaseUrl,
    ),
    serverBrainName: "Elyan",
  };
}

export async function ensureSharedBrainTargetDevice(
  app: FastifyInstance,
): Promise<
  NonNullable<Awaited<ReturnType<typeof getSharedBrainTargetDevice>>>
> {
  const now = new Date();
  const rows = await app.db
    .select({
      id: devices.id,
      type: devices.type,
      externalDeviceId: devices.externalDeviceId,
      label: devices.label,
      platform: devices.platform,
      runtimeVersion: devices.runtimeVersion,
      appVersion: devices.appVersion,
      isActive: devices.isActive,
      pairedAt: devices.pairedAt,
      lastSeenAt: devices.lastSeenAt,
      createdAt: devices.createdAt,
      updatedAt: devices.updatedAt,
    })
    .from(devices)
    .where(and(isNull(devices.userId), eq(devices.type, "desktop")))
    .orderBy(desc(devices.updatedAt), desc(devices.createdAt))
    .limit(10);

  const sharedBrainDevice =
    rows.find((device) => device.externalDeviceId === "shared-brain") ??
    rows.find((device) =>
      device.label.trim().toLowerCase().startsWith("elyan"),
    ) ??
    null;

  if (sharedBrainDevice) {
    if (
      sharedBrainDevice.externalDeviceId !== "shared-brain" ||
      sharedBrainDevice.label.trim() !== "Elyan" ||
      sharedBrainDevice.platform.trim().toLowerCase() !== "server" ||
      !sharedBrainDevice.isActive
    ) {
      await app.db
        .update(devices)
        .set({
          externalDeviceId: "shared-brain",
          label: "Elyan",
          platform: "server",
          isActive: true,
          pairedAt: sharedBrainDevice.pairedAt ?? now,
          lastSeenAt: sharedBrainDevice.lastSeenAt ?? now,
          updatedAt: now,
        })
        .where(eq(devices.id, sharedBrainDevice.id));
    }

    const ensured = await getSharedBrainTargetDevice(app);
    if (!ensured) {
      throw new Error("Shared brain device bootstrap failed");
    }

    return ensured;
  }

  await app.db.insert(devices).values({
    userId: null,
    type: "desktop",
    externalDeviceId: "shared-brain",
    label: "Elyan",
    platform: "server",
    runtimeVersion: "server",
    isActive: true,
    pairedAt: now,
    lastSeenAt: now,
    createdAt: now,
    updatedAt: now,
  });

  const ensured = await getSharedBrainTargetDevice(app);
  if (!ensured) {
    throw new Error("Shared brain device bootstrap failed");
  }

  return ensured;
}

export async function getSharedBrainTargetDeviceId(app: FastifyInstance) {
  const device = await getSharedBrainTargetDevice(app);
  return device?.id ?? null;
}

export async function listUserDevices(app: FastifyInstance, userId: string) {
  const accessTruth = await getUserUsageAccessTruth(app.db, userId);
  const desktopAllowed = canUseDesktopConnections(accessTruth.planCode);
  const deviceRows = await app.db
    .select({
      id: devices.id,
      type: devices.type,
      externalDeviceId: devices.externalDeviceId,
      label: devices.label,
      platform: devices.platform,
      runtimeVersion: devices.runtimeVersion,
      appVersion: devices.appVersion,
      isActive: devices.isActive,
      pairedAt: devices.pairedAt,
      lastSeenAt: devices.lastSeenAt,
      createdAt: devices.createdAt,
      updatedAt: devices.updatedAt,
    })
    .from(devices)
    .where(eq(devices.userId, userId))
    .orderBy(desc(devices.pairedAt), desc(devices.createdAt));

  const desktopIds = deviceRows
    .filter((device) => device.type === "desktop")
    .map((device) => device.id);
  // Fetch the most recent connection row per device regardless of disconnectedAt.
  // We use wsConnected (live hub check) as the authoritative online signal,
  // so even if disconnectedAt is set we can still route tasks when the WS is open.
  const recentConnections =
    desktopIds.length > 0
      ? await app.db
          .select({
            id: runtimeConnections.id,
            deviceId: runtimeConnections.deviceId,
            status: runtimeConnections.status,
            capabilities: runtimeConnections.capabilities,
            capabilityStates: runtimeConnections.capabilityStates,
            currentTaskId: runtimeConnections.currentTaskId,
            connectedAt: runtimeConnections.connectedAt,
            lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
          })
          .from(runtimeConnections)
          .where(inArray(runtimeConnections.deviceId, desktopIds))
          .orderBy(desc(runtimeConnections.connectedAt))
      : [];
  const queuedTaskCounts = await listQueuedTaskCountsByDevice(app, desktopIds);
  const reachability = getBaseUrlReachability(app.config);

  // Keep only the most recent connection per device
  const recentByDeviceId = new Map<string, typeof recentConnections[0]>();
  for (const conn of recentConnections) {
    if (!recentByDeviceId.has(conn.deviceId)) {
      recentByDeviceId.set(conn.deviceId, conn);
    }
  }

  return deviceRows.map((device) => {
    const runtime =
      device.type === "desktop"
        ? (recentByDeviceId.get(device.id) ?? null)
        : null;
    const wsConnected = device.type === "desktop"
      ? app.services.realtimeHub.isRuntimeConnected(device.id)
      : false;
    return shapeUserDevice(
      device,
      runtime,
      reachability.externalClientsCanReachAdvertisedBaseUrl,
      {
        queuedTaskCount: queuedTaskCounts.get(device.id) ?? 0,
        desktopAllowed,
        wsConnected,
      },
    );
  });
}

export async function getUserDevice(
  app: FastifyInstance,
  userId: string,
  deviceId: string,
) {
  const accessTruth = await getUserUsageAccessTruth(app.db, userId);
  const desktopAllowed = canUseDesktopConnections(accessTruth.planCode);
  const deviceRows = await app.db
    .select({
      id: devices.id,
      type: devices.type,
      externalDeviceId: devices.externalDeviceId,
      label: devices.label,
      platform: devices.platform,
      runtimeVersion: devices.runtimeVersion,
      appVersion: devices.appVersion,
      isActive: devices.isActive,
      pairedAt: devices.pairedAt,
      lastSeenAt: devices.lastSeenAt,
      createdAt: devices.createdAt,
      updatedAt: devices.updatedAt,
    })
    .from(devices)
    .where(and(eq(devices.id, deviceId), eq(devices.userId, userId)))
    .limit(1);

  const device = deviceRows[0];

  if (!device) {
    return null;
  }

  // Fetch the most recent connection row regardless of disconnectedAt —
  // live WS presence (wsConnected) is the authoritative online signal.
  const runtimeRows =
    device.type === "desktop"
      ? await app.db
          .select({
            id: runtimeConnections.id,
            deviceId: runtimeConnections.deviceId,
            status: runtimeConnections.status,
            capabilities: runtimeConnections.capabilities,
            capabilityStates: runtimeConnections.capabilityStates,
            currentTaskId: runtimeConnections.currentTaskId,
            connectedAt: runtimeConnections.connectedAt,
            lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
          })
          .from(runtimeConnections)
          .where(eq(runtimeConnections.deviceId, device.id))
          .orderBy(desc(runtimeConnections.connectedAt))
          .limit(1)
      : [];
  const queuedTaskCounts =
    device.type === "desktop"
      ? await listQueuedTaskCountsByDevice(app, [device.id])
      : new Map<string, number>();
  const reachability = getBaseUrlReachability(app.config);
  const wsConnected = device.type === "desktop"
    ? app.services.realtimeHub.isRuntimeConnected(device.id)
    : false;

  return shapeUserDevice(
    device,
    runtimeRows[0] ?? null,
    reachability.externalClientsCanReachAdvertisedBaseUrl,
    {
      queuedTaskCount: queuedTaskCounts.get(device.id) ?? 0,
      desktopAllowed,
      wsConnected,
    },
  );
}

export async function registerMobileDevice(
  app: FastifyInstance,
  input: {
    userId: string;
    externalDeviceId: string;
    label: string;
    platform: string;
    appVersion?: string;
    pushToken?: string;
    pushProvider?: string;
    notificationAuthorizationStatus?: string;
    supportsLiveActivities?: boolean;
    supportsDynamicIsland?: boolean;
    backgroundRefreshEnabled?: boolean;
    buildMetadata?: Record<string, unknown>;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const existingRows = await app.db
    .select({
      id: devices.id,
      externalDeviceId: devices.externalDeviceId,
    })
    .from(devices)
    .where(
      and(
        eq(devices.userId, input.userId),
        eq(devices.type, "mobile"),
        eq(devices.externalDeviceId, input.externalDeviceId),
      ),
    )
    .limit(1);

  const now = new Date();
  const clientMetadata = {
    pushToken: input.pushToken ?? null,
    pushProvider: input.pushProvider ?? null,
    notificationAuthorizationStatus:
      input.notificationAuthorizationStatus ?? null,
    supportsLiveActivities: input.supportsLiveActivities ?? false,
    supportsDynamicIsland: input.supportsDynamicIsland ?? false,
    backgroundRefreshEnabled: input.backgroundRefreshEnabled ?? false,
    buildMetadata: input.buildMetadata ?? {},
  };

  if (existingRows[0]) {
    let updatedRows;
    try {
      updatedRows = await app.db
        .update(devices)
        .set({
          label: input.label,
          platform: input.platform,
          appVersion: input.appVersion,
          clientMetadata,
          lastSeenAt: now,
          updatedAt: now,
        })
        .where(eq(devices.id, existingRows[0].id))
        .returning(deviceRegistrationReturning);
    } catch (error) {
      if (!isUndefinedColumnError(error)) {
        throw error;
      }
      app.log.warn(
        { requestId: input.requestId },
        "devices.client_metadata migration missing; registering mobile without optional metadata",
      );
      updatedRows = await app.db
        .update(devices)
        .set({
          label: input.label,
          platform: input.platform,
          appVersion: input.appVersion,
          lastSeenAt: now,
          updatedAt: now,
        })
        .where(eq(devices.id, existingRows[0].id))
        .returning(deviceRegistrationReturning);
    }

    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "device.mobile.register",
      resourceType: "device",
      resourceId: existingRows[0].id,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        externalDeviceId: input.externalDeviceId,
        ...mobileRegistrationAuditMetadata(input),
      },
    });

    return updatedRows[0];
  }

  let insertedRows;

  try {
    insertedRows = await app.db
      .insert(devices)
      .values({
        userId: input.userId,
        type: "mobile",
        externalDeviceId: input.externalDeviceId,
        label: input.label,
        platform: input.platform,
        appVersion: input.appVersion,
        clientMetadata,
        pairedAt: now,
        lastSeenAt: now,
      })
      .returning(deviceRegistrationReturning);
  } catch (error) {
    const code =
      typeof error === "object" && error && "code" in error
        ? String(error.code)
        : "";

    if (isUndefinedColumnError(error)) {
      app.log.warn(
        { requestId: input.requestId },
        "devices.client_metadata migration missing; inserting mobile without optional metadata",
      );
      try {
        insertedRows = await app.db
          .insert(devices)
          .values({
            userId: input.userId,
            type: "mobile",
            externalDeviceId: input.externalDeviceId,
            label: input.label,
            platform: input.platform,
            appVersion: input.appVersion,
            pairedAt: now,
            lastSeenAt: now,
          })
          .returning(deviceRegistrationReturning);
      } catch (fallbackError) {
        const fallbackCode =
          typeof fallbackError === "object" &&
          fallbackError &&
          "code" in fallbackError
            ? String(fallbackError.code)
            : "";
        if (fallbackCode !== "23505") {
          throw fallbackError;
        }
        const racedRows = await app.db
          .select(deviceRegistrationReturning)
          .from(devices)
          .where(
            and(
              eq(devices.userId, input.userId),
              eq(devices.type, "mobile"),
              eq(devices.externalDeviceId, input.externalDeviceId),
            ),
          )
          .limit(1);
        if (racedRows[0]) {
          return racedRows[0];
        }
        throw fallbackError;
      }
    } else if (code === "23505") {
      const racedRows = await app.db
        .select(deviceRegistrationReturning)
        .from(devices)
        .where(
          and(
            eq(devices.userId, input.userId),
            eq(devices.type, "mobile"),
            eq(devices.externalDeviceId, input.externalDeviceId),
          ),
        )
        .limit(1);

      if (racedRows[0]) {
        return racedRows[0];
      }
      throw error;
    } else {
      throw error;
    }
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "device.mobile.register",
    resourceType: "device",
    resourceId: insertedRows[0]?.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      externalDeviceId: input.externalDeviceId,
    },
  });

  invalidateBrainProfileCache(app, input.userId);
  return insertedRows[0];
}

export function isUndefinedColumnError(error: unknown): boolean {
  return Boolean(
    typeof error === "object" &&
    error &&
    "code" in error &&
    String(error.code) === "42703",
  );
}

export async function deactivateUserDevice(
  app: FastifyInstance,
  userId: string,
  deviceId: string,
) {
  const deviceRows = await app.db
    .select({
      id: devices.id,
      type: devices.type,
      isActive: devices.isActive,
    })
    .from(devices)
    .where(and(eq(devices.id, deviceId), eq(devices.userId, userId)))
    .limit(1);

  const device = deviceRows[0];

  if (!device) {
    throw notFound("Device not found");
  }

  if (!device.isActive) {
    throw conflict("Device is already inactive");
  }

  const now = new Date();

  // 1. Mark device inactive and wipe the deviceKeyHash so the old deviceSecret
  //    can never be used to re-register or heartbeat again.
  const rows = await app.db
    .update(devices)
    .set({
      isActive: false,
      deviceKeyHash: null,     // invalidate stored secret
      updatedAt: now,
    })
    .where(eq(devices.id, device.id))
    .returning();

  // 2. Disconnect all active runtime connections for this device.
  await app.db
    .update(runtimeConnections)
    .set({
      status: "offline",
      disconnectedAt: now,
    })
    .where(
      and(
        eq(runtimeConnections.deviceId, device.id),
        isNull(runtimeConnections.disconnectedAt),
      ),
    );

  // 3. Force-close any live WebSocket with a specific close code so the desktop
  //    bridge knows it was deactivated (not a transient drop) and clears creds.
  app.services.realtimeHub.closeRuntime(device.id, 4003, "device_deactivated");

  invalidateBrainProfileCache(app, userId);
  return rows[0];
}

export async function listDeviceTaskBacklog(
  app: FastifyInstance,
  userId: string,
  deviceId: string,
) {
  const deviceRows = await app.db
    .select({
      id: devices.id,
      userId: devices.userId,
      type: devices.type,
    })
    .from(devices)
    .where(and(eq(devices.id, deviceId), eq(devices.userId, userId)))
    .limit(1);

  const device = deviceRows[0];

  if (!device || device.type !== "desktop") {
    throw notFound("Desktop device not found");
  }

  return app.db
    .select({
      id: tasks.id,
      title: tasks.title,
      status: tasks.status,
      queuePosition: tasks.queuePosition,
      createdAt: tasks.createdAt,
      updatedAt: tasks.updatedAt,
    })
    .from(tasks)
    .where(
      and(
        eq(tasks.userId, userId),
        eq(tasks.targetDeviceId, deviceId),
        inArray(tasks.status, [
          "queued",
          "planning",
          "running",
          "waiting_approval",
        ]),
      ),
    )
    .orderBy(tasks.queuePosition, tasks.createdAt);
}
