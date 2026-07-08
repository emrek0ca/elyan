import type { FastifyPluginAsync, FastifyReply, FastifyRequest } from "fastify";
import type { TaskStatus } from "../../contracts/domain.js";
import { getRequestContext, serializeZodError } from "../../lib/http.js";
import { getIdempotencyKey } from "../../lib/idempotency.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { approvalBodySchema, createTaskBodySchema, feedbackBodySchema, listTasksQuerySchema, taskArtifactParamsSchema, taskParamsSchema } from "./schemas.js";
import { cancelTask, createTask, getTaskArtifact, getTaskArtifactContent, getTaskArtifactRawContent, getTaskDetail, listTasks, resolveTaskApproval, submitTaskFeedback } from "./service.js";

function parseTaskParamsOrReply(request: FastifyRequest, reply: FastifyReply): { taskId: string } | null {
  const parsed = taskParamsSchema.safeParse(request.params);
  if (!parsed.success) {
    reply.status(400).send({
      error: "validation_error",
      message: "Invalid task id",
      details: serializeZodError(parsed.error),
      requestId: request.id,
    });
    return null;
  }
  return parsed.data;
}

function parseTaskArtifactParamsOrReply(
  request: FastifyRequest,
  reply: FastifyReply,
): { taskId: string; artifactId: string } | null {
  const parsed = taskArtifactParamsSchema.safeParse(request.params);
  if (!parsed.success) {
    reply.status(400).send({
      error: "validation_error",
      message: "Invalid artifact params",
      details: serializeZodError(parsed.error),
      requestId: request.id,
    });
    return null;
  }
  return parsed.data;
}

export const taskRoutes: FastifyPluginAsync = async (app) => {
  app.post("/", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createTaskBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    const idempotencyKey = getIdempotencyKey(request);

    return createTask(app, {
      userId: auth.sub,
      targetDeviceId: body.targetDeviceId,
      requestedTargetDeviceId: body.targetDeviceId,
      title: body.title,
      payload: body.payload,
      requestedCapabilities: body.requestedCapabilities,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
      idempotencyKey,
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

    const params = parseTaskParamsOrReply(request, reply);
    if (!params) {
      return;
    }
    const auth = getUserAuth(request);
    return getTaskDetail(app, params.taskId, auth.sub);
  });

  app.get("/:taskId/artifacts/:artifactId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = parseTaskArtifactParamsOrReply(request, reply);
    if (!params) {
      return;
    }
    const auth = getUserAuth(request);
    return getTaskArtifact(app, params.taskId, params.artifactId, auth.sub);
  });

  app.get("/:taskId/artifacts/:artifactId/content/raw", async (request, reply) => {
    const params = parseTaskArtifactParamsOrReply(request, reply);
    if (!params) {
      return;
    }
    const query = request.query && typeof request.query === "object"
      ? (request.query as Record<string, unknown>)
      : {};
    const token = typeof query.token === "string" ? query.token : null;
    const content = await getTaskArtifactRawContent(app, params.taskId, params.artifactId, token);
    reply
      .header("Cache-Control", "private, max-age=600")
      .header("Content-Disposition", `inline; filename="${content.fileName.replace(/"/g, "")}"`)
      .type(content.contentType)
      .send(content.body);
  });

  app.get("/:taskId/artifacts/:artifactId/content", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = parseTaskArtifactParamsOrReply(request, reply);
    if (!params) {
      return;
    }
    const auth = getUserAuth(request);
    return getTaskArtifactContent(app, params.taskId, params.artifactId, auth.sub);
  });

  app.post("/:taskId/cancel", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = parseTaskParamsOrReply(request, reply);
    if (!params) {
      return;
    }
    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    return cancelTask(app, params.taskId, auth.sub, {
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });

  app.post("/:taskId/approval", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = parseTaskParamsOrReply(request, reply);
    if (!params) {
      return;
    }
    const body = approvalBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return resolveTaskApproval(app, {
      taskId: params.taskId,
      userId: auth.sub,
      approved: body.approved,
      notes: body.notes,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });

  app.post("/:taskId/feedback", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = parseTaskParamsOrReply(request, reply);
    if (!params) {
      return;
    }
    const body = feedbackBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return submitTaskFeedback(app, {
      taskId: params.taskId,
      userId: auth.sub,
      feedbackType: body.type,
      reasonTags: body.reasonTags,
      correction: body.correction,
      preferredAnswer: body.preferredAnswer,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });
};
