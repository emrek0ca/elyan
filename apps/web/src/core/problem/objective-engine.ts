import type { ProblemClass, ProblemClassification } from './classifier';

export type ObjectiveMetric = 'cost' | 'time' | 'efficiency' | 'constraints';
export type ObjectiveDirection = 'minimize' | 'maximize';

export type WeightedObjectiveTerm = {
  metric: ObjectiveMetric;
  weight: number;
  direction: ObjectiveDirection;
  description: string;
};

export type WeightedObjectiveFunction = {
  kind: 'weighted';
  direction: ObjectiveDirection;
  primaryMetric: ObjectiveMetric;
  weights: Record<ObjectiveMetric, number>;
  terms: WeightedObjectiveTerm[];
  expression: string;
};

export type ProblemObjective = WeightedObjectiveFunction;

export type StructuredProblemType = 'routing' | 'scheduling' | 'allocation';

export type StructuredProblemEntity = {
  id: string;
  kind: 'node' | 'worker' | 'task' | 'resource' | 'location';
  title?: string;
  capacity?: number;
  need?: number;
  priority?: number;
};

export type StructuredProblemConstraint = {
  id: string;
  description: string;
  required: boolean;
};

export type StructuredCostFunction = {
  kind: 'matrix' | 'bipartite_costs';
  metric: 'cost' | 'efficiency';
  complete: boolean;
  expression: string;
};

export type StructuredProblemModel = {
  type: StructuredProblemType;
  entities: StructuredProblemEntity[];
  constraints: StructuredProblemConstraint[];
  objective: ProblemObjective;
  costFunction: StructuredCostFunction;
  classification: ProblemClassification;
};

export type StructuredProblemModelResult =
  | {
      status: 'ready';
      model: StructuredProblemModel;
      missing: [];
    }
  | {
      status: 'needs_input';
      type: StructuredProblemType;
      missing: string[];
      classification: ProblemClassification;
    };

type EntityInput = {
  id: string;
  title?: string;
  capacity?: number;
  need?: number;
  priority?: number;
};

export type ObjectiveEngineInput = {
  classification: ProblemClassification;
  graph?: {
    nodes: string[];
    costMatrix: number[][];
  };
  assignment?: {
    workers: EntityInput[];
    tasks: EntityInput[];
    costs: Record<string, Record<string, number>>;
  };
  allocation?: {
    resources: EntityInput[];
    locations: EntityInput[];
    costs: Record<string, Record<string, number>>;
  };
  source?: Record<string, unknown>;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
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

function clamp01(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, Math.min(1, value));
}

function round2(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(2)) : 0;
}

function readObjectiveHint(source: Record<string, unknown> | undefined) {
  return [
    source?.objective,
    source?.goal,
    source?.optimizationGoal,
    source?.optimization_goal,
    source?.target,
    source?.targetMetric,
    source?.objectiveMetric,
  ]
    .filter((value): value is string => typeof value === 'string')
    .join(' ')
    .toLowerCase();
}

function readObjectiveWeights(source: Record<string, unknown> | undefined) {
  const rawWeights = isRecord(source?.weights)
    ? (source?.weights as Record<string, unknown>)
    : isRecord(source?.objectiveWeights)
      ? (source?.objectiveWeights as Record<string, unknown>)
      : isRecord(source?.objective_weights)
        ? (source?.objective_weights as Record<string, unknown>)
        : undefined;

  const explicit = {
    cost: toFiniteNumber(rawWeights?.cost) ?? toFiniteNumber(source?.costWeight) ?? toFiniteNumber(source?.cost_weight),
    time: toFiniteNumber(rawWeights?.time) ?? toFiniteNumber(source?.timeWeight) ?? toFiniteNumber(source?.time_weight),
    efficiency:
      toFiniteNumber(rawWeights?.efficiency) ??
      toFiniteNumber(source?.efficiencyWeight) ??
      toFiniteNumber(source?.efficiency_weight),
    constraints:
      toFiniteNumber(rawWeights?.constraints) ??
      toFiniteNumber(source?.constraintWeight) ??
      toFiniteNumber(source?.constraint_weight),
  };

  return explicit;
}

function normalizeWeights(weights: Record<ObjectiveMetric, number>) {
  const entries = Object.entries(weights) as Array<[ObjectiveMetric, number]>;
  const positive = entries.map(([, value]) => Math.max(0, value));
  const total = positive.reduce((sum, value) => sum + value, 0);

  if (total <= 0) {
    return {
      cost: 1,
      time: 0,
      efficiency: 0,
      constraints: 0,
    };
  }

  return entries.reduce((accumulator, [metric, value]) => {
    accumulator[metric] = round2(Math.max(0, value) / total);
    return accumulator;
  }, {
    cost: 0,
    time: 0,
    efficiency: 0,
    constraints: 0,
  } satisfies Record<ObjectiveMetric, number>);
}

function buildObjectiveFunction(source: Record<string, unknown> | undefined, classification: ProblemClassification): ProblemObjective {
  const hint = readObjectiveHint(source);
  const maximize = /\b(maximize|maximise|efficiency|throughput|utilization|utilisation|priority|verim|optimize throughput)\b/.test(hint);
  const routingBias = classification.type === 'routing' || classification.type === 'graph';
  const explicit = readObjectiveWeights(source);

  const defaults = maximize
    ? {
        cost: routingBias ? 0.2 : 0.25,
        time: 0.2,
        efficiency: routingBias ? 0.45 : 0.4,
        constraints: 0.15,
      }
    : {
        cost: routingBias ? 0.7 : 0.55,
        time: routingBias ? 0.2 : 0.18,
        efficiency: routingBias ? 0.05 : 0.12,
        constraints: 0.05,
      };

  const weights = normalizeWeights({
    cost: explicit.cost ?? defaults.cost,
    time: explicit.time ?? defaults.time,
    efficiency: explicit.efficiency ?? defaults.efficiency,
    constraints: explicit.constraints ?? defaults.constraints,
  });
  const direction: ObjectiveDirection = maximize ? 'maximize' : 'minimize';
  const terms: WeightedObjectiveTerm[] = [
    {
      metric: 'cost',
      weight: weights.cost,
      direction: 'minimize',
      description: 'minimize cost',
    },
    {
      metric: 'time',
      weight: weights.time,
      direction: 'minimize',
      description: 'minimize time',
    },
    {
      metric: 'efficiency',
      weight: weights.efficiency,
      direction: maximize ? 'maximize' : 'minimize',
      description: maximize ? 'maximize efficiency' : 'keep efficiency penalties low',
    },
    {
      metric: 'constraints',
      weight: weights.constraints,
      direction: 'minimize',
      description: 'minimize constraint violations',
    },
  ];

  const expression = terms
    .filter((term) => term.weight > 0)
    .map((term) => {
      const sign = term.direction === 'maximize' ? '-' : '+';
      const metric = term.metric === 'constraints' ? 'constraint_penalty' : term.metric;
      return `${sign} ${term.weight.toFixed(2)} * ${metric}`;
    })
    .join(' ')
    .replace(/^\+\s*/, '')
    .trim();

  return {
    kind: 'weighted',
    direction,
    primaryMetric: maximize ? 'efficiency' : 'cost',
    weights,
    terms,
    expression: expression.length > 0 ? expression : '0',
  };
}

export function describeObjectiveFunction(objective: ProblemObjective) {
  const activeTerms = objective.terms.filter((term) => term.weight > 0);
  const description = activeTerms
    .map((term) => `${term.weight.toFixed(2)} ${term.description}`)
    .join(', ');

  return `${objective.direction} weighted objective over ${objective.primaryMetric}: ${description || 'no active weights'}.`;
}

function hasCompleteCosts(costs: Record<string, Record<string, number>>, leftIds: string[], rightIds: string[]) {
  return leftIds.every((leftId) =>
    rightIds.every((rightId) => Number.isFinite(costs[leftId]?.[rightId]))
  );
}

function toEntities(entries: EntityInput[], kind: StructuredProblemEntity['kind']) {
  return entries.map((entry) => ({
    id: entry.id,
    kind,
    title: entry.title,
    capacity: entry.capacity,
    need: entry.need,
    priority: entry.priority,
  }));
}

function normalizeStructuredType(classificationType: ProblemClass): StructuredProblemType {
  if (classificationType === 'routing' || classificationType === 'graph') {
    return 'routing';
  }

  if (classificationType === 'allocation') {
    return 'allocation';
  }

  return 'scheduling';
}

function buildRoutingModel(input: ObjectiveEngineInput): StructuredProblemModelResult {
  const missing: string[] = [];
  const nodes = input.graph?.nodes ?? [];
  const costMatrix = input.graph?.costMatrix ?? [];

  if (nodes.length < 2) {
    missing.push('nodes');
  }

  const matrixComplete =
    costMatrix.length === nodes.length &&
    costMatrix.every((row) => row.length === nodes.length && row.every((entry) => Number.isFinite(entry)));

  if (!matrixComplete) {
    missing.push('costMatrix');
  }

  if (missing.length > 0) {
    return {
      status: 'needs_input',
      type: 'routing',
      missing,
      classification: input.classification,
    };
  }

  return {
    status: 'ready',
    missing: [],
    model: {
      type: 'routing',
      entities: nodes.map((id) => ({ id, kind: 'node' })),
      constraints: [
        { id: 'visit_each_node_once', description: 'Every node must be visited exactly once.', required: true },
        { id: 'return_to_start', description: 'The route must close back to the start node.', required: true },
        { id: 'numeric_cost_matrix', description: 'Every directed edge cost must be numeric.', required: true },
      ],
      objective: buildObjectiveFunction(input.source, input.classification),
      costFunction: {
        kind: 'matrix',
        metric: 'cost',
        complete: true,
        expression: 'sum(costMatrix[route[i]][route[i+1]]) including return edge',
      },
      classification: input.classification,
    },
  };
}

function buildBipartiteModel(input: ObjectiveEngineInput): StructuredProblemModelResult {
  const allocation = input.classification.type === 'allocation';
  const left = allocation ? input.allocation?.resources ?? [] : input.assignment?.workers ?? [];
  const right = allocation ? input.allocation?.locations ?? [] : input.assignment?.tasks ?? [];
  const costs = allocation ? input.allocation?.costs ?? {} : input.assignment?.costs ?? {};
  const leftIds = left.map((entry) => entry.id);
  const rightIds = right.map((entry) => entry.id);
  const missing: string[] = [];

  if (left.length === 0) {
    missing.push(allocation ? 'resources' : 'workers');
  }

  if (right.length === 0) {
    missing.push(allocation ? 'locations' : 'tasks');
  }

  if (!hasCompleteCosts(costs, leftIds, rightIds)) {
    missing.push('costs');
  }

  if (missing.length > 0) {
    return {
      status: 'needs_input',
      type: allocation ? 'allocation' : 'scheduling',
      missing,
      classification: input.classification,
    };
  }

  return {
    status: 'ready',
    missing: [],
    model: {
      type: allocation ? 'allocation' : 'scheduling',
      entities: allocation
        ? [...toEntities(left, 'resource'), ...toEntities(right, 'location')]
        : [...toEntities(left, 'worker'), ...toEntities(right, 'task')],
      constraints: allocation
        ? [
            { id: 'each_location_allocated_once', description: 'Every location must receive exactly one resource.', required: true },
            { id: 'resource_capacity_limits', description: 'Resource assignment counts must not exceed capacity.', required: true },
            { id: 'complete_numeric_costs', description: 'Every resource-location pair must have a numeric cost.', required: true },
          ]
        : [
            { id: 'each_task_assigned_once', description: 'Every task must be assigned exactly once.', required: true },
            { id: 'worker_capacity_limits', description: 'Worker assignment counts must not exceed capacity.', required: true },
            { id: 'complete_numeric_costs', description: 'Every worker-task pair must have a numeric cost.', required: true },
          ],
      objective: buildObjectiveFunction(input.source, input.classification),
      costFunction: {
        kind: 'bipartite_costs',
        metric: 'cost',
        complete: true,
        expression: allocation
          ? 'sum(costs[resource][location]) adjusted by location priority'
          : 'sum(costs[worker][task]) plus hard penalties for constraint violations',
      },
      classification: input.classification,
    },
  };
}

export function buildStructuredProblemModel(input: ObjectiveEngineInput): StructuredProblemModelResult {
  if (input.classification.type === 'routing' || input.classification.type === 'graph') {
    return buildRoutingModel(input);
  }

  if (input.classification.type === 'unknown') {
    return {
      status: 'needs_input',
      type: normalizeStructuredType(input.classification.type),
      missing: ['problem_type'],
      classification: input.classification,
    };
  }

  if (isRecord(input.source) && /\b(efficiency|throughput|utilization|utilisation)\b/i.test(JSON.stringify(input.source))) {
    // Objective is still expressed through the same deterministic cost model; the metadata records the goal.
    return buildBipartiteModel(input);
  }

  return buildBipartiteModel(input);
}
