import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";

function rolloutBucket(userId: string): number {
  return createHash("sha256").update(`agent-engine-v2:${userId}`).digest().readUInt32BE(0) % 100;
}

export function isAgentEngineV2Enabled(app: FastifyInstance, userId: string): boolean {
  if (app.config.ELYAN_AGENT_ENGINE_V2_ENABLED === true) return true;
  const percent = app.config.ELYAN_AGENT_ENGINE_ROLLOUT_PERCENT ?? 0;
  return percent > 0 && rolloutBucket(userId) < percent;
}

export function isAgentEngineShadowEnabled(app: FastifyInstance): boolean {
  return app.config.ELYAN_AGENT_ENGINE_SHADOW_ENABLED === true;
}

export type AgentEngineQueueLimits = {
  globalConcurrency: number;
  userConcurrency: number;
  globalBackpressureMax: number;
  userBackpressureMax: number;
};

export type AgentEngineQueueSnapshot = {
  globalWaiting: number;
  userWaiting: number;
};

export type AgentEngineQueueDecision = {
  accepted: boolean;
  reason: "accepted" | "global_backpressure" | "user_backpressure";
};

function positiveInt(value: unknown, fallback: number, max: number): number {
  return Math.max(
    1,
    Math.min(
      typeof value === "number" && Number.isFinite(value) ? Math.floor(value) : fallback,
      max,
    ),
  );
}

export function getAgentEngineQueueLimits(app: FastifyInstance): AgentEngineQueueLimits {
  return {
    globalConcurrency: positiveInt(app.config.ELYAN_AGENT_ENGINE_GLOBAL_CONCURRENCY, 4, 64),
    userConcurrency: positiveInt(app.config.ELYAN_AGENT_ENGINE_USER_CONCURRENCY, 1, 8),
    globalBackpressureMax: positiveInt(app.config.ELYAN_AGENT_ENGINE_GLOBAL_BACKPRESSURE_MAX, 2_000, 200_000),
    userBackpressureMax: positiveInt(app.config.ELYAN_AGENT_ENGINE_USER_BACKPRESSURE_MAX, 20, 2_000),
  };
}

export function decideAgentEngineQueueAdmission(
  snapshot: AgentEngineQueueSnapshot,
  limits: AgentEngineQueueLimits,
): AgentEngineQueueDecision {
  if (snapshot.globalWaiting >= limits.globalBackpressureMax) {
    return { accepted: false, reason: "global_backpressure" };
  }
  if (snapshot.userWaiting >= limits.userBackpressureMax) {
    return { accepted: false, reason: "user_backpressure" };
  }
  return { accepted: true, reason: "accepted" };
}

export function buildAgentEngineTenantQueueKey(input: { userId: string }): string {
  return `agent-engine:user:${input.userId}`;
}
