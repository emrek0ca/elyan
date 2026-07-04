import assert from "node:assert/strict";
import test from "node:test";
import {
  commonPrefixLength,
  createDeltaPublisherCore,
  type SharedBrainInferenceDelta,
} from "./stream-publisher.js";

test("commonPrefixLength returns the shared prefix length", () => {
  assert.equal(commonPrefixLength("abcdef", "abcxyz"), 3);
  assert.equal(commonPrefixLength("abc", "xyz"), 0);
  assert.equal(commonPrefixLength("same", "same"), 4);
});

test("createDeltaPublisherCore streams visible appended content monotonically", async () => {
  const emitted: SharedBrainInferenceDelta[] = [];
  const publisher = createDeltaPublisherCore({
    startedAt: Date.now(),
    provider: "groq",
    model: "test-model",
    onDelta: (delta) => {
      emitted.push(delta);
    },
    computeVisibleText: (full) => full.replace(/\{hidden\}/g, ""),
    looksLikeReasoningDumpOpening: () => false,
  });

  await publisher.publish("Hello ", "Hello ");
  await publisher.publish("world", "Hello {hidden}world", { force: true });

  assert.equal(emitted.at(-1)?.content, "Hello world");
  assert.deepEqual(
    emitted.map((item) => item.delta).join(""),
    "Hello world",
  );
});

test("createDeltaPublisherCore suppresses reasoning dump openings until replacement", async () => {
  const emitted: SharedBrainInferenceDelta[] = [];
  const publisher = createDeltaPublisherCore({
    startedAt: Date.now(),
    provider: "groq",
    model: "test-model",
    onDelta: (delta) => {
      emitted.push(delta);
    },
    computeVisibleText: (full) => full,
    looksLikeReasoningDumpOpening: (text) => text.startsWith("We need answer"),
  });

  await publisher.publish(
    "We need answer",
    "We need answer by exposing chain of thought",
    { force: true },
  );
  assert.equal(publisher.suppressedAsReasoningDump, true);
  assert.equal(emitted.length, 0);

  await publisher.publishReplacement("Safe final answer");
  assert.equal(emitted.length, 1);
  assert.equal(emitted[0]?.content, "Safe final answer");
});
