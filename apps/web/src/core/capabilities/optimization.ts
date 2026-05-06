import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';
import { runOptimization } from '@/core/optimization';
import { solveHybridOptimization } from './quantum/hybrid_solver';
import { matchScenario, runScenarioBenchmark, type ScenarioId } from '@/core/scenarios';

const optimizationActionSchema = z.enum([
  'model_problem',
  'build_qubo',
  'solve',
  'compare_solvers',
  'explain_solution',
  'run_demo',
]);

const optimizationProblemSchema = z.record(z.string(), z.unknown());

export const optimizationSolveInputSchema = z.object({
  action: optimizationActionSchema.default('run_demo'),
  demo: z.enum(['assignment', 'resource-allocation', 'resource_allocation']).default('assignment'),
  scenario: z.enum([
    'logistics_routing',
    'delivery_optimization',
    'scheduling_system',
    'resource_allocation',
    'load_balancing',
  ]).optional(),
  problem: optimizationProblemSchema.optional(),
  query: z.string().optional(),
  preferredSolverId: z.string().optional(),
});

const optimizationAssignmentOutputSchema = z.object({
  ok: z.boolean(),
  action: optimizationActionSchema,
  problem: z.record(z.string(), z.unknown()),
  problemProfile: z.object({
    problemType: z.string(),
    leftEntityKind: z.string(),
    leftEntityCount: z.number().int().nonnegative(),
    rightEntityKind: z.string(),
    rightEntityCount: z.number().int().nonnegative(),
    decisionVariableCount: z.number().int().nonnegative(),
    hardConstraintCount: z.number().int().nonnegative(),
  }),
  model: z.object({
    problemType: z.string(),
    variables: z.number().int().nonnegative(),
    constraints: z.array(z.string()),
    objective: z.string(),
  }),
  pipeline: z.array(
    z.object({
      step: z.enum(['problem', 'model', 'constraint', 'objective', 'representation', 'solve', 'compare', 'explain']),
      title: z.string(),
      summary: z.string(),
    })
  ),
  comparisonSummary: z.object({
    solverCount: z.number().int().nonnegative(),
    feasibleSolverCount: z.number().int().nonnegative(),
    selectedSolver: z.string(),
    selectedBackend: z.enum(['classical', 'quantum_inspired', 'optional_external_unavailable']),
    selectedCost: z.number(),
    runnerUpCost: z.number().nullable(),
    costGapToRunnerUp: z.number(),
    selectedEnergy: z.number(),
    explanation: z.string(),
  }),
  qubo: z.object({
    variables: z.array(
      z.object({
        id: z.string(),
        leftId: z.string(),
        rightId: z.string(),
      })
    ),
    linear: z.record(z.string(), z.number()),
    quadratic: z.record(z.string(), z.number()),
    offset: z.number(),
    penalty: z.number(),
  }),
  solverResults: z.array(
    z.object({
      solver: z.string(),
      backend: z.enum(['classical', 'quantum_inspired', 'optional_external_unavailable']),
      feasible: z.boolean(),
      totalCost: z.number(),
      energy: z.number(),
      assignments: z.array(
        z.object({
          from: z.string(),
          to: z.string(),
          cost: z.number(),
        })
      ),
      violationCount: z.number().int().nonnegative(),
      violations: z.array(z.string()),
      runtimeMs: z.number().nonnegative(),
      explanation: z.string(),
    })
  ),
  selectedSolution: z.object({
    solver: z.string(),
    backend: z.enum(['classical', 'quantum_inspired', 'optional_external_unavailable']),
    feasible: z.boolean(),
    totalCost: z.number(),
    energy: z.number(),
    assignments: z.array(
      z.object({
        from: z.string(),
        to: z.string(),
        cost: z.number(),
      })
    ),
    violationCount: z.number().int().nonnegative(),
    violations: z.array(z.string()),
    runtimeMs: z.number().nonnegative(),
    explanation: z.string(),
  }),
  markdownReport: z.string(),
  jsonSummary: z.object({
    problemType: z.string(),
    selectedSolver: z.string(),
    selectedBackend: z.string(),
    feasible: z.boolean(),
    totalCost: z.number(),
    violationCount: z.number().int().nonnegative(),
    assignmentCount: z.number().int().nonnegative(),
  }),
});

const optimizationHybridOutputSchema = z.object({
  ok: z.boolean(),
  status: z.enum(['solved', 'needs_input']),
  action: z.literal('solve'),
  problemType: z.string().optional(),
  mapping: z.record(z.string(), z.unknown()),
  missingInputs: z.array(z.string()),
  solverResults: z.array(
    z.object({
      solver: z.string(),
      backend: z.enum(['classical', 'quantum_inspired', 'optional_external_unavailable']),
      feasible: z.boolean(),
      totalCost: z.number(),
      energy: z.number(),
      assignments: z.array(
        z.object({
          from: z.string(),
          to: z.string(),
          cost: z.number(),
        })
      ),
      route: z.array(z.string()).optional(),
      violationCount: z.number().int().nonnegative(),
      violations: z.array(z.string()),
      runtimeMs: z.number().nonnegative(),
      explanation: z.string(),
    })
  ),
  baselineSolution: z.unknown().optional(),
  selectedSolution: z.unknown().optional(),
  bestSolution: z.unknown().optional(),
  score: z.number().optional(),
  whyThisSolution: z.string(),
  tradeOffs: z.array(z.string()),
  rejectedAlternatives: z.array(
    z.object({
      solver: z.string(),
      backend: z.string(),
      score: z.number(),
      totalCost: z.number(),
      runtimeMs: z.number().nonnegative(),
      reason: z.string(),
    })
  ),
  problemIntelligence: z.object({
    type: z.string(),
    complexity: z.string(),
    estimatedSpace: z.number(),
    problemSize: z.number(),
    objective: z.string(),
    objectiveSummary: z.string(),
  }),
  scenario: z.object({
    id: z.enum([
      'logistics_routing',
      'delivery_optimization',
      'scheduling_system',
      'resource_allocation',
      'load_balancing',
    ]),
    label: z.string(),
    type: z.enum(['routing', 'scheduling', 'allocation']),
    mode: z.enum(['standard', 'demo', 'competition']),
    confidence: z.number(),
    reason: z.string(),
    demoRequested: z.boolean(),
  }).optional(),
  scenarioBenchmark: z.object({
    improvementPercent: z.number(),
    efficiencyGain: z.number(),
    constraintSatisfaction: z.number(),
    baseline: z.object({
      solver: z.string(),
      backend: z.string(),
      feasible: z.boolean(),
      totalCost: z.number(),
      runtimeMs: z.number(),
      violationCount: z.number().int().nonnegative(),
      constraintSatisfaction: z.number(),
      explanation: z.string(),
    }),
    classical: z.object({
      solver: z.string(),
      backend: z.string(),
      feasible: z.boolean(),
      totalCost: z.number(),
      runtimeMs: z.number(),
      violationCount: z.number().int().nonnegative(),
      constraintSatisfaction: z.number(),
      explanation: z.string(),
    }),
    hybrid: z.object({
      solver: z.string(),
      backend: z.string(),
      feasible: z.boolean(),
      totalCost: z.number(),
      runtimeMs: z.number(),
      violationCount: z.number().int().nonnegative(),
      constraintSatisfaction: z.number(),
      explanation: z.string(),
    }),
  }).optional(),
  comparison: z.array(
    z.object({
      solver: z.string(),
      backend: z.string(),
      feasible: z.boolean(),
      valid: z.boolean(),
      constraintViolations: z.number().int().nonnegative(),
      totalCost: z.number(),
      runtimeMs: z.number().nonnegative(),
      score: z.number(),
      rejected: z.boolean(),
      rejectionReason: z.string().optional(),
    })
  ),
  verification: z.object({
    valid: z.boolean(),
    violations: z.array(z.string()),
  }),
  markdownReport: z.string(),
    jsonSummary: z.object({
    problemType: z.string().optional(),
    selectedSolver: z.string().optional(),
    selectedBackend: z.string().optional(),
    feasible: z.boolean(),
    totalCost: z.number().optional(),
    violationCount: z.number().int().nonnegative().optional(),
    assignmentCount: z.number().int().nonnegative().optional(),
    improvementRatio: z.number().optional(),
    solutionQuality: z.number().optional(),
    solverQuality: z.number().optional(),
    successRate: z.number().optional(),
    solverStrategy: z.enum(['classical_only', 'hybrid', 'quantum_biased']).optional(),
    problemComplexity: z.string().optional(),
    estimatedSpace: z.number().optional(),
    objectiveSummary: z.string().optional(),
    scenarioId: z.enum([
      'logistics_routing',
      'delivery_optimization',
      'scheduling_system',
      'resource_allocation',
      'load_balancing',
    ]).optional(),
    scenarioMode: z.enum(['standard', 'demo', 'competition']).optional(),
    improvementPercent: z.number().optional(),
    efficiencyGain: z.number().optional(),
    constraintSatisfaction: z.number().optional(),
    status: z.enum(['solved', 'needs_input']),
  }),
  metadata: z.record(z.string(), z.unknown()),
});

export const optimizationSolveOutputSchema = z.union([
  optimizationAssignmentOutputSchema,
  optimizationHybridOutputSchema,
]);

function shouldUseScenarioBenchmark(input: z.output<typeof optimizationSolveInputSchema>) {
  if (input.problem) {
    return false;
  }

  return Boolean(input.scenario || (input.query && /\bdemo\b/i.test(input.query)));
}

function scenarioIdFromInput(input: z.output<typeof optimizationSolveInputSchema>): ScenarioId | undefined {
  if (input.scenario) {
    return input.scenario;
  }

  const matched = matchScenario(input.query);
  return matched.matched ? matched.scenarioId : undefined;
}

function buildScenarioBenchmarkOutput(
  benchmark: ReturnType<typeof runScenarioBenchmark> & { status: 'ready' },
  input: z.output<typeof optimizationSolveInputSchema>
) {
  const hybridResult = benchmark.hybridResult;
  return {
    ...hybridResult,
    scenario: {
      id: benchmark.scenario.id,
      label: benchmark.scenario.label,
      type: benchmark.scenario.type,
      mode: benchmark.mode,
      confidence: benchmark.match.confidence,
      reason: benchmark.match.reason,
      demoRequested: benchmark.match.demoRequested,
    },
    scenarioBenchmark: {
      improvementPercent: benchmark.improvementPercent,
      efficiencyGain: benchmark.efficiencyGain,
      constraintSatisfaction: benchmark.constraintSatisfaction,
      baseline: benchmark.baseline,
      classical: benchmark.classical,
      hybrid: benchmark.hybrid,
    },
    jsonSummary: {
      ...hybridResult.jsonSummary,
      scenarioId: benchmark.scenario.id,
      scenarioMode: benchmark.mode,
      improvementPercent: benchmark.improvementPercent,
      efficiencyGain: benchmark.efficiencyGain,
      constraintSatisfaction: benchmark.constraintSatisfaction,
    },
    markdownReport: [
      benchmark.markdownReport,
      '',
      `Scenario request: ${input.scenario ?? 'matched-by-query'}`,
    ].join('\n'),
  };
}

export function executeOptimizationSolve(input: z.output<typeof optimizationSolveInputSchema>) {
  if (shouldUseScenarioBenchmark(input)) {
    const scenarioBenchmark = runScenarioBenchmark(input.query ?? input.scenario ?? input.problem, {
      mode: 'demo',
      scenarioId: scenarioIdFromInput(input),
    });

    if (scenarioBenchmark.status === 'ready') {
      return buildScenarioBenchmarkOutput(scenarioBenchmark, input);
    }
  }

  if (input.problem || input.query?.trim()) {
    return solveHybridOptimization({
      query: input.query,
      problem: input.problem,
      preferredSolverId: input.preferredSolverId,
    });
  }

  return runOptimization(input);
}

export const optimizationSolveCapability: CapabilityDefinition<
  typeof optimizationSolveInputSchema,
  typeof optimizationSolveOutputSchema
> = {
  id: 'optimization_solve',
  title: 'Optimization Solve',
  description: 'Models assignment and resource allocation problems as QUBO and compares classical and quantum-inspired solvers.',
  library: 'elyan-optimization',
  enabled: true,
  timeoutMs: 3_000,
  inputSchema: optimizationSolveInputSchema,
  outputSchema: optimizationSolveOutputSchema,
  run: async (input: z.output<typeof optimizationSolveInputSchema>, _context: CapabilityExecutionContext) => {
    void _context;
    return optimizationSolveOutputSchema.parse(executeOptimizationSolve(input));
  },
};
