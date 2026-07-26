import assert from "node:assert/strict";
import test from "node:test";
import { configureBenchmarkRuntimeEnv } from "./benchmark-runtime.js";

test("benchmark runtime disables semantic compute by default", () => {
  const env: Record<string, string | undefined> = {};

  const result = configureBenchmarkRuntimeEnv(env);

  assert.equal(result.semanticComputeEnabled, false);
  assert.equal(env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED, "false");
  assert.equal(env.ELYAN_RAG_SEMANTIC_RERANK_ENABLED, "false");
});

test("benchmark runtime preserves semantic settings behind explicit opt-in", () => {
  const env: Record<string, string | undefined> = {
    ELYAN_BENCHMARK_SEMANTIC_COMPUTE: "true",
    ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED: "true",
    ELYAN_RAG_SEMANTIC_RERANK_ENABLED: "true",
  };

  const result = configureBenchmarkRuntimeEnv(env);

  assert.equal(result.semanticComputeEnabled, true);
  assert.equal(env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED, "true");
  assert.equal(env.ELYAN_RAG_SEMANTIC_RERANK_ENABLED, "true");
});
