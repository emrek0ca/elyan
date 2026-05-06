import { env } from '@/lib/env';
import { classifyProblem } from '@/core/problem/classifier';
import { mapProblem, type QuantumProblemMapping } from '@/core/quantum/problem-mapper';
import { calculateGraphRouteCost, solveClassicalBaseline, type QuantumSolverResult } from '@/core/capabilities/quantum/classical_solver';
import { solveHybridOptimization, type HybridSolverResult, type HybridSolverStrategy } from '@/core/capabilities/quantum/hybrid_solver';
import { scenarioDefinitions, type ScenarioDefinition, type ScenarioId, type ScenarioOutputStructure, type ScenarioType } from './definitions';

export type ScenarioResolutionMode = 'standard' | 'demo' | 'competition';

export type ScenarioMatch = {
  matched: boolean;
  scenarioId?: ScenarioId;
  label?: string;
  type?: ScenarioType;
  confidence: number;
  reason: string;
  mode: ScenarioResolutionMode;
  demoRequested: boolean;
  strict: boolean;
};

export type ScenarioValidationResult = {
  ok: boolean;
  missing: string[];
  errors: string[];
};

export type ScenarioResolutionReady = {
  status: 'ready';
  scenario: ScenarioDefinition;
  match: ScenarioMatch;
  mode: ScenarioResolutionMode;
  input: Record<string, unknown>;
  validation: ScenarioValidationResult;
  usesExampleInput: boolean;
};

export type ScenarioResolutionNeedsInput = {
  status: 'needs_input';
  scenario?: ScenarioDefinition;
  match: ScenarioMatch;
  mode: ScenarioResolutionMode;
  required: string[];
  missing: string[];
  validation: ScenarioValidationResult;
  reason: string;
  usesExampleInput: boolean;
};

export type ScenarioResolution = ScenarioResolutionReady | ScenarioResolutionNeedsInput;

export type ScenarioBenchmarkEntry = {
  solver: string;
  backend: string;
  feasible: boolean;
  totalCost: number;
  runtimeMs: number;
  violationCount: number;
  constraintSatisfaction: number;
  explanation: string;
};

export type ScenarioBenchmarkReady = {
  status: 'ready';
  scenario: ScenarioDefinition;
  match: ScenarioMatch;
  mode: ScenarioResolutionMode;
  validation: ScenarioValidationResult;
  input: Record<string, unknown>;
  mapping: Extract<QuantumProblemMapping, { status: 'ready' }>;
  baseline: ScenarioBenchmarkEntry;
  classical: ScenarioBenchmarkEntry;
  hybrid: ScenarioBenchmarkEntry;
  improvementPercent: number;
  efficiencyGain: number;
  constraintSatisfaction: number;
  hybridResult: HybridSolverResult;
  markdownReport: string;
  expectedOutputStructure: ScenarioOutputStructure;
};

export type ScenarioBenchmarkNeedsInput = {
  status: 'needs_input';
  scenario?: ScenarioDefinition;
  match: ScenarioMatch;
  mode: ScenarioResolutionMode;
  validation: ScenarioValidationResult;
  required: string[];
  missing: string[];
  reason: string;
  expectedOutputStructure?: ScenarioOutputStructure;
};

export type ScenarioBenchmarkResult = ScenarioBenchmarkReady | ScenarioBenchmarkNeedsInput;

function normalizeText(value: string) {
  return value.replace(/\s+/g, ' ').trim().toLowerCase();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function scorePatterns(text: string, patterns: RegExp[]) {
  const evidence: string[] = [];
  let score = 0;

  for (const pattern of patterns) {
    if (!pattern.test(text)) {
      continue;
    }

    score += 1;
    evidence.push(pattern.source);
  }

  return { score, evidence };
}

function readRawInput(input: string | Record<string, unknown> | undefined) {
  if (input === undefined) {
    return undefined;
  }

  if (typeof input !== 'string') {
    return input;
  }

  const trimmed = input.trim();
  if (!trimmed) {
    return undefined;
  }

  if (trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed);
      return isRecord(parsed) ? parsed : undefined;
    } catch {
      return undefined;
    }
  }

  const start = trimmed.indexOf('{');
  if (start >= 0) {
    let depth = 0;
    for (let index = start; index < trimmed.length; index += 1) {
      const char = trimmed[index];
      if (char === '{') {
        depth += 1;
      } else if (char === '}') {
        depth -= 1;
        if (depth === 0) {
          try {
            const parsed = JSON.parse(trimmed.slice(start, index + 1));
            return isRecord(parsed) ? parsed : undefined;
          } catch {
            return undefined;
          }
        }
      }
    }
  }

  return undefined;
}

function isDemoRequested(text: string | undefined) {
  return Boolean(text && /\bdemo\b|\bexample\b|\bsample\b/i.test(text));
}

function defaultScenarioForType(type: ScenarioType): ScenarioDefinition {
  if (type === 'scheduling') {
    return scenarioDefinitions.scheduling_system;
  }

  if (type === 'allocation') {
    return scenarioDefinitions.resource_allocation;
  }

  return scenarioDefinitions.logistics_routing;
}

export function matchScenario(input: string | Record<string, unknown> | undefined, mode: ScenarioResolutionMode = 'standard'): ScenarioMatch {
  const rawObject = readRawInput(input);
  const text = normalizeText(typeof input === 'string' ? input : JSON.stringify(input ?? {}));
  const classification = classifyProblem(input ?? '');
  const demoRequested = isDemoRequested(typeof input === 'string' ? input : undefined);

  const scored = Object.values(scenarioDefinitions).map((scenario) => {
    const patternResult = scorePatterns(text, scenario.patterns);
    const typeBoost = classification.type === scenario.type ? 0.65 : classification.type === 'graph' && scenario.type === 'routing' ? 0.5 : 0;
    const explicitBoost = rawObject && typeof rawObject.scenario === 'string' && rawObject.scenario === scenario.id ? 0.9 : 0;
    const demoBoost = demoRequested && scenario.id === 'logistics_routing' ? 0.3 : 0;
    const score = patternResult.score + typeBoost + explicitBoost + demoBoost;

    return {
      scenario,
      score,
      evidence: [
        ...patternResult.evidence,
        ...(typeBoost > 0 ? [`classification=${classification.type}`] : []),
        ...(explicitBoost > 0 ? ['explicit scenario id'] : []),
        ...(demoBoost > 0 ? ['demo keyword'] : []),
      ],
    };
  });

  scored.sort((left, right) => right.score - left.score || left.scenario.id.localeCompare(right.scenario.id));

  const best = scored[0];
  if (!best || best.score <= 0) {
    const fallback = defaultScenarioForType(classification.type === 'graph' ? 'routing' : classification.type === 'allocation' ? 'allocation' : classification.type === 'scheduling' ? 'scheduling' : 'routing');
    return {
      matched: false,
      scenarioId: fallback.id,
      label: fallback.label,
      type: fallback.type,
      confidence: 0.38,
      reason: `Fallback scenario selected from problem classification=${classification.type || 'unknown'}.`,
      mode,
      demoRequested,
      strict: mode === 'competition',
    };
  }

  const confidence = Math.max(0.35, Math.min(0.98, 0.4 + best.score * 0.18));
  return {
    matched: true,
    scenarioId: best.scenario.id,
    label: best.scenario.label,
    type: best.scenario.type,
    confidence,
    reason: best.evidence.length > 0 ? `Matched scenario using: ${best.evidence.join(', ')}.` : 'Matched scenario by problem classification.',
    mode,
    demoRequested,
    strict: mode === 'competition',
  };
}

function buildValidationResult(result: ReturnType<ScenarioDefinition['input_schema']['safeParse']>): ScenarioValidationResult {
  if (result.success) {
    return {
      ok: true,
      missing: [],
      errors: [],
    };
  }

  const missing = [...new Set(result.error.issues.map((issue) => issue.path[0]).filter((value): value is string => typeof value === 'string' && value.length > 0))];
  return {
    ok: false,
    missing,
    errors: result.error.issues.map((issue) => issue.message),
  };
}

function buildBenchmarkEntry(result: QuantumSolverResult | undefined, fallbackLabel: string): ScenarioBenchmarkEntry {
  if (!result) {
    return {
      solver: fallbackLabel,
      backend: 'classical',
      feasible: false,
      totalCost: Number.POSITIVE_INFINITY,
      runtimeMs: 0,
      violationCount: 1,
      constraintSatisfaction: 0,
      explanation: `${fallbackLabel} result unavailable.`,
    };
  }

  return {
    solver: result.solver,
    backend: result.backend,
    feasible: result.feasible,
    totalCost: result.totalCost,
    runtimeMs: result.runtimeMs,
    violationCount: result.violationCount,
    constraintSatisfaction: result.feasible ? 100 : Math.max(0, 100 - result.violationCount * 15),
    explanation: result.explanation,
  };
}

function buildNaiveGraphBenchmark(problem: Extract<Extract<QuantumProblemMapping, { status: 'ready' }>['problem'], { problemType: 'graph' }>) {
  const route = [...problem.nodes];
  const totalCost = calculateGraphRouteCost(problem, route);
  const feasible = route.length === problem.nodes.length && Number.isFinite(totalCost);
  return {
    solver: 'naive_baseline',
    backend: 'classical',
    feasible,
    totalCost,
    runtimeMs: 1,
    violationCount: feasible ? 0 : 1,
    constraintSatisfaction: feasible ? 100 : 0,
    explanation: 'Naive baseline visits nodes in input order without optimization.',
  } satisfies ScenarioBenchmarkEntry;
}

function buildNaiveAssignmentBenchmark(problem: Extract<Extract<QuantumProblemMapping, { status: 'ready' }>['problem'], { problemType: 'assignment' | 'resource_allocation' }>) {
  const left = (problem.problemType === 'resource_allocation' ? problem.resources : problem.workers ?? []) as Array<{ id: string }>;
  const right = (problem.problemType === 'resource_allocation' ? problem.locations : problem.tasks ?? []) as Array<{ id: string }>;
  const pairCount = Math.min(left.length, right.length);
  const assignments = left.slice(0, pairCount).map((leftItem, index) => {
    const rightItem = right[index];
    if (!rightItem) {
      return undefined;
    }

    const cost = problem.costs[leftItem.id]?.[rightItem.id];
    return {
      from: leftItem.id,
      to: rightItem.id,
      cost: Number.isFinite(cost) ? cost : Number.POSITIVE_INFINITY,
    };
  }).filter((assignment): assignment is { from: string; to: string; cost: number } => Boolean(assignment));

  const totalCost = assignments.reduce((sum, assignment) => sum + (Number.isFinite(assignment.cost) ? assignment.cost : 0), 0);
  const feasible = left.length === right.length && assignments.every((assignment) => Number.isFinite(assignment.cost));
  const violationCount = feasible ? 0 : Math.abs(left.length - right.length) + assignments.filter((assignment) => !Number.isFinite(assignment.cost)).length;

  return {
    solver: 'naive_baseline',
    backend: 'classical',
    feasible,
    totalCost,
    runtimeMs: 1,
    violationCount,
    constraintSatisfaction: feasible ? 100 : Math.max(0, 100 - violationCount * 15),
    explanation: 'Naive baseline pairs entities in input order without cost awareness.',
  } satisfies ScenarioBenchmarkEntry;
}

function summarizeBenchmark(
  baseline: ScenarioBenchmarkEntry,
  classical: ScenarioBenchmarkEntry,
  hybrid: ScenarioBenchmarkEntry
) {
  const improvementPercent = Number.isFinite(baseline.totalCost) && baseline.totalCost > 0 && Number.isFinite(hybrid.totalCost)
    ? Number(((baseline.totalCost - hybrid.totalCost) / baseline.totalCost * 100).toFixed(2))
    : 0;
  const efficiencyGain = classical.runtimeMs > 0
    ? Number(((classical.runtimeMs - hybrid.runtimeMs) / classical.runtimeMs * 100).toFixed(2))
    : 0;
  const constraintSatisfaction = Number(Math.max(
    0,
    Math.min(100, hybrid.feasible ? 100 : 100 - hybrid.violationCount * 15)
  ).toFixed(2));

  return {
    improvementPercent,
    efficiencyGain,
    constraintSatisfaction,
  };
}

function buildMarkdownReport(args: {
  scenario: ScenarioDefinition;
  mode: ScenarioResolutionMode;
  validation: ScenarioValidationResult;
  baseline: ScenarioBenchmarkEntry;
  classical: ScenarioBenchmarkEntry;
  hybrid: ScenarioBenchmarkEntry;
  improvementPercent: number;
  efficiencyGain: number;
  constraintSatisfaction: number;
  hybridResult: HybridSolverResult;
}) {
  const lines = [
    `# Scenario Benchmark: ${args.scenario.label}`,
    `- Scenario ID: ${args.scenario.id}`,
    `- Scenario type: ${args.scenario.type}`,
    `- Mode: ${args.mode}`,
    `- Validation: ${args.validation.ok ? 'passed' : 'needs_input'}`,
    '',
    '## Baseline vs Classical vs Hybrid',
    `- Baseline solver: ${args.baseline.solver} (${args.baseline.backend})`,
    `- Classical solver: ${args.classical.solver} (${args.classical.backend})`,
    `- Hybrid solver: ${args.hybrid.solver} (${args.hybrid.backend})`,
    `- Baseline cost: ${Number.isFinite(args.baseline.totalCost) ? args.baseline.totalCost : 'n/a'}`,
    `- Classical cost: ${Number.isFinite(args.classical.totalCost) ? args.classical.totalCost : 'n/a'}`,
    `- Hybrid cost: ${Number.isFinite(args.hybrid.totalCost) ? args.hybrid.totalCost : 'n/a'}`,
    `- Improvement: ${args.improvementPercent}%`,
    `- Efficiency gain: ${args.efficiencyGain}%`,
    `- Constraint satisfaction: ${args.constraintSatisfaction}%`,
    '',
    '## Why This Solution',
    args.hybridResult.whyThisSolution,
    '',
    '## Trade-offs',
    ...args.hybridResult.tradeOffs.map((item) => `- ${item}`),
    '',
    '## Rejected Alternatives',
    ...args.hybridResult.rejectedAlternatives.map((item) => `- ${item.solver} (${item.backend}) score=${item.score}`),
    '',
    args.hybridResult.markdownReport,
  ];

  return lines.join('\n');
}

export function resolveScenarioRequest(
  input: string | Record<string, unknown> | undefined,
  options: {
    mode?: ScenarioResolutionMode;
    scenarioId?: ScenarioId;
  } = {}
): ScenarioResolution {
  const mode = options.mode ?? 'standard';
  const rawObject = readRawInput(input);
  const match = matchScenario(input, mode);
  const scenario = options.scenarioId ? scenarioDefinitions[options.scenarioId] : match.scenarioId ? scenarioDefinitions[match.scenarioId] : undefined;
  const demoRequested = mode === 'demo' || (mode !== 'competition' && match.demoRequested);
  const usesExampleInput = Boolean(demoRequested && scenario);
  const candidateInput = usesExampleInput
    ? scenario?.example_input
    : rawObject;
  const validation = scenario
    ? buildValidationResult(scenario.input_schema.safeParse(candidateInput ?? {}))
    : {
        ok: false,
        missing: ['scenario'],
        errors: ['No scenario could be matched for the provided input.'],
      };

  if (!scenario) {
    return {
      status: 'needs_input',
      match,
      mode,
      required: [],
      missing: ['scenario'],
      validation,
      reason: 'No scenario could be matched for the provided input.',
      usesExampleInput: false,
    };
  }

  if (validation.ok && candidateInput && isRecord(candidateInput)) {
    return {
      status: 'ready',
      scenario,
      match,
      mode,
      input: candidateInput,
      validation,
      usesExampleInput,
    };
  }

  const required = validation.ok ? [] : validation.missing.length > 0 ? validation.missing : Object.keys(scenario.example_input);
  return {
    status: 'needs_input',
    scenario,
    match,
    mode,
    required,
    missing: validation.ok ? [] : validation.missing,
    validation,
    reason: usesExampleInput
      ? 'Demo mode could not validate the predefined scenario input.'
      : mode === 'competition'
        ? 'Competition mode requires explicit structured scenario input.'
        : 'Scenario input is incomplete and cannot be benchmarked without required fields.',
    usesExampleInput,
  };
}

export function runScenarioBenchmark(
  input: string | Record<string, unknown> | undefined,
  options: {
    mode?: ScenarioResolutionMode;
    scenarioId?: ScenarioId;
    solverStrategy?: HybridSolverStrategy;
  } = {}
): ScenarioBenchmarkResult {
  const resolution = resolveScenarioRequest(input, options);
  if (resolution.status === 'needs_input') {
    return {
      status: 'needs_input',
      scenario: resolution.scenario,
      match: resolution.match,
      mode: resolution.mode,
      validation: resolution.validation,
      required: resolution.required,
      missing: resolution.missing,
      reason: resolution.reason,
      expectedOutputStructure: resolution.scenario?.expected_output_structure,
    };
  }

  const parsed = mapProblem(resolution.input);
  if (parsed.status !== 'ready') {
    return {
      status: 'needs_input',
      scenario: resolution.scenario,
      match: resolution.match,
      mode: resolution.mode,
      validation: resolution.validation,
      required: parsed.missing,
      missing: parsed.missing,
      reason: 'Problem mapping could not build a ready optimization model.',
      expectedOutputStructure: resolution.scenario.expected_output_structure,
    };
  }

  const baseline = parsed.problem.problemType === 'graph'
    ? buildNaiveGraphBenchmark(parsed.problem)
    : buildNaiveAssignmentBenchmark(parsed.problem);
  const classicalResult = solveClassicalBaseline(parsed);
  const classical = buildBenchmarkEntry(classicalResult, 'greedy');
  const hybridResult = solveHybridOptimization({
    problem: resolution.input,
    strategy: options.solverStrategy ?? (resolution.mode === 'competition' ? 'quantum_biased' : 'hybrid'),
  });
  const hybrid = buildBenchmarkEntry(hybridResult.selectedSolution as QuantumSolverResult | undefined, 'hybrid');
  const { improvementPercent, efficiencyGain, constraintSatisfaction } = summarizeBenchmark(baseline, classical, hybrid);
  const markdownReport = buildMarkdownReport({
    scenario: resolution.scenario,
    mode: resolution.mode,
    validation: resolution.validation,
    baseline,
    classical,
    hybrid,
    improvementPercent,
    efficiencyGain,
    constraintSatisfaction,
    hybridResult,
  });

  return {
    status: 'ready',
    scenario: resolution.scenario,
    match: resolution.match,
    mode: resolution.mode,
    validation: resolution.validation,
    input: resolution.input,
    mapping: parsed,
    baseline,
    classical,
    hybrid,
    improvementPercent,
    efficiencyGain,
    constraintSatisfaction,
    hybridResult,
    markdownReport,
    expectedOutputStructure: resolution.scenario.expected_output_structure,
  };
}

export function isCompetitionMode() {
  return env.ELYAN_MODE === 'competition';
}

export function getScenarioDefinition(scenarioId: ScenarioId) {
  return scenarioDefinitions[scenarioId];
}

export { scenarioDefinitions } from './definitions';
