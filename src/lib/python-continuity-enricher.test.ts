import assert from "node:assert/strict";
import test from "node:test";
import { buildContinuityEnrichmentBaseline } from "./python-continuity-enricher.js";

test("buildContinuityEnrichmentBaseline derives recurring topics and continuity style from safe user memory", () => {
  const result = buildContinuityEnrichmentBaseline({
    facts: [
      { key: "active_project", value: "backend auth pipeline", factType: "project_context" },
      { key: "stack", value: "fastify backend auth", factType: "technical_stack" },
      { key: "routing_mode", value: "preserve architecture", factType: "routing" },
    ],
    episodes: [
      { episodeType: "task_completed", summary: "Backend auth follow up is pending for the next step." },
      { episodeType: "session_recovered", summary: "Continue the same backend auth task tomorrow." },
    ],
  });

  assert.ok(result);
  assert.match(result?.recentTopics ?? "", /backend|auth/i);
  assert.match(result?.continuityStyle ?? "", /restat|carry|preserve/i);
  assert.match(result?.reasoningStyle ?? "", /architecture|stepwise/i);
  assert.equal(result?.source, "typescript_baseline");
});

test("buildContinuityEnrichmentBaseline returns null for empty weak input", () => {
  const result = buildContinuityEnrichmentBaseline({
    facts: [],
    episodes: [],
  });

  assert.equal(result, null);
});
