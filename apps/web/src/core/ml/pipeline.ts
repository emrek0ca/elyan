import { generateObject, type LanguageModel } from 'ai';
import { z } from 'zod';
import { evaluateReasoningOutcome } from '@/core/reasoning';
import type { OrchestrationPlan } from '@/core/orchestration';
import { registry } from '@/core/providers';

export type MlDatabaseAccountRow = {
  account_id: string;
  display_name: string;
  owner_type: string;
  status: string;
  plan_id: string;
  subscription_status: string;
  interaction_state: unknown;
  updated_at: string;
};

export type MlDatabaseEvaluationSignalRow = {
  signal_id: string;
  account_id: string;
  request_id: string | null;
  payload: unknown;
  created_at: string;
};

export type MlDatabaseLearningEventRow = {
  event_id: string;
  account_id: string;
  request_id: string;
  source: string;
  input: string;
  intent: string;
  plan: string;
  reasoning_steps: unknown;
  reasoning_trace: unknown;
  output: string;
  better_output: string | null;
  success: boolean;
  failure_reason: string | null;
  latency_ms: number;
  score: number;
  accepted: boolean;
  model_id: string | null;
  model_provider: string | null;
  metadata: unknown;
  created_at: string;
};

export type MlDatasetCandidateSource = 'request' | 'interaction' | 'learning';

export type MlDatasetCandidate = {
  account_id: string;
  account_display_name: string;
  owner_type: string;
  account_status: string;
  plan_id: string;
  subscription_status: string;
  thread_id?: string;
  request_id?: string;
  source: MlDatasetCandidateSource;
  instruction: string;
  input: string;
  output: string;
  better_output?: string;
  plan: string;
  reasoning_trace: string[];
  success: boolean;
  failure_reason?: string;
  quality: 'good' | 'mixed' | 'poor' | 'skipped';
  latency_ms?: number;
  metadata: Record<string, unknown>;
};

export type MlTeacherDraft = {
  better_output: string;
  reasoning_trace: string[];
  score: number;
  failure_reason?: string;
  evaluation: string;
  teacher_strategy: 'llm';
};

export type MlQualityAssessment = {
  better_output: string;
  reasoning_trace: string[];
  score: number;
  accepted: boolean;
  evaluator_notes: string;
  discard_reason?: string;
  teacher_strategy: 'llm' | 'missing';
};

export type MlDatasetRecord = MlDatasetCandidate & MlTeacherDraft & {
  model_role: 'generator' | 'teacher' | 'evaluator';
  accepted: boolean;
  evaluator_notes: string;
  discard_reason?: string;
  created_at: string;
};

export type MlTeacherModel = {
  modelId: string;
  model: LanguageModel;
};

const teacherCompletionSchema = z.object({
  better_output: z.string().min(1),
  reasoning_trace: z.array(z.string().min(1)).default([]),
  score: z.number().min(0).max(1).default(0.7),
  failure_reason: z.string().min(1).optional(),
  evaluation: z.string().min(1).default('Teacher model rewrote the response successfully.'),
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asString(value: unknown, fallback = '') {
  return typeof value === 'string' ? value : fallback;
}

function normalizeWhitespace(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function readSignalPayload(payload: unknown) {
  if (!isRecord(payload)) {
    return {};
  }

  return payload;
}

function readNumber(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function buildPlanSummary(input: {
  intent: string;
  routingMode: string;
  reasoningDepth: string;
  source: MlDatasetCandidateSource;
  quality: MlDatasetCandidate['quality'];
}) {
  return [
    `intent=${input.intent}`,
    `routing=${input.routingMode}`,
    `depth=${input.reasoningDepth}`,
    `source=${input.source}`,
    `quality=${input.quality}`,
  ].join('; ');
}

function inferInstruction(candidate: Pick<MlDatasetCandidate, 'source' | 'quality'>) {
  if (candidate.source === 'request') {
    return candidate.quality === 'poor'
      ? 'Rewrite the failed answer into a grounded, safer, and more complete response.'
      : 'Improve the assistant answer using the learning event as a training example.';
  }

  if (candidate.source === 'learning') {
    return 'Turn this learning draft into a reusable teaching example and tighten the answer.';
  }

  return candidate.quality === 'poor'
    ? 'Rewrite the assistant answer into a stronger, safer, and more direct response.'
    : 'Rewrite the assistant answer to be clearer, more useful, and better aligned with the request.';
}

function summarizeSignal(candidate: MlDatasetCandidate) {
  const parts = [
    `intent=${candidate.metadata.intent ?? 'unknown'}`,
    `routing=${candidate.metadata.routing_mode ?? 'local_first'}`,
    `depth=${candidate.metadata.reasoning_depth ?? 'standard'}`,
    `quality=${candidate.quality}`,
  ];

  if (typeof candidate.latency_ms === 'number') {
    parts.push(`latency=${candidate.latency_ms}ms`);
  }

  return parts.join('; ');
}

function buildReasoningTrace(candidate: MlDatasetCandidate) {
  const trace = candidate.reasoning_trace.slice();

  if (trace.length === 0) {
    trace.push(`input: ${candidate.input.slice(0, 200)}`);
  }

  trace.push(`plan: ${candidate.plan}`);
  trace.push(`observe: ${summarizeSignal(candidate)}`);
  trace.push(`refine: ${candidate.failure_reason ? candidate.failure_reason : 'retain learning-safe answer'}`);

  return trace;
}

function evaluateCandidate(candidate: MlDatasetCandidate, betterOutput: string) {
  const outputLength = candidate.output.trim().length;
  const betterLength = betterOutput.trim().length;
  const lengthDelta = Math.min(0.15, Math.max(-0.1, (betterLength - outputLength) / Math.max(1, outputLength) / 5));
  const qualityBase =
    candidate.quality === 'good' ? 0.85 : candidate.quality === 'mixed' ? 0.7 : candidate.quality === 'poor' ? 0.45 : 0.6;
  return Number(Math.max(0, Math.min(1, qualityBase + lengthDelta)).toFixed(2));
}

export function buildInteractionTrace(candidate: MlDatasetCandidate) {
  return buildReasoningTrace(candidate);
}

export function buildDatasetRecord(candidate: MlDatasetCandidate, draft: MlTeacherDraft): MlDatasetRecord {
  return {
    ...candidate,
    ...draft,
    reasoning_trace: draft.reasoning_trace.length > 0 ? draft.reasoning_trace : buildReasoningTrace(candidate),
    model_role: 'teacher',
    accepted: draft.score >= 0.6,
    evaluator_notes: draft.evaluation,
    created_at: new Date().toISOString(),
  };
}

export function buildTeacherPrompt(candidate: MlDatasetCandidate) {
  return [
    'You are Elyan brain teacher model.',
    'Improve the answer without inventing private local context.',
    'Keep the response grounded in the provided input, output, plan, and trace.',
    'Return a concise but higher-quality response and a short reasoning trace.',
    '',
    `instruction: ${candidate.instruction}`,
    `input: ${candidate.input}`,
    `output: ${candidate.output}`,
    `plan: ${candidate.plan}`,
    `trace: ${candidate.reasoning_trace.join(' | ')}`,
  ].join('\n');
}

export async function resolveTeacherModel(): Promise<MlTeacherModel | null> {
  try {
    const modelId = await registry.resolvePreferredModelId({ routingMode: 'cloud_preferred' });
    const { model } = registry.resolveModel(modelId);
    return { modelId, model };
  } catch {
    return null;
  }
}

export async function generateTeacherDraft(
  candidate: MlDatasetCandidate,
  teacherModel?: MlTeacherModel | null
): Promise<MlTeacherDraft | null> {
  if (!teacherModel) {
    return null;
  }

  try {
    const result = await generateObject({
      model: teacherModel.model,
      schema: teacherCompletionSchema,
      temperature: 0.2,
      system: [
        'You are Elyan\'s teacher model for self-improvement.',
        'Rewrite the answer to be better than the generator output.',
        'Do not add private local context or unsupported claims.',
        'Prefer concise, direct, instruction-following answers.',
      ].join('\n'),
      prompt: buildTeacherPrompt(candidate),
    });

    const draft = result.object;
    return {
      better_output: normalizeWhitespace(draft.better_output || candidate.output),
      reasoning_trace: draft.reasoning_trace.length > 0 ? draft.reasoning_trace : buildReasoningTrace(candidate),
      score: draft.score,
      failure_reason: draft.failure_reason ?? candidate.failure_reason,
      evaluation: draft.evaluation,
      teacher_strategy: 'llm',
    };
  } catch {
    return null;
  }
}

export function evaluateTeacherDraft(candidate: MlDatasetCandidate, draft: MlTeacherDraft): MlQualityAssessment {
  const qualityPlan = {
    stages: [],
    searchRounds: 0,
    maxUrls: 0,
    temperature: 0,
    reasoningDepth: (candidate.metadata.reasoning_depth as string) || 'standard',
    taskIntent: (candidate.metadata.intent as string) || 'direct_answer',
    intentConfidence: 'medium',
    uncertainty: 'medium',
    routingMode: (candidate.metadata.routing_mode as string) || 'local_first',
    expandSearchQueries: false,
    retrieval: {
      rounds: 0,
      maxUrls: 0,
      rerankTopK: 0,
      language: 'en',
      expandSearchQueries: false,
    },
    capabilityPolicy: [],
    evaluation: {
      collectRetrievalSignals: false,
      collectToolSignals: false,
      captureUsageSignals: false,
      promoteLearnings: true,
    },
    usageBudget: {
      inference: 0,
      retrieval: 0,
      integrations: 0,
      evaluation: 0,
    },
    executionMode: 'single',
    teamPolicy: {
      enabledByDefault: false,
      reasons: [],
      maxConcurrentAgents: 0,
      maxTasksPerRun: 0,
      allowCloudEscalation: false,
      modelRoutingMode: 'local_only',
      riskBoundary: 'read_only',
      requiredRoles: [],
    },
    surface: 'shared-vps',
    mode: 'speed',
    executionPolicy: {
      preferredOrder: [],
      primary: {
        kind: 'direct_answer',
        source: 'none',
        reason: 'quality assessment',
        requiresConfirmation: false,
      },
      candidates: [],
      shouldRetrieve: false,
      shouldDiscoverMcp: false,
      shouldEscalateModel: false,
      requiresConfirmation: false,
      decisionSummary: 'quality assessment',
      notes: [],
    },
    skillPolicy: {
      selectedSkillId: 'quality_assessment',
      selectedSkillTitle: 'Quality assessment',
      selectedSkillVersion: '1',
      resultShape: 'answer',
      policyBoundary: 'workspace',
      preferredCapabilityIds: [],
      requiresConfirmation: false,
      decisionSummary: 'quality assessment',
      notes: [],
      candidates: [],
      stages: [],
      selectedTechniques: [],
    },
  } as OrchestrationPlan;

  const reasoningEvaluation = evaluateReasoningOutcome({
    input: candidate.input,
    intent: (candidate.metadata.intent as string) || 'direct_answer',
    plan: qualityPlan,
    output: draft.better_output,
    success: candidate.success,
    failureReason: draft.failure_reason ?? candidate.failure_reason,
    latencyMs: candidate.latency_ms ?? 0,
    citationCount: Number(candidate.metadata.citation_count ?? 0),
    toolCallCount: Number(candidate.metadata.tool_call_count ?? 0),
  });

  const score = Number(
    Math.max(
      0,
      Math.min(
        1,
        (draft.score + reasoningEvaluation.score) / 2
      )
    ).toFixed(2)
  );
  const accepted = score >= 0.6;

  return {
    better_output: draft.better_output,
    reasoning_trace: draft.reasoning_trace.length > 0 ? draft.reasoning_trace : buildReasoningTrace(candidate),
    score,
    accepted,
    evaluator_notes: draft.evaluation,
    discard_reason: accepted ? undefined : 'score_below_threshold',
    teacher_strategy: draft.teacher_strategy,
  };
}

export async function buildQualityAssessment(
  candidate: MlDatasetCandidate,
  teacherModel?: MlTeacherModel | null
): Promise<MlQualityAssessment> {
  const draft = await generateTeacherDraft(candidate, teacherModel);
  if (!draft) {
    return {
      better_output: '',
      reasoning_trace: [],
      score: 0,
      accepted: false,
      evaluator_notes: 'Teacher model unavailable; sample discarded.',
      discard_reason: 'teacher_unavailable',
      teacher_strategy: 'missing',
    };
  }

  return evaluateTeacherDraft(candidate, draft);
}

function parseMessages(value: unknown) {
  if (!isRecord(value)) {
    return [];
  }

  const messages = Array.isArray(value.messages) ? value.messages : [];
  return messages
    .filter(isRecord)
    .map((message) => ({
      messageId: asString(message.messageId),
      threadId: asString(message.threadId),
      role: asString(message.role),
      content: asString(message.content).trim(),
      createdAt: asString(message.createdAt),
      metadata: isRecord(message.metadata) ? message.metadata : {},
    }))
    .filter((message) => message.threadId && message.content && (message.role === 'user' || message.role === 'assistant'))
    .sort((left, right) => Date.parse(left.createdAt || '') - Date.parse(right.createdAt || ''));
}

function parseThreads(value: unknown) {
  if (!isRecord(value)) {
    return [];
  }

  const threads = Array.isArray(value.threads) ? value.threads : [];
  return threads
    .filter(isRecord)
    .map((thread) => ({
      threadId: asString(thread.threadId),
      intent: asString(thread.intent) || 'direct_answer',
      title: asString(thread.title) || 'Untitled thread',
      summary: asString(thread.summary),
      source: asString(thread.source) || 'answer_engine',
      metadata: isRecord(thread.metadata) ? thread.metadata : {},
    }))
    .filter((thread) => thread.threadId.length > 0);
}

function parseLearningDrafts(value: unknown) {
  if (!isRecord(value)) {
    return [];
  }

  const drafts = Array.isArray(value.learningDrafts) ? value.learningDrafts : [];
  return drafts
    .filter(isRecord)
    .map((draft) => ({
      draftId: asString(draft.draftId),
      threadId: asString(draft.threadId),
      kind: asString(draft.kind) || 'preference',
      title: asString(draft.title) || 'Learning draft',
      summary: asString(draft.summary),
      body: asString(draft.body),
      status: asString(draft.status) || 'draft',
      metadata: isRecord(draft.metadata) ? draft.metadata : {},
    }))
    .filter((draft) => draft.draftId.length > 0 && draft.body.length > 0);
}

function buildCandidateFromMessagePair(input: {
  account: MlDatabaseAccountRow;
  thread: ReturnType<typeof parseThreads>[number];
  userMessage: ReturnType<typeof parseMessages>[number];
  assistantMessage: ReturnType<typeof parseMessages>[number];
  signal?: MlDatabaseEvaluationSignalRow & { payload: Record<string, unknown> };
}): MlDatasetCandidate {
  const signalPayload = input.signal?.payload ?? {};
  const modelPayload = isRecord(signalPayload.model) ? signalPayload.model : {};
  const retrievalPayload = isRecord(signalPayload.retrieval) ? signalPayload.retrieval : {};
  const toolingPayload = isRecord(signalPayload.tooling) ? signalPayload.tooling : {};
  const intent = asString(input.thread.metadata.intent) || input.thread.intent;
  const routingMode = asString(signalPayload.routingMode) || 'local_first';
  const reasoningDepth = asString(signalPayload.reasoningDepth) || 'standard';
  const quality = (asString(signalPayload.quality) as MlDatasetCandidate['quality']) || 'mixed';
  const requestId =
    asString(input.signal?.request_id) ||
    asString(input.userMessage.metadata.requestId) ||
    asString(input.assistantMessage.metadata.requestId) ||
    undefined;
  const failureReason =
    quality === 'poor'
      ? 'Hosted evaluation marked the response as poor.'
      : asString(signalPayload.failureReason) || undefined;
  const sourceCount = readNumber(retrievalPayload.sourceCount);
  const citationCount = readNumber(retrievalPayload.citationCount);
  const toolCallCount = readNumber(toolingPayload.toolCallCount);
  const toolResultCount = readNumber(toolingPayload.toolResultCount);
  const latencyMs = readNumber(signalPayload.latencyMs);

  return {
    account_id: input.account.account_id,
    account_display_name: input.account.display_name,
    owner_type: input.account.owner_type,
    account_status: input.account.status,
    plan_id: input.account.plan_id,
    subscription_status: input.account.subscription_status,
    thread_id: input.thread.threadId,
    request_id: requestId,
    source: 'interaction',
    instruction: inferInstruction({ source: 'interaction', quality }),
    input: input.userMessage.content,
    output: input.assistantMessage.content,
    plan: buildPlanSummary({
      intent,
      routingMode,
      reasoningDepth,
      source: 'interaction',
      quality,
    }),
    reasoning_trace: [
      `input: ${input.userMessage.content.slice(0, 220)}`,
      `intent: ${intent}`,
      `plan: ${routingMode} / ${reasoningDepth}`,
      `action: ${
        toolCallCount !== undefined
          ? `${toolCallCount} tool calls / ${toolResultCount ?? 0} results`
          : 'no tool calls captured'
      }`,
    ],
    success: quality !== 'poor',
    failure_reason: failureReason,
    quality,
    latency_ms: latencyMs,
    metadata: {
      intent,
      routing_mode: routingMode,
      reasoning_depth: reasoningDepth,
      model_provider: asString(modelPayload.provider),
      model_id: asString(modelPayload.modelId),
      request_id: requestId,
      signal_id: input.signal?.signal_id,
      source_count: sourceCount,
      citation_count: citationCount,
    },
  };
}

function buildCandidateFromDraft(input: {
  account: MlDatabaseAccountRow;
  thread?: ReturnType<typeof parseThreads>[number];
  draft: ReturnType<typeof parseLearningDrafts>[number];
}): MlDatasetCandidate {
  const kind = input.draft.kind;
  return {
    account_id: input.account.account_id,
    account_display_name: input.account.display_name,
    owner_type: input.account.owner_type,
    account_status: input.account.status,
    plan_id: input.account.plan_id,
    subscription_status: input.account.subscription_status,
    thread_id: input.thread?.threadId || input.draft.threadId || undefined,
    source: 'learning',
    instruction: inferInstruction({ source: 'learning', quality: 'mixed' }),
    input: input.draft.summary || input.draft.title,
    output: input.draft.body,
    plan: `promote ${kind} learning draft into reusable memory`,
    reasoning_trace: [
      `draft: ${input.draft.title}`,
      `kind: ${kind}`,
      `status: ${input.draft.status}`,
    ],
    success: input.draft.status === 'promoted',
    failure_reason: input.draft.status === 'discarded' ? 'Draft was discarded before promotion.' : undefined,
    quality: input.draft.status === 'promoted' ? 'good' : 'mixed',
    metadata: {
      draft_id: input.draft.draftId,
      kind,
      draft_status: input.draft.status,
      promoted: input.draft.status === 'promoted',
    },
  };
}

function buildCandidateFromLearningEvent(input: {
  account: MlDatabaseAccountRow;
  event: MlDatabaseLearningEventRow & { metadata: Record<string, unknown> };
  signal?: MlDatabaseEvaluationSignalRow & { payload: Record<string, unknown> };
}): MlDatasetCandidate {
  const signalPayload = input.signal?.payload ?? {};
  const retrievalPayload = isRecord(signalPayload.retrieval) ? signalPayload.retrieval : {};
  const toolingPayload = isRecord(signalPayload.tooling) ? signalPayload.tooling : {};
  const rawReasoningTrace = Array.isArray(input.event.reasoning_trace)
    ? input.event.reasoning_trace
    : Array.isArray(input.event.reasoning_steps)
      ? input.event.reasoning_steps
      : [];
  const reasoningSteps = rawReasoningTrace.filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0);
  const score = Number.isFinite(input.event.score) ? input.event.score : 0;
  const quality: MlDatasetCandidate['quality'] =
    score >= 0.8 ? 'good' : score >= 0.55 ? 'mixed' : 'poor';

  return {
    account_id: input.account.account_id,
    account_display_name: input.account.display_name,
    owner_type: input.account.owner_type,
    account_status: input.account.status,
    plan_id: input.account.plan_id,
    subscription_status: input.account.subscription_status,
    thread_id: input.event.request_id,
    request_id: input.event.request_id,
    source: 'request',
    instruction: inferInstruction({ source: 'request', quality }),
    input: input.event.input,
    output: input.event.output,
    better_output: typeof input.event.better_output === 'string' ? input.event.better_output : input.event.output,
    plan: input.event.plan,
    reasoning_trace: reasoningSteps.length > 0 ? reasoningSteps : [`request: ${input.event.request_id}`, `plan: ${input.event.plan}`],
    success: input.event.success,
    failure_reason: input.event.failure_reason ?? undefined,
    quality,
    latency_ms: input.event.latency_ms,
    metadata: {
      event_id: input.event.event_id,
      intent: input.event.intent,
      model_id: input.event.model_id,
      model_provider: input.event.model_provider,
      score,
      accepted: input.event.accepted,
      created_at: input.event.created_at,
      source_count: readNumber(retrievalPayload.sourceCount),
      citation_count: readNumber(retrievalPayload.citationCount),
      tool_call_count: readNumber(toolingPayload.toolCallCount),
      tool_result_count: readNumber(toolingPayload.toolResultCount),
      ...input.event.metadata,
      ...signalPayload,
    },
  };
}

export function buildMlDatasetCandidates(
  accounts: MlDatabaseAccountRow[],
  learningEvents: MlDatabaseLearningEventRow[],
  evaluationSignals: MlDatabaseEvaluationSignalRow[],
  options?: {
    maxSamples?: number;
    minScore?: number;
  }
) {
  const maxSamples = Math.max(1, options?.maxSamples ?? 500);
  const minScore = typeof options?.minScore === 'number' ? options.minScore : 0.45;
  void accounts;
  void evaluationSignals;

  const candidates: MlDatasetCandidate[] = [];

  for (const event of learningEvents) {
    if (candidates.length >= maxSamples) {
      break;
    }

    const score = Number.isFinite(event.score) ? Number(event.score) : 0;
    if (event.accepted !== true || score < minScore) {
      continue;
    }

    const metadata =
      isRecord(event.metadata) && !Array.isArray(event.metadata)
        ? (event.metadata as Record<string, unknown>)
        : {};
    const quality: MlDatasetCandidate['quality'] = score >= 0.85 ? 'good' : score >= 0.7 ? 'mixed' : 'poor';
    const account = {
      account_id: String(event.account_id),
      account_display_name: String(metadata.account_display_name ?? event.account_id),
      owner_type: String(metadata.owner_type ?? 'individual'),
      account_status: String(metadata.account_status ?? 'active'),
      plan_id: String(metadata.plan_id ?? 'cloud_assisted'),
      subscription_status: String(metadata.subscription_status ?? 'active'),
    } as unknown as MlDatabaseAccountRow;

    candidates.push(
      buildCandidateFromLearningEvent({
        account,
        event: {
          ...event,
          better_output: event.better_output ?? event.output,
          accepted: event.accepted,
          metadata,
        },
      })
    );
  }

  return candidates;
}

export async function buildMlDatasetRecord(
  candidate: MlDatasetCandidate,
  teacherModel?: MlTeacherModel | null
) {
  void teacherModel;
  const betterOutput = normalizeWhitespace(candidate.better_output || candidate.output);
  if (!betterOutput) {
    return null;
  }

  const draft: MlTeacherDraft = {
    better_output: betterOutput,
    reasoning_trace: candidate.reasoning_trace.length > 0 ? candidate.reasoning_trace : buildReasoningTrace(candidate),
    score: typeof candidate.metadata.score === 'number' ? candidate.metadata.score : 0,
    failure_reason: candidate.failure_reason,
    evaluation: 'Pre-approved quality event',
    teacher_strategy: 'llm',
  };
  const record = buildDatasetRecord(candidate, draft);
  return record.accepted ? record : null;
}

export function buildMlDatasetSummary(records: MlDatasetRecord[]) {
  const acceptedCount = records.filter((record) => record.accepted).length;
  const totalScore = records.reduce((sum, record) => sum + Number(record.score ?? 0), 0);
  const averageScore = records.length > 0 ? Number((totalScore / records.length).toFixed(2)) : 0;

  return {
    record_count: records.length,
    accepted_count: acceptedCount,
    discarded_count: records.length - acceptedCount,
    average_score: averageScore,
    request_count: records.filter((record) => record.source === 'request').length,
    learning_count: records.filter((record) => record.source === 'learning').length,
    poor_quality_count: records.filter((record) => record.quality === 'poor').length,
  };
}
