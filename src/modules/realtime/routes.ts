import { randomUUID } from "node:crypto";
import { and, eq } from "drizzle-orm";
import type { FastifyPluginAsync } from "fastify";
import { ZodError } from "zod";
import type { RawData } from "ws";
import { devices, tasks } from "../../db/schema.js";
import { badRequest, notFound, unauthorized } from "../../lib/errors.js";
import { extractBearerToken, getUserAuth } from "../../lib/request-auth.js";
import type { RuntimeAuthTokenPayload } from "../../types/auth.js";
import { appendTaskArtifacts, updateTaskFromRuntime } from "../tasks/service.js";
import { runtimeSocketMessageSchema } from "../runtime/schemas.js";
import { disconnectRuntime, heartbeatRuntime, listAssignedRuntimeTasks, markRuntimeConnected } from "../runtime/service.js";

export const realtimeRoutes: FastifyPluginAsync = async (app) => {
  app.get("/stream", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const query = (request.query as { taskId?: string; deviceId?: string } | undefined) ?? {};

    if (query.taskId) {
      const ownedTask = await app.db
        .select({ id: tasks.id })
        .from(tasks)
        .where(and(eq(tasks.id, query.taskId), eq(tasks.userId, auth.sub)))
        .limit(1);

      if (!ownedTask[0]) {
        throw notFound("Task stream not found");
      }
    }

    if (query.deviceId) {
      const ownedDevice = await app.db
        .select({ id: devices.id })
        .from(devices)
        .where(and(eq(devices.id, query.deviceId), eq(devices.userId, auth.sub)))
        .limit(1);

      if (!ownedDevice[0]) {
        throw notFound("Device stream not found");
      }
    }

    const channel = query.taskId
      ? `task:${query.taskId}`
      : query.deviceId
        ? `device:${query.deviceId}`
        : `user:${auth.sub}`;

    reply.hijack();
    reply.raw.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    });
    reply.raw.write(`event: ready\ndata: ${JSON.stringify({ channel, timestamp: new Date().toISOString() })}\n\n`);

    const unsubscribe = app.services.eventBus.subscribe(channel, (event) => {
      reply.raw.write(`event: ${event.topic}\ndata: ${JSON.stringify(event)}\n\n`);
    });

    const heartbeat = setInterval(() => {
      reply.raw.write(`event: ping\ndata: ${JSON.stringify({ timestamp: new Date().toISOString() })}\n\n`);
    }, 15_000);

    request.raw.on("close", () => {
      clearInterval(heartbeat);
      unsubscribe();
    });
  });

  app.get("/runtime", { websocket: true }, async (socket, request) => {
    try {
      const token = extractBearerToken(request);
      const payload = (await app.jwt.verify(token)) as RuntimeAuthTokenPayload;

      if (payload.kind !== "runtime") {
        throw unauthorized("Runtime token required");
      }

      const socketSessionId = randomUUID();
      app.services.realtimeHub.attachRuntime({
        socket,
        userId: payload.sub,
        deviceId: payload.deviceId,
      });
      await markRuntimeConnected(app, payload, socketSessionId);

      const queuedTasks = await listAssignedRuntimeTasks(app, payload);

      for (const task of queuedTasks) {
        socket.send(
          JSON.stringify({
            type: "task.dispatch",
            task,
          }),
        );
      }

      socket.on("message", async (raw: RawData) => {
        try {
          const parsed = runtimeSocketMessageSchema.parse(JSON.parse(raw.toString()));

          if (parsed.type === "heartbeat") {
            await heartbeatRuntime(app, payload, parsed);
            return;
          }

          if (parsed.type === "task.update") {
            await updateTaskFromRuntime(app, payload, parsed.taskId, parsed.body);
            return;
          }

          if (parsed.type === "task.artifacts") {
            await appendTaskArtifacts(app, payload, parsed.taskId, parsed.artifacts);
          }
        } catch (error) {
          const message =
            error instanceof ZodError
              ? "Invalid runtime socket message"
              : error instanceof Error
                ? error.message
                : "Unknown runtime socket error";

          socket.send(
            JSON.stringify({
              type: "error",
              message,
            }),
          );
        }
      });

      socket.on("close", async () => {
        app.services.realtimeHub.detachRuntime(payload.deviceId);
        await disconnectRuntime(app, payload);
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Runtime websocket authentication failed";
      socket.close(4401, message);
    }
  });

  app.get("/runtime-token-check", async (request) => {
    const token = extractBearerToken(request);
    const payload = (await app.jwt.verify(token)) as RuntimeAuthTokenPayload;

    if (payload.kind !== "runtime") {
      throw badRequest("Runtime token required");
    }

    return {
      ok: true,
      deviceId: payload.deviceId,
      userId: payload.sub,
    };
  });
};
