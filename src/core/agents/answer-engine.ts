import { generateText, streamText, type OnFinishEvent } from 'ai';
import { registry } from '@/core/providers';
import { citationEngine, reranker, scraper, searchClient } from '@/core/search';
import { SearchMode, SearxNGResult, type ScrapedContent } from '@/types/search';
import { resolveAnswerPrompt } from './answer-prompts';
import {
  buildExecutionSurfaceSnapshot,
  buildOrchestrationPlan,
  refreshExecutionSurfaceWithLiveMcp,
  runOperatorPreflight,
  type ExecutionSurfaceSnapshot,
  type ExecutionTarget,
  type OrchestrationPlan,
} from '@/core/orchestration';

type PreparedAnswer = {
  model: Parameters<typeof streamText>[0]['model'];
  providerId: string;
  resolvedModelId: string;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  sources: ScrapedContent[];
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
  searchAvailable: boolean;
  operatorNotes: string[];
  operatorTarget?: ExecutionTarget;
};

type AnswerExecutionOptions = {
  plan?: OrchestrationPlan;
  surface?: ExecutionSurfaceSnapshot;
  searchEnabled?: boolean;
  onFinish?: (event: OnFinishEvent, context: AnswerFinishContext) => PromiseLike<void> | void;
  onError?: (error: unknown, context: AnswerFinishContext) => PromiseLike<void> | void;
  onAbort?: (context: AnswerFinishContext) => PromiseLike<void> | void;
};

function dedupeResults<T extends { url: string }>(results: T[]): T[] {
  const seen = new Set<string>();
  const deduped: T[] = [];

  for (const result of results) {
    if (seen.has(result.url)) {
      continue;
    }

    seen.add(result.url);
    deduped.push(result);
  }

  return deduped;
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
      searchAvailable: prepared.searchAvailable,
      operatorNotes: prepared.operatorNotes,
      operatorTarget: prepared.operatorTarget,
    };
    try {
      const result = await streamText({
        model: prepared.model,
        system: prepared.systemPrompt,
        prompt: query,
        temperature: prepared.sources.length > 0 ? prepared.plan.temperature : 0,
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
      searchAvailable: prepared.searchAvailable,
      operatorNotes: prepared.operatorNotes,
      operatorTarget: prepared.operatorTarget,
    };
    try {
      const result = await generateText({
        model: prepared.model,
        system: prepared.systemPrompt,
        prompt: query,
        temperature: prepared.sources.length > 0 ? prepared.plan.temperature : 0,
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
    const baseSurface = options?.surface ?? buildExecutionSurfaceSnapshot();
    let plan = options?.plan ?? buildOrchestrationPlan(query, mode, baseSurface);
    let surface = baseSurface;

    if (plan.executionPolicy.shouldDiscoverMcp) {
      surface = await refreshExecutionSurfaceWithLiveMcp(baseSurface);
      plan = buildOrchestrationPlan(query, mode, surface);
    }

    const operatorOutcome = await runOperatorPreflight(query, plan.executionPolicy, surface);
    const resolvedModelId = await registry.resolvePreferredModelId({
      preferredModelId: modelId,
      routingMode: plan.routingMode,
      taskIntent: plan.taskIntent,
      reasoningDepth: plan.reasoningDepth,
    });
    const { provider, model } = registry.resolveModel(resolvedModelId);

    const searchAvailable =
      plan.executionPolicy.shouldRetrieve &&
      (options?.searchEnabled ?? true) &&
      (await searchClient.isAvailable());
    const searchQueries = searchAvailable && plan.retrieval.expandSearchQueries
      ? await this.generateResearchQueries(query, model)
      : [query];
    const limitedSearchQueries = searchQueries.slice(0, plan.retrieval.rounds);

    const searchResultsNested = searchAvailable
      ? await Promise.allSettled(
          limitedSearchQueries.map((searchQuery) =>
            searchClient.search(searchQuery, {
              language: plan.retrieval.language,
            })
          )
        )
      : [];

    const fulfilledResults = searchResultsNested
      .filter((result): result is PromiseFulfilledResult<SearxNGResult[]> => result.status === 'fulfilled')
      .flatMap((result) => result.value);

    const rankedResults = reranker.rerank(query, dedupeResults(fulfilledResults), plan.retrieval.rerankTopK);
    const scrapedContent = await scraper.scrapeUrls(
      rankedResults.slice(0, plan.retrieval.maxUrls).map((result) => result.url),
      plan.retrieval.maxUrls
    );

    const sources = dedupeSources([...operatorOutcome.sources, ...scrapedContent]);
    const hasSources = sources.length > 0;
    const operatorContext = operatorOutcome.contextBlocks.length > 0 ? operatorOutcome.contextBlocks.join('\n\n') : '';
    const context = hasSources
      ? citationEngine.buildContext(sources)
      : 'No reliable sources were retrieved.';
    const systemPrompt = resolveAnswerPrompt(mode, [operatorContext, context].filter(Boolean).join('\n\n'), hasSources);

    return {
      model,
      providerId: provider.id,
      resolvedModelId,
      plan,
      surface,
      sources,
      systemPrompt,
      query,
      searchAvailable,
      operatorNotes: operatorOutcome.notes,
      operatorTarget: operatorOutcome.target,
    };
  }

  private async generateResearchQueries(query: string, model: Parameters<typeof streamText>[0]['model']) {
    try {
      const response = await generateText({
        model,
        system:
          'Generate 2 short search queries that complement the user query. Return one query per line and nothing else.',
        prompt: query,
      });

      const extraQueries = response.text
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, 2);

      return [query, ...extraQueries];
    } catch {
      return [query];
    }
  }
}

export const answerEngine = new AnswerEngine();
