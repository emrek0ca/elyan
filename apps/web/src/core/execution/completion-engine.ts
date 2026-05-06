import type { ModelRoutingMode, TaskIntent } from '@/core/orchestration';
import type { OperatorArtifact, OperatorRun, OperatorRunStep, OperatorRunStatus } from '@/core/operator/runs';

export type ExecutionCompletionVerdict = 'success' | 'retry' | 'failure';

export type ExecutionCompletionOutput = {
  text: string;
  sources: Array<{ url: string; title: string }>;
  success?: boolean;
  failureReason?: string;
  modelId?: string;
  modelProvider?: string;
};

export type ExecutionCompletionArtifact = OperatorArtifact;

export type ExecutionCompletionRetryPlan = {
  modelStrategy: 'alternate' | 'same';
  promptHints: string[];
  toolVariation: 'search' | 'browser' | 'connectors' | 'none';
  searchEnabled: boolean;
};

export type ExecutionCompletionVerification = {
  status: 'passed' | 'failed' | 'blocked';
  summary: string;
};

export type ExecutionCompletionResult = {
  verdict: ExecutionCompletionVerdict;
  reason: string;
  retryLimit: number;
  attempt: number;
  requiredArtifacts: string[];
  missingArtifacts: string[];
  retryPlan?: ExecutionCompletionRetryPlan;
  verification: ExecutionCompletionVerification;
  shouldTriggerLearning: boolean;
  finalRunStatus: OperatorRunStatus;
};

export type ExecutionCompletionInput = {
  run: OperatorRun;
  steps: OperatorRunStep[];
  outputs: ExecutionCompletionOutput[];
  artifacts: ExecutionCompletionArtifact[];
  attempt: number;
  retryLimit?: number;
  taskIntent?: TaskIntent;
  routingMode?: ModelRoutingMode;
};

function normalizeText(value: string) {
  return value.replace(/\s+/g, ' ').trim();
}

function hasMeaningfulText(value: string) {
  return normalizeText(value).length > 0;
}

function hasErrorText(value: string) {
  return /\b(error|exception|timeout|timed out|failed|failure|traceback|unable|cannot|can't|not configured|missing)\b/i.test(value);
}

function hasUnavailableEvidence(value: string) {
  return /\b(unavailable|no verified sources|live evidence is unavailable|evidence unavailable|no reliable sources)\b/i.test(value);
}

function hasCitationMarkers(value: string) {
  return /\[[0-9]+\]/.test(value);
}

function isResearchAligned(output: ExecutionCompletionOutput) {
  return output.sources.length > 0 || hasUnavailableEvidence(output.text) || hasCitationMarkers(output.text);
}

function isTaskAligned(output: ExecutionCompletionOutput) {
  return hasMeaningfulText(output.text);
}

function isCodeAligned(output: ExecutionCompletionOutput) {
  return hasMeaningfulText(output.text) && !hasErrorText(output.text);
}

function resolveRequiredArtifacts(run: OperatorRun): Array<OperatorArtifact['kind']> {
  if (run.mode === 'research') {
    return ['research'];
  }

  if (run.mode === 'code') {
    return ['summary'];
  }

  return ['summary'];
}

function buildRetryPlan(input: ExecutionCompletionInput, output: ExecutionCompletionOutput): ExecutionCompletionRetryPlan {
  const researchMode = input.run.mode === 'research';
  const likelyLocalModel = /^(ollama:|local:|lmstudio:|llama\.cpp:|openai:gpt-oss|anthropic:.*local)/i.test(output.modelId ?? '') ||
    /\b(local|ollama|lmstudio|llama)\b/i.test(output.modelId ?? '');

  return {
    modelStrategy: 'alternate',
    promptHints: researchMode
      ? [
          'Retry with tighter evidence gathering and preserve only grounded citations.',
          output.failureReason ? `Failure reason: ${output.failureReason}` : 'Missing evidence should be addressed explicitly.',
        ]
      : [
          'Retry with a tighter response that matches the task intent exactly.',
          output.failureReason ? `Failure reason: ${output.failureReason}` : 'The previous attempt did not satisfy the completion checks.',
        ],
    toolVariation: researchMode
      ? 'search'
      : input.run.mode === 'code'
        ? 'browser'
        : 'connectors',
    searchEnabled: researchMode ? true : likelyLocalModel,
  };
}

function buildVerificationSummary(
  input: ExecutionCompletionInput,
  output: ExecutionCompletionOutput,
  verdict: ExecutionCompletionVerdict,
  missingArtifacts: string[]
) {
  if (verdict === 'success') {
    if (input.run.mode === 'research') {
      return output.sources.length > 0
        ? 'Research output is grounded in sources and passed completion checks.'
        : 'Research output completed with an explicit unavailable-state explanation.';
    }

    if (input.run.mode === 'code') {
      return 'Code-task output is inspectable and passed the deterministic completion checks.';
    }

    return 'Task output matched the request intent and passed completion checks.';
  }

  if (verdict === 'retry') {
    return missingArtifacts.length > 0
      ? `Completion checks are incomplete: ${missingArtifacts.join(', ')}.`
      : 'Completion checks suggest a retry is needed.';
  }

  return output.failureReason ?? 'Completion checks failed and retries were exhausted.';
}

function buildFinalRunStatus(verdict: ExecutionCompletionVerdict): OperatorRunStatus {
  if (verdict === 'success') {
    return 'completed';
  }

  return 'failed';
}

export function evaluateExecutionCompletion(input: ExecutionCompletionInput): ExecutionCompletionResult {
  const retryLimit = Math.max(0, input.retryLimit ?? 0);
  const output = input.outputs.at(-1);
  const requiredArtifacts = resolveRequiredArtifacts(input.run);
  const artifactKinds = new Set<OperatorArtifact['kind']>(input.artifacts.map((artifact) => artifact.kind));
  const missingArtifacts = requiredArtifacts.filter((kind) => !artifactKinds.has(kind));
  const hasBlockedSteps = input.steps.some((step) => step.status === 'blocked');
  const hasFailedSteps = input.steps.some((step) => step.status === 'failed');
  const hasError = Boolean(output?.failureReason) || hasFailedSteps || Boolean(output && hasErrorText(output.text));
  const alignsWithIntent =
    output
      ? input.run.mode === 'research'
        ? isResearchAligned(output)
        : input.run.mode === 'code'
          ? isCodeAligned(output)
          : isTaskAligned(output)
      : false;

  const enoughArtifacts = missingArtifacts.length === 0;

  const success = Boolean(output) && alignsWithIntent && enoughArtifacts && !hasError && !hasBlockedSteps;
  const reason = success
    ? buildVerificationSummary(input, output!, 'success', missingArtifacts)
    : output?.failureReason?.trim() ||
      (hasFailedSteps ? 'One or more execution steps failed.' : undefined) ||
      (hasBlockedSteps ? 'One or more execution steps are still blocked.' : undefined) ||
      (missingArtifacts.length > 0 ? `Missing required artifacts: ${missingArtifacts.join(', ')}.` : undefined) ||
      (hasErrorText(output?.text ?? '') ? 'Output contains an execution error.' : undefined) ||
      'Completion checks did not pass.';

  if (success) {
    return {
      verdict: 'success',
      reason,
      retryLimit,
      attempt: input.attempt,
      requiredArtifacts,
      missingArtifacts: [],
      verification: {
        status: 'passed',
        summary: reason,
      },
      shouldTriggerLearning: true,
      finalRunStatus: buildFinalRunStatus('success'),
    };
  }

  if (input.attempt < retryLimit) {
    const retryPlan = buildRetryPlan(input, output ?? { text: '', sources: [], failureReason: reason });
    return {
      verdict: 'retry',
      reason,
      retryLimit,
      attempt: input.attempt,
      requiredArtifacts,
      missingArtifacts,
      retryPlan,
      verification: {
        status: 'blocked',
        summary: buildVerificationSummary(input, output ?? { text: '', sources: [], failureReason: reason }, 'retry', missingArtifacts),
      },
      shouldTriggerLearning: false,
      finalRunStatus: buildFinalRunStatus('retry'),
    };
  }

  return {
    verdict: 'failure',
    reason,
    retryLimit,
    attempt: input.attempt,
    requiredArtifacts,
    missingArtifacts,
    verification: {
      status: 'failed',
      summary: buildVerificationSummary(input, output ?? { text: '', sources: [], failureReason: reason }, 'failure', missingArtifacts),
    },
    shouldTriggerLearning: false,
    finalRunStatus: buildFinalRunStatus('failure'),
  };
}
