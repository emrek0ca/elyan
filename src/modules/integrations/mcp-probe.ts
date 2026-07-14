import { and, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import type { ConnectionProvider } from "../../contracts/domain.js";
import { integrationConnections } from "../../db/schema.js";
import { getIntegrationMcpApp, integrationMcpAppCatalog } from "./provider-registry.js";

/**
 * MCP el sıkışma probu.
 *
 * "connected" bugüne kadar yalnız OAuth başarısını gösteriyordu — uzak MCP
 * sunucusunun gerçekten konuştuğunu değil. Bu modül streamable HTTP MCP
 * sunucusuna initialize + tools/list el sıkışması yapar ve sonucu bağlantının
 * KENDİ metadata'sına yazar. Prob her zaman ilgili bağlantının kendi access
 * token'ıyla koşar; sonuç yalnız o connection satırına yazılır — kullanıcılar
 * arası paylaşılan hiçbir durum yoktur.
 */

export const MCP_PROBE_PROTOCOL_VERSION = "2025-06-18";
const DEFAULT_PROBE_TIMEOUT_MS = 10_000;
const MAX_RECORDED_TOOL_NAMES = 24;

export type McpProbeErrorCode =
  | "MCP_AUTH_REQUIRED"
  | "MCP_UNREACHABLE"
  | "MCP_PROTOCOL_ERROR"
  | "MCP_HTTP_ERROR";

export type McpProbeResult = {
  status: "ok" | "failed";
  errorCode: McpProbeErrorCode | null;
  httpStatus: number | null;
  protocolVersion: string | null;
  serverName: string | null;
  toolCount: number | null;
  toolNames: string[];
  latencyMs: number;
  probedAt: string;
};

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

/**
 * Streamable HTTP cevabı düz JSON ya da SSE olabilir. SSE'de sunucu stream'i
 * açık tutabilir: gövdeyi komple beklemek yerine ilk tam `data:` event'ini
 * okuyup bağlantıyı iptal ediyoruz.
 */
async function readJsonRpcBody(response: Response): Promise<JsonRecord> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("text/event-stream")) {
    return asRecord(await response.json());
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("empty_sse_body");
  }
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (value) {
        buffer += decoder.decode(value, { stream: true });
        // Event sınırı: boş satır. İlk JSON-RPC cevabını taşıyan event yeter.
        const events = buffer.split(/\n\n/u);
        for (const event of events.slice(0, -1)) {
          const data = event
            .split(/\n/u)
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim())
            .join("\n");
          if (!data) continue;
          try {
            const parsed = asRecord(JSON.parse(data));
            if ("result" in parsed || "error" in parsed) {
              return parsed;
            }
          } catch {
            // kısmi/ilgisiz event — sıradakine bak
          }
        }
        buffer = events[events.length - 1] ?? "";
      }
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
  throw new Error("sse_without_jsonrpc_response");
}

async function postJsonRpc(input: {
  url: string;
  accessToken: string;
  sessionId?: string | null;
  body: JsonRecord;
  timeoutMs: number;
}): Promise<{ httpStatus: number; sessionId: string | null; payload: JsonRecord | null }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), input.timeoutMs);
  try {
    const response = await fetch(input.url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
        Authorization: `Bearer ${input.accessToken}`,
        "MCP-Protocol-Version": MCP_PROBE_PROTOCOL_VERSION,
        ...(input.sessionId ? { "Mcp-Session-Id": input.sessionId } : {}),
      },
      body: JSON.stringify(input.body),
      signal: controller.signal,
    });
    const sessionId = response.headers.get("mcp-session-id");
    if (!response.ok) {
      await response.body?.cancel().catch(() => {});
      return { httpStatus: response.status, sessionId, payload: null };
    }
    // 202 Accepted: notification kabulü — gövde beklenmez.
    if (response.status === 202) {
      await response.body?.cancel().catch(() => {});
      return { httpStatus: response.status, sessionId, payload: {} };
    }
    const payload = await readJsonRpcBody(response);
    return { httpStatus: response.status, sessionId, payload };
  } finally {
    clearTimeout(timer);
  }
}

export async function probeMcpServer(input: {
  url: string;
  accessToken: string;
  timeoutMs?: number;
}): Promise<McpProbeResult> {
  const timeoutMs = input.timeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS;
  const startedAt = Date.now();
  const probedAt = new Date().toISOString();
  const fail = (
    errorCode: McpProbeErrorCode,
    httpStatus: number | null = null,
  ): McpProbeResult => ({
    status: "failed",
    errorCode,
    httpStatus,
    protocolVersion: null,
    serverName: null,
    toolCount: null,
    toolNames: [],
    latencyMs: Date.now() - startedAt,
    probedAt,
  });

  let initialize: Awaited<ReturnType<typeof postJsonRpc>>;
  try {
    initialize = await postJsonRpc({
      url: input.url,
      accessToken: input.accessToken,
      timeoutMs,
      body: {
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: MCP_PROBE_PROTOCOL_VERSION,
          capabilities: {},
          clientInfo: { name: "elyan-mcp-probe", version: "1.0" },
        },
      },
    });
  } catch {
    return fail("MCP_UNREACHABLE");
  }
  if (initialize.httpStatus === 401 || initialize.httpStatus === 403) {
    return fail("MCP_AUTH_REQUIRED", initialize.httpStatus);
  }
  if (!initialize.payload || initialize.payload.error) {
    return fail(
      initialize.payload?.error ? "MCP_PROTOCOL_ERROR" : "MCP_HTTP_ERROR",
      initialize.httpStatus,
    );
  }
  const initResult = asRecord(initialize.payload.result);
  const serverInfo = asRecord(initResult.serverInfo);
  const sessionId = initialize.sessionId;

  // Spec: initialize sonrası initialized notification. Reddeden sunucu için
  // prob başarısız sayılmaz — bazı sunucular bunu opsiyonel tutuyor.
  try {
    await postJsonRpc({
      url: input.url,
      accessToken: input.accessToken,
      sessionId,
      timeoutMs,
      body: { jsonrpc: "2.0", method: "notifications/initialized" },
    });
  } catch {
    // yut — tools/list asıl doğrulama
  }

  let toolsList: Awaited<ReturnType<typeof postJsonRpc>>;
  try {
    toolsList = await postJsonRpc({
      url: input.url,
      accessToken: input.accessToken,
      sessionId,
      timeoutMs,
      body: { jsonrpc: "2.0", id: 2, method: "tools/list", params: {} },
    });
  } catch {
    return fail("MCP_UNREACHABLE");
  }
  if (toolsList.httpStatus === 401 || toolsList.httpStatus === 403) {
    return fail("MCP_AUTH_REQUIRED", toolsList.httpStatus);
  }
  if (!toolsList.payload || toolsList.payload.error) {
    return fail(
      toolsList.payload?.error ? "MCP_PROTOCOL_ERROR" : "MCP_HTTP_ERROR",
      toolsList.httpStatus,
    );
  }
  const tools = asRecord(toolsList.payload.result).tools;
  if (!Array.isArray(tools)) {
    return fail("MCP_PROTOCOL_ERROR", toolsList.httpStatus);
  }

  return {
    status: "ok",
    errorCode: null,
    httpStatus: toolsList.httpStatus,
    protocolVersion:
      typeof initResult.protocolVersion === "string"
        ? initResult.protocolVersion
        : null,
    serverName: typeof serverInfo.name === "string" ? serverInfo.name : null,
    toolCount: tools.length,
    toolNames: tools
      .map((tool) => String(asRecord(tool).name ?? "").trim())
      .filter(Boolean)
      .slice(0, MAX_RECORDED_TOOL_NAMES),
    latencyMs: Date.now() - startedAt,
    probedAt,
  };
}

export type ConnectionMcpProbeSummary = {
  appId: string;
  serverUrl: string;
  result: McpProbeResult;
};

/**
 * Bir kullanıcının bağlantısındaki remote_mcp app'leri probla ve sonuçları
 * bağlantı metadata'sına (metadata.mcpProbe[appId]) yaz.
 *
 * İzolasyon: connection satırı HER ZAMAN userId + connectionId birlikte
 * filtrelenir — başka kullanıcının bağlantısı problanamaz ve sonucu okunamaz.
 */
export async function probeConnectionMcpApps(
  app: FastifyInstance,
  input: {
    userId: string;
    connectionId: string;
    appId?: string;
    timeoutMs?: number;
    /** Connection-scoped access token sağlayıcısı (service.ts'ten enjekte
     * edilir; mcp-probe → service döngüsel import'u olmasın diye parametre). */
    getAccessToken: (
      connectionId: string,
      provider: ConnectionProvider,
      appId?: string,
    ) => Promise<string>;
  },
): Promise<ConnectionMcpProbeSummary[]> {
  const rows = await app.db
    .select({
      id: integrationConnections.id,
      appId: integrationConnections.appId,
      provider: integrationConnections.provider,
      status: integrationConnections.status,
      metadata: integrationConnections.metadata,
    })
    .from(integrationConnections)
    .where(
      and(
        eq(integrationConnections.id, input.connectionId),
        eq(integrationConnections.userId, input.userId),
        eq(integrationConnections.status, "connected"),
      ),
    )
    .limit(1);
  const connection = rows[0];
  if (!connection) {
    return [];
  }

  const entries = integrationMcpAppCatalog.filter(
    (entry) =>
      entry.execution === "remote_mcp" &&
      entry.serverUrl &&
      entry.id === (input.appId ?? connection.appId) &&
      entry.provider === connection.provider,
  );
  if (entries.length === 0) {
    return [];
  }

  const summaries: ConnectionMcpProbeSummary[] = [];
  for (const entry of entries) {
    let result: McpProbeResult;
    try {
      const accessToken = await input.getAccessToken(
        connection.id,
        connection.provider,
        connection.appId ?? undefined,
      );
      result = await probeMcpServer({
        url: entry.serverUrl,
        accessToken,
        timeoutMs: input.timeoutMs,
      });
    } catch {
      result = {
        status: "failed",
        errorCode: "MCP_AUTH_REQUIRED",
        httpStatus: null,
        protocolVersion: null,
        serverName: null,
        toolCount: null,
        toolNames: [],
        latencyMs: 0,
        probedAt: new Date().toISOString(),
      };
    }
    summaries.push({ appId: entry.id, serverUrl: entry.serverUrl, result });
  }

  const previousMetadata = asRecord(connection.metadata);
  const previousProbes = asRecord(previousMetadata.mcpProbe);
  const nextProbes = { ...previousProbes };
  for (const summary of summaries) {
    nextProbes[summary.appId] = summary.result;
  }
  await app.db
    .update(integrationConnections)
    .set({
      metadata: { ...previousMetadata, mcpProbe: nextProbes },
      updatedAt: new Date(),
    })
    .where(
      and(
        eq(integrationConnections.id, connection.id),
        eq(integrationConnections.userId, input.userId),
      ),
    );

  app.log.info(
    {
      connectionId: connection.id,
      results: summaries.map((summary) => ({
        appId: summary.appId,
        status: summary.result.status,
        errorCode: summary.result.errorCode,
        toolCount: summary.result.toolCount,
        latencyMs: summary.result.latencyMs,
      })),
    },
    "mcp handshake probe completed",
  );
  return summaries;
}

export function readConnectionMcpProbe(
  metadata: unknown,
  appId: string,
): McpProbeResult | null {
  const probes = asRecord(asRecord(metadata).mcpProbe);
  const entry = probes[appId];
  if (!entry || typeof entry !== "object") {
    return null;
  }
  const record = asRecord(entry);
  if (record.status !== "ok" && record.status !== "failed") {
    return null;
  }
  return record as McpProbeResult;
}

export function isRemoteMcpApp(appId: string | null | undefined): boolean {
  if (!appId) return false;
  const entry = getIntegrationMcpApp(appId);
  return Boolean(entry && entry.execution === "remote_mcp" && entry.serverUrl);
}
