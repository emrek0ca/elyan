import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  extractFirstJsonObject,
  validateDesktopPlanPayload,
} from "./desktop-plan.js";

const parityFixture = JSON.parse(
  readFileSync(new URL("./fixtures/elyan-contract-parity.json", import.meta.url), "utf8"),
) as {
  validPlan: Record<string, unknown>;
  compiledTaskContract: Record<string, unknown>;
  invalidDecisionShape: Record<string, unknown>;
};

test("extractFirstJsonObject prefers the compiled plan after model reasoning", () => {
  const output = [
    '<think>{"draft":"not a plan"}</think>',
    '{"contract":"elyan.plan.v2","steps":[{"id":"close","capability":"close_app","args":{"app_name":"Chrome"}}]}',
  ].join("\n");

  assert.deepEqual(extractFirstJsonObject(output), {
    contract: "elyan.plan.v2",
    steps: [
      {
        id: "close",
        capability: "close_app",
        args: { app_name: "Chrome" },
      },
    ],
  });
});

test("extractFirstJsonObject keeps backward-compatible first-object fallback", () => {
  assert.deepEqual(extractFirstJsonObject('prefix {"ok":true} suffix'), {
    ok: true,
  });
  assert.equal(extractFirstJsonObject("no json"), null);
});

test("extractFirstJsonObject selects the final plan when reasoning contains a draft plan", () => {
  const output = [
    '<think>{"contract":"elyan.plan.v2","steps":[{"id":"draft","capability":"shell_run","args":{}}]}</think>',
    '{"steps":[{"id":"final","capability":"directory_tree","args":{"path":"~/Desktop"}}]}',
  ].join("\n");

  assert.deepEqual(extractFirstJsonObject(output), {
    steps: [
      {
        id: "final",
        capability: "directory_tree",
        args: { path: "~/Desktop" },
      },
    ],
  });
});

test("validateDesktopPlanPayload accepts the shared plan.v2 fixture and keeps its revision", () => {
  const result = validateDesktopPlanPayload(parityFixture.validPlan, {
    taskId: "task_parity",
  });

  assert.equal(result.error, undefined);
  assert.equal(result.plan?.contract, "elyan.plan.v2");
  assert.equal(result.plan?.taskId, "task_parity");
  assert.equal(result.plan?.planRevision, 3);
  assert.deepEqual(
    (result.plan?.steps as Array<Record<string, unknown>>).map((step) => ({
      id: step.id,
      capability: step.capability,
      dependsOn: step.dependsOn ?? [],
    })),
    [
      { id: "research", capability: "web_research", dependsOn: [] },
      { id: "write", capability: "document_write", dependsOn: ["research"] },
    ],
  );
});

test("validateDesktopPlanPayload rejects a contract mismatch and malformed materialized steps", () => {
  assert.equal(
    validateDesktopPlanPayload(parityFixture.compiledTaskContract).error,
    "plan_contract_invalid",
  );

  const unknownCapability = {
    ...parityFixture.validPlan,
    steps: [
      {
        id: "unknown",
        capability: "not_registered",
        args: {},
      },
    ],
  };
  assert.equal(
    validateDesktopPlanPayload(unknownCapability).error,
    "plan_schema_invalid:unknown: capability not_registered is not in the desktop manifest",
  );

  const dependencyOutOfOrder = {
    ...parityFixture.validPlan,
    steps: [
      parityFixture.validPlan.steps instanceof Array
        ? (parityFixture.validPlan.steps[1] as Record<string, unknown>)
        : {},
      parityFixture.validPlan.steps instanceof Array
        ? (parityFixture.validPlan.steps[0] as Record<string, unknown>)
        : {},
    ],
  };
  assert.match(
    validateDesktopPlanPayload(dependencyOutOfOrder).error ?? "",
    /dependsOn must reference an earlier step/,
  );
});

test("validateDesktopPlanPayload preserves an explicit clarification without inventing a tool step", () => {
  const result = validateDesktopPlanPayload({
    contract: "elyan.plan.v2",
    planRevision: 4,
    clarification: {
      needed: true,
      question: "Hangi klasöre kaydedeyim?",
    },
    steps: [],
  });

  assert.equal(result.error, undefined);
  assert.deepEqual(result.plan?.steps, []);
  assert.deepEqual(result.plan?.clarification, {
    needed: true,
    question: "Hangi klasöre kaydedeyim?",
  });
});

test("the shared task contract is an execution input, never an agent decision", () => {
  assert.equal(parityFixture.compiledTaskContract.contract, "elyan.task_execution_contract.v2");
  assert.equal(parityFixture.invalidDecisionShape.contract, "elyan.plan.v2");
  assert.equal(typeof parityFixture.compiledTaskContract.execution, "object");
});
