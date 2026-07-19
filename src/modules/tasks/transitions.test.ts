import assert from "node:assert/strict";
import test from "node:test";
import { assertTaskTransition, isTerminalTaskStatus } from "./transitions.js";

test("assertTaskTransition allows active task progressions", () => {
  assert.doesNotThrow(() => assertTaskTransition("queued", "planning"));
  assert.doesNotThrow(() => assertTaskTransition("waiting_approval", "running"));
  assert.doesNotThrow(() => assertTaskTransition("running", "completed"));
});

test("assertTaskTransition accepts late honest terminal from requeued task", () => {
  // Görev lease/stale süpürücüsüyle queued'a döndükten sonra masaüstü runtime
  // yürütmeyi bitirip geç terminal gönderebilir; sonuç kaybolmamalı.
  assert.doesNotThrow(() => assertTaskTransition("queued", "completed"));
  assert.doesNotThrow(() => assertTaskTransition("queued", "failed"));
});

test("assertTaskTransition rejects invalid terminal transitions", () => {
  assert.throws(() => assertTaskTransition("completed", "running"), /cannot move/i);
  assert.throws(() => assertTaskTransition("failed", "planning"), /cannot move/i);
  assert.throws(() => assertTaskTransition("completed", "queued"), /cannot move/i);
  assert.throws(() => assertTaskTransition("canceled", "completed"), /cannot move/i);
});

test("isTerminalTaskStatus reports terminal states correctly", () => {
  assert.equal(isTerminalTaskStatus("completed"), true);
  assert.equal(isTerminalTaskStatus("failed"), true);
  assert.equal(isTerminalTaskStatus("canceled"), true);
  assert.equal(isTerminalTaskStatus("running"), false);
});
