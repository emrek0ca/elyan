import { env } from '@/lib/env';
import { getControlPlanePool } from '@/core/control-plane/database';
import type { ModelRoutingMode, ReasoningDepth, TaskIntent } from '@/core/orchestration';
import { isOptimizationQuery } from '@/core/optimization/signals';
import { refineProblem, type RefinedProblemResult, type RefinedProblemType } from '@/core/problem/refiner';
import type { ProblemComplexityEstimate } from '@/core/problem/complexity';
import { matchScenario, type ScenarioMatch, type ScenarioType } from '@/core/scenarios';

export type ExecutionDecisionMode = 'fast' | 'research' | 'task' | 'quantum';
export type QuantumSolverStrategy = 'classical_only' | 'hybrid' | 'quantum_biased';

export type ExecutionDecisionToolPolicy = {
  allowWebSearch: boolean;
  allowConnectors: boolean;
  allowLocalTools: boolean;
  allowBrowser: boolean;
  preferredTools: string[];
};

export type ExecutionDecisionSteps = {
  complexity: 'low' | 'medium' | 'high';
  stepBudget: number;
  retryLimit: number;
};

export type ExecutionDecision = {
  mode: ExecutionDecisionMode;
  modelId?: string;
  solverPreference?: {
    solverId: string;
    problemType?: RefinedProblemType | string;
    confidence: number;
  };
  solverStrategy?: QuantumSolverStrategy;
  problemRefinement?: {
    type: RefinedProblemType;
    status: RefinedProblemResult['status'];
    summary: string;
    required: string[];
    missing: string[];
  };
  problemComplexity?: ProblemComplexityEstimate;
  scenario?: {
    id: string;
    label: string;
    type: ScenarioType;
    confidence: number;
    reason: string;
    demoRequested: boolean;
    mode: ScenarioMatch['mode'];
  };
  modelPerformance: number;
  tools: ExecutionDecisionToolPolicy;
  steps: ExecutionDecisionSteps;
  reasoning: string[];
  artifactCount: number;
};

export type DecisionEngineInput = {
  query: string;
  taskType: TaskIntent;
  requestedModelId?: string | null;
  spaceId?: string | null;
  routingMode?: ModelRoutingMode;
  reasoningDepth?: ReasoningDepth;
};

type DecisionArtifactRow = {
  artifact_type: string | null;
  base_model: string | null;
  space_id: string | null;
  score: number | string | null;
  confidence_score: number | string | null;
  metadata: unknown;
  created_at: string | Date | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeText(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function clamp01(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, Math.min(1, value));
}

function asLowerText(value: string) {
  return normalizeText(value).toLowerCase();
}

function hasAny(text: string, patterns: RegExp[]) {
  return patterns.some((pattern) => pattern.test(text));
}

function hasStructuredProblem(input: string) {
  return input.includes('{') && input.includes('}');
}

function isConceptualOptimizationQuestion(query: string) {
  return hasAny(query, [
    /\b(what is|what are|define|explain|overview|history of|meaning of)\b.*\b(optimization|qubo|ising|scheduling|routing|allocation)\b/i,
    /\b(optimization|qubo|ising|scheduling|routing|allocation)\b.*\b(nedir|ne demek|açıkla|tanım|tarihçe)\b/i,
  ]);
}

function isQuantumOptimizationWork(input: DecisionEngineInput, scenario?: ScenarioMatch) {
  const query = asLowerText(input.query);
  if (scenario?.matched) {
    return true;
  }

  if (isConceptualOptimizationQuestion(query)) {
    return false;
  }

  const refinement = refineProblem(input.query);
  if (refinement.type !== 'unknown' && (isOptimizationQuery(query) || hasStructuredProblem(input.query))) {
    return true;
  }

  if (!isOptimizationQuery(query)) {
    return false;
  }

  if (hasStructuredProblem(input.query)) {
    return true;
  }

  return hasAny(query, [
    /\b(solve|optimize|optimise|minimize|maximize|find optimal|best route|route optimization|schedule|assign|allocate|distribute|load balancing|minimum-cost|minimum cost|best distribution)\b/i,
    /\b(graph|qubo|ising|resource allocation|task assignment|scheduling|routing)\b/i,
    /\b(çöz|optimize et|en iyi|en düşük maliyet|rota|görev dağıt|kaynak tahsisi|yük dengele)\b/i,
  ]);
}

function isProbablyLocalModelId(modelId: string) {
  return /^(ollama:|local:|lmstudio:|llama\.cpp:|openai:gpt-oss|anthropic:.*local)/i.test(modelId) || /\b(local|ollama|lmstudio|llama)\b/i.test(modelId);
}

function pickDecisionMode(
  input: DecisionEngineInput,
  artifactHints: string[],
  hasArtifactRoutingHint: boolean,
  scenario?: ScenarioMatch
): ExecutionDecisionMode {
  const query = asLowerText(input.query);
  const directResearchSignals = hasAny(query, [
    /\b(research|researching|compare|comparison|versus|difference|tradeoff|benchmark)\b/i,
    /\b(latest|recent|current|today|this week|news|sources?|cite|evidence|what changed)\b/i,
    /\b(perplexity|web search|search web)\b/i,
  ]);
  const directTaskSignals = hasAny(query, [
    /\b(how to|steps?|guide|setup|configure|install|run|fix|read|inspect|summarize|extract|write|draft|generate|compose|implement|edit|open|close|create|update|delete)\b/i,
    /\b(my files|local|computer|device|workspace|folder|browser|automation|command)\b/i,
  ]);
  const shortDirectAnswer = query.length <= 72 && !directResearchSignals && !directTaskSignals;

  if (isQuantumOptimizationWork(input, scenario)) {
    return 'quantum';
  }

  if (input.taskType === 'research' || input.taskType === 'comparison' || directResearchSignals) {
    return 'research';
  }

  if (input.taskType === 'procedural' || input.taskType === 'personal_workflow' || directTaskSignals) {
    return 'task';
  }

  if (hasArtifactRoutingHint) {
    const joinedHints = artifactHints.join(' ').toLowerCase();
    if (joinedHints.includes('retrieval-first') || joinedHints.includes('cloud-preferred')) {
      return 'research';
    }

    if (joinedHints.includes('local-first') || joinedHints.includes('local only')) {
      return 'task';
    }
  }

  if (shortDirectAnswer) {
    return 'fast';
  }

  return 'fast';
}

function resolveComplexity(query: string, mode: ExecutionDecisionMode) {
  const length = normalizeText(query).length;
  const hasMultipleClauses = /[;,.!?].*[;,.!?]/.test(query) || /\b(and|then|after|before|while|plus)\b/i.test(query);

  if (mode === 'fast') {
    return {
      complexity: length > 120 || hasMultipleClauses ? 'medium' : 'low',
      stepBudget: length > 120 ? 2 : 1,
      retryLimit: 0,
    } as const;
  }

  if (mode === 'research') {
    return {
      complexity: length > 180 || hasMultipleClauses ? 'high' : 'medium',
      stepBudget: length > 180 ? 4 : 3,
      retryLimit: 1,
    } as const;
  }

  if (mode === 'quantum') {
    return {
      complexity: length > 220 || hasMultipleClauses ? 'high' : 'medium',
      stepBudget: 3,
      retryLimit: 1,
    } as const;
  }

  return {
    complexity: length > 180 || hasMultipleClauses ? 'high' : length > 100 ? 'medium' : 'low',
    stepBudget: length > 180 ? 5 : hasMultipleClauses ? 4 : length > 100 ? 4 : 3,
    retryLimit: 2,
  } as const;
}

function resolveSolverStrategy(refinement: RefinedProblemResult): QuantumSolverStrategy {
  if (refinement.status === 'needs_input') {
    return refinement.complexity.complexity === 'high'
      ? 'quantum_biased'
      : refinement.complexity.complexity === 'medium'
        ? 'hybrid'
        : 'classical_only';
  }

  if (refinement.complexity.complexity === 'low') {
    return 'classical_only';
  }

  if (refinement.complexity.complexity === 'medium') {
    return 'hybrid';
  }

  return 'quantum_biased';
}

function resolveTools(mode: ExecutionDecisionMode) {
  if (mode === 'quantum') {
    return {
      allowWebSearch: false,
      allowConnectors: false,
      allowLocalTools: true,
      allowBrowser: false,
      preferredTools: ['optimization_solve', 'tool_bridge'],
    };
  }

  if (mode === 'research') {
    return {
      allowWebSearch: true,
      allowConnectors: true,
      allowLocalTools: false,
      allowBrowser: true,
      preferredTools: ['web_search', 'connectors', 'browser'],
    };
  }

  if (mode === 'task') {
    return {
      allowWebSearch: false,
      allowConnectors: true,
      allowLocalTools: true,
      allowBrowser: true,
      preferredTools: ['local_tools', 'connectors', 'browser'],
    };
  }

  return {
    allowWebSearch: false,
    allowConnectors: false,
    allowLocalTools: false,
    allowBrowser: false,
    preferredTools: [],
  };
}

function toNumber(value: number | string | null | undefined) {
  const parsed = typeof value === 'string' ? Number(value) : Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function readArtifactHint(metadata: unknown) {
  if (!isRecord(metadata)) {
    return '';
  }

  const hint =
    typeof metadata.routing_hint === 'string'
      ? metadata.routing_hint
      : typeof metadata.prompt_hint === 'string'
        ? metadata.prompt_hint
        : typeof metadata.tool_usage_pattern === 'string'
          ? metadata.tool_usage_pattern
          : '';

  return hint.trim();
}

function readSolverPreference(metadata: unknown) {
  if (!isRecord(metadata)) {
    return undefined;
  }

  const decisionMode = typeof metadata.decision_mode === 'string' ? metadata.decision_mode : '';
  const solverUsed = typeof metadata.solver_used === 'string'
    ? metadata.solver_used
    : typeof metadata.preferred_solver === 'string'
      ? metadata.preferred_solver
      : '';

  if (decisionMode !== 'quantum' || !solverUsed.trim()) {
    return undefined;
  }

  const problemType = typeof metadata.problem_type === 'string' ? metadata.problem_type : undefined;
  const solutionQuality = toNumber(metadata.solution_quality as number | string | null | undefined);
  const improvementRatio = toNumber(metadata.improvement_ratio as number | string | null | undefined);
  const score = clamp01(solutionQuality * 0.7 + Math.min(0.3, Math.max(0, improvementRatio)));

  return {
    solverId: solverUsed.trim(),
    problemType,
    confidence: score,
  };
}

function normalizeProblemTypeLabel(value: string | undefined) {
  const normalized = value?.trim().toLowerCase();

  if (!normalized) {
    return undefined;
  }

  if (normalized === 'graph' || normalized === 'route' || normalized === 'routing') {
    return 'routing';
  }

  if (normalized === 'assignment' || normalized === 'scheduling') {
    return 'scheduling';
  }

  if (normalized === 'resource_allocation' || normalized === 'allocation') {
    return 'allocation';
  }

  return normalized;
}

async function loadDecisionArtifacts(input: DecisionEngineInput) {
  if (!env.DATABASE_URL?.trim()) {
    return [];
  }

  try {
    const pool = getControlPlanePool(env.DATABASE_URL);
    const result = await pool.query<DecisionArtifactRow>(
      `
        SELECT artifact_type, base_model, space_id, score, confidence_score, metadata, created_at
        FROM model_artifacts
        WHERE is_safe_for_learning = true
          AND (space_id = $1 OR space_id = 'global')
          AND (
            metadata->>'task_type' = $2
            OR metadata->>'task_type' IS NULL
            OR metadata->>'decision_mode' = 'quantum'
          )
          AND artifact_type IN ('brain_model', 'prompt_hint', 'routing_hint', 'tool_usage_pattern')
        ORDER BY COALESCE(confidence_score, score, 0) DESC, COALESCE(score, 0) DESC, created_at DESC
        LIMIT 12
      `,
      [input.spaceId?.trim() || '', input.taskType]
    );

    return result.rows;
  } catch {
    return [];
  }
}

function chooseSolverPreference(
  problemType: RefinedProblemType,
  artifacts: DecisionArtifactRow[]
) {
  const preferences: Array<{ solverId: string; problemType?: string; confidence: number }> = [];
  const normalizedProblemType = normalizeProblemTypeLabel(problemType);

  for (const artifact of artifacts) {
    const preference = readSolverPreference(artifact.metadata);
    if (!preference) {
      continue;
    }

    if (
      normalizedProblemType &&
      preference.problemType &&
      normalizeProblemTypeLabel(preference.problemType) !== normalizedProblemType
    ) {
      continue;
    }

    const confidence = clamp01(
      Math.max(
        preference.confidence,
        toNumber(artifact.confidence_score ?? artifact.score)
      )
    );

    preferences.push({
      solverId: preference.solverId,
      problemType: preference.problemType,
      confidence,
    });
  }

  preferences.sort((left, right) => right.confidence - left.confidence || left.solverId.localeCompare(right.solverId));

  return preferences[0];
}

function chooseModelId(
  input: DecisionEngineInput,
  artifacts: DecisionArtifactRow[],
  requestedModelId?: string | null
) {
  const preferred = requestedModelId?.trim() || undefined;
  const topArtifact = artifacts.find((artifact) => {
    const baseModel = artifact.base_model?.trim();
    if (!baseModel || baseModel === 'unknown') {
      return false;
    }

    const confidence = clamp01(toNumber(artifact.confidence_score ?? artifact.score));
    return confidence >= 0.65;
  });

  if (!topArtifact?.base_model?.trim()) {
    return preferred;
  }

  const topModelId = topArtifact.base_model.trim();
  const artifactConfidence = clamp01(toNumber(topArtifact.confidence_score ?? topArtifact.score));
  const routingHint = readArtifactHint(topArtifact.metadata).toLowerCase();

  if (input.routingMode === 'local_only' && !isProbablyLocalModelId(topModelId)) {
    return preferred?.length ? preferred : undefined;
  }

  if (preferred && preferred === topModelId) {
    return preferred;
  }

  if (artifactConfidence >= 0.75) {
    return topModelId;
  }

  if (routingHint.includes('local-first') || routingHint.includes('local only')) {
    return topModelId;
  }

  if (!preferred) {
    return topModelId;
  }

  return preferred;
}

export async function decideExecution(input: DecisionEngineInput): Promise<ExecutionDecision> {
  const artifacts = await loadDecisionArtifacts(input);
  const artifactHints = artifacts.map((artifact) => readArtifactHint(artifact.metadata)).filter(Boolean);
  const hasArtifactRoutingHint = artifactHints.some((hint) => /local-first|local only|cloud-preferred|retrieval-first/i.test(hint));
  const scenario = matchScenario(input.query, env.ELYAN_MODE === 'competition' ? 'competition' : 'standard');
  const refinement = refineProblem(input.query);

  const mode = pickDecisionMode(input, artifactHints, hasArtifactRoutingHint, scenario);
  const modelId = mode === 'quantum' ? 'elyan:quantum-hybrid' : chooseModelId(input, artifacts, input.requestedModelId);
  const solverPreference = mode === 'quantum' ? chooseSolverPreference(refinement.type, artifacts) : undefined;
  const solverStrategy = mode === 'quantum' ? resolveSolverStrategy(refinement) : undefined;
  const steps = resolveComplexity(input.query, mode);
  const tools = resolveTools(mode);
  const modelPerformance = artifacts.length > 0 ? clamp01(toNumber(artifacts[0]?.confidence_score ?? artifacts[0]?.score)) : 0;
  const reasoning = [
    `task_type=${input.taskType}`,
    `mode=${mode}`,
    `artifacts=${artifacts.length}`,
    `model_performance=${modelPerformance.toFixed(2)}`,
    `step_budget=${steps.stepBudget}`,
    `problem_type=${refinement.type}`,
    `problem_complexity=${refinement.complexity.complexity}`,
    `problem_size=${refinement.complexity.problemSize}`,
    `estimated_space=${refinement.complexity.estimated_space}`,
  ];

  if (scenario.matched) {
    reasoning.push(`scenario=${scenario.scenarioId}`);
    reasoning.push(`scenario_label=${scenario.label}`);
    reasoning.push(`scenario_mode=${scenario.mode}`);
  }

  if (input.routingMode) {
    reasoning.push(`routing_mode=${input.routingMode}`);
  }

  if (input.reasoningDepth) {
    reasoning.push(`reasoning_depth=${input.reasoningDepth}`);
  }

  if (modelId) {
    reasoning.push(`model_id=${modelId}`);
  }

  if (solverPreference) {
    reasoning.push(`solver_preference=${solverPreference.solverId}`);
  }

  if (solverStrategy) {
    reasoning.push(`solver_strategy=${solverStrategy}`);
  }

  return {
    mode,
    modelId,
    solverPreference,
    solverStrategy,
    problemRefinement: {
      type: refinement.type,
      status: refinement.status,
      summary: refinement.summary,
      required: refinement.required,
      missing: refinement.missing,
    },
    problemComplexity: refinement.complexity,
    scenario: scenario.matched && scenario.scenarioId && scenario.type ? {
      id: scenario.scenarioId,
      label: scenario.label ?? scenario.scenarioId,
      type: scenario.type,
      confidence: scenario.confidence,
      reason: scenario.reason,
      demoRequested: scenario.demoRequested,
      mode: scenario.mode,
    } : undefined,
    modelPerformance,
    tools,
    steps,
    reasoning,
    artifactCount: artifacts.length,
  };
}
