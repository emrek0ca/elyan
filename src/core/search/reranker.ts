import { SearxNGResult } from '@/types/search';
import { rankFuzzyItems } from '@/core/capabilities';

export class ResultReranker {
  rerank(query: string, results: SearxNGResult[], limit = results.length): SearxNGResult[] {
    const cappedResults = results.slice(0, limit);
    const ranked = rankFuzzyItems(
      query,
      cappedResults.map((result, index) => ({
        id: `${index}`,
        title: result.title,
        content: result.content,
        url: result.url,
        tags: [result.engine, result.category].filter((value): value is string => Boolean(value)),
        metadata: result.publishedDate ? { publishedAt: result.publishedDate } : {},
      })),
      results.length,
      0.35
    );

    const scoreByUrl = new Map<string, number>();
    for (const entry of ranked) {
      if (entry.item.url) {
        scoreByUrl.set(entry.item.url, entry.score);
      }
    }

    return cappedResults
      .map((result) => ({
        ...result,
        _score: scoreByUrl.get(result.url) ?? result.score ?? 0,
      }))
      .sort((left, right) => right._score - left._score);
  }
}

export const reranker = new ResultReranker();
