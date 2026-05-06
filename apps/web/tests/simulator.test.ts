import { describe, expect, it } from 'vitest';
import type { InteractionRequest } from '@/core/interaction/orchestrator';
import type { OrchestrationPlan } from '@/core/orchestration';
import { createRunTrace } from '@/core/observability/run-trace';
import { defaultSimulationScenarios, evaluateScenario, type ScenarioSimulationResult } from '@/core/testing/simulator';

function buildScenarioResult(overrides: Partial<ScenarioSimulationResult> = {}) {
  const scenario = overrides.scenario ?? defaultSimulationScenarios.find((item) => item.kind === 'deep_research')!;
  const request: InteractionRequest = {
    source: 'cli',
    text: scenario.input,
    requestId: 'scenario-test-request',
  } as InteractionRequest;
  const decision = overrides.decision ?? {
    mode: 'research' as const,
    modelId: 'gpt-4.1',
    modelPerformance: 0.92,
    tools: {
      allowWebSearch: true,
      allowConnectors: true,
      allowLocalTools: false,
      allowBrowser: true,
      preferredTools: ['web_search', 'connectors', 'browser'],
    },
    steps: {
      complexity: 'medium' as const,
      stepBudget: 3,
      retryLimit: 1,
    },
    reasoning: ['test'],
    artifactCount: 1,
  };
  const policy = overrides.policy ?? {
    maxSteps: 3,
    maxRetries: 1,
    maxTimeMs: 30_000,
    maxCostUsd: 0.08,
    allowedTools: ['web_search', 'connectors', 'browser'],
  };
  const traceRecorder = createRunTrace({
    runId: 'run-test',
    mode: 'research',
    taskType: 'research',
    modelId: 'gpt-4.1',
    stepBudget: 3,
    retryLimit: 1,
  });

  traceRecorder.beforeExecution({ scenarioId: scenario.id });
  traceRecorder.recordStepStarted({
    step: 1,
    modelId: 'gpt-4.1',
    tool: 'web_search',
    retryCount: 0,
  });
  traceRecorder.recordStepCompleted({
    step: 1,
    modelId: 'gpt-4.1',
    tool: 'web_search',
    latencyMs: 220,
    success: true,
    retryCount: 0,
  });
  traceRecorder.recordCompletion({
    step: 1,
    modelId: 'gpt-4.1',
    tool: 'web_search',
    latencyMs: 220,
    verdict: 'success',
    reason: 'Grounded answer',
    retryCount: 0,
  });

  const trace = {
    ...traceRecorder.finalize(),
    scenario,
    scenarioId: scenario.id,
    scenarioKind: scenario.kind,
    requestId: request.requestId ?? 'scenario-test-request',
    input: request.text,
    request,
    decision,
    policy,
    expected: scenario.expectations,
    modelSwitchObserved: false,
  };

  return {
    scenario,
    request,
    classification: {} as ScenarioSimulationResult['classification'],
    plan: { taskIntent: 'research' } as OrchestrationPlan,
    decision,
    policy,
    execution: {
      status: 'success' as const,
      text: 'Grounded answer',
      sources: [{ url: 'https://example.com', title: 'Example' }],
      modelId: 'gpt-4.1',
      modelProvider: 'openai',
      completion: null,
      runId: 'run-test',
    },
    trace,
    evaluation: {
      pass: false,
      scores: {
        decisionQuality: 0,
        executionEfficiency: 0,
        retryEffectiveness: 0,
        toolUsageCorrectness: 0,
        overall: 0,
        pass: false,
      },
      diffs: [],
      traceSummary: trace.summary,
      traceMetrics: {
        runCount: 0,
        successRate: 0,
        retryCount: 0,
        avgLatencyMs: 0,
        estimatedCostUsd: 0,
        modelSuccessRateByModel: {},
        modelMetrics: [],
      },
    },
  } satisfies ScenarioSimulationResult;
}

describe('simulation catalog', () => {
  it('includes advanced scenarios for ambiguity, conflicts, retries, and model switching', () => {
    const kinds = defaultSimulationScenarios.map((scenario) => scenario.kind);

    expect(kinds).toEqual(
      expect.arrayContaining([
        'ambiguous_query',
        'conflicting_sources',
        'long_running_task',
        'tool_failure_recovery',
        'model_switching',
        'route_optimization',
        'scheduling_problem',
        'resource_allocation',
      ])
    );
  });
});

describe('simulation scoring', () => {
  it('scores a grounded research run highly when decision and tools match the scenario', () => {
    const result = buildScenarioResult();
    const evaluation = evaluateScenario(result);

    expect(evaluation.pass).toBe(true);
    expect(evaluation.scores.decisionQuality).toBeGreaterThan(0.6);
    expect(evaluation.scores.executionEfficiency).toBeGreaterThan(0.4);
    expect(evaluation.scores.toolUsageCorrectness).toBeGreaterThan(0.6);
    expect(evaluation.traceSummary.success).toBe(true);
  });
});
