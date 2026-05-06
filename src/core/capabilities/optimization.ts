import { z } from 'zod';
import type { CapabilityDefinition, CapabilityExecutionContext } from './types';
import { runOptimization } from '@/core/optimization';

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
  problem: optimizationProblemSchema.optional(),
});

export const optimizationSolveOutputSchema = z.object({
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
    return optimizationSolveOutputSchema.parse(runOptimization(input));
  },
};
