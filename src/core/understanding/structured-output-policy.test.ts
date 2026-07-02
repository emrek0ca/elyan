import assert from "node:assert/strict";
import test from "node:test";
import {
  decideStructuredResponseDecision,
  isExplicitTableRequest,
  isPlanOrStepRequest,
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

  assert.equal(isExplicitTableRequest("Bunu sadece duz yazi olarak anlat, tablo kullanma"), false);
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.widgetPolicy, "none");
  assert.equal(decision.reasons.includes("explicit_prose_preference"), true);
});

test("decideStructuredResponseDecision respects explicit no-table comparison requests", () => {
  const prompt = "ios ve android geliştirmeyi karşılaştır ama tablo yapma";
  const decision = decideStructuredResponseDecision({ prompt });

  assert.equal(isExplicitTableRequest(prompt), false);
  assert.equal(decision.primaryShape, "prose");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.tablePolicy, "forbidden");
  assert.equal(decision.widgetPolicy, "none");
});

test("decideStructuredResponseDecision keeps a brief-explanation prompt as prose-only", () => {
  // "kisaca anlat" signals the user wants a short prose answer, not a widget.
  const decision = decideStructuredResponseDecision({
    prompt: "Turk matematikcileri kisaca anlat",
  });

  assert.equal(decision.widgetPolicy, "none");
});

test("decideStructuredResponseDecision keeps summary prompts prose-only", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Bu metni kısa bir özet halinde yaz",
  });

  assert.equal(decision.primaryShape, "prose");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.tablePolicy, "forbidden");
  assert.equal(decision.widgetPolicy, "none");
});

test("decideStructuredResponseDecision respects explicit no-chart prose requests", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Bunu düz yazı olarak anlat, grafik istemiyorum",
  });

  assert.equal(decision.primaryShape, "prose");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.widgetPolicy, "none");
});

test("decideStructuredResponseDecision keeps planning prompts out of table widgets", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "Bana 5 adımlık Teknofest çalışma planı çıkar",
    selectedWorkload: "planning",
  });

  assert.equal(isExplicitTableRequest("Bana 5 adımlık Teknofest çalışma planı çıkar"), false);
  assert.equal(isPlanOrStepRequest("Bana 5 adımlık Teknofest çalışma planı çıkar"), true);
  assert.equal(decision.primaryShape, "list");
  assert.equal(decision.primaryBlockType, "text");
  assert.equal(decision.tablePolicy, "forbidden");
  assert.equal(decision.widgetPolicy, "none");
  assert.equal(decision.reasons.includes("plan_request_prefers_list"), true);
});

test("decideStructuredResponseDecision still allows explicit table plans", () => {
  const decision = decideStructuredResponseDecision({
    prompt: "5 adımlık Teknofest çalışma planını tablo olarak ver",
    selectedWorkload: "planning",
  });

  assert.equal(isExplicitTableRequest("5 adımlık Teknofest çalışma planını tablo olarak ver"), true);
  assert.equal(decision.primaryBlockType, "table");
  assert.equal(decision.widgetPolicy, "single_primary_widget");
});
