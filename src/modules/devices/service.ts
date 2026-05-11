import { and, desc, eq, inArray, isNull } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { devices, runtimeConnections, tasks } from "../../db/schema.js";
import { conflict, notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";

export async function listUserDevices(app: FastifyInstance, userId: string) {
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

  const desktopIds = deviceRows.filter((device) => device.type === "desktop").map((device) => device.id);
  const activeConnections =
    desktopIds.length > 0
      ? await app.db
          .select({
            id: runtimeConnections.id,
            deviceId: runtimeConnections.deviceId,
            status: runtimeConnections.status,
            capabilities: runtimeConnections.capabilities,
            currentTaskId: runtimeConnections.currentTaskId,
            connectedAt: runtimeConnections.connectedAt,
            lastHeartbeatAt: runtimeConnections.lastHeartbeatAt,
          })
          .from(runtimeConnections)
          .where(and(inArray(runtimeConnections.deviceId, desktopIds), isNull(runtimeConnections.disconnectedAt)))
      : [];

  const activeByDeviceId = new Map(activeConnections.map((connection) => [connection.deviceId, connection]));

  return deviceRows.map((device) => {
    const runtime = device.type === "desktop" ? activeByDeviceId.get(device.id) ?? null : null;

    return {
      ...device,
      runtime: runtime
        ? {
            isConnected: true,
            status: runtime.status,
            capabilities: runtime.capabilities,
            currentTaskId: runtime.currentTaskId,
            connectedAt: runtime.connectedAt,
            lastHeartbeatAt: runtime.lastHeartbeatAt,
          }
        : {
            isConnected: false,
            status: "offline",
            capabilities: [],
            currentTaskId: null,
            connectedAt: null,
            lastHeartbeatAt: null,
          },
    };
  });
}

export async function registerMobileDevice(
  app: FastifyInstance,
  input: {
    userId: string;
    externalDeviceId: string;
    label: string;
    platform: string;
    appVersion?: string;
    ipAddress?: string;
    userAgent?: string;
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

  if (existingRows[0]) {
    const updatedRows = await app.db
      .update(devices)
      .set({
        label: input.label,
        platform: input.platform,
        appVersion: input.appVersion,
        lastSeenAt: now,
        updatedAt: now,
      })
      .where(eq(devices.id, existingRows[0].id))
      .returning();

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
      payload: {
        externalDeviceId: input.externalDeviceId,
      },
    });

    return updatedRows[0];
  }

  const insertedRows = await app.db
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
    .returning();

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
    payload: {
      externalDeviceId: input.externalDeviceId,
    },
  });

  return insertedRows[0];
}

export async function deactivateUserDevice(app: FastifyInstance, userId: string, deviceId: string) {
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

  const rows = await app.db
    .update(devices)
    .set({
      isActive: false,
      updatedAt: new Date(),
    })
    .where(eq(devices.id, device.id))
    .returning();

  return rows[0];
}

export async function listDeviceTaskBacklog(app: FastifyInstance, userId: string, deviceId: string) {
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
        inArray(tasks.status, ["queued", "planning", "running", "waiting_approval"]),
      ),
    )
    .orderBy(tasks.queuePosition, tasks.createdAt);
}
