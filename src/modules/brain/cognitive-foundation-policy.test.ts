import assert from "node:assert/strict";
import test from "node:test";
import {
  isCognitiveFoundationEnabled,
  isCognitiveShadowReadEnabled,
} from "./cognitive-foundation-policy.js";

function app(config: Record<string, unknown>) {
  return { config } as never;
}

test("cognitive foundation rollout is disabled by default", () => {
  assert.equal(isCognitiveFoundationEnabled(app({}), "user-1"), false);
});

test("cognitive foundation supports explicit and deterministic percentage rollout", () => {
  assert.equal(isCognitiveFoundationEnabled(app({
    ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED: true,
    ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT: 0,
  }), "user-1"), true);
  assert.equal(isCognitiveFoundationEnabled(app({
    ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED: false,
    ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT: 100,
  }), "user-1"), true);
});

test("cognitive shadow reads are independently gated", () => {
  assert.equal(isCognitiveShadowReadEnabled(app({
    ELYAN_COGNITIVE_SHADOW_READ_ENABLED: true,
  })), true);
});
