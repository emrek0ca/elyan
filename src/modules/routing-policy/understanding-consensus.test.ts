import assert from "node:assert/strict";
import test from "node:test";
import type { IntentClassification } from "../../core/understanding/types.js";
import { buildUnderstandingConsensus } from "./understanding-consensus.js";

function classification(
  overrides: Partial<IntentClassification> = {},
): IntentClassification {
  return {
    primaryIntent: "automation",
    secondaryIntents: [],
    requiresLocalRuntime: true,
    requiresRetrieval: false,
    requiresToolUse: true,
    requiresCitation: false,
    requiresLongRunningTask: false,
    privacyRisk: "high",
    confidence: 0.91,
    reason: "typed",
    taskFrame: {
      goal: "local action",
      likelyAnswerShape: "execution",
      reasoningMode: "fast",
      shouldClarify: false,
    },
    ecosystemHints: [],
    routingHints: {
      mode: "local_private",
      preferredCapabilities: ["close_app"],
      avoidCloud: true,
      requiresLocalRuntime: true,
    },
    ...overrides,
  };
}

test("consensus agrees on a direct local capability without storing model prose", () => {
  const result = buildUnderstandingConsensus({
    message: "Chrome u kapat",
    primary: classification(),
    verifier: classification(),
    verifierInvoked: true,
  });

  assert.equal(result.status, "agreed");
  assert.equal(result.targetSurface, "desktop");
  assert.equal(result.goal.objectiveHash.length, 24);
  assert.equal(result.selectedCapabilities.includes("close_app"), true);
  assert.equal(JSON.stringify(result).includes("typed"), false);
});

test("consensus fails closed when semantic candidates disagree on execution surface", () => {
  const result = buildUnderstandingConsensus({
    message: "Chrome u kapat",
    primary: classification(),
    verifier: classification({
      primaryIntent: "chat",
      requiresLocalRuntime: false,
      requiresToolUse: false,
      privacyRisk: "low",
      routingHints: {
        mode: "fast",
        preferredCapabilities: [],
        avoidCloud: false,
        requiresLocalRuntime: false,
      },
    }),
    verifierInvoked: true,
  });

  assert.equal(result.status, "clarification_required");
  assert.equal(result.conflict.targetSurface, true);
  assert.equal(result.privacy.maySendPrivateContextToServer, true);
});
