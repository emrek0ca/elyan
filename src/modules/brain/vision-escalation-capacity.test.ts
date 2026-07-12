import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import {
  canAffordVisionEscalation,
  tryAcquireVisionEscalationPermit,
} from "./vision-escalation-capacity.js";

const appWithoutRedis = {} as FastifyInstance;

test("in-process guard permits one escalation per user without Redis", async () => {
  const first = await tryAcquireVisionEscalationPermit(appWithoutRedis, "user-1");
  const sameUser = await tryAcquireVisionEscalationPermit(appWithoutRedis, "user-1");
  const secondUser = await tryAcquireVisionEscalationPermit(appWithoutRedis, "user-2");
  const thirdUser = await tryAcquireVisionEscalationPermit(appWithoutRedis, "user-3");
  assert.ok(first);
  assert.equal(sameUser, null);
  assert.ok(secondUser);
  assert.equal(thirdUser, null);
  await first?.release();
  await secondUser?.release();
});

test("credit guard keeps a reserve for the secondary call", () => {
  assert.equal(canAffordVisionEscalation({ remainingCredits: 100, estimatedPrimaryCredits: 80, costGuardEnabled: false }), false);
  assert.equal(canAffordVisionEscalation({ remainingCredits: 300, estimatedPrimaryCredits: 80, costGuardEnabled: true }), true);
  assert.equal(canAffordVisionEscalation({ remainingCredits: 100, estimatedPrimaryCredits: 80, costGuardEnabled: true }), false);
});
