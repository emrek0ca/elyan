export type ProblemClass = 'routing' | 'scheduling' | 'allocation' | 'graph' | 'unknown';

export type ProblemClassification = {
  type: ProblemClass;
  confidence: number;
  evidence: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, ' ').trim().toLowerCase();
}

function parseEmbeddedJsonObject(input: string) {
  const start = input.indexOf('{');
  if (start < 0) {
    return undefined;
  }

  let depth = 0;

  for (let index = start; index < input.length; index += 1) {
    const char = input[index];
    if (char === '{') {
      depth += 1;
    } else if (char === '}') {
      depth -= 1;

      if (depth === 0) {
        try {
          const parsed = JSON.parse(input.slice(start, index + 1));
          return isRecord(parsed) ? parsed : undefined;
        } catch {
          return undefined;
        }
      }
    }
  }

  return undefined;
}

function readProblemObject(input: string | Record<string, unknown>) {
  return typeof input === 'string' ? parseEmbeddedJsonObject(input) : input;
}

function scoreKeywordEvidence(text: string, patterns: Array<[ProblemClass, RegExp, string]>) {
  const scores = new Map<ProblemClass, { score: number; evidence: string[] }>();

  for (const [type, pattern, evidence] of patterns) {
    if (!pattern.test(text)) {
      continue;
    }

    const current = scores.get(type) ?? { score: 0, evidence: [] };
    current.score += 1;
    current.evidence.push(evidence);
    scores.set(type, current);
  }

  return scores;
}

function classifyFromStructure(problem: Record<string, unknown>) {
  const typeHint = typeof problem.type === 'string'
    ? problem.type
    : typeof problem.problemType === 'string'
      ? problem.problemType
      : '';
  const normalizedHint = normalizeText(typeHint);
  const evidence: string[] = [];

  if (/\b(route|routing|tsp|delivery)\b/.test(normalizedHint)) {
    evidence.push('type hint indicates routing');
    return { type: 'routing' as const, confidence: 0.95, evidence };
  }

  if (/\b(graph)\b/.test(normalizedHint)) {
    evidence.push('type hint indicates graph');
    return { type: 'graph' as const, confidence: 0.9, evidence };
  }

  if (/\b(schedule|scheduling|shift|slot)\b/.test(normalizedHint)) {
    evidence.push('type hint indicates scheduling');
    return { type: 'scheduling' as const, confidence: 0.95, evidence };
  }

  if (/\b(allocation|resource|distribution|load)\b/.test(normalizedHint)) {
    evidence.push('type hint indicates allocation');
    return { type: 'allocation' as const, confidence: 0.95, evidence };
  }

  if (Array.isArray(problem.nodes) && (Array.isArray(problem.costMatrix) || Array.isArray(problem.cost_matrix))) {
    evidence.push('nodes plus cost matrix indicate routing or graph optimization');
    return { type: 'routing' as const, confidence: 0.9, evidence };
  }

  if (Array.isArray(problem.resources) || Array.isArray(problem.locations)) {
    evidence.push('resources or locations indicate allocation');
    return { type: 'allocation' as const, confidence: 0.85, evidence };
  }

  if (Array.isArray(problem.slots) || Array.isArray(problem.shifts)) {
    evidence.push('slots or shifts indicate scheduling');
    return { type: 'scheduling' as const, confidence: 0.85, evidence };
  }

  if (Array.isArray(problem.workers) && Array.isArray(problem.tasks)) {
    evidence.push('workers plus tasks indicate scheduling/assignment');
    return { type: 'scheduling' as const, confidence: 0.75, evidence };
  }

  return undefined;
}

export function classifyProblem(input: string | Record<string, unknown>): ProblemClassification {
  const problem = readProblemObject(input);
  const structured = problem ? classifyFromStructure(problem) : undefined;
  if (structured) {
    return structured;
  }

  const text = normalizeText(typeof input === 'string' ? input : JSON.stringify(input));
  const scores = scoreKeywordEvidence(text, [
    ['routing', /\b(route|routing|delivery|delivery route|delivery optimization|best route|traveling salesman|tsp|rota|teslimat rotası)\b/i, 'routing keyword'],
    ['graph', /\b(graph|node|edge|shortest path|min cut|max flow|graf|düğüm|kenar)\b/i, 'graph keyword'],
    ['scheduling', /\b(schedule|scheduling|shift|slot|calendar|job shop|vardiya|zamanla|planla)\b/i, 'scheduling keyword'],
    ['allocation', /\b(resource allocation|allocate|allocation|distribution|load balancing|capacity planning|kaynak tahsisi|dağıtım|yük dengele)\b/i, 'allocation keyword'],
  ]);

  const ranked = [...scores.entries()].sort((left, right) => right[1].score - left[1].score || left[0].localeCompare(right[0]));
  const [topType, topScore] = ranked[0] ?? [];
  if (!topType || !topScore) {
    return {
      type: 'unknown',
      confidence: 0,
      evidence: [],
    };
  }

  return {
    type: topType,
    confidence: Math.min(0.8, 0.45 + topScore.score * 0.2),
    evidence: topScore.evidence,
  };
}
