import assert from "node:assert/strict";
import test from "node:test";
import { rerankSemanticCandidates } from "./semantic-rerank.js";

test("rerankSemanticCandidates promotes semantically closer results over lexical distractors", async () => {
  const result = await rerankSemanticCandidates({
    query: "OpenAI API anahtarı nasıl kullanılır",
    candidates: [
      {
        title: "Billing settings",
        content: "Invoice management and subscription limits.",
        score: 0.71,
      },
      {
        title: "OpenAI API key setup",
        content: "How to configure an OpenAI API key securely.",
        score: 0.69,
      },
      {
        title: "Device pairing",
        content: "Pair a mobile device with the desktop runtime.",
        score: 0.33,
      },
    ],
    enabled: true,
    windowSize: 3,
    embedder: {
      async embedBatch(texts: string[]) {
        return texts.map((text) => {
          if (text.includes("OpenAI API anahtarı")) {
            return [1, 0];
          }
          if (text.includes("OpenAI API key setup")) {
            return [0.95, 0.05];
          }
          if (text.includes("Billing settings")) {
            return [0.12, 0.88];
          }
          return [0.15, 0.85];
        });
      },
    },
  });

  assert.equal(result.used, true);
  assert.equal(result.degradedReason, null);
  assert.equal(result.results[0]?.title, "OpenAI API key setup");
});

test("rerankSemanticCandidates keeps the original order when reranking is disabled", async () => {
  const candidates = [
    {
      title: "First",
      content: "First candidate.",
      score: 0.9,
    },
    {
      title: "Second",
      content: "Second candidate.",
      score: 0.8,
    },
  ];

  const result = await rerankSemanticCandidates({
    query: "Anything",
    candidates,
    enabled: false,
  });

  assert.equal(result.used, false);
  assert.deepEqual(result.results, candidates);
});
