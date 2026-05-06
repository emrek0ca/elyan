import { randomUUID } from 'crypto';
import type { LanguageModelUsage } from 'ai';
import { answerEngine } from '@/core/agents/answer-engine';
import { getControlPlaneService, isControlPlaneSessionConfigured } from '@/core/control-plane';
import { ControlPlaneAuthenticationError, ControlPlaneInsufficientCreditsError, ControlPlaneUsageLimitError } from '@/core/control-plane/errors';
import type { ControlPlaneSessionToken } from '@/core/control-plane/session';
import { buildExecutionSurfaceSnapshot, buildOrchestrationPlan } from '@/core/orchestration';
import { buildReasoningPlanSummary, buildReasoningTrace } from '@/core/reasoning';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import { decideExecution, type ExecutionDecision } from '@/core/decision/engine';
import { decidePolicy, type PolicyEngineOutput } from '@/core/control/policy-engine';
import { evaluateExecutionCompletion, type ExecutionCompletionArtifact, type ExecutionCompletionOutput, type ExecutionCompletionResult } from '@/core/execution/completion-engine';
import { explainExecution, formatExecutionExplanation, type ExecutionExplanation } from '@/core/execution/explain';
import { buildRunMetrics } from '@/core/observability/metrics';
import { classifyFailure } from '@/core/observability/failure-classifier';
import { createRunTrace, type RunTraceReport, type RunTraceRecorder } from '@/core/observability/run-trace';
import { solveHybridOptimization } from '@/core/capabilities/quantum/hybrid_solver';
import { registry } from '@/core/providers';
import { teamRunner } from '@/core/teams';
import { getOperatorRunStore, recordOperatorRunArtifact, type OperatorArtifact, type OperatorRun } from '@/core/operator/runs';
import { buildQualityAssessment, resolveTeacherModel, type MlDatasetCandidate } from '@/core/ml';
import { loadLearningPromptHints } from '@/core/control-plane/learning/signal-extractor';
import type { SearchMode } from '@/types/search';
import type { ExecutionSurfaceSnapshot, OrchestrationPlan } from '@/core/orchestration';
import { classifyInteractionIntent } from './intent';
import { type OperatorSource } from '@/core/operator/types';
import { estimateHostedRequestTokens, estimateHostedUsageDraft, estimateRunCostUsd } from '@/core/control-plane/pricing';
import { captureRepositorySnapshot } from '@/core/orchestration/repo-inspection';
import { resolveScenarioRequest } from '@/core/scenarios';
import type { CapabilityRuntimeContext } from '@/core/capabilities/types';

export type InteractionResponseKind = 'text' | 'stream';
type ControlPlaneServiceInstance = ReturnType<typeof getControlPlaneService>;
type HostedAccountView = Awaited<ReturnType<ControlPlaneServiceInstance['getAccount']>>;

export type InteractionRequest = {
  source: OperatorSource;
  text: string;
  mode?: SearchMode;
  modelId?: string;
  conversationId?: string;
  messageId?: string;
  userId?: string;
  displayName?: string;
  metadata?: Record<string, string>;
  responseKind?: InteractionResponseKind;
  requireHostedSession?: boolean;
  controlPlaneSession?: ControlPlaneSessionToken | null;
  requestId?: string;
  runtimeContext?: CapabilityRuntimeContext;
  signal?: AbortSignal;
};

export type InteractionTextResponse = {
  text: string;
  sources: Array<{ url: string; title: string }>;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  modelId: string;
  classification: ReturnType<typeof classifyInteractionIntent>;
  runId?: string;
};

type PreparedInteraction = {
  requestId: string;
  classification: ReturnType<typeof classifyInteractionIntent>;
  mode: SearchMode;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  decision: ExecutionDecision;
  policy: PolicyEngineOutput;
  selectedModelId: string;
  memoryContext: string[];
  controlPlaneSession?: ControlPlaneSessionToken | null;
  runtimeContext?: CapabilityRuntimeContext;
  signal?: AbortSignal;
  hostedAccountId?: string;
  spaceId?: string;
  hostedAccount?: HostedAccountView | null;
  operatorRun?: OperatorRun;
  observabilityTrace: RunTraceRecorder;
  startedAt: number;
  queryLength: number;
  estimatedRequestTokens: number;
  estimatedRunCostUsd: number;
};

async function loadLearningContextAugments(prepared: PreparedInteraction) {
  const learningHints = await loadLearningPromptHints({
    taskType: prepared.plan.taskIntent,
    modelId: prepared.selectedModelId,
    spaceId: prepared.spaceId,
  });

  return [...prepared.memoryContext, ...learningHints];
}

function createEmptyLanguageModelUsage(): LanguageModelUsage {
  return {
    inputTokens: undefined,
    inputTokenDetails: {
      noCacheTokens: undefined,
      cacheReadTokens: undefined,
      cacheWriteTokens: undefined,
    },
    outputTokens: undefined,
    outputTokenDetails: {
      textTokens: undefined,
      reasoningTokens: undefined,
    },
    totalTokens: undefined,
  };
}

function normalizeError(error: unknown) {
  const message = error instanceof Error ? error.message.toLowerCase() : '';

  if (message.includes('no models are currently available')) {
    return {
      code: 'model_not_configured',
      message: 'No model provider configured',
      status: 503,
    };
  }

  if (message.includes('no model provider configured')) {
    return {
      code: 'model_not_configured',
      message: 'No model provider configured',
      status: 503,
    };
  }

  if (message.includes('api key not configured')) {
    return {
      code: 'provider_not_configured',
      message: 'The selected cloud provider is not configured. Add the required API key or choose another model.',
      status: 503,
    };
  }

  if (message.includes('control-plane session is required')) {
    return {
      code: 'control_plane_session_required',
      message: 'Login is required for the main chat surface. Use the public preview or sign in first.',
      status: 401,
    };
  }

  if (error instanceof ControlPlaneUsageLimitError) {
    return {
      code: 'hosted_usage_limit_reached',
      message: error.message,
      status: 429,
    };
  }

  if (error instanceof ControlPlaneInsufficientCreditsError) {
    return {
      code: 'hosted_credits_exhausted',
      message: error.message,
      status: 402,
    };
  }

  if (message.includes('hosted usage is disabled')) {
    return {
      code: 'hosted_usage_disabled',
      message: 'Hosted usage is not allowed for this plan. Use the local runtime or upgrade to a hosted plan.',
      status: 403,
    };
  }

  if (message.includes('hosted usage is not active')) {
    return {
      code: 'hosted_usage_inactive',
      message: 'Hosted usage is not active for this subscription yet.',
      status: 403,
    };
  }

  if (message.includes('insufficient credits')) {
    return {
      code: 'hosted_credits_exhausted',
      message: 'Hosted credits are exhausted for this account.',
      status: 402,
    };
  }

  if (message.includes('elyan boot failure') || message.includes('invalid environment')) {
    return {
      code: 'invalid_environment',
      message: 'Environment configuration is invalid. Check Elyan startup settings.',
      status: 503,
    };
  }

  if (error && typeof error === 'object' && 'statusCode' in error) {
    return {
      code: 'request_failed',
      message: error instanceof Error ? error.message : 'The current request could not be completed.',
      status: Number((error as { statusCode: number }).statusCode) || 500,
    };
  }

  return {
    code: 'request_failed',
    message: error instanceof Error ? error.message : 'The current request could not be completed.',
    status: 500,
  };
}

function pickSelectedModelId(plan: OrchestrationPlan, requestedModelId?: string) {
  const runtimeSettings = readRuntimeSettingsSync();
  const routingMode =
    plan.executionMode === 'team' && runtimeSettings.team.enabled
      ? runtimeSettings.team.allowCloudEscalation
        ? plan.routingMode
        : plan.teamPolicy.modelRoutingMode
      : plan.routingMode;
  const preferredModelId =
    routingMode === 'local_only' && requestedModelId && /(?:^|:)(?:openai|anthropic|azure|google|gemini|claude|gpt|perplexity|openrouter)/i.test(requestedModelId)
      ? undefined
      : requestedModelId?.trim();

  return registry.resolvePreferredModelId({
    preferredModelId,
    routingMode,
    taskIntent: plan.taskIntent,
    reasoningDepth: plan.reasoningDepth,
  });
}

function buildCompletionArtifactPreview(
  prepared: PreparedInteraction,
  output: ExecutionCompletionOutput,
  attempt: number
): ExecutionCompletionArtifact {
  const createdAt = new Date().toISOString();
  const kind = prepared.operatorRun?.mode === 'research' ? 'research' : 'summary';
  const title = prepared.operatorRun?.mode === 'research' ? `Research attempt ${attempt + 1}` : `Execution attempt ${attempt + 1}`;

  return {
    id: `completion_${prepared.requestId}_${attempt}`,
    runId: prepared.operatorRun?.id ?? prepared.requestId,
    kind,
    title,
    content: [
      'Answer:',
      output.text || 'No answer was produced.',
      '',
      output.sources.length > 0
        ? 'Sources:'
        : 'Sources: none',
      ...output.sources.map((source, index) => `[${index + 1}] ${source.title} - ${source.url}`),
    ].join('\n'),
    createdAt,
    metadata: {
      sourceCount: output.sources.length,
      attempt,
      modelId: output.modelId,
      modelProvider: output.modelProvider,
      failureReason: output.failureReason,
      taskIntent: prepared.plan.taskIntent,
      routingMode: prepared.plan.routingMode,
      isRetryPreview: true,
    },
  };
}

async function resolveRetryModelId(currentModelId: string) {
  const availableModels = await registry.listAvailableModels().catch(() => []);
  if (availableModels.length <= 1) {
    return currentModelId;
  }

  const currentModel = availableModels.find((model) => model.id === currentModelId);
  const currentLooksLocal =
    currentModel?.type === 'local' ||
    /^(ollama:|local:|lmstudio:|llama\.cpp:|openai:gpt-oss|anthropic:.*local)/i.test(currentModelId) ||
    /\b(local|ollama|lmstudio|llama)\b/i.test(currentModelId);

  const alternateModel =
    currentLooksLocal
      ? availableModels.find((model) => model.type === 'cloud' && model.id !== currentModelId) ??
        availableModels.find((model) => model.id !== currentModelId)
      : availableModels.find((model) => model.type === 'local' && model.id !== currentModelId) ??
        availableModels.find((model) => model.id !== currentModelId);

  return alternateModel?.id ?? currentModelId;
}

function buildRetryContextAugments(baseAugments: string[], completion: ExecutionCompletionResult) {
  const hints = completion.retryPlan?.promptHints ?? [];
  return [...baseAugments, ...hints];
}

function resolveQueryComplexity(query: string, mode: ExecutionDecision['mode']) {
  const normalized = query.replace(/\s+/g, ' ').trim();
  const length = normalized.length;
  const hasMultipleClauses = /[;,.!?].*[;,.!?]/.test(normalized) || /\b(and|then|after|before|while|plus)\b/i.test(normalized);

  if (mode === 'fast') {
    return length > 120 || hasMultipleClauses ? 'medium' : 'low';
  }

  if (mode === 'research') {
    return length > 180 || hasMultipleClauses ? 'high' : 'medium';
  }

  return length > 180 || hasMultipleClauses ? 'high' : length > 100 ? 'medium' : 'low';
}

function hasAllowedTool(policy: PolicyEngineOutput, tool: string) {
  return policy.allowedTools.includes(tool);
}

function buildExecutionBudgetError(
  message: string,
  details: {
    limitType: 'per_request_token_limit' | 'run_cost_cap';
    planId?: string;
    remainingTokens?: number;
  }
) {
  return new ControlPlaneUsageLimitError(message, {
    limitType: details.limitType,
    remainingTokens: details.remainingTokens,
    planId: details.planId,
  });
}

function resolveTraceTool(prepared: PreparedInteraction, searchEnabled: boolean, teamExecution: boolean) {
  if (teamExecution) {
    return 'team_runner';
  }

  if (searchEnabled) {
    return 'web_search';
  }

  if (prepared.decision.tools.allowLocalTools) {
    return 'local_tools';
  }

  if (prepared.decision.tools.allowConnectors) {
    return 'connectors';
  }

  return 'direct_answer';
}

function buildFinalFailureArtifact(
  prepared: PreparedInteraction,
  output: ExecutionCompletionOutput,
  completion: ExecutionCompletionResult,
  observabilityTrace?: RunTraceReport,
  executionExplanation?: ExecutionExplanation
): OperatorArtifact {
  const createdAt = new Date().toISOString();
  const metadata: Record<string, unknown> = {
    sourceCount: output.sources.length,
    modelId: output.modelId,
    modelProvider: output.modelProvider,
    failureReason: completion.reason,
    retryLimit: completion.retryLimit,
    attempt: completion.attempt,
    taskIntent: prepared.plan.taskIntent,
    routingMode: prepared.plan.routingMode,
    finalRunStatus: completion.finalRunStatus,
  };

  if (executionExplanation) {
    Object.assign(metadata, {
      executionExplanation,
    });
  }

  if (observabilityTrace) {
    Object.assign(metadata, {
      observabilityTrace,
      observabilityMetrics: buildRunMetrics([observabilityTrace]),
    });
  }

  return {
    id: `completion_failed_${prepared.requestId}`,
    runId: prepared.operatorRun?.id ?? prepared.requestId,
    kind: prepared.operatorRun?.mode === 'research' ? 'research' : 'summary',
    title: 'Completion failure',
    content: [
      'Answer:',
      output.text || 'No final answer was produced.',
      '',
      'Completion failure:',
      completion.reason,
      '',
      output.sources.length > 0
        ? 'Sources:'
        : 'Sources: none',
      ...output.sources.map((source, index) => `[${index + 1}] ${source.title} - ${source.url}`),
      '',
      executionExplanation ? 'Execution explanation:' : 'Execution explanation: unavailable',
      ...(executionExplanation ? formatExecutionExplanation(executionExplanation).split('\n') : []),
    ].join('\n'),
    createdAt,
    metadata,
  };
}

async function finalizeFailedOperatorRun(
  prepared: PreparedInteraction,
  output: ExecutionCompletionOutput,
  completion: ExecutionCompletionResult,
  observabilityTrace?: RunTraceReport,
  executionExplanation?: ExecutionExplanation
) {
  if (!prepared.operatorRun) {
    return;
  }

  const store = getOperatorRunStore();
  const run = (await store.get(prepared.operatorRun.id)) ?? prepared.operatorRun;
  const failedAt = new Date().toISOString();
  const failureArtifact = buildFinalFailureArtifact(prepared, output, completion, observabilityTrace, executionExplanation);
  const nextContinuity =
    run.continuity ?? {
      summary: 'Execution completion failed before a terminal artifact could be accepted.',
      nextSteps: [],
      openItemCount: 0,
      lastActivityAt: failedAt,
    };

  await store.write({
    ...run,
    status: 'failed',
    updatedAt: failedAt,
    artifacts: [...(run.artifacts ?? []), failureArtifact],
    verification: {
      status: 'failed',
      summary: completion.reason,
      checkedAt: failedAt,
    },
    continuity: {
      ...nextContinuity,
      lastActivityAt: failedAt,
    },
    notes: [
      ...(run.notes ?? []),
      `Completion engine failed after ${completion.attempt + 1} attempt(s): ${completion.reason}`,
    ],
  });
}

type CompletionAwareResult = {
  text: string;
  sources: Array<{ url: string; title: string }>;
  modelId: string;
  modelProvider: string;
  plan: OrchestrationPlan;
  completion: ExecutionCompletionResult;
  learningMetadata?: Record<string, unknown>;
};

class ExecutionCompletionFailureError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ExecutionCompletionFailureError';
  }
}

async function executeCompletionAwareInteraction(
  prepared: PreparedInteraction,
  request: InteractionRequest,
  runtimeSettings: ReturnType<typeof readRuntimeSettingsSync>,
  baseContextAugments: string[]
): Promise<CompletionAwareResult> {
  const retryLimit = Math.max(0, Math.min(prepared.decision.steps.retryLimit, prepared.policy.maxRetries));
  let currentModelId = prepared.selectedModelId;
  let currentContextAugments = baseContextAugments;
  let currentSearchEnabled = runtimeSettings.routing.searchEnabled && prepared.decision.tools.allowWebSearch && hasAllowedTool(prepared.policy, 'web_search');
  let lastCompletion: ExecutionCompletionResult | null = null;
  let lastOutput: CompletionAwareResult | null = null;

  for (let attempt = 0; attempt <= retryLimit; attempt += 1) {
    if (Date.now() - prepared.startedAt > prepared.policy.maxTimeMs) {
      break;
    }

    const { provider } = registry.resolveModel(currentModelId);
    const providerId = provider.id;
    const step = attempt + 1;
    const traceTool = resolveTraceTool(prepared, currentSearchEnabled, false);
    const stepStartedAt = Date.now();

    prepared.observabilityTrace.recordStepStarted({
      step,
      modelId: currentModelId,
      tool: traceTool,
      retryCount: attempt,
      details: {
        path: 'answer_engine',
        searchEnabled: currentSearchEnabled,
      },
    });

    try {
      const result = await answerEngine.executeText(request.text, currentModelId, prepared.mode, {
        plan: prepared.plan,
        surface: prepared.surface,
        accountId: prepared.hostedAccountId,
        spaceId: prepared.spaceId,
        searchEnabled: currentSearchEnabled,
        contextAugments: currentContextAugments,
        operatorRunId: prepared.operatorRun?.id,
        runtimeContext: prepared.runtimeContext,
        signal: prepared.signal,
      });

      const output: ExecutionCompletionOutput = {
        text: result.text,
        sources: result.sources.map((source) => ({ url: source.url, title: source.title })),
        success: true,
        modelId: currentModelId,
        modelProvider: providerId,
      };
      const completionArtifacts = [
        ...(prepared.operatorRun?.artifacts ?? []),
        buildCompletionArtifactPreview(prepared, output, attempt),
      ];
      const completion = evaluateExecutionCompletion({
        run: prepared.operatorRun ?? ({} as OperatorRun),
        steps: prepared.operatorRun?.steps ?? [],
        outputs: [output],
        artifacts: completionArtifacts,
        attempt,
        retryLimit,
        taskIntent: prepared.plan.taskIntent,
        routingMode: prepared.plan.routingMode,
      });
      const stepLatencyMs = Date.now() - stepStartedAt;
      const completionError = completion.verdict === 'success'
        ? undefined
        : classifyFailure({
            outputText: output.text,
            failureReason: completion.reason,
            verdict: completion.verdict,
            tool: traceTool,
            modelId: currentModelId,
            modelProvider: providerId,
            sourcesCount: output.sources.length,
          })?.errorType;

      prepared.observabilityTrace.recordStepCompleted({
        step,
        modelId: currentModelId,
        tool: traceTool,
        latencyMs: stepLatencyMs,
        success: output.success === true,
        retryCount: attempt,
        errorType: completionError,
        details: {
          sourceCount: output.sources.length,
          verdict: completion.verdict,
        },
      });
      prepared.observabilityTrace.recordCompletion({
        step,
        modelId: currentModelId,
        tool: traceTool,
        latencyMs: stepLatencyMs,
        success: completion.verdict === 'success',
        verdict: completion.verdict,
        reason: completion.reason,
        retryCount: attempt,
        errorType: completionError,
        details: {
          sourceCount: output.sources.length,
          searchEnabled: currentSearchEnabled,
        },
      });

      lastCompletion = completion;
      lastOutput = {
        text: result.text,
        sources: output.sources,
        modelId: currentModelId,
        modelProvider: providerId,
        plan: result.plan ?? prepared.plan,
        completion,
      };

      if (completion.verdict === 'retry' && attempt < retryLimit) {
        currentModelId = await resolveRetryModelId(currentModelId);
        currentSearchEnabled = completion.retryPlan?.searchEnabled ?? currentSearchEnabled;
        currentContextAugments = buildRetryContextAugments(baseContextAugments, completion);
        continue;
      }

      break;
    } catch (error) {
      const output: ExecutionCompletionOutput = {
        text: '',
        sources: [],
        success: false,
        failureReason: normalizeError(error).message,
        modelId: currentModelId,
        modelProvider: providerId,
      };
      const completionArtifacts = [
        ...(prepared.operatorRun?.artifacts ?? []),
        buildCompletionArtifactPreview(prepared, output, attempt),
      ];
      const completion = evaluateExecutionCompletion({
        run: prepared.operatorRun ?? ({} as OperatorRun),
        steps: prepared.operatorRun?.steps ?? [],
        outputs: [output],
        artifacts: completionArtifacts,
        attempt,
        retryLimit,
        taskIntent: prepared.plan.taskIntent,
        routingMode: prepared.plan.routingMode,
      });
      const stepLatencyMs = Date.now() - stepStartedAt;
      const classifiedFailure = classifyFailure({
        error,
        outputText: output.text,
        failureReason: completion.reason,
        verdict: completion.verdict,
        tool: traceTool,
        modelId: currentModelId,
        modelProvider: providerId,
        sourcesCount: output.sources.length,
      });

      prepared.observabilityTrace.recordStepCompleted({
        step,
        modelId: currentModelId,
        tool: traceTool,
        latencyMs: stepLatencyMs,
        success: false,
        retryCount: attempt,
        errorType: classifiedFailure?.errorType,
        details: {
          error: normalizeError(error).message,
          path: 'answer_engine',
        },
      });
      prepared.observabilityTrace.recordCompletion({
        step,
        modelId: currentModelId,
        tool: traceTool,
        latencyMs: stepLatencyMs,
        success: completion.verdict === 'success',
        verdict: completion.verdict,
        reason: completion.reason,
        retryCount: attempt,
        errorType: classifiedFailure?.errorType,
        details: {
          error: normalizeError(error).message,
          searchEnabled: currentSearchEnabled,
        },
      });

      lastCompletion = completion;
      lastOutput = {
        text: output.text,
        sources: output.sources,
        modelId: currentModelId,
        modelProvider: providerId,
        plan: prepared.plan,
        completion,
      };

      if (completion.verdict === 'retry' && attempt < retryLimit) {
        currentModelId = await resolveRetryModelId(currentModelId);
        currentSearchEnabled = completion.retryPlan?.searchEnabled ?? currentSearchEnabled;
        currentContextAugments = buildRetryContextAugments(baseContextAugments, completion);
        continue;
      }

      break;
    }
  }

  if (!lastCompletion || !lastOutput) {
    throw new Error('Execution completion could not be evaluated.');
  }

  const normalizedCompletion =
    lastCompletion.verdict === 'retry'
      ? {
          ...lastCompletion,
          verdict: 'failure' as const,
          verification: {
            ...lastCompletion.verification,
            status: 'failed' as const,
          },
          finalRunStatus: 'failed' as const,
        }
      : lastCompletion;

  return {
    ...lastOutput,
    plan: lastOutput.plan ?? prepared.plan,
    completion: normalizedCompletion,
  };
}

async function executeTeamCompletionAwareInteraction(
  prepared: PreparedInteraction,
  request: InteractionRequest,
  runtimeSettings: ReturnType<typeof readRuntimeSettingsSync>,
  baseContextAugments: string[]
): Promise<CompletionAwareResult> {
  const retryLimit = Math.max(0, Math.min(prepared.decision.steps.retryLimit, prepared.policy.maxRetries));
  let currentModelId = prepared.selectedModelId;
  let currentContextAugments = baseContextAugments;
  let currentSearchEnabled = runtimeSettings.routing.searchEnabled && prepared.decision.tools.allowWebSearch && hasAllowedTool(prepared.policy, 'web_search');
  let lastCompletion: ExecutionCompletionResult | null = null;
  let lastOutput: CompletionAwareResult | null = null;

  for (let attempt = 0; attempt <= retryLimit; attempt += 1) {
    if (Date.now() - prepared.startedAt > prepared.policy.maxTimeMs) {
      break;
    }

    const step = attempt + 1;
    const traceTool = resolveTraceTool(prepared, currentSearchEnabled, true);
    const stepStartedAt = Date.now();

    prepared.observabilityTrace.recordStepStarted({
      step,
      modelId: currentModelId,
      tool: traceTool,
      retryCount: attempt,
      details: {
        path: 'team_runner',
        searchEnabled: currentSearchEnabled,
      },
    });

    try {
      const team = await teamRunner.run({
        query: request.text,
        mode: prepared.mode,
        requestedModelId: currentModelId,
        sourcePlan: prepared.plan,
        maxConcurrentAgents: runtimeSettings.team.maxConcurrentAgents,
        maxTasksPerRun: runtimeSettings.team.maxTasksPerRun,
        allowCloudEscalation: runtimeSettings.team.allowCloudEscalation,
        contextAugments: currentContextAugments,
        searchEnabled: currentSearchEnabled,
      });

      const output: ExecutionCompletionOutput = {
        text: team.text,
        sources: team.sources.map((source) => ({ url: source.url, title: source.title })),
        success: Boolean(team.summary.verifier.passed),
        modelId: team.modelId,
        modelProvider: team.modelProvider,
      };
      const completionArtifacts = [
        ...(prepared.operatorRun?.artifacts ?? []),
        buildCompletionArtifactPreview(prepared, output, attempt),
      ];
      const completion = evaluateExecutionCompletion({
        run: prepared.operatorRun ?? ({} as OperatorRun),
        steps: prepared.operatorRun?.steps ?? [],
        outputs: [output],
        artifacts: completionArtifacts,
        attempt,
        retryLimit,
        taskIntent: prepared.plan.taskIntent,
        routingMode: prepared.plan.routingMode,
      });
      const stepLatencyMs = Date.now() - stepStartedAt;
      const completionError = completion.verdict === 'success'
        ? undefined
        : classifyFailure({
            outputText: output.text,
            failureReason: completion.reason,
            verdict: completion.verdict,
            tool: traceTool,
            modelId: currentModelId,
            modelProvider: output.modelProvider,
            sourcesCount: output.sources.length,
          })?.errorType;

      prepared.observabilityTrace.recordStepCompleted({
        step,
        modelId: currentModelId,
        tool: traceTool,
        latencyMs: stepLatencyMs,
        success: output.success === true,
        retryCount: attempt,
        errorType: completionError,
        details: {
          sourceCount: output.sources.length,
          verdict: completion.verdict,
        },
      });
      prepared.observabilityTrace.recordCompletion({
        step,
        modelId: currentModelId,
        tool: traceTool,
        latencyMs: stepLatencyMs,
        success: completion.verdict === 'success',
        verdict: completion.verdict,
        reason: completion.reason,
        retryCount: attempt,
        errorType: completionError,
        details: {
          sourceCount: output.sources.length,
          searchEnabled: currentSearchEnabled,
        },
      });

      lastCompletion = completion;
      lastOutput = {
        text: team.text,
        sources: output.sources,
        modelId: team.modelId,
        modelProvider: team.modelProvider,
        plan: prepared.plan,
        completion,
      };

      if (completion.verdict === 'retry' && attempt < retryLimit) {
        currentModelId = await resolveRetryModelId(currentModelId);
        currentSearchEnabled = completion.retryPlan?.searchEnabled ?? currentSearchEnabled;
        currentContextAugments = buildRetryContextAugments(baseContextAugments, completion);
        continue;
      }

      break;
    } catch (error) {
      const stepLatencyMs = Date.now() - stepStartedAt;
      const output: ExecutionCompletionOutput = {
        text: '',
        sources: [],
        success: false,
        failureReason: normalizeError(error).message,
        modelId: currentModelId,
        modelProvider: currentModelId.includes(':') ? currentModelId.split(':', 1)[0] : currentModelId,
      };
      const completionArtifacts = [
        ...(prepared.operatorRun?.artifacts ?? []),
        buildCompletionArtifactPreview(prepared, output, attempt),
      ];
      const completion = evaluateExecutionCompletion({
        run: prepared.operatorRun ?? ({} as OperatorRun),
        steps: prepared.operatorRun?.steps ?? [],
        outputs: [output],
        artifacts: completionArtifacts,
        attempt,
        retryLimit,
        taskIntent: prepared.plan.taskIntent,
        routingMode: prepared.plan.routingMode,
      });
      const classifiedFailure = classifyFailure({
        error,
        outputText: output.text,
        failureReason: completion.reason,
        verdict: completion.verdict,
        tool: traceTool,
        modelId: currentModelId,
        modelProvider: output.modelProvider,
        sourcesCount: output.sources.length,
      });

      prepared.observabilityTrace.recordStepCompleted({
        step,
        modelId: currentModelId,
        tool: traceTool,
        latencyMs: stepLatencyMs,
        success: false,
        retryCount: attempt,
        errorType: classifiedFailure?.errorType,
        details: {
          error: normalizeError(error).message,
          path: 'team_runner',
        },
      });
      prepared.observabilityTrace.recordCompletion({
        step,
        modelId: currentModelId,
        tool: traceTool,
        latencyMs: stepLatencyMs,
        success: completion.verdict === 'success',
        verdict: completion.verdict,
        reason: completion.reason,
        retryCount: attempt,
        errorType: classifiedFailure?.errorType,
        details: {
          error: normalizeError(error).message,
          searchEnabled: currentSearchEnabled,
        },
      });

      lastCompletion = completion;
      lastOutput = {
        text: output.text,
        sources: output.sources,
        modelId: currentModelId,
        modelProvider: output.modelProvider ?? currentModelId,
        plan: prepared.plan,
        completion,
      };

      if (completion.verdict === 'retry' && attempt < retryLimit) {
        currentModelId = await resolveRetryModelId(currentModelId);
        currentSearchEnabled = completion.retryPlan?.searchEnabled ?? currentSearchEnabled;
        currentContextAugments = buildRetryContextAugments(baseContextAugments, completion);
        continue;
      }

      break;
    }
  }

  if (!lastCompletion || !lastOutput) {
    throw new Error('Execution completion could not be evaluated.');
  }

  const normalizedCompletion =
    lastCompletion.verdict === 'retry'
      ? {
          ...lastCompletion,
          verdict: 'failure' as const,
          verification: {
            ...lastCompletion.verification,
            status: 'failed' as const,
          },
          finalRunStatus: 'failed' as const,
        }
      : lastCompletion;

  return {
    ...lastOutput,
    plan: lastOutput.plan ?? prepared.plan,
    completion: normalizedCompletion,
  };
}

function buildQuantumCompletion(
  status: 'solved' | 'needs_input',
  retryLimit: number
): ExecutionCompletionResult {
  const reason = status === 'solved'
    ? 'Quantum hybrid solver produced a deterministic optimization report.'
    : 'Quantum optimization requires more structured input before solving.';

  return {
    verdict: 'success',
    reason,
    retryLimit,
    attempt: 0,
    requiredArtifacts: ['summary'],
    missingArtifacts: [],
    verification: {
      status: 'passed',
      summary: reason,
    },
    shouldTriggerLearning: status === 'solved',
    finalRunStatus: 'completed',
  };
}

async function executeQuantumCompletionAwareInteraction(
  prepared: PreparedInteraction,
  request: InteractionRequest
): Promise<CompletionAwareResult> {
  const step = 1;
  const modelId = 'elyan:quantum-hybrid';
  const modelProvider = 'elyan_quantum';
  const traceTool = 'optimization_solve';
  const stepStartedAt = Date.now();
  const scenarioResolution = resolveScenarioRequest(request.text, {
    mode: process.env.ELYAN_MODE === 'competition' ? 'competition' : 'standard',
  });

  prepared.observabilityTrace.recordStepStarted({
    step,
    modelId,
    tool: traceTool,
    retryCount: 0,
    details: {
      path: 'quantum_hybrid_solver',
      preferredSolver: prepared.decision.solverPreference?.solverId,
      scenarioId: scenarioResolution.status === 'ready' ? scenarioResolution.scenario.id : scenarioResolution.scenario?.id,
      scenarioMode: scenarioResolution.mode,
      scenarioDemo: scenarioResolution.status === 'ready' ? scenarioResolution.usesExampleInput : scenarioResolution.usesExampleInput,
    },
  });

  const result = solveHybridOptimization(
    scenarioResolution.status === 'ready'
      ? {
          query: request.text,
          problem: scenarioResolution.input,
          preferredSolverId: prepared.decision.solverPreference?.solverId,
          strategy: prepared.decision.solverStrategy,
        }
      : {
          query: request.text,
          preferredSolverId: prepared.decision.solverPreference?.solverId,
          strategy: prepared.decision.solverStrategy,
        }
  );
  const latencyMs = Date.now() - stepStartedAt;
  const success = result.status === 'needs_input' || Boolean(result.selectedSolution?.feasible);
  const completion = buildQuantumCompletion(result.status, prepared.policy.maxRetries);

  prepared.observabilityTrace.recordStepCompleted({
    step,
    modelId,
    tool: traceTool,
    latencyMs,
    success,
    retryCount: 0,
      details: {
        path: 'quantum_hybrid_solver',
        solverStatus: result.status,
        problemType: result.problemType,
        solverStrategy: prepared.decision.solverStrategy,
        scenarioId: scenarioResolution.status === 'ready' ? scenarioResolution.scenario.id : scenarioResolution.scenario?.id,
        solverUsed: result.metadata.solver_used,
        selectedCost: result.metadata.selected_cost,
        baselineCost: result.metadata.baseline_cost,
        improvementRatio: result.metadata.improvement_ratio,
      },
  });
  prepared.observabilityTrace.recordCompletion({
    step,
    modelId,
    tool: traceTool,
    latencyMs,
    success: true,
    verdict: completion.verdict,
    reason: completion.reason,
    retryCount: 0,
    details: {
      path: 'quantum_hybrid_solver',
      solverStatus: result.status,
      problemType: result.problemType,
      solverStrategy: prepared.decision.solverStrategy,
      solverUsed: result.metadata.solver_used,
    },
  });

  return {
    text: result.markdownReport,
    sources: [
      {
        url: 'local://optimization_solve/quantum_hybrid_solver',
        title: result.status === 'solved' ? 'Quantum hybrid solver report' : 'Quantum solver input requirements',
      },
    ],
    modelId,
    modelProvider,
    plan: prepared.plan,
    completion,
    learningMetadata: result.metadata,
  };
}

async function prepareInteraction(request: InteractionRequest): Promise<PreparedInteraction> {
  const controlPlane = getControlPlaneService();
  const requestId = request.requestId?.trim() || randomUUID();
  const runtimeSettings = readRuntimeSettingsSync();
  const classification = classifyInteractionIntent(request.text, request.mode);
  const surface = buildExecutionSurfaceSnapshot();
  const requestedModelId = request.modelId?.trim() || runtimeSettings.routing.preferredModelId?.trim();
  const spaceId = request.metadata?.spaceId?.trim() || request.metadata?.space_id?.trim() || request.controlPlaneSession?.accountId;
  const initialPlan = buildOrchestrationPlan(request.text, classification.resolvedMode, surface);
  const decision = await decideExecution({
    query: request.text,
    taskType: initialPlan.taskIntent,
    requestedModelId,
    spaceId,
    routingMode: initialPlan.routingMode,
    reasoningDepth: initialPlan.reasoningDepth,
  });
  const policy = decidePolicy({
    decision,
    taskType: initialPlan.taskIntent,
    queryComplexity: resolveQueryComplexity(request.text, decision.mode),
  });
  const mode: SearchMode = decision.mode === 'research' ? 'research' : 'speed';
  const basePlan =
    mode === classification.resolvedMode
      ? initialPlan
      : buildOrchestrationPlan(request.text, mode, surface);
  const plan = {
    ...basePlan,
    searchRounds: Math.min(basePlan.searchRounds, Math.min(decision.steps.stepBudget, policy.maxSteps)),
    retrieval: {
      ...basePlan.retrieval,
      rounds: Math.min(basePlan.retrieval.rounds, Math.min(decision.steps.stepBudget, policy.maxSteps)),
    },
  };
  const selectedModelId = decision.mode === 'quantum'
    ? decision.modelId ?? 'elyan:quantum-hybrid'
    : await pickSelectedModelId(plan, decision.modelId ?? requestedModelId);

  let memoryContext: string[] = [];
  let hostedAccountId: string | undefined;
  let hostedAccount: HostedAccountView | null = null;

  if (request.controlPlaneSession?.accountId) {
    hostedAccountId = request.controlPlaneSession.accountId;
    hostedAccount = await controlPlane.getAccount(request.controlPlaneSession.accountId);
    const context = await controlPlane.getInteractionContext(request.controlPlaneSession.accountId, {
      query: request.text,
      source: request.source,
      conversationId: request.conversationId,
    });
    memoryContext = context.contextBlocks;
  }

  const estimatedRequestTokens = decision.mode === 'quantum' ? 0 : estimateHostedRequestTokens(plan);
  const estimatedRunCostUsd = decision.mode === 'quantum'
    ? 0.002
    : estimateRunCostUsd({
        modelId: selectedModelId,
        tokens: estimatedRequestTokens,
        stepBudget: policy.maxSteps,
        retryLimit: policy.maxRetries,
      });

  if (estimatedRequestTokens > policy.maxTokens) {
    throw buildExecutionBudgetError(
      `Requested token budget exceeds the configured per-request limit of ${policy.maxTokens} tokens.`,
      {
        limitType: 'per_request_token_limit',
        planId: hostedAccount?.subscription.planId,
        remainingTokens: policy.maxTokens,
      }
    );
  }

  if (estimatedRunCostUsd > policy.maxCostUsd) {
    throw buildExecutionBudgetError(
      `Estimated run cost ${estimatedRunCostUsd.toFixed(4)} USD exceeds the configured cost cap of ${policy.maxCostUsd.toFixed(4)} USD.`,
      {
        limitType: 'run_cost_cap',
        planId: hostedAccount?.subscription.planId,
      }
    );
  }

  if (hostedAccountId && hostedAccount?.entitlements.hostedAccess && hostedAccount.entitlements.hostedUsageAccounting) {
    const usageDraft = estimateHostedUsageDraft(plan, requestId);
    const usageQuote = await controlPlane.quoteUsageBundle(hostedAccountId, usageDraft);

    if (!usageQuote.allowed) {
      if (usageQuote.denialReason === 'monthly_credits_exhausted') {
        throw new ControlPlaneInsufficientCreditsError(
          `Hosted credits are exhausted for ${hostedAccount.subscription.planId}.`,
          {
            monthlyCreditsRemaining: usageQuote.monthlyCreditsRemaining,
            balanceBefore: hostedAccount.balanceCredits,
            balanceAfter: hostedAccount.balanceCredits,
            planId: hostedAccount.subscription.planId,
            requiredCredits: '0.00',
          }
        );
      }

      throw new ControlPlaneUsageLimitError(
        'Hosted usage limit reached before execution began.',
        {
          limitType:
            usageQuote.denialReason === 'daily_tokens_limit'
              ? 'daily_tokens_limit'
              : usageQuote.denialReason === 'daily_tool_action_calls_limit'
                ? 'daily_tool_action_calls_limit'
                : 'daily_requests_limit',
          resetAt: usageQuote.resetAt,
          remainingRequests: usageQuote.remainingRequests,
          remainingHostedToolActionCalls: usageQuote.remainingHostedToolActionCalls,
          remainingTokens: usageQuote.remainingTokens,
          monthlyCreditsRemaining: usageQuote.monthlyCreditsRemaining,
          planId: hostedAccount.subscription.planId,
        }
      );
    }
  }

  const operatorRun = await getOperatorRunStore().create({
    source: request.source,
    text: request.text,
    mode: plan.taskIntent === 'research' || plan.taskIntent === 'comparison' || mode === 'research' ? 'research' : 'auto',
    title: request.text.slice(0, 80),
  });
  const observabilityTrace = createRunTrace({
    runId: operatorRun.id,
    taskId: requestId,
    mode: decision.mode,
    taskType: plan.taskIntent,
    modelId: selectedModelId,
    stepBudget: decision.steps.stepBudget,
    retryLimit: decision.steps.retryLimit,
    spaceId,
    recoveryState: request.runtimeContext?.recoveryState,
  });
  observabilityTrace.beforeExecution({
    requestId,
    decisionReasoning: decision.reasoning,
    modelPerformance: decision.modelPerformance,
    artifactCount: decision.artifactCount,
    solverStrategy: decision.solverStrategy,
    problemRefinement: decision.problemRefinement,
    problemComplexity: decision.problemComplexity,
    preferredTools: decision.tools.preferredTools,
    policy: {
      maxSteps: policy.maxSteps,
      maxRetries: policy.maxRetries,
      maxTimeMs: policy.maxTimeMs,
      maxCostUsd: policy.maxCostUsd,
      maxTokens: policy.maxTokens,
      allowedTools: policy.allowedTools,
    },
    estimatedRequestTokens,
    estimatedRunCostUsd,
  });

  return {
    requestId,
    classification,
    mode,
    plan,
    surface,
    decision,
    policy,
    selectedModelId,
    memoryContext,
    controlPlaneSession: request.controlPlaneSession,
    runtimeContext: request.runtimeContext,
    signal: request.signal,
    hostedAccountId,
    spaceId,
    hostedAccount,
    operatorRun,
    observabilityTrace,
    startedAt: Date.now(),
    queryLength: request.text.length,
    estimatedRequestTokens,
    estimatedRunCostUsd,
  };
}

async function maybeRecordHostedUsage(prepared: PreparedInteraction) {
  if (!prepared.hostedAccountId || !prepared.hostedAccount) {
    return;
  }

  const controlPlane = getControlPlaneService();
  if (prepared.hostedAccount.entitlements.hostedAccess && prepared.hostedAccount.entitlements.hostedUsageAccounting) {
    const usageDraft = estimateHostedUsageDraft(prepared.plan, prepared.requestId);
    await controlPlane.recordUsageBundle(prepared.hostedAccountId, usageDraft);
  }
}

async function recordLearningEvent(
  prepared: PreparedInteraction,
  request: InteractionRequest,
  output: {
    text: string;
    sources: Array<{ url: string; title: string }>;
    failureReason?: string;
    success: boolean;
    modelId?: string;
    modelProvider?: string;
    observabilityTrace?: RunTraceReport;
    learningMetadata?: Record<string, unknown>;
  }
) {
  if (!prepared.hostedAccountId) {
    return;
  }

  const controlPlane = getControlPlaneService();
  const latencyMs = Date.now() - prepared.startedAt;
  const sourceCount = output.sources.length;
  const citationCount = (output.text.match(/\[(\d+)\]/g) ?? []).length;
  const isSafeForLearning = Boolean(prepared.hostedAccount?.entitlements.hostedImprovementSignals);
  const observabilityMetrics = output.observabilityTrace ? buildRunMetrics([output.observabilityTrace]) : undefined;
  const reasoningSteps = buildReasoningTrace({
    input: request.text,
    intent: prepared.classification.intent,
    plan: prepared.plan,
    reasoningSteps: [
      `input: ${request.text.slice(0, 240)}`,
      `intent: ${prepared.classification.intent}`,
      `plan: ${buildReasoningPlanSummary(prepared.plan, prepared.classification.intent)}`,
    ],
    action: sourceCount > 0 ? `tool output grounded by ${sourceCount} source(s)` : 'direct answer',
    observation: sourceCount > 0 ? `${sourceCount} source(s) observed` : 'no live sources observed',
    refinement: output.failureReason ?? (output.success ? 'retain grounded answer' : 'retry with fallback'),
    output: output.text,
    success: output.success,
    failureReason: output.failureReason,
    latencyMs,
    citationCount,
    toolCallCount: sourceCount,
  });
  const teacherModel = await resolveTeacherModel().catch(() => null);
  const candidate: MlDatasetCandidate = {
    account_id: prepared.hostedAccountId ?? 'local',
    account_display_name: prepared.hostedAccount?.displayName ?? 'local',
    owner_type: prepared.hostedAccount?.ownerType ?? 'individual',
    account_status: prepared.hostedAccount?.status ?? 'active',
    plan_id: prepared.hostedAccount?.subscription?.planId ?? 'local_byok',
    subscription_status: prepared.hostedAccount?.subscription?.status ?? 'trialing',
    request_id: prepared.requestId,
    source: request.source === 'web' ? 'request' : 'request',
    instruction: request.text,
    input: request.text,
    output: output.text,
    plan: buildReasoningPlanSummary(prepared.plan, prepared.classification.intent),
    reasoning_trace: reasoningSteps,
    success: output.success,
    failure_reason: output.failureReason,
    quality: output.success ? 'good' : 'poor',
    latency_ms: latencyMs,
    metadata: {
      intent: prepared.classification.intent,
      routing_mode: prepared.plan.routingMode,
      reasoning_depth: prepared.plan.reasoningDepth,
      request_id: prepared.requestId,
      source_count: sourceCount,
      citation_count: citationCount,
      model_id: output.modelId ?? prepared.selectedModelId,
      model_provider: output.modelProvider,
      taskIntent: prepared.plan.taskIntent,
      decision_mode: prepared.decision.mode,
      solver_metadata: output.learningMetadata,
    },
  };
  const quality = await buildQualityAssessment(candidate, teacherModel);

  try {
    await controlPlane.recordLearningEvent?.(prepared.hostedAccountId, {
      requestId: prepared.requestId,
      source: request.source,
      input: request.text,
      intent: prepared.classification.intent,
      taskType: prepared.plan.taskIntent,
      spaceId: prepared.spaceId,
      plan: buildReasoningPlanSummary(prepared.plan, prepared.classification.intent),
      reasoningSteps,
      output: output.text,
      betterOutput: quality.better_output,
      success: output.success,
      failureReason: output.failureReason,
      feedback: {
        evaluatorNotes: quality.evaluator_notes,
        discardReason: quality.discard_reason,
        teacherStrategy: quality.teacher_strategy,
      },
      latencyMs,
      score: quality.score,
      accepted: quality.accepted,
      modelId: output.modelId ?? prepared.selectedModelId,
      modelProvider: output.modelProvider,
      isSafeForLearning,
      metadata: {
        requestId: prepared.requestId,
        queryLength: prepared.queryLength,
        sourceCount,
        citationCount,
        taskIntent: prepared.plan.taskIntent,
        reasoningDepth: prepared.plan.reasoningDepth,
        routingMode: prepared.plan.routingMode,
        teacherStrategy: quality.teacher_strategy,
        evaluatorNotes: quality.evaluator_notes,
        discardReason: quality.discard_reason,
        accepted: quality.accepted,
        score: quality.score,
        spaceId: prepared.spaceId,
        decision_mode: prepared.decision.mode,
        ...(output.learningMetadata ?? {}),
        observability: output.observabilityTrace
          ? {
              runId: output.observabilityTrace.runId,
              mode: output.observabilityTrace.mode,
              taskType: output.observabilityTrace.taskType,
              modelId: output.observabilityTrace.modelId,
              summary: output.observabilityTrace.summary,
            }
          : undefined,
        observabilityMetrics,
      },
    });
  } catch (error) {
    console.warn('Elyan learning event capture failed', error);
  }
}

async function recordInteractionOutput(
  prepared: PreparedInteraction,
  request: InteractionRequest,
  output: {
    text: string;
    sources: Array<{ url: string; title: string }>;
    totalUsage: LanguageModelUsage;
    modelProvider: string;
    modelId?: string;
    observabilityTrace?: RunTraceReport;
    learningMetadata?: Record<string, unknown>;
  }
) {
  if (!prepared.hostedAccountId) {
    return;
  }

  const controlPlane = getControlPlaneService();

  try {
    await controlPlane.recordInteraction(prepared.hostedAccountId, {
      source: request.source,
      query: request.text,
      responseText: output.text,
      mode: prepared.mode,
      intent: prepared.classification.intent,
      confidence: prepared.classification.confidence,
      conversationId: request.conversationId,
      messageId: request.messageId,
      userId: request.userId,
      displayName: request.displayName,
      modelId: output.modelId ?? prepared.selectedModelId,
      metadata: {
        ...(request.metadata ?? {}),
        requestId: prepared.requestId,
      },
      sources: output.sources,
      citationCount: (output.text.match(/\[(\d+)\]/g) ?? []).length,
    });
  } catch (error) {
    console.warn('Elyan interaction memory capture failed', error);
  }

  await recordLearningEvent(prepared, request, {
    text: output.text,
    sources: output.sources,
    success: true,
    modelId: output.modelId ?? prepared.selectedModelId,
    modelProvider: output.modelProvider,
    observabilityTrace: output.observabilityTrace,
    learningMetadata: output.learningMetadata,
  });
}

async function recordOperatorRunOutput(
  prepared: PreparedInteraction,
  output: {
    text: string;
    sources: Array<{ url: string; title: string }>;
    observabilityTrace?: RunTraceReport;
    executionExplanation?: ExecutionExplanation;
    learningMetadata?: Record<string, unknown>;
  }
) {
  if (!prepared.operatorRun) {
    return;
  }

  const mode = prepared.operatorRun.mode;
  const sourceLines = output.sources.length > 0
    ? output.sources.map((source, index) => `[${index + 1}] ${source.title} - ${source.url}`).join('\n')
    : 'No verified sources were available for this run.';
  const modeMetadata: Record<string, unknown> =
    mode === 'research'
      ? {
          sourceCount: output.sources.length,
          taskIntent: prepared.plan.taskIntent,
          mode: prepared.mode,
          unavailable: output.sources.length === 0,
        }
      : mode === 'code'
        ? {
            taskIntent: prepared.plan.taskIntent,
            mode: prepared.mode,
          }
        : {
            taskIntent: prepared.plan.taskIntent,
            mode: prepared.mode,
            sharedToHosted: false,
            memoryBoundary: 'local',
          };
  const kind = mode === 'research' ? 'research' : 'summary';
  const title = mode === 'research' ? 'Research result' : mode === 'code' ? 'Code result' : 'Operator result';

  if (mode === 'code') {
    const repositorySnapshot = await captureRepositorySnapshot();
    Object.assign(modeMetadata, repositorySnapshot);
  }

  if (output.observabilityTrace) {
    Object.assign(modeMetadata, {
      observabilityTrace: output.observabilityTrace,
      observabilityMetrics: buildRunMetrics([output.observabilityTrace]),
    });
  }

  if (output.learningMetadata) {
    Object.assign(modeMetadata, {
      quantumSolver: output.learningMetadata,
    });
  }

  if (output.executionExplanation) {
    Object.assign(modeMetadata, {
      executionExplanation: output.executionExplanation,
    });
  }

  const bodyParts =
    mode === 'research'
      ? [
          'Answer:',
          output.text,
          '',
          output.sources.length === 0 ? 'Live evidence is unavailable for this run.' : 'Sources:',
          sourceLines,
        ]
      : mode === 'code'
        ? [
            'Answer:',
            output.text,
            '',
            'Repository snapshot:',
            describeRepositorySnapshot(modeMetadata),
            '',
            'Sources:',
            sourceLines,
          ]
      : [
          'Answer:',
          output.text,
          '',
          'Project memory boundary:',
          'Local only by default.',
          '',
          'Sources:',
          sourceLines,
        ];

  if (output.executionExplanation) {
    bodyParts.push(
      '',
      'Execution explanation:',
      formatExecutionExplanation(output.executionExplanation)
    );
  } else {
    bodyParts.push('', 'Execution explanation: unavailable.');
  }

  await recordOperatorRunArtifact(prepared.operatorRun.id, {
    kind,
    title,
    content: bodyParts.join('\n'),
    metadata: modeMetadata,
  });
}

function describeRepositorySnapshot(metadata: Record<string, unknown>) {
  if (metadata.repoInspected !== true) {
    return `Inspection unavailable: ${String(metadata.repoInspectionError ?? 'repo snapshot could not be collected.')}`;
  }

  const branch = String(metadata.repoBranch ?? 'unknown');
  const dirtyCount = Number(metadata.repoDirtyFileCount ?? 0);
  const summary = String(metadata.repoDirtySummary ?? 'clean');
  const entrypoints = Array.isArray(metadata.repoEntrypoints) ? metadata.repoEntrypoints.filter((item) => typeof item === 'string') : [];
  const patchSummary = String(metadata.repoPatchSummary ?? '').trim();
  const tsFiles = Number(metadata.repoTypeScriptFileCount ?? 0);

  const lines = [
    `Branch: ${branch}`,
    `Changed files: ${dirtyCount}`,
    `Status: ${summary}`,
    `TypeScript files: ${tsFiles}`,
    'Verification evidence still required before the run can complete.',
  ];

  if (entrypoints.length > 0) {
    lines.push(`Entrypoints: ${entrypoints.slice(0, 5).join(', ')}`);
  }

  if (patchSummary) {
    lines.push(`Patch: ${patchSummary}`);
  }

  return lines.join('\n');
}

export async function executeInteractionText(request: InteractionRequest): Promise<InteractionTextResponse> {
  const prepared = await prepareInteraction(request);
  const account = prepared.hostedAccount;
  const runtimeSettings = readRuntimeSettingsSync();
  const contextAugments = await loadLearningContextAugments(prepared);

  try {
    if (request.requireHostedSession && isControlPlaneSessionConfigured() && !prepared.controlPlaneSession?.accountId) {
      throw new ControlPlaneAuthenticationError('Control-plane session is required for the main chat surface');
    }

    if (prepared.hostedAccountId && account) {
      await maybeRecordHostedUsage(prepared);
    }

    if (prepared.decision.mode === 'quantum') {
      const quantumCompletion = await executeQuantumCompletionAwareInteraction(prepared, request);
      const observabilityTrace = prepared.observabilityTrace.finalize();
      const executionExplanation = explainExecution({
        run: prepared.operatorRun!,
        completion: quantumCompletion.completion,
        trace: observabilityTrace,
        artifacts: prepared.operatorRun?.artifacts ?? [],
      });

      await recordInteractionOutput(prepared, request, {
        text: quantumCompletion.text,
        sources: quantumCompletion.sources,
        totalUsage: createEmptyLanguageModelUsage(),
        modelProvider: quantumCompletion.modelProvider,
        modelId: quantumCompletion.modelId,
        observabilityTrace,
        learningMetadata: quantumCompletion.learningMetadata,
      });
      await recordOperatorRunOutput(prepared, {
        text: quantumCompletion.text,
        sources: quantumCompletion.sources,
        observabilityTrace,
        executionExplanation,
        learningMetadata: quantumCompletion.learningMetadata,
      });

      return {
        text: quantumCompletion.text,
        sources: quantumCompletion.sources.map((source) => ({ url: source.url, title: source.title })),
        plan: quantumCompletion.plan,
        surface: prepared.surface,
        modelId: quantumCompletion.modelId,
        classification: prepared.classification,
        runId: prepared.operatorRun?.id,
      };
    }

    if (prepared.plan.executionMode === 'team' && runtimeSettings.team.enabled && runtimeSettings.team.defaultMode !== 'single') {
      const teamCompletion = await executeTeamCompletionAwareInteraction(prepared, request, runtimeSettings, contextAugments);
      const observabilityTrace = prepared.observabilityTrace.finalize();
      const executionExplanation = explainExecution({
        run: prepared.operatorRun!,
        completion: teamCompletion.completion,
        trace: observabilityTrace,
        artifacts: prepared.operatorRun?.artifacts ?? [],
      });

      if (teamCompletion.completion.verdict !== 'success') {
        await recordLearningEvent(prepared, request, {
          text: teamCompletion.text,
          sources: teamCompletion.sources,
          success: false,
          failureReason: teamCompletion.completion.reason,
          modelId: teamCompletion.modelId,
          modelProvider: teamCompletion.modelProvider,
          observabilityTrace,
        });
        await finalizeFailedOperatorRun(
          prepared,
          {
            text: teamCompletion.text,
            sources: teamCompletion.sources,
            success: false,
            failureReason: teamCompletion.completion.reason,
            modelId: teamCompletion.modelId,
            modelProvider: teamCompletion.modelProvider,
          },
          teamCompletion.completion,
          observabilityTrace,
          executionExplanation
        );
        throw new ExecutionCompletionFailureError(teamCompletion.completion.reason);
      }

      await recordInteractionOutput(prepared, request, {
        text: teamCompletion.text,
        sources: teamCompletion.sources,
        totalUsage: createEmptyLanguageModelUsage(),
        modelProvider: teamCompletion.modelProvider,
        modelId: teamCompletion.modelId,
        observabilityTrace,
      });
      await recordOperatorRunOutput(prepared, {
        text: teamCompletion.text,
        sources: teamCompletion.sources,
        observabilityTrace,
        executionExplanation,
      });

      return {
        text: teamCompletion.text,
        sources: teamCompletion.sources.map((source) => ({ url: source.url, title: source.title })),
        plan: prepared.plan,
        surface: prepared.surface,
        modelId: teamCompletion.modelId,
        classification: prepared.classification,
        runId: prepared.operatorRun?.id,
      };
    }

    const completionAware = await executeCompletionAwareInteraction(prepared, request, runtimeSettings, contextAugments);
    const observabilityTrace = prepared.observabilityTrace.finalize();
    const executionExplanation = explainExecution({
      run: prepared.operatorRun!,
      completion: completionAware.completion,
      trace: observabilityTrace,
      artifacts: prepared.operatorRun?.artifacts ?? [],
    });

    if (completionAware.completion.verdict !== 'success') {
      await recordLearningEvent(prepared, request, {
        text: completionAware.text,
        sources: completionAware.sources,
        success: false,
        failureReason: completionAware.completion.reason,
        modelId: completionAware.modelId,
        modelProvider: completionAware.modelProvider,
        observabilityTrace,
      });
      await finalizeFailedOperatorRun(
        prepared,
        {
          text: completionAware.text,
          sources: completionAware.sources,
          success: false,
          failureReason: completionAware.completion.reason,
          modelId: completionAware.modelId,
          modelProvider: completionAware.modelProvider,
        },
        completionAware.completion,
        observabilityTrace,
        executionExplanation
      );
      throw new ExecutionCompletionFailureError(completionAware.completion.reason);
    }

    await recordInteractionOutput(prepared, request, {
      text: completionAware.text,
      sources: completionAware.sources,
      totalUsage: createEmptyLanguageModelUsage(),
      modelProvider: completionAware.modelProvider,
      modelId: completionAware.modelId,
      observabilityTrace,
    });
    await recordOperatorRunOutput(prepared, {
      text: completionAware.text,
      sources: completionAware.sources,
      observabilityTrace,
      executionExplanation,
    });

    return {
      text: completionAware.text,
      sources: completionAware.sources.map((source) => ({ url: source.url, title: source.title })),
      plan: completionAware.plan,
      surface: prepared.surface,
      modelId: completionAware.modelId,
      classification: prepared.classification,
      runId: prepared.operatorRun?.id,
    };
  } catch (error) {
    if (error instanceof ExecutionCompletionFailureError) {
      throw error;
    }

    const observabilityTrace = prepared.observabilityTrace.finalize();
    await recordLearningEvent(prepared, request, {
      text: '',
      sources: [],
      success: false,
      failureReason: normalizeError(error).message,
      modelId: prepared.selectedModelId,
      observabilityTrace,
    });
    throw error;
  }
}

export async function executeInteractionStream(request: InteractionRequest) {
  const prepared = await prepareInteraction(request);
  const account = prepared.hostedAccount;
  const runtimeSettings = readRuntimeSettingsSync();
  const contextAugments = await loadLearningContextAugments(prepared);

  try {
    if (request.requireHostedSession && isControlPlaneSessionConfigured() && !prepared.controlPlaneSession?.accountId) {
      throw new ControlPlaneAuthenticationError('Control-plane session is required for the main chat surface');
    }

    if (prepared.hostedAccountId && account) {
      await maybeRecordHostedUsage(prepared);
    }

    if (prepared.decision.mode === 'quantum') {
      const quantumCompletion = await executeQuantumCompletionAwareInteraction(prepared, request);
      const observabilityTrace = prepared.observabilityTrace.finalize();
      const executionExplanation = explainExecution({
        run: prepared.operatorRun!,
        completion: quantumCompletion.completion,
        trace: observabilityTrace,
        artifacts: prepared.operatorRun?.artifacts ?? [],
      });

      await recordInteractionOutput(prepared, request, {
        text: quantumCompletion.text,
        sources: quantumCompletion.sources,
        totalUsage: createEmptyLanguageModelUsage(),
        modelProvider: quantumCompletion.modelProvider,
        modelId: quantumCompletion.modelId,
        observabilityTrace,
        learningMetadata: quantumCompletion.learningMetadata,
      });
      await recordOperatorRunOutput(prepared, {
        text: quantumCompletion.text,
        sources: quantumCompletion.sources,
        observabilityTrace,
        executionExplanation,
        learningMetadata: quantumCompletion.learningMetadata,
      });

      const { createUIMessageStream, createUIMessageStreamResponse } = await import('ai');
      const stream = createUIMessageStream({
        execute: async ({ writer }) => {
          const textId = `quantum-${prepared.requestId}`;

          writer.write({ type: 'start' });
          writer.write({ type: 'text-start', id: textId });
          writer.write({ type: 'text-delta', id: textId, delta: quantumCompletion.text });
          writer.write({ type: 'text-end', id: textId });
          writer.write({
            type: 'finish',
            finishReason: 'stop',
          });
        },
      });

      return createUIMessageStreamResponse({ stream });
    }

    if (prepared.plan.executionMode === 'team' && runtimeSettings.team.enabled && runtimeSettings.team.defaultMode !== 'single') {
      const teamCompletion = await executeTeamCompletionAwareInteraction(prepared, request, runtimeSettings, contextAugments);
      const observabilityTrace = prepared.observabilityTrace.finalize();
      const executionExplanation = explainExecution({
        run: prepared.operatorRun!,
        completion: teamCompletion.completion,
        trace: observabilityTrace,
        artifacts: prepared.operatorRun?.artifacts ?? [],
      });

      if (teamCompletion.completion.verdict !== 'success') {
        await recordLearningEvent(prepared, request, {
          text: teamCompletion.text,
          sources: teamCompletion.sources,
          success: false,
          failureReason: teamCompletion.completion.reason,
          modelId: teamCompletion.modelId,
          modelProvider: teamCompletion.modelProvider,
        });
        await finalizeFailedOperatorRun(
          prepared,
          {
            text: teamCompletion.text,
            sources: teamCompletion.sources,
            success: false,
            failureReason: teamCompletion.completion.reason,
            modelId: teamCompletion.modelId,
            modelProvider: teamCompletion.modelProvider,
          },
          teamCompletion.completion,
          observabilityTrace,
          executionExplanation
        );
        throw new ExecutionCompletionFailureError(teamCompletion.completion.reason);
      }

      await recordInteractionOutput(prepared, request, {
        text: teamCompletion.text,
        sources: teamCompletion.sources,
        totalUsage: createEmptyLanguageModelUsage(),
        modelProvider: teamCompletion.modelProvider,
        modelId: teamCompletion.modelId,
      });
      await recordOperatorRunOutput(prepared, {
        text: teamCompletion.text,
        sources: teamCompletion.sources,
        observabilityTrace,
        executionExplanation,
      });

      const { createUIMessageStream, createUIMessageStreamResponse } = await import('ai');
      const stream = createUIMessageStream({
        execute: async ({ writer }) => {
          const textId = `team-${prepared.requestId}`;

          writer.write({ type: 'start' });
          writer.write({ type: 'text-start', id: textId });
          writer.write({ type: 'text-delta', id: textId, delta: teamCompletion.text });
          writer.write({ type: 'text-end', id: textId });
          writer.write({
            type: 'finish',
            finishReason: 'stop',
          });
        },
      });

      return createUIMessageStreamResponse({ stream });
    }

    const completionAware = await executeCompletionAwareInteraction(prepared, request, runtimeSettings, contextAugments);
    const observabilityTrace = prepared.observabilityTrace.finalize();
    const executionExplanation = explainExecution({
      run: prepared.operatorRun!,
      completion: completionAware.completion,
      trace: observabilityTrace,
      artifacts: prepared.operatorRun?.artifacts ?? [],
    });

    if (completionAware.completion.verdict !== 'success') {
      await recordLearningEvent(prepared, request, {
        text: completionAware.text,
        sources: completionAware.sources,
        success: false,
          failureReason: completionAware.completion.reason,
          modelId: completionAware.modelId,
          modelProvider: completionAware.modelProvider,
        });
        await finalizeFailedOperatorRun(
        prepared,
          {
            text: completionAware.text,
            sources: completionAware.sources,
            success: false,
            failureReason: completionAware.completion.reason,
            modelId: completionAware.modelId,
            modelProvider: completionAware.modelProvider,
          },
          completionAware.completion,
          observabilityTrace,
          executionExplanation
        );
        throw new ExecutionCompletionFailureError(completionAware.completion.reason);
      }

    await recordInteractionOutput(prepared, request, {
      text: completionAware.text,
      sources: completionAware.sources,
      totalUsage: createEmptyLanguageModelUsage(),
      modelProvider: completionAware.modelProvider,
      modelId: completionAware.modelId,
    });
    await recordOperatorRunOutput(prepared, {
      text: completionAware.text,
      sources: completionAware.sources,
      observabilityTrace,
      executionExplanation,
    });

    const { createUIMessageStream, createUIMessageStreamResponse } = await import('ai');
    const stream = createUIMessageStream({
      execute: async ({ writer }) => {
        const textId = `answer-${prepared.requestId}`;

        writer.write({ type: 'start' });
        writer.write({ type: 'text-start', id: textId });
        writer.write({ type: 'text-delta', id: textId, delta: completionAware.text });
        writer.write({ type: 'text-end', id: textId });
        writer.write({
          type: 'finish',
          finishReason: 'stop',
        });
      },
    });

    return createUIMessageStreamResponse({ stream });
  } catch (error) {
    if (error instanceof ExecutionCompletionFailureError) {
      throw error;
    }

    const observabilityTrace = prepared.observabilityTrace.finalize();
    await recordLearningEvent(prepared, request, {
      text: '',
      sources: [],
      success: false,
      failureReason: normalizeError(error).message,
      modelId: prepared.selectedModelId,
      observabilityTrace,
    });
    throw error;
  }
}

export function normalizeInteractionError(error: unknown) {
  return normalizeError(error);
}
