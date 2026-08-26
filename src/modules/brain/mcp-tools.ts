import type { FastifyInstance } from "fastify";
import { and, eq } from "drizzle-orm";
import { rankSemanticTextCandidates } from "../../core/understanding/intent-semantic.js";
import { mcpServers } from "../../db/schema.js";
import { callMcpToolViaSdk } from "../integrations/mcp-sdk-client.js";
import { createAuditLog } from "../audit/service.js";
import {
  isRemoteMcpApp,
  probeMcpServer,
  readConnectionMcpProbe,
  isConnectionMcpProbeFresh,
  type McpProbeResult,
} from "../integrations/mcp-probe.js";
import { getIntegrationMcpApp } from "../integrations/provider-registry.js";
import {
  getConnectionAccessTokenForProbe,
  listUserIntegrationConnections,
  normalizeSafePublicMcpUrl,
} from "../integrations/service.js";

/**
 * Uzak MCP sunucularının TÜM araç kataloğunu paylaşılan beyne bağlar.
 *
 * Bugüne kadar her uzak MCP uygulamasından yalnız BİR araç (`notion.search`,
 * `github.search`, `slack.search`) beyne ulaşıyordu ve o da MCP üzerinden
 * değil, `connector-tools.ts` içinde elle yazılmış bir REST çağrısıyla.
 * Sunucunun geri kalan araçları yalnız masaüstü runtime lease'ine gidiyordu,
 * yani mobilden erişilemiyordu. Bu modül prob sırasında zaten keşfedilip
 * bağlantı metadata'sına yazılan kataloğu okuyup araçları modele ilan eder ve
 * çağrıları `callMcpToolViaSdk` ile sunucu tarafında çalıştırır.
 *
 * Güvenlik sınırı: okuma araçları doğrudan çalışır; yazma veya belirsiz yan
 * etkili araçlar mevcut onay politikasına bırakılır. MCP annotation'ı yoksa
 * araç fail-closed olarak yan etki kabul edilir ve semantik sınıflandırma da
 * yeterince güçlü değilse çağrı çalıştırılmaz.
 */

/** Katalog başına ilan edilen araç tavanı — istem şişmesin. */
const MAX_TOOLS_PER_APP = 12;
/** Bir turda ilan edilen toplam MCP aracı tavanı. */
const MAX_TOTAL_MCP_TOOLS = 32;
const MCP_TOOL_TIMEOUT_MS = 20_000;

/**
 * GEÇİCİ arızada tek yeniden deneme.
 *
 * `callMcpToolViaSdk` her çağrıda yeni bir bağlantı kurar ve uzak MCP
 * sunucuları soğuk başlangıç, DNS gecikmesi ya da anlık 5xx ile düşebiliyor.
 * Yeniden deneme YALNIZ taşıma katmanı hatasında yapılır: sunucunun iş
 * mantığıyla verdiği `isError` sonucu tekrarlanmaz, çünkü o bir cevaptır.
 *
 * Yan etkili araçlar da yeniden denenir mi? Denenmez. Bir "sayfa oluştur"
 * çağrısı zaman aşımına uğradığında isteğin sunucuya ULAŞMIŞ olabileceğini
 * bilemeyiz; tekrarlamak ikinci bir sayfa yaratabilir. Yalnız salt-okuma
 * araçları tekrarlanabilir.
 */
const MCP_RETRYABLE_ERROR_CODES = new Set([
  "mcp_network_error",
  "mcp_timeout",
  "network_error",
  "timeout",
]);
const MCP_RETRY_DELAY_MS = 400;
/** Ad alanı ayracı. Nokta KULLANILMIYOR: yerleşik `notion.search` ile çakışırdı. */
export const MCP_TOOL_PREFIX = "mcp__";
const MCP_DECLARATION_CACHE_TTL_MS = 3_000;
const MCP_DECLARATION_CACHE_MAX_ENTRIES = 4_096;
const MCP_PERMISSION_CACHE_TTL_MS = 5 * 60_000;
const MCP_OUTPUT_MAX_DEPTH = 6;
const MCP_OUTPUT_MAX_KEYS = 96;
const MCP_OUTPUT_MAX_ITEMS = 160;
const MCP_OUTPUT_MAX_STRING_LENGTH = 120_000;

type McpDeclarationCacheEntry = {
  value?: McpToolDeclaration[];
  expiresAt: number;
  pending?: Promise<McpToolDeclaration[]>;
};

const mcpDeclarationCache = new WeakMap<
  FastifyInstance,
  Map<string, McpDeclarationCacheEntry>
>();

export type McpToolDeclaration = {
  /** Modele gösterilen ad: `mcp__<appId>__<toolName>`. */
  name: string;
  appId: string;
  appDisplayName: string;
  connectionId: string;
  serverId?: string;
  serverUrl?: string;
  provider?: string;
  connectionAppId?: string | null;
  authType?: string;
  /** Uzak sunucudaki gerçek araç adı. */
  remoteToolName: string;
  description: string;
  inputSchema: Record<string, unknown> | null;
  annotations: {
    readOnlyHint?: boolean;
    destructiveHint?: boolean;
    idempotentHint?: boolean;
    openWorldHint?: boolean;
  } | null;
  /** `connectorToolContracts` içine konan tek satırlık sözleşme. */
  contract: string;
};

/**
 * Permission metadata is connection-scoped. The same remote tool name can
 * exist on two servers with different annotations/descriptions; caching by
 * app/tool alone could reuse one tenant's classification for another.
 */
export function mcpPermissionCacheKey(
  declaration: Pick<
    McpToolDeclaration,
    "appId" | "remoteToolName" | "connectionId" | "serverId" | "serverUrl"
  >,
): string {
  return JSON.stringify([
    declaration.serverId ?? "",
    declaration.connectionId,
    declaration.serverUrl ?? "",
    declaration.appId,
    declaration.remoteToolName,
  ]);
}

export type McpToolOperation = "read" | "write";

export type McpToolSelection = {
  tool: string;
  operation: McpToolOperation;
  score: number;
  margin: number;
  source: "transformer";
};

type McpToolPermission = "read" | "side_effect";

type McpPermissionCacheEntry = {
  permission: McpToolPermission;
  expiresAt: number;
};

const mcpPermissionCache = new WeakMap<
  FastifyInstance,
  Map<string, McpPermissionCacheEntry>
>();

function sanitizeSegment(value: string): string {
  return value.replace(/[^a-zA-Z0-9_]+/gu, "_").slice(0, 64);
}

export function mcpToolName(appId: string, remoteToolName: string): string {
  return `${MCP_TOOL_PREFIX}${sanitizeSegment(appId)}__${sanitizeSegment(remoteToolName)}`;
}

export function isMcpToolName(name: string): boolean {
  return name.startsWith(MCP_TOOL_PREFIX);
}

/**
 * Bağlı ve el sıkışması BAŞARILI uzak MCP bağlantılarının araç kataloğu.
 *
 * Probu başarısız ya da süresi geçmiş bağlantılar atlanır: bayat katalogla
 * araç ilan etmek, modelin sunucuda artık var olmayan bir aracı çağırması
 * demek olurdu.
 */
export async function listMcpToolDeclarations(
  app: FastifyInstance,
  userId: string,
): Promise<McpToolDeclaration[]> {
  if (app.config?.ELYAN_MCP_DYNAMIC_TOOLS_ENABLED !== true) {
    return [];
  }

  let cache = mcpDeclarationCache.get(app);
  if (!cache) {
    cache = new Map();
    mcpDeclarationCache.set(app, cache);
  }
  const now = Date.now();
  const cached = cache.get(userId);
  if (cached?.value && cached.expiresAt > now) {
    return cached.value;
  }
  if (cached?.pending) {
    return cached.pending;
  }

  if (!cached && cache.size >= MCP_DECLARATION_CACHE_MAX_ENTRIES) {
    const oldestKey = cache.keys().next().value;
    if (typeof oldestKey === "string") cache.delete(oldestKey);
  }
  const pending = queryMcpToolDeclarations(app, userId);
  cache.set(userId, { expiresAt: 0, pending });
  try {
    const value = await pending;
    cache.set(userId, {
      value,
      expiresAt: Date.now() + MCP_DECLARATION_CACHE_TTL_MS,
    });
    return value;
  } catch (error) {
    cache.delete(userId);
    throw error;
  }
}

async function queryMcpToolDeclarations(
  app: FastifyInstance,
  userId: string,
): Promise<McpToolDeclaration[]> {
  if (app.config?.ELYAN_MCP_DYNAMIC_TOOLS_ENABLED !== true) {
    return [];
  }

  const connections = await listUserIntegrationConnections(app, userId);
  const declarations: McpToolDeclaration[] = [];
  /**
   * ÇAKIŞMA KAPISI: aynı araç iki kez ilan edilmesin.
   *
   * Bildirimler iki ayrı kaynaktan geliyor — küratörlü katalog uygulamaları
   * ve kullanıcının kendi kaydettiği MCP sunucuları. Aynı sunucu ikisinden de
   * bağlanabilir (ör. Notion hem katalogdan hem elle eklenmiş bir
   * `https://mcp.notion.com/mcp` kaydı olarak). Adlar `appId` farklı olduğu
   * için ÇARPIŞMIYOR, bu yüzden hiçbir yerde hata vermiyordu; model aynı
   * aracı iki ayrı isimle görüyor, ikisi farklı yetkilendirmeyle çalışıyor ve
   * hangisini seçtiği tesadüfe kalıyordu.
   *
   * Anahtar sunucu adresi + uzak araç adıdır: aynı uçtaki aynı araç bir kez
   * ilan edilir. Katalog kaydı önce geldiği için o kazanır — incelenmiş
   * uç nokta ve incelenmiş yetki akışı olan taraf odur.
   */
  const advertised = new Set<string>();
  const advertiseKey = (url: string, toolName: string): string =>
    `${url.trim().toLowerCase().replace(/\/+$/u, "")}::${toolName.trim().toLowerCase()}`;

  for (const connection of connections) {
    if (declarations.length >= MAX_TOTAL_MCP_TOOLS) break;
    const appId = connection.appId;
    if (
      connection.status !== "connected" ||
      !appId ||
      !isRemoteMcpApp(appId)
    ) {
      continue;
    }
    const entry = getIntegrationMcpApp(appId);
    if (!entry?.serverUrl) continue;

    const probe = readConnectionMcpProbe(connection.metadata, appId);
    if (!probe || probe.status !== "ok") continue;
    // TTL: `readConnectionMcpProbe` süresi geçmiş kaydı zaten `null` döndürür,
    // ama sözleşme değişirse burada da sessizce yanlış araç ilan etmeyelim.
    if (Date.parse(probe.expiresAt) <= Date.now()) continue;

    for (const tool of probe.tools.slice(0, MAX_TOOLS_PER_APP)) {
      if (declarations.length >= MAX_TOTAL_MCP_TOOLS) break;
      if (!tool.name) continue;
      const catalogUrl = entry.serverUrl ?? "";
      if (catalogUrl) {
        const key = advertiseKey(catalogUrl, tool.name);
        if (advertised.has(key)) continue;
        advertised.add(key);
      }
      const name = mcpToolName(appId, tool.name);
      const description =
        tool.description || `${entry.displayName}: ${tool.name}`;
      declarations.push({
        name,
        appId,
        appDisplayName: entry.displayName,
        connectionId: connection.id,
        remoteToolName: tool.name,
        description,
        inputSchema: tool.inputSchema ?? null,
        annotations: tool.annotations ?? null,
        contract: buildContract(name, description, tool.inputSchema ?? null),
      });
    }
  }

  const registeredServers = await app.db
    .select({
      id: mcpServers.id,
      integrationConnectionId: mcpServers.integrationConnectionId,
      name: mcpServers.name,
      transport: mcpServers.transport,
      authType: mcpServers.authType,
      status: mcpServers.status,
      baseUrl: mcpServers.baseUrl,
      metadata: mcpServers.metadata,
    })
    .from(mcpServers)
    .where(eq(mcpServers.userId, userId));

  for (const server of registeredServers) {
    const safeServerUrl = normalizeSafePublicMcpUrl(server.baseUrl);
    if (
      declarations.length >= MAX_TOTAL_MCP_TOOLS ||
      server.status === "revoked" ||
      server.transport === "stdio" ||
      !safeServerUrl ||
      !["remote", "oauth_remote", "streamable_http"].includes(server.transport)
    ) {
      continue;
    }
    const serverAppId = `mcp_server_${server.id}`;
    const metadata = asRecord(server.metadata);
    let probe = readRegisteredMcpProbe(metadata);
    if (!probe || !isConnectionMcpProbeFresh(probe)) {
      probe = await probeRegisteredMcpServer(
        app,
        userId,
        { ...server, baseUrl: safeServerUrl },
        connections,
      );
    }
    if (!probe || probe.status !== "ok") continue;

    for (const tool of probe.tools.slice(0, MAX_TOOLS_PER_APP)) {
      if (declarations.length >= MAX_TOTAL_MCP_TOOLS || !tool.name) break;
      const key = advertiseKey(safeServerUrl, tool.name);
      if (advertised.has(key)) continue;
      advertised.add(key);
      const name = mcpToolName(serverAppId, tool.name);
      const description = tool.description || `${server.name}: ${tool.name}`;
      declarations.push({
        name,
        appId: serverAppId,
        appDisplayName: server.name,
        connectionId: server.integrationConnectionId ?? "",
        serverId: server.id,
        serverUrl: safeServerUrl,
        provider: connections.find(
          (connection) => connection.id === server.integrationConnectionId,
        )?.provider,
        connectionAppId: connections.find(
          (connection) => connection.id === server.integrationConnectionId,
        )?.appId,
        authType: server.authType,
        remoteToolName: tool.name,
        description,
        inputSchema: tool.inputSchema ?? null,
        annotations: tool.annotations ?? null,
        contract: buildContract(name, description, tool.inputSchema ?? null),
      });
    }
  }

  return declarations;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function readRegisteredMcpProbe(metadata: Record<string, unknown>): McpProbeResult | null {
  const probe = metadata.mcpProbe;
  if (!probe || typeof probe !== "object" || Array.isArray(probe)) return null;
  const result = probe as McpProbeResult;
  return result.status === "ok" || result.status === "failed" ? result : null;
}

async function probeRegisteredMcpServer(
  app: FastifyInstance,
  userId: string,
  server: {
    id: string;
    integrationConnectionId: string | null;
    name: string;
    authType: string;
    baseUrl: string | null;
    metadata: unknown;
  },
  connections: Awaited<ReturnType<typeof listUserIntegrationConnections>>,
): Promise<McpProbeResult | null> {
  if (!server.baseUrl) return null;
  const connection = connections.find(
    (candidate) => candidate.id === server.integrationConnectionId,
  );
  if (
    server.authType !== "none" &&
    (!connection || connection.status !== "connected")
  ) {
    return null;
  }
  let accessToken = "";
  try {
    if (connection && server.authType !== "none") {
      accessToken = await getConnectionAccessTokenForProbe(
        app,
        connection.id,
        connection.provider,
        connection.appId ?? undefined,
        4_000,
      );
    }
    const probe = await probeMcpServer({
      url: server.baseUrl,
      accessToken,
      timeoutMs: 4_000,
      useSdk: app.config.ELYAN_MCP_SDK_ENABLED === true,
    });
    const metadata = asRecord(server.metadata);
    await app.db
      .update(mcpServers)
      .set({
        metadata: { ...metadata, mcpProbe: probe },
        updatedAt: new Date(),
      })
      .where(and(eq(mcpServers.id, server.id), eq(mcpServers.userId, userId)));
    return probe;
  } catch {
    return null;
  }
}

const MCP_TOOL_SELECTION_NEGATIVES = [
  {
    id: "negative:general",
    description:
      "General conversation, explanation, coding, or a request that does not need data from a connected account or MCP server.",
  },
  {
    id: "negative:meta",
    description:
      "Explain what an integration, MCP, API, or software tool is without accessing the connected account.",
  },
] as const;

function operationCandidates(
  declaration: McpToolDeclaration,
): Array<{ id: string; description: string }> {
  const base = `${declaration.appDisplayName} ${declaration.remoteToolName}: ${declaration.description}`;
  const candidates: Array<{ id: string; description: string }> = [];
  const annotation = declaration.annotations;
  if (annotation?.readOnlyHint !== false && annotation?.destructiveHint !== true) {
    candidates.push({
      id: `read:${declaration.name}`,
      description: `Read, search, list, inspect, retrieve, or summarize data from ${base}. Do not change the connected account.`,
    });
  }
  if (annotation?.readOnlyHint !== true) {
    candidates.push({
      id: `write:${declaration.name}`,
      description: `Create, send, update, delete, move, or otherwise change data in ${base}. This is an external side effect.`,
    });
  }
  return candidates;
}

/**
 * Selects one live MCP tool from the current connected-server catalog. The
 * candidate descriptions are generated from the server's own tool metadata;
 * no provider/tool keyword table is involved.
 */
export async function selectSemanticMcpTool(
  prompt: string,
  declarations: readonly McpToolDeclaration[],
  options: { sideEffectDetected?: boolean } = {},
): Promise<McpToolSelection | null> {
  const candidates = declarations.flatMap((declaration) => {
    if (options.sideEffectDetected === true) {
      return operationCandidates(declaration).filter((candidate) =>
        candidate.id.startsWith("write:"),
      );
    }
    return operationCandidates(declaration);
  });
  if (candidates.length === 0) return null;

  const match = await rankSemanticTextCandidates(
    prompt,
    [...candidates, ...MCP_TOOL_SELECTION_NEGATIVES],
    {
      transformerMinScore: 0.72,
      transformerMinMargin: 0.006,
      transformerTimeoutMs: 1_800,
      hashMinScore: 1.1,
      hashMinMargin: 1.1,
    },
  );
  if (!match || match.source !== "transformer") return null;
  const separator = match.id.indexOf(":");
  const operation = separator > 0 ? match.id.slice(0, separator) : "";
  const tool = separator > 0 ? match.id.slice(separator + 1) : "";
  if (
    (operation !== "read" && operation !== "write") ||
    !declarations.some((declaration) => declaration.name === tool)
  ) {
    return null;
  }
  return {
    tool,
    operation,
    score: match.score,
    margin: match.margin,
    source: "transformer",
  };
}

/**
 * Resolves the execution permission from MCP annotations first and from the
 * tool's own semantic description second. Unknown tools remain side-effecting.
 */
export async function resolveMcpToolPermission(
  app: FastifyInstance,
  declaration: McpToolDeclaration,
): Promise<McpToolPermission> {
  const annotation = declaration.annotations;
  if (annotation?.readOnlyHint === true && annotation.destructiveHint !== true) {
    return "read";
  }
  if (annotation?.readOnlyHint === false || annotation?.destructiveHint === true) {
    return "side_effect";
  }

  let cache = mcpPermissionCache.get(app);
  if (!cache) {
    cache = new Map();
    mcpPermissionCache.set(app, cache);
  }
  const cacheKey = mcpPermissionCacheKey(declaration);
  const cached = cache.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) return cached.permission;

  const match = await rankSemanticTextCandidates(
    `${declaration.appDisplayName} ${declaration.remoteToolName}: ${declaration.description}`,
    [
      {
        id: "read",
        description:
          "Read, search, list, inspect, retrieve, or summarize existing data without changing the connected account.",
      },
      {
        id: "write",
        description:
          "Create, send, update, delete, move, publish, or otherwise change existing data in a connected account.",
      },
    ],
    {
      transformerMinScore: 0.62,
      transformerMinMargin: 0.01,
      transformerTimeoutMs: 1_800,
      hashMinScore: 1.1,
      hashMinMargin: 1.1,
    },
  );
  const permission: McpToolPermission =
    match?.source === "transformer" && match.id === "read"
      ? "read"
      : "side_effect";
  cache.set(cacheKey, {
    permission,
    expiresAt: Date.now() + MCP_PERMISSION_CACHE_TTL_MS,
  });
  return permission;
}

/**
 * Tek satırlık model sözleşmesi. Yerleşik araçlarla aynı biçim:
 * `ad {arg:type, ...} — açıklama`.
 */
function buildContract(
  name: string,
  description: string,
  inputSchema: Record<string, unknown> | null,
): string {
  const properties =
    inputSchema && typeof inputSchema.properties === "object"
      ? (inputSchema.properties as Record<string, unknown>)
      : {};
  const required = new Set(
    Array.isArray(inputSchema?.required)
      ? (inputSchema?.required as unknown[]).map(String)
      : [],
  );
  const args = Object.entries(properties)
    .slice(0, 10)
    .map(([key, raw]) => {
      const schema =
        raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
      const type = typeof schema.type === "string" ? schema.type : "any";
      return required.has(key) ? `${key}:${type}` : `${key}?:${type}`;
    })
    .join(", ");
  const signature = args ? `{${args}}` : "{}";
  return `${name} ${signature} — ${description}`;
}

function boundedMcpValue(
  value: unknown,
  depth = 0,
): unknown {
  if (value == null || typeof value === "boolean" || typeof value === "number") {
    return value;
  }
  if (typeof value === "string") {
    return value.slice(0, MCP_OUTPUT_MAX_STRING_LENGTH);
  }
  if (depth >= MCP_OUTPUT_MAX_DEPTH) return "[truncated]";
  if (Array.isArray(value)) {
    return value
      .slice(0, MCP_OUTPUT_MAX_ITEMS)
      .map((item) => boundedMcpValue(item, depth + 1));
  }
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .slice(0, MCP_OUTPUT_MAX_KEYS)
        .map(([key, nested]) => [key.slice(0, 160), boundedMcpValue(nested, depth + 1)]),
    );
  }
  return String(value).slice(0, MCP_OUTPUT_MAX_STRING_LENGTH);
}

function parseJsonText(value: unknown): unknown {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (
    !trimmed ||
    (!trimmed.startsWith("{") && !trimmed.startsWith("[")) ||
    trimmed.length > MCP_OUTPUT_MAX_STRING_LENGTH
  ) {
    return null;
  }
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return null;
  }
}

function normalizeMcpContent(content: unknown): {
  items: unknown[];
  text: string;
  structured: unknown;
} {
  const items: unknown[] = [];
  const textParts: string[] = [];
  let structured: unknown = null;
  const entries = Array.isArray(content) ? content : content == null ? [] : [content];
  for (const entry of entries.slice(0, MCP_OUTPUT_MAX_ITEMS)) {
    const record =
      entry && typeof entry === "object" && !Array.isArray(entry)
        ? (entry as Record<string, unknown>)
        : null;
    if (record?.type === "text" && typeof record.text === "string") {
      const parsed = parseJsonText(record.text);
      if (parsed !== null) structured = parsed;
      textParts.push(record.text.slice(0, MCP_OUTPUT_MAX_STRING_LENGTH));
      items.push({ type: "text", text: record.text.slice(0, MCP_OUTPUT_MAX_STRING_LENGTH) });
      continue;
    }
    if (record?.type === "resource" && record.resource) {
      const resource = boundedMcpValue(record.resource);
      items.push({ type: "resource", resource });
      const resourceRecord =
        resource && typeof resource === "object" && !Array.isArray(resource)
          ? (resource as Record<string, unknown>)
          : null;
      if (typeof resourceRecord?.text === "string") {
        const parsed = parseJsonText(resourceRecord.text);
        if (parsed !== null) structured = parsed;
        textParts.push(resourceRecord.text);
      }
      continue;
    }
    if (record?.type === "image") {
      items.push({
        type: "image",
        mimeType:
          typeof record.mimeType === "string" ? record.mimeType.slice(0, 120) : null,
        data: boundedMcpValue(record.data),
      });
      continue;
    }
    const bounded = boundedMcpValue(entry);
    items.push(bounded);
    if (typeof bounded === "string") textParts.push(bounded);
  }
  return { items, text: textParts.join("\n").slice(0, MCP_OUTPUT_MAX_STRING_LENGTH), structured };
}

function findRows(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) {
    return value
      .filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
      .slice(0, MCP_OUTPUT_MAX_ITEMS);
  }
  if (!value || typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  for (const key of ["results", "items", "rows", "records", "data", "events", "messages", "files"]) {
    const rows = findRows(record[key]);
    if (rows.length > 0) return rows;
  }
  return [];
}

function normalizeMcpToolOutput(input: {
  appId: string;
  appDisplayName: string;
  toolName: string;
  permission: McpToolPermission;
  content: unknown;
  structuredContent?: unknown;
}): Record<string, unknown> {
  const normalizedContent = normalizeMcpContent(input.content);
  const structured =
    input.structuredContent != null
      ? boundedMcpValue(input.structuredContent)
      : normalizedContent.structured ?? null;
  const data = structured ?? normalizedContent.items;
  const results = findRows(data);
  return {
    source: "mcp",
    app: input.appId,
    appDisplayName: input.appDisplayName,
    tool: input.toolName,
    permission: input.permission,
    data,
    results,
    resultCount: results.length,
    text: normalizedContent.text || null,
    content: normalizedContent.items,
  };
}

export type McpToolCallOutcome = {
  ok: boolean;
  permission: McpToolPermission;
  output: Record<string, unknown> | null;
  errorCode: string | null;
  errorMessage: string | null;
};

export async function resolveMcpToolDeclaration(
  app: FastifyInstance,
  userId: string,
  toolName: string,
): Promise<McpToolDeclaration | null> {
  const declarations = await queryMcpToolDeclarations(app, userId);
  return declarations.find((item) => item.name === toolName) ?? null;
}

/**
 * İlan edilmiş bir MCP aracını çalıştırır.
 *
 * Araç adı her zaman kullanıcının KENDİ bağlantı kataloğundan yeniden
 * çözümlenir — modelin ürettiği ada güvenip doğrudan uzak sunucuya
 * geçirmiyoruz; kataloğunda olmayan bir araç çağrılamaz.
 */
export async function callMcpTool(
  app: FastifyInstance,
  input: { userId: string; toolName: string; args: Record<string, unknown> },
): Promise<McpToolCallOutcome> {
  let permission: McpToolPermission = "side_effect";
  try {
  // Tool execution re-reads the connection catalog so a just-revoked
  // integration can never remain usable through the advertisement cache.
  const declaration = await resolveMcpToolDeclaration(
    app,
    input.userId,
    input.toolName,
  );
  if (!declaration) {
    return {
      ok: false,
      permission: "side_effect",
      output: null,
      errorCode: "mcp_tool_not_available",
      errorMessage: "Bu MCP aracı bağlı değil ya da katalogda yok.",
    };
  }

  const entry = getIntegrationMcpApp(declaration.appId);
  const serverUrl = declaration.serverUrl ?? entry?.serverUrl;
  if (!serverUrl) {
    return {
      ok: false,
      permission: "side_effect",
      output: null,
      errorCode: "mcp_server_missing",
      errorMessage: "MCP sunucu adresi tanımlı değil.",
    };
  }

  let accessToken = "";
  try {
    accessToken = declaration.authType === "none"
      ? ""
      : declaration.connectionId && declaration.provider
        ? await getConnectionAccessTokenForProbe(
            app,
            declaration.connectionId,
            declaration.provider as Parameters<typeof getConnectionAccessTokenForProbe>[2],
            declaration.connectionAppId ?? (declaration.serverId ? undefined : declaration.appId),
          )
        : "";
  } catch {
    return {
      ok: false,
      permission,
      output: null,
      errorCode: "mcp_auth_required",
      errorMessage: "Bağlantı yetkisi alınamadı, yeniden bağlan.",
    };
  }
  if (!accessToken) {
    if (declaration.authType === "none") {
      // Anonymous MCP servers intentionally use the empty bearer value.
    } else {
      return {
        ok: false,
        permission: "side_effect",
        output: null,
        errorCode: "mcp_auth_required",
        errorMessage: "Bağlantı yetkisi alınamadı, yeniden bağlan.",
      };
    }
  }

  permission = await resolveMcpToolPermission(app, declaration);

  const startedAt = Date.now();
  let result = await callMcpToolViaSdk({
    url: serverUrl,
    accessToken,
    toolName: declaration.remoteToolName,
    args: input.args,
    timeoutMs: MCP_TOOL_TIMEOUT_MS,
  });
  let attempts = 1;
  if (
    !result.ok &&
    permission === "read" &&
    MCP_RETRYABLE_ERROR_CODES.has(String(result.errorCode ?? ""))
  ) {
    await new Promise((resolve) => setTimeout(resolve, MCP_RETRY_DELAY_MS));
    attempts = 2;
    result = await callMcpToolViaSdk({
      url: serverUrl,
      accessToken,
      toolName: declaration.remoteToolName,
      args: input.args,
      timeoutMs: MCP_TOOL_TIMEOUT_MS,
    });
  }

  await traceMcpToolCall(app, {
    userId: input.userId,
    declaration,
    permission,
    args: input.args,
    ok: result.ok,
    errorCode: result.ok ? null : (result.errorCode ?? "mcp_tool_failed"),
    durationMs: Date.now() - startedAt,
    attempts,
  });

  if (!result.ok) {
    return {
      ok: false,
      permission,
      output: null,
      errorCode: result.errorCode ?? "mcp_tool_failed",
      errorMessage: `${declaration.appDisplayName} aracı çalıştırılamadı.`,
    };
  }

  return {
    ok: true,
    permission,
    output: {
      ...normalizeMcpToolOutput({
        appId: declaration.appId,
        appDisplayName: declaration.appDisplayName,
        toolName: declaration.remoteToolName,
        permission,
        content: result.content,
        structuredContent: result.structuredContent,
      }),
    },
    errorCode: null,
    errorMessage: null,
  };
  } catch (error) {
    // SESSİZ YUTMA YASAK. Bu blok hatayı hiçbir iz bırakmadan yutuyordu:
    // "MCP aracı çalışmıyor" ile "kodda bir istisna var" birbirinden ayırt
    // edilemiyordu. Davranış aynı (kullanıcıya aynı mesaj), fark: artık
    // sebebi logda yazıyor.
    app.log?.warn?.(
      {
        err: error instanceof Error ? error.message : String(error),
        toolName: input.toolName,
      },
      "mcp tool call threw",
    );
    return {
      ok: false,
      permission,
      output: null,
      errorCode: "mcp_tool_failed",
      errorMessage: "MCP aracı şu anda kullanılamıyor.",
    };
  }
}

/**
 * BAĞLI UYGULAMA ÇAĞRISININ İZİ.
 *
 * MCP sunucusu EKLEMEK denetime yazılıyordu (`mcp.server.create`), ama araç
 * ÇAĞIRMAK hiçbir iz bırakmıyordu. Yani kullanıcının Notion'ında bir sayfa
 * oluşturulduğunda ya da Gmail'i okunduğunda sistemde bunun kaydı yoktu —
 * ne kullanıcı görebiliyordu ne de bir arıza sonrası geriye bakılabiliyordu.
 *
 * ARGÜMAN DEĞERLERİ YAZILMAZ, yalnız anahtar adları. Bir MCP çağrısının
 * argümanı mesaj gövdesi, sayfa içeriği ya da arama sorgusu olabilir; denetim
 * kaydı ne yapıldığını göstermeli, kullanıcının verisini ikinci bir yere
 * kopyalamamalı. (Aynı ilke `task-episode` ambarında da uygulanıyor.)
 *
 * İz YAZILAMAZSA çağrı düşmez: denetim kaydı işin kendisini engellemez.
 */
async function traceMcpToolCall(
  app: FastifyInstance,
  input: {
    userId: string;
    declaration: McpToolDeclaration;
    permission: McpToolPermission;
    args: Record<string, unknown>;
    ok: boolean;
    errorCode: string | null;
    durationMs: number;
    attempts: number;
  },
): Promise<void> {
  try {
    await createAuditLog(app, {
      userId: input.userId,
      // Çağrıyı backend yapar; hesap sahibi `userId` alanında zaten duruyor.
      actorType: "system",
      actorId: input.userId,
      action: "mcp.tool.call",
      resourceType: "mcp_tool",
      resourceId: input.declaration.name,
      status: input.ok ? "success" : "failure",
      payload: {
        appId: input.declaration.appId,
        appDisplayName: input.declaration.appDisplayName,
        toolName: input.declaration.remoteToolName,
        permission: input.permission,
        argKeys: Object.keys(input.args ?? {}).slice(0, 24),
        argCount: Object.keys(input.args ?? {}).length,
        durationMs: input.durationMs,
        attempts: input.attempts,
        ...(input.errorCode ? { errorCode: input.errorCode } : {}),
      },
    });
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "mcp tool call trace not recorded",
    );
  }
}
