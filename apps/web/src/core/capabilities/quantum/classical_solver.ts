import { runOptimization } from '@/core/optimization';
import type { QuantumGraphProblem, QuantumProblemMapping } from '@/core/quantum/problem-mapper';

export type QuantumSolverBackend = 'classical' | 'quantum_inspired' | 'optional_external_unavailable';

export type QuantumSolverAssignment = {
  from: string;
  to: string;
  cost: number;
};

export type QuantumSolverResult = {
  solver: string;
  backend: QuantumSolverBackend;
  feasible: boolean;
  totalCost: number;
  energy: number;
  assignments: QuantumSolverAssignment[];
  route?: string[];
  violationCount: number;
  violations: string[];
  runtimeMs: number;
  explanation: string;
};

function normalizeSolverResult(result: unknown): QuantumSolverResult | undefined {
  if (!result || typeof result !== 'object') {
    return undefined;
  }

  const entry = result as Record<string, unknown>;
  const solver = typeof entry.solver === 'string' ? entry.solver : 'unknown';
  const backend =
    entry.backend === 'quantum_inspired' || entry.backend === 'optional_external_unavailable'
      ? entry.backend
      : 'classical';

  return {
    solver,
    backend,
    feasible: Boolean(entry.feasible),
    totalCost: Number(entry.totalCost ?? Number.POSITIVE_INFINITY),
    energy: Number(entry.energy ?? entry.totalCost ?? Number.POSITIVE_INFINITY),
    assignments: Array.isArray(entry.assignments)
      ? entry.assignments.filter((assignment): assignment is QuantumSolverAssignment => {
          return Boolean(assignment) && typeof assignment === 'object' &&
            typeof (assignment as QuantumSolverAssignment).from === 'string' &&
            typeof (assignment as QuantumSolverAssignment).to === 'string' &&
            typeof (assignment as QuantumSolverAssignment).cost === 'number';
        })
      : [],
    violationCount: Number(entry.violationCount ?? 0),
    violations: Array.isArray(entry.violations)
      ? entry.violations.filter((violation): violation is string => typeof violation === 'string')
      : [],
    runtimeMs: Math.max(0, Number(entry.runtimeMs ?? 0)),
    explanation: typeof entry.explanation === 'string' ? entry.explanation : 'Existing optimization solver result.',
  };
}

function routeCost(problem: QuantumGraphProblem, route: string[]) {
  let total = 0;

  for (let index = 0; index < route.length; index += 1) {
    const from = route[index];
    const to = route[(index + 1) % route.length];
    const fromIndex = problem.nodes.indexOf(from);
    const toIndex = problem.nodes.indexOf(to);
    const cost = problem.costMatrix[fromIndex]?.[toIndex];

    if (!Number.isFinite(cost)) {
      return Number.POSITIVE_INFINITY;
    }

    total += cost;
  }

  return total;
}

export function solveGraphNearestNeighbor(problem: QuantumGraphProblem): QuantumSolverResult {
  const startedAt = Date.now();
  const start = problem.start && problem.nodes.includes(problem.start) ? problem.start : problem.nodes[0];
  const route = [start];
  const remaining = new Set(problem.nodes.filter((node) => node !== start));

  while (remaining.size > 0) {
    const current = route.at(-1) ?? start;
    const currentIndex = problem.nodes.indexOf(current);
    const next = [...remaining].sort((left, right) => {
      const leftCost = problem.costMatrix[currentIndex]?.[problem.nodes.indexOf(left)] ?? Number.POSITIVE_INFINITY;
      const rightCost = problem.costMatrix[currentIndex]?.[problem.nodes.indexOf(right)] ?? Number.POSITIVE_INFINITY;
      return leftCost - rightCost || left.localeCompare(right);
    })[0];

    if (!next) {
      break;
    }

    route.push(next);
    remaining.delete(next);
  }

  const totalCost = routeCost(problem, route);

  return {
    solver: 'nearest_neighbor',
    backend: 'classical',
    feasible: route.length === problem.nodes.length && Number.isFinite(totalCost),
    totalCost,
    energy: totalCost,
    assignments: route.map((from, index) => {
      const to = route[(index + 1) % route.length];
      const fromIndex = problem.nodes.indexOf(from);
      const toIndex = problem.nodes.indexOf(to);
      return {
        from,
        to,
        cost: problem.costMatrix[fromIndex]?.[toIndex] ?? Number.POSITIVE_INFINITY,
      };
    }),
    route,
    violationCount: route.length === problem.nodes.length ? 0 : 1,
    violations: route.length === problem.nodes.length ? [] : ['Route did not visit every node exactly once.'],
    runtimeMs: Date.now() - startedAt,
    explanation: 'Nearest-neighbor baseline selected the cheapest next edge at each step.',
  };
}

export function solveClassicalBaseline(mapping: Extract<QuantumProblemMapping, { status: 'ready' }>): QuantumSolverResult {
  if (mapping.problem.problemType === 'graph') {
    return solveGraphNearestNeighbor(mapping.problem);
  }

  const result = runOptimization({
    action: 'solve',
    problem: mapping.problem,
  }) as { solverResults?: unknown[]; selectedSolution?: unknown };
  const greedy = result.solverResults?.map(normalizeSolverResult).find((entry) => entry?.solver === 'greedy');
  const fallback = normalizeSolverResult(result.selectedSolution);

  return greedy ?? fallback ?? {
    solver: 'greedy',
    backend: 'classical',
    feasible: false,
    totalCost: Number.POSITIVE_INFINITY,
    energy: Number.POSITIVE_INFINITY,
    assignments: [],
    violationCount: 1,
    violations: ['Classical baseline did not return a usable result.'],
    runtimeMs: 0,
    explanation: 'Classical baseline unavailable.',
  };
}

export function calculateGraphRouteCost(problem: QuantumGraphProblem, route: string[]) {
  return routeCost(problem, route);
}
