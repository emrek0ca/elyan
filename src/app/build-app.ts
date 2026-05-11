import Fastify from "fastify";
import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import jwt from "@fastify/jwt";
import rateLimit from "@fastify/rate-limit";
import sensible from "@fastify/sensible";
import websocket from "@fastify/websocket";
import type { FastifyReply, FastifyRequest } from "fastify";
import { loadEnv, type AppEnv } from "../config/env.js";
import { dbPlugin } from "../plugins/db.js";
import { errorHandlerPlugin } from "../plugins/error-handler.js";
import { EventBus } from "../modules/realtime/event-bus.js";
import { RealtimeHub } from "../modules/realtime/hub.js";
import { extractBearerToken } from "../lib/request-auth.js";
import { unauthorized } from "../lib/errors.js";
import type { AuthTokenPayload } from "../types/auth.js";
import { healthRoutes } from "../modules/health/routes.js";
import { authRoutes } from "../modules/auth/routes.js";
import { pairingRoutes } from "../modules/pairing/routes.js";
import { runtimeRoutes } from "../modules/runtime/routes.js";
import { taskRoutes } from "../modules/tasks/routes.js";
import { realtimeRoutes } from "../modules/realtime/routes.js";
import { aiRoutes } from "../modules/ai/routes.js";

export async function buildApp(envInput?: AppEnv) {
  const env = envInput ?? loadEnv();
  const app = Fastify({
    logger: {
      level: env.LOG_LEVEL,
    },
  });

  const services = {
    eventBus: new EventBus(),
    realtimeHub: new RealtimeHub(),
  };

  app.decorate("config", env);
  app.decorate("services", services);

  await app.register(sensible);
  await app.register(helmet, {
    global: true,
  });
  await app.register(rateLimit, {
    global: true,
    max: 120,
    timeWindow: "1 minute",
  });
  await app.register(cors, {
    origin:
      env.CORS_ORIGIN === "*"
        ? true
        : env.CORS_ORIGIN.split(",")
            .map((value) => value.trim())
            .filter(Boolean),
  });
  await app.register(websocket);
  await app.register(jwt, {
    secret: env.JWT_SECRET,
  });
  await app.register(dbPlugin);

  app.decorate("authenticateUser", async (request: FastifyRequest, reply: FastifyReply) => {
    try {
      const payload = (await request.jwtVerify()) as AuthTokenPayload;

      if (payload.kind !== "user") {
        throw unauthorized("User token required");
      }

      request.auth = payload;
    } catch (error) {
      throw unauthorized(error instanceof Error ? error.message : "Unauthorized");
    }
  });

  app.decorate("authenticateRuntime", async (request: FastifyRequest, reply: FastifyReply) => {
    try {
      const payload = (await request.jwtVerify()) as AuthTokenPayload;

      if (payload.kind !== "runtime") {
        throw unauthorized("Runtime token required");
      }

      request.auth = payload;
    } catch (error) {
      throw unauthorized(error instanceof Error ? error.message : "Unauthorized");
    }
  });

  app.addHook("onRequest", async (request) => {
    const authorization = request.headers.authorization;

    if (!authorization) {
      return;
    }

    try {
      const token = extractBearerToken(request);
      request.auth = (await app.jwt.verify(token)) as AuthTokenPayload;
    } catch {
      request.auth = undefined;
    }
  });

  await app.register(healthRoutes);
  await app.register(authRoutes, { prefix: "/v1/auth" });
  await app.register(pairingRoutes, { prefix: "/v1/pairing" });
  await app.register(runtimeRoutes, { prefix: "/v1/runtime" });
  await app.register(taskRoutes, { prefix: "/v1/tasks" });
  await app.register(realtimeRoutes, { prefix: "/v1/realtime" });
  await app.register(aiRoutes, { prefix: "/v1/ai" });
  await app.register(errorHandlerPlugin);

  return app;
}
