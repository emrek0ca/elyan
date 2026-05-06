import { runOptimization } from '@/core/optimization';
import type { QuantumGraphProblem, QuantumProblemMapping } from '@/core/quantum/problem-mapper';
import {
  calculateGraphRouteCost,
  solveGraphNearestNeighbor,
  type QuantumSolverResult,
} from './classical_solver';

function createSeededRandom(seed = 20260505) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function normalizeSolverResult(result: unknown): QuantumSolverResult | undefined {
  if (!result || typeof result !== 'object') {
    return undefined;
  }

  const entry = result as Record<string, unknown>;
  if (entry.backend !== 'quantum_inspired') {
    return undefined;
  }

  return {
    solver: typeof entry.solver === 'string' ? entry.solver : 'quantum_inspired',
    backend: 'quantum_inspired',
    feasible: Boolean(entry.feasible),
    totalCost: Number(entry.totalCost ?? Number.POSITIVE_INFINITY),
    energy: Number(entry.energy ?? entry.totalCost ?? Number.POSITIVE_INFINITY),
    assignments: Array.isArray(entry.assignments)
      ? entry.assignments.filter((assignment): assignment is QuantumSolverResult['assignments'][number] => {
          return Boolean(assignment) && typeof assignment === 'object' &&
            typeof (assignment as QuantumSolverResult['assignments'][number]).from === 'string' &&
            typeof (assignment as QuantumSolverResult['assignments'][number]).to === 'string' &&
            typeof (assignment as QuantumSolverResult['assignments'][number]).cost === 'number';
        })
      : [],
    violationCount: Number(entry.violationCount ?? 0),
    violations: Array.isArray(entry.violations)
      ? entry.violations.filter((violation): violation is string => typeof violation === 'string')
      : [],
    runtimeMs: Math.max(0, Number(entry.runtimeMs ?? 0)),
    explanation: typeof entry.explanation === 'string' ? entry.explanation : 'Quantum-inspired built-in solver result.',
  };
}

function buildGraphResult(
  solver: string,
  problem: QuantumGraphProblem,
  route: string[],
  runtimeMs: number,
  explanation: string
): QuantumSolverResult {
  const totalCost = calculateGraphRouteCost(problem, route);

  return {
    solver,
    backend: 'quantum_inspired',
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
    runtimeMs,
    explanation,
  };
}

function swapTwo(route: string[], leftIndex: number, rightIndex: number) {
  const next = [...route];
  const temp = next[leftIndex];
  next[leftIndex] = next[rightIndex];
  next[rightIndex] = temp;
  return next;
}

export function solveGraphSimulatedAnnealing(problem: QuantumGraphProblem): QuantumSolverResult {
  const startedAt = Date.now();
  const random = createSeededRandom();
  const start = problem.start && problem.nodes.includes(problem.start) ? problem.start : problem.nodes[0];
  let route = [start, ...problem.nodes.filter((node) => node !== start)];
  let cost = calculateGraphRouteCost(problem, route);
  let bestRoute = [...route];
  let bestCost = cost;
  const movableCount = Math.max(0, route.length - 1);
  const iterations = Math.max(200, Math.min(2_000, problem.nodes.length * 250));

  for (let step = 0; step < iterations && movableCount > 1; step += 1) {
    const temperature = Math.max(0.01, 8 * (1 - step / iterations));
    const left = 1 + Math.floor(random() * movableCount);
    const right = 1 + Math.floor(random() * movableCount);
    if (left === right) {
      continue;
    }

    const candidate = swapTwo(route, left, right);
    const candidateCost = calculateGraphRouteCost(problem, candidate);
    const delta = candidateCost - cost;
    if (delta < 0 || Math.exp(-delta / temperature) > random()) {
      route = candidate;
      cost = candidateCost;

      if (cost < bestCost) {
        bestRoute = [...route];
        bestCost = cost;
      }
    }
  }

  return buildGraphResult(
    'simulated_annealing',
    problem,
    bestRoute,
    Date.now() - startedAt,
    'Deterministic simulated annealing searched route permutations without external quantum hardware.'
  );
}

export function solveGraphQaoaStyleLocalApproximation(problem: QuantumGraphProblem): QuantumSolverResult {
  const startedAt = Date.now();
  let route = solveGraphNearestNeighbor(problem).route ?? [...problem.nodes];
  let improved = true;

  while (improved) {
    improved = false;

    for (let left = 1; left < route.length - 1; left += 1) {
      for (let right = left + 1; right < route.length; right += 1) {
        const candidate = [
          ...route.slice(0, left),
          ...route.slice(left, right + 1).reverse(),
          ...route.slice(right + 1),
        ];

        if (calculateGraphRouteCost(problem, candidate) < calculateGraphRouteCost(problem, route)) {
          route = candidate;
          improved = true;
        }
      }
    }
  }

  return buildGraphResult(
    'qaoa_style_local_approximation',
    problem,
    route,
    Date.now() - startedAt,
    'QAOA-style local approximation label: deterministic local search over the QUBO-like route landscape; no hardware claim.'
  );
}

export function solveQuantumInspired(mapping: Extract<QuantumProblemMapping, { status: 'ready' }>): QuantumSolverResult[] {
  if (mapping.problem.problemType === 'graph') {
    return [
      solveGraphSimulatedAnnealing(mapping.problem),
      solveGraphQaoaStyleLocalApproximation(mapping.problem),
    ];
  }

  const result = runOptimization({
    action: 'solve',
    problem: mapping.problem,
  }) as { solverResults?: unknown[] };
  const quantumResults = (result.solverResults ?? [])
    .map(normalizeSolverResult)
    .filter((entry): entry is QuantumSolverResult => Boolean(entry));

  return quantumResults.length > 0
    ? quantumResults
    : [
        {
          solver: 'quantum_inspired_unavailable',
          backend: 'optional_external_unavailable',
          feasible: false,
          totalCost: Number.POSITIVE_INFINITY,
          energy: Number.POSITIVE_INFINITY,
          assignments: [],
          violationCount: 1,
          violations: ['No quantum-inspired fallback returned a usable result.'],
          runtimeMs: 0,
          explanation: 'Quantum-inspired fallback unavailable.',
        },
      ];
}
