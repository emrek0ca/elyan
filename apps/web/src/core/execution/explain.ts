import type { ExecutionCompletionResult } from '@/core/execution/completion-engine';
import type { RunTraceEvent, RunTraceReport } from '@/core/observability/run-trace';
import type { OperatorArtifact, OperatorRun, OperatorRunStep } from '@/core/operator/runs';

export type ExecutionExplanationStep = {
  step: number;
  title: string;
  kind: OperatorRunStep['kind'] | 'unknown';
  status: OperatorRunStep['status'] | 'unknown';
  tool: string;
  modelId: string;
  latencyMs: number;
  reason: string;
  success: boolean;
};

export type ExecutionExplanation = {
  runId: string;
  mode: OperatorRun['mode'];
  taskIntent: string;
  planSummary: string;
  stepsTaken: ExecutionExplanationStep[];
  whyDecisionsWereMade: string[];
  toolsUsed: string[];
  confidenceScore: number;
  verdict: ExecutionCompletionResult['verdict'];
  summary: string;
};

export type ExecutionExplanationInput = {
  run: OperatorRun;
  completion: ExecutionCompletionResult;
  trace?: RunTraceReport | null;
  artifacts?: OperatorArtifact[];
};

function normalizeText(value?: string | null) {
  return typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function round2(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(2)) : 0;
}

function titleCase(value: string) {
  if (!value) {
    return value;
  }

  return value.charAt(0).toUpperCase() + value.slice(1);
}

function getTraceFromArtifacts(artifacts: OperatorArtifact[] = []): RunTraceReport | null {
  for (const artifact of artifacts) {
    const candidate = artifact.metadata?.observabilityTrace;
    if (candidate && typeof candidate === 'object') {
      return candidate as RunTraceReport;
    }
  }

  return null;
}

function getBeforeExecutionEvent(trace: RunTraceReport | null | undefined) {
  return trace?.events.find((event) => event.kind === 'before_execution') ?? null;
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .flatMap((item) => {
      if (typeof item === 'string') {
        return [item];
      }

      if (item && typeof item === 'object') {
        const candidate = item as Record<string, unknown>;
        if (typeof candidate.reason === 'string') {
          return [candidate.reason];
        }

        if (typeof candidate.summary === 'string') {
          return [candidate.summary];
        }
      }

      return [];
    })
    .map(normalizeText)
    .filter((value) => value.length > 0);
}

function readAllowedTools(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.map((item) => String(item).trim()).filter((item) => item.length > 0);
}

function resolveFallbackTool(step: OperatorRunStep | undefined, run: OperatorRun): string {
  if (step?.kind === 'research') {
    return 'web_search';
  }

  if (step?.kind === 'repo_inspection' || step?.kind === 'execution' || step?.kind === 'verification') {
    return run.mode === 'code' ? 'local_tools' : 'direct_answer';
  }

  if (step?.kind === 'memory') {
    return 'memory';
  }

  if (run.mode === 'research') {
    return 'web_search';
  }

  if (run.mode === 'code') {
    return 'local_tools';
  }

  return 'direct_answer';
}

function summarizePlan(run: OperatorRun, completion: ExecutionCompletionResult, trace: RunTraceReport | null | undefined) {
  const taskLabel = titleCase(run.mode);
  const intent = normalizeText(run.intent) || 'the task';
  const base = `${taskLabel} run for ${intent}.`;

  if (completion.verdict === 'success') {
    if (run.mode === 'research') {
      return `${base} It converged on grounded evidence and produced a completion-passed result.`;
    }

    if (run.mode === 'code') {
      return `${base} It completed the inspect-plan-execute-verify loop and passed deterministic checks.`;
    }

    return `${base} It completed the requested task and passed completion checks.`;
  }

  if (completion.verdict === 'retry') {
    const missingArtifacts = completion.missingArtifacts.length > 0 ? ` Missing artifacts: ${completion.missingArtifacts.join(', ')}.` : '';
    return `${base} It required another pass before completion.${missingArtifacts}`;
  }

  const failureDetail = trace?.summary.failureType ? ` Failure type: ${trace.summary.failureType}.` : '';
  return `${base} It failed deterministic completion checks.${failureDetail}`;
}

function collectDecisionReasons(trace: RunTraceReport | null | undefined, completion: ExecutionCompletionResult, artifacts: OperatorArtifact[]) {
  const reasons: string[] = [];
  const beforeExecution = getBeforeExecutionEvent(trace);
  const details = beforeExecution?.details ?? {};

  reasons.push(
    `Completion verdict: ${completion.verdict} (${completion.reason}).`
  );

  const decisionReasoning = readStringArray(details.decisionReasoning);
  if (decisionReasoning.length > 0) {
    reasons.push(...decisionReasoning.map((reason) => `Decision reasoning: ${reason}`));
  } else if (typeof details.decisionReasoning === 'string' && details.decisionReasoning.trim().length > 0) {
    reasons.push(`Decision reasoning: ${details.decisionReasoning.trim()}.`);
  }

  const policy = details.policy && typeof details.policy === 'object' ? (details.policy as Record<string, unknown>) : null;
  if (policy) {
    const allowedTools = readAllowedTools(policy.allowedTools);
    const maxSteps = typeof policy.maxSteps === 'number' ? policy.maxSteps : undefined;
    const maxRetries = typeof policy.maxRetries === 'number' ? policy.maxRetries : undefined;
    const maxTimeMs = typeof policy.maxTimeMs === 'number' ? policy.maxTimeMs : undefined;
    const maxCostUsd = typeof policy.maxCostUsd === 'number' ? policy.maxCostUsd : undefined;
    const policyParts = [
      maxSteps !== undefined ? `${maxSteps} step(s)` : null,
      maxRetries !== undefined ? `${maxRetries} retry(ies)` : null,
      maxTimeMs !== undefined ? `${maxTimeMs} ms` : null,
      maxCostUsd !== undefined ? `$${maxCostUsd.toFixed(2)} cap` : null,
      allowedTools.length > 0 ? `allowed tools: ${allowedTools.join(', ')}` : 'no allowed tools',
    ].filter((part): part is string => Boolean(part));

    if (policyParts.length > 0) {
      reasons.push(`Policy constraints: ${policyParts.join(', ')}.`);
    }
  }

  if (typeof details.solverStrategy === 'string' && details.solverStrategy.trim().length > 0) {
    reasons.push(`Solver strategy: ${details.solverStrategy.trim()}.`);
  }

  if (details.problemRefinement && typeof details.problemRefinement === 'object') {
    const refinement = details.problemRefinement as Record<string, unknown>;
    const refinementSummary =
      typeof refinement.summary === 'string' && refinement.summary.trim().length > 0
        ? refinement.summary.trim()
        : typeof refinement.type === 'string'
          ? `Refined problem type: ${refinement.type}.`
          : '';
    if (refinementSummary) {
      reasons.push(`Problem refinement: ${refinementSummary}`);
    }
  }

  if (typeof details.problemComplexity === 'object' && details.problemComplexity !== null) {
    const complexity = details.problemComplexity as Record<string, unknown>;
    const complexityLabel = typeof complexity.complexity === 'string' ? complexity.complexity : undefined;
    const estimatedSpace = typeof complexity.estimated_space === 'number' ? complexity.estimated_space : undefined;
    if (complexityLabel || estimatedSpace !== undefined) {
      reasons.push(
        `Problem complexity: ${complexityLabel ?? 'unknown'}${estimatedSpace !== undefined ? ` (estimated space ${estimatedSpace})` : ''}.`
      );
    }
  }

  if (typeof details.modelPerformance === 'object' && details.modelPerformance !== null) {
    reasons.push('Historical model performance influenced the selected model and routing policy.');
  }

  if (typeof details.artifactCount === 'number' && details.artifactCount > 0) {
    reasons.push(`Existing artifacts (${details.artifactCount}) informed the explanation and routing.`);
  } else if (artifacts.length > 0) {
    reasons.push(`Existing artifacts (${artifacts.length}) were available to support the run.`);
  }

  if (completion.retryPlan) {
    const retryParts = [
      `Retry plan uses ${completion.retryPlan.modelStrategy} model selection`,
      completion.retryPlan.toolVariation !== 'none' ? `tool variation: ${completion.retryPlan.toolVariation}` : 'no tool variation',
      completion.retryPlan.searchEnabled ? 'search enabled' : 'search disabled',
    ];
    reasons.push(`Retry guidance: ${retryParts.join(', ')}.`);
    if (completion.retryPlan.promptHints.length > 0) {
      reasons.push(...completion.retryPlan.promptHints.map((hint) => `Retry hint: ${hint}`));
    }
  }

  if (trace?.summary.failureType) {
    reasons.push(`Observed failure type: ${trace.summary.failureType}.`);
  }

  return reasons;
}

function summarizeToolsUsed(trace: RunTraceReport | null | undefined, run: OperatorRun) {
  const tools = new Set<string>();
  const steps = run.steps ?? [];

  trace?.events
    .filter((event): event is RunTraceEvent & { tool: string } => typeof event.tool === 'string' && event.tool.trim().length > 0)
    .forEach((event) => {
      tools.add(event.tool);
    });

  if (tools.size === 0) {
    steps.forEach((step, index) => {
      tools.add(resolveFallbackTool(step, run));
      if (index > 8) {
        return;
      }
    });
  }

  return [...tools].filter((tool) => tool.length > 0);
}

function summarizeSteps(run: OperatorRun, trace: RunTraceReport | null | undefined, completion: ExecutionCompletionResult) {
  const steps = run.steps ?? [];
  const stepEvents = new Map<number, { started?: RunTraceEvent; completed?: RunTraceEvent; completion?: RunTraceEvent }>();

  trace?.events.forEach((event) => {
    if (event.kind === 'before_execution') {
      return;
    }

    const entry = stepEvents.get(event.step) ?? {};
    if (event.kind === 'step_started') {
      entry.started = event;
    } else if (event.kind === 'step_completed') {
      entry.completed = event;
    } else if (event.kind === 'completion') {
      entry.completion = event;
    }
    stepEvents.set(event.step, entry);
  });

  return steps.map((step, index) => {
    const stepNumber = index + 1;
    const eventGroup = stepEvents.get(stepNumber);
    const completedEvent = eventGroup?.completed;
    const completionEvent = eventGroup?.completion;
    const successful = completionEvent?.success ?? completedEvent?.success ?? step.status === 'completed';
    const latencyMs = Math.max(0, Math.round(completedEvent?.latencyMs ?? completionEvent?.latencyMs ?? 0));
    const tool = completedEvent?.tool ?? eventGroup?.started?.tool ?? resolveFallbackTool(step, run);
    const modelId = completedEvent?.modelId ?? eventGroup?.started?.modelId ?? trace?.modelId ?? 'unknown';
    const completionReason =
      completionEvent?.details && typeof completionEvent.details === 'object'
        ? typeof (completionEvent.details as Record<string, unknown>).reason === 'string'
          ? String((completionEvent.details as Record<string, unknown>).reason)
          : undefined
        : undefined;
    const reason =
      completionReason
        ? completionReason
        : completedEvent?.errorType
          ? `Observed ${completedEvent.errorType} during step completion.`
          : successful
            ? 'Step completed without a recorded failure.'
            : completion.verdict === 'retry'
              ? 'Step contributed to a retry.'
              : 'Step contributed to the final completion result.';

    return {
      step: stepNumber,
      title: step.title,
      kind: step.kind,
      status: step.status,
      tool,
      modelId,
      latencyMs,
      reason,
      success: successful,
    };
  });
}

function scoreConfidence(input: {
  run: OperatorRun;
  completion: ExecutionCompletionResult;
  trace: RunTraceReport | null | undefined;
  stepsTaken: ExecutionExplanationStep[];
  toolsUsed: string[];
  artifacts: OperatorArtifact[];
}) {
  let score = 0.44;

  if (input.completion.verdict === 'success') {
    score += 0.22;
  } else if (input.completion.verdict === 'retry') {
    score += 0.04;
  } else {
    score -= 0.12;
  }

  if (input.trace) {
    score += 0.08;
    score += input.trace.summary.success ? 0.08 : -0.04;
    score += input.trace.summary.stepCount > 0 ? 0.05 : 0;
    score -= Math.min(0.12, input.trace.summary.retryCount * 0.04);
    score += input.trace.summary.avgLatencyMs > 0 ? 0.02 : 0;
  }

  if (input.stepsTaken.some((step) => step.success)) {
    score += 0.04;
  }

  if (input.toolsUsed.length > 0) {
    score += 0.04;
  }

  if (input.artifacts.length > 0) {
    score += 0.03;
  }

  if (input.completion.missingArtifacts.length > 0) {
    score -= Math.min(0.14, input.completion.missingArtifacts.length * 0.04);
  }

  if (input.completion.retryPlan) {
    score -= 0.03;
  }

  if (input.run.mode === 'research' && input.completion.verdict === 'success' && (input.trace?.summary.success ?? false)) {
    score += 0.04;
  }

  return round2(clamp(score, 0, 1));
}

function buildSummary(explanation: ExecutionExplanation) {
  const stepCount = explanation.stepsTaken.length;
  const toolLabel = explanation.toolsUsed.length > 0 ? explanation.toolsUsed.join(', ') : 'no explicit tools';
  return `${explanation.planSummary} ${stepCount} step(s) were analyzed with ${toolLabel}. Confidence ${explanation.confidenceScore.toFixed(2)}.`;
}

export function explainExecution(input: ExecutionExplanationInput): ExecutionExplanation {
  const trace = input.trace ?? getTraceFromArtifacts(input.artifacts);
  const toolsUsed = summarizeToolsUsed(trace, input.run);
  const stepsTaken = summarizeSteps(input.run, trace, input.completion);
  const explanation: ExecutionExplanation = {
    runId: input.run.id,
    mode: input.run.mode,
    taskIntent: input.run.intent,
    planSummary: summarizePlan(input.run, input.completion, trace),
    stepsTaken,
    whyDecisionsWereMade: collectDecisionReasons(trace, input.completion, input.artifacts ?? input.run.artifacts),
    toolsUsed,
    confidenceScore: 0,
    verdict: input.completion.verdict,
    summary: '',
  };

  explanation.confidenceScore = scoreConfidence({
    run: input.run,
    completion: input.completion,
    trace,
    stepsTaken,
    toolsUsed,
    artifacts: input.artifacts ?? input.run.artifacts,
  });
  explanation.summary = buildSummary(explanation);

  return explanation;
}

export function formatExecutionExplanation(explanation: ExecutionExplanation) {
  const lines: string[] = [
    `Plan summary: ${explanation.planSummary}`,
    'Steps taken:',
  ];

  if (explanation.stepsTaken.length === 0) {
    lines.push('- No step-level trace was available.');
  } else {
    explanation.stepsTaken.forEach((step) => {
      const toolLabel = step.tool ? `tool=${step.tool}` : 'tool=unknown';
      const latencyLabel = `${step.latencyMs}ms`;
      lines.push(`- Step ${step.step} (${step.kind}, ${step.status}, ${toolLabel}, ${latencyLabel}, model=${step.modelId}) — ${step.reason}`);
    });
  }

  lines.push('Why decisions were made:');
  if (explanation.whyDecisionsWereMade.length === 0) {
    lines.push('- No decision trace was available; explanation was inferred from the run state.');
  } else {
    explanation.whyDecisionsWereMade.forEach((reason) => {
      lines.push(`- ${reason}`);
    });
  }

  lines.push(`Tools used: ${explanation.toolsUsed.length > 0 ? explanation.toolsUsed.join(', ') : 'none'}`);
  lines.push(`Confidence score: ${explanation.confidenceScore.toFixed(2)}`);
  lines.push(`Verdict: ${explanation.verdict}`);

  return lines.join('\n');
}
