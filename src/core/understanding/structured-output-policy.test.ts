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

test("decideStructuredResponseDecision allows proactive visuals on an ordinary non-explicit prompt", () => {
  // No explicit widget word and no plain-prose preference → the model may
  // proactively emit ONE widget when the answer content warrants it.
  const decision = decideStructuredResponseDecision({
    prompt: "Dunyanin en yuksek bes dagini ve yuksekliklerini soyle",
  });

  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.widgetPolicy, "proactive_optional");
  assert.equal(decision.reasons.includes("proactive_visuals_allowed"), true);
});

test("decideStructuredResponseDecision stays prose-only when the user asks for plain text", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Bunu sadece duz yazi olarak anlat, tablo kullanma",
  });

  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.widgetPolicy, "none");
  assert.equal(decision.reasons.includes("explicit_prose_preference"), true);
});

test("decideStructuredResponseDecision keeps a brief-explanation prompt as prose-only", () => {
  // "kisaca anlat" signals the user wants a short prose answer, not a widget.
  const decision = decideStructuredResponseDecision({
    prompt: "Turk matematikcileri kisaca anlat",
  });

  assert.equal(decision.widgetPolicy, "none");
});

