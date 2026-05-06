import { buildReasoningPlanSummary } from './planner';
import { evaluateReasoningOutcome } from './evaluator';
import { summarizeReasoningAction } from './executor';
import type { ReasoningEvaluation, ReasoningLoopInput, ReasoningToolExecution } from './types';

export type ReasoningLoopPass = {
  step: string;
  action?: ReasoningToolExecution;
  observation?: string;
  refinement?: string;
};

export type ReasoningLoopResult = {
  output: string;
  reasoningSteps: string[];
  evaluation: ReasoningEvaluation;
  passes: ReasoningLoopPass[];
};

export function buildReasoningTrace(input: ReasoningLoopInput) {
  const planSummary = buildReasoningPlanSummary(input.plan, input.intent);
  const steps = input.reasoningSteps?.slice() ?? [];

  if (steps.length === 0) {
    steps.push(`input: ${input.input.slice(0, 240)}`);
    steps.push(`intent: ${input.intent}`);
    steps.push(`plan: ${planSummary}`);
  }

  steps.push(`action: ${input.action ?? 'no tool action'}`);
  steps.push(`observe: ${input.observation ?? 'no observation'}`);
  steps.push(`refine: ${input.refinement ?? 'retain grounded answer'}`);
  steps.push(`output: ${(input.output ?? '').slice(0, 240)}`);

  return steps;
}

export async function runReasoningLoop(input: {
  loop: ReasoningLoopInput;
  maxPasses?: number;
  toolExecutor?: (pass: number, context: ReasoningLoopResult | null) => Promise<ReasoningToolExecution | null>;
}): Promise<ReasoningLoopResult> {
  const passes: ReasoningLoopPass[] = [];
  let context: ReasoningLoopResult | null = null;
  const maxPasses = Math.max(1, input.maxPasses ?? 3);
  let output = input.loop.output ?? '';

  for (let pass = 0; pass < maxPasses; pass += 1) {
    const action = input.toolExecutor ? await input.toolExecutor(pass, context) : null;
    const stepLabel = `pass_${pass + 1}`;
    const observation = action?.result?.trim() || input.loop.observation || 'no observation';
    const refinement = action?.solved ? 'solved' : input.loop.refinement || 'refine grounded answer';

    passes.push({
      step: stepLabel,
      action: action ?? undefined,
      observation,
      refinement,
    });

    if (action?.result?.trim()) {
      output = action.result.trim();
    }

    context = {
      output,
      reasoningSteps: buildReasoningTrace({
        ...input.loop,
        action: summarizeReasoningAction(action ?? undefined),
        observation,
        refinement,
        output,
      }),
      evaluation: evaluateReasoningOutcome({
        ...input.loop,
        action: summarizeReasoningAction(action ?? undefined),
        observation,
        refinement,
        output,
        success: action?.solved ?? input.loop.success,
      }),
      passes,
    } as ReasoningLoopResult;

    if (action?.solved || context.evaluation.success) {
      break;
    }
  }

  const evaluation = evaluateReasoningOutcome({
    ...input.loop,
    output,
    success: input.loop.success ?? Boolean(output.trim()),
  });
  const reasoningSteps = buildReasoningTrace({
    ...input.loop,
    action: passes.at(-1)?.action ? summarizeReasoningAction(passes.at(-1)!.action) : input.loop.action,
    observation: passes.at(-1)?.observation ?? input.loop.observation,
    refinement: passes.at(-1)?.refinement ?? input.loop.refinement,
    output,
    success: input.loop.success,
  });

  return {
    output,
    reasoningSteps,
    evaluation,
    passes,
  };
}

