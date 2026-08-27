import type { FastifyPluginAsync, FastifyReply, FastifyRequest } from "fastify";
import { z } from "zod";
import type { TaskStatus } from "../../contracts/domain.js";
import { getRequestContext, serializeZodError } from "../../lib/http.js";
import { getIdempotencyKey } from "../../lib/idempotency.js";
import { assertRequestBudget } from "../../lib/reliability/request-budget.js";
import { getUserAuth, getUserScopedAuth } from "../../lib/request-auth.js";
import {
  approvalBodySchema,
  createTaskBodySchema,
  feedbackBodySchema,
  listTasksQuerySchema,
  taskControlBodySchema,
  taskArtifactParamsSchema,
  taskParamsSchema,
} from "./schemas.js";
import {
  cancelTask,
  createTask,
  getTaskArtifact,
  getTaskArtifactContent,
  getTaskArtifactRawContent,
  getTaskDetail,
  listTasks,
  requestTaskControl,
  resolveTaskApproval,
  submitTaskFeedback,
} from "./service.js";
import { releaseMediaInputRefs, storeMediaInput } from "./media-inputs.js";

const releaseMediaInputsBodySchema = z.object({
  inputRefs: z
    .array(z.object({ inputRef: z.string().min(1).max(4096) }).passthrough())
    .min(1)
    .max(4),
});

function parseTaskParamsOrReply(
  request: FastifyRequest,
  reply: FastifyReply,
): { taskId: string } | null {
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
  app.addContentTypeParser(
    ["image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"],
    { parseAs: "buffer", bodyLimit: 12 * 1024 * 1024 },
    (_request, body, done) => done(null, body),
  );

  app.post(
    "/media-inputs",
    {
      bodyLimit: 12 * 1024 * 1024,
      onRequest: async (request, reply) => {
        await app.authenticateUser(request, reply);
        if (reply.sent) return;
        const auth = getUserAuth(request);
        await Promise.all([
          assertRequestBudget(app, {
            scope: "media_input_ip",
            identity: request.ip,
            max: 80,
            windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
          }),
          assertRequestBudget(app, {
            scope: "media_input_user",
            identity: auth.sub,
            max: 60,
            windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
          }),
        ]);
      },
    },
    async (request, reply) => {
      if (!Buffer.isBuffer(request.body)) {
        return reply.status(400).send({
          error: "validation_error",
          message: "Binary image body required",
        });
      }
      const auth = getUserAuth(request);
      const contentType =
        String(request.headers["content-type"] ?? "").split(";", 1)[0] ?? "";
      const name = String(request.headers["x-elyan-file-name"] ?? "image");
      const intent = String(
        request.headers["x-elyan-media-intent"] ?? "attachment",
      );
      const temporalRole = request.headers["x-elyan-media-temporal-role"];
      const temporalSequence = request.headers["x-elyan-media-sequence"];
      return storeMediaInput(app, {
        userId: auth.sub,
        body: request.body,
        contentType,
        name,
        intent,
        temporalRole:
          typeof temporalRole === "string" ? temporalRole : undefined,
        temporalSequence:
          typeof temporalSequence === "string" ? temporalSequence : undefined,
      });
    },
  );

  app.delete("/media-inputs", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const parsed = releaseMediaInputsBodySchema.safeParse(request.body);
    if (!parsed.success) {
      return reply.status(400).send({
        error: "validation_error",
        message: "Invalid media input references",
        details: serializeZodError(parsed.error),
        requestId: request.id,
      });
    }
    const auth = getUserAuth(request);
    await releaseMediaInputRefs(app, auth.sub, parsed.data.inputRefs);
    return reply.status(204).send();
  });

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

  app.get(
    "/:taskId/artifacts/:artifactId/content/raw",
    async (request, reply) => {
      const params = parseTaskArtifactParamsOrReply(request, reply);
      if (!params) {
        return;
      }
      const query =
        request.query && typeof request.query === "object"
          ? (request.query as Record<string, unknown>)
          : {};
      const token = typeof query.token === "string" ? query.token : null;
      const variant = query.variant === "thumbnail" ? "thumbnail" : "original";
      const content = await getTaskArtifactRawContent(
        app,
        params.taskId,
        params.artifactId,
        token,
        variant,
      );
      reply
        .header("Cache-Control", "private, max-age=600")
        .header(
          "Content-Disposition",
          `inline; filename="${content.fileName.replace(/"/g, "")}"`,
        )
        .type(content.contentType)
        .send(content.body);
    },
  );

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
    return getTaskArtifactContent(
      app,
      params.taskId,
      params.artifactId,
      auth.sub,
    );
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

  app.post("/:taskId/control", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;

    const params = parseTaskParamsOrReply(request, reply);
    if (!params) return;
    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    const idempotencyKey = getIdempotencyKey(request);
    const body = taskControlBodySchema.parse(request.body);
    await assertRequestBudget(app, {
      scope: "task_control",
      identity: auth.sub,
      max: 30,
      windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
    });
    return requestTaskControl(app, {
      taskId: params.taskId,
      userId: auth.sub,
      kind: body.kind,
      instruction: body.instruction,
      anchorStepId: body.anchorStepId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
      idempotencyKey,
    });
  });

  // Runtime token da kabul edilir (sub = cihaz sahibinin userId'si): QR ile
  // anonim eşleşmiş masaüstünde kullanıcı token'ı yoktur ama makinenin
  // başındaki kullanıcı tepsi menüsünden bekleyen onayı çözebilmelidir —
  // aksi halde mobil onay kartı kaçırıldığında görev sonsuza dek takılır.
  app.post("/:taskId/approval", async (request, reply) => {
    await app.authenticateUserOrRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const params = parseTaskParamsOrReply(request, reply);
    if (!params) {
      return;
    }
    const body = approvalBodySchema.parse(request.body);
    const auth = getUserScopedAuth(request);
    const context = getRequestContext(request);

    return resolveTaskApproval(app, {
      taskId: params.taskId,
      userId: auth.sub,
      approved: body.approved ?? body.action !== "reject",
      action: body.action,
      notes: body.notes ?? body.answer,
      interactionId: body.interactionId ?? body.id,
      interactionRevision: body.interactionRevision ?? body.revision,
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
