import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import {
  backfillSemanticV2Embeddings,
  fuseRetrievalCandidates,
  type RetrievalSearchResult,
} from "./retrieval.js";

function flattenSqlFragment(fragment: { queryChunks?: unknown[] }): string {
  return (fragment.queryChunks ?? [])
    .map((chunk) => {
      if (typeof chunk === "string") return chunk;
      if (chunk && typeof chunk === "object" && "value" in chunk) {
        const value = (chunk as { value?: unknown }).value;
        return Array.isArray(value) ? value.join("") : String(value ?? "");
      }
      return String(chunk);
    })
    .join("");
}

test("semantic v2 backfill ensures every vector column used by its query", async () => {
  const statements: string[] = [];
  let executeCount = 0;
  const app = {
    db: {
      execute: async (fragment: { queryChunks?: unknown[] }) => {
        executeCount += 1;
        statements.push(flattenSqlFragment(fragment));
        return executeCount === 1 ? [{ ready: true }] : [];
      },
      select: () => ({
        from: () => ({
          where: () => ({
            limit: async () => [],
          }),
        }),
      }),
    },
    log: {
      warn: () => undefined,
    },
  } as unknown as FastifyInstance;

  const result = await backfillSemanticV2Embeddings(app, { maxBatches: 1 });
  const schemaStatement = statements.find((statement) =>
    statement.includes("alter table knowledge_chunks"),
  );

  assert.equal(result.stopped, "complete");
  assert.match(schemaStatement ?? "", /embedding vector\(256\)/u);
  assert.match(schemaStatement ?? "", /embedding_v2 vector\(384\)/u);
});

function candidate(id: string, score: number): RetrievalSearchResult {
  return {
    documentId: `doc-${id}`,
    chunkId: id,
    title: id,
    scope: "user",
    sourceType: "note",
    sourceUri: null,
    summary: null,
    content: id,
    tokenEstimate: 1,
    ordinal: 0,
    metadata: {},
    score,
    updatedAt: new Date("2030-01-01T00:00:00.000Z"),
  };
}

test("hybrid and lexical candidates are fused by rank instead of raw score", () => {
  const semanticWinner = candidate("semantic", 0.81);
  const lexicalOnly = candidate("lexical", 9);
  const fused = fuseRetrievalCandidates([
    [semanticWinner, lexicalOnly],
    [semanticWinner],
  ]);

  assert.equal(fused[0]?.chunkId, "semantic");
  assert.ok((fused[0]?.score ?? 0) < 1);
});
