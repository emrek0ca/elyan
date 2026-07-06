import assert from "node:assert/strict";
import test from "node:test";
import { proceduralMemoryCandidateSchema } from "./procedural-memory-contract.js";

test("procedural memory contract accepts inert draft candidates", () => {
  const parsed = proceduralMemoryCandidateSchema.parse({
    version: "procedural_memory_candidate.v1",
    id: "11111111-1111-4111-8111-111111111111",
    ownerUserId: null,
    capability: "document.export",
    trigger: { intent: "document_generate", requiredInputs: ["content"] },
    steps: [{
      ordinal: 0,
      capability: "document.render",
      inputBindings: { content: "request.content" },
      expectedOutput: { artifact: true },
    }],
    evidenceTraceIds: [],
    status: "draft",
    createdAt: "2026-07-05T12:00:00.000Z",
  });

  assert.equal(parsed.status, "draft");
  assert.equal(parsed.steps.length, 1);
});

test("procedural memory contract rejects active candidates", () => {
  assert.equal(proceduralMemoryCandidateSchema.safeParse({
    version: "procedural_memory_candidate.v1",
    id: "11111111-1111-4111-8111-111111111111",
    ownerUserId: null,
    capability: "document.export",
    trigger: { intent: "document_generate", requiredInputs: ["content"] },
    steps: [{
      ordinal: 0,
      capability: "document.render",
      inputBindings: {},
      expectedOutput: {},
    }],
    evidenceTraceIds: [],
    status: "active",
    createdAt: "2026-07-05T12:00:00.000Z",
  }).success, false);
});
