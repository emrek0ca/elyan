import assert from "node:assert/strict";
import test from "node:test";
import {
  getPerfSnapshot,
  recordStageDuration,
  resetPerfTelemetry,
  startPerfTelemetry,
  startStage,
  stopPerfTelemetry,
} from "./perf-telemetry.js";

test("perf: stage p50/p95 doğru hesaplanır", () => {
  resetPerfTelemetry();
  for (let i = 1; i <= 100; i++) {
    recordStageDuration("test_stage", i);
  }
  const snapshot = getPerfSnapshot();
  const stage = snapshot.stages.test_stage;
  assert.equal(stage.count, 100);
  assert.equal(stage.p50Ms, 50);
  assert.equal(stage.p95Ms, 95);
  assert.equal(stage.p99Ms, 99);
});

test("perf: startStage ölçer ve kaydeder", async () => {
  resetPerfTelemetry();
  const done = startStage("timed");
  await new Promise((resolve) => setTimeout(resolve, 15));
  done();
  const stage = getPerfSnapshot().stages.timed;
  assert.equal(stage.count, 1);
  assert.ok(stage.p50Ms >= 10, `beklenen >=10ms, ölçülen ${stage.p50Ms}`);
});

test("perf: event loop monitörü çalışır ve resetlenir", async () => {
  startPerfTelemetry();
  await new Promise((resolve) => setTimeout(resolve, 60));
  const snapshot = getPerfSnapshot({ resetLoop: true });
  assert.ok(snapshot.eventLoop);
  assert.ok(snapshot.eventLoop.p50Ms >= 0);
  stopPerfTelemetry();
});

test("perf: kardinalite 64 stage ile sınırlı", () => {
  resetPerfTelemetry();
  for (let i = 0; i < 100; i++) {
    recordStageDuration(`stage_${i}`, 1);
  }
  assert.ok(Object.keys(getPerfSnapshot().stages).length <= 64);
});

test("perf: negatif/NaN süre kaydedilmez", () => {
  resetPerfTelemetry();
  recordStageDuration("bad", -5);
  recordStageDuration("bad", Number.NaN);
  assert.equal(getPerfSnapshot().stages.bad, undefined);
});
