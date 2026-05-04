import Fuse from 'fuse.js';
import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';

export type FuzzyItem = {
  id: string;
  title: string;
  content?: string;
  url?: string;
  tags: string[];
  metadata: Record<string, unknown>;
};

const fuzzyItemSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  content: z.string().optional(),
  url: z.string().url().optional(),
  tags: z.array(z.string()).default([]),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

const fuzzyFindInputSchema = z.object({
  query: z.string().min(1),
  items: z.array(fuzzyItemSchema).min(1),
  limit: z.number().int().min(1).max(50).default(10),
  threshold: z.number().min(0).max(1).default(0.35),
});

const fuzzyFindOutputSchema = z.object({
  matches: z.array(
    z.object({
      item: fuzzyItemSchema,
      score: z.number().min(0).max(1),
    })
  ),
});

function authorityScore(url?: string): number {
  if (!url) {
    return 0.4;
  }

  try {
    const host = new URL(url).hostname.toLowerCase();
    if (host.includes('wikipedia.org')) return 1;
    if (host.includes('github.com')) return 0.9;
    if (host.endsWith('.edu') || host.endsWith('.gov')) return 0.9;
    if (host.includes('medium.com')) return 0.6;
    return 0.5;
  } catch {
    return 0.4;
  }
}

function freshnessScore(metadata?: Record<string, unknown>): number {
  const published = metadata?.publishedAt;
  if (typeof published !== 'string') {
    return 0.5;
  }

  const publishedAt = Date.parse(published);
  if (Number.isNaN(publishedAt)) {
    return 0.5;
  }

  const ageInDays = (Date.now() - publishedAt) / (1000 * 60 * 60 * 24);
  return Math.max(0, Math.min(1, (30 - ageInDays) / 30));
}

export function rankFuzzyItems(query: string, items: FuzzyItem[], limit = 10, threshold = 0.35) {
  const fuse = new Fuse(items, {
    includeScore: true,
    ignoreLocation: true,
    threshold,
    keys: [
      { name: 'title', weight: 0.6 },
      { name: 'content', weight: 0.25 },
      { name: 'url', weight: 0.1 },
      { name: 'tags', weight: 0.05 },
    ],
  });

  const ranked = fuse.search(query).map((match) => {
    const item = match.item;
    const fuseScore = match.score ?? 1;
    const relevance = 1 - fuseScore;
    const score =
      relevance * 0.65 +
      authorityScore(item.url) * 0.2 +
      freshnessScore(item.metadata) * 0.15;

    return {
      item,
      score,
    };
  });

  return ranked.sort((left, right) => right.score - left.score).slice(0, limit);
}

export const fuzzyFindCapability: CapabilityDefinition<
  typeof fuzzyFindInputSchema,
  typeof fuzzyFindOutputSchema
> = {
  id: 'fuzzy_find',
  title: 'Fuzzy Find',
  description: 'Ranks local items with typo-tolerant matching.',
  library: 'fuse.js',
  enabled: true,
  timeoutMs: 250,
  inputSchema: fuzzyFindInputSchema,
  outputSchema: fuzzyFindOutputSchema,
  run: async (input: z.output<typeof fuzzyFindInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return {
      matches: rankFuzzyItems(input.query, input.items, input.limit, input.threshold),
    };
  },
};
