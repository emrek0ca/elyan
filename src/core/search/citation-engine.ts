import { ScrapedContent } from '@/types/search';

export class CitationEngine {
  /**
   * Build citation context for the LLM prompt.
   * Each source gets a numbered reference the LLM can cite.
   */
  buildContext(sources: ScrapedContent[]): string {
    if (sources.length === 0) {
      return 'No reliable sources were retrieved. State that clearly and do not invent citations.';
    }

    return sources
      .map((source, i) => {
        const truncated =
          source.content.length > 2000
            ? source.content.slice(0, 2000) + '...'
            : source.content;
        return `[Source ${i + 1}] ${source.title}\nURL: ${source.url}\nContent: ${truncated}\n`;
      })
      .join('\n---\n');
  }
}

export const citationEngine = new CitationEngine();
