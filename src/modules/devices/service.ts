import { and, desc, eq, inArray, isNull, lt, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { devices, pairSessions, runtimeConnections, tasks } from "../../db/schema.js";
import { getBaseUrlReachability } from "../../config/env.js";
import { conflict, notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import { canUseDesktopConnections } from "../billing/catalog.js";
import { getUserUsageAccessTruth } from "../billing/service.js";
import { invalidateBrainProfileCache } from "../brain/profile-cache.js";
import {
  normalizeRuntimeCapabilities,
  summarizeRuntimeCapabilities,
  summarizeRuntimeCapabilityReadiness,
} from "../runtime/capabilities.js";

export const RUNTIME_CONNECTION_STALE_AFTER_MS = 300_000; // 5 minutes — relay sends heartbeats every 2-5s so this is very forgiving

/**
 * Bu cihazın GERÇEKTEN canlı bir runtime bağlantısı var mı?
 *
 * `devices.lastSeenAt` bu soruyu cevaplamaz: o damga canlı bir soket olmadan da
 * tazelenebiliyor. Canlı arıza (2026-08-13): kullanıcı masaüstünde `unpair`
 * yaptı, `pair` ile yeni kod aldı ve mobilde kodu girince "Desktop runtime is
 * already paired with another user" gördü. Ölçüm o anda şunu söylüyordu:
 *
 *   devices.last_seen_at = 08:13:49  (taze → çakışma kontrolü "canlı" sandı)
 *   runtime_connections  = offline, son heartbeat 04:26, disconnected_at dolu
 *
 * Yani makinenin hiç bağlantısı yokken kendi bilgisayarını geri alamıyordu ve
 * bekleme dışında çıkış yolu yoktu: her `pair` denemesi damgayı yeniden
 * tazeliyordu.
 *
 * Otoriter sinyal soketin kendisi. Bu yardımcı KORUMAYI ZAYIFLATMAZ: başka bir
 * kullanıcının o an bağlı masaüstünün `online` ve taze heartbeat'li bir kaydı
 * olur, dolayısıyla devralınamaz.
 */
export async function hasLiveRuntimeConnection(
  app: FastifyInstance,
  deviceId: string,
): Promise<boolean> {
  if (!deviceId) return false;
  const rows = await app.db
    .select({
      status: runtimeConnections.status,
      lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
      disconnectedAt: runtimeConnections.disconnectedAt,
    })
    .from(runtimeConnections)
    .where(eq(runtimeConnections.deviceId, deviceId))
    .orderBy(desc(runtimeConnections.connectedAt))
    .limit(1);
  const row = rows[0];
  if (!row) return false;
  if (row.status === "offline" || row.disconnectedAt) return false;
  const heartbeat = row.lastHeartbeatAt?.getTime() ?? 0;
  return Date.now() - heartbeat <= RUNTIME_CONNECTION_STALE_AFTER_MS;
}
const SHARED_BRAIN_TARGET_CACHE_TTL_MS = 2_000;

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

type SharedBrainTargetDevice = ReturnType<typeof shapeUserDevice> & {
  serverBrainName: string;
};

type SharedBrainTargetCacheEntry = {
  value?: SharedBrainTargetDevice | null;
  expiresAt: number;
  inFlight?: Promise<SharedBrainTargetDevice | null>;
};

const sharedBrainTargetCache = new WeakMap<
  FastifyInstance,
  SharedBrainTargetCacheEntry
>();

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
  const runtimeConnected =
    (runtimeFresh || wsConnected) && runtime?.status !== "offline";
  const runtimeStale =
    Boolean(runtime) &&
    runtime?.status !== "offline" &&
    !runtimeFresh &&
    !wsConnected;
  const normalizedCapabilities = runtime
    ? normalizeRuntimeCapabilities(runtime.capabilities)
    : [];
  const isDesktop = device.type === "desktop";
  // When WS is live and the connection row exists (even with disconnectedAt), treat as online
  const isOnline =
    isDesktop && (runtimeConnected || (wsConnected && Boolean(runtime)));
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
  const transportReady = realtimeReady;
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
    transportReady,
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
            capabilityReadinessSummary:
              summarizeRuntimeCapabilityReadiness(runtime.capabilityStates),
            currentTaskId: runtime.currentTaskId,
            connectedAt: runtime.connectedAt,
            lastHeartbeatAt: runtime.lastHeartbeatAt,
            stale: false,
            transportMode,
            queuedTaskCount,
            realtimeReady,
            transportReady,
          }
        : {
            isConnected: false,
            status: (runtime?.status ?? "offline") as
              "online" | "busy" | "idle" | "offline",
            capabilities: normalizedCapabilities,
            capabilityStates: runtime?.capabilityStates ?? {},
            capabilitySummary: summarizeRuntimeCapabilities(
              normalizedCapabilities,
            ),
            capabilityReadinessSummary:
              summarizeRuntimeCapabilityReadiness(runtime?.capabilityStates ?? {}),
            currentTaskId: runtime?.currentTaskId ?? null,
            connectedAt: runtime?.connectedAt ?? null,
            lastHeartbeatAt: runtime?.lastHeartbeatAt ?? null,
            stale: runtimeStale,
            transportMode,
            queuedTaskCount,
            realtimeReady,
            transportReady,
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
  const now = Date.now();
  const cached = sharedBrainTargetCache.get(app);
  if (cached?.inFlight) return cached.inFlight;
  if (cached && cached.expiresAt > now && cached.value !== undefined) {
    return cached.value;
  }

  const lookup = (async (): Promise<SharedBrainTargetDevice | null> => {
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
  })();

  sharedBrainTargetCache.set(app, {
    value: cached?.value,
    expiresAt: 0,
    inFlight: lookup,
  });
  try {
    const value = await lookup;
    sharedBrainTargetCache.set(app, {
      value,
      expiresAt: Date.now() + SHARED_BRAIN_TARGET_CACHE_TTL_MS,
    });
    return value;
  } catch (error) {
    sharedBrainTargetCache.delete(app);
    throw error;
  }
}

export function invalidateSharedBrainTargetDeviceCache(app: FastifyInstance) {
  sharedBrainTargetCache.delete(app);
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

    invalidateSharedBrainTargetDeviceCache(app);
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

  invalidateSharedBrainTargetDeviceCache(app);
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

type UserDevicesCacheEntry = {
  value: Awaited<ReturnType<typeof listUserDevicesUncached>>;
  expiresAt: number;
};

/**
 * Aynı istek içinde cihaz listesini TEKİLLEŞTİRİR.
 *
 * Yönlendirme kararı artık iki kez cihaz durumuna bakıyor: (1) kullanıcının
 * canlı bir masaüstü çalışma zamanı var mı — modelin "sohbet" kararının
 * bağlayıcı olup olmadığını belirler, (2) hedef cihazın seçimi. İkisi de aynı
 * sorguyu çalıştırıyordu; çok kısa ömürlü bu önbellek ikinci okumayı bedava
 * yapar. TTL bilinçli olarak çok kısa: cihaz çevrimdışı olduğunda karar
 * saniyeler içinde güncellenmeli.
 */
const USER_DEVICES_CACHE_TTL_MS = 2_000;
const userDevicesCache = new WeakMap<
  FastifyInstance,
  Map<string, UserDevicesCacheEntry>
>();

export async function listUserDevices(app: FastifyInstance, userId: string) {
  const now = Date.now();
  const perApp = userDevicesCache.get(app) ?? new Map<string, UserDevicesCacheEntry>();
  userDevicesCache.set(app, perApp);
  const cached = perApp.get(userId);
  if (cached && cached.expiresAt > now) {
    return cached.value;
  }
  const value = await listUserDevicesUncached(app, userId);
  perApp.set(userId, { value, expiresAt: now + USER_DEVICES_CACHE_TTL_MS });
  return value;
}

async function listUserDevicesUncached(app: FastifyInstance, userId: string) {
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
    // Deactivated devices are kept in the DB for audit / task history reasons
    // but must NOT leak into the user-facing list — that's exactly the bug
    // that made deleted desktops "resurrect" days later on the client. Only
    // active rows are user-visible.
    .where(and(eq(devices.userId, userId), eq(devices.isActive, true)))
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
  const recentByDeviceId = new Map<string, (typeof recentConnections)[0]>();
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
    const wsConnected =
      device.type === "desktop"
        ? Boolean(app.services.realtimeHub?.isRuntimeConnected?.(device.id))
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
  const wsConnected =
    device.type === "desktop"
      ? Boolean(app.services.realtimeHub?.isRuntimeConnected?.(device.id))
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
    capabilities?: string[];
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
  // The token is duplicated into client_metadata on purpose: the dedicated
  // columns are authoritative, but a deployment whose 0048 migration has not
  // run yet still needs a place for the sender to read from.
  const clientMetadata = {
    pushToken: input.pushToken ?? null,
    pushProvider: input.pushProvider ?? null,
    notificationAuthorizationStatus:
      input.notificationAuthorizationStatus ?? null,
    supportsLiveActivities: input.supportsLiveActivities ?? false,
    supportsDynamicIsland: input.supportsDynamicIsland ?? false,
    backgroundRefreshEnabled: input.backgroundRefreshEnabled ?? false,
    capabilities: input.capabilities ?? [],
    buildMetadata: input.buildMetadata ?? {},
  };
  // A fresh token from the same install clears an earlier "provider says this
  // token is dead" mark; without this the device would stay silent forever
  // after one transient unregister.
  const pushColumns = input.pushToken
    ? {
        pushToken: input.pushToken,
        pushProvider: input.pushProvider ?? "fcm",
        pushTokenUpdatedAt: now,
        pushInvalidatedAt: null,
        notificationAuthorizationStatus:
          input.notificationAuthorizationStatus ?? null,
      }
    : {
        notificationAuthorizationStatus:
          input.notificationAuthorizationStatus ?? null,
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
          ...pushColumns,
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
        ...pushColumns,
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

/**
 * Token-only update path. Returns `registered: false` when the device is not
 * known yet — the client then falls back to a full registration instead of
 * silently believing push is on.
 */
export async function updateDevicePushToken(
  app: FastifyInstance,
  input: {
    userId: string;
    externalDeviceId: string;
    pushToken: string | null;
    pushProvider?: string;
    notificationAuthorizationStatus?: string;
  },
): Promise<{ registered: boolean; pushEnabled: boolean }> {
  const rows = await app.db
    .select({
      id: devices.id,
      platform: devices.platform,
      clientMetadata: devices.clientMetadata,
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

  const existing = rows[0];
  if (!existing) {
    return { registered: false, pushEnabled: false };
  }

  const now = new Date();
  // The provider must describe the token we are storing. Defaulting to "fcm"
  // on an iOS device would make the APNs dispatcher skip it as an unsupported
  // provider — silently, forever.
  const defaultProvider = String(existing.platform ?? "")
    .toLowerCase()
    .includes("ios")
    ? "apns"
    : "fcm";
  const metadata =
    existing.clientMetadata && typeof existing.clientMetadata === "object"
      ? (existing.clientMetadata as Record<string, unknown>)
      : {};
  const nextMetadata = {
    ...metadata,
    pushToken: input.pushToken,
    pushProvider: input.pushToken ? (input.pushProvider ?? defaultProvider) : null,
    notificationAuthorizationStatus:
      input.notificationAuthorizationStatus ??
      (metadata.notificationAuthorizationStatus as string | undefined) ??
      null,
  };

  const columns = input.pushToken
    ? {
        pushToken: input.pushToken,
        pushProvider: input.pushProvider ?? defaultProvider,
        pushTokenUpdatedAt: now,
        pushInvalidatedAt: null,
      }
    : {
        // Explicit revoke (user turned notifications off): drop the token
        // rather than marking it invalid, so we never treat it as a
        // provider-side failure.
        pushToken: null,
        pushProvider: null,
        pushTokenUpdatedAt: now,
        pushInvalidatedAt: null,
      };

  try {
    await app.db
      .update(devices)
      .set({
        ...columns,
        notificationAuthorizationStatus:
          input.notificationAuthorizationStatus ?? null,
        clientMetadata: nextMetadata,
        lastSeenAt: now,
        updatedAt: now,
      })
      .where(eq(devices.id, existing.id));
  } catch (error) {
    if (!isUndefinedColumnError(error)) {
      throw error;
    }
    app.log.warn(
      "devices.push_token migration missing; storing push token in client_metadata only",
    );
    await app.db
      .update(devices)
      .set({ clientMetadata: nextMetadata, lastSeenAt: now, updatedAt: now })
      .where(eq(devices.id, existing.id));
  }

  return { registered: true, pushEnabled: Boolean(input.pushToken) };
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

  // 1. Mark device inactive, wipe the deviceKeyHash so the old deviceSecret
  //    can never be used to re-register or heartbeat again, and RELEASE
  //    OWNERSHIP.
  //
  //    `userId` eskiden korunuyordu: cihaz pasifleşiyor ama o hesaba AİT
  //    kalmaya devam ediyordu. Sonuç, kullanıcının canlıda gördüğü hâl —
  //    mobilden bağlantıyı koparıyor, sonra aynı bilgisayarı yeniden
  //    eşleştirmek isteyince "Desktop runtime is already paired with another
  //    user" alıyor. Kopardığı şey aslında hiç kopmamış oluyordu.
  //
  //    Sahiplik bırakılınca kayıt sahipsiz kalır; aynı makine herhangi bir
  //    hesaba yeniden eşleşebilir. Geçmiş kaybolmaz: görevler `deviceId`ye
  //    bağlı, `userId`ye değil.
  const rows = await app.db
    .update(devices)
    .set({
      isActive: false,
      userId: null,
      deviceKeyHash: null, // invalidate stored secret
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

  // 3. Delete any pending pair sessions bound to this device so the desktop
  //    can't complete a stale claim or reuse an old pairing code after being
  //    removed. Ghost pair sessions were part of the "deleted device came
  //    back" bug class.
  await app.db
    .delete(pairSessions)
    .where(eq(pairSessions.desktopDeviceId, device.id));

  // 4. Force-close any live WebSocket with a specific close code so the desktop
  //    bridge knows it was deactivated (not a transient drop) and clears creds.
  app.services.realtimeHub.closeRuntime(device.id, 4003, "device_deactivated");

  // 5. Notify mobile via SSE so it refreshes device status immediately without
  //    waiting for the next bootstrap poll.
  await app.services.eventBus.publishVolatile({
    topic: "device.status_changed",
    userId,
    deviceId: device.id,
    payload: {
      deviceId: device.id,
      isActive: false,
      isOnline: false,
      reason: "device_deactivated",
    },
  });

  invalidateBrainProfileCache(app, userId);
  return rows[0];
}

const STALE_MOBILE_DEVICE_DAYS = 90;

export async function pruneStaleDevices(
  app: FastifyInstance,
  userId: string,
): Promise<void> {
  const cutoff = new Date(
    Date.now() - STALE_MOBILE_DEVICE_DAYS * 24 * 60 * 60 * 1000,
  );
  const staleRows = await app.db
    .select({ id: devices.id })
    .from(devices)
    .where(
      and(
        eq(devices.userId, userId),
        eq(devices.type, "mobile"),
        eq(devices.isActive, true),
        lt(devices.lastSeenAt, cutoff),
      ),
    );
  for (const row of staleRows) {
    await deactivateUserDevice(app, userId, row.id).catch(() => undefined);
  }
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
