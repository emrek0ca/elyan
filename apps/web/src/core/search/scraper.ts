import * as cheerio from 'cheerio';
import { ScrapedContent } from '@/types/search';
import { extractCheerioText } from './content-utils';

export class WebScraper {
  async scrapeUrls(urls: string[], limit: number = 5, signal?: AbortSignal): Promise<ScrapedContent[]> {
    const results = await Promise.allSettled(
      urls.slice(0, limit).map((url) => this.scrapeUrl(url, signal))
    );
    return results
      .filter((r): r is PromiseFulfilledResult<ScrapedContent> => r.status === 'fulfilled')
      .map(r => r.value);
  }

  private async scrapeUrl(url: string, signal?: AbortSignal): Promise<ScrapedContent> {
    let response: Response;

    try {
      response = await fetch(url, {
        headers: { 'User-Agent': 'Elyan/1.0 (Research Assistant)' },
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(10_000)]) : AbortSignal.timeout(10_000),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'unknown network failure';
      throw new Error(`Unable to fetch ${url}: ${message}`);
    }

    if (!response.ok) {
      throw new Error(`Unable to fetch ${url}: HTTP ${response.status}`);
    }

    const html = await response.text();
    const $ = cheerio.load(html);
    const cleanContent = extractCheerioText($);

    return {
      url,
      title: $('title').text().trim(),
      content: cleanContent,
      wordCount: cleanContent.split(/\s+/).length,
      extractedAt: new Date(),
    };
  }
}

export const scraper = new WebScraper();
