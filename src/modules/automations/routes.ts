import type { FastifyPluginAsync } from "fastify";
import { getUserAuth } from "../../lib/request-auth.js";
import {
  automationParamsSchema,
  createAutomationBodySchema,
  listAutomationsQuerySchema,
  updateAutomationBodySchema,
} from "./schemas.js";
import {
  cancelAutomation,
  createAutomation,
  listAutomations,
  updateAutomation,
} from "./service.js";

export const automationRoutes: FastifyPluginAsync = async (app) => {
  app.get("/", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const auth = getUserAuth(request);
    const query = listAutomationsQuerySchema.parse(request.query ?? {});
    return listAutomations(app, { userId: auth.sub, limit: query.limit });
  });

  app.post("/", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const auth = getUserAuth(request);
    const body = createAutomationBodySchema.parse(request.body);
    return createAutomation(app, {
      userId: auth.sub,
      sourceTaskId: body.sourceTaskId,
      title: body.title,
      intervalMinutes: body.intervalMinutes,
      timezone: body.timezone,
      firstRunAt: body.firstRunAt ? new Date(body.firstRunAt) : undefined,
      targetDeviceId: body.targetDeviceId,
    });
  });

  app.patch("/:automationId", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const auth = getUserAuth(request);
    const params = automationParamsSchema.parse(request.params);
    const body = updateAutomationBodySchema.parse(request.body);
    return updateAutomation(app, {
      userId: auth.sub,
      automationId: params.automationId,
      status: body.status,
    });
  });

  app.delete("/:automationId", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const auth = getUserAuth(request);
    const params = automationParamsSchema.parse(request.params);
    return cancelAutomation(app, {
      userId: auth.sub,
      automationId: params.automationId,
    });
  });
};
