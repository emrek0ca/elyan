import type { ObservabilityFailureType } from './failure-classifier';

export type RunTraceMode = 'fast' | 'research' | 'task' | 'quantum';

export type RunTraceRecoveryState = 'fresh' | 'resumed' | 'recovered' | 'failed' | 'cancelled';

export type RunTraceEventKind =
  | 'before_execution'
  | 'step_started'
  | 'step_completed'
  | 'completion'
  | 'capability_started'
  | 'capability_completed';

export type RunTraceEvent = {
  traceId: string;
  taskId: string;
  kind: RunTraceEventKind;
  step: number;
  modelId: string;
  tool?: string;
  capabilityId?: string;
  latencyMs?: number;
  durationMs?: number;
  success: boolean;
  status: 'started' | 'success' | 'retry' | 'failure' | 'cancelled' | 'blocked';
  errorType?: ObservabilityFailureType;
  retryCount: number;
  timestamp: string;
  artifactRefs?: string[];
  recoveryState?: RunTraceRecoveryState;
  details?: Record<string, unknown>;
};

export type RunTraceSummary = {
  success: boolean;
  failureType?: ObservabilityFailureType;
  retryCount: number;
  stepCount: number;
  totalLatencyMs: number;
  avgLatencyMs: number;
  estimatedCostUsd: number;
  modelSuccessRate: number;
};

export type RunTraceReport = {
  traceId: string;
  taskId: string;
  runId: string;
  mode: RunTraceMode;
  taskType: string;
  modelId: string;
  stepBudget: number;
  retryLimit: number;
  spaceId?: string;
  startedAt: string;
  finishedAt: string;
  events: RunTraceEvent[];
  summary: RunTraceSummary;
};

export type RunTraceInput = {
  runId: string;
  taskId?: string;
  traceId?: string;
  mode: RunTraceMode;
  taskType: string;
  modelId: string;
  stepBudget: number;
  retryLimit: number;
  spaceId?: string;
  recoveryState?: RunTraceRecoveryState;
};

export type RunTraceStepInput = {
  step: number;
  modelId?: string;
  tool?: string;
  capabilityId?: string;
  artifactRefs?: string[];
  retryCount: number;
  recoveryState?: RunTraceRecoveryState;
  details?: Record<string, unknown>;
};

export type RunTraceStepCompletionInput = RunTraceStepInput & {
  latencyMs: number;
  success: boolean;
  status?: 'success' | 'retry' | 'failure' | 'cancelled' | 'blocked';
  errorType?: ObservabilityFailureType;
};

export type RunTraceCompletionInput = RunTraceStepCompletionInput & {
  verdict: 'success' | 'retry' | 'failure';
  reason: string;
};

function normalizeModelId(value: string) {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : 'unknown';
}

function round4(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(4)) : 0;
}

function isLikelyLocalModelId(modelId: string) {
  return /^(ollama:|local:|lmstudio:|llama\.cpp:|openai:gpt-oss|anthropic:.*local)/i.test(modelId) || /\b(local|ollama|lmstudio|llama)\b/i.test(modelId);
}

function estimateRunCostUsd(input: {
  modelId: string;
  stepCount: number;
  retryCount: number;
  totalLatencyMs: number;
}) {
  const localModel = isLikelyLocalModelId(input.modelId);
  const base = localModel ? 0.0005 : 0.006;
  const latencyWeight = localModel ? 0.00001 : 0.00003;
  const stepWeight = localModel ? 0.0008 : 0.0035;
  const retryWeight = localModel ? 0.001 : 0.004;

  return round4(base + input.totalLatencyMs * latencyWeight + input.stepCount * stepWeight + input.retryCount * retryWeight);
}

function summarize(events: RunTraceEvent[], modelId: string): RunTraceSummary {
  const completionEvents = events.filter((event) => event.kind === 'completion');
  const stepCompletedEvents = events.filter((event) => event.kind === 'step_completed');
  const lastCompletion = completionEvents.at(-1);
  const retryCount = completionEvents.filter((event) => event.success === false && event.errorType === 'BAD_RESULT' && event.details?.['verdict'] === 'retry').length
    || completionEvents.filter((event) => event.details?.['verdict'] === 'retry').length
    || Math.max(0, completionEvents.length - 1);
  const totalLatencyMs = stepCompletedEvents.reduce((sum, event) => sum + Math.max(0, Number(event.latencyMs ?? 0)), 0);
  const stepCount = stepCompletedEvents.length;
  const avgLatencyMs = stepCount > 0 ? Math.round(totalLatencyMs / stepCount) : 0;
  const success = lastCompletion?.details?.['verdict'] === 'success' || lastCompletion?.success === true || false;
  const failureType = success ? undefined : (lastCompletion?.errorType ?? stepCompletedEvents.at(-1)?.errorType);

  return {
    success,
    failureType,
    retryCount,
    stepCount,
    totalLatencyMs,
    avgLatencyMs,
    estimatedCostUsd: estimateRunCostUsd({
      modelId,
      stepCount,
      retryCount,
      totalLatencyMs,
    }),
    modelSuccessRate: success ? 1 : 0,
  };
}

export class RunTraceRecorder {
  private readonly events: RunTraceEvent[] = [];
  private startedAt = new Date().toISOString();
  private finishedAt: string | null = null;

  constructor(private readonly context: RunTraceInput) {}

  getTraceId() {
    return normalizeModelId(this.context.traceId ?? this.context.runId);
  }

  getTaskId() {
    return normalizeModelId(this.context.taskId ?? this.context.runId);
  }

  private buildEventBase(kind: RunTraceEventKind, step: number, modelId: string) {
    return {
      traceId: this.getTraceId(),
      taskId: this.getTaskId(),
      kind,
      step,
      modelId: normalizeModelId(modelId),
      timestamp: new Date().toISOString(),
      recoveryState: this.context.recoveryState ?? 'fresh',
    } as const;
  }

  beforeExecution(details: Record<string, unknown> = {}) {
    this.events.push({
      ...this.buildEventBase('before_execution', 0, this.context.modelId),
      success: true,
      status: 'started',
      retryCount: 0,
      details: {
        ...details,
        stepBudget: this.context.stepBudget,
        retryLimit: this.context.retryLimit,
        taskType: this.context.taskType,
        mode: this.context.mode,
        spaceId: this.context.spaceId,
      },
    });
  }

  recordStepStarted(input: RunTraceStepInput) {
    this.events.push({
      ...this.buildEventBase('step_started', input.step, input.modelId ?? this.context.modelId),
      tool: input.tool,
      capabilityId: input.capabilityId ?? input.tool,
      success: true,
      status: 'started',
      retryCount: input.retryCount,
      latencyMs: 0,
      durationMs: 0,
      artifactRefs: input.artifactRefs ?? [],
      recoveryState: input.recoveryState ?? this.context.recoveryState ?? 'fresh',
      details: input.details,
    });
  }

  recordStepCompleted(input: RunTraceStepCompletionInput) {
    this.events.push({
      ...this.buildEventBase('step_completed', input.step, input.modelId ?? this.context.modelId),
      tool: input.tool,
      capabilityId: input.capabilityId ?? input.tool,
      latencyMs: Math.max(0, Math.round(input.latencyMs)),
      durationMs: Math.max(0, Math.round(input.latencyMs)),
      success: input.success,
      status: input.status ?? (input.success ? 'success' : input.errorType ? 'failure' : 'retry'),
      errorType: input.errorType,
      retryCount: input.retryCount,
      artifactRefs: input.artifactRefs ?? [],
      recoveryState: input.recoveryState ?? this.context.recoveryState ?? 'fresh',
      details: input.details,
    });
  }

  recordCompletion(input: RunTraceCompletionInput) {
    this.events.push({
      ...this.buildEventBase('completion', input.step, input.modelId ?? this.context.modelId),
      tool: input.tool,
      capabilityId: input.capabilityId ?? input.tool,
      latencyMs: Math.max(0, Math.round(input.latencyMs)),
      durationMs: Math.max(0, Math.round(input.latencyMs)),
      success: input.verdict === 'success',
      status: input.verdict === 'success' ? 'success' : input.verdict === 'retry' ? 'retry' : 'failure',
      errorType: input.errorType,
      retryCount: input.retryCount,
      artifactRefs: input.artifactRefs ?? [],
      recoveryState: input.recoveryState ?? this.context.recoveryState ?? 'fresh',
      details: {
        verdict: input.verdict,
        reason: input.reason,
        ...input.details,
      },
    });
  }

  recordCapabilityStarted(input: {
    step: number;
    capabilityId: string;
    modelId?: string;
    tool?: string;
    retryCount: number;
    artifactRefs?: string[];
    recoveryState?: RunTraceRecoveryState;
    details?: Record<string, unknown>;
  }) {
    this.events.push({
      ...this.buildEventBase('capability_started', input.step, input.modelId ?? this.context.modelId),
      tool: input.tool,
      capabilityId: input.capabilityId,
      success: true,
      status: 'started',
      retryCount: input.retryCount,
      latencyMs: 0,
      durationMs: 0,
      artifactRefs: input.artifactRefs ?? [],
      recoveryState: input.recoveryState ?? this.context.recoveryState ?? 'fresh',
      details: input.details,
    });
  }

  recordCapabilityCompleted(input: {
    step: number;
    capabilityId: string;
    modelId?: string;
    tool?: string;
    latencyMs: number;
    success: boolean;
    status?: 'success' | 'failure' | 'retry' | 'cancelled' | 'blocked';
    retryCount: number;
    errorType?: ObservabilityFailureType;
    artifactRefs?: string[];
    recoveryState?: RunTraceRecoveryState;
    details?: Record<string, unknown>;
  }) {
    const status = input.status ?? (input.success ? 'success' : 'failure');
    this.events.push({
      ...this.buildEventBase('capability_completed', input.step, input.modelId ?? this.context.modelId),
      tool: input.tool,
      capabilityId: input.capabilityId,
      latencyMs: Math.max(0, Math.round(input.latencyMs)),
      durationMs: Math.max(0, Math.round(input.latencyMs)),
      success: input.success,
      status,
      errorType: input.errorType,
      retryCount: input.retryCount,
      artifactRefs: input.artifactRefs ?? [],
      recoveryState: input.recoveryState ?? this.context.recoveryState ?? 'fresh',
      details: input.details,
    });
  }

  finalize(): RunTraceReport {
    if (!this.finishedAt) {
      this.finishedAt = new Date().toISOString();
    }

    const modelId = normalizeModelId(this.context.modelId);

    return {
      traceId: this.getTraceId(),
      taskId: this.getTaskId(),
      runId: this.context.runId,
      mode: this.context.mode,
      taskType: this.context.taskType,
      modelId,
      stepBudget: this.context.stepBudget,
      retryLimit: this.context.retryLimit,
      spaceId: this.context.spaceId,
      startedAt: this.startedAt,
      finishedAt: this.finishedAt,
      events: [...this.events],
      summary: summarize(this.events, modelId),
    };
  }

  snapshot() {
    return this.finalize();
  }
}

export function createRunTrace(input: RunTraceInput) {
  return new RunTraceRecorder(input);
}
