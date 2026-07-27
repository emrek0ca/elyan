import assert from "node:assert/strict";
import test from "node:test";
import {
  canonicalMemoryCacheKey,
  invalidateCanonicalMemoryCache,
  readCanonicalMemoryCache,
  writeCanonicalMemoryCache,
} from "./memory-context-cache.js";

test("canonical memory cache is tenant keyed, TTL bounded, and invalidatable", async () => {
  const values = new Map<string, string>();
  const ttls = new Map<string, number | undefined>();
  const app = {
    services: {
      reliability: {
        store: {
          async get(key: string) {
            return values.get(key) ?? null;
          },
          async set(key: string, value: string, ttlMs?: number) {
            values.set(key, value);
            ttls.set(key, ttlMs);
          },
          async del(key: string) {
            values.delete(key);
          },
        },
      },
    },
  };

  await writeCanonicalMemoryCache(app as never, "user-a", [{ key: "tone" }]);
  assert.deepEqual(await readCanonicalMemoryCache(app as never, "user-a"), [
    { key: "tone" },
  ]);
  assert.equal(ttls.get(canonicalMemoryCacheKey("user-a")), 20_000);

  await invalidateCanonicalMemoryCache(app as never, "user-a");
  assert.equal(await readCanonicalMemoryCache(app as never, "user-a"), undefined);
});
