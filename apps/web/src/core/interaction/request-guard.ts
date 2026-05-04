import { env } from '@/lib/env';
import type { OrchestrationPlan } from '@/core/orchestration';

export type RequestGuard = {
  mode: 'development' | 'production';
  maxExecutionMs: number;
  maxSteps: number;
  maxInputTokens: number;
  maxOutputTokens: number;
  maxCostUnits: number;
  maxRetries: number;
};

export class RequestGuardError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly statusCode = 429
  ) {
    super(message);
    this.name = 'RequestGuardError';
  }
}

export function estimateTextTokens(value: string) {
  return Math.max(1, Math.ceil(value.length / 4));
}

function sumUsageBudget(plan: OrchestrationPlan) {
  return (
    (plan.usageBudget?.inference ?? 0) +
    (plan.usageBudget?.retrieval ?? 0) +
    (plan.usageBudget?.integrations ?? 0) +
    (plan.usageBudget?.evaluation ?? 0)
  );
}

export function resolveRequestGuard(plan: OrchestrationPlan, inputText: string): RequestGuard {
  const mode = env.ELYAN_MODE;
  const production = mode === 'production';
  const researchLike =
    plan.mode === 'research' ||
    plan.taskIntent === 'research' ||
    plan.taskIntent === 'comparison' ||
    plan.reasoningDepth === 'deep';
  const teamLike = plan.executionMode === 'team';
  const inputTokens = estimateTextTokens(inputText);

  return {
    mode,
    maxExecutionMs: production
      ? teamLike
        ? 45_000
        : researchLike
          ? 35_000
          : 18_000
      : teamLike
        ? 90_000
        : researchLike
          ? 75_000
          : 35_000,
    maxSteps: production
      ? teamLike
        ? 4
        : researchLike
          ? 4
          : 2
      : teamLike
        ? 8
        : researchLike
          ? 6
          : 3,
    maxInputTokens: production ? Math.max(1_200, Math.min(6_000, inputTokens + 4_000)) : 12_000,
    maxOutputTokens: production ? (researchLike ? 1_000 : 700) : researchLike ? 1_600 : 1_000,
    maxCostUnits: production ? (researchLike ? 6 : 3) : researchLike ? 12 : 6,
    maxRetries: production ? (researchLike ? 1 : 0) : 1,
  };
}

export function applyRequestGuardToPlan(plan: OrchestrationPlan, guard: RequestGuard): OrchestrationPlan {
  const currentRetrieval = plan.retrieval ?? {
    rounds: plan.searchRounds ?? 0,
    maxUrls: plan.maxUrls ?? 0,
    rerankTopK: 0,
    language: 'en',
    expandSearchQueries: false,
  };
  const currentTeamPolicy = plan.teamPolicy ?? {
    enabledByDefault: false,
    reasons: ['Default single-run guard policy.'],
    maxConcurrentAgents: 1,
    maxTasksPerRun: 2,
    allowCloudEscalation: false,
    modelRoutingMode: plan.routingMode,
    riskBoundary: 'read_only',
    requiredRoles: [],
  };
  const retrievalRounds = Math.min(currentRetrieval.rounds, Math.max(0, guard.maxSteps - 1));
  const maxUrls = Math.min(plan.maxUrls ?? currentRetrieval.maxUrls, guard.mode === 'production' ? 6 : 10);
  const teamMaxTasks = Math.max(2, Math.min(currentTeamPolicy.maxTasksPerRun, guard.maxSteps));

  return {
    ...plan,
    searchRounds: Math.min(plan.searchRounds, retrievalRounds),
    maxUrls,
    retrieval: {
      ...currentRetrieval,
      rounds: retrievalRounds,
      maxUrls: Math.min(currentRetrieval.maxUrls, maxUrls),
      rerankTopK: Math.min(currentRetrieval.rerankTopK, guard.mode === 'production' ? 8 : 12),
    },
    teamPolicy: {
      ...currentTeamPolicy,
      maxTasksPerRun: teamMaxTasks,
      maxConcurrentAgents: Math.min(currentTeamPolicy.maxConcurrentAgents, guard.mode === 'production' ? 2 : 3),
    },
    usageBudget: {
      inference: Math.min(plan.usageBudget?.inference ?? 0, guard.maxCostUnits),
      retrieval: Math.min(plan.usageBudget?.retrieval ?? 0, guard.maxCostUnits),
      integrations: Math.min(plan.usageBudget?.integrations ?? 0, guard.maxCostUnits),
      evaluation: Math.min(plan.usageBudget?.evaluation ?? 0, guard.maxCostUnits),
    },
  };
}

export function assertRequestWithinGuard(text: string, plan: OrchestrationPlan, guard: RequestGuard) {
  const inputTokens = estimateTextTokens(text);
  if (inputTokens > guard.maxInputTokens) {
    throw new RequestGuardError(
      'request_input_too_large',
      `Request exceeds the ${guard.maxInputTokens} token input limit.`,
      413
    );
  }

  const costUnits = sumUsageBudget(plan);
  if (costUnits > guard.maxCostUnits * 2) {
    throw new RequestGuardError(
      'request_cost_cap_exceeded',
      `Request exceeds the ${guard.maxCostUnits} cost unit guardrail.`,
      429
    );
  }
}

export function createRequestGuardRuntime(guard: RequestGuard) {
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort(
      new RequestGuardError(
        'request_time_limit_exceeded',
        `Request exceeded the ${guard.maxExecutionMs}ms execution limit.`,
        408
      )
    );
  }, guard.maxExecutionMs);

  const clear = () => clearTimeout(timeout);
  const assertActive = () => {
    if (controller.signal.aborted) {
      throw controller.signal.reason instanceof Error
        ? controller.signal.reason
        : new RequestGuardError('request_aborted', 'Request was aborted by the execution guard.', 408);
    }
  };

  return {
    signal: controller.signal,
    clear,
    assertActive,
  };
}

export async function withRequestGuard<T>(
  runtime: ReturnType<typeof createRequestGuardRuntime>,
  operation: Promise<T>
): Promise<T> {
  runtime.assertActive();

  return await Promise.race([
    operation,
    new Promise<T>((_, reject) => {
      runtime.signal.addEventListener(
        'abort',
        () => {
          reject(
            runtime.signal.reason instanceof Error
              ? runtime.signal.reason
              : new RequestGuardError('request_aborted', 'Request was aborted by the execution guard.', 408)
          );
        },
        { once: true }
      );
    }),
  ]);
}
