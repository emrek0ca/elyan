import type { FastifyPluginAsync } from "fastify";
import type { TaskStatus } from "../../contracts/domain.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { approvalBodySchema, createTaskBodySchema, listTasksQuerySchema, taskParamsSchema } from "./schemas.js";
import { cancelTask, createTask, getTaskDetail, listTasks, resolveTaskApproval } from "./service.js";

export const taskRoutes: FastifyPluginAsync = async (app) => {
  app.post("/", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createTaskBodySchema.parse(request.body);
    const auth = getUserAuth(request);

    return createTask(app, {
      userId: auth.sub,
      targetDeviceId: body.targetDeviceId,
      title: body.title,
      payload: body.payload,
      requestedCapabilities: body.requestedCapabilities,
      preferredAiProvider: body.preferredAiProvider,
    });
  });

  app.get("/", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const query = listTasksQuerySchema.parse(request.query);
    const auth = getUserAuth(request);
    const statuses = query.status
      ? (query.status
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean) as TaskStatus[])
      : undefined;

    return {
      tasks: await listTasks(app, {
        userId: auth.sub,
        targetDeviceId: query.targetDeviceId,
        statuses,
        limit: query.limit,
      }),
    };
  });

  app.get("/:taskId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = taskParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    return getTaskDetail(app, params.taskId, auth.sub);
  });

  app.post("/:taskId/cancel", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = taskParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    return cancelTask(app, params.taskId, auth.sub);
  });

  app.post("/:taskId/approval", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = taskParamsSchema.parse(request.params);
    const body = approvalBodySchema.parse(request.body);
    const auth = getUserAuth(request);

    return resolveTaskApproval(app, {
      taskId: params.taskId,
      userId: auth.sub,
      approved: body.approved,
      notes: body.notes,
    });
  });
};
