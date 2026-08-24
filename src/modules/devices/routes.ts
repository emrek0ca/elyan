import type { FastifyPluginAsync } from "fastify";
import { getRequestContext } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { AppError } from "../../lib/errors.js";
import {
  deviceParamsSchema,
  registerMobileDeviceBodySchema,
  runtimeAccessBodySchema,
  updatePushTokenBodySchema,
} from "./schemas.js";
import {
  deactivateUserDevice,
  listDeviceTaskBacklog,
  listUserDevices,
  getUserDevice,
  registerMobileDevice,
  updateDevicePushToken,
} from "./service.js";
import { reconcileStaleRuntimeTasks } from "../tasks/service.js";
import {
  abandonRuntimeAccessCommand,
  issueRuntimeAccessCommand,
} from "../runtime/service.js";
import { RUNTIME_ACCESS_SESSION_TTL_SECONDS } from "../runtime/access-state.js";

export const deviceRoutes: FastifyPluginAsync = async (app) => {
  app.get("/", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      devices: await listUserDevices(app, auth.sub),
    };
  });

  app.post("/mobile/register", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = registerMobileDeviceBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return registerMobileDevice(app, {
      userId: auth.sub,
      externalDeviceId: body.externalDeviceId,
      label: body.label,
      platform: body.platform,
      appVersion: body.appVersion,
      pushToken: body.pushToken ?? undefined,
      pushProvider: body.pushProvider ?? undefined,
      notificationAuthorizationStatus:
        body.notificationAuthorizationStatus ?? undefined,
      supportsLiveActivities: body.supportsLiveActivities,
      supportsDynamicIsland: body.supportsDynamicIsland,
      backgroundRefreshEnabled: body.backgroundRefreshEnabled,
      capabilities: body.capabilities,
      buildMetadata: body.buildMetadata,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });

  app.post("/mobile/push-token", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = updatePushTokenBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const result = await updateDevicePushToken(app, {
      userId: auth.sub,
      externalDeviceId: body.externalDeviceId,
      pushToken: body.pushToken,
      pushProvider: body.pushProvider,
      notificationAuthorizationStatus: body.notificationAuthorizationStatus,
    });

    if (!result.registered) {
      reply.code(404);
      return { error: "device_not_registered" };
    }

    return result;
  });

  app.get("/:deviceId/backlog", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = deviceParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    return {
      tasks: await listDeviceTaskBacklog(app, auth.sub, params.deviceId),
    };
  });

  app.post("/:deviceId/runtime-access", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const params = deviceParamsSchema.parse(request.params);
    const body = runtimeAccessBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const device = await getUserDevice(app, auth.sub, params.deviceId);
    if (!device || device.type !== "desktop" || !device.isActive) {
      throw new AppError(404, "device_not_found", "Desktop device not found");
    }
    if (!device.runtime.capabilities.includes("runtime.access.session.v1")) {
      throw new AppError(
        409,
        "runtime_access_unsupported",
        "Desktop runtime does not support temporary access",
      );
    }
    if (!device.runtime.isConnected || !device.canReceiveTasks) {
      throw new AppError(409, "device_offline", "Desktop runtime is offline");
    }

    // Komut ÖNCE sunucuya yazılır. Bekleyen kayıt (commandId, action, revision,
    // issuedAt, beklenen süre sonu) olmadan hiçbir ACK erişim açamaz; süre sonu
    // da runtime'ın bildirdiği değere değil bu kayda göre kırpılır.
    const issued = await issueRuntimeAccessCommand(app, {
      userId: auth.sub,
      deviceId: device.id,
      action: body.action,
    });
    const delivered = await app.services.realtimeHub.sendToRuntimeDistributed(
      device.id,
      {
        type: "runtime.access.command",
        commandId: issued.commandId,
        action: body.action,
        ...(body.action === "grant_session"
          ? { ttlSeconds: RUNTIME_ACCESS_SESSION_TTL_SECONDS }
          : {}),
      },
    );
    if (!delivered) {
      await abandonRuntimeAccessCommand(app, {
        userId: auth.sub,
        deviceId: device.id,
        commandId: issued.commandId,
      });
      throw new AppError(
        409,
        "runtime_access_delivery_failed",
        "Temporary access command could not reach the desktop runtime",
      );
    }
    reply.code(202);
    return {
      accepted: true,
      commandId: issued.commandId,
      action: body.action,
      state: "pending",
      ...(body.action === "grant_session"
        ? { expiresAt: issued.expectedExpiresAt }
        : {}),
    };
  });

  app.post("/:deviceId/deactivate", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = deviceParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    const result = await deactivateUserDevice(app, auth.sub, params.deviceId);
    // Immediately reconcile stale tasks for the deactivated device so
    // running/planning tasks are re-queued without waiting for the sweeper.
    reconcileStaleRuntimeTasks(app, {
      userId: auth.sub,
      targetDeviceId: params.deviceId,
      limit: 50,
    }).catch(() => undefined);
    return result;
  });
};
