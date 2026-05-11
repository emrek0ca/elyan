import { randomUUID } from "node:crypto";
import { and, eq, inArray, isNull } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { devices, runtimeConnections, tasks } from "../../db/schema.js";
import { signRuntimeAccessToken } from "../../lib/auth-tokens.js";
import { conflict, notFound, unauthorized } from "../../lib/errors.js";
import { verifySecret } from "../../lib/auth-crypto.js";
import type { RuntimeAuthTokenPayload } from "../../types/auth.js";

export async function registerRuntime(
  app: FastifyInstance,
  input: {
    deviceId: string;
    deviceSecret: string;
    runtimeVersion?: string;
    capabilities: string[];
  },
) {
  const rows = await app.db
    .select({
      id: devices.id,
      userId: devices.userId,
      label: devices.label,
      type: devices.type,
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

  if (!device.userId || !device.deviceKeyHash) {
    throw conflict("Desktop runtime has not completed pairing");
  }

  const secretMatches = await verifySecret(input.deviceSecret, device.deviceKeyHash);

  if (!secretMatches) {
    throw unauthorized("Device secret is invalid");
  }

  await app.db
    .update(runtimeConnections)
    .set({
      status: "offline",
      disconnectedAt: new Date(),
    })
    .where(and(eq(runtimeConnections.deviceId, device.id), isNull(runtimeConnections.disconnectedAt)));

  await app.db
    .update(devices)
    .set({
      runtimeVersion: input.runtimeVersion,
      lastSeenAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(devices.id, device.id));

  const socketSessionId = randomUUID();

  await app.db.insert(runtimeConnections).values({
    deviceId: device.id,
    userId: device.userId,
    status: "online",
    socketSessionId,
    capabilities: input.capabilities,
  });

  const tokenPayload: RuntimeAuthTokenPayload = {
    kind: "runtime",
    sub: device.userId,
    deviceId: device.id,
    deviceType: "desktop",
  };
  const accessToken = await signRuntimeAccessToken(app, tokenPayload);

  return {
    runtime: {
      deviceId: device.id,
      label: device.label,
      platform: device.platform,
    },
    capabilities: input.capabilities,
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
  await app.db
    .update(runtimeConnections)
    .set({
      status: "online",
      socketSessionId,
      lastHeartbeatAt: new Date(),
      disconnectedAt: null,
    })
    .where(and(eq(runtimeConnections.deviceId, auth.deviceId), eq(runtimeConnections.userId, auth.sub)));

  await app.db
    .update(devices)
    .set({
      lastSeenAt: new Date(),
      updatedAt: new Date(),
    })
    .where(eq(devices.id, auth.deviceId));
}

export async function heartbeatRuntime(
  app: FastifyInstance,
  auth: RuntimeAuthTokenPayload,
  input: {
    status: "online" | "busy" | "idle";
    currentTaskId?: string;
  },
) {
  await app.db
    .update(runtimeConnections)
    .set({
      status: input.status,
      currentTaskId: input.currentTaskId,
      lastHeartbeatAt: new Date(),
      disconnectedAt: null,
    })
    .where(and(eq(runtimeConnections.deviceId, auth.deviceId), eq(runtimeConnections.userId, auth.sub)));

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
  };
}

export async function disconnectRuntime(app: FastifyInstance, auth: RuntimeAuthTokenPayload): Promise<void> {
  await app.db
    .update(runtimeConnections)
    .set({
      status: "offline",
      disconnectedAt: new Date(),
    })
    .where(and(eq(runtimeConnections.deviceId, auth.deviceId), eq(runtimeConnections.userId, auth.sub)));
}

export async function listAssignedRuntimeTasks(app: FastifyInstance, auth: RuntimeAuthTokenPayload) {
  return app.db
    .select({
      id: tasks.id,
      title: tasks.title,
      payload: tasks.payload,
      requestedCapabilities: tasks.requestedCapabilities,
      preferredAiProvider: tasks.preferredAiProvider,
      status: tasks.status,
      approvalRequest: tasks.approvalRequest,
      createdAt: tasks.createdAt,
      updatedAt: tasks.updatedAt,
    })
    .from(tasks)
    .where(
      and(
        eq(tasks.userId, auth.sub),
        eq(tasks.targetDeviceId, auth.deviceId),
        inArray(tasks.status, ["queued", "running", "waiting_approval"]),
      ),
    )
    .orderBy(tasks.createdAt);
}
