import { describe, expect, it } from 'vitest';
import { capabilityRegistry } from '@/core/capabilities';
import { buildAssignmentDemo, buildQubo, runOptimization } from '@/core/optimization';
import { mapProblem } from '@/core/quantum/problem-mapper';
import { solveHybridOptimization } from '@/core/capabilities/quantum/hybrid_solver';
import { classifyProblem } from '@/core/problem/classifier';

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

  it('maps graph route problems into a QUBO-like structure', () => {
    const mapping = mapProblem({
      type: 'graph',
      nodes: ['depot', 'a', 'b'],
      costMatrix: [
        [0, 2, 8],
        [2, 0, 1],
        [8, 1, 0],
      ],
      start: 'depot',
    });

    expect(mapping.status).toBe('ready');
    if (mapping.status !== 'ready') {
      throw new Error('expected ready graph mapping');
    }
    expect(mapping.type).toBe('graph');
    expect(mapping.structuredModel).toMatchObject({
      type: 'routing',
      objective: {
        kind: 'weighted',
        primaryMetric: 'cost',
        direction: 'minimize',
      },
      costFunction: {
        kind: 'matrix',
        complete: true,
      },
    });
    expect(mapping.structuredModel.objective.weights.cost).toBeGreaterThan(mapping.structuredModel.objective.weights.efficiency);
    expect(mapping.structuredModel.constraints.map((constraint) => constraint.id)).toEqual(
      expect.arrayContaining(['visit_each_node_once', 'return_to_start'])
    );
    expect(mapping.qubo.variables.length).toBe(6);
    expect(mapping.problem.problemType).toBe('graph');
  });

  it('maps scheduling and allocation problems into assignment-compatible structures', () => {
    const scheduling = mapProblem({
      type: 'scheduling',
      workers: ['morning', 'afternoon'],
      tasks: ['job-a', 'job-b'],
      costs: {
        morning: { 'job-a': 7, 'job-b': 2 },
        afternoon: { 'job-a': 1, 'job-b': 8 },
      },
    });
    const allocation = mapProblem({
      type: 'allocation',
      resources: ['truck-a', 'truck-b'],
      locations: ['zone-1', 'zone-2'],
      costs: {
        'truck-a': { 'zone-1': 8, 'zone-2': 1 },
        'truck-b': { 'zone-1': 2, 'zone-2': 7 },
      },
    });

    expect(scheduling.status).toBe('ready');
    expect(allocation.status).toBe('ready');
    if (scheduling.status === 'ready') {
      expect(scheduling.problem.problemType).toBe('assignment');
      expect(scheduling.structuredModel.type).toBe('scheduling');
      expect(scheduling.structuredModel.constraints.map((constraint) => constraint.id)).toContain('each_task_assigned_once');
    }
    if (allocation.status === 'ready') {
      expect(allocation.problem.problemType).toBe('resource_allocation');
      expect(allocation.structuredModel.type).toBe('allocation');
      expect(allocation.structuredModel.constraints.map((constraint) => constraint.id)).toContain('each_location_allocated_once');
    }
  });

  it('classifies problem shape deterministically before solving', () => {
    expect(classifyProblem('Find the best delivery route through these nodes').type).toBe('routing');
    expect(classifyProblem('Build a shift scheduling plan with minimum cost').type).toBe('scheduling');
    expect(classifyProblem('Allocate resources to zones with capacity limits').type).toBe('allocation');
    expect(classifyProblem('Hello there').type).toBe('unknown');
  });

  it('returns needs_input instead of inventing missing optimization data', () => {
    const mapping = mapProblem('Find the optimal delivery route tomorrow.');

    expect(mapping.status).toBe('needs_input');
    if (mapping.status === 'needs_input') {
      expect(mapping.type).toBe('graph');
      expect(mapping.missing).toEqual(expect.arrayContaining(['nodes', 'costMatrix']));
    }
  });

  it('hybrid solver improves over a deliberately suboptimal greedy baseline', () => {
    const result = solveHybridOptimization({
      strategy: 'hybrid',
      problem: {
        type: 'assignment',
        workers: ['w1', 'w2'],
        tasks: ['t1', 't2'],
        costs: {
          w1: { t1: 1, t2: 2 },
          w2: { t1: 2, t2: 100 },
        },
      },
    });

    expect(result.status).toBe('solved');
    expect(result.baselineSolution?.solver).toBe('greedy');
    expect(result.metadata.baseline_cost).toBeGreaterThan(result.metadata.selected_cost ?? 0);
    expect(result.metadata.improvement_ratio).toBeGreaterThan(0);
    expect(result.comparison.length).toBeGreaterThan(0);
    expect(result.score).toBeGreaterThan(0);
    expect(result.verification.valid).toBe(true);
    expect(result.bestSolution?.solver).toBe(result.selectedSolution?.solver);
    expect(result.selectedSolution?.feasible).toBe(true);
    expect(result.markdownReport).toContain('Quantum Hybrid Optimization Report');
    expect(result.markdownReport).toContain('## Why This Solution');
    expect(result.markdownReport).toContain('## Trade-offs');
    expect(result.markdownReport).toContain('## Rejected Alternatives');
  });

  it('optimization_solve uses hybrid solving for mapped non-demo problems', async () => {
    const result = await capabilityRegistry.execute('optimization_solve', {
      action: 'solve',
      problem: {
        type: 'allocation',
        resources: ['truck-a', 'truck-b'],
        locations: ['zone-1', 'zone-2'],
        costs: {
          'truck-a': { 'zone-1': 8, 'zone-2': 1 },
          'truck-b': { 'zone-1': 2, 'zone-2': 7 },
        },
      },
    });

    expect(result.ok).toBe(true);
    expect(result.markdownReport).toContain('Quantum Hybrid Optimization Report');
    expect(result.jsonSummary.status).toBe('solved');
  });

  it('returns a scenario benchmark for demo logistics requests', async () => {
    const result = await capabilityRegistry.execute('optimization_solve', {
      action: 'run_demo',
      query: 'demo logistics',
    });

    expect(result.ok).toBe(true);
    expect(result.scenario?.id).toBe('logistics_routing');
    expect(result.scenarioBenchmark?.improvementPercent).toBeGreaterThanOrEqual(0);
    expect(result.scenarioBenchmark?.constraintSatisfaction).toBeGreaterThanOrEqual(0);
    expect(result.jsonSummary.scenarioId).toBe('logistics_routing');
    expect(result.jsonSummary.scenarioMode).toBe('demo');
    expect(result.markdownReport).toContain('Scenario Benchmark');
  });
});
