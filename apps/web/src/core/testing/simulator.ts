import { randomUUID } from 'crypto';
import type { RunTraceMetrics } from '@/core/observability/metrics';
import { buildRunMetrics } from '@/core/observability/metrics';
import { classifyFailure, type ObservabilityFailureType } from '@/core/observability/failure-classifier';
import { createRunTrace, type RunTraceReport } from '@/core/observability/run-trace';
import { decideExecution, type DecisionEngineInput, type ExecutionDecision } from '@/core/decision/engine';
import { decidePolicy, type PolicyEngineOutput } from '@/core/control/policy-engine';
import type { ExecutionCompletionResult } from '@/core/execution/completion-engine';
import { getOperatorRunStore, type OperatorRun } from '@/core/operator/runs';
import { buildExecutionSurfaceSnapshot, buildOrchestrationPlan, type OrchestrationPlan } from '@/core/orchestration';
import { classifyInteractionIntent } from '@/core/interaction/intent';
import type { InteractionRequest, InteractionTextResponse } from '@/core/interaction/orchestrator';

export type SimulationScenarioKind =
  | 'simple_qa'
  | 'ambiguous_query'
  | 'conflicting_sources'
  | 'deep_research'
  | 'multi_step_task'
  | 'long_running_task'
  | 'tool_usage'
  | 'tool_failure_recovery'
  | 'failure_retry'
  | 'model_switching'
  | 'route_optimization'
  | 'scheduling_problem'
  | 'resource_allocation'
  | 'bad_input';

export type SimulationScenarioExpectations = {
  mode?: ExecutionDecision['mode'];
  taskType?: string;
  expectedTools?: string[];
  requireRetry?: boolean;
  expectedModelSwitch?: 'none' | 'expected' | 'required';
  minStepCount?: number;
  maxStepCount?: number;
};

export type SimulationScenario = {
  id: string;
  title: string;
  kind: SimulationScenarioKind;
  input: string;
  source?: InteractionRequest['source'];
  requestOverrides?: Partial<Omit<InteractionRequest, 'source' | 'text'>>;
  expectations: SimulationScenarioExpectations;
};

export type ScenarioScoreBreakdown = {
  decisionQuality: number;
  executionEfficiency: number;
  retryEffectiveness: number;
  toolUsageCorrectness: number;
  overall: number;
  pass: boolean;
};

export type ScenarioBehaviorDiff = {
  field: string;
  expected: string | number | boolean | null;
  actual: string | number | boolean | null;
  reason: string;
};

export type ScenarioLearningSignal = {
  failureType: ObservabilityFailureType;
  promptHint: string;
  routingHint: string;
  toolUsagePattern: string;
  sanitizedSummary: string;
};

export type ScenarioReplayComparison = {
  improved: boolean;
  scoreDelta: Partial<Record<keyof ScenarioScoreBreakdown, number>>;
  diffs: ScenarioBehaviorDiff[];
};

export type ScenarioSimulationTrace = RunTraceReport & {
  scenario: SimulationScenario;
  scenarioId: string;
  scenarioKind: SimulationScenarioKind;
  requestId: string;
  input: string;
  request: InteractionRequest;
  decision: ExecutionDecision;
  policy: PolicyEngineOutput;
  expected: SimulationScenarioExpectations;
  modelSwitchObserved: boolean;
};

export type ScenarioExecutionOutcome = {
  status: 'success' | 'failure';
  text: string;
  sources: Array<{ url: string; title: string }>;
  modelId?: string;
  modelProvider?: string;
  error?: string;
  completion: ExecutionCompletionResult | null;
  runId?: string;
};

export type ScenarioEvaluation = {
  pass: boolean;
  scores: ScenarioScoreBreakdown;
  diffs: ScenarioBehaviorDiff[];
  traceSummary: RunTraceReport['summary'];
  traceMetrics: RunTraceMetrics;
};

export type ScenarioSimulationResult = {
  scenario: SimulationScenario;
  request: InteractionRequest;
  classification: ReturnType<typeof classifyInteractionIntent>;
  plan: OrchestrationPlan;
  decision: ExecutionDecision;
  policy: PolicyEngineOutput;
  execution: ScenarioExecutionOutcome;
  trace: ScenarioSimulationTrace;
  evaluation: ScenarioEvaluation;
  failureLearning?: {
    failureType: ObservabilityFailureType;
    signal: ScenarioLearningSignal;
    rerun: ScenarioSimulationResult;
    comparison: ScenarioReplayComparison;
  };
  replay?: ScenarioReplayComparison;
};

export type SimulationExecutor = (request: InteractionRequest) => Promise<InteractionTextResponse>;

export type SimulationOptions = {
  executor?: SimulationExecutor;
  recordFailureLearning?: boolean;
  allowFailureLearningRerun?: boolean;
};

const DEFAULT_SCENARIOS: SimulationScenario[] = [
  {
    id: 'simple-qa',
    title: 'Simple Q&A',
    kind: 'simple_qa',
    input: 'What is the capital of France?',
    expectations: {
      mode: 'fast',
      taskType: 'direct_answer',
      expectedTools: [],
      requireRetry: false,
      expectedModelSwitch: 'none',
      minStepCount: 1,
      maxStepCount: 2,
    },
  },
  {
    id: 'ambiguous-query',
    title: 'Ambiguous Query',
    kind: 'ambiguous_query',
    input: 'Can you help me with that thing I mentioned earlier?',
    expectations: {
      mode: 'fast',
      expectedTools: [],
      expectedModelSwitch: 'none',
      minStepCount: 1,
      maxStepCount: 2,
    },
  },
  {
    id: 'conflicting-sources',
    title: 'Conflicting Sources',
    kind: 'conflicting_sources',
    input: 'Compare the conflicting evidence about whether local-first or cloud-first AI runtimes are better, and cite the sources.',
    expectations: {
      mode: 'research',
      taskType: 'research',
      expectedTools: ['web_search', 'connectors', 'browser'],
      expectedModelSwitch: 'expected',
      minStepCount: 1,
      maxStepCount: 6,
    },
  },
  {
    id: 'deep-research',
    title: 'Deep Research',
    kind: 'deep_research',
    input: 'Research the tradeoffs between retrieval-first systems and model-first systems with current evidence and summarize the findings.',
    expectations: {
      mode: 'research',
      taskType: 'research',
      expectedTools: ['web_search', 'connectors', 'browser'],
      expectedModelSwitch: 'expected',
      minStepCount: 2,
      maxStepCount: 6,
    },
  },
  {
    id: 'multi-step-task',
    title: 'Multi-step Task',
    kind: 'multi_step_task',
    input: 'Plan a three-step migration for the backend configuration, include verification checkpoints, and summarize the execution order.',
    expectations: {
      mode: 'task',
      taskType: 'procedural',
      expectedTools: ['local_tools', 'connectors', 'browser'],
      expectedModelSwitch: 'expected',
      minStepCount: 2,
      maxStepCount: 6,
    },
  },
  {
    id: 'long-running-task',
    title: 'Long-running Task',
    kind: 'long_running_task',
    input: 'Review the system state, build a detailed rollout plan, and keep the result consistent across several verification checkpoints.',
    expectations: {
      mode: 'task',
      taskType: 'procedural',
      expectedTools: ['local_tools', 'connectors', 'browser'],
      expectedModelSwitch: 'expected',
      minStepCount: 3,
      maxStepCount: 6,
      requireRetry: true,
    },
  },
  {
    id: 'tool-usage',
    title: 'Tool Usage',
    kind: 'tool_usage',
    input: 'Use the available tools to inspect the project, then summarize which files would be touched.',
    expectations: {
      mode: 'task',
      taskType: 'procedural',
      expectedTools: ['local_tools', 'connectors', 'browser'],
      expectedModelSwitch: 'expected',
      minStepCount: 1,
      maxStepCount: 5,
    },
  },
  {
    id: 'tool-failure-recovery',
    title: 'Tool Failure Recovery',
    kind: 'tool_failure_recovery',
    input: 'If the browser lookup fails, recover by switching strategy and retry once with a different tool path.',
    expectations: {
      mode: 'task',
      taskType: 'procedural',
      expectedTools: ['browser', 'connectors', 'local_tools'],
      expectedModelSwitch: 'required',
      minStepCount: 1,
      maxStepCount: 5,
      requireRetry: true,
    },
  },
  {
    id: 'failure-retry',
    title: 'Failure + Retry',
    kind: 'failure_retry',
    input: 'Solve the task carefully and retry if the first attempt is incomplete.',
    expectations: {
      mode: 'task',
      taskType: 'procedural',
      expectedTools: ['local_tools', 'connectors', 'browser'],
      expectedModelSwitch: 'expected',
      minStepCount: 1,
      maxStepCount: 5,
      requireRetry: true,
    },
  },
  {
    id: 'model-switching',
    title: 'Model Switching',
    kind: 'model_switching',
    input: 'Prefer a better model if the first choice is weak, then answer concisely.',
    requestOverrides: {
      modelId: 'cloud:gpt-4.1',
    },
    expectations: {
      mode: 'fast',
      taskType: 'direct_answer',
      expectedTools: [],
      expectedModelSwitch: 'required',
      minStepCount: 1,
      maxStepCount: 3,
    },
  },
  {
    id: 'route-optimization',
    title: 'Route Optimization',
    kind: 'route_optimization',
    input: 'Solve this route optimization problem: {"type":"graph","nodes":["depot","a","b","c"],"costMatrix":[[0,2,9,10],[1,0,6,4],[15,7,0,8],[6,3,12,0]],"start":"depot"}',
    expectations: {
      mode: 'quantum',
      expectedTools: ['optimization_solve'],
      expectedModelSwitch: 'none',
      minStepCount: 1,
      maxStepCount: 3,
    },
  },
  {
    id: 'scheduling-problem',
    title: 'Scheduling Problem',
    kind: 'scheduling_problem',
    input: 'Schedule these jobs with minimum cost: {"type":"scheduling","workers":["morning","afternoon"],"tasks":["job-a","job-b"],"costs":{"morning":{"job-a":7,"job-b":2},"afternoon":{"job-a":1,"job-b":8}}}',
    expectations: {
      mode: 'quantum',
      expectedTools: ['optimization_solve'],
      expectedModelSwitch: 'none',
      minStepCount: 1,
      maxStepCount: 3,
    },
  },
  {
    id: 'resource-allocation',
    title: 'Resource Allocation',
    kind: 'resource_allocation',
    input: 'Find the best resource allocation: {"type":"allocation","resources":["truck-a","truck-b"],"locations":["zone-1","zone-2"],"costs":{"truck-a":{"zone-1":8,"zone-2":1},"truck-b":{"zone-1":2,"zone-2":7}}}',
    expectations: {
      mode: 'quantum',
      expectedTools: ['optimization_solve'],
      expectedModelSwitch: 'none',
      minStepCount: 1,
      maxStepCount: 3,
    },
  },
  {
    id: 'bad-input',
    title: 'Bad Input',
    kind: 'bad_input',
    input: 'asdf qwer zxcv ???',
    expectations: {
      mode: 'fast',
      taskType: 'direct_answer',
      expectedTools: [],
      expectedModelSwitch: 'none',
      minStepCount: 1,
      maxStepCount: 1,
    },
  },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function clamp01(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }

  return Math.max(0, Math.min(1, value));
}

function round2(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(2)) : 0;
}

function uniqueTools(trace: RunTraceReport) {
  return [...new Set(
    trace.events
      .map((event) => event.tool?.trim())
      .filter((tool): tool is string => Boolean(tool && tool.length > 0))
  )];
}

function pickPrimaryTool(decision: ExecutionDecision) {
  if (decision.tools.preferredTools.length > 0) {
    return decision.tools.preferredTools[0];
  }

  return decision.mode === 'research'
    ? 'web_search'
    : decision.mode === 'task'
      ? 'local_tools'
      : 'none';
}

function scoreDecisionQuality(result: ScenarioSimulationResult) {
  const { scenario, decision, execution, trace } = result;
  const expected = scenario.expectations;
  let score = 0.2;

  if (expected.mode && decision.mode === expected.mode) {
    score += 0.35;
  }

  if (expected.taskType && result.plan.taskIntent === expected.taskType) {
    score += 0.2;
  }

  if (expected.expectedModelSwitch === 'none') {
    score += decision.modelId === execution.modelId ? 0.15 : 0;
  } else if (expected.expectedModelSwitch === 'required') {
    score += decision.modelId !== result.request.modelId ? 0.2 : 0;
  } else if (expected.expectedModelSwitch === 'expected') {
    score += decision.modelId ? 0.15 : 0;
  }

  const actualTools = uniqueTools(trace);
  const expectedTools = expected.expectedTools ?? [];
  if (expectedTools.length === 0) {
    score += actualTools.length === 0 ? 0.1 : 0.05;
  } else {
    const overlap = expectedTools.filter((tool) => actualTools.includes(tool)).length;
    score += overlap > 0 ? Math.min(0.1, overlap / expectedTools.length * 0.1) : 0;
  }

  if (typeof expected.minStepCount === 'number' && trace.summary.stepCount >= expected.minStepCount) {
    score += 0.05;
  }

  if (typeof expected.maxStepCount === 'number' && trace.summary.stepCount <= expected.maxStepCount) {
    score += 0.05;
  }

  if (!trace.summary.success && trace.summary.failureType) {
    score -= 0.05;
  }

  return clamp01(score);
}

function scoreExecutionEfficiency(result: ScenarioSimulationResult) {
  const { policy, trace } = result;
  const stepPressure = policy.maxSteps > 0 ? trace.summary.stepCount / policy.maxSteps : 1;
  const latencyPressure = policy.maxTimeMs > 0 ? trace.summary.totalLatencyMs / policy.maxTimeMs : 1;
  const retryPressure = policy.maxRetries > 0 ? trace.summary.retryCount / policy.maxRetries : trace.summary.retryCount > 0 ? 1 : 0;
  const base = trace.summary.success ? 0.8 : 0.35;
  const penalty = (stepPressure * 0.25) + (latencyPressure * 0.4) + (retryPressure * 0.2);

  return clamp01(base - penalty);
}

function scoreRetryEffectiveness(result: ScenarioSimulationResult) {
  const { trace, failureLearning, scenario } = result;

  if (trace.summary.retryCount === 0) {
    return trace.summary.success ? 1 : 0.25;
  }

  if (trace.summary.success) {
    return clamp01(0.55 + (1 - Math.min(1, trace.summary.retryCount / Math.max(1, result.policy.maxRetries))) * 0.35);
  }

  if (failureLearning?.rerun) {
    const improvement = failureLearning.comparison.scoreDelta.overall ?? 0;
    return clamp01(0.4 + Math.max(0, improvement) * 0.5);
  }

  if (scenario.expectations.requireRetry) {
    return 0.6;
  }

  return 0.2;
}

function scoreToolUsageCorrectness(result: ScenarioSimulationResult) {
  const expected = result.scenario.expectations.expectedTools ?? [];
  const actual = uniqueTools(result.trace);

  if (expected.length === 0) {
    return actual.length === 0 ? 1 : 0.75;
  }

  const overlap = expected.filter((tool) => actual.includes(tool)).length;
  const forbidden = actual.filter((tool) => !expected.includes(tool));

  let score = overlap > 0 ? 0.55 + (overlap / expected.length) * 0.45 : 0;
  if (forbidden.length > 0) {
    score -= Math.min(0.35, forbidden.length * 0.1);
  }

  return clamp01(score);
}

function computeOverall(scores: Omit<ScenarioScoreBreakdown, 'overall' | 'pass'>) {
  return round2((scores.decisionQuality + scores.executionEfficiency + scores.retryEffectiveness + scores.toolUsageCorrectness) / 4);
}

function buildBehaviorDiffs(result: ScenarioSimulationResult): ScenarioBehaviorDiff[] {
  const diffs: ScenarioBehaviorDiff[] = [];
  const expected = result.scenario.expectations;
  const actualTools = uniqueTools(result.trace);

  if (expected.mode && result.decision.mode !== expected.mode) {
    diffs.push({
      field: 'mode',
      expected: expected.mode,
      actual: result.decision.mode,
      reason: 'Decision engine selected a different execution mode than the scenario expected.',
    });
  }

  if (expected.taskType && result.plan.taskIntent !== expected.taskType) {
    diffs.push({
      field: 'taskType',
      expected: expected.taskType,
      actual: result.plan.taskIntent,
      reason: 'Resolved task intent differed from the expected workflow shape.',
    });
  }

  if (typeof expected.minStepCount === 'number' && result.trace.summary.stepCount < expected.minStepCount) {
    diffs.push({
      field: 'stepCount',
      expected: expected.minStepCount,
      actual: result.trace.summary.stepCount,
      reason: 'The run did not execute enough steps for the requested scenario.',
    });
  }

  if (typeof expected.maxStepCount === 'number' && result.trace.summary.stepCount > expected.maxStepCount) {
    diffs.push({
      field: 'stepCount',
      expected: expected.maxStepCount,
      actual: result.trace.summary.stepCount,
      reason: 'The run used more steps than the scenario budget expected.',
    });
  }

  if ((expected.expectedTools ?? []).length > 0) {
    const overlap = (expected.expectedTools ?? []).filter((tool) => actualTools.includes(tool));
    if (overlap.length === 0) {
      diffs.push({
        field: 'tools',
        expected: expected.expectedTools!.join(', '),
        actual: actualTools.length > 0 ? actualTools.join(', ') : 'none',
        reason: 'The run did not use the tool family the scenario expected.',
      });
    }
  } else if (actualTools.length > 0) {
    diffs.push({
      field: 'tools',
      expected: 'none',
      actual: actualTools.join(', '),
      reason: 'The run used tools even though the scenario expected a direct answer path.',
    });
  }

  if (expected.requireRetry && result.trace.summary.retryCount === 0) {
    diffs.push({
      field: 'retryCount',
      expected: 1,
      actual: 0,
      reason: 'The scenario expected recovery behavior but the run never retried.',
    });
  }

  if (expected.expectedModelSwitch && expected.expectedModelSwitch !== 'none') {
    const switched = Boolean(result.execution.modelId && result.request.modelId && result.execution.modelId !== result.request.modelId);
    if (!switched) {
      diffs.push({
        field: 'modelSwitch',
        expected: expected.expectedModelSwitch,
        actual: false,
        reason: 'The model did not switch even though the scenario expected a different model choice.',
      });
    }
  }

  return diffs;
}

function buildLearningSignal(result: ScenarioSimulationResult, failureType: ObservabilityFailureType): ScenarioLearningSignal {
  const safeSummary = [
    `scenario=${result.scenario.kind}`,
    `mode=${result.decision.mode}`,
    `task_type=${result.plan.taskIntent}`,
    `failure_type=${failureType}`,
    `retry_count=${result.trace.summary.retryCount}`,
    `step_count=${result.trace.summary.stepCount}`,
  ].join('; ');

  if (result.scenario.kind === 'tool_failure_recovery') {
    return {
      failureType,
      promptHint: 'When the browser path fails, fail closed and switch to a smaller recovery path with a clearer retry instruction.',
      routingHint: 'Prefer alternate tool selection and keep the retry budget small for fragile browser tasks.',
      toolUsagePattern: 'Use browser only when a page is reachable; otherwise fall back to connectors or direct guidance.',
      sanitizedSummary: safeSummary,
    };
  }

  if (result.scenario.kind === 'model_switching') {
    return {
      failureType,
      promptHint: 'When the requested model is weak or unavailable, move to the best available local alternative and keep the answer concise.',
      routingHint: 'Prefer a local model fallback when the preferred cloud model is not a clear fit.',
      toolUsagePattern: 'Do not add tools when the task is a direct answer and the model switch alone is sufficient.',
      sanitizedSummary: safeSummary,
    };
  }

  if (result.scenario.kind === 'deep_research' || result.scenario.kind === 'conflicting_sources') {
    return {
      failureType,
      promptHint: 'Gather evidence before answering and make the uncertainty explicit when the sources disagree.',
      routingHint: 'Use retrieval-first research and keep citations visible when evidence is conflicting.',
      toolUsagePattern: 'Search, read, compare, and only then answer.',
      sanitizedSummary: safeSummary,
    };
  }

  return {
    failureType,
    promptHint: 'Tighten the request, reduce ambiguity, and answer only with the verified facts available.',
    routingHint: 'Stay conservative and prefer the smaller execution path on failure.',
    toolUsagePattern: 'Use the minimum tool set needed to recover or explain the failure.',
    sanitizedSummary: safeSummary,
  };
}

function isRunTraceReport(value: unknown): value is RunTraceReport {
  if (!isRecord(value)) {
    return false;
  }

  return typeof value.runId === 'string'
    && typeof value.mode === 'string'
    && typeof value.taskType === 'string'
    && typeof value.modelId === 'string'
    && Array.isArray(value.events)
    && isRecord(value.summary);
}

function extractTraceFromRun(run: OperatorRun): RunTraceReport | null {
  for (const artifact of [...run.artifacts].reverse()) {
    if (!isRecord(artifact.metadata)) {
      continue;
    }

    const candidate = artifact.metadata.observabilityTrace;
    if (isRunTraceReport(candidate)) {
      return candidate;
    }

    if (isRecord(artifact.metadata.observability) && isRunTraceReport(artifact.metadata.observability.trace)) {
      return artifact.metadata.observability.trace;
    }
  }

  return null;
}

function traceContainsRequestId(trace: RunTraceReport, requestId: string) {
  return trace.events.some((event) => {
    if (!isRecord(event.details)) {
      return false;
    }

    return event.details.requestId === requestId;
  });
}

function runMatchesRequestId(run: OperatorRun, requestId: string) {
  for (const artifact of [...run.artifacts].reverse()) {
    if (!isRecord(artifact.metadata)) {
      continue;
    }

    if (artifact.metadata.requestId === requestId || artifact.metadata.request_id === requestId) {
      return true;
    }

    const traceCandidate = artifact.metadata.observabilityTrace;
    if (isRunTraceReport(traceCandidate) && traceContainsRequestId(traceCandidate, requestId)) {
      return true;
    }

    if (isRecord(artifact.metadata.observability) && isRunTraceReport(artifact.metadata.observability.trace) && traceContainsRequestId(artifact.metadata.observability.trace, requestId)) {
      return true;
    }
  }

  return false;
}

function synthesizeTrace(
  scenario: SimulationScenario,
  request: InteractionRequest,
  decision: ExecutionDecision,
  policy: PolicyEngineOutput,
  outcome: ScenarioExecutionOutcome,
  requestId: string
) {
  const recorder = createRunTrace({
    runId: `simulation_${scenario.id}_${requestId}`,
    mode: decision.mode,
    taskType: scenario.expectations.taskType ?? 'direct_answer',
    modelId: outcome.modelId ?? decision.modelId ?? 'unknown',
    stepBudget: Math.max(1, decision.steps.stepBudget),
    retryLimit: Math.max(0, policy.maxRetries),
    spaceId: request.metadata?.spaceId ?? request.metadata?.space_id,
  });

  recorder.beforeExecution({
    scenarioId: scenario.id,
    scenarioKind: scenario.kind,
  });

  const tool = outcome.status === 'success'
    ? pickPrimaryTool(decision)
    : 'none';
  const latencyMs = Math.max(1, outcome.completion ? outcome.completion.attempt + 1 : 1) * 120;

  recorder.recordStepStarted({
    step: 1,
    modelId: outcome.modelId ?? decision.modelId,
    tool,
    retryCount: Math.max(0, outcome.completion?.attempt ?? 0),
  });
  recorder.recordStepCompleted({
    step: 1,
    modelId: outcome.modelId ?? decision.modelId,
    tool,
    latencyMs,
    success: outcome.status === 'success',
    errorType: outcome.status === 'failure'
      ? classifyFailure({
          outputText: outcome.text,
          failureReason: outcome.error,
          verdict: 'failure',
          tool,
          modelId: outcome.modelId,
        })?.errorType
      : undefined,
    retryCount: Math.max(0, outcome.completion?.attempt ?? 0),
  });
  recorder.recordCompletion({
    step: 1,
    modelId: outcome.modelId ?? decision.modelId,
    tool,
    latencyMs,
    success: outcome.status === 'success',
    verdict: outcome.status === 'success' ? 'success' : outcome.completion?.verdict ?? 'failure',
    reason: outcome.error ?? outcome.completion?.reason ?? 'Simulation completed.',
    retryCount: Math.max(0, outcome.completion?.attempt ?? 0),
    errorType: outcome.status === 'failure'
      ? classifyFailure({
          outputText: outcome.text,
          failureReason: outcome.error,
          verdict: 'failure',
          tool,
          modelId: outcome.modelId,
        })?.errorType
      : undefined,
  });

  return recorder.finalize();
}

function buildExecutionOutcomeFromResponse(
  response: InteractionTextResponse,
  run: OperatorRun | null,
  decision: ExecutionDecision,
  policy: PolicyEngineOutput
): ScenarioExecutionOutcome {
  const trace = run ? extractTraceFromRun(run) : null;
  const completion: ExecutionCompletionResult | null = trace
    ? {
        verdict: trace.summary.success ? 'success' : 'failure',
        reason: trace.summary.failureType ?? 'Simulation completed.',
        retryLimit: policy.maxRetries,
        attempt: trace.summary.retryCount,
        requiredArtifacts: [],
        missingArtifacts: [],
        verification: {
          status: trace.summary.success ? 'passed' : 'failed',
          summary: trace.summary.success ? 'Simulation succeeded.' : trace.summary.failureType ?? 'Simulation failed.',
        },
        shouldTriggerLearning: trace.summary.success,
        finalRunStatus: trace.summary.success ? 'completed' : 'failed',
      }
    : {
        verdict: 'success',
        reason: 'Simulation completed.',
        retryLimit: policy.maxRetries,
        attempt: 0,
        requiredArtifacts: [],
        missingArtifacts: [],
        verification: {
          status: 'passed',
          summary: 'Simulation succeeded.',
        },
        shouldTriggerLearning: true,
        finalRunStatus: 'completed',
      };

  return {
    status: trace?.summary.success === false ? 'failure' : 'success',
    text: response.text,
    sources: response.sources,
    modelId: response.modelId,
    completion,
    runId: response.runId ?? run?.id,
    modelProvider: undefined,
  };
}

async function runScenarioOnce(
  scenario: SimulationScenario,
  options: SimulationOptions = {}
): Promise<ScenarioSimulationResult> {
  const requestId = scenario.requestOverrides?.requestId?.trim() || `scenario_${scenario.id}_${randomUUID()}`;
  const request: InteractionRequest = {
    source: scenario.source ?? 'cli',
    text: scenario.input,
    ...scenario.requestOverrides,
    requestId,
    metadata: {
      ...(scenario.requestOverrides?.metadata ?? {}),
      simulationScenarioId: scenario.id,
      simulationScenarioKind: scenario.kind,
      simulationRequestId: requestId,
    },
  } as InteractionRequest;

  const classification = classifyInteractionIntent(request.text, request.mode);
  const surface = buildExecutionSurfaceSnapshot();
  const plan = buildOrchestrationPlan(request.text, classification.resolvedMode, surface);
  const decisionInput: DecisionEngineInput = {
    query: request.text,
    taskType: plan.taskIntent,
    requestedModelId: request.modelId?.trim(),
    spaceId: request.metadata?.spaceId?.trim() || request.metadata?.space_id?.trim(),
    routingMode: plan.routingMode,
    reasoningDepth: plan.reasoningDepth,
  };
  const decision = await decideExecution(decisionInput);
  const policy = decidePolicy({
    decision,
    taskType: plan.taskIntent,
    queryComplexity: decision.steps.complexity,
  });

  const store = getOperatorRunStore();
  const beforeRuns = await store.list();
  const beforeIds = new Set(beforeRuns.map((run) => run.id));

  let execution: ScenarioExecutionOutcome;
  let response: InteractionTextResponse | null = null;

  const executor = options.executor ?? (await import('@/core/interaction/orchestrator')).executeInteractionText;

  try {
    response = await executor(request);
    const afterRuns = await store.list();
    const createdRun = afterRuns.find((run) => !beforeIds.has(run.id) && runMatchesRequestId(run, requestId))
      ?? afterRuns.find((run) => !beforeIds.has(run.id))
      ?? null;
    execution = buildExecutionOutcomeFromResponse(response, createdRun ?? null, decision, policy);
  } catch (error) {
    const afterRuns = await store.list();
    const createdRun = afterRuns.find((run) => !beforeIds.has(run.id) && runMatchesRequestId(run, requestId))
      ?? afterRuns.find((run) => !beforeIds.has(run.id))
      ?? null;
    const text = error instanceof Error ? error.message : String(error);
    const failureType = classifyFailure({
      error,
      outputText: '',
      failureReason: text,
      verdict: 'failure',
      modelId: decision.modelId,
    })?.errorType;
    const completion: ExecutionCompletionResult = {
      verdict: 'failure',
      reason: text,
      retryLimit: policy.maxRetries,
      attempt: 0,
      requiredArtifacts: [],
      missingArtifacts: [],
      verification: {
        status: 'failed',
        summary: text,
      },
      shouldTriggerLearning: false,
      finalRunStatus: 'failed',
    };

    execution = {
      status: 'failure',
      text: '',
      sources: [],
      modelId: decision.modelId,
      completion,
      runId: createdRun?.id,
      error: failureType ? `${failureType}: ${text}` : text,
      modelProvider: undefined,
    };
  }

  const traceFromRun = execution.runId ? await store.get(execution.runId).then((run) => run ? extractTraceFromRun(run) : null).catch(() => null) : null;
  const trace = traceFromRun
    ? {
        ...traceFromRun,
        scenario,
        scenarioId: scenario.id,
        scenarioKind: scenario.kind,
        requestId,
        input: request.text,
        request,
        decision,
        policy,
        expected: scenario.expectations,
        modelSwitchObserved: Boolean(
          execution.modelId && request.modelId && execution.modelId !== request.modelId
        ),
      }
    : {
        ...synthesizeTrace(
          scenario,
          request,
          decision,
          policy,
          execution,
          requestId
        ),
        scenario,
        scenarioId: scenario.id,
        scenarioKind: scenario.kind,
        requestId,
        input: request.text,
        request,
        decision,
        policy,
        expected: scenario.expectations,
        modelSwitchObserved: Boolean(
          execution.modelId && request.modelId && execution.modelId !== request.modelId
        ),
      };

  const result: ScenarioSimulationResult = {
    scenario,
    request,
    classification,
    plan,
    decision,
    policy,
    execution,
    trace,
    evaluation: {
      pass: false,
      scores: {
        decisionQuality: 0,
        executionEfficiency: 0,
        retryEffectiveness: 0,
        toolUsageCorrectness: 0,
        overall: 0,
        pass: false,
      },
      diffs: [],
      traceSummary: trace.summary,
      traceMetrics: buildRunMetrics([trace]),
    },
  };

  const evaluation = evaluateScenario(result);
  result.evaluation = evaluation;

  if (!evaluation.pass && options.recordFailureLearning !== false && options.allowFailureLearningRerun !== false) {
    const completion = execution.completion ?? {
      verdict: 'failure' as const,
      reason: execution.error ?? 'Simulation failed.',
      retryLimit: policy.maxRetries,
      attempt: 0,
      requiredArtifacts: [],
      missingArtifacts: [],
      verification: {
        status: 'failed' as const,
        summary: execution.error ?? 'Simulation failed.',
      },
      shouldTriggerLearning: false,
      finalRunStatus: 'failed' as const,
    };
    const failureType = trace.summary.failureType ?? classifyFailure({
      error: execution.error ?? new Error(completion.reason),
      outputText: execution.text,
      failureReason: execution.error ?? completion.reason,
      verdict: 'failure',
      modelId: execution.modelId,
    })?.errorType ?? 'BAD_RESULT';
    const signal = buildLearningSignal(result, failureType);
    const rerun = await runScenarioOnce({
      ...scenario,
      requestOverrides: {
        ...scenario.requestOverrides,
        metadata: {
          ...(scenario.requestOverrides?.metadata ?? {}),
          simulationFailureType: failureType,
          simulationLearningSignal: signal.sanitizedSummary,
        },
      },
    }, {
      ...options,
      allowFailureLearningRerun: false,
    });
    const comparison = compareScenarioResults(result, rerun);

    return {
      ...result,
      failureLearning: {
        failureType,
        signal,
        rerun,
        comparison,
      },
    };
  }

  return result;
}

function compareScenarioResults(previous: ScenarioSimulationResult, next: ScenarioSimulationResult): ScenarioReplayComparison {
  const scoreDelta = {
    decisionQuality: round2(next.evaluation.scores.decisionQuality - previous.evaluation.scores.decisionQuality),
    executionEfficiency: round2(next.evaluation.scores.executionEfficiency - previous.evaluation.scores.executionEfficiency),
    retryEffectiveness: round2(next.evaluation.scores.retryEffectiveness - previous.evaluation.scores.retryEffectiveness),
    toolUsageCorrectness: round2(next.evaluation.scores.toolUsageCorrectness - previous.evaluation.scores.toolUsageCorrectness),
    overall: round2(next.evaluation.scores.overall - previous.evaluation.scores.overall),
    pass: next.evaluation.scores.pass === previous.evaluation.scores.pass ? 0 : next.evaluation.scores.pass ? 1 : -1,
  };

  return {
    improved: next.evaluation.scores.overall > previous.evaluation.scores.overall || (!previous.evaluation.scores.pass && next.evaluation.scores.pass),
    scoreDelta,
    diffs: buildBehaviorDiffs(next),
  };
}

export function evaluateScenario(result: ScenarioSimulationResult): ScenarioEvaluation {
  const decisionQuality = round2(scoreDecisionQuality(result));
  const executionEfficiency = round2(scoreExecutionEfficiency(result));
  const retryEffectiveness = round2(scoreRetryEffectiveness(result));
  const toolUsageCorrectness = round2(scoreToolUsageCorrectness(result));
  const overall = computeOverall({
    decisionQuality,
    executionEfficiency,
    retryEffectiveness,
    toolUsageCorrectness,
  });
  const pass =
    result.trace.summary.success &&
    decisionQuality >= 0.6 &&
    executionEfficiency >= 0.4 &&
    toolUsageCorrectness >= 0.4 &&
    overall >= 0.55;

  return {
    pass,
    scores: {
      decisionQuality,
      executionEfficiency,
      retryEffectiveness,
      toolUsageCorrectness,
      overall,
      pass,
    },
    diffs: buildBehaviorDiffs(result),
    traceSummary: result.trace.summary,
    traceMetrics: buildRunMetrics([result.trace]),
  };
}

export async function simulateScenario(scenario: SimulationScenario, options: SimulationOptions = {}) {
  return runScenarioOnce(scenario, options);
}

export async function replayRun(runTrace: ScenarioSimulationTrace, options: SimulationOptions = {}) {
  const rerun = await simulateScenario(runTrace.scenario, options);

  const comparison = compareScenarioResults(
    {
      scenario: runTrace.scenario,
      request: runTrace.request,
      classification: classifyInteractionIntent(runTrace.request.text, runTrace.request.mode),
      plan: buildOrchestrationPlan(runTrace.request.text, classifyInteractionIntent(runTrace.request.text, runTrace.request.mode).resolvedMode, buildExecutionSurfaceSnapshot()),
      decision: runTrace.decision,
      policy: runTrace.policy,
      execution: {
        status: runTrace.summary.success ? 'success' : 'failure',
        text: '',
        sources: [],
        modelId: runTrace.modelId,
        completion: null,
        runId: runTrace.runId,
      },
      trace: runTrace,
      evaluation: {
        pass: runTrace.summary.success,
        scores: {
          decisionQuality: 0,
          executionEfficiency: 0,
          retryEffectiveness: 0,
          toolUsageCorrectness: 0,
          overall: 0,
          pass: runTrace.summary.success,
        },
        diffs: [],
        traceSummary: runTrace.summary,
        traceMetrics: buildRunMetrics([runTrace]),
      },
    },
    rerun
  );

  return {
    rerun,
    comparison,
  };
}

export const defaultSimulationScenarios = DEFAULT_SCENARIOS;
