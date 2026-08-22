import assert from "node:assert/strict";
import test from "node:test";
import { assertAgentRunTransition, assertAgentStepTransition } from "./agent-state-machine.js";
import { isSideEffectApprovedForStep } from "./agent-engine.js";

test("agent run follows execute observe verify sequence", () => {
  assert.doesNotThrow(() => assertAgentRunTransition("ready", "executing"));
  assert.doesNotThrow(() => assertAgentRunTransition("executing", "observing"));
  assert.doesNotThrow(() => assertAgentRunTransition("observing", "verifying"));
  assert.doesNotThrow(() => assertAgentRunTransition("verifying", "completed"));
});

test("shadow projection can skip a step that legacy execution did not reach", () => {
  assert.doesNotThrow(() => assertAgentStepTransition("ready", "skipped"));
});

test("side-effect approval is scoped to one step", () => {
  assert.equal(isSideEffectApprovedForStep({ allowSideEffects: true, approvedStepId: "step-a", stepId: "step-a" }), true);
  assert.equal(isSideEffectApprovedForStep({ allowSideEffects: true, approvedStepId: "step-a", stepId: "step-b" }), false);
  assert.equal(isSideEffectApprovedForStep({ allowSideEffects: false, approvedStepId: "step-a", stepId: "step-a" }), false);
});

test("completed runs and verified steps are immutable", () => {
  assert.throws(() => assertAgentRunTransition("completed", "executing"), /invalid_agent_run_transition/);
  assert.throws(() => assertAgentStepTransition("verified", "ready"), /invalid_agent_step_transition/);
});
