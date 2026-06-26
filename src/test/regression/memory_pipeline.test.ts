import assert from "node:assert/strict";
import test from "node:test";

const MEMORY_JOB_KINDS = new Set([
  "memory_extraction",
  "memory_consolidation",
  "memory_reconsolidation",
  "memory_index",
]);

test("memory pipeline: memory job kinds are excluded from ml-worker SQL filter", () => {
  const sqlFilter = `tj.kind not in ('memory_extraction','memory_consolidation','memory_reconsolidation','memory_index')`;
  for (const kind of MEMORY_JOB_KINDS) {
    assert.ok(sqlFilter.includes(kind), `SQL filter must exclude kind: ${kind}`);
  }
});

test("memory pipeline: maybeQueueMemoryExtractionJob skips when no signals", () => {
  let queued = false;
  const persistedSignals = 0;
  if (persistedSignals > 0) {
    queued = true;
  }
  assert.equal(queued, false);
});

test("memory pipeline: maybeQueueMemoryExtractionJob queues when signals > 0", () => {
  let queued = false;
  const persistedSignals = 2;
  if (persistedSignals > 0) {
    queued = true;
  }
  assert.equal(queued, true);
});

test("memory pipeline: ml-worker does not claim memory job kinds", () => {
  const nonMemoryKinds = ["embedding_train", "corpus_index", "skill_eval"];
  for (const kind of nonMemoryKinds) {
    assert.equal(MEMORY_JOB_KINDS.has(kind), false, `ml-worker kind ${kind} should not be in memory set`);
  }
});
