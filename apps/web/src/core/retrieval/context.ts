type ContextEntry = {
  text: string;
  score?: number;
  layer?: 'short_term' | 'episodic' | 'semantic' | 'web';
};

export type FilterContextOptions = {
  maxTokens?: number;
  maxBlocks?: number;
  minScore?: number;
};

function normalizeContextText(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function tokenEstimate(value: string) {
  return Math.max(1, normalizeContextText(value).split(/\s+/).filter(Boolean).length);
}

export function filterContextBlocks(blocks: Array<string | ContextEntry>, options?: FilterContextOptions) {
  const maxTokens = Math.max(200, options?.maxTokens ?? 2_000);
  const maxBlocks = Math.max(1, options?.maxBlocks ?? 8);
  const minScore = typeof options?.minScore === 'number' ? options.minScore : 0;
  const seen = new Set<string>();
  const filtered: string[] = [];
  let tokensUsed = 0;

  for (const block of blocks) {
    const entry = typeof block === 'string' ? { text: block } : block;
    const normalized = normalizeContextText(entry.text);
    if (!normalized) {
      continue;
    }

    if (typeof entry.score === 'number' && Number.isFinite(entry.score) && entry.score < minScore) {
      continue;
    }

    const signature = normalized.toLowerCase();
    if (seen.has(signature)) {
      continue;
    }

    const tokens = tokenEstimate(normalized);
    if (filtered.length >= maxBlocks || tokensUsed + tokens > maxTokens) {
      break;
    }

    seen.add(signature);
    filtered.push(normalized);
    tokensUsed += tokens;
  }

  return filtered;
}

export function buildContextLayerBlock(input: {
  title: string;
  entries: Array<{ label: string; summary: string; score?: number }>;
}) {
  if (input.entries.length === 0) {
    return '';
  }

  const body = input.entries
    .map((entry) => `- ${entry.label}: ${normalizeContextText(entry.summary)}`)
    .join('\n');

  return `${input.title}\n${body}`;
}

