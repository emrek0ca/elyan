import assert from "node:assert/strict";
import test from "node:test";
import {
  decideStructuredResponseDecision,
  isExplicitTableRequest,
} from "./structured-output-policy.js";

test("decideStructuredResponseDecision defaults ordinary explanation prompts to prose", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Turk matematikcileri kisaca anlat",
  });

  assert.equal(isExplicitTableRequest("Turk matematikcileri kisaca anlat"), false);
  assert.equal(decision.primaryShape, "prose");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.tablePolicy, "forbidden");
});

test("decideStructuredResponseDecision selects the requested widget shape only when explicit", () => {
  assert.equal(
    decideStructuredResponseDecision({ prompt: "Gelir gider verisini tablo olarak ver" }).primaryBlockType,
    "table",
  );
  assert.equal(
    decideStructuredResponseDecision({ prompt: "2020-2025 gelir gider cizgi grafik olustur" }).primaryBlockType,
    "chart",
  );
  assert.equal(
    decideStructuredResponseDecision({ prompt: "Ucgen icin sade SVG geometrik cizim olustur" }).primaryBlockType,
    "svg",
  );
  assert.equal(
    decideStructuredResponseDecision({ prompt: "x^2 fonksiyonunun turevini LaTeX ile ver" }).primaryBlockType,
    "math",
  );
});

