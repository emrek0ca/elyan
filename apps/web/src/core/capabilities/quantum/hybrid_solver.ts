import { mapProblem, type QuantumProblemMapping } from '@/core/quantum/problem-mapper';
import { refineProblem } from '@/core/problem/refiner';
import { describeObjectiveFunction } from '@/core/problem/objective-engine';
import { solveClassicalBaseline, type QuantumSolverResult } from './classical_solver';
import { solveQuantumInspired } from './quantum_solver';

export type HybridSolverStatus = 'solved' | 'needs_input';
export type HybridSolverStrategy = 'classical_only' | 'hybrid' | 'quantum_biased';

export type HybridSolverMetadata = {
  decision_mode: 'quantum';
  problem_type?: string;
  problem_complexity?: string;
  problem_size?: number;
  estimated_space?: number;
  problem_objective?: string;
  solver_strategy?: HybridSolverStrategy;
  solver_used?: string;
  solver_backend?: string;
  solver_latency_ms: number;
  baseline_cost?: number;
  selected_cost?: number;
  solution_quality: number;
  solver_quality?: number;
  success_rate?: number;
  improvement_ratio: number;
  solver_status: HybridSolverStatus;
  preferred_solver?: string;
  candidate_count?: number;
};

export type HybridSolverRejectedAlternative = {
  solver: string;
  backend: string;
  score: number;
  totalCost: number;
  runtimeMs: number;
  reason: string;
};

export type SolverQualityComparison = {
  solver: string;
  backend: string;
  feasible: boolean;
  valid: boolean;
  constraintViolations: number;
  totalCost: number;
  runtimeMs: number;
  score: number;
  rejected: boolean;
  rejectionReason?: string;
};

export type HybridSolverResult = {
  ok: boolean;
  status: HybridSolverStatus;
  action: 'solve';
  problemType?: string;
  mapping: QuantumProblemMapping;
  missingInputs: string[];
  solverResults: QuantumSolverResult[];
  baselineSolution?: QuantumSolverResult;
  selectedSolution?: QuantumSolverResult;
  bestSolution?: QuantumSolverResult;
  score?: number;
  comparison: SolverQualityComparison[];
  verification: {
    valid: boolean;
    violations: string[];
  };
  whyThisSolution: string;
  tradeOffs: string[];
  rejectedAlternatives: HybridSolverRejectedAlternative[];
  problemIntelligence: {
    type: string;
    complexity: string;
    estimatedSpace: number;
    problemSize: number;
    objective: string;
    objectiveSummary: string;
  };
  markdownReport: string;
  jsonSummary: {
    problemType?: string;
    selectedSolver?: string;
    selectedBackend?: string;
    feasible: boolean;
    totalCost?: number;
    violationCount?: number;
    assignmentCount?: number;
    improvementRatio?: number;
    solutionQuality?: number;
    solverQuality?: number;
    successRate?: number;
    solverStrategy?: HybridSolverStrategy;
    problemComplexity?: string;
    estimatedSpace?: number;
    objectiveSummary?: string;
    status: HybridSolverStatus;
  };
  metadata: HybridSolverMetadata;
};

export type HybridSolverInput = {
  query?: string;
  problem?: Record<string, unknown>;
  preferredSolverId?: string;
  strategy?: HybridSolverStrategy;
};

function round4(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(4)) : 0;
}

function finiteCost(value: number | undefined) {
  return Number.isFinite(value) ? value : undefined;
}

function toSerializableNumber(value: number) {
  return Number.isFinite(value) ? value : Number.MAX_SAFE_INTEGER;
}

function serializeResult(result: QuantumSolverResult): QuantumSolverResult {
  return {
    ...result,
    totalCost: toSerializableNumber(result.totalCost),
    energy: toSerializableNumber(result.energy),
    assignments: result.assignments.map((assignment) => ({
      ...assignment,
      cost: toSerializableNumber(assignment.cost),
    })),
  };
}

function unique(values: string[]) {
  return [...new Set(values.filter((value) => value.trim().length > 0))];
}

function rankResults(results: QuantumSolverResult[]) {
  return [...results].sort((left, right) => {
    if (left.feasible !== right.feasible) {
      return left.feasible ? -1 : 1;
    }

    if (left.violationCount !== right.violationCount) {
      return left.violationCount - right.violationCount;
    }

    if (left.totalCost !== right.totalCost) {
      return left.totalCost - right.totalCost;
    }

    if (left.energy !== right.energy) {
      return left.energy - right.energy;
    }

    return left.runtimeMs - right.runtimeMs || left.solver.localeCompare(right.solver);
  });
}

function computeImprovementRatio(baselineCost: number | undefined, selectedCost: number | undefined) {
  if (!Number.isFinite(baselineCost) || !Number.isFinite(selectedCost) || baselineCost === undefined || selectedCost === undefined) {
    return 0;
  }

  if (baselineCost <= 0 || selectedCost >= baselineCost) {
    return 0;
  }

  return round4((baselineCost - selectedCost) / baselineCost);
}

function computeSolutionQuality(selected: QuantumSolverResult | undefined, improvementRatio: number) {
  if (!selected) {
    return 0;
  }

  if (!selected.feasible) {
    return Math.max(0, round4(0.25 - selected.violationCount * 0.05));
  }

  return Math.min(1, round4(0.72 + Math.min(0.22, improvementRatio) + Math.max(0, 0.06 - selected.runtimeMs / 100_000)));
}

function verifyResult(
  mapping: Extract<QuantumProblemMapping, { status: 'ready' }>,
  result: QuantumSolverResult | undefined
) {
  if (!result) {
    return {
      valid: false,
      violations: ['No solver result was available.'],
    };
  }

  const violations = [...result.violations];

  if (mapping.problem.problemType === 'graph') {
    const route = result.route ?? result.assignments.map((assignment) => assignment.from);
    const visited = new Set(route);

    if (route.length !== mapping.problem.nodes.length || visited.size !== mapping.problem.nodes.length) {
      violations.push('Route must visit every node exactly once.');
    }

    for (let index = 0; index < route.length; index += 1) {
      const from = route[index];
      const to = route[(index + 1) % route.length];
      const fromIndex = mapping.problem.nodes.indexOf(from);
      const toIndex = mapping.problem.nodes.indexOf(to);
      if (!Number.isFinite(mapping.problem.costMatrix[fromIndex]?.[toIndex])) {
        violations.push(`Missing edge cost for ${from} -> ${to}.`);
      }
    }
  } else if (mapping.problem.problemType === 'resource_allocation') {
    const locations = mapping.problem.locations ?? [];
    const resources = mapping.problem.resources ?? [];

    for (const location of locations) {
      const count = result.assignments.filter((assignment) => assignment.to === location.id).length;
      if (count !== 1) {
        violations.push(`${location.id} allocation count ${count}, expected 1.`);
      }
    }

    for (const resource of resources) {
      const count = result.assignments.filter((assignment) => assignment.from === resource.id).length;
      if (count > (resource.capacity ?? 1)) {
        violations.push(`${resource.id} exceeds capacity.`);
      }
    }
  } else {
    const tasks = mapping.problem.tasks ?? [];
    const workers = mapping.problem.workers ?? [];

    for (const task of tasks) {
      const count = result.assignments.filter((assignment) => assignment.to === task.id).length;
      if (count !== 1) {
        violations.push(`${task.id} assignment count ${count}, expected 1.`);
      }
    }

    for (const worker of workers) {
      const count = result.assignments.filter((assignment) => assignment.from === worker.id).length;
      if (count > (worker.capacity ?? 1)) {
        violations.push(`${worker.id} exceeds capacity.`);
      }
    }
  }

  const normalizedViolations = unique(violations);
  return {
    valid: result.feasible && normalizedViolations.length === 0,
    violations: normalizedViolations,
  };
}

function scoreSolverResult(
  mapping: Extract<QuantumProblemMapping, { status: 'ready' }>,
  result: QuantumSolverResult,
  costRange: { best: number; worst: number }
): SolverQualityComparison {
  const verification = verifyResult(mapping, result);
  const finiteCostValue = finiteCost(result.totalCost) ?? Number.MAX_SAFE_INTEGER;
  const costSpan = Math.max(1, costRange.worst - costRange.best);
  const costScore = Number.isFinite(result.totalCost)
    ? 1 - Math.min(1, Math.max(0, finiteCostValue - costRange.best) / costSpan)
    : 0;
  const feasibilityScore = verification.valid ? 0.55 : result.feasible ? 0.25 : 0;
  const violationPenalty = Math.min(0.45, verification.violations.length * 0.12);
  const runtimePenalty = Math.min(0.12, result.runtimeMs / 50_000);
  const score = Math.max(0, round4(feasibilityScore + costScore * 0.38 - violationPenalty - runtimePenalty));

  return {
    solver: result.solver,
    backend: result.backend,
    feasible: result.feasible,
    valid: verification.valid,
    constraintViolations: verification.violations.length,
    totalCost: toSerializableNumber(result.totalCost),
    runtimeMs: result.runtimeMs,
    score,
    rejected: !verification.valid,
    rejectionReason: verification.valid ? undefined : verification.violations.join('; '),
  };
}

function buildQualityComparison(
  mapping: Extract<QuantumProblemMapping, { status: 'ready' }>,
  results: QuantumSolverResult[],
  strategy: HybridSolverStrategy
) {
  const finiteCosts = results
    .map((result) => finiteCost(result.totalCost))
    .filter((value): value is number => typeof value === 'number');
  const costRange = {
    best: finiteCosts.length > 0 ? Math.min(...finiteCosts) : 0,
    worst: finiteCosts.length > 0 ? Math.max(...finiteCosts) : 1,
  };

  return results
    .map((result) => scoreSolverResult(mapping, result, costRange))
    .map((entry) => ({
      ...entry,
      score:
        strategy === 'quantum_biased' && entry.backend === 'quantum_inspired'
          ? round4(Math.min(1, entry.score + 0.08))
          : entry.score,
    }))
    .sort((left, right) => right.score - left.score || left.totalCost - right.totalCost || left.runtimeMs - right.runtimeMs);
}

function buildNeedsInputReport(
  mapping: Extract<QuantumProblemMapping, { status: 'needs_input' }>,
  refinementMessage?: string,
  missingFields?: string[]
) {
  const fields = missingFields ?? mapping.missing;
  return [
    '## Quantum Optimization Input Required',
    '',
    `Detected problem type: ${mapping.type}`,
    '',
    'I can solve this with Elyan’s deterministic hybrid optimization lane, but the problem is not fully specified.',
    '',
    refinementMessage ? `Clarification: ${refinementMessage}` : '',
    'Missing inputs:',
    ...fields.map((field) => `- ${field}`),
    '',
    'Provide structured JSON with real entities and numeric costs. No fake optimization was run.',
  ].join('\n');
}

function summarizeAssignments(selected: QuantumSolverResult) {
  if (selected.route?.length) {
    return [`Route: ${selected.route.join(' -> ')} -> ${selected.route[0]}`];
  }

  return selected.assignments.map((assignment) => `- ${assignment.from} -> ${assignment.to} (cost ${assignment.cost})`);
}

function buildSolvedReport(input: {
  mapping: Extract<QuantumProblemMapping, { status: 'ready' }>;
  baseline: QuantumSolverResult;
  selected: QuantumSolverResult;
  results: QuantumSolverResult[];
  comparison: SolverQualityComparison[];
  verification: { valid: boolean; violations: string[] };
  improvementRatio: number;
  solutionQuality: number;
  strategy: HybridSolverStrategy;
  whyThisSolution: string;
  tradeOffs: string[];
  rejectedAlternatives: HybridSolverRejectedAlternative[];
  problemIntelligence: HybridSolverResult['problemIntelligence'];
}) {
  return [
    '## Quantum Hybrid Optimization Report',
    '',
    `Problem family: ${input.problemIntelligence.type}`,
    `Problem complexity: ${input.problemIntelligence.complexity} (estimated space: ${input.problemIntelligence.estimatedSpace})`,
    `Objective: ${input.problemIntelligence.objectiveSummary}`,
    `Solver strategy: ${input.strategy}`,
    `Problem type: ${input.mapping.type}`,
    `Selected solver: ${input.selected.solver} (${input.selected.backend})`,
    `Feasible: ${input.selected.feasible ? 'yes' : 'no'}`,
    `Selected cost: ${finiteCost(input.selected.totalCost) ?? 'unavailable'}`,
    `Baseline cost: ${finiteCost(input.baseline.totalCost) ?? 'unavailable'}`,
    `Improvement ratio: ${input.improvementRatio}`,
    `Solution quality: ${input.solutionQuality}`,
    `Verification: ${input.verification.valid ? 'passed' : 'failed'}`,
    '',
    '## Why This Solution',
    input.whyThisSolution,
    '',
    '## Trade-offs',
    ...(input.tradeOffs.length > 0
      ? input.tradeOffs.map((entry) => `- ${entry}`)
      : ['- No explicit trade-offs were required for this run.']),
    '',
    '## Rejected Alternatives',
    ...(input.rejectedAlternatives.length > 0
      ? input.rejectedAlternatives.map(
          (entry) =>
            `- ${entry.solver} [${entry.backend}] score=${entry.score}, cost=${finiteCost(entry.totalCost) ?? 'unavailable'}, runtime_ms=${entry.runtimeMs}: ${entry.reason}`
        )
      : ['- No alternatives were rejected.']),
    '',
    '## Solver Comparison',
    ...input.comparison.map((result) =>
      `- ${result.solver} [${result.backend}]: score=${result.score}, cost=${finiteCost(result.totalCost) ?? 'unavailable'}, valid=${result.valid}, violations=${result.constraintViolations}, latency_ms=${result.runtimeMs}`
    ),
    '',
    '## Recommended Solution',
    ...summarizeAssignments(input.selected),
    '',
    'No external quantum hardware was used. This run used deterministic classical and quantum-inspired approximation paths only.',
  ].join('\n');
}

function selectResult(
  results: QuantumSolverResult[],
  comparison: SolverQualityComparison[],
  preferredSolverId?: string,
  strategy: HybridSolverStrategy = 'hybrid'
) {
  if (strategy === 'classical_only') {
    return results[0];
  }

  const ranked = comparison.filter((entry) => entry.valid && !entry.rejected);
  const top = ranked[0];
  const preferred = preferredSolverId
    ? ranked.find((result) => result.solver === preferredSolverId && top && result.score >= top.score - 0.02)
    : undefined;

  const selectedScore = preferred ?? top;
  return selectedScore
    ? results.find((result) => result.solver === selectedScore.solver && result.backend === selectedScore.backend)
    : undefined;
}

export function solveHybridOptimization(input: HybridSolverInput): HybridSolverResult {
  const startedAt = Date.now();
  const refinement = refineProblem(input.problem ?? input.query ?? '');
  const strategy: HybridSolverStrategy = input.strategy ?? (refinement.complexity.complexity === 'high'
    ? 'quantum_biased'
    : refinement.complexity.complexity === 'medium'
      ? 'hybrid'
      : 'classical_only');

  if (refinement.status === 'needs_input') {
    const mapping = mapProblem(input.problem ?? input.query ?? '');
    const latencyMs = Date.now() - startedAt;
    const objectiveSummary = 'Optimization objective is unavailable until the problem is fully specified.';

    return {
      ok: false,
      status: 'needs_input',
      action: 'solve',
      problemType: refinement.type,
      mapping,
      missingInputs: refinement.missing,
      solverResults: [],
      baselineSolution: undefined,
      selectedSolution: undefined,
      bestSolution: undefined,
      score: 0,
      comparison: [],
      verification: {
        valid: false,
        violations: refinement.missing.map((field) => `Missing input: ${field}`),
      },
      whyThisSolution: 'The problem is incomplete, so no solver run was selected.',
      tradeOffs: ['No solver comparison was executed until the required inputs are provided.'],
      rejectedAlternatives: [],
      problemIntelligence: {
        type: refinement.type,
        complexity: refinement.complexity.complexity,
        estimatedSpace: refinement.complexity.estimated_space,
        problemSize: refinement.complexity.problemSize,
        objective: 'unavailable',
        objectiveSummary,
      },
      markdownReport: buildNeedsInputReport(mapping as Extract<QuantumProblemMapping, { status: 'needs_input' }>, refinement.summary, refinement.missing),
      jsonSummary: {
        problemType: refinement.type,
        selectedSolver: undefined,
        selectedBackend: undefined,
        feasible: false,
        improvementRatio: 0,
        solutionQuality: 0,
        solverQuality: 0,
        successRate: 0,
        solverStrategy: strategy,
        problemComplexity: refinement.complexity.complexity,
        estimatedSpace: refinement.complexity.estimated_space,
        objectiveSummary,
        status: 'needs_input',
      },
      metadata: {
        decision_mode: 'quantum',
        problem_type: refinement.type,
        problem_complexity: refinement.complexity.complexity,
        problem_size: refinement.complexity.problemSize,
        estimated_space: refinement.complexity.estimated_space,
        problem_objective: objectiveSummary,
        solver_strategy: strategy,
        solver_latency_ms: latencyMs,
        baseline_cost: undefined,
        selected_cost: undefined,
        solution_quality: 0,
        solver_quality: 0,
        success_rate: 0,
        improvement_ratio: 0,
        solver_status: 'needs_input',
        preferred_solver: input.preferredSolverId,
        candidate_count: 0,
      },
    };
  }

  const mapping = mapProblem(refinement.normalizedProblem);

  if (mapping.status === 'needs_input') {
    const latencyMs = Date.now() - startedAt;
    const objectiveSummary = describeObjectiveFunction(refinement.structuredModel.objective);
    return {
      ok: false,
      status: 'needs_input',
      action: 'solve',
      problemType: refinement.type,
      mapping,
      missingInputs: mapping.missing,
      solverResults: [],
      baselineSolution: undefined,
      selectedSolution: undefined,
      bestSolution: undefined,
      score: 0,
      comparison: [],
      verification: {
        valid: false,
        violations: mapping.missing.map((field) => `Missing input: ${field}`),
      },
      whyThisSolution: 'The problem mapping could not be completed, so no solver run was selected.',
      tradeOffs: ['No solver comparison was executed until the required inputs are available.'],
      rejectedAlternatives: [],
      problemIntelligence: {
        type: refinement.type,
        complexity: refinement.complexity.complexity,
        estimatedSpace: refinement.complexity.estimated_space,
        problemSize: refinement.complexity.problemSize,
        objective: 'weighted',
        objectiveSummary,
      },
      markdownReport: buildNeedsInputReport(mapping, refinement.summary, mapping.missing),
      jsonSummary: {
        problemType: refinement.type,
        selectedSolver: undefined,
        selectedBackend: undefined,
        feasible: false,
        improvementRatio: 0,
        solutionQuality: 0,
        solverQuality: 0,
        successRate: 0,
        solverStrategy: strategy,
        problemComplexity: refinement.complexity.complexity,
        estimatedSpace: refinement.complexity.estimated_space,
        objectiveSummary,
        status: 'needs_input',
      },
      metadata: {
        decision_mode: 'quantum',
        problem_type: refinement.type,
        problem_complexity: refinement.complexity.complexity,
        problem_size: refinement.complexity.problemSize,
        estimated_space: refinement.complexity.estimated_space,
        problem_objective: objectiveSummary,
        solver_strategy: strategy,
        solver_latency_ms: latencyMs,
        baseline_cost: undefined,
        selected_cost: undefined,
        solution_quality: 0,
        solver_quality: 0,
        success_rate: 0,
        improvement_ratio: 0,
        solver_status: 'needs_input',
        preferred_solver: input.preferredSolverId,
        candidate_count: 0,
      },
    };
  }

  const baseline = solveClassicalBaseline(mapping);
  const quantumResults = strategy === 'classical_only' ? [] : solveQuantumInspired(mapping);
  const solverResults = strategy === 'classical_only' ? [baseline] : [baseline, ...quantumResults];
  const comparison = buildQualityComparison(mapping, solverResults, strategy);
  const selected = selectResult(solverResults, comparison, input.preferredSolverId, strategy);
  const verification = verifyResult(mapping, selected);
  const latencyMs = Date.now() - startedAt;
  const baselineCost = finiteCost(baseline.totalCost);
  const selectedCost = finiteCost(selected?.totalCost);
  const improvementRatio = computeImprovementRatio(baselineCost, selectedCost);
  const solutionQuality = computeSolutionQuality(selected, improvementRatio);
  const selectedComparison = selected
    ? comparison.find((entry) => entry.solver === selected.solver && entry.backend === selected.backend)
    : undefined;
  const solverQuality = selectedComparison?.score ?? 0;
  const successRate = solverResults.length > 0
    ? round4(comparison.filter((entry) => entry.valid).length / solverResults.length)
    : 0;
  const objectiveSummary = describeObjectiveFunction(refinement.structuredModel.objective);
  const problemIntelligence = {
    type: refinement.type,
    complexity: refinement.complexity.complexity,
    estimatedSpace: refinement.complexity.estimated_space,
    problemSize: refinement.complexity.problemSize,
    objective: 'weighted',
    objectiveSummary,
  };
  const whyThisSolution = selected
    ? selectedComparison
      ? `Selected ${selected.solver} because it was feasible and achieved the best comparison score (${selectedComparison.score.toFixed(2)}).`
      : `Selected ${selected.solver} because it was the only feasible candidate.`
    : 'No feasible solver result was available.';
  const tradeOffs = selected
    ? [
        selected.backend === 'quantum_inspired'
          ? 'Accepted a small runtime increase to reduce optimization cost.'
          : 'Used a classical baseline to minimize runtime overhead.',
        strategy === 'quantum_biased'
          ? 'Applied a quantum bias to favor quantum-inspired candidates when scores were close.'
          : 'Kept solver selection deterministic and conservative.',
      ]
    : ['No feasible solver result was available to compare trade-offs.'];
  const rejectedAlternatives = comparison
    .filter((entry) => !selected || entry.solver !== selected.solver || entry.backend !== selected.backend)
    .map((entry) => ({
      solver: entry.solver,
      backend: entry.backend,
      score: entry.score,
      totalCost: entry.totalCost,
      runtimeMs: entry.runtimeMs,
      reason: entry.rejected
        ? entry.rejectionReason ?? 'Rejected by verification checks.'
        : 'Ranked below the selected solution.',
    }));
  const markdownReport = selected
    ? buildSolvedReport({
        mapping,
        baseline,
        selected,
        results: rankResults(solverResults),
        comparison,
        verification,
        improvementRatio,
        solutionQuality,
        strategy,
        whyThisSolution,
        tradeOffs,
        rejectedAlternatives,
        problemIntelligence,
      })
    : buildNeedsInputReport({
        status: 'needs_input',
        type: mapping.type,
        source: mapping.source,
        missing: ['solver result'],
        notes: ['No solver returned a selectable result.'],
      });

  return {
    ok: Boolean(selected?.feasible),
    status: 'solved',
    action: 'solve',
    problemType: refinement.type,
    mapping,
    missingInputs: [],
    solverResults: rankResults(solverResults).map(serializeResult),
    baselineSolution: serializeResult(baseline),
    selectedSolution: selected ? serializeResult(selected) : undefined,
    bestSolution: selected ? serializeResult(selected) : undefined,
    score: solverQuality,
    comparison,
    verification,
    whyThisSolution,
    tradeOffs,
    rejectedAlternatives,
    problemIntelligence,
    markdownReport,
    jsonSummary: {
      problemType: refinement.type,
      selectedSolver: selected?.solver,
      selectedBackend: selected?.backend,
      feasible: Boolean(selected?.feasible),
      totalCost: selectedCost,
      violationCount: selected?.violationCount,
      assignmentCount: selected?.assignments.length,
      improvementRatio,
      solutionQuality,
      solverQuality,
      successRate,
      solverStrategy: strategy,
      problemComplexity: refinement.complexity.complexity,
      estimatedSpace: refinement.complexity.estimated_space,
      objectiveSummary,
      status: 'solved',
    },
    metadata: {
      decision_mode: 'quantum',
      problem_type: refinement.type,
      problem_complexity: refinement.complexity.complexity,
      problem_size: refinement.complexity.problemSize,
      estimated_space: refinement.complexity.estimated_space,
      problem_objective: objectiveSummary,
      solver_strategy: strategy,
      solver_used: selected?.solver,
      solver_backend: selected?.backend,
      solver_latency_ms: latencyMs,
      baseline_cost: baselineCost,
      selected_cost: selectedCost,
      solution_quality: solutionQuality,
      solver_quality: solverQuality,
      success_rate: successRate,
      improvement_ratio: improvementRatio,
      solver_status: verification.valid ? 'solved' : 'needs_input',
      preferred_solver: input.preferredSolverId,
      candidate_count: solverResults.length,
    },
  };
}
