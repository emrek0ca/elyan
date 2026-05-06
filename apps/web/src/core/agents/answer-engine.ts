import { generateText, streamText, type OnFinishEvent } from 'ai';
import { registry } from '@/core/providers';
import { citationEngine } from '@/core/search';
import { SearchMode, type ScrapedContent } from '@/types/search';
import { resolveBrainPreferredModelId } from '@/core/ml/model-routing';
import { resolveAnswerPrompt } from './answer-prompts';
import { runResearchLoop } from '@/core/retrieval';
import { filterContextBlocks } from '@/core/retrieval/context';
import { loadLearningRoutingHints } from '@/core/control-plane/learning/signal-extractor';
import {
  buildExecutionSurfaceSnapshot,
  buildOrchestrationPlan,
  refreshExecutionSurfaceWithLiveMcp,
  runOperatorPreflight,
  type ExecutionSurfaceSnapshot,
  type ExecutionTarget,
  type OrchestrationPlan,
} from '@/core/orchestration';
import type { CapabilityRuntimeContext } from '@/core/capabilities/types';
import type { RunTraceRecorder } from '@/core/observability/run-trace';

type PreparedAnswer = {
  model: Parameters<typeof streamText>[0]['model'];
  providerId: string;
  resolvedModelId: string;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  sources: ScrapedContent[];
  retrievalContextBlocks: string[];
  systemPrompt: string;
  query: string;
  searchAvailable: boolean;
  operatorNotes: string[];
  operatorTarget?: ExecutionTarget;
};

export type AnswerFinishContext = {
  query: string;
  providerId: string;
  resolvedModelId: string;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  sources: ScrapedContent[];
  retrievalContextBlocks: string[];
  searchAvailable: boolean;
  operatorNotes: string[];
  operatorTarget?: ExecutionTarget;
};

type AnswerExecutionOptions = {
  plan?: OrchestrationPlan;
  surface?: ExecutionSurfaceSnapshot;
  searchEnabled?: boolean;
  accountId?: string;
  spaceId?: string;
  operatorRunId?: string;
  contextAugments?: string[];
  runtimeContext?: CapabilityRuntimeContext;
  trace?: RunTraceRecorder;
  signal?: AbortSignal;
  onFinish?: (event: OnFinishEvent, context: AnswerFinishContext) => PromiseLike<void> | void;
  onError?: (error: unknown, context: AnswerFinishContext) => PromiseLike<void> | void;
  onAbort?: (context: AnswerFinishContext) => PromiseLike<void> | void;
};

function chatDebug(message: string, payload: Record<string, unknown>) {
  if (process.env.NODE_ENV !== 'production') {
    console.debug(message, payload);
  }
}

function dedupeSources(sources: ScrapedContent[]): ScrapedContent[] {
  const seen = new Set<string>();
  const deduped: ScrapedContent[] = [];

  for (const source of sources) {
    if (seen.has(source.url)) {
      continue;
    }

    seen.add(source.url);
    deduped.push(source);
  }

  return deduped;
}

export class AnswerEngine {
  async execute(
    query: string,
    modelId: string,
    mode: SearchMode = 'speed',
    options?: AnswerExecutionOptions
  ) {
    const prepared = await this.prepare(query, modelId, mode, options);
    const context: AnswerFinishContext = {
      query: prepared.query,
      providerId: prepared.providerId,
      resolvedModelId: prepared.resolvedModelId,
      plan: prepared.plan,
      surface: prepared.surface,
      sources: prepared.sources,
      retrievalContextBlocks: prepared.retrievalContextBlocks,
      searchAvailable: prepared.searchAvailable,
      operatorNotes: prepared.operatorNotes,
      operatorTarget: prepared.operatorTarget,
    };
    try {
      const augmentedContext = filterContextBlocks(options?.contextAugments ?? [], {
        maxTokens: 1_200,
        maxBlocks: 6,
        minScore: 0.15,
      }).join('\n\n');
      const result = await streamText({
        model: prepared.model,
        system: augmentedContext ? `${augmentedContext}\n\n${prepared.systemPrompt}` : prepared.systemPrompt,
        prompt: query,
        temperature: prepared.sources.length > 0 ? prepared.plan.temperature : 0,
        abortSignal: options?.signal,
        onFinish: options?.onFinish
          ? async (event) => {
              try {
                await options.onFinish?.(event, context);
              } catch (error) {
                console.warn('Elyan answer finish hook failed', error);
              }
            }
          : undefined,
        onError: options?.onError
          ? async ({ error }) => {
              try {
                await options.onError?.(error, context);
              } catch (hookError) {
                console.warn('Elyan answer error hook failed', hookError);
              }
            }
          : undefined,
        onAbort: options?.onAbort
          ? async () => {
              try {
                await options.onAbort?.(context);
              } catch (hookError) {
                console.warn('Elyan answer abort hook failed', hookError);
              }
          }
          : undefined,
      });

      return {
        stream: result.toUIMessageStreamResponse(),
        sources: prepared.sources,
        plan: prepared.plan,
      };
    } catch (error) {
      if (options?.onError) {
        try {
          await options.onError(error, context);
        } catch (hookError) {
          console.warn('Elyan answer error hook failed', hookError);
        }
      }

      throw error;
    }
  }

  async executeText(
    query: string,
    modelId: string,
    mode: SearchMode = 'speed',
    options?: AnswerExecutionOptions
  ) {
    const prepared = await this.prepare(query, modelId, mode, options);
    const context: AnswerFinishContext = {
      query: prepared.query,
      providerId: prepared.providerId,
      resolvedModelId: prepared.resolvedModelId,
      plan: prepared.plan,
      surface: prepared.surface,
      sources: prepared.sources,
      retrievalContextBlocks: prepared.retrievalContextBlocks,
      searchAvailable: prepared.searchAvailable,
      operatorNotes: prepared.operatorNotes,
      operatorTarget: prepared.operatorTarget,
    };
    try {
      const augmentedContext = filterContextBlocks(options?.contextAugments ?? [], {
        maxTokens: 1_200,
        maxBlocks: 6,
        minScore: 0.15,
      }).join('\n\n');
      const result = await generateText({
        model: prepared.model,
        system: augmentedContext ? `${augmentedContext}\n\n${prepared.systemPrompt}` : prepared.systemPrompt,
        prompt: query,
        temperature: prepared.sources.length > 0 ? prepared.plan.temperature : 0,
        abortSignal: options?.signal,
        onFinish: options?.onFinish
          ? async (event) => {
              try {
                await options.onFinish?.(event, context);
              } catch (error) {
                console.warn('Elyan answer finish hook failed', error);
              }
          }
          : undefined,
      });

      return {
        text: result.text,
        sources: prepared.sources,
        plan: prepared.plan,
      };
    } catch (error) {
      if (options?.onError) {
        try {
          await options.onError(error, context);
        } catch (hookError) {
          console.warn('Elyan answer error hook failed', hookError);
        }
      }

      throw error;
    }
  }

  private async prepare(
    query: string,
    modelId: string,
    mode: SearchMode,
    options?: AnswerExecutionOptions
  ): Promise<PreparedAnswer> {
    chatDebug('[chat] answer prepare', {
      queryLength: query.length,
      requestedModelId: modelId,
      mode,
    });

    const baseSurface = options?.surface ?? buildExecutionSurfaceSnapshot();
    let plan = options?.plan ?? buildOrchestrationPlan(query, mode, baseSurface);
    let surface = baseSurface;
    const spaceId = options?.spaceId ?? options?.accountId;

    if (plan.executionPolicy.shouldDiscoverMcp) {
      surface = await refreshExecutionSurfaceWithLiveMcp(baseSurface);
      plan = buildOrchestrationPlan(query, mode, surface);
    }

    const operatorOutcome = await runOperatorPreflight(
      query,
      plan.executionPolicy,
      surface,
      options?.runtimeContext,
      options?.trace,
      options?.signal
    );
    const learningRouting = await loadLearningRoutingHints({
      taskType: plan.taskIntent,
      modelId,
      spaceId,
    });
    const brainPreferredModelId = await resolveBrainPreferredModelId();
    const resolvedModelId = await registry.resolvePreferredModelId({
      preferredModelId: learningRouting.preferredModelId ?? brainPreferredModelId ?? modelId,
      routingMode: learningRouting.routingMode ?? plan.routingMode,
      taskIntent: plan.taskIntent,
      reasoningDepth: plan.reasoningDepth,
    });
    const { provider, model } = registry.resolveModel(resolvedModelId);
    chatDebug('[chat] answer model selected', {
      resolvedModelId,
      providerId: provider.id,
    });

    const retrieval = await runResearchLoop({
      query,
      accountId: options?.accountId,
      spaceId,
      plan,
      searchEnabled: options?.searchEnabled ?? true,
      operatorRunId: options?.operatorRunId,
      trace: options?.trace,
      signal: options?.signal,
    });

    const sources = dedupeSources([...operatorOutcome.sources, ...retrieval.sources]);
    const hasSources = sources.length > 0;
    const operatorContext = filterContextBlocks(operatorOutcome.contextBlocks, {
      maxTokens: 1_000,
      maxBlocks: 4,
      minScore: 0.15,
    }).join('\n\n');
    const retrievalContext = filterContextBlocks(retrieval.contextBlocks, {
      maxTokens: 1_200,
      maxBlocks: 6,
      minScore: 0.15,
    }).join('\n\n');
    const context = hasSources
      ? citationEngine.buildContext(sources)
      : 'No reliable sources were retrieved.';
    const systemPrompt = resolveAnswerPrompt(
      mode,
      [operatorContext, retrievalContext, context].filter(Boolean).join('\n\n'),
      hasSources,
      {
        plan,
        operatorNotes: operatorOutcome.notes,
      }
    );
    chatDebug('[chat] answer prepared', {
      resolvedModelId,
      sourceCount: sources.length,
    });

    return {
      model,
      providerId: provider.id,
      resolvedModelId,
      plan,
      surface,
      sources,
      retrievalContextBlocks: retrieval.contextBlocks,
      systemPrompt,
      query,
      searchAvailable: retrieval.searchAvailable,
      operatorNotes: operatorOutcome.notes,
      operatorTarget: operatorOutcome.target,
    };
  }

}

export const answerEngine = new AnswerEngine();
