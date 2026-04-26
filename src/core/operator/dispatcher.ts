import { executeInteractionText } from '@/core/interaction/orchestrator';
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
  const mode = normalizeMode(request.mode, settings);
  const answer = await executeInteractionText({
    source: request.source,
    text: request.text,
    mode,
    modelId: request.modelId,
    conversationId: request.conversationId,
    messageId: request.messageId,
    userId: request.userId,
    displayName: request.displayName,
    metadata: request.metadata,
  });

  return {
    text: answer.text,
    sources: answer.sources.map((source) => ({
      url: source.url,
      title: source.title,
    })),
    plan: answer.plan,
    surface: answer.surface,
    settings,
    modelId: answer.modelId,
  };
}
