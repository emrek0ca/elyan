import type { FastifyInstance, FastifyPluginAsync } from "fastify";
import { getRequestContext } from "../../lib/http.js";
import { getRuntimeAuth, getUserAuth } from "../../lib/request-auth.js";
import {
  connectionParamsSchema,
  integrationAppParamsSchema,
  listConnectionsQuerySchema,
  oauthCallbackQuerySchema,
  oauthProviderParamsSchema,
  sendGmailBodySchema,
  startAppOauthBodySchema,
  startOauthBodySchema,
} from "./schemas.js";
import {
  disconnectIntegrationApp,
  disconnectIntegration,
  handleOauthCallback,
  listIntegrationApps,
  listIntegrationProviders,
  listRuntimeMcpConnections,
  listUserIntegrationConnections,
  sendGmailMessage,
  startOauthAppConnection,
  startOauthConnection,
} from "./service.js";
import { getRuntimeConnectionByAuth } from "../runtime/service.js";

function registerGmailSend(app: FastifyInstance) {
  app.post("/gmail/send", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const body = sendGmailBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    return sendGmailMessage(app, {
      userId: auth.sub,
      connectionId: body.connectionId,
      to: body.to,
      subject: body.subject,
      body: body.body,
      cc: body.cc,
      bcc: body.bcc,
      replyTo: body.replyTo,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });
}

function registerCuratedAppRoutes(app: FastifyInstance) {
  app.get("/apps", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const auth = getUserAuth(request);
    return { apps: await listIntegrationApps(app, auth.sub) };
  });

  app.post("/apps/:appId/oauth/start", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const params = integrationAppParamsSchema.parse(request.params);
    const body = startAppOauthBodySchema.parse(request.body ?? {});
    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    return startOauthAppConnection(app, {
      userId: auth.sub,
      appId: params.appId,
      redirectUri: body.redirectUri,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.delete("/apps/:appId", async (request, reply) => {
    await app.authenticateUser(request, reply);
    if (reply.sent) return;
    const params = integrationAppParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    return disconnectIntegrationApp(app, {
      userId: auth.sub,
      appId: params.appId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.get("/runtime/mcp", async (request, reply) => {
    await app.authenticateRuntime(request, reply);
    if (reply.sent) return;
    const auth = getRuntimeAuth(request);
    await getRuntimeConnectionByAuth(app, auth);
    reply.header("Cache-Control", "no-store");
    reply.header("Pragma", "no-cache");
    return listRuntimeMcpConnections(app, auth.sub);
  });
}

function registerOauthCallback(app: FastifyInstance) {
  app.get("/oauth/:provider/callback", async (request, reply) => {
    const params = oauthProviderParamsSchema.parse(request.params);
    const query = oauthCallbackQuerySchema.parse(request.query);
    const result = await handleOauthCallback(app, {
      provider: params.provider,
      state: query.state,
      code: query.code,
      error: query.error,
      errorDescription: query.error_description,
    });

    if (result.redirectUri) {
      return reply.redirect(
        redirectWithQuery(result.redirectUri, {
          status: result.status,
          provider: result.provider,
          appId: result.appId ?? "",
          connectionId: result.connectionId ?? "",
          error: result.error ?? "",
        }),
      );
    }

    return result;
  });
}

/** Shipping surface: curated cards, app-scoped OAuth, gmail send and runtime leases. */
export const integrationAppRoutes: FastifyPluginAsync = async (app) => {
  registerCuratedAppRoutes(app);
  registerGmailSend(app);
  registerOauthCallback(app);
};

/** Legacy/provider-admin surface kept for compatibility but not registered by V1. */
export const integrationRoutes: FastifyPluginAsync = async (app) => {
  registerCuratedAppRoutes(app);
  registerOauthCallback(app);

  app.get("/providers", async () => ({
    providers: await listIntegrationProviders(app),
  }));

  app.get("/connections", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const query = listConnectionsQuerySchema.parse(request.query);
    return {
      connections: await listUserIntegrationConnections(app, auth.sub, query.provider),
    };
  });

  app.post("/oauth/:provider/start", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = oauthProviderParamsSchema.parse(request.params);
    const body = startOauthBodySchema.parse(request.body ?? {});
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return startOauthConnection(app, {
      userId: auth.sub,
      provider: params.provider,
      redirectUri: body.redirectUri,
      scopes: body.scopes,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.delete("/connections/:connectionId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = connectionParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return disconnectIntegration(app, {
      userId: auth.sub,
      connectionId: params.connectionId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/gmail/send", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = sendGmailBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return sendGmailMessage(app, {
      userId: auth.sub,
      connectionId: body.connectionId,
      to: body.to,
      subject: body.subject,
      body: body.body,
      cc: body.cc,
      bcc: body.bcc,
      replyTo: body.replyTo,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });
};

function redirectWithQuery(baseUrl: string, params: Record<string, string>) {
  const url = new URL(baseUrl);

  for (const [key, value] of Object.entries(params)) {
    if (value) {
      url.searchParams.set(key, value);
    }
  }

  return url.toString();
}
