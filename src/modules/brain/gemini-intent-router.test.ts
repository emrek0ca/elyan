import assert from "node:assert/strict";
import test from "node:test";
import { classifyIntent } from "../../core/understanding/intent-classifier.js";
import { enhanceIntentWithGeminiFree } from "./gemini-intent-router.js";

test("enhanceIntentWithGeminiFree never lets a topic override an explicit plan", async () => {
  const current = classifyIntent({
    userId: "user-1",
    message:
      "Bu hedef için bir plan oluştur, doktor olmak istiyorum ama matematik bölümündeyim",
  });

  const result = await enhanceIntentWithGeminiFree(null as never, {
    userId: "user-1",
    message:
      "Bu hedef için bir plan oluştur, doktor olmak istiyorum ama matematik bölümündeyim",
    current,
  });

  assert.equal(result.primaryIntent, "planning");
  assert.equal(result.secondaryIntents.includes("math"), true);
});
