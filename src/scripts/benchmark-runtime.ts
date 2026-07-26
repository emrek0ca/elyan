export type BenchmarkRuntimeEnv = Record<string, string | undefined>;

export function configureBenchmarkRuntimeEnv(
  env: BenchmarkRuntimeEnv = process.env,
): { semanticComputeEnabled: boolean } {
  const semanticComputeEnabled =
    env.ELYAN_BENCHMARK_SEMANTIC_COMPUTE?.trim().toLowerCase() === "true";
  if (!semanticComputeEnabled) {
    env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = "false";
    env.ELYAN_RAG_SEMANTIC_RERANK_ENABLED = "false";
  }
  return { semanticComputeEnabled };
}
