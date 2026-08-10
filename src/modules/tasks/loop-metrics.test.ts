import test from "node:test";
import assert from "node:assert/strict";
import {
  assignLoopCredit,
  deriveLoopMetrics,
  deriveTerminationReason,
  readLoopSteps,
} from "./loop-metrics.js";

test("retry load is counted as extra attempts, not as steps", () => {
  // attemptCount sözleşmede en az 1; 1 = yeniden deneme YOK. Toplamı doğrudan
  // saymak her adımı bir retry gibi göstermiş olurdu.
  const metrics = deriveLoopMetrics({
    steps: [
      { status: "completed", capability: "file_read", attemptCount: 1, durationMs: 100 },
      { status: "completed", capability: "shell_run", attemptCount: 3, durationMs: 900 },
    ],
  });
  assert.equal(metrics.plannedStepCount, 2);
  assert.equal(metrics.executedStepCount, 2);
  assert.equal(metrics.retryCount, 2);
  assert.equal(metrics.totalDurationMs, 1_000);
  assert.equal(metrics.slowestCapability, "shell_run");
});

test("pending and skipped steps are planned but not executed", () => {
  const metrics = deriveLoopMetrics({
    steps: [
      { status: "completed", capability: "directory_tree" },
      { status: "pending", capability: "document_write" },
      { status: "skipped", capability: "web_research" },
    ],
  });
  assert.equal(metrics.plannedStepCount, 3);
  assert.equal(metrics.executedStepCount, 1);
});

test("repaired steps are visible instead of hiding inside success", () => {
  const metrics = deriveLoopMetrics({
    steps: [
      { status: "completed", verificationStatus: "repaired", attemptCount: 2 },
      { status: "completed", verificationStatus: "passed" },
    ],
  });
  assert.equal(metrics.repairedStepCount, 1);
  assert.equal(metrics.failedStepCount, 0);
  assert.equal(metrics.retryCount, 1);
});

test("a clean run without a goal verdict is not called goal_reached", () => {
  // "Hata yok" ile "hedef tuttu" karıştırılmaz — düzeltmeye çalıştığımız
  // asıl karışıklık buydu.
  assert.equal(
    deriveTerminationReason({
      plannedStepCount: 2,
      executedStepCount: 2,
      failedStepCount: 0,
    }),
    "unknown",
  );
  assert.equal(
    deriveTerminationReason({
      plannedStepCount: 2,
      executedStepCount: 2,
      failedStepCount: 0,
      goalVerdict: "met",
    }),
    "goal_reached",
  );
});

test("budget exhaustion is distinguished from failure", () => {
  assert.equal(
    deriveTerminationReason({
      plannedStepCount: 8,
      executedStepCount: 8,
      failedStepCount: 0,
      maxSteps: 8,
    }),
    "budget_exhausted",
  );
  assert.equal(
    deriveTerminationReason({
      plannedStepCount: 8,
      executedStepCount: 8,
      failedStepCount: 1,
      maxSteps: 8,
    }),
    "step_failure",
  );
  assert.equal(
    deriveTerminationReason({
      plannedStepCount: 0,
      executedStepCount: 0,
      failedStepCount: 0,
    }),
    "no_plan",
  );
});

test("credit points at the router guess when the failing step came from a hint", () => {
  // "Chrome u kapat" sınıfı: suçlu araç değil, o adımı plana koyan tahmin.
  const credit = assignLoopCredit({
    steps: [
      { status: "completed", capability: "open_app" },
      { status: "failed", capability: "desktop_operator.run", attemptCount: 2 },
    ],
    // İpucu noktalı, adım noktalı; farklı yazımlar da eşleşmeli.
    routerHints: ["desktop_operator_run"],
  });
  assert.equal(credit?.capability, "desktop_operator.run");
  assert.equal(credit?.origin, "router_hint");
  assert.equal(credit?.attempts, 2);
});

test("credit points at the planner when the failing step was its own choice", () => {
  const credit = assignLoopCredit({
    steps: [{ status: "failed", capability: "shell_run" }],
    routerHints: ["file_read"],
  });
  assert.equal(credit?.origin, "planner_choice");
});

test("a run without failures assigns no credit", () => {
  assert.equal(
    assignLoopCredit({
      steps: [{ status: "completed", capability: "file_read" }],
      routerHints: [],
    }),
    null,
  );
});

test("step reports are read from either the result or the dispatch widget", () => {
  assert.equal(readLoopSteps({ steps: [{ status: "completed" }] }).length, 1);
  assert.equal(
    readLoopSteps({ dispatchWidget: { steps: [{ status: "failed" }] } }).length,
    1,
  );
  assert.deepEqual(readLoopSteps(null), []);
  assert.deepEqual(readLoopSteps({ steps: "bozuk" }), []);
});
