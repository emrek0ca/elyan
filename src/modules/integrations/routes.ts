import type { FastifyPluginAsync } from "fastify";
import { getRequestContext } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { connectionParamsSchema, listConnectionsQuerySchema, oauthCallbackQuerySchema, oauthProviderParamsSchema, startOauthBodySchema } from "./schemas.js";
import {
  disconnectIntegration,
  handleOauthCallback,
  listIntegrationProviders,
  listUserIntegrationConnections,
  startOauthConnection,
} from "./service.js";

export const integrationRoutes: FastifyPluginAsync = async (app) => {
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
          connectionId: result.connectionId ?? "",
          error: result.error ?? "",
        }),
      );
    }

    return result;
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
