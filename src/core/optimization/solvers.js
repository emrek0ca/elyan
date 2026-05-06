/* eslint-disable @typescript-eslint/no-require-imports */
const { evaluateQubo, variableId } = require('./qubo.js');

function createSeededRandom(seed = 42) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function decodeAssignments(problem, qubo, bits) {
  return qubo.variables
    .filter((variable) => bits[variable.id])
    .map((variable) => ({
      from: variable.leftId,
      to: variable.rightId,
      cost: problem.costs?.[variable.leftId]?.[variable.rightId] ?? 999,
    }));
}

function evaluateSolution(problem, assignments) {
  const totalCost = assignments.reduce((total, item) => total + item.cost, 0);
  const violations = [];

  if (problem.problemType === 'resource_allocation') {
    for (const location of problem.locations) {
      const count = assignments.filter((item) => item.to === location.id).length;
      if (count !== 1) violations.push(`${location.id} allocation count ${count}, expected 1`);
    }
    for (const resource of problem.resources) {
      const count = assignments.filter((item) => item.from === resource.id).length;
      if (count > (resource.capacity ?? 1)) violations.push(`${resource.id} exceeds capacity`);
    }
  } else {
    for (const task of problem.tasks) {
      const count = assignments.filter((item) => item.to === task.id).length;
      if (count !== 1) violations.push(`${task.id} assignment count ${count}, expected 1`);
      const assigned = assignments.find((item) => item.to === task.id);
      const worker = assigned ? problem.workers.find((entry) => entry.id === assigned.from) : undefined;
      if (task.requiredSkill && worker && !worker.skills?.includes(task.requiredSkill)) {
        violations.push(`${worker.id} lacks required skill ${task.requiredSkill} for ${task.id}`);
      }
    }
    for (const worker of problem.workers) {
      const count = assignments.filter((item) => item.from === worker.id).length;
      if (count > (worker.capacity ?? 1)) violations.push(`${worker.id} exceeds capacity`);
    }
  }

  return {
    totalCost,
    feasible: violations.length === 0,
    violationCount: violations.length,
    violations,
  };
}

function buildSolverResult(solver, backend, problem, qubo, bits, explanation, runtimeMs = 0) {
  const assignments = decodeAssignments(problem, qubo, bits);
  const evaluation = evaluateSolution(problem, assignments);

  return {
    solver,
    backend,
    feasible: evaluation.feasible,
    totalCost: evaluation.totalCost,
    energy: evaluateQubo(qubo, bits),
    assignments,
    violationCount: evaluation.violationCount,
    violations: evaluation.violations,
    runtimeMs,
    explanation,
  };
}

function greedySolve(problem, qubo) {
  const assignments = [];
  const remaining = new Map();
  const leftItems = problem.problemType === 'resource_allocation' ? problem.resources : problem.workers;
  const rightItems = problem.problemType === 'resource_allocation' ? problem.locations : problem.tasks;
  for (const item of leftItems) remaining.set(item.id, item.capacity ?? 1);

  for (const right of rightItems) {
    const ranked = leftItems
      .map((left) => ({
        left,
        cost: problem.costs?.[left.id]?.[right.id] ?? 999,
        skillOk:
          problem.problemType === 'resource_allocation' ||
          !right.requiredSkill ||
          left.skills?.includes(right.requiredSkill),
      }))
      .filter((candidate) => (remaining.get(candidate.left.id) ?? 0) > 0)
      .sort((a, b) => (a.skillOk === b.skillOk ? a.cost - b.cost : a.skillOk ? -1 : 1));
    const selected = ranked[0];
    if (selected) {
      assignments.push({ from: selected.left.id, to: right.id, cost: selected.cost });
      remaining.set(selected.left.id, (remaining.get(selected.left.id) ?? 0) - 1);
    }
  }

  const bits = Object.fromEntries(qubo.variables.map((variable) => [variable.id, false]));
  for (const assignment of assignments) {
    bits[variableId(assignment.from, assignment.to)] = true;
  }

  return buildSolverResult('greedy', 'classical', problem, qubo, bits, 'Greedy selected the cheapest feasible local step at each decision.');
}

function bruteForceQuboSolve(problem, qubo) {
  if (qubo.variables.length > 20) {
    return {
      solver: 'qubo_bruteforce',
      backend: 'optional_external_unavailable',
      feasible: false,
      totalCost: Number.POSITIVE_INFINITY,
      energy: Number.POSITIVE_INFINITY,
      assignments: [],
      violationCount: 1,
      violations: ['Brute-force QUBO fallback is limited to 20 binary variables.'],
      runtimeMs: 0,
      explanation: 'Problem is too large for the built-in exact fallback.',
    };
  }

  const started = Date.now();
  let bestBits = {};
  let bestEnergy = Number.POSITIVE_INFINITY;
  const count = 2 ** qubo.variables.length;

  for (let mask = 0; mask < count; mask += 1) {
    const bits = {};
    for (let index = 0; index < qubo.variables.length; index += 1) {
      bits[qubo.variables[index].id] = Boolean(mask & (1 << index));
    }
    const energy = evaluateQubo(qubo, bits);
    if (energy < bestEnergy) {
      bestEnergy = energy;
      bestBits = bits;
    }
  }

  return buildSolverResult(
    'qubo_bruteforce',
    'quantum_inspired',
    problem,
    qubo,
    bestBits,
    'Exact brute-force fallback minimized the QUBO energy for this small binary model.',
    Date.now() - started
  );
}

function simulatedAnnealingSolve(problem, qubo) {
  const started = Date.now();
  const random = createSeededRandom(1337);
  let bits = Object.fromEntries(qubo.variables.map((variable) => [variable.id, random() > 0.5]));
  let energy = evaluateQubo(qubo, bits);
  let bestBits = { ...bits };
  let bestEnergy = energy;
  const iterations = 1500;

  for (let step = 0; step < iterations; step += 1) {
    const temperature = Math.max(0.01, 6 * (1 - step / iterations));
    const variable = qubo.variables[Math.floor(random() * qubo.variables.length)];
    const candidate = { ...bits, [variable.id]: !bits[variable.id] };
    const candidateEnergy = evaluateQubo(qubo, candidate);
    const delta = candidateEnergy - energy;
    if (delta < 0 || Math.exp(-delta / temperature) > random()) {
      bits = candidate;
      energy = candidateEnergy;
      if (energy < bestEnergy) {
        bestBits = { ...bits };
        bestEnergy = energy;
      }
    }
  }

  return buildSolverResult(
    'simulated_annealing',
    'quantum_inspired',
    problem,
    qubo,
    bestBits,
    'Simulated annealing searched the QUBO landscape with a deterministic seed.',
    Date.now() - started
  );
}

function solveWithBuiltInSolvers(problem, qubo) {
  return [
    greedySolve(problem, qubo),
    simulatedAnnealingSolve(problem, qubo),
    bruteForceQuboSolve(problem, qubo),
  ];
}

function rankSolverResults(results) {
  return [...results].sort((left, right) => {
    if (left.feasible !== right.feasible) return left.feasible ? -1 : 1;
    if (left.violationCount !== right.violationCount) return left.violationCount - right.violationCount;
    if (left.totalCost !== right.totalCost) return left.totalCost - right.totalCost;
    return left.energy - right.energy;
  });
}

function selectBestResult(results) {
  return rankSolverResults(results)[0];
}

module.exports = {
  rankSolverResults,
  selectBestResult,
  solveWithBuiltInSolvers,
};
