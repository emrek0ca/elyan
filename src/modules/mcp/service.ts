import { and, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { integrationConnections, mcpServers } from "../../db/schema.js";
import { badRequest, notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";

function validateMcpInput(input: {
  transport?: "stdio" | "remote" | "oauth_remote" | "streamable_http";
  authType?: "none" | "bearer" | "oauth2" | "api_key";
  baseUrl?: string;
  command?: string;
  integrationConnectionId?: string;
}) {
  if (input.transport === "stdio" && !input.command) {
    throw badRequest("stdio MCP servers require command");
  }

  if (input.transport && input.transport !== "stdio" && !input.baseUrl) {
    throw badRequest(`${input.transport} MCP servers require baseUrl`);
  }

  if (input.authType === "oauth2" && !input.integrationConnectionId) {
    throw badRequest("oauth2 MCP servers require integrationConnectionId");
  }
}

async function assertIntegrationOwnership(
  app: FastifyInstance,
  userId: string,
  integrationConnectionId?: string,
) {
  if (!integrationConnectionId) {
    return;
  }

  const rows = await app.db
    .select({
      id: integrationConnections.id,
    })
    .from(integrationConnections)
    .where(and(eq(integrationConnections.id, integrationConnectionId), eq(integrationConnections.userId, userId)))
    .limit(1);

  if (!rows[0]) {
    throw notFound("Linked integration connection not found");
  }
}

export async function listMcpServers(app: FastifyInstance, userId: string) {
  return app.db
    .select()
    .from(mcpServers)
    .where(eq(mcpServers.userId, userId))
    .orderBy(desc(mcpServers.updatedAt));
}

export async function createMcpServer(
  app: FastifyInstance,
  input: {
    userId: string;
    integrationConnectionId?: string;
    name: string;
    transport: "stdio" | "remote" | "oauth_remote" | "streamable_http";
    authType: "none" | "bearer" | "oauth2" | "api_key";
    status?: "configured" | "connected" | "degraded" | "revoked";
    baseUrl?: string;
    command?: string;
    args: string[];
    config?: Record<string, unknown>;
    capabilities: string[];
    metadata?: Record<string, unknown>;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  validateMcpInput(input);
  await assertIntegrationOwnership(app, input.userId, input.integrationConnectionId);

  const rows = await app.db
    .insert(mcpServers)
    .values({
      userId: input.userId,
      integrationConnectionId: input.integrationConnectionId,
      name: input.name,
      transport: input.transport,
      authType: input.authType,
      status: input.status ?? "configured",
      baseUrl: input.baseUrl,
      command: input.command,
      args: input.args,
      config: input.config ?? {},
      capabilities: input.capabilities,
      metadata: input.metadata ?? {},
    })
    .returning();

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "mcp.server.create",
    resourceType: "mcp_server",
    resourceId: rows[0]?.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      transport: input.transport,
    },
  });

  return rows[0];
}

export async function updateMcpServer(
  app: FastifyInstance,
  input: {
    userId: string;
    serverId: string;
    integrationConnectionId?: string;
    name?: string;
    transport?: "stdio" | "remote" | "oauth_remote" | "streamable_http";
    authType?: "none" | "bearer" | "oauth2" | "api_key";
    status?: "configured" | "connected" | "degraded" | "revoked";
    baseUrl?: string;
    command?: string;
    args?: string[];
    config?: Record<string, unknown>;
    capabilities?: string[];
    metadata?: Record<string, unknown>;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  validateMcpInput(input);
  await assertIntegrationOwnership(app, input.userId, input.integrationConnectionId);

  const rows = await app.db
    .update(mcpServers)
    .set({
      integrationConnectionId: input.integrationConnectionId,
      name: input.name,
      transport: input.transport,
      authType: input.authType,
      status: input.status,
      baseUrl: input.baseUrl,
      command: input.command,
      args: input.args,
      config: input.config,
      capabilities: input.capabilities,
      metadata: input.metadata,
      updatedAt: new Date(),
    })
    .where(and(eq(mcpServers.id, input.serverId), eq(mcpServers.userId, input.userId)))
    .returning();

  const server = rows[0];

  if (!server) {
    throw notFound("MCP server not found");
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "mcp.server.update",
    resourceType: "mcp_server",
    resourceId: server.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      transport: server.transport,
    },
  });

  return server;
}
