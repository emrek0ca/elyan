import assert from "node:assert/strict";
import test from "node:test";
import { evidenceStateForRetrieval } from "./retrieval-orchestrator.js";

test("required retrieval with zero results is insufficient", () => {
  assert.equal(
    evidenceStateForRetrieval({
      evidenceRequired: true,
      resultCount: 0,
      lowConfidence: true,
    }),
    "insufficient",
  );
});
