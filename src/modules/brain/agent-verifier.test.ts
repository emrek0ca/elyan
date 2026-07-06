import assert from "node:assert/strict";
import test from "node:test";
import { buildAgentPlanFromToolRequests } from "./agent-plan.js";
import { canCompleteAgentRun, verifyAgentStep } from "./agent-verifier.js";

const step = buildAgentPlanFromToolRequests({
  goal: "Search",
  requests: [{ tool: "web.search", args: { query: "test" } }],
}).steps[0]!;

test("model completion claims are never accepted as verification evidence", () => {
  const verification = verifyAgentStep({
    step,
    evidence: [{ kind: "state_readback", payload: { modelClaim: "I completed it" }, valid: true }],
  });
  assert.equal(verification.passed, false);
  assert.deepEqual(verification.missing_evidence, ["tool_result:ok"]);
  assert.equal(canCompleteAgentRun([verification]), false);
});

test("schema-valid successful tool evidence passes deterministic verification", () => {
  const verification = verifyAgentStep({
    step,
    evidence: [{
      id: "11111111-1111-4111-8111-111111111111",
      kind: "tool_result",
      payload: { ok: true, output: { results: [{ title: "source" }] } },
      valid: true,
    }],
  });
  assert.equal(verification.passed, true);
  assert.equal(verification.confidence, 1);
  assert.equal(canCompleteAgentRun([verification]), true);
});

test("successful tool call with wrong expected outcome does not pass", () => {
  const strictStep = {
    ...step,
    expected_outcome: {
      description: "needs two sources",
      rules: [{ source: "tool_result" as const, path: "output.sourceCount", operator: "gte" as const, value: 2 }],
    },
  };
  const verification = verifyAgentStep({
    step: strictStep,
    evidence: [{ kind: "tool_result", payload: { ok: true, output: { sourceCount: 1 } }, valid: true }],
  });
  assert.equal(verification.passed, false);
  assert.equal(verification.failed_rules.length, 1);
});

test("artifact completion requires the declared content hash", () => {
  const artifactStep = {
    ...step,
    expected_outcome: {
      description: "artifact persisted",
      rules: [{ source: "artifact" as const, path: "", operator: "sha256" as const, value: "abc123" }],
    },
  };
  assert.equal(verifyAgentStep({
    step: artifactStep,
    evidence: [{ kind: "artifact", sourceRef: "artifact-1", contentHash: "wrong", payload: {}, valid: true }],
  }).passed, false);
  assert.equal(verifyAgentStep({
    step: artifactStep,
    evidence: [{ kind: "artifact", sourceRef: "artifact-1", contentHash: "abc123", payload: {}, valid: true }],
  }).passed, true);
});
