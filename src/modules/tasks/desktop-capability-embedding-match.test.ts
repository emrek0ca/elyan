import assert from "node:assert/strict";
import test from "node:test";
import {
  matchDesktopCapabilitiesWithEmbeddings,
  refineDesktopCapabilityHints,
  resetDesktopCapabilityVectorsForTests,
} from "./desktop-capability-embedding-match.js";
import { mcpToolManifestEntry } from "./mcp-capability-bridge.js";
import { setMcpCapabilityIndex } from "./task-execution-contract.js";

test("cold-start refinement uses measured lexical evidence while vectors warm", async () => {
  resetDesktopCapabilityVectorsForTests();
  try {
    const refined = await refineDesktopCapabilityHints({
      query: "Masaüstünde hangi klasörler var?",
      capabilities: ["desktop.runtime"],
      intent: "automate",
      sideEffectLevel: "read",
      allowExpansion: true,
    });

    assert.deepEqual(refined, ["directory_tree", "desktop.runtime"]);
  } finally {
    resetDesktopCapabilityVectorsForTests();
  }
});

test("cold-start refinement cannot expand a closed structured capability set", async () => {
  resetDesktopCapabilityVectorsForTests();
  try {
    const refined = await refineDesktopCapabilityHints({
      query: "Masaüstünde hangi klasörler var?",
      capabilities: ["desktop.runtime"],
      intent: "automate",
      sideEffectLevel: "read",
      allowExpansion: false,
    });

    assert.deepEqual(refined, ["desktop.runtime"]);
  } finally {
    resetDesktopCapabilityVectorsForTests();
  }
});

test("cold-start refinement cannot expand capabilities excluded from degraded fallback", async () => {
  resetDesktopCapabilityVectorsForTests();
  try {
    for (const query of ["ekranı kapat", "pdf nedir açıkla"]) {
      const refined = await refineDesktopCapabilityHints({
        query,
        capabilities: [],
        allowExpansion: true,
      });
      assert.deepEqual(refined, [], query);
    }
  } finally {
    resetDesktopCapabilityVectorsForTests();
  }
});

test("connected MCP tools participate in the canonical cold-start ranker", async () => {
  resetDesktopCapabilityVectorsForTests();
  setMcpCapabilityIndex(new Map([
    [
      "mcp:notion:create-pages",
      mcpToolManifestEntry({
        capabilityId: "mcp:notion:create-pages",
        serverName: "Notion",
        toolName: "create-pages",
        description: "Notion'da yeni sayfa oluşturur.",
        sideEffectClass: "write",
        requiresApproval: true,
      }),
    ],
  ]));
  try {
    const ranked = await matchDesktopCapabilitiesWithEmbeddings({
      query: "Notion create pages",
      limit: 3,
    });
    assert.equal(ranked[0]?.capability, "mcp:notion:create-pages");
  } finally {
    setMcpCapabilityIndex(new Map());
    resetDesktopCapabilityVectorsForTests();
  }
});
