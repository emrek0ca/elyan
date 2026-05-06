import { describe, expect, it } from 'vitest';
import { createRunTrace } from '@/core/observability/run-trace';
import { compareBaseline, type ScenarioSuiteReport } from '@/core/testing/eval-runner';
import { defaultSimulationScenarios, type ScenarioSimulationResult } from '@/core/testing/simulator';

function buildTrace(runId: string, success: boolean, retryCount: number, stepCount: number, latencyMs: number) {
  const trace = createRunTrace({
    runId,
    mode: 'research',
    taskType: 'research',
    modelId: 'gpt-4.1',
    stepBudget: 3,
    retryLimit: 1,
  });

  trace.beforeExecution({ scenarioId: runId });

  for (let step = 1; step <= stepCount; step += 1) {
    trace.recordStepStarted({
      step,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      retryCount: Math.max(0, step - 1),
    });
    trace.recordStepCompleted({
      step,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      latencyMs,
      success,
      retryCount: Math.max(0, step - 1),
      errorType: success ? undefined : 'BAD_RESULT',
    });
  }

  trace.recordCompletion({
    step: stepCount,
    modelId: 'gpt-4.1',
    tool: 'web_search',
    latencyMs,
    verdict: success ? 'success' : 'failure',
    reason: success ? 'Grounded answer' : 'Completion checks failed and retries were exhausted.',
    retryCount,
    errorType: success ? undefined : 'BAD_RESULT',
  });

  return trace.finalize();
}

function buildReport(
  scenarioKind: ScenarioSimulationResult['scenario']['kind'],
  pass: boolean,
  score: number,
  runId: string
): ScenarioSuiteReport {
  const scenario = defaultSimulationScenarios.find((item) => item.kind === scenarioKind)!;
  const trace = buildTrace(runId, pass, pass ? 0 : 1, pass ? 1 : 2, pass ? 120 : 260);

  return {
    runAt: `${runId}-at`,
    scenarios: [scenario],
    entries: [
      {
        scenario,
        result: {
          scenario,
          request: {
            source: 'cli',
            text: scenario.input,
            requestId: `${runId}-request`,
          } as ScenarioSimulationResult['request'],
          classification: {} as ScenarioSimulationResult['classification'],
          plan: { taskIntent: scenario.expectations.taskType ?? 'research' } as ScenarioSimulationResult['plan'],
          decision: {
            mode: 'research',
            modelId: 'gpt-4.1',
            modelPerformance: 0.9,
            tools: {
              allowWebSearch: true,
              allowConnectors: true,
              allowLocalTools: false,
              allowBrowser: true,
              preferredTools: ['web_search'],
            },
            steps: {
              complexity: 'medium',
              stepBudget: 3,
              retryLimit: 1,
            },
            reasoning: ['test'],
            artifactCount: 1,
          } as ScenarioSimulationResult['decision'],
          policy: {
            maxSteps: 3,
            maxRetries: 1,
            maxTimeMs: 30_000,
            maxCostUsd: 0.08,
            allowedTools: ['web_search'],
          } as ScenarioSimulationResult['policy'],
          execution: {
            status: pass ? 'success' : 'failure',
            text: pass ? 'Grounded answer' : '',
            sources: pass ? [{ url: 'https://example.com', title: 'Example' }] : [],
            modelId: 'gpt-4.1',
            modelProvider: 'openai',
            completion: null,
            runId,
            error: pass ? undefined : 'BAD_RESULT: completion failed',
          } as ScenarioSimulationResult['execution'],
          trace: {
            ...trace,
            scenario,
            scenarioId: scenario.id,
            scenarioKind: scenario.kind,
            requestId: `${runId}-request`,
            input: scenario.input,
            request: {
              source: 'cli',
              text: scenario.input,
              requestId: `${runId}-request`,
            } as ScenarioSimulationResult['request'],
            decision: {
              mode: 'research',
              modelId: 'gpt-4.1',
              modelPerformance: 0.9,
              tools: {
                allowWebSearch: true,
                allowConnectors: true,
                allowLocalTools: false,
                allowBrowser: true,
                preferredTools: ['web_search'],
              },
              steps: {
                complexity: 'medium',
                stepBudget: 3,
                retryLimit: 1,
              },
              reasoning: ['test'],
              artifactCount: 1,
            } as ScenarioSimulationResult['decision'],
            policy: {
              maxSteps: 3,
              maxRetries: 1,
              maxTimeMs: 30_000,
              maxCostUsd: 0.08,
              allowedTools: ['web_search'],
            } as ScenarioSimulationResult['policy'],
            expected: scenario.expectations,
            modelSwitchObserved: false,
          },
          evaluation: {
            pass,
            scores: {
              decisionQuality: score,
              executionEfficiency: score,
              retryEffectiveness: score,
              toolUsageCorrectness: score,
              overall: score,
              pass,
            },
            diffs: pass
              ? []
              : [
                  {
                    field: 'overall',
                    expected: 0.8,
                    actual: score,
                    reason: 'Regression example',
                  },
                ],
            traceSummary: trace.summary,
            traceMetrics: {
              runCount: 1,
              successRate: pass ? 1 : 0,
              retryCount: trace.summary.retryCount,
              avgLatencyMs: trace.summary.avgLatencyMs,
              estimatedCostUsd: trace.summary.estimatedCostUsd,
              modelSuccessRateByModel: { 'gpt-4.1': pass ? 1 : 0 },
              modelMetrics: [
                {
                  modelId: 'gpt-4.1',
                  runCount: 1,
                  successRate: pass ? 1 : 0,
                  retryCount: trace.summary.retryCount,
                  avgLatencyMs: trace.summary.avgLatencyMs,
                  estimatedCostUsd: trace.summary.estimatedCostUsd,
                },
              ],
            },
          },
        },
      },
    ],
    summary: {
      runCount: 1,
      passCount: pass ? 1 : 0,
      failureCount: pass ? 0 : 1,
      averageScores: {
        decisionQuality: score,
        executionEfficiency: score,
        retryEffectiveness: score,
        toolUsageCorrectness: score,
        overall: score,
      },
      traceMetrics: {
        runCount: 1,
        successRate: pass ? 1 : 0,
        retryCount: trace.summary.retryCount,
        avgLatencyMs: trace.summary.avgLatencyMs,
        estimatedCostUsd: trace.summary.estimatedCostUsd,
        modelSuccessRateByModel: { 'gpt-4.1': pass ? 1 : 0 },
        modelMetrics: [
          {
            modelId: 'gpt-4.1',
            runCount: 1,
            successRate: pass ? 1 : 0,
            retryCount: trace.summary.retryCount,
            avgLatencyMs: trace.summary.avgLatencyMs,
            estimatedCostUsd: trace.summary.estimatedCostUsd,
          },
        ],
      },
      failureSummary: pass
        ? []
        : [
            {
              scenarioId: scenario.id,
              kind: scenario.kind,
              failureType: 'BAD_RESULT',
              reason: 'BAD_RESULT',
            },
          ],
    },
  };
}

describe('eval runner regression comparison', () => {
  it('flags regressions when the current suite drops below the baseline', () => {
    const baseline = buildReport('deep_research', true, 0.9, 'baseline-run');
    const current = buildReport('deep_research', false, 0.4, 'current-run');

    const report = compareBaseline(current, baseline);

    expect(report.regression).toBe(true);
    expect(report.regressions).toHaveLength(1);
    expect(report.scoreDiff.overall).toBeLessThan(0);
    expect(report.failureSummary).toContain('deep-research: BAD_RESULT');
  });
});

