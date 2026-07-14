import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MCP_PROBE_PROTOCOL_VERSION,
  isRemoteMcpApp,
  probeMcpServer,
  readConnectionMcpProbe,
} from "./mcp-probe.js";

type FetchHandler = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

async function withMockedFetch<T>(handler: FetchHandler, run: () => Promise<T>): Promise<T> {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = handler as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

function jsonResponse(payload: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

function parseBody(init?: RequestInit): Record<string, unknown> {
  return JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
}

test("probeMcpServer completes initialize + tools/list handshake over JSON", async () => {
  const seenAuth: string[] = [];
  const seenSessionIds: Array<string | null> = [];
  const result = await withMockedFetch(
    async (_input, init) => {
      const body = parseBody(init);
      const headers = new Headers(init?.headers as HeadersInit);
      seenAuth.push(headers.get("authorization") ?? "");
      seenSessionIds.push(headers.get("mcp-session-id"));
      if (body.method === "initialize") {
        return jsonResponse(
          {
            jsonrpc: "2.0",
            id: body.id,
            result: {
              protocolVersion: MCP_PROBE_PROTOCOL_VERSION,
              capabilities: { tools: {} },
              serverInfo: { name: "linear-mcp", version: "1.2" },
            },
          },
          { headers: { "content-type": "application/json", "mcp-session-id": "sess-42" } },
        );
      }
      if (body.method === "notifications/initialized") {
        return new Response(null, { status: 202 });
      }
      if (body.method === "tools/list") {
        return jsonResponse({
          jsonrpc: "2.0",
          id: body.id,
          result: {
            tools: [
              { name: "linear.search_issues", description: "" },
              { name: "linear.create_issue", description: "" },
            ],
          },
        });
      }
      throw new Error(`unexpected method: ${String(body.method)}`);
    },
    () => probeMcpServer({ url: "https://mcp.linear.app/mcp", accessToken: "tok-1" }),
  );

  assert.equal(result.status, "ok");
  assert.equal(result.errorCode, null);
  assert.equal(result.toolCount, 2);
  assert.deepEqual(result.toolNames, ["linear.search_issues", "linear.create_issue"]);
  assert.equal(result.serverName, "linear-mcp");
  assert.equal(result.protocolVersion, MCP_PROBE_PROTOCOL_VERSION);
  // Her istek bağlantının kendi bearer token'ını taşımalı.
  assert.equal(seenAuth.every((value) => value === "Bearer tok-1"), true);
  // initialize sonrası session id taşınmalı.
  assert.equal(seenSessionIds[0], null);
  assert.equal(seenSessionIds[1], "sess-42");
  assert.equal(seenSessionIds[2], "sess-42");
});

test("probeMcpServer parses SSE-framed JSON-RPC responses", async () => {
  const result = await withMockedFetch(
    async (_input, init) => {
      const body = parseBody(init);
      if (body.method === "initialize") {
        const sse = [
          ": keepalive",
          "",
          `data: ${JSON.stringify({
            jsonrpc: "2.0",
            id: body.id,
            result: { protocolVersion: MCP_PROBE_PROTOCOL_VERSION, serverInfo: { name: "notion-mcp" } },
          })}`,
          "",
          "",
        ].join("\n");
        return new Response(sse, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        });
      }
      if (body.method === "notifications/initialized") {
        return new Response(null, { status: 202 });
      }
      return jsonResponse({
        jsonrpc: "2.0",
        id: body.id,
        result: { tools: [{ name: "notion.search" }] },
      });
    },
    () => probeMcpServer({ url: "https://mcp.notion.com/mcp", accessToken: "tok-2" }),
  );

  assert.equal(result.status, "ok");
  assert.equal(result.toolCount, 1);
  assert.equal(result.serverName, "notion-mcp");
});

test("probeMcpServer reports MCP_AUTH_REQUIRED on 401", async () => {
  const result = await withMockedFetch(
    async () => new Response("unauthorized", { status: 401 }),
    () => probeMcpServer({ url: "https://mcp.linear.app/mcp", accessToken: "expired" }),
  );
  assert.equal(result.status, "failed");
  assert.equal(result.errorCode, "MCP_AUTH_REQUIRED");
  assert.equal(result.httpStatus, 401);
});

test("probeMcpServer reports MCP_UNREACHABLE on network failure", async () => {
  const result = await withMockedFetch(
    async () => {
      throw new TypeError("fetch failed");
    },
    () => probeMcpServer({ url: "https://mcp.linear.app/mcp", accessToken: "tok" }),
  );
  assert.equal(result.status, "failed");
  assert.equal(result.errorCode, "MCP_UNREACHABLE");
});

test("probeMcpServer reports MCP_PROTOCOL_ERROR when tools/list is malformed", async () => {
  const result = await withMockedFetch(
    async (_input, init) => {
      const body = parseBody(init);
      if (body.method === "initialize") {
        return jsonResponse({ jsonrpc: "2.0", id: body.id, result: { serverInfo: {} } });
      }
      if (body.method === "notifications/initialized") {
        return new Response(null, { status: 202 });
      }
      return jsonResponse({ jsonrpc: "2.0", id: body.id, result: { nope: true } });
    },
    () => probeMcpServer({ url: "https://mcp.linear.app/mcp", accessToken: "tok" }),
  );
  assert.equal(result.status, "failed");
  assert.equal(result.errorCode, "MCP_PROTOCOL_ERROR");
});

test("probeMcpServer reports MCP_PROTOCOL_ERROR on JSON-RPC error payloads", async () => {
  const result = await withMockedFetch(
    async (_input, init) => {
      const body = parseBody(init);
      return jsonResponse({
        jsonrpc: "2.0",
        id: body.id,
        error: { code: -32600, message: "bad request" },
      });
    },
    () => probeMcpServer({ url: "https://mcp.linear.app/mcp", accessToken: "tok" }),
  );
  assert.equal(result.status, "failed");
  assert.equal(result.errorCode, "MCP_PROTOCOL_ERROR");
});

test("readConnectionMcpProbe reads only well-formed per-app probe records", () => {
  const metadata = {
    mcpProbe: {
      linear: {
        status: "ok",
        errorCode: null,
        httpStatus: 200,
        protocolVersion: MCP_PROBE_PROTOCOL_VERSION,
        serverName: "linear-mcp",
        toolCount: 3,
        toolNames: ["a", "b", "c"],
        latencyMs: 120,
        probedAt: "2026-07-14T15:00:00.000Z",
      },
      broken: { status: "weird" },
    },
  };
  assert.equal(readConnectionMcpProbe(metadata, "linear")?.toolCount, 3);
  assert.equal(readConnectionMcpProbe(metadata, "broken"), null);
  assert.equal(readConnectionMcpProbe(metadata, "missing"), null);
  assert.equal(readConnectionMcpProbe(null, "linear"), null);
});

test("isRemoteMcpApp matches only catalog remote MCP entries", () => {
  assert.equal(isRemoteMcpApp("linear"), true);
  assert.equal(isRemoteMcpApp("notion"), true);
  // Google yetenekleri server_connector — desktop lease'ine ve proba girmez.
  assert.equal(isRemoteMcpApp("gmail"), false);
  assert.equal(isRemoteMcpApp("unknown-app"), false);
  assert.equal(isRemoteMcpApp(null), false);
});
