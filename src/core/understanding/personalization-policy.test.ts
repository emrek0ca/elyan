import assert from "node:assert/strict";
import test from "node:test";
import { filterLearningSignals, filterRetrievedMemory, isSafeForLearning } from "./personalization-policy.js";

test("isSafeForLearning rejects secrets and private local paths", () => {
  assert.equal(isSafeForLearning("api_key=sk_test_secret_value_1234567890"), false);
  assert.equal(isSafeForLearning("/Users/example/Desktop/private.txt"), false);
  assert.equal(isSafeForLearning("tek kullanımlık kod 123456"), false);
  assert.equal(isSafeForLearning("IBAN TR33 0006 1005 1978 6457 8413 26"), false);
  assert.equal(isSafeForLearning("T.C. kimlik no 12345678901"), false);
  assert.equal(isSafeForLearning("jwt eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123abc123abc123"), false);
  assert.equal(isSafeForLearning("prefers concise Turkish technical answers"), true);
});

test("filterLearningSignals applies confidence threshold and deduplication", () => {
  const filtered = filterLearningSignals([
    {
      type: "style",
      key: "answer length",
      value: "concise",
      confidence: 0.7,
      scope: "user",
      source: "interaction",
      ttlDays: null,
    },
    {
      type: "style",
      key: "answer length",
      value: "concise",
      confidence: 0.7,
      scope: "user",
      source: "interaction",
      ttlDays: null,
    },
    {
      type: "preference",
      key: "temporary",
      value: "maybe",
      confidence: 0.4,
      scope: "user",
      source: "interaction",
      ttlDays: null,
    },
  ]);

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.key, "answer_length");
});

test("filterRetrievedMemory removes unsafe memory before prompt use", () => {
  const filtered = filterRetrievedMemory([
    {
      id: "1",
      type: "style",
      key: "answer_length",
      value: "concise",
      confidence: 0.9,
      scope: "user",
      source: "interaction",
      createdAt: new Date(),
      staleness: "fresh",
      conflictStatus: "active",
    },
    {
      id: "2",
      type: "preference",
      key: "secret",
      value: "password is hunter2",
      confidence: 0.9,
      scope: "user",
      source: "interaction",
      createdAt: new Date(),
      staleness: "fresh",
      conflictStatus: "active",
    },
  ]);

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.id, "1");
});

test("filterRetrievedMemory prefers verified fresh corrections and drops contested noise", () => {
  const filtered = filterRetrievedMemory([
    {
      id: "1",
      type: "correction",
      key: "negative_feedback",
      value: "be shorter",
      confidence: 0.9,
      scope: "user",
      source: "reflective_memory",
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      staleness: "stale",
      conflictStatus: "active",
    },
    {
      id: "2",
      type: "correction",
      key: "negative_feedback",
      value: "be more precise",
      confidence: 0.91,
      scope: "user",
      source: "reflective_memory",
      createdAt: new Date("2030-01-02T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-03T00:00:00.000Z"),
    },
    {
      id: "3",
      type: "style",
      key: "answer_length",
      value: "concise",
      confidence: 0.94,
      scope: "user",
      source: "semantic_memory",
      createdAt: new Date("2030-01-03T00:00:00.000Z"),
      staleness: "contested",
      conflictStatus: "contested",
    },
  ]);

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0]?.id, "2");
});
