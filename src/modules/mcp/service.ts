import { and, desc, eq, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { integrationConnections, mcpServers } from "../../db/schema.js";
import { badRequest, notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import { probeMcpServer } from "../integrations/mcp-probe.js";
import { describeMcpTools } from "../integrations/mcp-capability.js";

const MCP_SHELL_CONTROL_PATTERN = /[\0\r\n;&|`$<>]/u;
const MCP_INLINE_SECRET_ARG_PATTERN =
  /(?:^|[-_])(?:api[-_]?key|access[-_]?token|auth[-_]?token|bearer|password|passwd|secret|client[-_]?secret)(?:=|:|$)/iu;

function validateMcpInput(input: {
  transport?: "stdio" | "remote" | "oauth_remote" | "streamable_http";
  authType?: "none" | "bearer" | "oauth2" | "api_key";
  baseUrl?: string;
  command?: string;
  args?: string[];
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

  if (input.command && MCP_SHELL_CONTROL_PATTERN.test(input.command)) {
    throw badRequest("MCP command cannot contain shell control characters");
  }

  for (const arg of input.args ?? []) {
    if (MCP_SHELL_CONTROL_PATTERN.test(arg)) {
      throw badRequest("MCP args cannot contain shell control characters");
    }
    if (MCP_INLINE_SECRET_ARG_PATTERN.test(arg)) {
      throw badRequest("MCP args cannot include inline secrets");
    }
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

/**
 * KULLANICININ KENDİ MCP SUNUCUSUNU YOKLAR ve ARAÇLARINI TİPLER.
 *
 * NEDEN VAR
 * ---------
 * Kullanıcı bir MCP sunucusu ekleyebiliyordu ama sunucunun NE SUNDUĞUNU
 * hiçbir yerde göremiyordu: mobilde yalnız ad, taşıma türü ve durum vardı.
 * "Bağlandı" yazan bir satır, hangi araçların geldiğini ve hangilerinin onay
 * isteyeceğini söylemiyordu — kullanıcı neyi yetkilendirdiğini bilmiyordu.
 *
 * Yoklama araçları keşfeder, `describeMcpTools` her birini dar bir capability
 * tanımına çevirir (fail-closed: `readOnlyHint` yoksa salt-okuma sayılmaz) ve
 * sonuç sunucu kaydına yazılır. Böylece mobil "5 araç, 3'ü onay ister"
 * diyebilir ve derleyici bu araçları dar adlarıyla planlayabilir.
 *
 * NE YAPMAZ: aracı ETKİNLEŞTİRMEZ. Keşif, kullanım izni değildir.
 */
export async function probeUserMcpServer(
  app: FastifyInstance,
  input: { userId: string; serverId: string; accessToken?: string },
) {
  const rows = await app.db
    .select()
    .from(mcpServers)
    .where(and(eq(mcpServers.userId, input.userId), eq(mcpServers.id, input.serverId)))
    .limit(1);
  const server = rows[0];
  if (!server) {
    throw notFound("MCP server not found");
  }
  const baseUrl = String(server.baseUrl ?? "").trim();
  if (!baseUrl) {
    throw badRequest("Only remote MCP servers can be probed");
  }

  const result = await probeMcpServer({
    url: baseUrl,
    accessToken: input.accessToken ?? "",
    useSdk: app.config?.ELYAN_MCP_SDK_ENABLED === true,
  });

  const descriptors =
    result.status === "ok"
      ? describeMcpTools({
          serverName: result.serverName ?? server.name,
          tools: result.tools ?? [],
        })
      : [];

  // Durum yoklamanın GERÇEĞİNİ yansıtır; başarısız yoklama "bağlı" bırakmaz.
  const nextStatus =
    result.status === "ok"
      ? "connected"
      : server.status === "revoked"
        ? "revoked"
        : "degraded";

  await app.db
    .update(mcpServers)
    .set({
      status: nextStatus,
      capabilities: descriptors.map((descriptor) => descriptor.capabilityId),
      metadata: sql`coalesce(${mcpServers.metadata}, '{}'::jsonb) || ${JSON.stringify({
        probe: {
          contract: "elyan.mcp_probe.v1",
          status: result.status,
          errorCode: result.errorCode ?? null,
          serverName: result.serverName ?? null,
          protocolVersion: result.protocolVersion ?? null,
          toolCount: descriptors.length,
          latencyMs: result.latencyMs ?? null,
          probedAt: result.probedAt,
          // Araç TANIMI saklanır: adı, etkisi, risk sınıfı ve şema özeti.
          // Serbest metin açıklaması karar mantığına girmez, yalnız gösterim.
          tools: descriptors.slice(0, 64).map((descriptor) => ({
            capabilityId: descriptor.capabilityId,
            toolName: descriptor.toolName,
            sideEffectClass: descriptor.sideEffectClass,
            riskClass: descriptor.riskClass,
            requiresApproval: descriptor.requiresApproval,
            inputContractHash: descriptor.inputContractHash,
            argSlots: descriptor.argSlots,
            description: descriptor.displayDescription,
          })),
        },
      })}::jsonb`,
      updatedAt: new Date(),
    })
    .where(and(eq(mcpServers.userId, input.userId), eq(mcpServers.id, input.serverId)));

  return {
    serverId: input.serverId,
    status: result.status,
    errorCode: result.errorCode ?? null,
    serverName: result.serverName ?? null,
    latencyMs: result.latencyMs ?? null,
    toolCount: descriptors.length,
    approvalToolCount: descriptors.filter((item) => item.requiresApproval).length,
    tools: descriptors,
  };
}
