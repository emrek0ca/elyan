import { getControlPlanePool } from '../database';
import type {
  ControlPlaneLearningArtifactType,
  ControlPlaneTaskIntent,
} from '../types';
import type { ModelRoutingMode } from '@/core/orchestration';

type LearningSignalInput = {
  accountId: string;
  spaceId?: string;
  eventId: string;
  requestId: string;
  source: string;
  input: string;
  output: string;
  intent: string;
  taskType: ControlPlaneTaskIntent;
  success: boolean;
  failureReason?: string;
  feedback?: Record<string, unknown>;
  latencyMs: number;
  score: number;
  accepted: boolean;
  modelId?: string;
  modelProvider?: string;
  isSafeForLearning: boolean;
  metadata?: Record<string, unknown>;
  createdAt?: string;
};

export type LearningSignal = {
  accountId: string;
  spaceId: string;
  eventId: string;
  requestId: string;
  source: string;
  intent: string;
  taskType: ControlPlaneTaskIntent;
  successScore: number;
  failureReason?: string;
  promptEffectiveness: number;
  modelPerformance: number;
  feedback: Record<string, unknown>;
  isSafeForLearning: boolean;
  modelId?: string;
  modelProvider?: string;
  latencyMs: number;
  score: number;
  accepted: boolean;
  sourceCount: number;
  citationCount: number;
  queryLength?: number;
  reasoningDepth?: string;
  routingMode?: string;
  teacherStrategy?: string;
  evaluatorNotes?: string;
  discardReason?: string;
  decisionMode?: string;
  problemType?: string;
  solverUsed?: string;
  solverBackend?: string;
  solverLatencyMs?: number;
  baselineCost?: number;
  selectedCost?: number;
  solutionQuality?: number;
  solverQuality?: number;
  successRate?: number;
  improvementRatio?: number;
  solverStatus?: string;
  preferredSolver?: string;
  problemObjective?: string;
  problemComplexity?: string;
  estimatedSpace?: number;
  problemSize?: number;
  solverStrategy?: string;
  createdAt: string;
  promptHint: string;
  routingHint: string;
  toolUsagePattern: string;
  sanitizedSummary: string;
};

export type LearningArtifactDraft = {
  modelVersion: string;
  baseModel: string;
  spaceId: string;
  datasetSize: number;
  loss?: number;
  score: number;
  active: boolean;
  artifactPath: string;
  artifactType: ControlPlaneLearningArtifactType;
  sourceEventIds: string[];
  confidenceScore: number;
  isSafeForLearning: boolean;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

type LearningArtifactRow = {
  model_version: string;
  source_event_ids: unknown;
  confidence_score: number | string | null;
  created_at: string | Date | null;
};

type LearningArtifactLookupRow = {
  model_version: string;
  artifact_type: string | null;
  base_model: string;
  space_id: string | null;
  source_event_ids: unknown;
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

function round2(value: number) {
  return Number(clamp01(value).toFixed(2));
}

function toPositiveInteger(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0;
}

function toFiniteNumber(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  return undefined;
}

function readMetadataString(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined;
}

function parseStringArray(value: unknown) {
  if (Array.isArray(value)) {
    return value.filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0);
  }

  return [];
}

function sanitizeSegment(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'unknown';
}

function joinUnique(values: string[]) {
  return [...new Set(values.filter((value) => value.trim().length > 0))];
}

function formatConfidence(value: number) {
  return clamp01(value).toFixed(2);
}

function buildPromptHint(signal: LearningSignal) {
  if (signal.decisionMode === 'quantum' && signal.solverStatus === 'solved') {
    const objectiveSuffix = signal.problemObjective ? ` Keep the weighted objective in view: ${signal.problemObjective}.` : '';
    return `For optimization work, summarize the deterministic solver comparison first and avoid claiming external quantum hardware was used.${objectiveSuffix}`;
  }

  const task = signal.taskType;

  if (signal.successScore >= 0.8) {
    if (task === 'research' || task === 'comparison') {
      return 'Use grounded evidence early, keep citations visible, and prefer concise answer-first structure.';
    }

    if (task === 'procedural' || task === 'personal_workflow') {
      return 'Prefer direct step-by-step guidance with concrete actions and minimal extra framing.';
    }

    return 'Favor clear direct answers and avoid unnecessary hedging when the request is already well-scoped.';
  }

  if (signal.failureReason) {
    return `When the request cannot be completed, fail closed with the exact reason: ${signal.failureReason}.`;
  }

  return 'Keep the answer concise, use the available context, and avoid overclaiming unsupported facts.';
}

function buildRoutingHint(signal: LearningSignal) {
  if (signal.decisionMode === 'quantum' && signal.solverUsed) {
    const strategySuffix = signal.solverStrategy ? ` The observed solver strategy was ${signal.solverStrategy}.` : '';
    return `Quantum optimization tasks should use optimization_solve locally and prefer solver ${signal.solverUsed} for ${signal.problemType ?? 'optimization'} when safe historical signals remain strong.${strategySuffix}`;
  }

  if (signal.taskType === 'research' || signal.taskType === 'comparison') {
    return 'Research and comparison tasks benefit from retrieval-first prompting and cloud-preferred model selection only when available.';
  }

  if (signal.taskType === 'procedural' || signal.taskType === 'personal_workflow') {
    return 'Procedural and personal workflow tasks should stay local-first unless hosted capabilities are explicitly required.';
  }

  return 'Keep routing conservative and preserve the resolved model unless a clearer task-specific reason emerges.';
}

function buildToolUsagePattern(signal: LearningSignal) {
  if (signal.decisionMode === 'quantum') {
    return 'Use optimization_solve for structured optimization problems, compare classical and quantum-inspired candidates, and return needs_input when entities or costs are missing.';
  }

  const sourceCount = signal.sourceCount;

  if (sourceCount > 0 || signal.citationCount > 0) {
    return 'When retrieval is available, gather evidence before answering and preserve only the minimal grounded context needed for the response.';
  }

  if (signal.taskType === 'procedural' || signal.taskType === 'personal_workflow') {
    return 'Use tools only when the request needs execution; otherwise answer directly and keep the turn lightweight.';
  }

  return 'Prefer simple direct answers unless the task clearly benefits from retrieval or a tool-assisted workflow.';
}

function buildSanitizedSummary(signal: LearningSignal) {
  const parts = [
    `task_type=${signal.taskType}`,
    `success_score=${formatConfidence(signal.successScore)}`,
    `prompt_effectiveness=${formatConfidence(signal.promptEffectiveness)}`,
    `model_performance=${formatConfidence(signal.modelPerformance)}`,
    `latency_ms=${signal.latencyMs}`,
    `source_count=${signal.sourceCount}`,
    `citation_count=${signal.citationCount}`,
  ];

  if (signal.failureReason) {
    parts.push(`failure_reason=${signal.failureReason}`);
  }

  if (signal.decisionMode === 'quantum') {
    parts.push(
      `decision_mode=quantum`,
      `problem_type=${signal.problemType ?? 'unknown'}`,
      `problem_objective=${signal.problemObjective ?? 'unavailable'}`,
      `problem_complexity=${signal.problemComplexity ?? 'unknown'}`,
      `problem_size=${signal.problemSize ?? 0}`,
      `estimated_space=${signal.estimatedSpace ?? 0}`,
      `solver_strategy=${signal.solverStrategy ?? 'unknown'}`,
      `solver_used=${signal.solverUsed ?? 'none'}`,
      `solver_status=${signal.solverStatus ?? 'unknown'}`,
      `solution_quality=${formatConfidence(signal.solutionQuality ?? 0)}`,
      `solver_quality=${formatConfidence(signal.solverQuality ?? 0)}`,
      `success_rate=${formatConfidence(signal.successRate ?? 0)}`,
      `improvement_ratio=${formatConfidence(signal.improvementRatio ?? 0)}`
    );
  }

  return parts.join('; ');
}

function toSignalMetadata(signal: LearningSignal) {
  return {
    task_type: signal.taskType,
    source: signal.source,
    intent: signal.intent,
    request_id: signal.requestId,
    success_score: signal.successScore,
    prompt_effectiveness: signal.promptEffectiveness,
    model_performance: signal.modelPerformance,
    source_count: signal.sourceCount,
    citation_count: signal.citationCount,
    query_length: signal.queryLength,
    routing_mode: signal.routingMode,
    reasoning_depth: signal.reasoningDepth,
    teacher_strategy: signal.teacherStrategy,
    evaluator_notes: signal.evaluatorNotes,
    discard_reason: signal.discardReason,
    decision_mode: signal.decisionMode,
    problem_type: signal.problemType,
    solver_used: signal.solverUsed,
    solver_backend: signal.solverBackend,
    solver_latency_ms: signal.solverLatencyMs,
    baseline_cost: signal.baselineCost,
    selected_cost: signal.selectedCost,
    solution_quality: signal.solutionQuality,
    solver_quality: signal.solverQuality,
    success_rate: signal.successRate,
    improvement_ratio: signal.improvementRatio,
    solver_status: signal.solverStatus,
    preferred_solver: signal.preferredSolver,
    problem_objective: signal.problemObjective,
    problem_complexity: signal.problemComplexity,
    estimated_space: signal.estimatedSpace,
    problem_size: signal.problemSize,
    solver_strategy: signal.solverStrategy,
    model_id: signal.modelId,
    model_provider: signal.modelProvider,
    feedback: signal.feedback,
    sanitized_summary: signal.sanitizedSummary,
  };
}

function buildArtifactVersion(signal: LearningSignal, artifactType: ControlPlaneLearningArtifactType) {
  const modelKey = sanitizeSegment(signal.modelId ?? signal.modelProvider ?? 'unknown');
  const spaceKey = sanitizeSegment(signal.spaceId);
  return `learning-${artifactType}-${signal.taskType}-${spaceKey}-${modelKey}`;
}

function mergeSourceEventIds(existing: string[], next: string[]) {
  return joinUnique([...existing, ...next]);
}

function mergeConfidence(existingConfidence: number, existingCount: number, nextConfidence: number, nextCount: number) {
  const totalCount = existingCount + nextCount;
  if (totalCount <= 0) {
    return round2(nextConfidence);
  }

  return round2(((existingConfidence * existingCount) + (nextConfidence * nextCount)) / totalCount);
}

function parseSourceEventIds(value: unknown) {
  if (Array.isArray(value)) {
    return parseStringArray(value);
  }

  if (typeof value === 'string' && value.trim().length > 0) {
    try {
      const parsed = JSON.parse(value);
      return parseSourceEventIds(parsed);
    } catch {
      return [value.trim()];
    }
  }

  if (isRecord(value) && Array.isArray(value.source_event_ids)) {
    return parseStringArray(value.source_event_ids);
  }

  return [];
}

export function deriveLearningSignal(input: LearningSignalInput): LearningSignal {
  const sourceCount = toPositiveInteger(input.metadata?.source_count);
  const citationCount = toPositiveInteger(input.metadata?.citation_count);
  const successScore = input.success
    ? Math.max(input.score, input.accepted ? 0.85 : 0.7)
    : Math.min(input.score * 0.6, 0.4);
  const promptEffectiveness = round2(
    (input.success ? 0.55 : 0.2) +
      Math.min(0.15, sourceCount * 0.05) +
      Math.min(0.15, citationCount * 0.05) +
      (input.accepted ? 0.1 : 0)
  );
  const latencyPenalty = Math.min(0.2, input.latencyMs / 30_000);
  const modelPerformance = round2(
    Math.max(
      0,
      (input.success ? 0.65 : 0.2) +
        (input.score * 0.25) +
        (input.accepted ? 0.05 : 0) -
        latencyPenalty
    )
  );
  const failureReason =
    input.failureReason?.trim() ||
    (typeof input.metadata?.discardReason === 'string' ? String(input.metadata.discardReason).trim() : '') ||
    (typeof input.metadata?.evaluatorNotes === 'string' ? String(input.metadata.evaluatorNotes).trim() : '') ||
    undefined;
  const quantumFields = {
    decisionMode: readMetadataString(input.metadata, 'decision_mode'),
    problemType: readMetadataString(input.metadata, 'problem_type'),
    problemObjective: readMetadataString(input.metadata, 'problem_objective'),
    problemComplexity: readMetadataString(input.metadata, 'problem_complexity'),
    solverUsed: readMetadataString(input.metadata, 'solver_used'),
    solverBackend: readMetadataString(input.metadata, 'solver_backend'),
    solverLatencyMs: toFiniteNumber(input.metadata?.solver_latency_ms),
    baselineCost: toFiniteNumber(input.metadata?.baseline_cost),
    selectedCost: toFiniteNumber(input.metadata?.selected_cost),
    solutionQuality: toFiniteNumber(input.metadata?.solution_quality),
    solverQuality: toFiniteNumber(input.metadata?.solver_quality),
    successRate: toFiniteNumber(input.metadata?.success_rate),
    improvementRatio: toFiniteNumber(input.metadata?.improvement_ratio),
    solverStatus: readMetadataString(input.metadata, 'solver_status'),
    preferredSolver: readMetadataString(input.metadata, 'preferred_solver'),
    estimatedSpace: toFiniteNumber(input.metadata?.estimated_space),
    problemSize: toPositiveInteger(input.metadata?.problem_size),
    solverStrategy: readMetadataString(input.metadata, 'solver_strategy'),
  };

  return {
    accountId: input.accountId,
    spaceId: input.spaceId?.trim() || input.accountId,
    eventId: input.eventId,
    requestId: input.requestId,
    source: input.source,
    intent: input.intent,
    taskType: input.taskType,
    successScore: round2(successScore),
    failureReason,
    promptEffectiveness,
    modelPerformance,
    feedback: input.feedback ?? {},
    isSafeForLearning: input.isSafeForLearning,
    modelId: input.modelId,
    modelProvider: input.modelProvider,
    latencyMs: input.latencyMs,
    score: round2(input.score),
    accepted: input.accepted,
    sourceCount,
    citationCount,
    queryLength: toPositiveInteger(input.metadata?.queryLength),
    reasoningDepth: typeof input.metadata?.reasoningDepth === 'string' ? String(input.metadata.reasoningDepth) : undefined,
    routingMode: typeof input.metadata?.routingMode === 'string' ? String(input.metadata.routingMode) : undefined,
    teacherStrategy: typeof input.metadata?.teacherStrategy === 'string' ? String(input.metadata.teacherStrategy) : undefined,
    evaluatorNotes: typeof input.metadata?.evaluatorNotes === 'string' ? String(input.metadata.evaluatorNotes) : undefined,
    discardReason: typeof input.metadata?.discardReason === 'string' ? String(input.metadata.discardReason) : undefined,
    ...quantumFields,
    createdAt: input.createdAt ?? new Date().toISOString(),
    promptHint: buildPromptHint({
      accountId: input.accountId,
      spaceId: input.spaceId ?? input.accountId,
      eventId: input.eventId,
      requestId: input.requestId,
      source: input.source,
      intent: input.intent,
      taskType: input.taskType,
      successScore: round2(successScore),
      failureReason,
      promptEffectiveness,
      modelPerformance,
      feedback: input.feedback ?? {},
      isSafeForLearning: input.isSafeForLearning,
      modelId: input.modelId,
      modelProvider: input.modelProvider,
      latencyMs: input.latencyMs,
      score: round2(input.score),
      accepted: input.accepted,
      sourceCount,
      citationCount,
      queryLength: toPositiveInteger(input.metadata?.queryLength),
      reasoningDepth: typeof input.metadata?.reasoningDepth === 'string' ? String(input.metadata.reasoningDepth) : undefined,
      routingMode: typeof input.metadata?.routingMode === 'string' ? String(input.metadata.routingMode) : undefined,
      teacherStrategy: typeof input.metadata?.teacherStrategy === 'string' ? String(input.metadata.teacherStrategy) : undefined,
      evaluatorNotes: typeof input.metadata?.evaluatorNotes === 'string' ? String(input.metadata.evaluatorNotes) : undefined,
      discardReason: typeof input.metadata?.discardReason === 'string' ? String(input.metadata.discardReason) : undefined,
      ...quantumFields,
      createdAt: input.createdAt ?? new Date().toISOString(),
      promptHint: '',
      routingHint: '',
      toolUsagePattern: '',
      sanitizedSummary: '',
    }),
    routingHint: buildRoutingHint({
      accountId: input.accountId,
      spaceId: input.spaceId ?? input.accountId,
      eventId: input.eventId,
      requestId: input.requestId,
      source: input.source,
      intent: input.intent,
      taskType: input.taskType,
      successScore: round2(successScore),
      failureReason,
      promptEffectiveness,
      modelPerformance,
      feedback: input.feedback ?? {},
      isSafeForLearning: input.isSafeForLearning,
      modelId: input.modelId,
      modelProvider: input.modelProvider,
      latencyMs: input.latencyMs,
      score: round2(input.score),
      accepted: input.accepted,
      sourceCount,
      citationCount,
      queryLength: toPositiveInteger(input.metadata?.queryLength),
      reasoningDepth: typeof input.metadata?.reasoningDepth === 'string' ? String(input.metadata.reasoningDepth) : undefined,
      routingMode: typeof input.metadata?.routingMode === 'string' ? String(input.metadata.routingMode) : undefined,
      teacherStrategy: typeof input.metadata?.teacherStrategy === 'string' ? String(input.metadata.teacherStrategy) : undefined,
      evaluatorNotes: typeof input.metadata?.evaluatorNotes === 'string' ? String(input.metadata.evaluatorNotes) : undefined,
      discardReason: typeof input.metadata?.discardReason === 'string' ? String(input.metadata.discardReason) : undefined,
      ...quantumFields,
      createdAt: input.createdAt ?? new Date().toISOString(),
      promptHint: '',
      routingHint: '',
      toolUsagePattern: '',
      sanitizedSummary: '',
    }),
    toolUsagePattern: buildToolUsagePattern({
      accountId: input.accountId,
      spaceId: input.spaceId ?? input.accountId,
      eventId: input.eventId,
      requestId: input.requestId,
      source: input.source,
      intent: input.intent,
      taskType: input.taskType,
      successScore: round2(successScore),
      failureReason,
      promptEffectiveness,
      modelPerformance,
      feedback: input.feedback ?? {},
      isSafeForLearning: input.isSafeForLearning,
      modelId: input.modelId,
      modelProvider: input.modelProvider,
      latencyMs: input.latencyMs,
      score: round2(input.score),
      accepted: input.accepted,
      sourceCount,
      citationCount,
      queryLength: toPositiveInteger(input.metadata?.queryLength),
      reasoningDepth: typeof input.metadata?.reasoningDepth === 'string' ? String(input.metadata.reasoningDepth) : undefined,
      routingMode: typeof input.metadata?.routingMode === 'string' ? String(input.metadata.routingMode) : undefined,
      teacherStrategy: typeof input.metadata?.teacherStrategy === 'string' ? String(input.metadata.teacherStrategy) : undefined,
      evaluatorNotes: typeof input.metadata?.evaluatorNotes === 'string' ? String(input.metadata.evaluatorNotes) : undefined,
      discardReason: typeof input.metadata?.discardReason === 'string' ? String(input.metadata.discardReason) : undefined,
      ...quantumFields,
      createdAt: input.createdAt ?? new Date().toISOString(),
      promptHint: '',
      routingHint: '',
      toolUsagePattern: '',
      sanitizedSummary: '',
    }),
    sanitizedSummary: buildSanitizedSummary({
      accountId: input.accountId,
      spaceId: input.spaceId ?? input.accountId,
      eventId: input.eventId,
      requestId: input.requestId,
      source: input.source,
      intent: input.intent,
      taskType: input.taskType,
      successScore: round2(successScore),
      failureReason,
      promptEffectiveness,
      modelPerformance,
      feedback: input.feedback ?? {},
      isSafeForLearning: input.isSafeForLearning,
      modelId: input.modelId,
      modelProvider: input.modelProvider,
      latencyMs: input.latencyMs,
      score: round2(input.score),
      accepted: input.accepted,
      sourceCount,
      citationCount,
      queryLength: toPositiveInteger(input.metadata?.queryLength),
      reasoningDepth: typeof input.metadata?.reasoningDepth === 'string' ? String(input.metadata.reasoningDepth) : undefined,
      routingMode: typeof input.metadata?.routingMode === 'string' ? String(input.metadata.routingMode) : undefined,
      teacherStrategy: typeof input.metadata?.teacherStrategy === 'string' ? String(input.metadata.teacherStrategy) : undefined,
      evaluatorNotes: typeof input.metadata?.evaluatorNotes === 'string' ? String(input.metadata.evaluatorNotes) : undefined,
      discardReason: typeof input.metadata?.discardReason === 'string' ? String(input.metadata.discardReason) : undefined,
      ...quantumFields,
      createdAt: input.createdAt ?? new Date().toISOString(),
      promptHint: '',
      routingHint: '',
      toolUsagePattern: '',
      sanitizedSummary: '',
    }),
  };
}

export function buildLearningArtifacts(signal: LearningSignal): LearningArtifactDraft[] {
  if (!signal.isSafeForLearning) {
    return [];
  }

  const now = new Date().toISOString();
  const modelKey = sanitizeSegment(signal.modelId ?? signal.modelProvider ?? 'unknown');
  const signalMetadata = toSignalMetadata(signal);
  const baseMetadata = {
    ...signalMetadata,
    account_id: signal.accountId,
    space_id: signal.spaceId,
    event_id: signal.eventId,
    request_id: signal.requestId,
    task_type: signal.taskType,
    source: signal.source,
    intent: signal.intent,
    model_id: signal.modelId,
    model_provider: signal.modelProvider,
    success_score: signal.successScore,
    prompt_effectiveness: signal.promptEffectiveness,
    model_performance: signal.modelPerformance,
    source_count: signal.sourceCount,
    citation_count: signal.citationCount,
    query_length: signal.queryLength,
    routing_mode: signal.routingMode,
    reasoning_depth: signal.reasoningDepth,
    teacher_strategy: signal.teacherStrategy,
    evaluator_notes: signal.evaluatorNotes,
    discard_reason: signal.discardReason,
    decision_mode: signal.decisionMode,
    problem_type: signal.problemType,
    solver_used: signal.solverUsed,
    solver_backend: signal.solverBackend,
    solver_latency_ms: signal.solverLatencyMs,
    baseline_cost: signal.baselineCost,
    selected_cost: signal.selectedCost,
    solution_quality: signal.solutionQuality,
    solver_quality: signal.solverQuality,
    success_rate: signal.successRate,
    improvement_ratio: signal.improvementRatio,
    solver_status: signal.solverStatus,
    preferred_solver: signal.preferredSolver,
    problem_objective: signal.problemObjective,
    problem_complexity: signal.problemComplexity,
    estimated_space: signal.estimatedSpace,
    problem_size: signal.problemSize,
    solver_strategy: signal.solverStrategy,
    feedback: signal.feedback,
    sanitized_summary: signal.sanitizedSummary,
  };

  return [
    {
      modelVersion: buildArtifactVersion(signal, 'prompt_hint'),
      baseModel: signal.modelId ?? signal.modelProvider ?? 'unknown',
      spaceId: signal.spaceId,
      datasetSize: 1,
      score: signal.promptEffectiveness,
      active: false,
      artifactPath: `learning://prompt_hint/${signal.taskType}/${modelKey}`,
      artifactType: 'prompt_hint',
      sourceEventIds: [signal.eventId],
      confidenceScore: signal.promptEffectiveness,
      isSafeForLearning: true,
      metadata: {
        ...baseMetadata,
        prompt_hint: signal.promptHint,
      },
      createdAt: now,
      updatedAt: now,
    },
    {
      modelVersion: buildArtifactVersion(signal, 'routing_hint'),
      baseModel: signal.modelId ?? signal.modelProvider ?? 'unknown',
      spaceId: signal.spaceId,
      datasetSize: 1,
      score: signal.modelPerformance,
      active: false,
      artifactPath: `learning://routing_hint/${signal.taskType}/${modelKey}`,
      artifactType: 'routing_hint',
      sourceEventIds: [signal.eventId],
      confidenceScore: signal.modelPerformance,
      isSafeForLearning: true,
      metadata: {
        ...baseMetadata,
        routing_hint: signal.routingHint,
      },
      createdAt: now,
      updatedAt: now,
    },
    {
      modelVersion: buildArtifactVersion(signal, 'tool_usage_pattern'),
      baseModel: signal.modelId ?? signal.modelProvider ?? 'unknown',
      spaceId: signal.spaceId,
      datasetSize: 1,
      score: round2((signal.promptEffectiveness + signal.modelPerformance) / 2),
      active: false,
      artifactPath: `learning://tool_usage_pattern/${signal.taskType}/${modelKey}`,
      artifactType: 'tool_usage_pattern',
      sourceEventIds: [signal.eventId],
      confidenceScore: round2((signal.promptEffectiveness + signal.modelPerformance) / 2),
      isSafeForLearning: true,
      metadata: {
        ...baseMetadata,
        tool_usage_pattern: signal.toolUsagePattern,
      },
      createdAt: now,
      updatedAt: now,
    },
  ];
}

async function readExistingArtifact(poolUrl: string, modelVersion: string) {
  const pool = getControlPlanePool(poolUrl);
  const result = await pool.query<LearningArtifactRow>(
    `
        SELECT model_version, source_event_ids, confidence_score, created_at
        FROM model_artifacts
        WHERE model_version = $1
      LIMIT 1
    `,
    [modelVersion]
  );

  return result.rows[0] ?? null;
}

export async function persistLearningArtifacts(databaseUrl: string | undefined, drafts: LearningArtifactDraft[]) {
  const normalizedDatabaseUrl = databaseUrl?.trim() || process.env.DATABASE_URL?.trim() || '';
  if (!normalizedDatabaseUrl || drafts.length === 0) {
    return;
  }

  const pool = getControlPlanePool(normalizedDatabaseUrl);

  for (const draft of drafts) {
    const existing = await readExistingArtifact(normalizedDatabaseUrl, draft.modelVersion).catch(() => null);
    const existingIds = existing ? parseSourceEventIds(existing.source_event_ids) : [];
    const mergedIds = mergeSourceEventIds(existingIds, draft.sourceEventIds);
    const existingConfidence = existing ? Number(existing.confidence_score ?? 0) : draft.confidenceScore;
    const mergedConfidence = mergeConfidence(existingConfidence, existingIds.length, draft.confidenceScore, draft.sourceEventIds.length);
    const createdAt = existing?.created_at ? new Date(String(existing.created_at)).toISOString() : draft.createdAt;

    await pool.query(
      `
        INSERT INTO model_artifacts (
          model_version,
          base_model,
          space_id,
          dataset_size,
          loss,
          score,
          active,
          artifact_path,
          artifact_type,
          source_event_ids,
          confidence_score,
          is_safe_for_learning,
          metadata,
          created_at,
          updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12, $13::jsonb, $14::timestamptz, $15::timestamptz)
        ON CONFLICT (model_version) DO UPDATE SET
          base_model = EXCLUDED.base_model,
          space_id = EXCLUDED.space_id,
          dataset_size = EXCLUDED.dataset_size,
          loss = EXCLUDED.loss,
          score = EXCLUDED.score,
          active = EXCLUDED.active,
          artifact_path = EXCLUDED.artifact_path,
          artifact_type = EXCLUDED.artifact_type,
          source_event_ids = EXCLUDED.source_event_ids,
          confidence_score = EXCLUDED.confidence_score,
          is_safe_for_learning = EXCLUDED.is_safe_for_learning,
          metadata = EXCLUDED.metadata,
          updated_at = EXCLUDED.updated_at
      `,
      [
        draft.modelVersion,
        draft.baseModel,
        draft.spaceId,
        mergedIds.length,
        null,
        draft.score,
        draft.active,
        draft.artifactPath,
        draft.artifactType,
        JSON.stringify(mergedIds),
        mergedConfidence,
        draft.isSafeForLearning,
        JSON.stringify({
          ...draft.metadata,
          source_event_ids: mergedIds,
          confidence_score: mergedConfidence,
        }),
        createdAt,
        draft.updatedAt,
      ]
    );
  }
}

function formatArtifactHintRow(row: LearningArtifactLookupRow) {
  const metadata = isRecord(row.metadata) ? row.metadata : {};
  const artifactType = row.artifact_type ?? 'brain_model';
  const confidenceScore = Number(row.confidence_score ?? 0);
  const sourceEventIds = parseSourceEventIds(row.source_event_ids);
  const hint =
    typeof metadata.prompt_hint === 'string'
      ? metadata.prompt_hint
      : typeof metadata.routing_hint === 'string'
        ? metadata.routing_hint
        : typeof metadata.tool_usage_pattern === 'string'
          ? metadata.tool_usage_pattern
          : '';

  if (!hint.trim()) {
    return null;
  }

  const tagParts = [
    `learning:${artifactType}`,
    `confidence=${formatConfidence(confidenceScore)}`,
    `sources=${sourceEventIds.length}`,
  ];

  const taskType = typeof metadata.task_type === 'string' ? metadata.task_type : undefined;
  if (taskType) {
    tagParts.push(`task=${taskType}`);
  }

  return `[${tagParts.join(' ')}] ${normalizeText(hint)}`;
}

export async function loadLearningPromptHints(input: {
  taskType: ControlPlaneTaskIntent;
  modelId?: string;
  spaceId?: string;
  limit?: number;
}) {
  const databaseUrl = process.env.DATABASE_URL?.trim() || '';
  if (!databaseUrl) {
    return [];
  }

  try {
    const pool = getControlPlanePool(databaseUrl);
    const limit = Math.max(1, Math.min(input.limit ?? 6, 12));
    const modelId = input.modelId?.trim() || '';

    const result = await pool.query<LearningArtifactLookupRow>(
      `
        SELECT model_version, artifact_type, base_model, space_id, source_event_ids, confidence_score, metadata, created_at
        FROM model_artifacts
        WHERE is_safe_for_learning = true
          AND artifact_type IN ('prompt_hint', 'routing_hint', 'tool_usage_pattern')
          AND (metadata->>'task_type' = $1 OR metadata->>'task_type' IS NULL)
          AND ($2 = '' OR metadata->>'model_id' = $2 OR base_model = $2)
          AND ($3 = '' OR space_id = $3 OR space_id = 'global')
        ORDER BY confidence_score DESC, created_at DESC
        LIMIT $4
      `,
      [input.taskType, modelId, input.spaceId?.trim() || '', limit]
    );

    return result.rows
      .map(formatArtifactHintRow)
      .filter((hint): hint is string => typeof hint === 'string' && hint.trim().length > 0);
  } catch {
    return [];
  }
}

export async function loadLearningRoutingHints(input: {
  taskType: ControlPlaneTaskIntent;
  modelId?: string;
  spaceId?: string;
  limit?: number;
}): Promise<{
  routingMode?: ModelRoutingMode;
  preferredModelId?: string;
  reason?: string;
}> {
  const hints = await loadLearningPromptHints(input);
  if (hints.length === 0) {
    return {};
  }

  const joined = hints.join(' ').toLowerCase();
  if (joined.includes('local-first') || joined.includes('local first')) {
    return {
      routingMode: 'local_first',
      reason: 'learning hint prefers local-first routing',
    };
  }

  if (joined.includes('cloud-preferred') || joined.includes('cloud preferred') || joined.includes('retrieval-first')) {
    return {
      routingMode: 'cloud_preferred',
      reason: 'learning hint prefers cloud-preferred routing',
    };
  }

  if (joined.includes('balanced')) {
    return {
      routingMode: 'balanced',
      reason: 'learning hint prefers balanced routing',
    };
  }

  return {
    routingMode: 'local_first',
    reason: 'default learning routing bias',
  };
}

export function buildLearningRetrievalText(signal: LearningSignal, artifacts: LearningArtifactDraft[]) {
  const hintMap = new Map<ControlPlaneLearningArtifactType, string>();

  for (const artifact of artifacts) {
    const metadata = artifact.metadata;
    const value =
      typeof metadata.prompt_hint === 'string'
        ? metadata.prompt_hint
        : typeof metadata.routing_hint === 'string'
          ? metadata.routing_hint
          : typeof metadata.tool_usage_pattern === 'string'
            ? metadata.tool_usage_pattern
            : '';

    if (value.trim().length > 0) {
      hintMap.set(artifact.artifactType, value);
    }
  }

  return [
    `task_type: ${signal.taskType}`,
    `space_id: ${signal.spaceId}`,
    `intent: ${signal.intent}`,
    `success_score: ${formatConfidence(signal.successScore)}`,
    `prompt_effectiveness: ${formatConfidence(signal.promptEffectiveness)}`,
    `model_performance: ${formatConfidence(signal.modelPerformance)}`,
    `latency_ms: ${signal.latencyMs}`,
    `source_count: ${signal.sourceCount}`,
    `citation_count: ${signal.citationCount}`,
    signal.problemObjective ? `problem_objective: ${signal.problemObjective}` : '',
    signal.problemComplexity ? `problem_complexity: ${signal.problemComplexity}` : '',
    signal.problemSize ? `problem_size: ${signal.problemSize}` : '',
    signal.estimatedSpace ? `estimated_space: ${signal.estimatedSpace}` : '',
    signal.solverStrategy ? `solver_strategy: ${signal.solverStrategy}` : '',
    signal.failureReason ? `failure_reason: ${signal.failureReason}` : '',
    hintMap.get('prompt_hint') ? `prompt_hint: ${hintMap.get('prompt_hint')}` : '',
    hintMap.get('routing_hint') ? `routing_hint: ${hintMap.get('routing_hint')}` : '',
    hintMap.get('tool_usage_pattern') ? `tool_usage_pattern: ${hintMap.get('tool_usage_pattern')}` : '',
    `summary: ${signal.sanitizedSummary}`,
  ]
    .filter((entry) => typeof entry === 'string' && entry.trim().length > 0)
    .join('\n');
}
