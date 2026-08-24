import assert from "node:assert/strict";
import test from "node:test";
import {
  refineDesktopCapabilityHints,
  resetDesktopCapabilityVectorsForTests,
} from "./desktop-capability-embedding-match.js";

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
