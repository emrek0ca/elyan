import assert from "node:assert/strict";
import test from "node:test";
import { mcpPermissionCacheKey } from "./mcp-tools.js";

test("MCP permission cache keys are scoped to the connection and server", () => {
  const declaration = {
    appId: "notion",
    remoteToolName: "search",
    connectionId: "connection-a",
    serverId: "server-a",
    serverUrl: "https://mcp.example.test/a",
  };

  assert.equal(mcpPermissionCacheKey(declaration), mcpPermissionCacheKey({ ...declaration }));
  assert.notEqual(
    mcpPermissionCacheKey(declaration),
    mcpPermissionCacheKey({ ...declaration, connectionId: "connection-b" }),
  );
  assert.notEqual(
    mcpPermissionCacheKey(declaration),
    mcpPermissionCacheKey({ ...declaration, serverId: "server-b" }),
  );
  assert.notEqual(
    mcpPermissionCacheKey(declaration),
    mcpPermissionCacheKey({ ...declaration, serverUrl: "https://mcp.example.test/b" }),
  );
});
