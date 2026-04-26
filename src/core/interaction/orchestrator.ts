import { randomUUID } from 'crypto';
import type { LanguageModelUsage } from 'ai';
import { answerEngine } from '@/core/agents/answer-engine';
import { getControlPlaneService, isControlPlaneSessionConfigured } from '@/core/control-plane';
import { ControlPlaneAuthenticationError, ControlPlaneInsufficientCreditsError, ControlPlaneUsageLimitError } from '@/core/control-plane/errors';
import type { ControlPlaneSessionToken } from '@/core/control-plane/session';
import { buildEvaluationSignalDraft } from '@/core/orchestration/evaluation';
import { buildExecutionSurfaceSnapshot, buildOrchestrationPlan } from '@/core/orchestration';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import { registry } from '@/core/providers';
import { teamRunner } from '@/core/teams';
import type { SearchMode } from '@/types/search';
import type { ExecutionSurfaceSnapshot, OrchestrationPlan, ExecutionTarget } from '@/core/orchestration';
import { classifyInteractionIntent } from './intent';
import { type OperatorSource } from '@/core/operator/types';
import { estimateHostedUsageDraft } from '@/core/control-plane/pricing';

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
};

export type InteractionTextResponse = {
  text: string;
  sources: Array<{ url: string; title: string }>;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  modelId: string;
  classification: ReturnType<typeof classifyInteractionIntent>;
};

type PreparedInteraction = {
  requestId: string;
  classification: ReturnType<typeof classifyInteractionIntent>;
  mode: SearchMode;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  selectedModelId: string;
  memoryContext: string[];
  controlPlaneSession?: ControlPlaneSessionToken | null;
  hostedAccountId?: string;
  hostedAccount?: HostedAccountView | null;
  startedAt: number;
  queryLength: number;
};

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
      code: 'no_model_available',
      message: 'No model is available. Configure Ollama or set at least one cloud API key.',
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

  return registry.resolvePreferredModelId({
    preferredModelId: requestedModelId?.trim(),
    routingMode,
    taskIntent: plan.taskIntent,
    reasoningDepth: plan.reasoningDepth,
  });
}

async function prepareInteraction(request: InteractionRequest): Promise<PreparedInteraction> {
  const controlPlane = getControlPlaneService();
  const requestId = request.requestId?.trim() || randomUUID();
  const runtimeSettings = readRuntimeSettingsSync();
  const classification = classifyInteractionIntent(request.text, request.mode);
  const mode = classification.resolvedMode;
  const surface = buildExecutionSurfaceSnapshot();
  const plan = buildOrchestrationPlan(request.text, mode, surface);
  const selectedModelId =
    request.modelId?.trim() ||
    runtimeSettings.routing.preferredModelId?.trim() ||
    (await pickSelectedModelId(plan, request.modelId));

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

  return {
    requestId,
    classification,
    mode,
    plan,
    surface,
    selectedModelId,
    memoryContext,
    controlPlaneSession: request.controlPlaneSession,
    hostedAccountId,
    hostedAccount,
    startedAt: Date.now(),
    queryLength: request.text.length,
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

async function recordHostedOutcome(
  prepared: PreparedInteraction,
  output: {
    text: string;
    sources: Array<{ url: string; title: string }>;
    totalUsage: LanguageModelUsage;
    modelProvider: string;
  }
) {
  if (!prepared.hostedAccountId || !prepared.hostedAccount) {
    return;
  }

  const controlPlane = getControlPlaneService();
  const signal = buildEvaluationSignalDraft({
    requestId: prepared.requestId,
    mode: prepared.mode,
    plan: prepared.plan,
    surface: prepared.surface,
    searchAvailable: prepared.plan.executionPolicy.shouldRetrieve,
    operatorNotes: prepared.plan.executionPolicy.notes,
    operatorTarget: prepared.plan.executionPolicy.primary as ExecutionTarget,
    modelProvider: output.modelProvider,
    modelId: prepared.selectedModelId,
    text: output.text,
    queryLength: prepared.queryLength,
    latencyMs: Date.now() - prepared.startedAt,
    totalUsage: output.totalUsage,
    toolCallCount: 0,
    toolResultCount: 0,
    sourcesCount: output.sources.length,
  });

  await controlPlane.recordEvaluationSignal(prepared.hostedAccountId, signal);
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

    if (prepared.hostedAccount?.entitlements.hostedImprovementSignals) {
      await recordHostedOutcome(prepared, {
        text: output.text,
        sources: output.sources,
        totalUsage: output.totalUsage,
        modelProvider: output.modelProvider,
      });
    }
  } catch (error) {
    console.warn('Elyan interaction memory capture failed', error);
  }
}

export async function executeInteractionText(request: InteractionRequest): Promise<InteractionTextResponse> {
  const prepared = await prepareInteraction(request);
  const account = prepared.hostedAccount;
  const runtimeSettings = readRuntimeSettingsSync();

  if (request.requireHostedSession && isControlPlaneSessionConfigured() && !prepared.controlPlaneSession?.accountId) {
    throw new ControlPlaneAuthenticationError('Control-plane session is required for the main chat surface');
  }

  if (prepared.hostedAccountId && account) {
    await maybeRecordHostedUsage(prepared);
  }

  if (prepared.plan.executionMode === 'team' && runtimeSettings.team.enabled && runtimeSettings.team.defaultMode !== 'single') {
    const team = await teamRunner.run({
      query: request.text,
      mode: prepared.mode,
      requestedModelId: request.modelId ?? runtimeSettings.routing.preferredModelId,
      sourcePlan: prepared.plan,
      maxConcurrentAgents: runtimeSettings.team.maxConcurrentAgents,
      maxTasksPerRun: runtimeSettings.team.maxTasksPerRun,
      allowCloudEscalation: runtimeSettings.team.allowCloudEscalation,
      contextAugments: prepared.memoryContext,
      searchEnabled: runtimeSettings.routing.searchEnabled,
    });

    await recordInteractionOutput(prepared, request, {
      text: team.text,
      sources: team.sources.map((source) => ({ url: source.url, title: source.title })),
      totalUsage: createEmptyLanguageModelUsage(),
      modelProvider: team.modelProvider,
      modelId: team.modelId,
    });

    return {
      text: team.text,
      sources: team.sources.map((source) => ({ url: source.url, title: source.title })),
      plan: prepared.plan,
      surface: prepared.surface,
      modelId: team.modelId,
      classification: prepared.classification,
    };
  }

  const { text, sources, plan } = await answerEngine.executeText(request.text, prepared.selectedModelId, prepared.mode, {
    plan: prepared.plan,
    surface: prepared.surface,
    searchEnabled: runtimeSettings.routing.searchEnabled,
    contextAugments: prepared.memoryContext,
    onFinish: async (event, context) => {
      await recordInteractionOutput(prepared, request, {
        text: event.text,
        sources: context.sources.map((source) => ({ url: source.url, title: source.title })),
        totalUsage: event.totalUsage,
        modelProvider: context.providerId,
        modelId: prepared.selectedModelId,
      });
    },
  });

  return {
    text,
    sources: sources.map((source) => ({ url: source.url, title: source.title })),
    plan,
    surface: prepared.surface,
    modelId: prepared.selectedModelId,
    classification: prepared.classification,
  };
}

export async function executeInteractionStream(request: InteractionRequest) {
  const prepared = await prepareInteraction(request);
  const account = prepared.hostedAccount;
  const runtimeSettings = readRuntimeSettingsSync();

  if (request.requireHostedSession && isControlPlaneSessionConfigured() && !prepared.controlPlaneSession?.accountId) {
    throw new ControlPlaneAuthenticationError('Control-plane session is required for the main chat surface');
  }

  if (prepared.hostedAccountId && account) {
    await maybeRecordHostedUsage(prepared);
  }

  if (prepared.plan.executionMode === 'team' && runtimeSettings.team.enabled && runtimeSettings.team.defaultMode !== 'single') {
    const { createUIMessageStream, createUIMessageStreamResponse } = await import('ai');
    const stream = createUIMessageStream({
      execute: async ({ writer }) => {
        const team = await teamRunner.run({
          query: request.text,
          mode: prepared.mode,
          requestedModelId: request.modelId ?? runtimeSettings.routing.preferredModelId,
          sourcePlan: prepared.plan,
          maxConcurrentAgents: runtimeSettings.team.maxConcurrentAgents,
          maxTasksPerRun: runtimeSettings.team.maxTasksPerRun,
          allowCloudEscalation: runtimeSettings.team.allowCloudEscalation,
          contextAugments: prepared.memoryContext,
          searchEnabled: runtimeSettings.routing.searchEnabled,
        });
        const textId = `team-${prepared.requestId}`;

        writer.write({ type: 'start' });
        writer.write({ type: 'text-start', id: textId });
        writer.write({ type: 'text-delta', id: textId, delta: team.text });
        writer.write({ type: 'text-end', id: textId });
        writer.write({
          type: 'finish',
          finishReason: team.summary.verifier.passed ? 'stop' : 'other',
        });

        await recordInteractionOutput(prepared, request, {
          text: team.text,
          sources: team.sources.map((source) => ({ url: source.url, title: source.title })),
          totalUsage: createEmptyLanguageModelUsage(),
          modelProvider: team.modelProvider,
          modelId: team.modelId,
        });
      },
    });

    return createUIMessageStreamResponse({ stream });
  }

  const { stream } = await answerEngine.execute(request.text, prepared.selectedModelId, prepared.mode, {
    plan: prepared.plan,
    surface: prepared.surface,
    searchEnabled: runtimeSettings.routing.searchEnabled,
    contextAugments: prepared.memoryContext,
    onFinish: async (event, context) => {
      await recordInteractionOutput(prepared, request, {
        text: event.text,
        sources: context.sources.map((source) => ({ url: source.url, title: source.title })),
        totalUsage: event.totalUsage,
        modelProvider: context.providerId,
        modelId: prepared.selectedModelId,
      });
    },
    onError: async (error) => {
      if (!prepared.hostedAccountId || !account || !account.entitlements.hostedImprovementSignals) {
        return;
      }

      try {
        await recordHostedOutcome(prepared, {
          text: '',
          sources: [],
          totalUsage: createEmptyLanguageModelUsage(),
          modelProvider: registry.resolveModel(prepared.selectedModelId).provider.id,
        });
      } catch (captureError) {
        console.warn('Elyan evaluation error capture failed', captureError);
      }
      console.warn('Elyan interaction stream error', error);
    },
  });

  return stream;
}

export function normalizeInteractionError(error: unknown) {
  return normalizeError(error);
}
