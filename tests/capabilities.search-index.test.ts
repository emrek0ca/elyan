import { describe, expect, it } from 'vitest';
import { searchLocalDocuments } from '@/core/capabilities';

describe('Local search index', () => {
  it('rebuilds the same deterministic ranking for the same corpus', async () => {
    const documents = [
      {
        id: 'a',
        title: 'Operator Runtime',
        content: 'A local-first operator runtime for docs and tasks.',
        source: 'memory',
        tags: ['runtime', 'operator'],
      },
      {
        id: 'b',
        title: 'Spreadsheet Notes',
        content: 'Workbook parsing and export are available locally.',
        source: 'docs',
        tags: ['spreadsheet', 'docs'],
      },
      {
        id: 'c',
        title: 'Search Index',
        content: 'Deterministic local retrieval for project memory.',
        source: 'memory',
        tags: ['search', 'retrieval'],
      },
    ];

    const first = await searchLocalDocuments('local runtime', documents, 3);
    const second = await searchLocalDocuments('local runtime', documents, 3);

    expect(first.hits.map((hit) => hit.id)).toEqual(second.hits.map((hit) => hit.id));
    expect(first.indexedDocumentCount).toBe(3);
    expect(first.hits[0]?.document.id).toBe('a');
  });
});
