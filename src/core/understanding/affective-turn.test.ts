import assert from "node:assert/strict";
import test from "node:test";
import { detectAffectiveTurn } from "./affective-turn.js";

test("current-turn affect detects frustration before response generation", async () => {
  const affect = await detectAffectiveTurn(
    "Bu yine çalışmıyor, gerçekten bıktım.",
  );

  assert.equal(affect.mood, "frustrated");
  assert.ok(affect.confidence >= 0.8);
  assert.match(affect.responseDirective, /calm, concrete, and solution-first/i);
});

test("current-turn affect lowers cognitive load for tired users", async () => {
  const affect = await detectAffectiveTurn(
    "Çok yorgunum, sadece en gerekli adımları ver.",
  );

  assert.equal(affect.mood, "tired");
  assert.equal(affect.energy, "low");
  assert.match(affect.responseDirective, /cognitive load low/i);
});
