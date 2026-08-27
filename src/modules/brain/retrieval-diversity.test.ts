import assert from "node:assert/strict";
import test from "node:test";
import { selectDiverseResults } from "./retrieval-orchestrator.js";
import type { RetrievalSearchResult } from "./retrieval.js";

function chunk(
  id: string,
  content: string,
  score: number,
): RetrievalSearchResult {
  return {
    documentId: `doc-${id}`,
    chunkId: id,
    title: `Belge ${id}`,
    scope: "user",
    sourceType: "note",
    sourceUri: null,
    summary: null,
    content,
    tokenEstimate: content.length,
    ordinal: 0,
    metadata: {},
    score,
    updatedAt: new Date("2030-01-01T00:00:00.000Z"),
  };
}

const solarContent =
  "Güneş enerjisi panelleri fotovoltaik hücrelerle elektrik üretir ve şebekeye bağlanır.";
const windContent =
  "Rüzgâr türbinleri kanat açısını değiştirerek düşük hızlarda da tork üretir.";
const hydroContent =
  "Hidroelektrik santraller su seviyesi farkını türbin miline aktarır.";

test("near-identical chunks do not each claim a slot in the context window", () => {
  const { selected, suppressedDuplicates } = selectDiverseResults(
    [
      chunk("a", solarContent, 1),
      // Aynı paragrafın komşu chunk kopyası: yeni bilgi taşımıyor.
      chunk("a-copy", `${solarContent} `, 0.98),
      chunk("b", windContent, 0.9),
      chunk("c", hydroContent, 0.8),
    ],
    3,
  );

  assert.equal(suppressedDuplicates, 1);
  assert.deepEqual(
    selected.map((item) => item.chunkId),
    ["a", "b", "c"],
  );
});

test("the most relevant result always keeps the first slot", () => {
  const { selected } = selectDiverseResults(
    [chunk("a", solarContent, 1), chunk("b", windContent, 0.2)],
    2,
  );
  assert.equal(selected[0]?.chunkId, "a");
  assert.equal(selected.length, 2);
});

test("diversity selection is a no-op on trivial inputs", () => {
  assert.deepEqual(selectDiverseResults([], 5).selected, []);
  assert.equal(selectDiverseResults([chunk("a", solarContent, 1)], 5).selected.length, 1);
  assert.deepEqual(selectDiverseResults([chunk("a", solarContent, 1)], 0).selected, []);
});

test("a limit smaller than the candidate list still returns distinct sources", () => {
  const { selected } = selectDiverseResults(
    [
      chunk("a", solarContent, 1),
      chunk("b", windContent, 0.9),
      chunk("c", hydroContent, 0.85),
    ],
    2,
  );
  assert.equal(selected.length, 2);
  assert.equal(new Set(selected.map((item) => item.chunkId)).size, 2);
});
