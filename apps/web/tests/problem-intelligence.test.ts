import { describe, expect, it } from 'vitest';
import { estimateProblemComplexity } from '@/core/problem/complexity';
import { refineProblem } from '@/core/problem/refiner';

function buildCostMatrix(size: number) {
  return Array.from({ length: size }, (_, leftIndex) =>
    Array.from({ length: size }, (_, rightIndex) => {
      if (leftIndex === rightIndex) {
        return 0;
      }

      return (leftIndex + 1) * (rightIndex + 2);
    })
  );
}

function buildCostObject(leftIds: string[], rightIds: string[], base = 1) {
  return Object.fromEntries(
    leftIds.map((leftId, leftIndex) => [
      leftId,
      Object.fromEntries(
        rightIds.map((rightId, rightIndex) => [
          rightId,
          base + leftIndex * rightIds.length + rightIndex + 1,
        ])
      ),
    ])
  );
}

describe('problem intelligence layer', () => {
  it('returns a structured clarification request for vague routing input', () => {
    const refinement = refineProblem('optimize delivery');

    expect(refinement.ok).toBe(false);
    expect(refinement.code).toBe('missing_input');
    expect(refinement.type).toBe('routing');
    expect(refinement.required).toEqual(expect.arrayContaining(['locations', 'cost_matrix']));
    expect(refinement.missing).toEqual(expect.arrayContaining(['locations', 'cost_matrix']));
    expect(refinement.summary).toContain('routing problem needs');
  });

  it('refines partial routing input into a weighted structured model', () => {
    const refinement = refineProblem({
      type: 'graph',
      locations: ['depot', 'a', 'b'],
      cost_matrix: buildCostMatrix(3),
      objective: 'maximize efficiency',
      weights: {
        cost: 0.2,
        time: 0.2,
        efficiency: 0.5,
        constraints: 0.1,
      },
    });

    expect(refinement.ok).toBe(true);
    if (!refinement.ok) {
      throw new Error('expected routing refinement to be ready');
    }

    expect(refinement.type).toBe('routing');
    expect(refinement.complexity.complexity).toBe('low');
    expect(refinement.structuredModel.objective.kind).toBe('weighted');
    expect(refinement.structuredModel.objective.direction).toBe('maximize');
    expect(refinement.structuredModel.objective.primaryMetric).toBe('efficiency');
    expect(refinement.structuredModel.objective.weights.efficiency).toBeGreaterThan(refinement.structuredModel.objective.weights.cost);
    expect(refinement.objectiveSummary).toContain('maximize weighted objective');
  });

  it('estimates complexity deterministically across small, medium, and large problems', () => {
    const low = estimateProblemComplexity({
      type: 'routing',
      nodes: ['a', 'b', 'c'],
      costMatrix: buildCostMatrix(3),
    });
    const mediumWorkers = ['w1', 'w2', 'w3', 'w4'];
    const mediumTasks = ['t1', 't2', 't3', 't4'];
    const medium = estimateProblemComplexity({
      type: 'scheduling',
      workers: mediumWorkers.map((id) => ({ id })),
      tasks: mediumTasks.map((id) => ({ id })),
      costs: buildCostObject(mediumWorkers, mediumTasks),
    });
    const largeWorkers = Array.from({ length: 8 }, (_, index) => `w${index + 1}`);
    const largeTasks = Array.from({ length: 8 }, (_, index) => `t${index + 1}`);
    const large = estimateProblemComplexity({
      type: 'scheduling',
      workers: largeWorkers.map((id) => ({ id })),
      tasks: largeTasks.map((id) => ({ id })),
      costs: buildCostObject(largeWorkers, largeTasks),
    });

    expect(low.complexity).toBe('low');
    expect(medium.complexity).toBe('medium');
    expect(large.complexity).toBe('high');
    expect(large.estimated_space).toBeGreaterThan(medium.estimated_space);
  });
});
