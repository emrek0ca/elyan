import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CONNECTOR_TOOL_CONTRACTS,
  connectorToolContract,
  connectorToolsForCapabilities,
  isConnectorTool,
} from "./connector-tools.js";
import { getAgentToolMetadata, listAgentTools } from "./tool-registry.js";

test("connectorToolsForCapabilities advertises only connected capabilities", () => {
  const gmailOnly = connectorToolsForCapabilities(["gmail"]).map((entry) => entry.name);
  assert.deepEqual(gmailOnly.sort(), ["gmail.read", "gmail.search"]);

  const none = connectorToolsForCapabilities([]);
  assert.equal(none.length, 0);

  const all = connectorToolsForCapabilities(["gmail", "calendar", "drive"]).map(
    (entry) => entry.name,
  );
  assert.deepEqual(all.sort(), [
    "calendar.list_events",
    "drive.search",
    "gmail.read",
    "gmail.search",
  ]);
});

test("connector tool contracts each map to a registered read-only agent tool", () => {
  const registered = new Map(
    listAgentTools().map((tool) => [tool.name, tool.permission]),
  );
  for (const entry of CONNECTOR_TOOL_CONTRACTS) {
    assert.equal(
      registered.get(entry.name),
      "read",
      `${entry.name} must be a registered read tool`,
    );
    const metadata = getAgentToolMetadata(entry.name);
    assert.ok(metadata, `${entry.name} metadata missing`);
    assert.equal(metadata?.idempotency, "read_only");
    assert.equal(metadata?.parallelSafe, true);
    assert.ok(isConnectorTool(entry.name));
    assert.ok(connectorToolContract(entry.name));
  }
});

test("unknown tools are not treated as connectors", () => {
  assert.equal(isConnectorTool("web.search"), false);
  assert.equal(connectorToolContract("web.search"), null);
});
