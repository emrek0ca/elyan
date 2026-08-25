import assert from "node:assert/strict";
import test from "node:test";
import {
  buildMcpCapabilityIndex,
  collectStoredMcpTools,
  mcpToolManifestEntry,
} from "./mcp-capability-bridge.js";

const server = (overrides: Record<string, unknown> = {}) => ({
  status: "connected",
  metadata: {
    probe: {
      tools: [
        {
          capabilityId: "mcp:google_calendar:list_events",
          toolName: "list_events",
          sideEffectClass: "read",
          riskClass: "low",
          requiresApproval: false,
        },
        {
          capabilityId: "mcp:google_calendar:create_event",
          toolName: "create_event",
          sideEffectClass: "write",
          riskClass: "elevated",
          requiresApproval: true,
        },
      ],
    },
  },
  ...overrides,
});

test("yoklanmış araçlar derleyici kataloğuna girer", () => {
  const tools = collectStoredMcpTools([server()]);
  assert.equal(tools.length, 2);
  assert.equal(tools[0].capabilityId, "mcp:google_calendar:list_events");
  assert.equal(tools[1].requiresApproval, true);
});

test("KAPATILMIŞ sunucunun araçları görünmez", () => {
  // Kullanıcının kapattığı bir sunucunun aracı planlanabilir olmamalı.
  assert.deepEqual(collectStoredMcpTools([server({ status: "revoked" })]), []);
});

test("yoklanmamış sunucu araç üretmez", () => {
  assert.deepEqual(collectStoredMcpTools([{ status: "configured", metadata: {} }]), []);
  assert.deepEqual(collectStoredMcpTools(null), []);
});

test("aynı araç iki sunucuda ilan edilse tek kayıt olur", () => {
  assert.equal(collectStoredMcpTools([server(), server()]).length, 2);
});

test("MCP olmayan ad kataloga giremez", () => {
  const tools = collectStoredMcpTools([
    {
      status: "connected",
      metadata: { probe: { tools: [{ capabilityId: "desktop_operator.run" }] } },
    },
  ]);
  assert.deepEqual(tools, []);
});

test("SINIF BİLİNMİYORSA araç onay ister ve yazıcı sayılır", () => {
  // Bilinmeyen bir aracı salt-okuma saymak, kullanıcının görmediği bir yan
  // etkiye kapı açmaktır.
  const entry = mcpToolManifestEntry({ capabilityId: "mcp:x:y" });
  assert.equal(entry.requiresApproval, true);
  assert.equal(entry.sideEffectClass, "write");
  assert.equal(entry.mutatesPath, false);
});

test("indeks capability adıyla sorgulanabilir", () => {
  const index = buildMcpCapabilityIndex(collectStoredMcpTools([server()]));
  assert.equal(index.get("mcp:google_calendar:list_events")?.requiresApproval, false);
  assert.equal(index.get("mcp:google_calendar:create_event")?.sideEffectClass, "write");
  assert.equal(index.get("yok"), undefined);
});
