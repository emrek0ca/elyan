import type { LanguageModelUsage } from 'ai';
import type {
  ControlPlaneEvaluationQuality,
  ControlPlaneEvaluationSignalDraft,
} from '@/core/control-plane/types';
import type { SearchMode } from '@/types/search';
import type { OrchestrationPlan, ExecutionTarget } from './types';
import type { ExecutionSurfaceSnapshot } from './surface';

type BuildEvaluationSignalInput = {
  requestId?: string;
  mode: SearchMode;
  plan: OrchestrationPlan;
  surface: ExecutionSurfaceSnapshot;
  searchAvailable: boolean;
  operatorNotes: string[];
  operatorTarget?: ExecutionTarget;
  modelProvider: string;
  modelId: string;
  text: string;
  queryLength: number;
  latencyMs: number;
  totalUsage: LanguageModelUsage;
  toolCallCount: number;
  toolResultCount: number;
  sourcesCount: number;
};

function countCitations(text: string) {
  const markers = text.match(/\[(\d+)\]/g) ?? [];
  return new Set(markers).size;
}

function resolveEvaluationQuality(input: BuildEvaluationSignalInput, citationCount: number): ControlPlaneEvaluationQuality {
  if (!input.plan.executionPolicy.shouldRetrieve) {
    return 'skipped';
  }

  if (input.sourcesCount === 0 && !input.searchAvailable) {
    return 'mixed';
  }

  if (input.sourcesCount === 0 && input.searchAvailable) {
    return 'poor';
  }

  if (input.toolCallCount > 0 && input.toolResultCount < input.toolCallCount) {
    return 'mixed';
  }

  if (input.sourcesCount > 0 && citationCount === 0) {
    return 'mixed';
  }

  if (input.searchAvailable || input.sourcesCount > 0 || input.toolCallCount > 0) {
    return 'good';
  }

  return 'skipped';
}

export function buildEvaluationSignalDraft(input: BuildEvaluationSignalInput): ControlPlaneEvaluationSignalDraft {
  const enabledCapabilities = input.plan.capabilityPolicy
    .filter((entry) => entry.enabled && entry.family !== 'retrieval')
    .map((entry) => entry.capabilityId);
  const citationCount = countCitations(input.text);
  const quality = resolveEvaluationQuality(input, citationCount);
  const promotionCandidate =
    input.plan.evaluation.promoteLearnings &&
    quality === 'good' &&
    input.sourcesCount > 0 &&
    citationCount > 0;
  const totalTokens = input.totalUsage.totalTokens;

  return {
    requestId: input.requestId,
    mode: input.mode,
    surface: input.plan.surface,
    model: {
      provider: input.modelProvider,
      modelId: input.modelId,
    },
    taskIntent: input.plan.taskIntent,
    reasoningDepth: input.plan.reasoningDepth,
    routingMode: input.plan.routingMode,
    intentConfidence: input.plan.intentConfidence,
    retrieval: {
      shouldRetrieve: input.plan.executionPolicy.shouldRetrieve,
      searchAvailable: input.searchAvailable,
      rounds: input.plan.retrieval.rounds,
      maxUrls: input.plan.retrieval.maxUrls,
      sourceCount: input.sourcesCount,
      citationCount,
    },
    tooling: {
      enabled: enabledCapabilities.length > 0,
      capabilityIds: enabledCapabilities,
      toolCallCount: input.toolCallCount,
      toolResultCount: input.toolResultCount,
    },
    usage: {
      inputTokens: input.totalUsage.inputTokens ?? undefined,
      outputTokens: input.totalUsage.outputTokens ?? undefined,
      totalTokens: totalTokens ?? undefined,
    },
    latencyMs: input.latencyMs,
    queryLength: input.queryLength,
    answerLength: input.text.length,
    quality,
    promotionCandidate,
    notes: [
      input.plan.executionPolicy.decisionSummary,
      ...input.operatorNotes.slice(0, 2),
      input.operatorTarget
        ? `Primary execution target: ${input.operatorTarget.kind}${input.operatorTarget.id ? ` (${input.operatorTarget.id})` : ''}.`
        : 'Primary execution target: direct answer.',
      `Retrieved sources: ${input.sourcesCount}. Citations: ${citationCount}.`,
    ].filter(Boolean),
  };
}
