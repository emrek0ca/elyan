import assert from "node:assert/strict";
import test, { beforeEach } from "node:test";
import {
  cachedKnowledge,
  knowledgeQueryDigest,
  resetKnowledgeCacheForTests,
  singleFlight,
} from "./knowledge-cache.js";

beforeEach(() => {
  resetKnowledgeCacheForTests();
});

test("the same query text reaches the same key regardless of spelling noise", () => {
  assert.equal(
    knowledgeQueryDigest("Dolar kaç TL?"),
    knowledgeQueryDigest("  dolar   kac  tl? "),
  );
  assert.notEqual(knowledgeQueryDigest("Dolar kaç TL?"), knowledgeQueryDigest("Euro kaç TL?"));
});

test("concurrent identical work runs once", async () => {
  let calls = 0;
  const load = async () => {
    calls += 1;
    await new Promise((resolve) => setTimeout(resolve, 10));
    return calls;
  };
  const [a, b, c] = await Promise.all([
    singleFlight("k", load),
    singleFlight("k", load),
    singleFlight("k", load),
  ]);
  assert.equal(calls, 1);
  assert.deepEqual([a, b, c], [1, 1, 1]);
});

test("a settled flight releases its key so later work can run", async () => {
  let calls = 0;
  const load = async () => {
    calls += 1;
    return calls;
  };
  await singleFlight("k", load);
  await singleFlight("k", load);
  assert.equal(calls, 2);
});

test("a failed flight is not cached and does not poison the key", async () => {
  let calls = 0;
  await assert.rejects(
    singleFlight("k", async () => {
      calls += 1;
      throw new Error("boom");
    }),
  );
  assert.equal(await singleFlight("k", async () => "recovered"), "recovered");
  assert.equal(calls, 1);
});

test("cached values are reused until the ttl expires", async () => {
  let calls = 0;
  const read = () =>
    cachedKnowledge(null, {
      key: "selection",
      ttlMs: 50,
      load: async () => {
        calls += 1;
        return { value: calls };
      },
    });
  assert.deepEqual(await read(), { value: 1 });
  assert.deepEqual(await read(), { value: 1 });
  assert.equal(calls, 1);
  await new Promise((resolve) => setTimeout(resolve, 60));
  assert.deepEqual(await read(), { value: 2 });
});

test("a value the caller rejects is returned but never stored", async () => {
  let calls = 0;
  const read = () =>
    cachedKnowledge(null, {
      key: "selection",
      ttlMs: 60_000,
      cacheable: (value: { ids: string[] }) => value.ids.length > 0,
      load: async () => {
        calls += 1;
        return { ids: calls > 1 ? ["fx"] : [] };
      },
    });
  assert.deepEqual(await read(), { ids: [] });
  assert.deepEqual(await read(), { ids: ["fx"] });
  assert.deepEqual(await read(), { ids: ["fx"] });
  assert.equal(calls, 2);
});
