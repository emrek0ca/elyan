import type { FastifyInstance } from "fastify";
import { callMcpToolViaSdk } from "../integrations/mcp-sdk-client.js";
import {
  isRemoteMcpApp,
  readConnectionMcpProbe,
} from "../integrations/mcp-probe.js";
import { getIntegrationMcpApp } from "../integrations/provider-registry.js";
import {
  getConnectionAccessTokenForProbe,
  listUserIntegrationConnections,
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
 * GÜVENLİK NOTU — bilinçli ürün kararı: araçlar okuma/yazma diye
 * sınıflandırılmaz ve onay kapısına uğramaz. Bir MCP sunucusu yazma aracı
 * ilan ediyorsa model onu doğrudan çalıştırabilir. `connector-writes`
 * staging'i yalnız elle yazılmış Gmail/Takvim yazmalarını kapsar; buradan
 * geçen çağrılar o kapıyı görmez.
 */

/** Katalog başına ilan edilen araç tavanı — istem şişmesin. */
const MAX_TOOLS_PER_APP = 12;
/** Bir turda ilan edilen toplam MCP aracı tavanı. */
const MAX_TOTAL_MCP_TOOLS = 32;
const MCP_TOOL_TIMEOUT_MS = 20_000;
/** Ad alanı ayracı. Nokta KULLANILMIYOR: yerleşik `notion.search` ile çakışırdı. */
export const MCP_TOOL_PREFIX = "mcp__";

export type McpToolDeclaration = {
  /** Modele gösterilen ad: `mcp__<appId>__<toolName>`. */
  name: string;
  appId: string;
  appDisplayName: string;
  connectionId: string;
  /** Uzak sunucudaki gerçek araç adı. */
  remoteToolName: string;
  description: string;
  inputSchema: Record<string, unknown> | null;
  /** `connectorToolContracts` içine konan tek satırlık sözleşme. */
  contract: string;
};

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

  const connections = await listUserIntegrationConnections(app, userId);
  const declarations: McpToolDeclaration[] = [];

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
        contract: buildContract(name, description, tool.inputSchema ?? null),
      });
    }
  }

  return declarations;
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

export type McpToolCallOutcome = {
  ok: boolean;
  output: Record<string, unknown> | null;
  errorCode: string | null;
  errorMessage: string | null;
};

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
  const declarations = await listMcpToolDeclarations(app, input.userId);
  const declaration = declarations.find((item) => item.name === input.toolName);
  if (!declaration) {
    return {
      ok: false,
      output: null,
      errorCode: "mcp_tool_not_available",
      errorMessage: "Bu MCP aracı bağlı değil ya da katalogda yok.",
    };
  }

  const entry = getIntegrationMcpApp(declaration.appId);
  if (!entry?.serverUrl) {
    return {
      ok: false,
      output: null,
      errorCode: "mcp_server_missing",
      errorMessage: "MCP sunucu adresi tanımlı değil.",
    };
  }

  const accessToken = await getConnectionAccessTokenForProbe(
    app,
    declaration.connectionId,
    entry.provider,
    declaration.appId,
  );
  if (!accessToken) {
    return {
      ok: false,
      output: null,
      errorCode: "mcp_auth_required",
      errorMessage: "Bağlantı yetkisi alınamadı, yeniden bağlan.",
    };
  }

  const result = await callMcpToolViaSdk({
    url: entry.serverUrl,
    accessToken,
    toolName: declaration.remoteToolName,
    args: input.args,
    timeoutMs: MCP_TOOL_TIMEOUT_MS,
  });

  if (!result.ok) {
    return {
      ok: false,
      output: null,
      errorCode: result.errorCode ?? "mcp_tool_failed",
      errorMessage: `${declaration.appDisplayName} aracı çalıştırılamadı.`,
    };
  }

  return {
    ok: true,
    output: {
      app: declaration.appId,
      tool: declaration.remoteToolName,
      content: result.content,
    },
    errorCode: null,
    errorMessage: null,
  };
}
