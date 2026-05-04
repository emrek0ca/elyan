import { describe, expect, it } from 'vitest';
import { capabilityRegistry } from '@/core/capabilities';
import { buildAssignmentDemo, buildQubo, runOptimization } from '@/core/optimization';

describe('optimization capability', () => {
  it('builds the assignment demo model and QUBO variables', () => {
    const problem = buildAssignmentDemo();
    const qubo = buildQubo(problem);

    expect(problem.problemType).toBe('assignment');
    expect(qubo.variables.length).toBe(problem.tasks.length * problem.workers.length);
    expect(qubo.variables[0]?.id).toMatch(/^x_/);
    expect(Object.keys(qubo.linear).length).toBeGreaterThan(0);
    expect(Object.keys(qubo.quadratic).length).toBeGreaterThan(0);
  });

  it('compares greedy, simulated annealing, and QUBO fallback results', () => {
    const result = runOptimization({ action: 'run_demo', demo: 'assignment' });

    expect(result.ok).toBe(true);
    expect(result.model.problemType).toBe('assignment');
    expect(result.pipeline.map((step) => step.step)).toEqual([
      'problem',
      'model',
      'constraint',
      'objective',
      'representation',
      'solve',
      'compare',
      'explain',
    ]);
    expect(result.problemProfile.leftEntityKind).toBe('worker');
    expect(result.problemProfile.rightEntityKind).toBe('task');
    expect(result.comparisonSummary.solverCount).toBe(3);
    expect(result.comparisonSummary.feasibleSolverCount).toBeGreaterThanOrEqual(2);
    expect(result.solverResults.map((entry) => entry.solver)).toEqual([
      'greedy',
      'simulated_annealing',
      'qubo_bruteforce',
    ]);
    expect(result.selectedSolution.feasible).toBe(true);
    expect(result.selectedSolution.violationCount).toBe(0);
    expect(result.markdownReport).toContain('## Problem Model');
    expect(result.markdownReport).toContain('## Decision Pipeline');
    expect(result.markdownReport).toContain('## Solver Comparison');
    expect(result.markdownReport).toContain('## Recommended Solution');
    expect(result.markdownReport).toContain('No real quantum hardware was used');
  });

  it('supports the resource allocation demo without external quantum dependencies', () => {
    const result = runOptimization({ action: 'run_demo', demo: 'resource-allocation' });

    expect(result.model.problemType).toBe('resource_allocation');
    expect(result.selectedSolution.feasible).toBe(true);
    expect(result.solverResults.some((entry) => entry.backend === 'quantum_inspired')).toBe(true);
  });

  it('executes through the typed capability registry', async () => {
    const result = await capabilityRegistry.execute('optimization_solve', {
      action: 'run_demo',
      demo: 'assignment',
    });

    expect(result.jsonSummary.problemType).toBe('assignment');
    expect(result.jsonSummary.feasible).toBe(true);
    expect(result.markdownReport).toContain('Recommended Solution');
  });
});
