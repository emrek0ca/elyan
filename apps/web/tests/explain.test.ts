import { describe, expect, it } from 'vitest';
import { explainExecution, formatExecutionExplanation } from '@/core/execution/explain';
import { createRunTrace } from '@/core/observability/run-trace';
import { buildOperatorRun } from '@/core/operator/runs';
import type { ExecutionCompletionResult } from '@/core/execution/completion-engine';

function buildSuccessCompletion(): ExecutionCompletionResult {
  return {
    verdict: 'success',
    reason: 'Grounded output passed completion checks.',
    retryLimit: 1,
    attempt: 0,
    requiredArtifacts: ['research'],
    missingArtifacts: [],
    verification: {
      status: 'passed',
      summary: 'Completion checks passed.',
    },
    shouldTriggerLearning: true,
    finalRunStatus: 'completed',
  };
}

function buildRetryCompletion(): ExecutionCompletionResult {
  return {
    verdict: 'retry',
    reason: 'Missing required artifacts.',
    retryLimit: 2,
    attempt: 0,
    requiredArtifacts: ['summary'],
    missingArtifacts: ['summary'],
    retryPlan: {
      modelStrategy: 'alternate',
      promptHints: ['Tighten the answer.', 'Include a summary artifact.'],
      toolVariation: 'connectors',
      searchEnabled: false,
    },
    verification: {
      status: 'blocked',
      summary: 'Completion checks are incomplete.',
    },
    shouldTriggerLearning: false,
    finalRunStatus: 'failed',
  };
}

describe('execution explainability', () => {
  it('explains a successful research run deterministically', () => {
    const run = buildOperatorRun({
      source: 'cli',
      text: 'Research the latest hosted control-plane status and summarize the sources.',
      mode: 'research',
    });
    const trace = createRunTrace({
      runId: run.id,
      mode: 'research',
      taskType: 'research',
      modelId: 'gpt-4.1',
      stepBudget: 3,
      retryLimit: 1,
    });

    trace.beforeExecution({
      decisionReasoning: ['Query is research-oriented.', 'Policy allows web search.'],
      policy: {
        maxSteps: 3,
        maxRetries: 1,
        maxTimeMs: 30000,
        maxCostUsd: 0.1,
        allowedTools: ['web_search'],
      },
      artifactCount: 2,
      modelPerformance: {
        'gpt-4.1': 1,
      },
    });
    trace.recordStepStarted({
      step: 1,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      retryCount: 0,
    });
    trace.recordStepCompleted({
      step: 1,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      latencyMs: 180,
      success: true,
      retryCount: 0,
    });
    trace.recordCompletion({
      step: 1,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      latencyMs: 180,
      verdict: 'success',
      reason: 'Grounded output passed completion checks.',
      retryCount: 0,
    });

    const explanation = explainExecution({
      run,
      completion: buildSuccessCompletion(),
      trace: trace.finalize(),
      artifacts: run.artifacts,
    });

    expect(explanation.planSummary).toContain('Research run');
    expect(explanation.stepsTaken).toHaveLength(run.steps.length);
    expect(explanation.toolsUsed).toContain('web_search');
    expect(explanation.whyDecisionsWereMade.join(' ')).toContain('Policy constraints');
    expect(explanation.confidenceScore).toBeGreaterThan(0.7);
    expect(formatExecutionExplanation(explanation)).toContain('Confidence score:');
  });

  it('explains a retrying code run with lower confidence', () => {
    const run = buildOperatorRun({
      source: 'cli',
      text: 'Implement a small code change and verify it.',
      mode: 'code',
    });
    const trace = createRunTrace({
      runId: run.id,
      mode: 'task',
      taskType: 'code',
      modelId: 'local:model-a',
      stepBudget: 4,
      retryLimit: 2,
    });

    trace.beforeExecution({
      decisionReasoning: ['Task is procedural and requires local tools.'],
      policy: {
        maxSteps: 4,
        maxRetries: 2,
        maxTimeMs: 60000,
        maxCostUsd: 0.2,
        allowedTools: ['local_tools'],
      },
      artifactCount: 0,
      modelPerformance: {
        'local:model-a': 0,
      },
    });
    trace.recordStepStarted({
      step: 1,
      modelId: 'local:model-a',
      tool: 'local_tools',
      retryCount: 0,
    });
    trace.recordStepCompleted({
      step: 1,
      modelId: 'local:model-a',
      tool: 'local_tools',
      latencyMs: 320,
      success: false,
      retryCount: 0,
      errorType: 'BAD_RESULT',
    });
    trace.recordCompletion({
      step: 1,
      modelId: 'local:model-a',
      tool: 'local_tools',
      latencyMs: 320,
      verdict: 'retry',
      reason: 'Missing required artifacts.',
      retryCount: 0,
      errorType: 'BAD_RESULT',
    });

    const explanation = explainExecution({
      run,
      completion: buildRetryCompletion(),
      trace: trace.finalize(),
      artifacts: run.artifacts,
    });

    expect(explanation.planSummary).toContain('It required another pass');
    expect(explanation.whyDecisionsWereMade.join(' ')).toContain('Retry guidance');
    expect(explanation.toolsUsed).toContain('local_tools');
    expect(explanation.confidenceScore).toBeLessThan(0.85);
    expect(explanation.summary).toContain('Confidence');
  });
});
