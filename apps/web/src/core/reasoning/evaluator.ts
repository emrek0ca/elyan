import type { ReasoningEvaluation, ReasoningLoopInput } from './types';

export function evaluateReasoningOutcome(input: ReasoningLoopInput): ReasoningEvaluation {
  const notes: string[] = [];
  const outputLength = input.output?.trim().length ?? 0;
  const citationCount = input.citationCount ?? 0;
  const toolCallCount = input.toolCallCount ?? 0;
  const latencyMs = input.latencyMs ?? 0;

  const completeness = outputLength > 0 ? 0.35 : 0.05;
  const evidence = citationCount > 0 ? 0.2 : 0.05;
  const actionCoverage = toolCallCount > 0 ? 0.2 : 0.1;
  const latencyPenalty = latencyMs > 0 ? Math.min(0.2, latencyMs / 60000) : 0;
  const successBonus = input.success ? 0.2 : 0;
  const failurePenalty = input.failureReason ? 0.15 : 0;

  if (outputLength === 0) {
    notes.push('empty_output');
  }
  if (citationCount > 0) {
    notes.push('grounded');
  }
  if (toolCallCount > 0) {
    notes.push('tool_use');
  }
  if (input.failureReason) {
    notes.push(`failure:${input.failureReason}`);
  }

  const score = Math.max(
    0,
    Math.min(1, completeness + evidence + actionCoverage + successBonus - latencyPenalty - failurePenalty)
  );

  return {
    score: Number(score.toFixed(2)),
    success: Boolean(input.success && score >= 0.5),
    notes,
    failureReason: input.failureReason,
  };
}

