import type { ReasoningToolExecution } from './types';

export function summarizeReasoningAction(action?: ReasoningToolExecution) {
  if (!action) {
    return 'no tool action';
  }

  const result = action.result?.trim();
  return result ? `${action.description} -> ${result}` : action.description;
}

