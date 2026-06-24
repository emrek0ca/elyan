import { buildApp } from "../../app/build-app.js";
import { runBrainBenchmark } from "./benchmark.js";

let app: Awaited<ReturnType<typeof buildApp>> | null = null;

try {
  app = await buildApp();
  const result = await runBrainBenchmark(app, {
    persistSummary: true,
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.log(
    JSON.stringify(
      {
        status: "warn",
        constitution_version: "2026-06-05.eval-first.v1",
        overall_score: 0,
        boundary_score: 0,
        reasoning_score: 0,
        clarification_score: 0,
        tool_use_score: 0,
        latency_score: 0,
        case_count: 0,
        live_model_case_count: 0,
        cases: [],
        runner_error: error instanceof Error ? error.message : "benchmark_runner_failed",
      },
      null,
      2,
    ),
  );
} finally {
  await app?.close();
}
