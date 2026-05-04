import { describe, expect, it, vi } from 'vitest';

const mockSearchClient = {
  isAvailable: vi.fn(),
  search: vi.fn(),
};

const mockScraper = {
  scrapeUrls: vi.fn(),
};

const mockReranker = {
  rerank: vi.fn(),
};

const mockStore = {
  searchRetrievalDocuments: vi.fn(),
  searchRetrievalDocumentsHybrid: vi.fn(),
  ingestRetrievalText: vi.fn(),
};

vi.mock('@/core/search', () => ({
  searchClient: mockSearchClient,
  scraper: mockScraper,
  reranker: mockReranker,
}));

vi.mock('@/core/retrieval/vector-store', () => mockStore);

describe('selective web retrieval', () => {
  it('uses stored context first and ingests selective web results', async () => {
    mockSearchClient.isAvailable.mockResolvedValue(true);
    mockSearchClient.search.mockResolvedValue([
      {
        url: 'https://example.com/a',
        title: 'Result A',
        content: 'alpha content',
        engine: 'searx',
        category: 'general',
        score: 0.92,
      },
    ]);
    mockReranker.rerank.mockImplementation((_query, results) => results);
    mockScraper.scrapeUrls.mockResolvedValue([
      {
        url: 'https://example.com/a',
        title: 'Result A',
        content: 'alpha content',
        wordCount: 2,
        extractedAt: new Date('2026-04-30T00:00:00.000Z'),
      },
    ]);
    mockStore.searchRetrievalDocumentsHybrid.mockResolvedValue([
      {
        documentId: 'doc_1',
        accountId: null,
        sourceKind: 'bootstrap',
        sourceName: 'common_crawl',
        sourceUrl: 'https://bootstrap.example/doc',
        title: 'Bootstrap Doc',
        content: 'bootstrapped context',
        contentHash: 'hash-1',
        metadata: {},
        createdAt: '2026-04-30T00:00:00.000Z',
        updatedAt: '2026-04-30T00:00:00.000Z',
        similarity: 0.91,
        keywordScore: 0.8,
        combinedScore: 0.88,
      },
    ]);
    mockStore.ingestRetrievalText.mockResolvedValue({ documentId: 'doc_2' });

    const { runSelectiveWebRetrieval } = await import('@/core/retrieval');
    const result = await runSelectiveWebRetrieval({
      query: 'What changed in the latest search patterns?',
      plan: {
        routingMode: 'cloud_preferred',
        reasoningDepth: 'deep',
        taskIntent: 'research',
        executionPolicy: { shouldRetrieve: true },
        retrieval: {
          language: 'en',
          rounds: 1,
          maxUrls: 1,
          rerankTopK: 1,
          expandSearchQueries: false,
        },
      },
      searchEnabled: true,
    });

    expect(result.searchAvailable).toBe(true);
    expect(result.liveSearchUsed).toBe(true);
    expect(result.sources).toHaveLength(1);
    expect(result.contextBlocks.join('\n')).toContain('BOOTSTRAP Bootstrap Doc');
    expect(result.contextBlocks.join('\n')).toContain('WEB Result A');
    expect(mockStore.ingestRetrievalText).toHaveBeenCalledWith(
      expect.objectContaining({
        sourceKind: 'web',
        sourceName: 'searxng',
        sourceUrl: 'https://example.com/a',
      })
    );
  });
});
