import assert from "node:assert/strict";
import test from "node:test";
import {
  decideAgentEngineQueueAdmission,
  getAgentEngineQueueLimits,
  isAgentEngineShadowEnabled,
  isAgentEngineV2Enabled,
} from "./agent-engine-policy.js";

function app(overrides: Record<string, unknown> = {}) {
  return { config: {
    ELYAN_AGENT_ENGINE_V2_ENABLED: false,
    ELYAN_AGENT_ENGINE_SHADOW_ENABLED: false,
    ELYAN_AGENT_ENGINE_ROLLOUT_PERCENT: 0,
    ELYAN_AGENT_ENGINE_GLOBAL_CONCURRENCY: 4,
    ELYAN_AGENT_ENGINE_USER_CONCURRENCY: 1,
    ELYAN_AGENT_ENGINE_GLOBAL_BACKPRESSURE_MAX: 2_000,
    ELYAN_AGENT_ENGINE_USER_BACKPRESSURE_MAX: 20,
    ...overrides,
  } } as never;
}

test("agent engine is exactly disabled by default", () => {
  assert.equal(isAgentEngineV2Enabled(app(), "user-1"), false);
  assert.equal(isAgentEngineShadowEnabled(app()), false);
});

test("agent engine supports explicit and deterministic rollout", () => {
  assert.equal(isAgentEngineV2Enabled(app({ ELYAN_AGENT_ENGINE_V2_ENABLED: true }), "user-1"), true);
  const rolloutApp = app({ ELYAN_AGENT_ENGINE_ROLLOUT_PERCENT: 37 });
  assert.equal(isAgentEngineV2Enabled(rolloutApp, "stable-user"), isAgentEngineV2Enabled(rolloutApp, "stable-user"));
  assert.equal(isAgentEngineShadowEnabled(app({ ELYAN_AGENT_ENGINE_SHADOW_ENABLED: true })), true);
});

test("agent engine queue limits reject global and user overload before enqueue", () => {
  const limits = getAgentEngineQueueLimits(app({
    ELYAN_AGENT_ENGINE_GLOBAL_BACKPRESSURE_MAX: 10,
    ELYAN_AGENT_ENGINE_USER_BACKPRESSURE_MAX: 3,
  }));

  assert.deepEqual(
    decideAgentEngineQueueAdmission({ globalWaiting: 9, userWaiting: 2 }, limits),
    { accepted: true, reason: "accepted" },
  );
  assert.deepEqual(
    decideAgentEngineQueueAdmission({ globalWaiting: 10, userWaiting: 2 }, limits),
    { accepted: false, reason: "global_backpressure" },
  );
  assert.deepEqual(
    decideAgentEngineQueueAdmission({ globalWaiting: 9, userWaiting: 3 }, limits),
    { accepted: false, reason: "user_backpressure" },
  );
});
