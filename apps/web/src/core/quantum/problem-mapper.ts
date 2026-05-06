import { classifyProblem, type ProblemClassification } from '@/core/problem/classifier';
import { buildStructuredProblemModel, type StructuredProblemModel } from '@/core/problem/objective-engine';

export type QuantumProblemType = 'graph' | 'scheduling' | 'allocation' | 'assignment';

export type QuantumEntity = {
  id: string;
  title?: string;
  capacity?: number;
  need?: number;
  priority?: number;
  requiredSkill?: string;
  skills?: string[];
};

export type QuantumEngineProblem = {
  problemType: 'assignment' | 'resource_allocation';
  title?: string;
  workers?: QuantumEntity[];
  tasks?: QuantumEntity[];
  resources?: QuantumEntity[];
  locations?: QuantumEntity[];
  costs: Record<string, Record<string, number>>;
};

export type QuantumGraphProblem = {
  problemType: 'graph';
  title?: string;
  nodes: string[];
  costMatrix: number[][];
  start?: string;
};

export type QuantumMappedProblem = QuantumEngineProblem | QuantumGraphProblem;

export type QuantumQuboLike = {
  variables: Array<{
    id: string;
    leftId: string;
    rightId: string;
  }>;
  linear: Record<string, number>;
  quadratic: Record<string, number>;
  offset: number;
  penalty: number;
};

export type QuantumProblemMapping =
  | {
      status: 'ready';
      type: QuantumProblemType;
      structuredModel: StructuredProblemModel;
      problem: QuantumMappedProblem;
      qubo: QuantumQuboLike;
      source: 'structured_json' | 'typed_problem';
      notes: string[];
      missing: [];
    }
  | {
      status: 'needs_input';
      type: QuantumProblemType;
      source: 'structured_json' | 'unstructured_text' | 'invalid_json' | 'typed_problem';
      missing: string[];
      notes: string[];
      classification?: ProblemClassification;
    };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function normalizeId(value: unknown, fallback: string) {
  const raw = typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
  const normalized = normalizeText(raw)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');

  return normalized || fallback;
}

function toFiniteNumber(value: unknown) {
  const parsed = typeof value === 'string' ? Number(value) : typeof value === 'number' ? value : Number.NaN;
  return Number.isFinite(parsed) ? parsed : undefined;
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
  if (typeof input === 'string') {
    const trimmed = input.trim();
    if (trimmed.startsWith('{')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (isRecord(parsed)) {
          return {
            source: 'structured_json' as const,
            value: parsed,
          };
        }
      } catch {
        return {
          source: 'invalid_json' as const,
          value: undefined,
        };
      }
    }

    return {
      source: 'structured_json' as const,
      value: parseEmbeddedJsonObject(input),
    };
  }

  return {
    source: 'typed_problem' as const,
    value: input,
  };
}

function normalizeEntityList(value: unknown, fallbackPrefix: string): QuantumEntity[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((entry, index): QuantumEntity | undefined => {
      if (typeof entry === 'string' || typeof entry === 'number') {
        const id = normalizeId(entry, `${fallbackPrefix}-${index + 1}`);
        return {
          id,
          title: String(entry),
        };
      }

      if (!isRecord(entry)) {
        return undefined;
      }

      const id = normalizeId(entry.id ?? entry.name ?? entry.title, `${fallbackPrefix}-${index + 1}`);
      const capacity = toFiniteNumber(entry.capacity);
      const need = toFiniteNumber(entry.need);
      const priority = toFiniteNumber(entry.priority);
      const skills = Array.isArray(entry.skills)
        ? entry.skills.filter((skill): skill is string => typeof skill === 'string' && skill.trim().length > 0)
        : undefined;

      return {
        id,
        title: typeof entry.title === 'string' ? entry.title : typeof entry.name === 'string' ? entry.name : id,
        capacity,
        need,
        priority,
        requiredSkill: typeof entry.requiredSkill === 'string' ? entry.requiredSkill : undefined,
        skills,
      };
    })
    .filter((entry): entry is QuantumEntity => Boolean(entry));
}

function normalizeCostObject(
  value: unknown,
  leftIds: string[],
  rightIds: string[]
): Record<string, Record<string, number>> {
  if (!isRecord(value)) {
    return {};
  }

  const costs: Record<string, Record<string, number>> = {};

  for (const leftId of leftIds) {
    const row = value[leftId];
    if (!isRecord(row)) {
      continue;
    }

    for (const rightId of rightIds) {
      const cost = toFiniteNumber(row[rightId]);
      if (cost !== undefined) {
        costs[leftId] = {
          ...(costs[leftId] ?? {}),
          [rightId]: cost,
        };
      }
    }
  }

  return costs;
}

function normalizeCostMatrix(
  value: unknown,
  leftIds: string[],
  rightIds: string[]
): Record<string, Record<string, number>> {
  if (!Array.isArray(value)) {
    return {};
  }

  const costs: Record<string, Record<string, number>> = {};

  for (let leftIndex = 0; leftIndex < leftIds.length; leftIndex += 1) {
    const row = value[leftIndex];
    if (!Array.isArray(row)) {
      continue;
    }

    for (let rightIndex = 0; rightIndex < rightIds.length; rightIndex += 1) {
      const cost = toFiniteNumber(row[rightIndex]);
      if (cost !== undefined) {
        const leftId = leftIds[leftIndex];
        const rightId = rightIds[rightIndex];
        costs[leftId] = {
          ...(costs[leftId] ?? {}),
          [rightId]: cost,
        };
      }
    }
  }

  return costs;
}

function hasCompleteCosts(costs: Record<string, Record<string, number>>, leftIds: string[], rightIds: string[]) {
  return leftIds.every((leftId) =>
    rightIds.every((rightId) => Number.isFinite(costs[leftId]?.[rightId]))
  );
}

function mergeCosts(
  problem: Record<string, unknown>,
  leftIds: string[],
  rightIds: string[]
) {
  const objectCosts = normalizeCostObject(problem.costs, leftIds, rightIds);
  if (hasCompleteCosts(objectCosts, leftIds, rightIds)) {
    return objectCosts;
  }

  const matrixCosts = normalizeCostMatrix(problem.costMatrix ?? problem.cost_matrix, leftIds, rightIds);
  return {
    ...objectCosts,
    ...Object.fromEntries(
      Object.entries(matrixCosts).map(([leftId, row]) => [
        leftId,
        {
          ...(objectCosts[leftId] ?? {}),
          ...row,
        },
      ])
    ),
  };
}

function inferTypeFromText(value: string): QuantumProblemType {
  const normalized = value.toLowerCase();
  if (/\b(route|routing|graph|node|edge|tsp|traveling|delivery|rota)\b/i.test(normalized)) {
    return 'graph';
  }

  if (/\b(schedule|scheduling|calendar|slot|shift|vardiya|planla)\b/i.test(normalized)) {
    return 'scheduling';
  }

  if (/\b(resource|allocation|allocate|distribution|load balancing|capacity|kaynak|dağıt)\b/i.test(normalized)) {
    return 'allocation';
  }

  return 'assignment';
}

function inferType(problem: Record<string, unknown>, originalInput: string | Record<string, unknown>): QuantumProblemType {
  const typeHint = typeof problem.type === 'string'
    ? problem.type
    : typeof problem.problemType === 'string'
      ? problem.problemType
      : typeof originalInput === 'string'
        ? originalInput
        : '';

  const normalized = typeHint.toLowerCase();
  if (/\b(graph|route|routing|tsp|delivery)\b/.test(normalized)) {
    return 'graph';
  }
  if (/\b(scheduling|schedule|slot|shift)\b/.test(normalized)) {
    return 'scheduling';
  }
  if (/\b(resource|allocation|distribution|load)\b/.test(normalized)) {
    return 'allocation';
  }
  if (/\b(assignment|assign)\b/.test(normalized)) {
    return 'assignment';
  }

  if (Array.isArray(problem.nodes) || Array.isArray(problem.edges)) {
    return 'graph';
  }
  if (Array.isArray(problem.resources) || Array.isArray(problem.locations)) {
    return 'allocation';
  }
  if (Array.isArray(problem.slots) || Array.isArray(problem.shifts)) {
    return 'scheduling';
  }

  return 'assignment';
}

function buildEngineQubo(problem: QuantumEngineProblem): QuantumQuboLike {
  const left = problem.problemType === 'resource_allocation' ? problem.resources ?? [] : problem.workers ?? [];
  const right = problem.problemType === 'resource_allocation' ? problem.locations ?? [] : problem.tasks ?? [];
  const variables = left.flatMap((leftItem) =>
    right.map((rightItem) => ({
      id: `x_${leftItem.id}__${rightItem.id}`.replace(/[^a-zA-Z0-9_]/g, '_'),
      leftId: leftItem.id,
      rightId: rightItem.id,
    }))
  );

  return {
    variables,
    linear: Object.fromEntries(
      variables.map((variable) => [
        variable.id,
        problem.costs[variable.leftId]?.[variable.rightId] ?? 999,
      ])
    ),
    quadratic: {},
    offset: 0,
    penalty: 25,
  };
}

function buildGraphQubo(problem: QuantumGraphProblem): QuantumQuboLike {
  const variables = problem.nodes.flatMap((leftId, leftIndex) =>
    problem.nodes
      .filter((_, rightIndex) => rightIndex !== leftIndex)
      .map((rightId) => ({
        id: `edge_${leftId}__${rightId}`.replace(/[^a-zA-Z0-9_]/g, '_'),
        leftId,
        rightId,
      }))
  );

  return {
    variables,
    linear: Object.fromEntries(
      variables.map((variable) => {
        const leftIndex = problem.nodes.indexOf(variable.leftId);
        const rightIndex = problem.nodes.indexOf(variable.rightId);
        return [variable.id, problem.costMatrix[leftIndex]?.[rightIndex] ?? 999];
      })
    ),
    quadratic: {},
    offset: 0,
    penalty: 25,
  };
}

function mapGraphProblem(
  problem: Record<string, unknown>,
  source: 'structured_json' | 'typed_problem'
): QuantumProblemMapping {
  const classification = classifyProblem(problem);
  const nodes = normalizeEntityList(problem.nodes, 'node').map((node) => node.id);
  const rawMatrix = problem.costMatrix ?? problem.cost_matrix;
  const costMatrix = Array.isArray(rawMatrix)
    ? rawMatrix.map((row) => (Array.isArray(row) ? row.map((entry) => toFiniteNumber(entry) ?? Number.NaN) : []))
    : [];
  const missing: string[] = [];

  if (nodes.length < 2) {
    missing.push('nodes');
  }

  const matrixReady =
    costMatrix.length === nodes.length &&
    costMatrix.every((row) => row.length === nodes.length && row.every((entry) => Number.isFinite(entry)));

  if (!matrixReady) {
    missing.push('costMatrix');
  }

  if (missing.length > 0) {
    return {
      status: 'needs_input',
      type: 'graph',
      source,
      missing,
      notes: ['Graph optimization requires explicit nodes and a complete numeric costMatrix.'],
      classification,
    };
  }

  const structured = buildStructuredProblemModel({
    classification,
    graph: {
      nodes,
      costMatrix,
    },
    source: problem,
  });

  if (structured.status === 'needs_input') {
    return {
      status: 'needs_input',
      type: 'graph',
      source,
      missing: structured.missing,
      notes: ['Problem intelligence could not build a complete routing model.'],
      classification,
    };
  }

  const mapped: QuantumGraphProblem = {
    problemType: 'graph',
    title: typeof problem.title === 'string' ? problem.title : 'Graph route optimization',
    nodes,
    costMatrix,
    start: typeof problem.start === 'string' ? normalizeId(problem.start, nodes[0] ?? 'node-1') : nodes[0],
  };

  return {
    status: 'ready',
    type: 'graph',
    structuredModel: structured.model,
    problem: mapped,
    qubo: buildGraphQubo(mapped),
    source,
    notes: ['Mapped graph route problem into a deterministic route-cost model.'],
    missing: [],
  };
}

function mapAssignmentLikeProblem(
  problem: Record<string, unknown>,
  type: QuantumProblemType,
  source: 'structured_json' | 'typed_problem'
): QuantumProblemMapping {
  const classification = classifyProblem(problem);
  const isAllocation = type === 'allocation';
  const left = isAllocation
    ? normalizeEntityList(problem.resources, 'resource')
    : normalizeEntityList(problem.workers ?? problem.resources ?? problem.slots ?? problem.shifts, 'worker');
  const right = isAllocation
    ? normalizeEntityList(problem.locations ?? problem.tasks, 'location')
    : normalizeEntityList(problem.tasks ?? problem.jobs ?? problem.locations, 'task');
  const leftIds = left.map((entry) => entry.id);
  const rightIds = right.map((entry) => entry.id);
  const costs = mergeCosts(problem, leftIds, rightIds);
  const missing: string[] = [];

  if (left.length === 0) {
    missing.push(isAllocation ? 'resources' : type === 'scheduling' ? 'workers or slots' : 'workers');
  }

  if (right.length === 0) {
    missing.push(isAllocation ? 'locations' : 'tasks');
  }

  if (!hasCompleteCosts(costs, leftIds, rightIds)) {
    missing.push('costs');
  }

  if (missing.length > 0) {
    return {
      status: 'needs_input',
      type,
      source,
      missing,
      notes: [`${type} optimization requires explicit entities and complete numeric costs.`],
      classification,
    };
  }

  const structured = buildStructuredProblemModel({
    classification,
    assignment: isAllocation
      ? undefined
      : {
          workers: left,
          tasks: right,
          costs,
        },
    allocation: isAllocation
      ? {
          resources: left,
          locations: right,
          costs,
        }
      : undefined,
    source: problem,
  });

  if (structured.status === 'needs_input') {
    return {
      status: 'needs_input',
      type,
      source,
      missing: structured.missing,
      notes: ['Problem intelligence could not build a complete structured model.'],
      classification,
    };
  }

  const mapped: QuantumEngineProblem = isAllocation
    ? {
        problemType: 'resource_allocation',
        title: typeof problem.title === 'string' ? problem.title : 'Resource allocation optimization',
        resources: left.map((entry) => ({ ...entry, capacity: entry.capacity ?? 1 })),
        locations: right.map((entry) => ({ ...entry, need: entry.need ?? 1, priority: entry.priority ?? 1 })),
        costs,
      }
    : {
        problemType: 'assignment',
        title: typeof problem.title === 'string' ? problem.title : type === 'scheduling' ? 'Scheduling optimization' : 'Assignment optimization',
        workers: left.map((entry) => ({ ...entry, capacity: entry.capacity ?? 1 })),
        tasks: right,
        costs,
      };

  return {
    status: 'ready',
    type,
    structuredModel: structured.model,
    problem: mapped,
    qubo: buildEngineQubo(mapped),
    source,
    notes: [`Mapped ${type} problem into the existing QUBO-compatible optimization model.`],
    missing: [],
  };
}

export function mapProblem(input: string | Record<string, unknown>): QuantumProblemMapping {
  const parsed = readProblemObject(input);

  if (!parsed.value) {
    const type = typeof input === 'string' ? inferTypeFromText(input) : 'assignment';
    return {
      status: 'needs_input',
      type,
      source: parsed.source === 'invalid_json' ? 'invalid_json' : 'unstructured_text',
      missing:
        type === 'graph'
          ? ['nodes', 'costMatrix']
          : type === 'allocation'
            ? ['resources', 'locations', 'costs']
            : ['workers', 'tasks', 'costs'],
      notes: ['No structured optimization problem was found. Provide JSON with entities and numeric costs.'],
      classification: classifyProblem(input),
    };
  }

  const type = inferType(parsed.value, input);
  const structuredSource = parsed.source === 'typed_problem' ? 'typed_problem' : 'structured_json';

  if (type === 'graph') {
    return mapGraphProblem(parsed.value, structuredSource);
  }

  return mapAssignmentLikeProblem(parsed.value, type, structuredSource);
}
