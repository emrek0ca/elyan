import { classifyProblem, type ProblemClassification } from './classifier';
import {
  buildStructuredProblemModel,
  describeObjectiveFunction,
  type StructuredProblemModel,
} from './objective-engine';
import { estimateProblemComplexity, type ProblemComplexityEstimate } from './complexity';

export type RefinedProblemType = 'routing' | 'scheduling' | 'allocation' | 'unknown';

export type RefinedProblemReady = {
  ok: true;
  status: 'ready';
  type: Exclude<RefinedProblemType, 'unknown'>;
  needs_input: false;
  required: string[];
  missing: [];
  classification: ProblemClassification;
  normalizedProblem: Record<string, unknown>;
  structuredModel: StructuredProblemModel;
  complexity: ProblemComplexityEstimate;
  objectiveSummary: string;
  summary: string;
};

export type RefinedProblemNeedsInput = {
  ok: false;
  status: 'needs_input';
  code: 'missing_input';
  type: RefinedProblemType;
  needs_input: true;
  required: string[];
  missing: string[];
  classification: ProblemClassification;
  complexity: ProblemComplexityEstimate;
  summary: string;
  partial?: Record<string, unknown>;
};

export type RefinedProblemResult = RefinedProblemReady | RefinedProblemNeedsInput;

type ProblemObject = Record<string, unknown>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function toFiniteNumber(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  return undefined;
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

function readProblemObject(input: string | ProblemObject) {
  if (typeof input !== 'string') {
    return input;
  }

  const trimmed = input.trim();
  if (trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed);
      return isRecord(parsed) ? parsed : undefined;
    } catch {
      return undefined;
    }
  }

  return parseEmbeddedJsonObject(input);
}

function readStringList(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((entry, index) => {
      if (typeof entry === 'string' || typeof entry === 'number') {
        return normalizeText(String(entry));
      }

      if (isRecord(entry)) {
        const candidate = entry.id ?? entry.name ?? entry.title ?? entry.label ?? `item-${index + 1}`;
        return normalizeText(String(candidate));
      }

      return '';
    })
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
}

function readNumberMatrix(value: unknown) {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.map((row) =>
    Array.isArray(row)
      ? row.map((entry) => {
          const parsed = toFiniteNumber(entry);
          return parsed ?? Number.NaN;
        })
      : []
  );
}

function matrixComplete(matrix: number[][], size: number) {
  return matrix.length === size && matrix.every((row) => row.length === size && row.every((entry) => Number.isFinite(entry)));
}

function costObjectComplete(costs: Record<string, Record<string, number>>, leftIds: string[], rightIds: string[]) {
  return leftIds.every((leftId) => rightIds.every((rightId) => Number.isFinite(costs[leftId]?.[rightId])));
}

function matrixToCosts(matrix: number[][], leftIds: string[], rightIds: string[]) {
  const costs: Record<string, Record<string, number>> = {};

  for (let leftIndex = 0; leftIndex < leftIds.length; leftIndex += 1) {
    for (let rightIndex = 0; rightIndex < rightIds.length; rightIndex += 1) {
      const row = matrix[leftIndex];
      const cost = row?.[rightIndex];
      if (Number.isFinite(cost)) {
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

function normalizeCostObject(value: unknown, leftIds: string[], rightIds: string[]) {
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

function requiredFieldsForType(type: Exclude<RefinedProblemType, 'unknown'>) {
  if (type === 'routing') {
    return ['locations', 'cost_matrix'];
  }

  if (type === 'allocation') {
    return ['resources', 'locations', 'costs'];
  }

  return ['workers', 'tasks', 'costs'];
}

function inferProblemType(classification: ProblemClassification, problem: ProblemObject | undefined): RefinedProblemType {
  if (classification.type === 'routing' || classification.type === 'graph') {
    return 'routing';
  }

  if (classification.type === 'allocation') {
    return 'allocation';
  }

  if (classification.type === 'scheduling') {
    return 'scheduling';
  }

  if (!problem) {
    return 'unknown';
  }

  if (Array.isArray(problem.nodes) || Array.isArray(problem.locations) || Array.isArray(problem.costMatrix) || Array.isArray(problem.cost_matrix)) {
    return 'routing';
  }

  if (Array.isArray(problem.resources) || Array.isArray(problem.locations)) {
    return 'allocation';
  }

  if (Array.isArray(problem.workers) || Array.isArray(problem.tasks) || Array.isArray(problem.jobs) || Array.isArray(problem.slots) || Array.isArray(problem.shifts)) {
    return 'scheduling';
  }

  return 'unknown';
}

function normalizeClassificationForType(type: RefinedProblemType, classification: ProblemClassification): ProblemClassification {
  if (type === 'unknown') {
    return classification;
  }

  const classificationType =
    type === 'routing'
      ? 'routing'
      : type === 'allocation'
        ? 'allocation'
        : 'scheduling';

  return {
    ...classification,
    type: classificationType,
    confidence: Math.max(classification.confidence, 0.75),
    evidence: classification.evidence.length > 0 ? classification.evidence : [`refined ${classificationType} structure`],
  };
}

function buildRoutingRefinement(problem: ProblemObject | undefined) {
  const nodes = readStringList(problem?.nodes ?? problem?.locations ?? problem?.stops ?? problem?.points);
  const costMatrix = readNumberMatrix(problem?.costMatrix ?? problem?.cost_matrix ?? problem?.distances);
  const required = requiredFieldsForType('routing');
  const missing: string[] = [];

  if (nodes.length < 2) {
    missing.push('locations');
  }

  if (costMatrix.length < 2 || !matrixComplete(costMatrix, nodes.length)) {
    missing.push('cost_matrix');
  }

  return {
    required,
    missing: [...new Set(missing)],
    normalizedProblem: {
      type: 'graph' as const,
      nodes,
      costMatrix,
      start: typeof problem?.start === 'string' ? problem.start : nodes[0],
    },
    partial: {
      nodes,
      costMatrix,
    },
  };
}

function buildSchedulingRefinement(problem: ProblemObject | undefined) {
  const workers = readStringList(problem?.workers ?? problem?.slots ?? problem?.shifts ?? problem?.resources);
  const tasks = readStringList(problem?.tasks ?? problem?.jobs ?? problem?.locations);
  const leftIds = workers;
  const rightIds = tasks;
  const costsFromObject = normalizeCostObject(problem?.costs, leftIds, rightIds);
  const costsFromMatrix = matrixToCosts(readNumberMatrix(problem?.costMatrix ?? problem?.cost_matrix), leftIds, rightIds);
  const costs = {
    ...costsFromObject,
    ...Object.fromEntries(
      Object.entries(costsFromMatrix).map(([leftId, row]) => [
        leftId,
        {
          ...(costsFromObject[leftId] ?? {}),
          ...row,
        },
      ])
    ),
  };
  const required = requiredFieldsForType('scheduling');
  const missing: string[] = [];

  if (workers.length === 0) {
    missing.push('workers');
  }

  if (tasks.length === 0) {
    missing.push('tasks');
  }

  if (!costObjectComplete(costs, leftIds, rightIds)) {
    missing.push('costs');
  }

  return {
    required,
    missing: [...new Set(missing)],
    normalizedProblem: {
      type: 'scheduling' as const,
      workers,
      tasks,
      costs,
    },
    partial: {
      workers,
      tasks,
      costs,
    },
  };
}

function buildAllocationRefinement(problem: ProblemObject | undefined) {
  const resources = readStringList(problem?.resources ?? problem?.assets ?? problem?.trucks);
  const locations = readStringList(problem?.locations ?? problem?.zones ?? problem?.targets);
  const leftIds = resources;
  const rightIds = locations;
  const costsFromObject = normalizeCostObject(problem?.costs, leftIds, rightIds);
  const costsFromMatrix = matrixToCosts(readNumberMatrix(problem?.costMatrix ?? problem?.cost_matrix), leftIds, rightIds);
  const costs = {
    ...costsFromObject,
    ...Object.fromEntries(
      Object.entries(costsFromMatrix).map(([leftId, row]) => [
        leftId,
        {
          ...(costsFromObject[leftId] ?? {}),
          ...row,
        },
      ])
    ),
  };
  const required = requiredFieldsForType('allocation');
  const missing: string[] = [];

  if (resources.length === 0) {
    missing.push('resources');
  }

  if (locations.length === 0) {
    missing.push('locations');
  }

  if (!costObjectComplete(costs, leftIds, rightIds)) {
    missing.push('costs');
  }

  return {
    required,
    missing: [...new Set(missing)],
    normalizedProblem: {
      type: 'allocation' as const,
      resources,
      locations,
      costs,
    },
    partial: {
      resources,
      locations,
      costs,
    },
  };
}

function summarizeMissing(type: RefinedProblemType, missing: string[]) {
  if (missing.length === 0) {
    return `${type} problem is fully specified.`;
  }

  return `${type} problem needs: ${missing.join(', ')}.`;
}

export function refineProblem(input: string | ProblemObject): RefinedProblemResult {
  const classification = classifyProblem(input);
  const problem = readProblemObject(input);
  const type = inferProblemType(classification, problem);
  const partialInput = problem ?? {};

  if (type === 'unknown') {
    const complexity = estimateProblemComplexity({
      type: 'unknown',
      source: partialInput,
    });

    return {
      ok: false,
      status: 'needs_input',
      code: 'missing_input',
      type,
      needs_input: true,
      required: ['problem_type'],
      missing: ['problem_type'],
      classification,
      complexity,
      summary: 'Could not determine the optimization problem type from the provided input.',
      partial: problem,
    };
  }

  if (type === 'routing') {
    const builder = buildRoutingRefinement(problem);
    const complexity = estimateProblemComplexity({
      type: builder.normalizedProblem.type,
      nodes: builder.normalizedProblem.nodes,
      costMatrix: builder.normalizedProblem.costMatrix,
      constraints: Array.isArray((problem ?? {})['constraints'])
        ? ((problem ?? {})['constraints'] as Array<unknown>)
        : undefined,
      source: partialInput,
    });

    if (builder.missing.length > 0) {
      return {
        ok: false,
        status: 'needs_input',
        code: 'missing_input',
        type,
        needs_input: true,
        required: builder.required,
        missing: builder.missing,
        classification,
        complexity,
        summary: summarizeMissing(type, builder.missing),
        partial: builder.partial,
      };
    }

    const structuredModel = buildStructuredProblemModel({
      classification: normalizeClassificationForType(type, classification),
      graph: {
        nodes: builder.normalizedProblem.nodes,
        costMatrix: builder.normalizedProblem.costMatrix,
      },
      source: partialInput,
    } as Parameters<typeof buildStructuredProblemModel>[0]);

    if (structuredModel.status === 'needs_input') {
      return {
        ok: false,
        status: 'needs_input',
        code: 'missing_input',
        type,
        needs_input: true,
        required: builder.required,
        missing: structuredModel.missing,
        classification,
        complexity,
        summary: summarizeMissing(type, structuredModel.missing),
        partial: builder.partial,
      };
    }

    return {
      ok: true,
      status: 'ready',
      type,
      needs_input: false,
      required: builder.required,
      missing: [],
      classification,
      normalizedProblem: builder.normalizedProblem,
      structuredModel: structuredModel.model,
      complexity,
      objectiveSummary: describeObjectiveFunction(structuredModel.model.objective),
      summary: `${type} problem is ready with ${complexity.problemSize} decision entities.`,
    };
  }

  if (type === 'allocation') {
    const builder = buildAllocationRefinement(problem);
    const complexity = estimateProblemComplexity({
      type: builder.normalizedProblem.type,
      resources: builder.normalizedProblem.resources,
      locations: builder.normalizedProblem.locations,
      costs: builder.normalizedProblem.costs,
      constraints: Array.isArray((problem ?? {})['constraints'])
        ? ((problem ?? {})['constraints'] as Array<unknown>)
        : undefined,
      source: partialInput,
    });

    if (builder.missing.length > 0) {
      return {
        ok: false,
        status: 'needs_input',
        code: 'missing_input',
        type,
        needs_input: true,
        required: builder.required,
        missing: builder.missing,
        classification,
        complexity,
        summary: summarizeMissing(type, builder.missing),
        partial: builder.partial,
      };
    }

    const structuredModel = buildStructuredProblemModel({
      classification: normalizeClassificationForType(type, classification),
      allocation: {
        resources: builder.normalizedProblem.resources.map((id: string) => ({ id })),
        locations: builder.normalizedProblem.locations.map((id: string) => ({ id })),
        costs: builder.normalizedProblem.costs,
      },
      source: partialInput,
    } as Parameters<typeof buildStructuredProblemModel>[0]);

    if (structuredModel.status === 'needs_input') {
      return {
        ok: false,
        status: 'needs_input',
        code: 'missing_input',
        type,
        needs_input: true,
        required: builder.required,
        missing: structuredModel.missing,
        classification,
        complexity,
        summary: summarizeMissing(type, structuredModel.missing),
        partial: builder.partial,
      };
    }

    return {
      ok: true,
      status: 'ready',
      type,
      needs_input: false,
      required: builder.required,
      missing: [],
      classification,
      normalizedProblem: builder.normalizedProblem,
      structuredModel: structuredModel.model,
      complexity,
      objectiveSummary: describeObjectiveFunction(structuredModel.model.objective),
      summary: `${type} problem is ready with ${complexity.problemSize} decision entities.`,
    };
  }

  const builder = buildSchedulingRefinement(problem);
  const complexity = estimateProblemComplexity({
    type: builder.normalizedProblem.type,
    workers: builder.normalizedProblem.workers,
    tasks: builder.normalizedProblem.tasks,
    costs: builder.normalizedProblem.costs,
    constraints: Array.isArray((problem ?? {})['constraints'])
      ? ((problem ?? {})['constraints'] as Array<unknown>)
      : undefined,
    source: partialInput,
  });

  if (builder.missing.length > 0) {
    return {
      ok: false,
      status: 'needs_input',
      code: 'missing_input',
      type,
      needs_input: true,
      required: builder.required,
      missing: builder.missing,
      classification,
      complexity,
      summary: summarizeMissing(type, builder.missing),
      partial: builder.partial,
    };
  }

  const structuredModel = buildStructuredProblemModel({
    classification: normalizeClassificationForType(type, classification),
    assignment: {
      workers: builder.normalizedProblem.workers.map((id: string) => ({ id })),
      tasks: builder.normalizedProblem.tasks.map((id: string) => ({ id })),
      costs: builder.normalizedProblem.costs,
    },
    source: partialInput,
  } as Parameters<typeof buildStructuredProblemModel>[0]);

  if (structuredModel.status === 'needs_input') {
    return {
      ok: false,
      status: 'needs_input',
      code: 'missing_input',
      type,
      needs_input: true,
      required: builder.required,
      missing: structuredModel.missing,
      classification,
      complexity,
      summary: summarizeMissing(type, structuredModel.missing),
      partial: builder.partial,
    };
  }

  return {
    ok: true,
    status: 'ready',
    type,
    needs_input: false,
    required: builder.required,
    missing: [],
    classification,
    normalizedProblem: builder.normalizedProblem,
    structuredModel: structuredModel.model,
    complexity,
    objectiveSummary: describeObjectiveFunction(structuredModel.model.objective),
    summary: `${type} problem is ready with ${complexity.problemSize} decision entities.`,
  };
}
