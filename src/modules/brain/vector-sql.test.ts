import assert from "node:assert/strict";
import test from "node:test";
import { buildVectorSql as buildMemoryVectorSql } from "./memory.js";
import { buildVectorSql as buildRetrievalVectorSql } from "./retrieval.js";

function flattenSqlFragment(fragment: { queryChunks: unknown[] }): string {
  return fragment.queryChunks
    .map((chunk) => {
      if (typeof chunk === "string") {
        return chunk;
      }
      if (chunk && typeof chunk === "object" && "value" in chunk) {
        const value = (chunk as { value?: unknown }).value;
        return Array.isArray(value) ? value.join("") : String(value ?? "");
      }
      return String(chunk);
    })
    .join("");
}

test("buildVectorSql binds pgvector literals instead of inlining raw strings", () => {
  const retrievalFragment = buildRetrievalVectorSql([0.1, 0.2, 0.3]);
  const memoryFragment = buildMemoryVectorSql([0.4, 0.5, 0.6]);

  assert.equal(flattenSqlFragment(retrievalFragment), "[0.1,0.2,0.3]::vector");
  assert.equal(flattenSqlFragment(memoryFragment), "[0.4,0.5,0.6]::vector");
  assert.equal(retrievalFragment.queryChunks.length, 3);
  assert.equal(memoryFragment.queryChunks.length, 3);
});
