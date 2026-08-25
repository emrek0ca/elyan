import type { FastifyPluginAsync } from "fastify";
import { getRequestContext } from "../../lib/http.js";
import { getUserAuth } from "../../lib/request-auth.js";
import { createMcpServerBodySchema, mcpServerParamsSchema, updateMcpServerBodySchema } from "./schemas.js";
import {
  createMcpServer,
  listMcpServers,
  probeUserMcpServer,
  updateMcpServer,
} from "./service.js";

export const mcpRoutes: FastifyPluginAsync = async (app) => {
  app.get("/servers", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      servers: await listMcpServers(app, auth.sub),
    };
  });

  app.post("/servers", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const body = createMcpServerBodySchema.parse(request.body);
    const context = getRequestContext(request);
    return createMcpServer(app, {
      userId: auth.sub,
      integrationConnectionId: body.integrationConnectionId,
      name: body.name,
      transport: body.transport,
      authType: body.authType,
      status: body.status,
      baseUrl: body.baseUrl,
      command: body.command,
      args: body.args,
      config: body.config,
      capabilities: body.capabilities,
      metadata: body.metadata,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });

  /**
   * SUNUCUYU YOKLA ve ARAÇLARINI GÖSTER.
   *
   * Kullanıcı bir MCP sunucusu ekleyebiliyor ama ne sunduğunu göremiyordu:
   * "bağlandı" yazan bir satır, hangi araçların geldiğini ve hangilerinin
   * onay isteyeceğini söylemiyordu. Yoklama araçları keşfeder ve her birini
   * dar bir capability tanımına çevirir.
   *
   * Keşif KULLANIM İZNİ DEĞİLDİR: araçlar burada etkinleştirilmez.
   */
  app.post("/servers/:serverId/probe", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const params = mcpServerParamsSchema.parse(request.params);
    return probeUserMcpServer(app, {
      userId: auth.sub,
      serverId: params.serverId,
    });
  });

  app.patch("/servers/:serverId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const params = mcpServerParamsSchema.parse(request.params);
    const body = updateMcpServerBodySchema.parse(request.body);
    const context = getRequestContext(request);
    return updateMcpServer(app, {
      userId: auth.sub,
      serverId: params.serverId,
      integrationConnectionId: body.integrationConnectionId,
      name: body.name,
      transport: body.transport,
      authType: body.authType,
      status: body.status,
      baseUrl: body.baseUrl,
      command: body.command,
      args: body.args,
      config: body.config,
      capabilities: body.capabilities,
      metadata: body.metadata,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
    });
  });
};
