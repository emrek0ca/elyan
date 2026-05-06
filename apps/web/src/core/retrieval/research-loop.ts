import { recordOperatorRunArtifact } from '@/core/operator/runs';
import { filterContextBlocks } from './context';
import { fetchConnectorBundle, listConnectorRegistry } from '@/core/connectors/registry';
import type { OrchestrationPlan } from '@/core/orchestration';
import type { SelectiveWebRetrievalResult } from './web';
import type { RunTraceRecorder } from '@/core/observability/run-trace';

export type ResearchLoopInput = {
  query: string;
  accountId?: string | null;
  spaceId?: string | null;
  plan?: OrchestrationPlan;
  searchEnabled?: boolean;
  operatorRunId?: string;
  trace?: RunTraceRecorder;
  signal?: AbortSignal;
};

function normalizeIterationContext(blocks: string[]) {
  return filterContextBlocks(blocks, {
    maxTokens: 1_500,
    maxBlocks: 6,
    minScore: 0.15,
  });
}

function refineQuery(query: string, blocks: string[]) {
  const evidence = blocks
    .map((block) => block.split('\n').slice(0, 2).join(' '))
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!evidence) {
    return query;
  }

  return `${query} ${evidence}`.slice(0, 260);
}

async function recordIterationArtifact(input: ResearchLoopInput, iteration: number, blocks: string[], sourceCount: number) {
  if (!input.operatorRunId) {
    return;
  }

  await recordOperatorRunArtifact(input.operatorRunId, {
    kind: 'research',
    title: `Research iteration ${iteration + 1}`,
    content: [
      `Query: ${input.query}`,
      `Iteration: ${iteration + 1}`,
      `Source count: ${sourceCount}`,
      '',
      ...blocks,
    ].join('\n'),
      metadata: {
        iteration,
        sourceCount,
        taskIntent: input.plan?.taskIntent ?? 'direct_answer',
        connectors: listConnectorRegistry().map((connector) => connector.id),
      },
    });
}

export async function runResearchLoop(input: ResearchLoopInput): Promise<SelectiveWebRetrievalResult> {
  const maxIterations = Math.max(1, Math.min(input.plan?.retrieval.rounds ?? 1, 3));
  let currentQuery = input.query;
  const allSources: SelectiveWebRetrievalResult['sources'] = [];
  const allStoredContexts: SelectiveWebRetrievalResult['storedContexts'] = [];
  const combinedBlocks: string[] = [];
  let searchAvailable = false;
  let liveSearchUsed = false;

  for (let iteration = 0; iteration < maxIterations; iteration += 1) {
    if (input.signal?.aborted) {
      throw new Error('Operation aborted.');
    }
    const [storedContextResult, learningHintResult, webResult] = await fetchConnectorBundle({
      ...input,
      query: currentQuery,
      trace: input.trace,
    });

    searchAvailable = searchAvailable || Boolean(webResult.searchAvailable);
    liveSearchUsed = liveSearchUsed || Boolean(webResult.liveSearchUsed);
    allSources.push(...webResult.sources);
    allStoredContexts.push(...storedContextResult.storedContexts);
    const iterationBlocks = normalizeIterationContext([
      ...storedContextResult.contextBlocks,
      ...learningHintResult.contextBlocks,
      ...webResult.contextBlocks,
    ]);
    combinedBlocks.push(...iterationBlocks);

    await recordIterationArtifact(input, iteration, iterationBlocks, webResult.sources.length);

    if (iteration + 1 >= maxIterations) {
      break;
    }

    currentQuery = refineQuery(currentQuery, iterationBlocks);
  }

  const dedupedSources = allSources.filter((source, index, array) =>
    array.findIndex((candidate) => candidate.url === source.url) === index
  );
  const dedupedContexts = allStoredContexts.filter(
    (context, index, array) => array.findIndex((candidate) => candidate.documentId === context.documentId) === index
  );

  return {
    searchAvailable,
    liveSearchUsed,
    storedContexts: dedupedContexts,
    sources: dedupedSources,
    contextBlocks: normalizeIterationContext(combinedBlocks),
  };
}
