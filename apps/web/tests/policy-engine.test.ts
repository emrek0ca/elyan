import { describe, expect, it } from 'vitest';

describe('policy engine', () => {
  it('keeps direct answers tight with conservative limits', async () => {
    const { decidePolicy } = await import('@/core/control/policy-engine');
    const policy = decidePolicy({
      decision: {
        mode: 'fast',
        modelPerformance: 0.8,
        tools: {
          allowWebSearch: false,
          allowConnectors: false,
          allowLocalTools: false,
          allowBrowser: false,
          preferredTools: [],
        },
        steps: {
          complexity: 'low',
          stepBudget: 1,
          retryLimit: 0,
        },
        reasoning: ['fast path'],
        artifactCount: 0,
      },
      taskType: 'direct_answer',
      queryComplexity: 'low',
    });

    expect(policy).toMatchObject({
      maxSteps: 1,
      maxRetries: 0,
      maxTimeMs: 7500,
      maxCostUsd: 0.01,
      allowedTools: [],
    });
  });

  it('keeps research tasks within the execution budget while preserving retrieval tools', async () => {
    const { decidePolicy } = await import('@/core/control/policy-engine');
    const policy = decidePolicy({
      decision: {
        mode: 'research',
        modelPerformance: 0.9,
        tools: {
          allowWebSearch: true,
          allowConnectors: true,
          allowLocalTools: false,
          allowBrowser: true,
          preferredTools: ['web_search'],
        },
        steps: {
          complexity: 'high',
          stepBudget: 6,
          retryLimit: 2,
        },
        reasoning: ['research path'],
        artifactCount: 2,
      },
      taskType: 'research',
      queryComplexity: 'high',
    });

    expect(policy.maxSteps).toBe(6);
    expect(policy.maxRetries).toBe(2);
    expect(policy.maxTimeMs).toBe(75_000);
    expect(policy.maxCostUsd).toBe(0.18);
    expect(policy.allowedTools).toEqual(['web_search', 'connectors', 'browser']);
  });
});
