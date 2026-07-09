import assert from "node:assert/strict";
import test from "node:test";
import { BOUNDED_JSON_LIMITS, boundedJsonRecordSchema } from "./json-boundary.js";

test("boundedJsonRecordSchema accepts normal structured metadata", () => {
  const parsed = boundedJsonRecordSchema.safeParse({
    route: "server_brain",
    context: {
      topics: ["continuity", "memory"],
      enabled: true,
    },
  });

  assert.equal(parsed.success, true);
});

test("boundedJsonRecordSchema rejects oversized and deeply nested payloads", () => {
  const oversized = boundedJsonRecordSchema.safeParse({
    text: "x".repeat(BOUNDED_JSON_LIMITS.maxStringLength + 1),
  });
  assert.equal(oversized.success, false);

  let nested: Record<string, unknown> = { value: true };
  for (let index = 0; index <= BOUNDED_JSON_LIMITS.maxDepth; index += 1) {
    nested = { nested };
  }
  const deeplyNested = boundedJsonRecordSchema.safeParse(nested);
  assert.equal(deeplyNested.success, false);
});

test("boundedJsonRecordSchema rejects excessive array fanout", () => {
  const parsed = boundedJsonRecordSchema.safeParse({
    blocks: Array.from({ length: BOUNDED_JSON_LIMITS.maxItemsPerArray + 1 }, () => true),
  });
  assert.equal(parsed.success, false);
});

test("boundedJsonRecordSchema rejects unsafe object keys", () => {
  const parsed = boundedJsonRecordSchema.safeParse(
    JSON.parse('{"__proto__":{"polluted":true}}'),
  );
  assert.equal(parsed.success, false);
});
