import type { FastifyPluginAsync } from "fastify";
import { getRequestContext } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { aiProviderParamsSchema, aiUsageQuerySchema, routePreviewBodySchema, upsertAiCredentialBodySchema } from "./schemas.js";
import {
  deleteAiProviderCredential,
  listAiProviderCredentials,
  listAiProviderRegistryForUser,
  listAiUsage,
  previewAiRoute,
  upsertAiProviderCredential,
} from "./service.js";

export const aiRoutes: FastifyPluginAsync = async (app) => {
  app.get("/providers", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      providers: await listAiProviderRegistryForUser(app, auth.sub),
      note: "AI assists intent understanding, planning, and routing. Desktop runtime performs real execution.",
    };
  });

  app.get("/credentials", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      credentials: await listAiProviderCredentials(app, auth.sub),
    };
  });

  app.put("/credentials/:provider", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = aiProviderParamsSchema.parse(request.params);
    const body = upsertAiCredentialBodySchema.parse(request.body);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return upsertAiProviderCredential(app, {
      userId: auth.sub,
      provider: params.provider,
      label: body.label,
      apiKey: body.apiKey,
      baseUrl: body.baseUrl,
      defaultModel: body.defaultModel,
      metadata: body.metadata,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.delete("/credentials/:provider", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const params = aiProviderParamsSchema.parse(request.params);
    const auth = getUserAuth(request);
    const context = getRequestContext(request);

    return deleteAiProviderCredential(app, {
      userId: auth.sub,
      provider: params.provider,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  app.post("/route-preview", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const body = routePreviewBodySchema.parse(request.body);
    return previewAiRoute(body);
  });

  app.get("/usage", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const query = aiUsageQuerySchema.parse(request.query);
    const auth = getUserAuth(request);

    return {
      usage: await listAiUsage(app, auth.sub, query.limit),
    };
  });
};
