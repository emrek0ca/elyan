import { describe, expect, it } from 'vitest';
import { buildExecutionSurfaceSnapshot, buildOrchestrationPlan } from '@/core/orchestration';
import {
  applyRequestGuardToPlan,
  assertRequestWithinGuard,
  createRequestGuardRuntime,
  RequestGuardError,
  resolveRequestGuard,
  withRequestGuard,
} from '@/core/interaction/request-guard';

describe('request guard', () => {
  it('applies stricter production bounds to research plans', () => {
    const surface = buildExecutionSurfaceSnapshot();
    const plan = buildOrchestrationPlan('Research the current state of model routing tradeoffs.', 'research', surface);
    const guard = resolveRequestGuard(plan, 'Research the current state of model routing tradeoffs.');
    const guardedPlan = applyRequestGuardToPlan(plan, guard);

    expect(guard.mode).toBe('production');
    expect(guard.maxSteps).toBeLessThanOrEqual(4);
    expect(guard.maxRetries).toBeLessThanOrEqual(1);
    expect(guardedPlan.retrieval.rounds).toBeLessThanOrEqual(guard.maxSteps - 1);
    expect(guardedPlan.teamPolicy.maxTasksPerRun).toBeLessThanOrEqual(guard.maxSteps);
  });

  it('rejects oversized input before execution starts', () => {
    const surface = buildExecutionSurfaceSnapshot();
    const plan = buildOrchestrationPlan('Summarize this.', 'speed', surface);
    const guard = resolveRequestGuard(plan, 'Summarize this.');
    const oversized = 'x'.repeat((guard.maxInputTokens + 1) * 4);

    expect(() => assertRequestWithinGuard(oversized, plan, guard)).toThrow(RequestGuardError);
  });

  it('aborts stuck execution with a structured guard error', async () => {
    const surface = buildExecutionSurfaceSnapshot();
    const plan = buildOrchestrationPlan('Quick answer.', 'speed', surface);
    const guard = { ...resolveRequestGuard(plan, 'Quick answer.'), maxExecutionMs: 1 };
    const runtime = createRequestGuardRuntime(guard);

    await expect(
      withRequestGuard(runtime, new Promise((resolve) => setTimeout(resolve, 50)))
    ).rejects.toMatchObject({
      code: 'request_time_limit_exceeded',
      statusCode: 408,
    });

    runtime.clear();
  });
});
