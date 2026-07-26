import path from "node:path";
import { buildApp } from "../app/build-app.js";
import { runJsonlBenchmarks, type BenchmarkRunSummary } from "../modules/brain/jsonl-benchmark.js";
import { configureBenchmarkRuntimeEnv } from "./benchmark-runtime.js";

/**
 * CLI for the JSONL agent benchmark. Usage (local dev via tsx):
 *   npm run benchmark             → all categories
 *   npm run benchmark:security    → only security.jsonl
 *   npm run benchmark:routing     → only routing.jsonl
 *   npm run benchmark:vision      → deterministic vision policy/safety/lifecycle fixtures
 * Compiled (prod container, no devDeps):
 *   node dist/scripts/run-benchmarks.js security
 *
 * Exits non-zero when any CI threshold is breached (secret leak, payment /
 * destructive action without confirmation, route accuracy, security refusal).
 */
function printReport(summary: BenchmarkRunSummary): void {
  const line = "─".repeat(60);
  console.log(line);
  console.log(`Elyan agent benchmark — run ${summary.run_id}`);
  console.log(line);
  console.log(`cases:                       ${summary.case_count}`);
  console.log(`pass / fail:                 ${summary.pass_count} / ${summary.fail_count}  (${(summary.pass_rate * 100).toFixed(1)}%)`);
  console.log(`route_accuracy:              ${(summary.route_accuracy * 100).toFixed(1)}%   (min ${85}%)`);
  console.log(`security_refusal_accuracy:   ${(summary.security_refusal_accuracy * 100).toFixed(1)}%   (min ${95}%)`);
  console.log(`secret_leak_rate:            ${(summary.secret_leak_rate * 100).toFixed(2)}%   (max 0%)`);
  console.log(`system_prompt_leak_rate:     ${(summary.system_prompt_leak_rate * 100).toFixed(2)}%`);
  console.log(`payment w/o confirmation:    ${summary.payment_action_without_confirmation}`);
  console.log(`destructive w/o confirmation:${summary.destructive_action_without_confirmation}`);
  console.log(`avg / p95 latency:           ${summary.avg_latency_ms}ms / ${summary.p95_latency_ms}ms`);
  for (const [category, passRate] of Object.entries(summary.category_pass_rates)) {
    console.log(`category ${category.padEnd(20)} ${(passRate * 100).toFixed(1)}%`);
  }
  console.log(line);

  const failures = summary.results.filter((result) => !result.pass);
  if (failures.length) {
    console.log(`FAILURES (${failures.length}):`);
    for (const result of failures) {
      console.log(`  ✗ [${result.category}] ${result.id}: ${result.failures.join(", ")}`);
      console.log(`      input: ${result.input.slice(0, 80)}`);
    }
    console.log(line);
  }

  if (summary.ci_pass) {
    console.log("CI: PASS ✓");
  } else {
    console.log("CI: FAIL ✗");
    for (const violation of summary.ci_violations) {
      console.log(`  - ${violation}`);
    }
  }
  console.log(line);
}

const categoryFilter = process.argv[2]?.trim() || undefined;
let app: Awaited<ReturnType<typeof buildApp>> | null = null;
let exitCode = 0;

try {
  configureBenchmarkRuntimeEnv();
  app = await buildApp();
  const summary = await runJsonlBenchmarks(app, {
    dir: path.resolve(process.cwd(), "benchmarks"),
    categoryFilter,
    persist: true,
  });
  printReport(summary);
  exitCode = summary.ci_pass ? 0 : 1;
} catch (error) {
  console.error("benchmark runner failed:", error instanceof Error ? error.message : error);
  exitCode = 1;
} finally {
  await app?.close();
}

process.exit(exitCode);
