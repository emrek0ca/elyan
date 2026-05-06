import { describe, expect, it } from 'vitest';
import { buildRunMetrics } from '@/core/observability/metrics';
import { classifyFailure } from '@/core/observability/failure-classifier';
import { createRunTrace } from '@/core/observability/run-trace';

describe('observability failure classifier', () => {
  it('classifies timeout, tool, llm, empty output, and bad result failures deterministically', () => {
    expect(classifyFailure({ error: new Error('request timed out'), verdict: 'failure' })?.errorType).toBe('TIMEOUT');
    expect(classifyFailure({ error: new Error('browser tool failed'), tool: 'browser', verdict: 'failure' })?.errorType).toBe('TOOL_ERROR');
    expect(classifyFailure({ error: new Error('openai API key not configured'), verdict: 'failure' })?.errorType).toBe('LLM_ERROR');
    expect(classifyFailure({ outputText: '   ', verdict: 'failure' })?.errorType).toBe('EMPTY_OUTPUT');
    expect(classifyFailure({ failureReason: 'missing required artifacts', outputText: 'valid text', verdict: 'failure' })?.errorType).toBe('BAD_RESULT');
  });
});

describe('observability run trace', () => {
  it('appends events in order and finalizes into a compact summary', () => {
    const trace = createRunTrace({
      runId: 'run_123',
      mode: 'research',
      taskType: 'research',
      modelId: 'gpt-4.1',
      stepBudget: 3,
      retryLimit: 1,
    });

    trace.beforeExecution({
      reasoning: ['use grounded evidence'],
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
      latencyMs: 820,
      success: true,
      retryCount: 0,
    });
    trace.recordCompletion({
      step: 1,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      latencyMs: 820,
      verdict: 'success',
      reason: 'Grounded result',
      retryCount: 0,
    });

    const report = trace.finalize();

    expect(report.runId).toBe('run_123');
    expect(report.events.map((event) => event.kind)).toEqual([
      'before_execution',
      'step_started',
      'step_completed',
      'completion',
    ]);
    expect(report.summary.success).toBe(true);
    expect(report.summary.retryCount).toBe(0);
    expect(report.summary.stepCount).toBe(1);
    expect(report.summary.avgLatencyMs).toBe(820);
    expect(report.summary.estimatedCostUsd).toBeGreaterThan(0);
  });
});

describe('observability metrics', () => {
  it('aggregates success rate, retries, latency, and model performance across traces', () => {
    const successTrace = createRunTrace({
      runId: 'run_success',
      mode: 'research',
      taskType: 'research',
      modelId: 'gpt-4.1',
      stepBudget: 2,
      retryLimit: 1,
    });
    successTrace.beforeExecution();
    successTrace.recordStepStarted({
      step: 1,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      retryCount: 0,
    });
    successTrace.recordStepCompleted({
      step: 1,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      latencyMs: 200,
      success: true,
      retryCount: 0,
    });
    successTrace.recordCompletion({
      step: 1,
      modelId: 'gpt-4.1',
      tool: 'web_search',
      latencyMs: 200,
      verdict: 'success',
      reason: 'Done',
      retryCount: 0,
    });

    const retryTrace = createRunTrace({
      runId: 'run_retry',
      mode: 'task',
      taskType: 'procedural',
      modelId: 'local:model-a',
      stepBudget: 3,
      retryLimit: 1,
    });
    retryTrace.beforeExecution();
    retryTrace.recordStepStarted({
      step: 1,
      modelId: 'local:model-a',
      tool: 'local_tools',
      retryCount: 0,
    });
    retryTrace.recordStepCompleted({
      step: 1,
      modelId: 'local:model-a',
      tool: 'local_tools',
      latencyMs: 150,
      success: false,
      retryCount: 0,
      errorType: 'BAD_RESULT',
    });
    retryTrace.recordCompletion({
      step: 1,
      modelId: 'local:model-a',
      tool: 'local_tools',
      latencyMs: 150,
      verdict: 'retry',
      reason: 'Completion checks suggest a retry is needed.',
      retryCount: 0,
      errorType: 'BAD_RESULT',
    });
    retryTrace.recordStepStarted({
      step: 2,
      modelId: 'local:model-a',
      tool: 'local_tools',
      retryCount: 1,
    });
    retryTrace.recordStepCompleted({
      step: 2,
      modelId: 'local:model-a',
      tool: 'local_tools',
      latencyMs: 250,
      success: false,
      retryCount: 1,
      errorType: 'BAD_RESULT',
    });
    retryTrace.recordCompletion({
      step: 2,
      modelId: 'local:model-a',
      tool: 'local_tools',
      latencyMs: 250,
      verdict: 'failure',
      reason: 'Completion checks failed and retries were exhausted.',
      retryCount: 1,
      errorType: 'BAD_RESULT',
    });

    const metrics = buildRunMetrics([successTrace.finalize(), retryTrace.finalize()]);

    expect(metrics.runCount).toBe(2);
    expect(metrics.successRate).toBe(0.5);
    expect(metrics.retryCount).toBe(1);
    expect(metrics.avgLatencyMs).toBe(200);
    expect(metrics.modelSuccessRateByModel['gpt-4.1']).toBe(1);
    expect(metrics.modelSuccessRateByModel['local:model-a']).toBe(0);
    expect(metrics.modelMetrics).toHaveLength(2);
  });
});
