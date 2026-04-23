import { registry } from '@/core/providers';
import { buildExecutionSurfaceSnapshot, buildOrchestrationPlan } from '@/core/orchestration';
import { answerEngine } from '@/core/agents/answer-engine';
import { readRuntimeSettings, type RuntimeSettings } from '@/core/runtime-settings';
import type { OperatorRequest, OperatorResponse } from './types';
import type { SearchMode } from '@/types/search';

function normalizeMode(mode: SearchMode | undefined, settings: RuntimeSettings): SearchMode {
  if (mode) {
    return mode;
  }

  return settings.routing.searchEnabled ? 'speed' : 'speed';
}

export async function dispatchOperatorRequest(request: OperatorRequest): Promise<OperatorResponse> {
  const settings = await readRuntimeSettings();
  const surface = buildExecutionSurfaceSnapshot();
  const mode = normalizeMode(request.mode, settings);
  const plan = buildOrchestrationPlan(request.text, mode, surface);
  const routingMode = settings.routing.routingMode ?? plan.routingMode;
  const selectedModelId =
    request.modelId?.trim() ||
    settings.routing.preferredModelId?.trim() ||
    (await registry.resolvePreferredModelId({
      routingMode,
      taskIntent: plan.taskIntent,
      reasoningDepth: plan.reasoningDepth,
    }));
  const answer = await answerEngine.executeText(request.text, selectedModelId, mode, {
    plan,
    surface,
    searchEnabled: settings.routing.searchEnabled,
  });

  return {
    text: answer.text,
    sources: answer.sources.map((source) => ({
      url: source.url,
      title: source.title,
    })),
    plan: answer.plan,
    surface,
    settings,
    modelId: selectedModelId,
  };
}
