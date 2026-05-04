import { randomUUID } from 'crypto';
import type { LanguageModelUsage } from 'ai';
import { answerEngine } from '@/core/agents/answer-engine';
import { getControlPlaneService, isControlPlaneSessionConfigured } from '@/core/control-plane';
import { ControlPlaneAuthenticationError, ControlPlaneInsufficientCreditsError, ControlPlaneUsageLimitError } from '@/core/control-plane/errors';
import type { ControlPlaneSessionToken } from '@/core/control-plane/session';
import { buildExecutionSurfaceSnapshot, buildOrchestrationPlan } from '@/core/orchestration';
import { buildReasoningPlanSummary, buildReasoningTrace } from '@/core/reasoning';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import { registry } from '@/core/providers';
import { teamRunner } from '@/core/teams';
import { getOperatorRunStore, recordOperatorRunArtifact, type OperatorRun } from '@/core/operator/runs';
import { buildQualityAssessment, resolveTeacherModel, type MlDatasetCandidate } from '@/core/ml';
import type { SearchMode } from '@/types/search';
import type { ExecutionSurfaceSnapshot, OrchestrationPlan } from '@/core/orchestration';
import { classifyInteractionIntent } from './intent';
import { type OperatorSource } from '@/core/operator/types';
import { estimateHostedUsageDraft } from '@/core/control-plane/pricing';
import { captureRepositorySnapshot } from '@/core/orchestration/repo-inspection';
import {
  applyRequestGuardToPlan,
  assertRequestWithinGuard,
  createRequestGuardRuntime,
  RequestGuardError,
  resolveRequestGuard,
  withRequestGuard,
  type RequestGuard,
} from './request-guard';

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
  runId?: string;
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
  operatorRun?: OperatorRun;
  startedAt: number;
  queryLength: number;
  requestGuard: RequestGuard;
  requireHostedSession: boolean;
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

  if (error instanceof RequestGuardError) {
    return {
      code: error.code,
      message: error.message,
      status: error.statusCode,
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
  const basePlan = buildOrchestrationPlan(request.text, mode, surface);
  const requestGuard = resolveRequestGuard(basePlan, request.text);
  const plan = applyRequestGuardToPlan(basePlan, requestGuard);
  assertRequestWithinGuard(request.text, plan, requestGuard);
  const operatorRun = await getOperatorRunStore().create({
    source: request.source,
    text: request.text,
    mode: plan.taskIntent === 'research' || plan.taskIntent === 'comparison' || mode === 'research' ? 'research' : 'auto',
    title: request.text.slice(0, 80),
  });
  const requestedModelId = request.modelId?.trim() || runtimeSettings.routing.preferredModelId?.trim();
  const selectedModelId = await pickSelectedModelId(plan, requestedModelId);

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
    operatorRun,
    startedAt: Date.now(),
    queryLength: request.text.length,
    requestGuard,
    requireHostedSession: request.requireHostedSession === true,
  };
}

async function maybeRecordHostedUsage(prepared: PreparedInteraction) {
  if (!prepared.hostedAccountId || !prepared.hostedAccount) {
    return;
  }

  if (
    !prepared.requireHostedSession &&
    !prepared.hostedAccount.entitlements.hostedAccess &&
    !prepared.hostedAccount.entitlements.hostedUsageAccounting
  ) {
    return;
  }

  const controlPlane = getControlPlaneService();
  const usageDraft = estimateHostedUsageDraft(prepared.plan, prepared.requestId);
  await controlPlane.recordUsageBundle(prepared.hostedAccountId, usageDraft);
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
  }
) {
  if (!prepared.hostedAccountId) {
    return;
  }

  const controlPlane = getControlPlaneService();
  const latencyMs = Date.now() - prepared.startedAt;
  const sourceCount = output.sources.length;
  const citationCount = (output.text.match(/\[(\d+)\]/g) ?? []).length;
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
    },
  };
  const quality = await buildQualityAssessment(candidate, teacherModel);

  try {
    await controlPlane.recordLearningEvent(prepared.hostedAccountId, {
      requestId: prepared.requestId,
      source: request.source,
      input: request.text,
      intent: prepared.classification.intent,
      plan: buildReasoningPlanSummary(prepared.plan, prepared.classification.intent),
      reasoningSteps,
      output: output.text,
      betterOutput: quality.better_output,
      success: output.success,
      failureReason: output.failureReason,
      latencyMs,
      score: quality.score,
      accepted: quality.accepted,
      modelId: output.modelId ?? prepared.selectedModelId,
      modelProvider: output.modelProvider,
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
  });
}

async function recordOperatorRunOutput(
  prepared: PreparedInteraction,
  output: {
    text: string;
    sources: Array<{ url: string; title: string }>;
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
  const guardRuntime = createRequestGuardRuntime(prepared.requestGuard);
  const account = prepared.hostedAccount;
  const runtimeSettings = readRuntimeSettingsSync();

  try {
    guardRuntime.assertActive();

    if (request.requireHostedSession && isControlPlaneSessionConfigured() && !prepared.controlPlaneSession?.accountId) {
      throw new ControlPlaneAuthenticationError('Control-plane session is required for the main chat surface');
    }

    if (prepared.hostedAccountId && account) {
      await withRequestGuard(guardRuntime, maybeRecordHostedUsage(prepared));
    }

    if (prepared.plan.executionMode === 'team' && runtimeSettings.team.enabled && runtimeSettings.team.defaultMode !== 'single') {
      const team = await withRequestGuard(guardRuntime, teamRunner.run({
        query: request.text,
        mode: prepared.mode,
        requestedModelId: prepared.selectedModelId,
        sourcePlan: prepared.plan,
        maxConcurrentAgents: Math.min(runtimeSettings.team.maxConcurrentAgents, prepared.plan.teamPolicy.maxConcurrentAgents),
        maxTasksPerRun: Math.min(runtimeSettings.team.maxTasksPerRun, prepared.plan.teamPolicy.maxTasksPerRun),
        allowCloudEscalation: runtimeSettings.team.allowCloudEscalation,
        contextAugments: prepared.memoryContext,
        searchEnabled: runtimeSettings.routing.searchEnabled,
        abortSignal: guardRuntime.signal,
        maxOutputTokens: prepared.requestGuard.maxOutputTokens,
        maxExecutionMs: prepared.requestGuard.maxExecutionMs,
      }));

      await recordInteractionOutput(prepared, request, {
        text: team.text,
        sources: team.sources.map((source) => ({ url: source.url, title: source.title })),
        totalUsage: createEmptyLanguageModelUsage(),
        modelProvider: team.modelProvider,
        modelId: team.modelId,
      });
      await recordOperatorRunOutput(prepared, {
        text: team.text,
        sources: team.sources.map((source) => ({ url: source.url, title: source.title })),
      });

      return {
        text: team.text,
        sources: team.sources.map((source) => ({ url: source.url, title: source.title })),
        plan: prepared.plan,
        surface: prepared.surface,
        modelId: team.modelId,
        classification: prepared.classification,
        runId: prepared.operatorRun?.id,
      };
    }

    const { text, sources, plan } = await withRequestGuard(guardRuntime, answerEngine.executeText(request.text, prepared.selectedModelId, prepared.mode, {
      plan: prepared.plan,
      surface: prepared.surface,
      accountId: prepared.hostedAccountId,
      searchEnabled: runtimeSettings.routing.searchEnabled,
      contextAugments: prepared.memoryContext,
      abortSignal: guardRuntime.signal,
      maxOutputTokens: prepared.requestGuard.maxOutputTokens,
      onFinish: async (event, context) => {
        await recordInteractionOutput(prepared, request, {
          text: event.text,
          sources: context.sources.map((source) => ({ url: source.url, title: source.title })),
          totalUsage: event.totalUsage,
          modelProvider: context.providerId,
          modelId: prepared.selectedModelId,
        });
        await recordOperatorRunOutput(prepared, {
          text: event.text,
          sources: context.sources.map((source) => ({ url: source.url, title: source.title })),
        });
      },
    }));

    return {
      text,
      sources: sources.map((source) => ({ url: source.url, title: source.title })),
      plan,
      surface: prepared.surface,
      modelId: prepared.selectedModelId,
      classification: prepared.classification,
      runId: prepared.operatorRun?.id,
    };
  } catch (error) {
    await recordLearningEvent(prepared, request, {
      text: '',
      sources: [],
      success: false,
      failureReason: normalizeError(error).message,
      modelId: prepared.selectedModelId,
    });
    throw error;
  } finally {
    guardRuntime.clear();
  }
}

export async function executeInteractionStream(request: InteractionRequest) {
  const prepared = await prepareInteraction(request);
  const guardRuntime = createRequestGuardRuntime(prepared.requestGuard);
  const account = prepared.hostedAccount;
  const runtimeSettings = readRuntimeSettingsSync();

  try {
    guardRuntime.assertActive();

    if (request.requireHostedSession && isControlPlaneSessionConfigured() && !prepared.controlPlaneSession?.accountId) {
      throw new ControlPlaneAuthenticationError('Control-plane session is required for the main chat surface');
    }

    if (prepared.hostedAccountId && account) {
      await withRequestGuard(guardRuntime, maybeRecordHostedUsage(prepared));
    }

    if (prepared.plan.executionMode === 'team' && runtimeSettings.team.enabled && runtimeSettings.team.defaultMode !== 'single') {
      const { createUIMessageStream, createUIMessageStreamResponse } = await import('ai');
      const stream = createUIMessageStream({
        execute: async ({ writer }) => {
          const team = await withRequestGuard(guardRuntime, teamRunner.run({
            query: request.text,
            mode: prepared.mode,
            requestedModelId: prepared.selectedModelId,
            sourcePlan: prepared.plan,
            maxConcurrentAgents: Math.min(runtimeSettings.team.maxConcurrentAgents, prepared.plan.teamPolicy.maxConcurrentAgents),
            maxTasksPerRun: Math.min(runtimeSettings.team.maxTasksPerRun, prepared.plan.teamPolicy.maxTasksPerRun),
            allowCloudEscalation: runtimeSettings.team.allowCloudEscalation,
            contextAugments: prepared.memoryContext,
            searchEnabled: runtimeSettings.routing.searchEnabled,
            abortSignal: guardRuntime.signal,
            maxOutputTokens: prepared.requestGuard.maxOutputTokens,
            maxExecutionMs: prepared.requestGuard.maxExecutionMs,
          }));
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
          await recordOperatorRunOutput(prepared, {
            text: team.text,
            sources: team.sources.map((source) => ({ url: source.url, title: source.title })),
          });
          guardRuntime.clear();
        },
      });

      return createUIMessageStreamResponse({ stream });
    }

    const { stream } = await answerEngine.execute(request.text, prepared.selectedModelId, prepared.mode, {
      plan: prepared.plan,
      surface: prepared.surface,
      accountId: prepared.hostedAccountId,
      searchEnabled: runtimeSettings.routing.searchEnabled,
      contextAugments: prepared.memoryContext,
      abortSignal: guardRuntime.signal,
      maxOutputTokens: prepared.requestGuard.maxOutputTokens,
      onFinish: async (event, context) => {
        await recordInteractionOutput(prepared, request, {
          text: event.text,
          sources: context.sources.map((source) => ({ url: source.url, title: source.title })),
          totalUsage: event.totalUsage,
          modelProvider: context.providerId,
          modelId: prepared.selectedModelId,
        });
        await recordOperatorRunOutput(prepared, {
          text: event.text,
          sources: context.sources.map((source) => ({ url: source.url, title: source.title })),
        });
        guardRuntime.clear();
      },
      onError: async (error) => {
        await recordLearningEvent(prepared, request, {
          text: '',
          sources: [],
          success: false,
          failureReason: normalizeError(error).message,
          modelId: prepared.selectedModelId,
        });
        console.warn('Elyan interaction stream error', error);
        guardRuntime.clear();
      },
      onAbort: async () => {
        await recordLearningEvent(prepared, request, {
          text: '',
          sources: [],
          success: false,
          failureReason: 'Request was aborted by the execution guard.',
          modelId: prepared.selectedModelId,
        });
        guardRuntime.clear();
      },
    });

    return stream;
  } catch (error) {
    guardRuntime.clear();
    await recordLearningEvent(prepared, request, {
      text: '',
      sources: [],
      success: false,
      failureReason: normalizeError(error).message,
      modelId: prepared.selectedModelId,
    });
    throw error;
  }
}

export function normalizeInteractionError(error: unknown) {
  return normalizeError(error);
}
