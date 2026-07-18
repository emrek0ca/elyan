import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  buildGeminiWebSynthesisPromptBlock,
  type GeminiWebSynthesis,
} from "./gemini-web-synthesizer.js";

function synthesis(overrides: Partial<GeminiWebSynthesis> = {}): GeminiWebSynthesis {
  return {
    summary: "Merkez bankası politika faizini %40 seviyesinde sabit tuttu.",
    keyPoints: ["Faiz değişmedi", "Karar oybirliğiyle alındı"],
    citedSourceNumbers: [1, 3],
    evidenceSufficient: true,
    conflictNote: "",
    ...overrides,
  };
}

test("renders summary, key points and citations", () => {
  const block = buildGeminiWebSynthesisPromptBlock(synthesis());
  assert.ok(block);
  assert.ok(block.includes("WEB EVIDENCE DIGEST"));
  assert.ok(block.includes("%40"));
  assert.ok(block.includes("- Faiz değişmedi"));
  assert.ok(block.includes("Supported by sources: 1, 3"));
});

test("insufficient evidence emits an abstention guard", () => {
  const block = buildGeminiWebSynthesisPromptBlock(
    synthesis({ evidenceSufficient: false }),
  );
  assert.ok(block);
  assert.ok(block.includes("DIGEST GUARD"));
});

test("conflicting evidence is surfaced", () => {
  const block = buildGeminiWebSynthesisPromptBlock(
    synthesis({ conflictNote: "Kaynak 2 farklı bir oran veriyor." }),
  );
  assert.ok(block?.includes("Conflicting evidence: Kaynak 2"));
});

test("null synthesis and empty summary fall back to the raw block", () => {
  assert.equal(buildGeminiWebSynthesisPromptBlock(null), null);
  assert.equal(buildGeminiWebSynthesisPromptBlock(synthesis({ summary: "   " })), null);
});

test("digest never claims authority over the freshness guards", () => {
  const block = buildGeminiWebSynthesisPromptBlock(synthesis());
  assert.ok(block?.includes("never overrides the freshness and evidence guards"));
});
