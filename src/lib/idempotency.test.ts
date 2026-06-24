import assert from "node:assert/strict";
import test from "node:test";
import { createIdempotencyFingerprint, getIdempotencyKey } from "./idempotency.js";

test("createIdempotencyFingerprint is stable across object key order", () => {
  const left = createIdempotencyFingerprint({
    planCode: "pro",
    payload: {
      prompt: "hello",
      metadata: {
        alpha: 1,
        beta: 2,
      },
    },
  });
  const right = createIdempotencyFingerprint({
    payload: {
      metadata: {
        beta: 2,
        alpha: 1,
      },
      prompt: "hello",
    },
    planCode: "pro",
  });

  assert.equal(left, right);
});

test("createIdempotencyFingerprint keeps array order significant", () => {
  const left = createIdempotencyFingerprint({
    requestedCapabilities: ["browser", "filesystem"],
  });
  const right = createIdempotencyFingerprint({
    requestedCapabilities: ["filesystem", "browser"],
  });

  assert.notEqual(left, right);
});

test("getIdempotencyKey reads and trims the request header", () => {
  const key = getIdempotencyKey({
    headers: {
      "idempotency-key": "  abcdefgh-12345678  ",
    },
  } as never);

  assert.equal(key, "abcdefgh-12345678");
});

test("getIdempotencyKey rejects too-short values", () => {
  assert.throws(
    () =>
      getIdempotencyKey({
        headers: {
          "idempotency-key": "short",
        },
      } as never),
    /Idempotency-Key/i,
  );
});
