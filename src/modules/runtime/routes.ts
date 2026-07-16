import type { FastifyPluginAsync } from "fastify";
import { ZodError } from "zod";
import { getRuntimeAuth } from "../../lib/request-auth.js";
import { serializeZodError } from "../../lib/http.js";
import { appendTaskArtifacts, appendTaskBinaryArtifact, getTaskMediaInputForRuntime, updateTaskFromRuntime } from "../tasks/service.js";
import { registerRuntimeBodySchema, runtimeHeartbeatBodySchema, runtimeTaskArtifactsBodySchema, runtimeTaskParamsSchema, runtimeTaskUpdateBodySchema } from "./schemas.js";
import { disconnectRuntime, getRuntimeSessionSnapshot, heartbeatRuntime, listAssignedRuntimeTasks, registerRuntime } from "./service.js";

export const runtimeRoutes: FastifyPluginAsync = async (app) => {
  app.addContentTypeParser(
    ["image/png", "image/jpeg", "image/webp"],
    { parseAs: "buffer", bodyLimit: 25 * 1024 * 1024 },
    (_request, body, done) => done(null, body),
  );
  app.post("/register", async (request, reply) => {
    let body;
    try {
      body = registerRuntimeBodySchema.parse(request.body);
    } catch (error) {
      if (error instanceof ZodError) {
        reply.status(400).send({
          error: "validation_error",
          message: "Invalid request payload",
          details: serializeZodError(error),
          requestId: request.id,
        });
        return;
      }
      throw error;
    }
    return registerRuntime(app, body);
  });

  app.post("/heartbeat", async (request, reply) => {
    await app.authenticateRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const body = runtimeHeartbeatBodySchema.parse(request.body);
    const auth = getRuntimeAuth(request);
    return heartbeatRuntime(app, auth, body);
  });

  app.post("/disconnect", async (request, reply) => {
    await app.authenticateRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getRuntimeAuth(request);
    await disconnectRuntime(app, auth);

    return {
      ok: true,
    };
  });

  app.get("/session", async (request, reply) => {
    await app.authenticateRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getRuntimeAuth(request);
    return getRuntimeSessionSnapshot(app, auth);
  });

  app.get("/tasks/assigned", async (request, reply) => {
    await app.authenticateRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getRuntimeAuth(request);

    const tasks = await listAssignedRuntimeTasks(app, auth);
    return {
      // Authenticated runtime channel binding: desktop WorkOrder v2 seals this
      // backend-owned identity into its device-local execution ledger.
      tasks: tasks.map((task) => ({ ...task, userId: auth.sub })),
    };
  });

  app.post("/tasks/:taskId/status", async (request, reply) => {
    await app.authenticateRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const params = runtimeTaskParamsSchema.parse(request.params);
    const body = runtimeTaskUpdateBodySchema.parse(request.body);
    const auth = getRuntimeAuth(request);

    return updateTaskFromRuntime(app, auth, params.taskId, body);
  });

  app.post("/tasks/:taskId/artifacts", async (request, reply) => {
    await app.authenticateRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const params = runtimeTaskParamsSchema.parse(request.params);
    const body = runtimeTaskArtifactsBodySchema.parse(request.body);
    const auth = getRuntimeAuth(request);

    return appendTaskArtifacts(app, auth, params.taskId, body.artifacts);
  });

  app.post("/tasks/:taskId/artifacts/binary", async (request, reply) => {
    await app.authenticateRuntime(request, reply);
    if (reply.sent) return;
    if (!Buffer.isBuffer(request.body)) {
      return reply.status(400).send({ error: "validation_error", message: "Binary artifact body required" });
    }
    const params = runtimeTaskParamsSchema.parse(request.params);
    const auth = getRuntimeAuth(request);
    return appendTaskBinaryArtifact(app, auth, params.taskId, {
      body: request.body,
      contentType: String(request.headers["content-type"] ?? ""),
      name: String(request.headers["x-elyan-file-name"] ?? "elyan-image.png"),
      sha256: String(request.headers["x-content-sha256"] ?? ""),
    });
  });

  app.get("/tasks/:taskId/inputs/:inputRef/content", async (request, reply) => {
    await app.authenticateRuntime(request, reply);
    if (reply.sent) return;
    const params = request.params as { taskId?: string; inputRef?: string };
    const task = runtimeTaskParamsSchema.parse({ taskId: params.taskId });
    const auth = getRuntimeAuth(request);
    const resolved = await getTaskMediaInputForRuntime(app, auth, task.taskId, String(params.inputRef ?? ""));
    reply
      .header("Cache-Control", "no-store")
      .header("Content-Disposition", `attachment; filename="${resolved.descriptor.name.replace(/"/g, "")}"`)
      .type(resolved.descriptor.contentType)
      .send(Buffer.from(resolved.body));
  });
};
