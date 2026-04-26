import { create, insertMultiple, search } from '@orama/orama';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

class SearchIndexCapabilityError extends Error {
  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = 'SearchIndexCapabilityError';

    if (cause !== undefined) {
      (this as Error & { cause?: unknown }).cause = cause;
    }
  }
}

const searchIndexDocumentSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  content: z.string().default(''),
  source: z.string().default(''),
  tags: z.array(z.string()).default([]),
});

const searchIndexInputSchema = z.object({
  query: z.string().min(1),
  limit: z.number().int().min(1).max(50).default(10),
  documents: z.array(searchIndexDocumentSchema).min(1),
});

const searchIndexOutputSchema = z.object({
  indexedDocumentCount: z.number().int().nonnegative(),
  count: z.number().int().nonnegative(),
  hits: z.array(
    z.object({
      id: z.string(),
      score: z.number(),
      document: searchIndexDocumentSchema,
    })
  ),
});

type SearchIndexDocument = z.output<typeof searchIndexDocumentSchema>;

const localSearchSchema = {
  id: 'string',
  title: 'string',
  content: 'string',
  source: 'string',
  tags: 'string[]',
} as const;

export async function searchLocalDocuments(query: string, documents: SearchIndexDocument[], limit: number) {
  try {
    const db = create({
      schema: localSearchSchema,
    });

    await insertMultiple(db, documents);

    const result = await search(db, {
      term: query,
      limit,
    });

    const hits = result.hits
      .map((hit) => ({
        score: hit.score,
        document: hit.document as SearchIndexDocument,
      }))
      .sort((left, right) => {
        if (right.score !== left.score) {
          return right.score - left.score;
        }

        return (
          left.document.title.localeCompare(right.document.title) ||
          left.document.id.localeCompare(right.document.id)
        );
      })
      .map((hit) => ({
        id: hit.document.id,
        score: hit.score,
        document: hit.document,
      }));

    return {
      indexedDocumentCount: documents.length,
      count: result.count,
      hits,
    };
  } catch (error) {
    throw new SearchIndexCapabilityError('Unable to search local documents', error);
  }
}

export const searchIndexCapability: CapabilityDefinition<
  typeof searchIndexInputSchema,
  typeof searchIndexOutputSchema
> = {
  id: 'local_search_index',
  title: 'Local Search Index',
  description: 'Builds a local Orama index and searches documents with deterministic ranking.',
  library: '@orama/orama',
  enabled: true,
  timeoutMs: 1_000,
  inputSchema: searchIndexInputSchema,
  outputSchema: searchIndexOutputSchema,
  run: async (input: z.output<typeof searchIndexInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return searchLocalDocuments(input.query, input.documents, input.limit);
  },
};
