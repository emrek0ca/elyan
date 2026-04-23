import { NextRequest, NextResponse } from 'next/server';
import { randomUUID } from 'crypto';
import { answerEngine } from '@/core/agents/answer-engine';
import { buildExecutionSurfaceSnapshot, buildOrchestrationPlan } from '@/core/orchestration';
import { buildEvaluationSignalDraft } from '@/core/orchestration/evaluation';
import {
  estimateHostedUsageDraft,
  getControlPlaneService,
  getControlPlaneSessionToken,
} from '@/core/control-plane';
import { readRuntimeSettingsSync } from '@/core/runtime-settings';
import { SearchMode } from '@/types/search';
import { env } from '@/lib/env'; // Triggers strict validation
import { z } from 'zod';
import { registry } from '@/core/providers';

const chatMessageSchema = z.object({
  role: z.string().min(1),
  content: z.string().trim().min(1),
});

const chatRequestSchema = z.object({
  messages: z.array(chatMessageSchema).min(1),
  mode: z.enum(['speed', 'research']).default('speed'),
  modelId: z.string().trim().min(1).optional(),
});

function invalidChatRequest(code: string, message: string, issues?: Record<string, string[] | undefined>) {
  return NextResponse.json(
    {
      error: message,
      code,
      ...(issues ? { issues } : {}),
    },
    { status: 400 }
  );
}

function createEmptyLanguageModelUsage() {
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

async function readChatRequestBody(request: NextRequest) {
  const rawBody = await request.text();

  if (!rawBody.trim()) {
    return {
      ok: false as const,
      response: invalidChatRequest('empty_request_body', 'Chat request body is empty.'),
    };
  }

  try {
    return {
      ok: true as const,
      body: JSON.parse(rawBody) as unknown,
    };
  } catch {
    return {
      ok: false as const,
      response: invalidChatRequest('invalid_json_body', 'Chat request body must be valid JSON.'),
    };
  }
}

function normalizeChatError(error: unknown) {
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

export async function POST(request: NextRequest) {
  try {
    void env;

    const bodyResult = await readChatRequestBody(request);
    if (!bodyResult.ok) {
      return bodyResult.response;
    }

    const parsed = chatRequestSchema.safeParse(bodyResult.body);

    if (!parsed.success) {
      return invalidChatRequest(
        'invalid_chat_request',
        'Chat request body does not match the expected schema.',
        parsed.error.flatten().fieldErrors
      );
    }

    const { messages, mode, modelId } = parsed.data;
    const latestUserMessage = [...messages].reverse().find((message) => message.role === 'user')?.content
      ?? messages[messages.length - 1].content;
    const resolvedMode: SearchMode = mode;
    const requestId = request.headers.get('x-request-id')?.trim() || randomUUID();
    const runtimeSettings = readRuntimeSettingsSync();
    const surface = buildExecutionSurfaceSnapshot();
    const plan = buildOrchestrationPlan(latestUserMessage, resolvedMode, surface);
    const controlPlane = getControlPlaneService();
    let hostedAccount: Awaited<ReturnType<typeof controlPlane.getAccount>> | null = null;
    let captureEvaluation = false;

    const selectedModel =
      modelId?.trim() ||
      runtimeSettings.routing.preferredModelId?.trim() ||
      (await registry.resolvePreferredModelId({
        routingMode: plan.routingMode,
        taskIntent: plan.taskIntent,
        reasoningDepth: plan.reasoningDepth,
      }));

    if (env.NEXTAUTH_SECRET) {
      const session = await getControlPlaneSessionToken(request);

      if (session?.accountId) {
        const account = await controlPlane.getAccount(session.accountId);
        hostedAccount = account;

        if (account.entitlements.hostedAccess && account.entitlements.hostedUsageAccounting) {
          const usageDraft = estimateHostedUsageDraft(plan, requestId);
          await controlPlane.recordUsageBundle(session.accountId, usageDraft);
        }

        captureEvaluation = account.entitlements.hostedImprovementSignals;
      }
    }

    const evaluationAccountId = hostedAccount?.accountId;

    const startedAt = Date.now();
    const { stream } = await answerEngine.execute(latestUserMessage, selectedModel, resolvedMode, {
      plan,
      surface,
      searchEnabled: runtimeSettings.routing.searchEnabled,
      onFinish:
        captureEvaluation && evaluationAccountId
          ? async (event, context) => {
              try {
                if (!evaluationAccountId) {
                  return;
                }

                const signal = buildEvaluationSignalDraft({
                  requestId,
                  mode: resolvedMode,
                  plan: context.plan,
                  surface: context.surface,
                  searchAvailable: context.searchAvailable,
                  operatorNotes: context.operatorNotes,
                  operatorTarget: context.operatorTarget,
                  modelProvider: event.model.provider,
                  modelId: event.model.modelId,
                  text: event.text,
                  queryLength: context.query.length,
                  latencyMs: Date.now() - startedAt,
                  totalUsage: event.totalUsage,
                  toolCallCount: event.toolCalls.length,
                  toolResultCount: event.toolResults.length,
                  sourcesCount: context.sources.length,
                });

                await controlPlane.recordEvaluationSignal(evaluationAccountId, signal);
              } catch (evaluationError) {
                console.warn('Elyan evaluation capture failed', evaluationError);
              }
            }
          : undefined,
      onError:
        captureEvaluation && evaluationAccountId
          ? async (error, context) => {
              try {
                if (!evaluationAccountId) {
                  return;
                }

                const signal = buildEvaluationSignalDraft({
                  requestId,
                  mode: resolvedMode,
                  plan: context.plan,
                  surface: context.surface,
                  searchAvailable: context.searchAvailable,
                  operatorNotes: [
                    ...context.operatorNotes,
                    `Stream error: ${error instanceof Error ? error.message : String(error)}`,
                  ],
                  operatorTarget: context.operatorTarget,
                  modelProvider: context.providerId,
                  modelId: context.resolvedModelId,
                  text: '',
                  queryLength: context.query.length,
                  latencyMs: Date.now() - startedAt,
                  totalUsage: createEmptyLanguageModelUsage(),
                  toolCallCount: 0,
                  toolResultCount: 0,
                  sourcesCount: context.sources.length,
                });

                await controlPlane.recordEvaluationSignal(evaluationAccountId, signal);
              } catch (evaluationError) {
                console.warn('Elyan evaluation error capture failed', evaluationError);
              }
            }
          : undefined,
    });
    return stream;
  } catch (error: unknown) {
    console.error('Chat endpoint error:', error);
    const normalized = normalizeChatError(error);
    return NextResponse.json(
      {
        error: normalized.message,
        code: normalized.code,
      },
      { status: normalized.status }
    );
  }
}
