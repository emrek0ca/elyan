import type { OrchestrationPlan } from '@/core/orchestration';

export function buildReasoningPlanSummary(plan: OrchestrationPlan, intent: string) {
  const retrievalRounds = plan.retrieval?.rounds ?? 0;
  const retrievalMaxUrls = plan.retrieval?.maxUrls ?? 0;
  const candidateCount = plan.executionPolicy?.candidates?.length ?? 0;

  return [
    `intent=${intent}`,
    `mode=${plan.routingMode}`,
    `depth=${plan.reasoningDepth}`,
    `execution=${plan.executionMode}`,
    `retrieval=${retrievalRounds}r/${retrievalMaxUrls}u`,
    `tooling=${candidateCount}`,
  ].join('; ');
}
