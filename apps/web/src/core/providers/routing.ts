import type { ModelRoutingMode, ReasoningDepth, TaskIntent } from '@/core/orchestration';
import type { ModelInfo } from '@/types/provider';

function hasModel(models: ModelInfo[], modelId: string) {
  return models.some((model) => model.id === modelId);
}

function getLocalModelRank(model: ModelInfo, selection: ModelRoutingSelection) {
  const identity = `${model.id} ${model.name}`.toLowerCase();
  const isDeepReasoningWork = selection.reasoningDepth === 'deep';
  let rank = 0;

  if (/\b(deepseek|r1|reasoning)\b/.test(identity)) {
    rank += isDeepReasoningWork ? 0 : 100;
  }

  if (/\b(llama3|llama-3)\b/.test(identity)) {
    rank -= 20;
  }

  if (/\b(qwen2\.5|qwen)\b/.test(identity)) {
    rank -= 10;
  }

  if (
    /\b(coder|code)\b/.test(identity) &&
    selection.taskIntent !== 'procedural' &&
    selection.taskIntent !== 'personal_workflow'
  ) {
    rank += 10;
  }

  if (/\b(latest)\b/.test(identity)) {
    rank += 2;
  }

  return rank;
}

function findLocalModel(models: ModelInfo[], selection: ModelRoutingSelection) {
  return models
    .filter((model) => model.type === 'local')
    .sort((left, right) => {
      const rankDelta = getLocalModelRank(left, selection) - getLocalModelRank(right, selection);
      return rankDelta || left.name.localeCompare(right.name);
    })[0];
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
  if (availableModels.length === 0) {
    throw new Error('No model provider configured');
  }

  const selection =
    typeof preferredModelIdOrSelection === 'string' || preferredModelIdOrSelection === undefined
      ? {
          preferredModelId: preferredModelIdOrSelection,
          routingMode,
        }
      : preferredModelIdOrSelection;

  const trimmedPreferredModelId = selection.preferredModelId?.trim();
  const resolvedRoutingMode = selection.routingMode ?? routingMode;
  const localModel = findLocalModel(availableModels, selection);
  const cloudModel = findCloudModel(availableModels);

  if (trimmedPreferredModelId && hasModel(availableModels, trimmedPreferredModelId)) {
    const preferredModel = availableModels.find((model) => model.id === trimmedPreferredModelId);
    const preferredIsLocal = preferredModel?.type === 'local';
    const preferredIsReasoningTagged =
      preferredModel && /\b(deepseek|r1|reasoning)\b/i.test(`${preferredModel.id} ${preferredModel.name}`);
    const shouldOverridePreferredLocal =
      preferredIsLocal &&
      selection.reasoningDepth !== 'deep' &&
      selection.taskIntent !== 'research' &&
      selection.taskIntent !== 'comparison' &&
      localModel !== undefined &&
      localModel.id !== trimmedPreferredModelId &&
      (preferredIsReasoningTagged || localModel.id !== preferredModel?.id);

    if (!shouldOverridePreferredLocal) {
      return trimmedPreferredModelId;
    }
  }

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
