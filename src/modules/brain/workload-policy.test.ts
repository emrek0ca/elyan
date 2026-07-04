import assert from "node:assert/strict";
import test from "node:test";
import type { PlanBrainProfile } from "../billing/catalog.js";
import {
  getChatTimeoutMs,
  getLoadSheddingOptions,
  getMaxTokensForWorkload,
} from "./workload-policy.js";

const standardProfile: PlanBrainProfile = {
  qualityProfile: "free_basic",
  tier: "standard",
  reasoningMultiplier: 1,
  retrievalFanout: 2,
  memoryFanout: 2,
  maxTokenScale: 1,
};

const premiumProfile: PlanBrainProfile = {
  qualityProfile: "pro_max",
  tier: "premium",
  reasoningMultiplier: 5,
  retrievalFanout: 5,
  memoryFanout: 6,
  maxTokenScale: 2,
};

test("getMaxTokensForWorkload keeps standard workloads at base budget", () => {
  assert.equal(
    getMaxTokensForWorkload("mobile_chat_fast", standardProfile),
    getMaxTokensForWorkload("mobile_chat_fast", { ...standardProfile, maxTokenScale: 10 }),
  );
});

test("getMaxTokensForWorkload caps premium workload expansion", () => {
  assert.equal(getMaxTokensForWorkload("mobile_chat_fast", premiumProfile), 360);
  assert.equal(getMaxTokensForWorkload("planning", premiumProfile), 900);
});

test("getLoadSheddingOptions derives stable namespace ttl and salt", () => {
  const options = getLoadSheddingOptions("planning", premiumProfile, "Pro");
  assert.equal(options.namespace, "shared-brain:premium");
  assert.equal(options.maxConcurrent, 2);
  assert.equal(options.retryAfterSeconds, 5);
  assert.match(options.salt, /^pro:planning:5:5:6$/);
  assert.ok(options.ttlMs >= getChatTimeoutMs("planning"));
});
