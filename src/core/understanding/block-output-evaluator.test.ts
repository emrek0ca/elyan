import assert from "node:assert/strict";
import test from "node:test";
import { evaluateBlockOutputPolicyFixtures } from "./block-output-evaluator.js";

test("block output evaluator reports deploy-ready quality score for fixture set", async () => {
  const summary = await evaluateBlockOutputPolicyFixtures();

  assert.equal(summary.fixtureCount, 55);
  assert.equal(summary.ciPass, true, summary.ciViolations.join("\n"));
  assert.equal(summary.routeAccuracy, 1);
  assert.equal(summary.shapeAccuracy, 1);
  assert.ok(summary.schemaValidRate >= 0.95);
  assert.equal(summary.duplicateTableRate, 0);
  assert.equal(summary.rawJsonLeakRate, 0);
  assert.ok(summary.averageQualityScore >= 95);
});
