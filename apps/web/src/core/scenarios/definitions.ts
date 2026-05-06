import { z } from 'zod';

export type ScenarioType = 'routing' | 'scheduling' | 'allocation';

export type ScenarioId =
  | 'logistics_routing'
  | 'delivery_optimization'
  | 'scheduling_system'
  | 'resource_allocation'
  | 'load_balancing';

export type ScenarioOutputStructure = {
  type: ScenarioType;
  validation: {
    ok: boolean;
    missing: string[];
  };
  benchmark: {
    baseline: {
      solver: string;
      backend: string;
    };
    classical: {
      solver: string;
      backend: string;
    };
    hybrid: {
      solver: string;
      backend: string;
    };
    improvement_percent: number;
    efficiency_gain: number;
    constraint_satisfaction: number;
  };
  explanation: {
    why_this_solution: string;
    trade_offs: string[];
    rejected_alternatives: string[];
  };
};

export type ScenarioDefinition = {
  id: ScenarioId;
  label: string;
  type: ScenarioType;
  description: string;
  patterns: RegExp[];
  input_schema: z.ZodType<Record<string, unknown>>;
  example_input: Record<string, unknown>;
  expected_output_structure: ScenarioOutputStructure;
};

const routingInputSchema = z
  .object({
    type: z.enum(['graph', 'routing']).optional(),
    nodes: z.array(z.string().min(1)).min(2),
    costMatrix: z.array(z.array(z.number())).min(2),
    cost_matrix: z.array(z.array(z.number())).min(2).optional(),
    start: z.string().optional(),
    deliveries: z.array(z.unknown()).optional(),
    vehicles: z.array(z.unknown()).optional(),
    constraints: z.array(z.unknown()).optional(),
  })
  .passthrough();

const schedulingInputSchema = z
  .object({
    type: z.enum(['scheduling', 'assignment']).optional(),
    workers: z.array(z.unknown()).min(2),
    tasks: z.array(z.unknown()).min(2),
    costs: z.record(z.string(), z.record(z.string(), z.number())),
    constraints: z.array(z.unknown()).optional(),
  })
  .passthrough();

const allocationInputSchema = z
  .object({
    type: z.enum(['allocation', 'resource_allocation']).optional(),
    resources: z.array(z.unknown()).min(2),
    locations: z.array(z.unknown()).min(2),
    costs: z.record(z.string(), z.record(z.string(), z.number())),
    capacities: z.array(z.unknown()).optional(),
    constraints: z.array(z.unknown()).optional(),
  })
  .passthrough();

const scenarioOutputStructure = (type: ScenarioType): ScenarioOutputStructure => ({
  type,
  validation: {
    ok: true,
    missing: [],
  },
  benchmark: {
    baseline: {
      solver: 'naive_baseline',
      backend: 'classical',
    },
    classical: {
      solver: 'greedy',
      backend: 'classical',
    },
    hybrid: {
      solver: 'hybrid',
      backend: 'quantum_inspired',
    },
    improvement_percent: 0,
    efficiency_gain: 0,
    constraint_satisfaction: 0,
  },
  explanation: {
    why_this_solution: 'The selected solution is the best deterministic candidate for this scenario.',
    trade_offs: ['Baseline solution is intentionally naive.', 'Hybrid solution may trade runtime for better cost.'],
    rejected_alternatives: ['Naive baseline', 'Classical baseline'],
  },
});

export const scenarioDefinitions: Record<ScenarioId, ScenarioDefinition> = {
  logistics_routing: {
    id: 'logistics_routing',
    label: 'Logistics Routing',
    type: 'routing',
    description: 'Route delivery stops through a complete distance matrix and choose the lowest-cost tour.',
    patterns: [
      /\b(logistics routing|logistics route|delivery routes?|route delivery|delivery route|delivery network)\b/i,
      /\b(optimize delivery routes?|optimize the delivery route|best route for deliveries|route planning)\b/i,
      /\b(last mile|fleet routing|dispatch route)\b/i,
    ],
    input_schema: routingInputSchema,
    example_input: {
      type: 'graph',
      title: 'Demo logistics routing',
      nodes: ['depot', 'north', 'central', 'south'],
      costMatrix: [
        [0, 3, 7, 5],
        [3, 0, 4, 6],
        [7, 4, 0, 2],
        [5, 6, 2, 0],
      ],
      start: 'depot',
      constraints: ['visit every stop once', 'return to depot'],
    },
    expected_output_structure: scenarioOutputStructure('routing'),
  },
  delivery_optimization: {
    id: 'delivery_optimization',
    label: 'Delivery Optimization',
    type: 'routing',
    description: 'Optimize delivery coverage and dispatch routing with a deterministic cost matrix.',
    patterns: [
      /\b(delivery optimization|delivery optimise|delivery optimize|courier routing|shipment routing)\b/i,
      /\b(dispatch optimization|route optimization for deliveries|dispatch planning)\b/i,
      /\b(parcel routing|package delivery|delivery scheduling)\b/i,
    ],
    input_schema: routingInputSchema,
    example_input: {
      type: 'graph',
      title: 'Demo delivery optimization',
      nodes: ['warehouse', 'zone-a', 'zone-b', 'zone-c'],
      costMatrix: [
        [0, 2, 9, 8],
        [2, 0, 3, 5],
        [9, 3, 0, 4],
        [8, 5, 4, 0],
      ],
      start: 'warehouse',
      deliveries: ['zone-a', 'zone-b', 'zone-c'],
      constraints: ['minimize travel cost', 'serve all zones'],
    },
    expected_output_structure: scenarioOutputStructure('routing'),
  },
  scheduling_system: {
    id: 'scheduling_system',
    label: 'Scheduling System',
    type: 'scheduling',
    description: 'Assign workers to jobs or shifts while minimizing total cost.',
    patterns: [
      /\b(scheduling system|schedule system|shift planning|shift roster|staff scheduling)\b/i,
      /\b(workforce scheduling|job scheduling|calendar scheduling|appointment scheduling)\b/i,
      /\b(vardiya planlama|planlama sistemi)\b/i,
    ],
    input_schema: schedulingInputSchema,
    example_input: {
      type: 'scheduling',
      title: 'Demo scheduling system',
      workers: ['morning', 'afternoon', 'night'],
      tasks: ['job-a', 'job-b', 'job-c'],
      costs: {
        morning: { 'job-a': 3, 'job-b': 7, 'job-c': 6 },
        afternoon: { 'job-a': 5, 'job-b': 2, 'job-c': 4 },
        night: { 'job-a': 6, 'job-b': 4, 'job-c': 1 },
      },
      constraints: ['assign each job once', 'respect shift coverage'],
    },
    expected_output_structure: scenarioOutputStructure('scheduling'),
  },
  resource_allocation: {
    id: 'resource_allocation',
    label: 'Resource Allocation',
    type: 'allocation',
    description: 'Allocate resources to locations or tasks with minimum cost and strict capacity checks.',
    patterns: [
      /\b(resource allocation|allocate resources|resource distribution|capacity planning)\b/i,
      /\b(best allocation|optimal allocation|allocation plan|resource plan)\b/i,
      /\b(kaynak tahsisi|kaynak dağıtımı)\b/i,
    ],
    input_schema: allocationInputSchema,
    example_input: {
      type: 'allocation',
      title: 'Demo resource allocation',
      resources: ['truck-a', 'truck-b', 'truck-c'],
      locations: ['zone-1', 'zone-2', 'zone-3'],
      costs: {
        'truck-a': { 'zone-1': 4, 'zone-2': 8, 'zone-3': 6 },
        'truck-b': { 'zone-1': 3, 'zone-2': 5, 'zone-3': 7 },
        'truck-c': { 'zone-1': 6, 'zone-2': 4, 'zone-3': 2 },
      },
      capacities: [1, 1, 1],
      constraints: ['allocate each location once', 'respect resource capacity'],
    },
    expected_output_structure: scenarioOutputStructure('allocation'),
  },
  load_balancing: {
    id: 'load_balancing',
    label: 'Load Balancing',
    type: 'allocation',
    description: 'Distribute traffic, compute work, or capacity across available resources.',
    patterns: [
      /\b(load balancing|server balancing|workload balancing|traffic balancing)\b/i,
      /\b(distribute traffic|balance load|balance the load|compute balancing)\b/i,
      /\b(yük dengeleme|yük dağıtımı)\b/i,
    ],
    input_schema: allocationInputSchema,
    example_input: {
      type: 'allocation',
      title: 'Demo load balancing',
      resources: ['server-a', 'server-b', 'server-c'],
      locations: ['queue-1', 'queue-2', 'queue-3'],
      costs: {
        'server-a': { 'queue-1': 6, 'queue-2': 2, 'queue-3': 5 },
        'server-b': { 'queue-1': 3, 'queue-2': 7, 'queue-3': 4 },
        'server-c': { 'queue-1': 4, 'queue-2': 5, 'queue-3': 1 },
      },
      capacities: [2, 2, 2],
      constraints: ['minimize total load imbalance', 'keep assignment deterministic'],
    },
    expected_output_structure: scenarioOutputStructure('allocation'),
  },
};

export const scenarioIds = Object.keys(scenarioDefinitions) as ScenarioId[];

