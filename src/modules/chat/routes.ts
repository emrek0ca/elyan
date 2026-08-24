import type { FastifyInstance, FastifyPluginAsync } from "fastify";
import { getIdempotencyKey } from "../../lib/idempotency.js";
import { getRequestContext, sendConditionalJson } from "../../lib/http.js";
import { recordNumericMetricSample } from "../../lib/reliability/sample-metrics.js";
import { getUserAuth, getUserScopedAuth } from "../../lib/request-auth.js";
import {
  clearChatSessionsQuerySchema,
  chatSessionParamsSchema,
  createChatMessageBodySchema,
  createChatSessionBodySchema,
  listChatSessionMessagesQuerySchema,
  listChatSessionsQuerySchema,
  updateChatSessionBodySchema,
} from "./schemas.js";
import {
  createChatMessage,
  createChatSession,
  clearChatSessions,
  deleteChatSession,
  getChatSessionDetail,
  listChatSessionMessages,
  listChatSessions,
  updateChatSession,
} from "./service.js";

const CHAT_SESSIONS_LIST_LATENCY_KEY = "metrics:chat:sessions:list:latency_ms";
const CHAT_SESSIONS_LIST_BYTES_KEY = "metrics:chat:sessions:list:payload_bytes";
const CHAT_SESSION_MESSAGES_LATENCY_KEY = "metrics:chat:sessions:messages:latency_ms";
const CHAT_SESSION_MESSAGES_BYTES_KEY = "metrics:chat:sessions:messages:payload_bytes";
const CHAT_MESSAGE_ACCEPT_LATENCY_KEY = "metrics:chat:message:accept:latency_ms";

function estimateJsonPayloadBytes(payload: unknown) {
  return Buffer.byteLength(JSON.stringify(payload), "utf8");
}

async function recordChatRouteMetric(
  app: FastifyInstance,
  key: string,
  value: number,
) {
  await recordNumericMetricSample(app.services?.reliability?.store, key, value);
}

export const chatRoutes: FastifyPluginAsync = async (app) => {
  app.get("/sessions", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const query = listChatSessionsQuerySchema.parse(request.query ?? {});
    const auth = getUserAuth(request);
    const startedAt = Date.now();

    const payload = {
      ...await listChatSessions(app, {
        userId: auth.sub,
        status: query.status,
        limit: query.limit,
        cursor: query.cursor,
      }),
    };
    await Promise.all([
      recordChatRouteMetric(
        app,
        CHAT_SESSIONS_LIST_LATENCY_KEY,
        Date.now() - startedAt,
      ),
      recordChatRouteMetric(
        app,
        CHAT_SESSIONS_LIST_BYTES_KEY,
        estimateJsonPayloadBytes(payload),
      ),
    ]);
    return sendConditionalJson(request, reply, payload);
  });

  app.post("/sessions", async (request, reply) => {
    await app.authenticateUserOrRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createChatSessionBodySchema.parse(request.body);
    const auth = getUserScopedAuth(request);
    const context = getRequestContext(request);

    return createChatSession(app, {
      userId: auth.sub,
      targetDeviceId: body.targetDeviceId,
      source: body.source,
      title: body.title,
      metadata: body.metadata,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.get("/sessions/:sessionId", async (request, reply) => {
    await app.authenticateUserOrRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const params = chatSessionParamsSchema.parse(request.params);
    const auth = getUserScopedAuth(request);
    const startedAt = Date.now();
    const payload = await getChatSessionDetail(app, auth.sub, params.sessionId);
    await Promise.all([
      recordChatRouteMetric(
        app,
        CHAT_SESSION_MESSAGES_LATENCY_KEY,
        Date.now() - startedAt,
      ),
      recordChatRouteMetric(
        app,
        CHAT_SESSION_MESSAGES_BYTES_KEY,
        estimateJsonPayloadBytes(payload),
      ),
    ]);
    return sendConditionalJson(request, reply, payload);
  });

  app.get("/sessions/:sessionId/messages", async (request, reply) => {
    await app.authenticateUserOrRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const params = chatSessionParamsSchema.parse(request.params);
    const query = listChatSessionMessagesQuerySchema.parse(request.query ?? {});
    const auth = getUserScopedAuth(request);
    const startedAt = Date.now();

    const payload = await listChatSessionMessages(app, {
      userId: auth.sub,
      sessionId: params.sessionId,
      cursor: query.cursor,
      limit: query.limit,
    });
    await Promise.all([
      recordChatRouteMetric(
        app,
        CHAT_SESSION_MESSAGES_LATENCY_KEY,
        Date.now() - startedAt,
      ),
      recordChatRouteMetric(
        app,
        CHAT_SESSION_MESSAGES_BYTES_KEY,
        estimateJsonPayloadBytes(payload),
      ),
    ]);
    return sendConditionalJson(request, reply, payload);
  });

  app.patch("/sessions/:sessionId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = chatSessionParamsSchema.parse(request.params);
    const body = updateChatSessionBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return updateChatSession(app, {
      userId: auth.sub,
      sessionId: params.sessionId,
      status: body.status,
      title: body.title,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.delete("/sessions/:sessionId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = chatSessionParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return deleteChatSession(app, {
      userId: auth.sub,
      sessionId: params.sessionId,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.delete("/sessions", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const query = clearChatSessionsQuerySchema.parse(request.query ?? {});
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return clearChatSessions(app, {
      userId: auth.sub,
      before: query.before,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/messages", async (request, reply) => {
    // Masaüstü runtime'ı görev yürütürken beyni runtime token'ıyla çağırır.
    await app.authenticateUserOrRuntime(request, reply);

    if (reply.sent) {
      return;
    }

    const body = createChatMessageBodySchema.parse(request.body);
    const auth = getUserScopedAuth(request);
    const context = getRequestContext(request);
    const idempotencyKey = getIdempotencyKey(request);
    const startedAt = Date.now();

    const payload = await createChatMessage(app, {
      userId: auth.sub,
      sessionId: body.sessionId,
      targetDeviceId: body.targetDeviceId,
      source: body.source,
      title: body.title,
      content: body.content,
      requestedCapabilities: body.requestedCapabilities,
      desktopAccess: body.desktopAccess,
      metadata: body.metadata,
      ephemeralVision: body.ephemeralVision,
      requestId: context.requestId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      idempotencyKey,
    });
    // Numeric-only telemetry stays detached from the response path and never
    // records the user's prompt or generated content.
    void recordChatRouteMetric(
      app,
      CHAT_MESSAGE_ACCEPT_LATENCY_KEY,
      Date.now() - startedAt,
    );
    // Chat acceptance is asynchronous by contract: the task/message rows are
    // durable and the realtime stream owns generation progress. Returning 202
    // makes that boundary explicit without changing the response envelope.
    return reply.code(202).send(payload);
  });
};
