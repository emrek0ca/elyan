import assert from "node:assert/strict";
import test from "node:test";
import {
  embedTextsWithSemanticWorker,
  isSemanticComputeWorkerUnavailable,
  resetSemanticComputeWorkerForTests,
} from "./semantic-compute-client.js";
import { rerankSemanticCandidates } from "./semantic-rerank.js";

test("semantic compute client fails closed when the worker is disabled", async () => {
  const previous = process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED;
  process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = "false";
  resetSemanticComputeWorkerForTests();

  const vectors = await embedTextsWithSemanticWorker({
    modelName: "Xenova/multilingual-e5-small",
    texts: ["query: test"],
  });

  assert.equal(vectors, null);
  assert.equal(isSemanticComputeWorkerUnavailable(), true);

  if (previous === undefined) {
    delete process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED;
  } else {
    process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = previous;
  }
  resetSemanticComputeWorkerForTests();
});

test("semantic rerank falls back to original order when worker compute is unavailable", async () => {
  const previous = process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED;
  process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = "false";
  resetSemanticComputeWorkerForTests();

  const candidates = [
    { title: "First", content: "First candidate.", score: 0.9 },
    { title: "Second", content: "Second candidate.", score: 0.8 },
  ];
  const warnings: unknown[] = [];

  const result = await rerankSemanticCandidates({
    query: "Anything",
    candidates,
    enabled: true,
    logger: {
      warn(value: unknown) {
        warnings.push(value);
      },
      debug() {},
    },
  });

  assert.equal(result.used, false);
  assert.equal(result.degradedReason, "semantic_rerank_embeddings_unavailable");
  assert.deepEqual(result.results, candidates);
  assert.equal(warnings.length > 0, true);

  if (previous === undefined) {
    delete process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED;
  } else {
    process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = previous;
  }
  resetSemanticComputeWorkerForTests();
});
