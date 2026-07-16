import Fastify from "fastify";
import { and, eq, isNull } from "drizzle-orm";
import compress from "@fastify/compress";
import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import jwt from "@fastify/jwt";
import rateLimit from "@fastify/rate-limit";
import sensible from "@fastify/sensible";
import websocket from "@fastify/websocket";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { VISION_LOG_REDACTION_PATHS } from "../lib/sensitive-log-redaction.js";
import { loadEnv, type AppEnv } from "../config/env.js";
import { realtimeEvents, sessions, users } from "../db/schema.js";
import { dbPlugin } from "../plugins/db.js";
import { errorHandlerPlugin } from "../plugins/error-handler.js";
import { EventBus, RedisRealtimeFanout } from "../modules/realtime/event-bus.js";
import { RealtimeHub } from "../modules/realtime/hub.js";
import { extractBearerToken } from "../lib/request-auth.js";
import { unauthorized } from "../lib/errors.js";
import { createReliabilityServices } from "../lib/reliability/index.js";
import { BlobService } from "../lib/blob/blob-service.js";
import { enforceRouteRequestBudget } from "../lib/reliability/request-budget.js";
import type { AuthTokenPayload } from "../types/auth.js";
import { healthRoutes } from "../modules/health/routes.js";
import { authRoutes, handleAppleCallbackRequest } from "../modules/auth/routes.js";
import { pairingRoutes } from "../modules/pairing/routes.js";
import { runtimeRoutes } from "../modules/runtime/routes.js";
import { taskRoutes } from "../modules/tasks/routes.js";
import { realtimeRoutes } from "../modules/realtime/routes.js";
import { deviceRoutes } from "../modules/devices/routes.js";
import { mobileRoutes } from "../modules/mobile/routes.js";
import { billingRoutes } from "../modules/billing/routes.js";
import { brainRoutes } from "../modules/brain/routes.js";
import { chatRoutes } from "../modules/chat/routes.js";
import { goalRoutes } from "../modules/goals/routes.js";
import { consentRoutes } from "../modules/consents/routes.js";
import { integrationAppRoutes } from "../modules/integrations/routes.js";
import { mcpRoutes } from "../modules/mcp/routes.js";
import { adminRoutes } from "../modules/admin/routes.js";
import { trainPanelRoutes } from "../modules/admin/train-panel.js";
import { ensureTaskDispatchWorker } from "../modules/tasks/dispatch-queue.js";
import { startTaskLeaseSweeper } from "../modules/tasks/lease-sweeper.js";
import { startRealtimeEventRetentionPruner } from "../modules/realtime/log.js";
import { startInProcessMemoryWorker } from "../modules/brain/worker.js";
import { nlpDaemon } from "../lib/nlp-daemon.js";
import { getPerfSnapshot, startPerfTelemetry } from "../lib/perf-telemetry.js";

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function compactRealtimePayload(value: unknown): Record<string, unknown> {
  const record = readRecord(value);
  if (!record) {
    return {};
  }

  const artifactIds = Array.isArray(record.artifacts)
    ? record.artifacts
        .map((item) => readRecord(item)?.id)
        .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        .slice(0, 8)
    : [];

  const compact = {
    ...(typeof record.sessionId === "string" ? { sessionId: record.sessionId } : {}),
    ...(typeof record.messageId === "string" ? { messageId: record.messageId } : {}),
    ...(typeof record.assistantMessageId === "string" ? { assistantMessageId: record.assistantMessageId } : {}),
    ...(typeof record.userMessageId === "string" ? { userMessageId: record.userMessageId } : {}),
    ...(typeof record.presentation === "string" ? { presentation: record.presentation } : {}),
    ...(typeof record.route === "string" ? { route: record.route } : {}),
    ...(typeof record.workload === "string" ? { workload: record.workload } : {}),
    ...(typeof record.status === "string" ? { status: record.status } : {}),
    ...(typeof record.leaseId === "string" ? { leaseId: record.leaseId } : {}),
    ...(typeof record.runtimeConnectionId === "string" ? { runtimeConnectionId: record.runtimeConnectionId } : {}),
    ...(typeof record.dispatched === "boolean" ? { dispatched: record.dispatched } : {}),
    ...(typeof record.reused === "boolean" ? { reused: record.reused } : {}),
    ...(typeof record.artifactCount === "number" ? { artifactCount: record.artifactCount } : {}),
    ...(artifactIds.length > 0 ? { artifactIds } : {}),
  };

  return compact;
}

function resolveCorsOrigins(env: AppEnv): true | string[] {
  if (env.NODE_ENV !== "production") {
    return env.CORS_ORIGIN === "*"
      ? true
      : env.CORS_ORIGIN.split(",")
          .map((value) => value.trim())
          .filter(Boolean);
  }

  if (env.CORS_ORIGIN !== "*") {
    return env.CORS_ORIGIN.split(",")
      .map((value) => value.trim())
      .filter(Boolean);
  }

  return [new URL(env.APP_BASE_URL).origin];
}

async function validateActiveUserSession(app: FastifyInstance, payload: AuthTokenPayload) {
  if (payload.kind !== "user") {
    return payload;
  }

  const rows = await app.db
    .select({
      sessionId: sessions.id,
      revokedAt: sessions.revokedAt,
      expiresAt: sessions.expiresAt,
      deletedAt: users.deletedAt,
    })
    .from(sessions)
    .innerJoin(users, eq(users.id, sessions.userId))
    .where(
      and(
        eq(sessions.id, payload.sessionId),
        eq(sessions.userId, payload.sub),
        isNull(sessions.revokedAt),
      ),
    )
    .limit(1);

  const session = rows[0];
  if (!session || session.deletedAt || session.expiresAt.getTime() <= Date.now()) {
    throw unauthorized("Authentication required");
  }

  return payload;
}

export async function buildApp(envInput?: AppEnv) {
  const env = envInput ?? loadEnv();
  const app = Fastify({
    logger: {
      level: env.LOG_LEVEL,
      redact: {
        paths: [
          "req.headers.authorization",
          "req.headers.cookie",
          "req.headers['x-api-key']",
          "req.body.password",
          "req.body.currentPassword",
          "req.body.nextPassword",
          "req.body.refreshToken",
          "req.body.idToken",
          "req.body.authorizationCode",
          "req.body.dataBase64",
          "req.body.token",
          ...VISION_LOG_REDACTION_PATHS,
          "res.headers['set-cookie']",
        ],
        remove: true,
      },
    },
    bodyLimit: 1_000_000,
    disableRequestLogging: true,
    trustProxy: env.NODE_ENV === "production",
  });

  const reliability = createReliabilityServices(env);

  app.decorate("config", env);

  await app.register(sensible);
  await app.register(compress, {
    global: true,
    encodings: ["gzip", "br"],
  });

  await app.register(helmet, {
    global: true,
  });
  app.addContentTypeParser(
    "application/x-www-form-urlencoded",
    {
      parseAs: "string",
    },
    (_request, body, done) => {
      const text = typeof body === "string" ? body : body.toString("utf-8");
      done(null, Object.fromEntries(new URLSearchParams(text)));
    },
  );
  await app.register(rateLimit, {
    global: true,
    max: 600,
    timeWindow: "1 minute",
    redis: env.RATE_LIMIT_REDIS_ENABLED ? reliability.store.redisClient ?? undefined : undefined,
    skipOnError: !env.RELIABILITY_REDIS_REQUIRED,
  });
  await app.register(cors, {
    origin: resolveCorsOrigins(env),
  });
  await app.register(websocket);
  await app.register(jwt, {
    secret: env.JWT_SECRET,
    sign: {
      algorithm: "HS256",
    },
    verify: {
      algorithms: ["HS256"],
    },
  });
  await app.register(dbPlugin);
  const blobs = new BlobService(app.db, reliability.store, env);
  app.get("/auth/callback/apple", handleAppleCallbackRequest);
  app.post("/auth/callback/apple", handleAppleCallbackRequest);

  const eventBus = new EventBus(
    async (event) => {
      try {
        const compactPayload = compactRealtimePayload(event.payload);
        const rows = await app.db
          .insert(realtimeEvents)
          .values({
            topic: event.topic,
            userId: event.userId ?? null,
            deviceId: event.deviceId ?? null,
            taskId: event.taskId ?? null,
            payload: compactPayload,
            createdAt: event.createdAt ? new Date(event.createdAt) : new Date(),
          })
          .returning({
            id: realtimeEvents.id,
            topic: realtimeEvents.topic,
            userId: realtimeEvents.userId,
            deviceId: realtimeEvents.deviceId,
            taskId: realtimeEvents.taskId,
            payload: realtimeEvents.payload,
            payloadBlobId: realtimeEvents.payloadBlobId,
            createdAt: realtimeEvents.createdAt,
          });
        const row = rows[0];

        if (!row) {
          return {
            ...event,
            createdAt: event.createdAt ?? new Date().toISOString(),
          };
        }

        if (event.payload !== undefined && event.payload !== null) {
          const blob = await blobs.storeJson({
            ownerType: "realtime_event",
            ownerId: String(row.id),
            userId: row.userId ?? undefined,
            slot: "payload",
            scope: "realtime_event_payload",
            value: event.payload,
          });
          if (blob?.blobId) {
            await app.db
              .update(realtimeEvents)
              .set({
                payloadBlobId: blob.blobId,
              })
              .where(eq(realtimeEvents.id, row.id));
          }
        }

        return {
          ...event,
          id: row.id,
          topic: row.topic,
          userId: row.userId ?? undefined,
          deviceId: row.deviceId ?? undefined,
          taskId: row.taskId ?? undefined,
          payload: row.payload,
          createdAt: row.createdAt.toISOString(),
        };
      } catch (error) {
        app.log.error(
          {
            error,
            topic: event.topic,
            userId: event.userId,
            deviceId: event.deviceId,
            taskId: event.taskId,
          },
          "failed to persist realtime event",
        );

        return {
          ...event,
          createdAt: event.createdAt ?? new Date().toISOString(),
        };
      }
    },
    {
      fanout:
        env.REALTIME_REDIS_FANOUT_ENABLED && env.REDIS_URL
          ? new RedisRealtimeFanout({
              redisUrl: env.REDIS_URL,
              channelPrefix: env.REALTIME_REDIS_CHANNEL_PREFIX,
              onError: (error) => app.log.warn({ error }, "realtime redis fanout error"),
            })
          : undefined,
      onFanoutError: (error) => app.log.warn({ error }, "failed to publish realtime fanout event"),
    },
  );
  await eventBus.startFanout().catch((error) => {
    app.log.warn({ error }, "realtime redis fanout unavailable; using local-only fanout");
  });

  const services = {
    eventBus,
    realtimeHub: new RealtimeHub(),
    reliability,
    blobs,
  };

  app.decorate("services", services);

  /* Start C NLP daemon — non-fatal if binary is not yet compiled */
  nlpDaemon.start({
    info: (msg) => app.log.info(msg),
    warn: (msg) => app.log.warn(msg),
  });

  /* Event loop lag + stage p95 telemetrisi. 60sn'de bir snapshot loglanır;
   * p95 lag > 50ms sürekli görülüyorsa bir şey event loop'u blokluyordur —
   * tahminle değil bu metrikle optimize edilir. */
  startPerfTelemetry();
  const perfLogTimer = setInterval(() => {
    const snapshot = getPerfSnapshot({ resetLoop: true });
    if (snapshot.eventLoop && snapshot.eventLoop.p95Ms > 20) {
      app.log.warn({ perf: snapshot }, "event loop lag yüksek");
    } else {
      app.log.info({ perf: snapshot }, "perf snapshot");
    }
  }, 60_000);
  perfLogTimer.unref?.();

  await ensureTaskDispatchWorker(app);
  const stopTaskLeaseSweeper = startTaskLeaseSweeper(app);
  const stopRealtimePruner = startRealtimeEventRetentionPruner(app);
  // Drains memory-extraction jobs in-process (the node training-worker is
  // disabled in prod and the python ml-worker doesn't run TS memory jobs).
  const stopMemoryWorker = startInProcessMemoryWorker(app);
  app.decorate("authenticateUser", async (request: FastifyRequest, reply: FastifyReply) => {
    try {
      const payload = (await request.jwtVerify()) as AuthTokenPayload;

      if (payload.kind !== "user") {
        throw unauthorized("User token required");
      }

      request.auth = await validateActiveUserSession(app, payload);
    } catch {
      throw unauthorized("Authentication required");
    }
  });

  app.decorate("authenticateRuntime", async (request: FastifyRequest, reply: FastifyReply) => {
    try {
      const payload = (await request.jwtVerify()) as AuthTokenPayload;

      if (payload.kind !== "runtime") {
        throw unauthorized("Runtime token required");
      }

      request.auth = payload;
    } catch {
      throw unauthorized("Runtime authentication required");
    }
  });

  app.decorate("authenticateUserOrRuntime", async (request: FastifyRequest, reply: FastifyReply) => {
    // Kullanıcı-kapsamlı ama masaüstü runtime'ının da erişmesi gereken rotalar
    // (chat/brain): runtime token'ın sub'ı cihaz sahibinin userId'sidir.
    try {
      const payload = (await request.jwtVerify()) as AuthTokenPayload;

      if (payload.kind === "user") {
        request.auth = await validateActiveUserSession(app, payload);
      } else if (payload.kind === "runtime") {
        request.auth = payload;
      } else {
        throw unauthorized("User or runtime token required");
      }
    } catch {
      throw unauthorized("Authentication required");
    }
  });

  app.addHook("onRequest", async (request, reply) => {
    reply.header("x-request-id", request.id);
    reply.header("permissions-policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()");
    reply.header("x-permitted-cross-domain-policies", "none");

    const authorization = request.headers.authorization;

    if (!authorization) {
      return;
    }

    try {
      const token = extractBearerToken(request);
      const payload = (await app.jwt.verify(token)) as AuthTokenPayload;
      request.auth = await validateActiveUserSession(app, payload);
    } catch {
      request.auth = undefined;
    }
  });

  app.addHook("preHandler", async (request) => {
    await enforceRouteRequestBudget(app, request);
  });

  app.addHook("onClose", async () => {
    stopTaskLeaseSweeper();
    stopRealtimePruner();
    stopMemoryWorker();
    nlpDaemon.stop();
    await eventBus.close();
    await reliability.store.close();
  });

  app.addHook("onResponse", async (request, reply) => {
    request.log.info(
      {
        requestId: request.id,
        method: request.method,
        url: request.url,
        statusCode: reply.statusCode,
      },
      "request completed",
    );
  });

  await app.register(errorHandlerPlugin);
  await app.register(healthRoutes);
  await app.register(authRoutes, { prefix: "/v1/auth" });
  await app.register(pairingRoutes, { prefix: "/v1/pairing" });
  await app.register(runtimeRoutes, { prefix: "/v1/runtime" });
  await app.register(taskRoutes, { prefix: "/v1/tasks" });
  await app.register(realtimeRoutes, { prefix: "/v1/realtime" });
  await app.register(deviceRoutes, { prefix: "/v1/devices" });
  await app.register(mobileRoutes, { prefix: "/v1/mobile" });
  await app.register(billingRoutes, { prefix: "/v1/billing" });
  await app.register(brainRoutes, { prefix: "/v1/brain" });
  await app.register(chatRoutes, { prefix: "/v1/chat" });
  await app.register(goalRoutes, { prefix: "/v1/goals" });
  await app.register(consentRoutes, { prefix: "/v1/consents" });
  await app.register(integrationAppRoutes, { prefix: "/v1/integrations" });
  await app.register(mcpRoutes, { prefix: "/v1/mcp" });
  await app.register(adminRoutes, { prefix: "/v1/admin" });
  await app.register(trainPanelRoutes);
  return app;
}
