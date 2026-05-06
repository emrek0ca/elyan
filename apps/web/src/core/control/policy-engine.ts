import type { ControlPlaneTaskIntent } from '@/core/control-plane/types';
import type { ExecutionDecision } from '@/core/decision/engine';

export type QueryComplexity = 'low' | 'medium' | 'high';

export type PolicyEngineInput = {
  decision: ExecutionDecision;
  taskType: ControlPlaneTaskIntent;
  queryComplexity: QueryComplexity;
};

export type PolicyEngineOutput = {
  maxSteps: number;
  maxRetries: number;
  maxTimeMs: number;
  maxCostUsd: number;
  maxTokens: number;
  allowedTools: string[];
};

function clampInt(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, Math.trunc(value)));
}

function round4(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(4)) : 0;
}

function deriveTokenCap(maxCostUsd: number) {
  return Math.max(4_000, Math.round(maxCostUsd * 40_000));
}

function isResearchTask(taskType: ControlPlaneTaskIntent) {
  return taskType === 'research' || taskType === 'comparison';
}

function isWorkflowTask(taskType: ControlPlaneTaskIntent) {
  return taskType === 'procedural' || taskType === 'personal_workflow';
}

function buildBasePolicy(input: PolicyEngineInput): PolicyEngineOutput {
  const mode = input.decision.mode;
  const complexity = input.queryComplexity;

  if (mode === 'fast') {
    return {
      maxSteps: complexity === 'high' ? 2 : 1,
      maxRetries: 0,
      maxTimeMs: complexity === 'high' ? 15_000 : 7_500,
      maxCostUsd: complexity === 'high' ? 0.02 : 0.01,
      maxTokens: deriveTokenCap(complexity === 'high' ? 0.02 : 0.01),
      allowedTools: [],
    };
  }

  if (mode === 'quantum') {
    return {
      maxSteps: 3,
      maxRetries: 1,
      maxTimeMs: 10_000,
      maxCostUsd: 0.01,
      maxTokens: deriveTokenCap(0.01),
      allowedTools: ['optimization_solve', 'tool_bridge'],
    };
  }

  if (mode === 'research') {
    return {
      maxSteps: complexity === 'high' ? 6 : complexity === 'medium' ? 4 : 3,
      maxRetries: complexity === 'high' ? 2 : 1,
      maxTimeMs: complexity === 'high' ? 75_000 : complexity === 'medium' ? 45_000 : 30_000,
      maxCostUsd: complexity === 'high' ? 0.18 : complexity === 'medium' ? 0.12 : 0.08,
      maxTokens: deriveTokenCap(complexity === 'high' ? 0.18 : complexity === 'medium' ? 0.12 : 0.08),
      allowedTools: ['web_search', 'connectors', 'browser'],
    };
  }

  return {
    maxSteps: complexity === 'high' ? 6 : complexity === 'medium' ? 4 : 3,
    maxRetries: complexity === 'high' ? 2 : 1,
    maxTimeMs: complexity === 'high' ? 60_000 : complexity === 'medium' ? 40_000 : 25_000,
    maxCostUsd: complexity === 'high' ? 0.14 : complexity === 'medium' ? 0.1 : 0.06,
    maxTokens: deriveTokenCap(complexity === 'high' ? 0.14 : complexity === 'medium' ? 0.1 : 0.06),
    allowedTools: ['local_tools', 'connectors', 'browser'],
  };
}

export function decidePolicy(input: PolicyEngineInput): PolicyEngineOutput {
  const base = buildBasePolicy(input);
  const complexity = input.queryComplexity;

  if (input.decision.mode === 'quantum') {
    return {
      maxSteps: 3,
      maxRetries: 1,
      maxTimeMs: 10_000,
      maxCostUsd: 0.01,
      maxTokens: deriveTokenCap(0.01),
      allowedTools: ['optimization_solve', 'tool_bridge'],
    };
  }

  const taskAdjustments = isResearchTask(input.taskType)
    ? {
        maxSteps: complexity === 'high' ? 7 : 4,
        maxRetries: base.maxRetries + 1,
        maxTimeMs: base.maxTimeMs + (complexity === 'high' ? 15_000 : 10_000),
        maxCostUsd: base.maxCostUsd + (complexity === 'high' ? 0.04 : 0.02),
        allowedTools: ['web_search', 'connectors', 'browser'],
      }
    : isWorkflowTask(input.taskType)
      ? {
          maxSteps: complexity === 'high' ? 6 : 4,
          maxRetries: base.maxRetries,
          maxTimeMs: base.maxTimeMs,
          maxCostUsd: base.maxCostUsd,
          allowedTools: ['local_tools', 'connectors', 'browser'],
        }
      : {
          maxSteps: Math.min(base.maxSteps, 2),
          maxRetries: 0,
          maxTimeMs: Math.min(base.maxTimeMs, 20_000),
          maxCostUsd: Math.min(base.maxCostUsd, 0.02),
          allowedTools: [],
        };

  const nextMaxSteps = clampInt(Math.min(base.maxSteps, taskAdjustments.maxSteps), 1, 8);
  const nextMaxRetries = clampInt(Math.min(base.maxRetries, taskAdjustments.maxRetries), 0, 3);
  const nextMaxTimeMs = clampInt(Math.min(base.maxTimeMs, taskAdjustments.maxTimeMs), 5_000, 120_000);
  const nextMaxCostUsd = round4(Math.min(base.maxCostUsd, taskAdjustments.maxCostUsd));
  const nextMaxTokens = clampInt(
    Math.min(base.maxTokens, deriveTokenCap(nextMaxCostUsd)),
    4_000,
    200_000
  );

  return {
    maxSteps: nextMaxSteps,
    maxRetries: nextMaxRetries,
    maxTimeMs: nextMaxTimeMs,
    maxCostUsd: nextMaxCostUsd,
    maxTokens: nextMaxTokens,
    allowedTools: [...new Set(taskAdjustments.allowedTools.length > 0 ? taskAdjustments.allowedTools : base.allowedTools)],
  };
}
