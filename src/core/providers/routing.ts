import type { ModelRoutingMode, ReasoningDepth, TaskIntent } from '@/core/orchestration';
import type { ModelInfo } from '@/types/provider';

function hasModel(models: ModelInfo[], modelId: string) {
  return models.some((model) => model.id === modelId);
}

function findLocalModel(models: ModelInfo[]) {
  return models.find((model) => model.type === 'local');
}

function findCloudModel(models: ModelInfo[]) {
  return models.find((model) => model.type === 'cloud');
}

export type ModelRoutingSelection = {
  preferredModelId?: string;
  routingMode?: ModelRoutingMode;
  taskIntent?: TaskIntent;
  reasoningDepth?: ReasoningDepth;
};

function shouldPreferCloud(
  routingMode: ModelRoutingMode,
  taskIntent?: TaskIntent,
  reasoningDepth?: ReasoningDepth
) {
  if (routingMode === 'cloud_preferred') {
    return true;
  }

  if (routingMode === 'balanced') {
    return taskIntent === 'research' || taskIntent === 'comparison' || reasoningDepth === 'deep';
  }

  return false;
}

export function resolvePreferredModelIdFromAvailableModels(
  availableModels: ModelInfo[],
  preferredModelIdOrSelection?: string | ModelRoutingSelection,
  routingMode: ModelRoutingMode = 'local_first'
): string {
  const selection =
    typeof preferredModelIdOrSelection === 'string' || preferredModelIdOrSelection === undefined
      ? {
          preferredModelId: preferredModelIdOrSelection,
          routingMode,
        }
      : preferredModelIdOrSelection;

  const trimmedPreferredModelId = selection.preferredModelId?.trim();
  if (trimmedPreferredModelId && hasModel(availableModels, trimmedPreferredModelId)) {
    return trimmedPreferredModelId;
  }

  const resolvedRoutingMode = selection.routingMode ?? routingMode;
  const localModel = findLocalModel(availableModels);
  const cloudModel = findCloudModel(availableModels);

  if (resolvedRoutingMode === 'local_only') {
    if (localModel) {
      return localModel.id;
    }

    throw new Error('No local models are currently available. Configure Ollama or select a different routing mode.');
  }

  if (shouldPreferCloud(resolvedRoutingMode, selection.taskIntent, selection.reasoningDepth)) {
    if (cloudModel) {
      return cloudModel.id;
    }

    if (localModel) {
      return localModel.id;
    }
  }

  if (localModel) {
    return localModel.id;
  }

  if (cloudModel) {
    return cloudModel.id;
  }

  throw new Error('No models are currently available. Configure Ollama or set at least one cloud API key.');
}
