import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";

const health = {
  consecutiveFailures: 0,
  mismatchSamples: 0,
  mismatchFailures: 0,
  slowReads: 0,
  openUntil: 0,
};

const AUTO_ROLLBACK_MS = 5 * 60_000;

function isHealthGateOpen(): boolean {
  if (health.openUntil <= Date.now()) {
    health.openUntil = 0;
    return false;
  }
  return true;
}

export function recordCognitiveFoundationSignal(input: {
  ok: boolean;
  keyMismatchCount?: number;
  latencyMs?: number;
}): void {
  health.consecutiveFailures = input.ok ? 0 : health.consecutiveFailures + 1;
  if (input.keyMismatchCount != null) {
    health.mismatchSamples += 1;
    if (input.keyMismatchCount > 0) health.mismatchFailures += 1;
  }
  if ((input.latencyMs ?? 0) > 200) health.slowReads += 1;

  const mismatchRate = health.mismatchSamples > 0
    ? health.mismatchFailures / health.mismatchSamples
    : 0;
  if (
    health.consecutiveFailures >= 3 ||
    (health.mismatchSamples >= 20 && mismatchRate > 0.5) ||
    health.slowReads >= 5
  ) {
    health.openUntil = Date.now() + AUTO_ROLLBACK_MS;
    health.consecutiveFailures = 0;
    health.mismatchSamples = 0;
    health.mismatchFailures = 0;
    health.slowReads = 0;
  }
}

function rolloutBucket(userId: string): number {
  const digest = createHash("sha256").update(`cognitive-foundation:${userId}`).digest();
  return digest.readUInt32BE(0) % 100;
}

export function isCognitiveFoundationEnabled(
  app: FastifyInstance,
  userId: string,
): boolean {
  if (isHealthGateOpen()) {
    return false;
  }
  if (app.config?.ELYAN_COGNITIVE_FOUNDATION_V2_ENABLED === true) {
    return true;
  }
  const percent = app.config?.ELYAN_COGNITIVE_FOUNDATION_ROLLOUT_PERCENT ?? 0;
  return percent > 0 && rolloutBucket(userId) < percent;
}

export function isCognitiveShadowReadEnabled(app: FastifyInstance): boolean {
  return app.config?.ELYAN_COGNITIVE_SHADOW_READ_ENABLED === true;
}
