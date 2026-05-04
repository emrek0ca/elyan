import { reranker, scraper, searchClient } from '@/core/search';
import { ScrapedContent, SearxNGResult } from '@/types/search';
import {
  ingestRetrievalText,
  searchRetrievalDocumentsHybrid,
  type RetrievalDocumentRecord,
} from './vector-store';
import { normalizeRetrievalText, truncateRetrievalText } from './embeddings';
import { filterContextBlocks } from './context';

export type SelectiveWebRetrievalInput = {
  query: string;
  accountId?: string | null;
  plan?: {
    routingMode: string;
    reasoningDepth: string;
    taskIntent: string;
    executionPolicy?: {
      shouldRetrieve?: boolean;
    };
    retrieval: {
      language: string;
      rounds: number;
      maxUrls: number;
      rerankTopK: number;
      expandSearchQueries?: boolean;
    };
  };
  searchEnabled?: boolean;
};

export type SelectiveWebRetrievalResult = {
  searchAvailable: boolean;
  liveSearchUsed: boolean;
  storedContexts: RetrievalDocumentRecord[];
  sources: ScrapedContent[];
  contextBlocks: string[];
};

function deriveSearchQueries(query: string, expandSearchQueries: boolean) {
  const trimmed = query.trim();
  if (!expandSearchQueries) {
    return [trimmed];
  }

  const fragments = trimmed
    .split(/[?.!]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .slice(0, 3);

  return Array.from(new Set([trimmed, ...fragments]));
}

function formatStoredContext(entry: RetrievalDocumentRecord) {
  const title = entry.title?.trim() || entry.sourceName;
  const url = entry.sourceUrl?.trim();
  const prefix = `${entry.sourceKind.toUpperCase()} ${title}`;
  const body = truncateRetrievalText(entry.content, 1_500);

  return [
    prefix,
    url ? `URL: ${url}` : '',
    body,
  ].filter(Boolean).join('\n');
}

function formatSourceContext(source: ScrapedContent) {
  const title = source.title?.trim() || source.url;
  const body = truncateRetrievalText(normalizeRetrievalText(source.content), 1_500);

  return [
    `WEB ${title}`,
    `URL: ${source.url}`,
    body,
  ].join('\n');
}

function dedupeResults<T extends { url: string }>(results: T[]) {
  const seen = new Set<string>();
  return results.filter((result) => {
    if (seen.has(result.url)) {
      return false;
    }

    seen.add(result.url);
    return true;
  });
}

function dedupeSources(sources: ScrapedContent[]) {
  return dedupeResults(sources);
}

function getResultScore(result: SearxNGResult) {
  const rawScore =
    typeof (result as SearxNGResult & { _score?: number })._score === 'number'
      ? (result as SearxNGResult & { _score?: number })._score
      : result.score;

  return Math.max(0, Math.min(1, Number(rawScore ?? 0)));
}

export async function runSelectiveWebRetrieval(input: SelectiveWebRetrievalInput): Promise<SelectiveWebRetrievalResult> {
  const searchAvailable = input.searchEnabled !== false && (await searchClient.isAvailable());
  const storedContexts = await searchRetrievalDocumentsHybrid(input.query, {
    accountId: input.accountId,
    sourceKinds: ['bootstrap', 'web', 'learning'],
    limit: 6,
  });

  const storedContextBlocks = filterContextBlocks(
    storedContexts.map((entry) => ({
      text: formatStoredContext(entry),
      score: entry.combinedScore ?? entry.similarity ?? entry.keywordScore ?? 0,
    })),
    { maxTokens: 1_200, maxBlocks: 4, minScore: 0.2 }
  );
  if (!searchAvailable || input.plan?.executionPolicy?.shouldRetrieve === false || (input.plan?.retrieval.rounds ?? 0) === 0) {
    return {
      searchAvailable,
      liveSearchUsed: false,
      storedContexts: storedContexts.map((entry) => ({ ...entry, similarity: entry.similarity ?? 0 })),
      sources: [],
      contextBlocks: storedContextBlocks,
    };
  }

  const searchQueries = deriveSearchQueries(input.query, Boolean(input.plan?.retrieval.expandSearchQueries));
  const searchResultsNested = await Promise.allSettled(
    searchQueries.slice(0, Math.max(1, input.plan?.retrieval.rounds ?? 1)).map((searchQuery) =>
      searchClient.search(searchQuery, {
        language: input.plan?.retrieval.language,
      })
    )
  );

  const fulfilledResults = searchResultsNested
    .filter((result): result is PromiseFulfilledResult<SearxNGResult[]> => result.status === 'fulfilled')
    .flatMap((result) => result.value);

  const ranked = reranker.rerank(input.query, dedupeResults(fulfilledResults), input.plan?.retrieval.rerankTopK ?? 12);
  const scraped = await scraper.scrapeUrls(
    ranked.slice(0, Math.max(1, input.plan?.retrieval.maxUrls ?? 5)).map((result) => result.url),
    Math.max(1, input.plan?.retrieval.maxUrls ?? 5)
  );
  const sources = dedupeSources(scraped);
  const sourceContextBlocks = filterContextBlocks(
    ranked
      .map((result) => {
        const source = sources.find((item) => item.url === result.url);
        if (!source) {
          return null;
        }

        return {
          text: formatSourceContext(source),
          score: getResultScore(result),
        };
      })
      .filter((entry): entry is { text: string; score: number } => Boolean(entry)),
    { maxTokens: 1_400, maxBlocks: 4, minScore: 0.15 }
  );

  await Promise.allSettled(
    sources.map((source) =>
      ingestRetrievalText({
        accountId: input.accountId,
        sourceKind: 'web',
        sourceName: 'searxng',
        sourceUrl: source.url,
        title: source.title || source.url,
        content: source.content,
        metadata: {
          query: input.query,
          source_count: sources.length,
          routing_mode: input.plan?.routingMode,
          reasoning_depth: input.plan?.reasoningDepth,
          task_intent: input.plan?.taskIntent,
        },
      })
    )
  );

  const refreshedContexts = await searchRetrievalDocumentsHybrid(input.query, {
    accountId: input.accountId,
    sourceKinds: ['bootstrap', 'web', 'learning'],
    limit: 6,
  });

  const contextBlocks = filterContextBlocks(
    [
      ...refreshedContexts.map((entry) => ({
        text: formatStoredContext(entry),
        score: entry.combinedScore ?? entry.similarity ?? entry.keywordScore ?? 0,
      })),
      ...sourceContextBlocks.map((text) => ({ text, score: 0.7 })),
    ],
    { maxTokens: 1_800, maxBlocks: 8, minScore: 0.15 }
  );

  return {
    searchAvailable,
    liveSearchUsed: sources.length > 0,
    storedContexts: refreshedContexts,
    sources,
    contextBlocks,
  };
}
