import assert from "node:assert/strict";
import test from "node:test";
import { assertGoalTransition, mergeGoalEngineState, readGoalEngineState } from "./state-machine.js";

test("goal state machine accepts forward work and rejects completed restarts", () => {
  assert.doesNotThrow(() => assertGoalTransition("open", "executing"));
  assert.doesNotThrow(() => assertGoalTransition("blocked", "planned"));
  assert.throws(() => assertGoalTransition("completed", "executing"), /invalid_goal_transition/);
});

test("goal engine state is stored additively inside progress", () => {
  const progress = mergeGoalEngineState({ completedSteps: ["one"] }, "waiting");
  assert.equal(readGoalEngineState(progress), "waiting");
  assert.deepEqual(progress.completedSteps, ["one"]);
});
