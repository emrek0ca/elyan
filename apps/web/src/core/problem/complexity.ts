export type ProblemComplexityLevel = 'low' | 'medium' | 'high';

export type ProblemComplexityEstimate = {
  complexity: ProblemComplexityLevel;
  problemSize: number;
  estimated_space: number;
  searchSpaceSize: number;
  expectedDifficulty: number;
  signals: string[];
};

export type ProblemComplexityInput = {
  type?: string;
  nodes?: string[];
  locations?: string[];
  workers?: Array<{ id: string } | string | number>;
  tasks?: Array<{ id: string } | string | number>;
  resources?: Array<{ id: string } | string | number>;
  costMatrix?: number[][];
  cost_matrix?: number[][];
  costs?: Record<string, Record<string, number>>;
  constraints?: Array<unknown>;
  entities?: Array<unknown>;
  source?: Record<string, unknown>;
};

function clampToSafeInteger(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return 1;
  }

  return Math.min(Number.MAX_SAFE_INTEGER, Math.round(value));
}

function round2(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(2)) : 0;
}

function factorialEstimate(size: number) {
  if (size <= 1) {
    return 1;
  }

  let result = 1;
  for (let index = 2; index <= size; index += 1) {
    if (result > Number.MAX_SAFE_INTEGER / index) {
      return Number.MAX_SAFE_INTEGER;
    }

    result *= index;
  }

  return result;
}

function readCount<T>(value: T[] | undefined) {
  return Array.isArray(value) ? value.length : 0;
}

function normalizeType(value: string | undefined) {
  const normalized = (value ?? '').trim().toLowerCase();

  if (/\b(routing|route|graph|delivery|tsp|path)\b/.test(normalized)) {
    return 'routing' as const;
  }

  if (/\b(scheduling|schedule|shift|slot|calendar|job)\b/.test(normalized)) {
    return 'scheduling' as const;
  }

  if (/\b(allocation|allocate|resource|distribution|load)\b/.test(normalized)) {
    return 'allocation' as const;
  }

  return 'unknown' as const;
}

function resolveCounts(input: ProblemComplexityInput) {
  const routingCount = Math.max(readCount(input.nodes), readCount(input.locations));
  const schedulingCount = readCount(input.workers) + readCount(input.tasks);
  const allocationCount = readCount(input.resources) + readCount(input.locations);

  if (input.type === 'routing') {
    return routingCount;
  }

  if (input.type === 'scheduling') {
    return schedulingCount;
  }

  if (input.type === 'allocation') {
    return allocationCount;
  }

  return Math.max(routingCount, schedulingCount, allocationCount, readCount(input.entities));
}

function estimateRoutingSpace(input: ProblemComplexityInput, size: number) {
  const matrixSize = input.costMatrix?.length ?? input.cost_matrix?.length ?? 0;
  const completeMatrix = matrixSize >= size && size > 0;
  const routeSize = Math.max(1, size - 1);
  const space = factorialEstimate(routeSize);
  return completeMatrix ? space : Math.max(space, size * size || 1);
}

function estimateAssignmentSpace(size: number) {
  if (size <= 1) {
    return 1;
  }

  return factorialEstimate(size);
}

export function estimateProblemComplexity(input: ProblemComplexityInput): ProblemComplexityEstimate {
  const type = normalizeType(input.type);
  const problemSize = resolveCounts(input);
  const baseSignals = [
    `type=${type}`,
    `size=${problemSize}`,
    `constraints=${readCount(input.constraints)}`,
  ];

  let searchSpaceSize = 1;

  if (type === 'routing') {
    searchSpaceSize = estimateRoutingSpace(input, problemSize);
    baseSignals.push(`routing_entities=${Math.max(readCount(input.nodes), readCount(input.locations))}`);
  } else if (type === 'scheduling') {
    searchSpaceSize = estimateAssignmentSpace(problemSize);
    baseSignals.push(`workers=${readCount(input.workers)}`, `tasks=${readCount(input.tasks)}`);
  } else if (type === 'allocation') {
    searchSpaceSize = estimateAssignmentSpace(problemSize);
    baseSignals.push(`resources=${readCount(input.resources)}`, `locations=${readCount(input.locations)}`);
  } else {
    searchSpaceSize = Math.max(1, problemSize);
  }

  const safeSearchSpace = clampToSafeInteger(searchSpaceSize);
  const logScale = Math.log10(safeSearchSpace + 1);
  const complexity: ProblemComplexityLevel =
    problemSize <= 3 || safeSearchSpace < 1_000
      ? 'low'
      : problemSize <= 7 || safeSearchSpace < 1_000_000
        ? 'medium'
        : 'high';

  return {
    complexity,
    problemSize,
    estimated_space: safeSearchSpace,
    searchSpaceSize: safeSearchSpace,
    expectedDifficulty: round2(Math.min(1, logScale / 8)),
    signals: baseSignals,
  };
}
