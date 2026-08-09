import { createHash } from "node:crypto";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { UnauthorizedError } from "@modelcontextprotocol/sdk/client/auth.js";
import {
  StreamableHTTPClientTransport,
  StreamableHTTPError,
} from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import {
  MCP_PROBE_PROTOCOL_VERSION,
  MCP_PROBE_TTL_MS,
  type McpProbeErrorCode,
  type McpProbeResult,
} from "./mcp-probe.js";

/**
 * Official `@modelcontextprotocol/sdk` (streamable HTTP) transport, behind the
 * `ELYAN_MCP_SDK_ENABLED` flag. This is a drop-in alternative to the hand-written
 * JSON-RPC probe in `mcp-probe.ts`: it produces the identical `McpProbeResult`
 * so the "connected but dead" honesty contract (real initialize + tools/list
 * handshake) is preserved while the transport is delegated to the SDK.
 *
 */

const DEFAULT_TIMEOUT_MS = 10_000;
const MAX_RECORDED_TOOL_NAMES = 24;
const MAX_RECORDED_TOOL_DESCRIPTION_LENGTH = 240;
// Elle yazılmış probla aynı sınır: modele ilan için ham şema saklanır.
const MAX_RECORDED_TOOL_SCHEMA_LENGTH = 8_000;

function bearerHeaders(accessToken: string): Record<string, string> {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

/** Map SDK transport/auth failures onto the shared probe error taxonomy. */
function classifySdkError(error: unknown): McpProbeErrorCode {
  if (error instanceof UnauthorizedError) return "MCP_AUTH_REQUIRED";
  if (error instanceof StreamableHTTPError) {
    const code = error.code ?? null;
    if (code === 401 || code === 403) return "MCP_AUTH_REQUIRED";
    if (typeof code === "number" && code >= 400) return "MCP_HTTP_ERROR";
    return "MCP_PROTOCOL_ERROR";
  }
  const message = error instanceof Error ? error.message : String(error);
  if (/\b401\b|\b403\b|unauthor/i.test(message)) return "MCP_AUTH_REQUIRED";
  if (/econnrefused|enotfound|etimedout|timeout|network|fetch failed|abort/i.test(message)) {
    return "MCP_UNREACHABLE";
  }
  return "MCP_PROTOCOL_ERROR";
}

async function safeClose(client: Client): Promise<void> {
  try {
    await client.close();
  } catch {
    // closing best-effort; probe result is already computed
  }
}

function newClient(name: string): Client {
  return new Client({ name, version: "1.0" }, { capabilities: {} });
}

function newTransport(url: string, accessToken: string): StreamableHTTPClientTransport {
  return new StreamableHTTPClientTransport(new URL(url), {
    requestInit: { headers: bearerHeaders(accessToken) },
  });
}

/**
 * Probe a streamable-HTTP MCP server through the official SDK. Returns the same
 * `McpProbeResult` shape as `probeMcpServer` so callers and stored metadata are
 * transport-agnostic.
 */
export async function probeMcpServerViaSdk(input: {
  url: string;
  accessToken: string;
  timeoutMs?: number;
}): Promise<McpProbeResult> {
  const timeoutMs = input.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const startedAt = Date.now();
  const probedAt = new Date().toISOString();
  const expiresAt = new Date(Date.now() + MCP_PROBE_TTL_MS).toISOString();
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
    tools: [],
    toolCatalogDigest: null,
    latencyMs: Date.now() - startedAt,
    probedAt,
    expiresAt,
  });

  const client = newClient("elyan-mcp-probe");
  let transport: StreamableHTTPClientTransport;
  try {
    transport = newTransport(input.url, input.accessToken);
  } catch {
    return fail("MCP_UNREACHABLE");
  }

  // connect() drives the initialize handshake (and initialized notification).
  try {
    await client.connect(transport, { timeout: timeoutMs });
  } catch (error) {
    await safeClose(client);
    return fail(classifySdkError(error));
  }

  let toolsResult: Awaited<ReturnType<Client["listTools"]>>;
  try {
    toolsResult = await client.listTools(undefined, { timeout: timeoutMs });
  } catch (error) {
    await safeClose(client);
    return fail(classifySdkError(error));
  }

  const serverVersion = client.getServerVersion();
  await safeClose(client);

  const tools = Array.isArray(toolsResult.tools) ? toolsResult.tools : [];
  const boundedTools = tools
    .slice(0, MAX_RECORDED_TOOL_NAMES)
    .map((tool) => {
      const name = String(tool.name ?? "").trim().slice(0, 160);
      if (!name) return null;
      const description =
        typeof tool.description === "string"
          ? tool.description.replace(/\s+/g, " ").trim().slice(
              0,
              MAX_RECORDED_TOOL_DESCRIPTION_LENGTH,
            )
          : "";
      const serializedInputSchema = tool.inputSchema
        ? (JSON.stringify(tool.inputSchema) ?? "").slice(0, 100_000)
        : "";
      const inputSchemaDigest = serializedInputSchema
        ? createHash("sha256").update(serializedInputSchema).digest("hex")
        : null;
      const inputSchema =
        serializedInputSchema &&
        serializedInputSchema.length <= MAX_RECORDED_TOOL_SCHEMA_LENGTH
          ? (tool.inputSchema as Record<string, unknown>)
          : null;
      const annotations = tool.annotations;
      return {
        name,
        description,
        inputSchemaDigest,
        inputSchema,
        annotations:
          annotations && typeof annotations === "object"
            ? {
                ...(typeof annotations.readOnlyHint === "boolean"
                  ? { readOnlyHint: annotations.readOnlyHint }
                  : {}),
                ...(typeof annotations.destructiveHint === "boolean"
                  ? { destructiveHint: annotations.destructiveHint }
                  : {}),
                ...(typeof annotations.idempotentHint === "boolean"
                  ? { idempotentHint: annotations.idempotentHint }
                  : {}),
                ...(typeof annotations.openWorldHint === "boolean"
                  ? { openWorldHint: annotations.openWorldHint }
                  : {}),
              }
            : null,
      };
    })
    .filter((tool): tool is NonNullable<typeof tool> => Boolean(tool));

  return {
    status: "ok",
    errorCode: null,
    httpStatus: 200,
    // The SDK negotiates the protocol version internally; record the version we
    // offered, matching the hand-written probe's reporting.
    protocolVersion: MCP_PROBE_PROTOCOL_VERSION,
    serverName:
      typeof serverVersion?.name === "string"
        ? serverVersion.name.trim().slice(0, 160)
        : null,
    toolCount: tools.length,
    toolNames: boundedTools.map((tool) => tool.name),
    tools: boundedTools,
    toolCatalogDigest: createHash("sha256")
      .update(JSON.stringify(boundedTools))
      .digest("hex"),
    latencyMs: Date.now() - startedAt,
    probedAt,
    expiresAt,
  };
}

export type McpSdkToolCallResult = {
  ok: boolean;
  isError: boolean;
  content: unknown;
  structuredContent?: unknown;
  errorCode: McpProbeErrorCode | null;
};

/**
 * Execute a single MCP tool via the official SDK. The caller enforces the live
 * user catalog and approval decision before reaching this transport.
 */
export async function callMcpToolViaSdk(input: {
  url: string;
  accessToken: string;
  toolName: string;
  args?: Record<string, unknown>;
  timeoutMs?: number;
}): Promise<McpSdkToolCallResult> {
  const timeoutMs = input.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const client = newClient("elyan-mcp-client");
  let transport: StreamableHTTPClientTransport;
  try {
    transport = newTransport(input.url, input.accessToken);
  } catch (error) {
    return {
      ok: false,
      isError: true,
      content: null,
      structuredContent: null,
      errorCode: classifySdkError(error),
    };
  }
  try {
    await client.connect(transport, { timeout: timeoutMs });
    const result = await client.callTool(
      { name: input.toolName, arguments: input.args ?? {} },
      undefined,
      { timeout: timeoutMs },
    );
    await safeClose(client);
    return {
      ok: result.isError !== true,
      isError: result.isError === true,
      content: result.content ?? null,
      structuredContent: result.structuredContent ?? null,
      errorCode: null,
    };
  } catch (error) {
    await safeClose(client);
    return {
      ok: false,
      isError: true,
      content: null,
      structuredContent: null,
      errorCode: classifySdkError(error),
    };
  }
}
