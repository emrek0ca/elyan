import { z } from 'zod';
import { extractCheerioText } from '../search/content-utils';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class CrawlCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'CrawlCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

type CrawledPage = z.output<typeof webCrawlOutputSchema>['pages'][number];
type CrawledError = z.output<typeof webCrawlOutputSchema>['errors'][number];

const webCrawlInputSchema = z.object({
  startUrls: z.array(z.string().url()).min(1).max(10),
  maxPages: z.number().int().min(1).max(50).default(10),
  maxDepth: z.number().int().min(0).max(4).default(1),
  sameDomainOnly: z.boolean().default(true),
});

const webCrawlOutputSchema = z.object({
  pages: z.array(
    z.object({
      url: z.string().url(),
      title: z.string(),
      text: z.string(),
      depth: z.number().int().nonnegative(),
    })
  ),
  errors: z.array(
    z.object({
      url: z.string(),
      message: z.string(),
    })
  ),
});

function compareStrings(left: string, right: string) {
  if (left < right) {
    return -1;
  }

  if (left > right) {
    return 1;
  }

  return 0;
}

function comparePages(left: CrawledPage, right: CrawledPage) {
  return (
    left.depth - right.depth ||
    compareStrings(left.url, right.url) ||
    compareStrings(left.title, right.title) ||
    compareStrings(left.text, right.text)
  );
}

function compareErrors(left: CrawledError, right: CrawledError) {
  return compareStrings(left.url, right.url) || compareStrings(left.message, right.message);
}

function dedupeByKey<T>(items: T[], keySelector: (item: T) => string): T[] {
  const seen = new Set<string>();
  const deduped: T[] = [];

  for (const item of items) {
    const key = keySelector(item);
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    deduped.push(item);
  }

  return deduped;
}

export async function crawlUrls(input: z.output<typeof webCrawlInputSchema>) {
  const pages: Array<z.output<typeof webCrawlOutputSchema>['pages'][number]> = [];
  const errors: Array<z.output<typeof webCrawlOutputSchema>['errors'][number]> = [];
  const { CheerioCrawler } = await import('@crawlee/cheerio');

  const crawler = new CheerioCrawler({
    maxRequestsPerCrawl: input.maxPages,
    async requestHandler({ $, request, enqueueLinks }) {
      const depth = Number(request.userData.depth ?? 0);
      const url = request.loadedUrl ?? request.url;
      const title = $('title').text().trim();
      const text = extractCheerioText($);

      pages.push({
        url,
        title,
        text,
        depth,
      });

      if (depth >= input.maxDepth) {
        return;
      }

      await enqueueLinks({
        selector: 'a[href]',
        strategy: input.sameDomainOnly ? 'same-domain' : 'all',
        transformRequestFunction: (request) => ({
          ...request,
          userData: {
            ...(request.userData ?? {}),
            depth: depth + 1,
          },
        }),
      });
    },
    failedRequestHandler({ request, error }) {
      errors.push({
        url: request.url,
        message: error instanceof Error ? error.message : 'crawl failed',
      });
    },
  });

  try {
    await crawler.run(
      input.startUrls.map((url) => ({
        url,
        userData: { depth: 0 },
      }))
    );
  } catch (error) {
    const label = input.startUrls.length === 1 ? input.startUrls[0] : `${input.startUrls.length} start URLs`;
    throw new CrawlCapabilityError(`Unable to crawl ${label}`, error);
  }

  const dedupedPages = dedupeByKey([...pages].sort(comparePages), (page) => page.url);
  const dedupedErrors = dedupeByKey([...errors].sort(compareErrors), (error) => `${error.url}\u0000${error.message}`);

  return {
    pages: dedupedPages,
    errors: dedupedErrors,
  };
}

export const webCrawlCapability: CapabilityDefinition<
  typeof webCrawlInputSchema,
  typeof webCrawlOutputSchema
> = {
  id: 'web_crawl',
  title: 'Web Crawl',
  description: 'Crawls same-domain pages with Crawlee and extracts readable HTML content.',
  library: 'crawlee',
  enabled: true,
  timeoutMs: 12_500,
  inputSchema: webCrawlInputSchema,
  outputSchema: webCrawlOutputSchema,
  run: async (input: z.output<typeof webCrawlInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return crawlUrls(input);
  },
};
