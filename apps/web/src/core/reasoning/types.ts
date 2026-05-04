import type { OrchestrationPlan } from '@/core/orchestration';

export type ReasoningLoopInput = {
  input: string;
  intent: string;
  plan: OrchestrationPlan;
  reasoningSteps?: string[];
  action?: string;
  observation?: string;
  refinement?: string;
  output?: string;
  success?: boolean;
  failureReason?: string;
  latencyMs?: number;
  citationCount?: number;
  toolCallCount?: number;
};

export type ReasoningEvaluation = {
  score: number;
  success: boolean;
  notes: string[];
  failureReason?: string;
};

export type ReasoningToolExecution = {
  description: string;
  result?: string;
  solved?: boolean;
};

