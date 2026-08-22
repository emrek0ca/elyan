import type { FastifyPluginAsync } from "fastify";
import { getRequestContext } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import {
  deviceParamsSchema,
  registerMobileDeviceBodySchema,
  updatePushTokenBodySchema,
} from "./schemas.js";
import {
  deactivateUserDevice,
  listDeviceTaskBacklog,
  listUserDevices,
  registerMobileDevice,
  updateDevicePushToken,
} from "./service.js";
import { reconcileStaleRuntimeTasks } from "../tasks/service.js";

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
