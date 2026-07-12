import assert from "node:assert/strict";
import test from "node:test";
import {
  canStartVisionProviderCall,
  selectVisionModelAttempts,
  selectVisionRequestAttempt,
  shouldRunVisionSecondaryReview,
  VISION_TOTAL_PROVIDER_CALL_BUDGET,
} from "./vision-attempt-budget.js";

test("vision provider call budget is capped at two", () => {
  assert.equal(VISION_TOTAL_PROVIDER_CALL_BUDGET, 2);
  assert.equal(canStartVisionProviderCall(0), true);
  assert.equal(canStartVisionProviderCall(1), true);
  assert.equal(canStartVisionProviderCall(2), false);
});

test("multiple providers receive one primary model attempt each", () => {
  assert.deepEqual(selectVisionModelAttempts({
    preferredModels: ["primary", "fallback"],
    providerCount: 2,
  }), ["primary"]);
});

test("single provider may use its fallback model within the same budget", () => {
  assert.deepEqual(selectVisionModelAttempts({
    preferredModels: ["primary", "fallback", "extra"],
    providerCount: 1,
  }), ["primary", "fallback"]);
});

test("vision skips Ollama text-only generate attempt in favor of chat images", () => {
  assert.deepEqual(selectVisionRequestAttempt([
    { path: "/api/generate", mode: "text-only" },
    { path: "/api/chat", mode: "multimodal" },
  ]), [{ path: "/api/chat", mode: "multimodal" }]);
});

test("secondary review runs only after a first-choice success with budget left", () => {
  assert.equal(shouldRunVisionSecondaryReview({ callsUsed: 1, fallbackUsed: false }), true);
  assert.equal(shouldRunVisionSecondaryReview({ callsUsed: 2, fallbackUsed: false }), false);
  assert.equal(shouldRunVisionSecondaryReview({ callsUsed: 1, fallbackUsed: true }), false);
});
