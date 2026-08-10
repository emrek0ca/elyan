import test from "node:test";
import assert from "node:assert/strict";
import {
  bucketCount,
  composeSituationValue,
  isCounterShapedSignal,
  markTelemetryOnly,
} from "./learning-signal-quality.js";
import type { LearningSignal } from "./types.js";

function signal(overrides: Partial<LearningSignal> = {}): LearningSignal {
  return {
    type: "workflow",
    key: "task_completed",
    value: "completed",
    confidence: 0.7,
    scope: "user",
    source: "runtime",
    ttlDays: 30,
    ...overrides,
  };
}

test("a value the key already implies is recognised as a counter", () => {
  // Canlıda 1.642 satır / 1 farklı değer üretmişti: anahtar "task_completed",
  // değer "completed". Sinyal hiçbir şey öğretmiyor.
  assert.equal(isCounterShapedSignal("task_completed", "completed"), true);
  assert.equal(isCounterShapedSignal("task_not_completed", "not_completed"), true);
  assert.equal(isCounterShapedSignal("bridge_readiness", "true"), true);
  assert.equal(isCounterShapedSignal("routing_mode", ""), true);
});

test("a composite value that names a real situation is not a counter", () => {
  assert.equal(
    isCounterShapedSignal("goal_verification", "missed|declared_artifact_missing|close_app"),
    false,
  );
  assert.equal(
    isCounterShapedSignal("task_handoff_state", "desktop_runtime|failed|task"),
    false,
  );
});

test("situation values join the discriminating parts and drop the empty ones", () => {
  assert.equal(
    composeSituationValue(["missed", "declared_artifact_missing", "make_directory"]),
    "missed|declared_artifact_missing|make_directory",
  );
  assert.equal(composeSituationValue(["budget_exhausted", "", null, undefined]), "budget_exhausted");
  assert.equal(composeSituationValue([]), "");
  assert.equal(composeSituationValue(["  MET  ", "Ok"]), "met|ok");
});

test("situation values stay bounded so one long field cannot dominate", () => {
  const value = composeSituationValue([
    "x".repeat(500),
    "y".repeat(500),
    "z".repeat(500),
  ]);
  assert.ok(value.length <= 200, `değer sınırsız büyüdü: ${value.length}`);
});

test("counts are bucketed so raw numbers do not fragment the corpus", () => {
  // Ham sayı her adım farkında yeni satır üretir ve örüntüyü gizler.
  assert.equal(bucketCount(0), "0");
  assert.equal(bucketCount(1), "1");
  assert.equal(bucketCount(2), "2");
  assert.equal(bucketCount(4), "3-5");
  assert.equal(bucketCount(9), "6-10");
  assert.equal(bucketCount(47), "10+");
  assert.equal(bucketCount(Number.NaN), "0");
});

test("telemetry marking keeps the signal but removes it from training", () => {
  // Sinyal SİLİNMEZ: bağlam ve göstergeler okumayı sürdürür.
  const marked = markTelemetryOnly(signal({ metadata: { route: "desktop" } }));
  assert.equal(marked.key, "task_completed");
  assert.equal(marked.value, "completed");
  assert.equal(marked.metadata?.route, "desktop");
  assert.equal(marked.metadata?.trainingEligible, false);
  assert.equal(marked.metadata?.telemetryOnly, true);
});

test("telemetry marking does not mutate the original signal", () => {
  const original = signal();
  markTelemetryOnly(original);
  assert.equal(original.metadata, undefined);
});
