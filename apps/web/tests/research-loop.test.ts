import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockFetchConnectorBundle = vi.fn();
const mockListConnectorRegistry = vi.fn();
const mockRecordOperatorRunArtifact = vi.fn();

vi.mock('@/core/connectors/registry', () => ({
  fetchConnectorBundle: mockFetchConnectorBundle,
  listConnectorRegistry: mockListConnectorRegistry,
}));

vi.mock('@/core/operator/runs', () => ({
  recordOperatorRunArtifact: mockRecordOperatorRunArtifact,
}));

describe('research loop', () => {
  beforeEach(() => {
    mockFetchConnectorBundle.mockReset();
    mockListConnectorRegistry.mockReset();
    mockRecordOperatorRunArtifact.mockReset();
    mockFetchConnectorBundle.mockResolvedValue([
      {
        connectorId: 'stored_contexts',
        contextBlocks: ['bootstrap note', 'bootstrap note'],
        sources: [],
        storedContexts: [
          {
            documentId: 'doc_1',
            accountId: 'acct_1',
            spaceId: 'acct_1',
            sourceKind: 'learning',
            sourceName: 'learning_signal',
            content: 'Use evidence first.',
            contentHash: 'hash_1',
            metadata: {},
            createdAt: '2026-05-01T00:00:00.000Z',
            updatedAt: '2026-05-01T00:00:00.000Z',
          },
        ],
      },
      {
        connectorId: 'learning_hints',
        contextBlocks: ['[learning:routing] prefer retrieval-first'],
        sources: [],
        storedContexts: [],
      },
      {
        connectorId: 'web_evidence',
        contextBlocks: ['WEB Result A'],
        sources: [{ url: 'https://example.com/a', title: 'Result A', content: 'alpha' }],
        storedContexts: [],
        searchAvailable: true,
        liveSearchUsed: true,
      },
    ]);
    mockListConnectorRegistry.mockReturnValue([
      { id: 'stored_contexts', title: 'Stored retrieval context', layer: 'retrieval' },
      { id: 'learning_hints', title: 'Learning hints', layer: 'learning' },
      { id: 'web_evidence', title: 'Live web evidence', layer: 'web' },
    ]);
    mockRecordOperatorRunArtifact.mockResolvedValue(undefined);
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
  });

  it('combines connector data across iterations and records research artifacts', async () => {
    const { runResearchLoop } = await import('@/core/retrieval/research-loop');

    const result = await runResearchLoop({
      query: 'Why did the latest answer improve?',
      accountId: 'acct_1',
      spaceId: 'acct_1',
      plan: {
        routingMode: 'cloud_preferred',
        reasoningDepth: 'deep',
        taskIntent: 'research',
        executionPolicy: { shouldRetrieve: true },
        retrieval: {
          language: 'en',
          rounds: 2,
          maxUrls: 2,
          rerankTopK: 2,
          expandSearchQueries: true,
        },
      } as never,
      searchEnabled: true,
      operatorRunId: 'run_1',
    });

    expect(mockFetchConnectorBundle).toHaveBeenCalled();
    expect(mockRecordOperatorRunArtifact).toHaveBeenCalled();
    expect(result.searchAvailable).toBe(true);
    expect(result.liveSearchUsed).toBe(true);
    expect(result.sources).toHaveLength(1);
    expect(result.contextBlocks.join('\n')).toContain('WEB Result A');
    expect(result.contextBlocks.join('\n')).toContain('learning:routing');
  });
});
