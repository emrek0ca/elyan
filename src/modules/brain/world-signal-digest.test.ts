import assert from "node:assert/strict";
import test from "node:test";
import { getRecentWorldSignalDigest } from "./service.js";

function appWithRows(rows: Array<{ kind: string; summary: string }>) {
  const chain = {
    from: () => chain,
    where: () => chain,
    orderBy: () => chain,
    limit: async () => rows,
  };
  return {
    db: { select: () => chain },
    log: { debug: () => {} },
  } as never;
}

test("world signal digest never leaks sensitive summaries", async () => {
  const digest = await getRecentWorldSignalDigest(
    appWithRows([
      { kind: "health", summary: "kan basinci 150/95 ilac kullaniyor" },
      { kind: "location_precise", summary: "41.0082, 28.9784 ev adresi" },
      { kind: "location", summary: "Ofis" },
    ]),
    "user-1",
  );

  const health = digest.find((item) => item.kind === "health");
  const precise = digest.find((item) => item.kind === "location_precise");
  const coarse = digest.find((item) => item.kind === "location");

  // Hassas türler yalnız TÜR olarak bildirilir; özet metni taşınmaz.
  assert.ok(health && health.summary === undefined);
  assert.ok(precise && precise.summary === undefined);
  // Hassas olmayan sinyal özetiyle birlikte gelir (canlılık bundan doğar).
  assert.equal(coarse?.summary, "Ofis");

  const serialized = JSON.stringify(digest);
  assert.ok(!serialized.includes("150/95"));
  assert.ok(!serialized.includes("28.9784"));
});

test("world signal digest degrades to empty instead of throwing", async () => {
  const failing = {
    db: {
      select: () => {
        throw new Error("db down");
      },
    },
    log: { debug: () => {} },
  } as never;

  assert.deepEqual(await getRecentWorldSignalDigest(failing, "user-1"), []);
});

test("world signal digest bounds summary length", async () => {
  const digest = await getRecentWorldSignalDigest(
    appWithRows([{ kind: "calendar", summary: "x".repeat(400) }]),
    "user-1",
  );
  assert.ok((digest[0]?.summary?.length ?? 0) <= 160);
});
