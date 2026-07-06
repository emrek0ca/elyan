import assert from "node:assert/strict";
import test from "node:test";
import { agentPlanEnvelopeSchema, buildAgentPlanFromToolRequests, hardenAgentPlanVerification } from "./agent-plan.js";

test("agent plan creates a bounded typed DAG from tool requests", () => {
  const plan = buildAgentPlanFromToolRequests({
    goal: "Research and remember",
    requests: [
      { tool: "web.search", args: { query: "Elyan" } },
      { tool: "memory.write", args: { key: "topic", value: "Elyan" } },
    ],
  });
  assert.equal(plan.version, "agent_plan.v2");
  assert.equal(plan.steps.length, 2);
  assert.equal(plan.steps[0]?.expected_outcome.rules[0]?.path, "ok");
});

test("server hardens model verification rules for state writes", () => {
  const plan = agentPlanEnvelopeSchema.parse({
    version: "agent_plan.v2",
    goal: { title: "Remember", success_criteria: ["stored"] },
    steps: [{
      id: "write", title: "Write", depends_on: [],
      tool_request: { tool: "memory.write", args: { key: "x", value: "y", kind: "fact" } },
      expected_outcome: { description: "model supplied weak rule", rules: [{ source: "tool_result", path: "output.processed", operator: "gte", value: 0 }] },
      max_attempts: 3,
    }],
  });
  const hardened = hardenAgentPlanVerification(plan);
  assert.equal(hardened.steps[0]?.expected_outcome.rules.some((rule) => rule.path === "ok" && rule.value === true), true);
  assert.equal(hardened.steps[0]?.expected_outcome.rules.some((rule) => rule.source === "state_readback"), true);
});

test("agent plan rejects forward dependencies and duplicate ids", () => {
  const parsed = agentPlanEnvelopeSchema.safeParse({
    version: "agent_plan.v2",
    goal: { title: "Invalid", success_criteria: ["done"] },
    steps: [
      { id: "same", title: "A", depends_on: ["later"], tool_request: { tool: "web.search", args: {} }, expected_outcome: { description: "ok", rules: [{ source: "tool_result", path: "ok", operator: "equals", value: true }] } },
      { id: "same", title: "B", depends_on: [], tool_request: { tool: "web.search", args: {} }, expected_outcome: { description: "ok", rules: [{ source: "tool_result", path: "ok", operator: "equals", value: true }] } },
    ],
  });
  assert.equal(parsed.success, false);
});
