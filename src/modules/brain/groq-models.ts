import type { SharedBrainWorkload } from "./workloads.js";

type GroqModelConfigSource = {
  GROQ_REASONING_MODEL?: string | null;
  GROQ_FAST_MODEL?: string | null;
  GROQ_FALLBACK_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_FAST_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_BALANCED_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_PLANNING_MODEL?: string | null;
};

export type GroqModelCatalog = {
  reasoningModel: string;
  fastModel: string;
  fallbackModel: string;
  defaultModelByWorkload: Record<SharedBrainWorkload, string>;
  models: string[];
};

function compactText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => compactText(value)).filter(Boolean))];
}

export function buildGroqModelCatalog(config: GroqModelConfigSource): GroqModelCatalog {
  const reasoningModel =
    compactText(config.GROQ_REASONING_MODEL) ||
    compactText(config.ELYAN_SHARED_BRAIN_MODEL) ||
    "openai/gpt-oss-120b";
  const fastModel =
    compactText(config.GROQ_FAST_MODEL) ||
    compactText(config.ELYAN_SHARED_BRAIN_FAST_MODEL) ||
    "openai/gpt-oss-20b";
  const fallbackModel =
    compactText(config.GROQ_FALLBACK_MODEL) ||
    compactText(config.ELYAN_SHARED_BRAIN_BALANCED_MODEL) ||
    compactText(config.ELYAN_SHARED_BRAIN_PLANNING_MODEL) ||
    "qwen/qwen3.6-27b";

  return {
    reasoningModel,
    fastModel,
    fallbackModel,
    defaultModelByWorkload: {
      intent: fastModel,
      fast_route: fastModel,
      mobile_chat_fast: reasoningModel,
      mobile_chat_balanced: reasoningModel,
      document_analysis: fallbackModel,
      planning: reasoningModel,
      desktop_handoff: fastModel,
    },
    models: uniqueStrings([reasoningModel, fastModel, fallbackModel]),
  };
}

export function resolveGroqModelForWorkload(
  config: GroqModelConfigSource,
  workload: SharedBrainWorkload,
): string {
  return buildGroqModelCatalog(config).defaultModelByWorkload[workload];
}

export function resolveGroqFallbackModel(
  config: GroqModelConfigSource,
  primaryModel?: string | null,
  workload?: SharedBrainWorkload,
): string | null {
  const catalog = buildGroqModelCatalog(config);
  const preferredOrder =
    workload === "document_analysis"
      ? [catalog.fastModel, catalog.reasoningModel, catalog.fallbackModel]
      : [catalog.fallbackModel, catalog.reasoningModel, catalog.fastModel];
  const primary = compactText(primaryModel).toLowerCase();

  for (const model of preferredOrder) {
    if (!model) {
      continue;
    }
    if (compactText(model).toLowerCase() !== primary) {
      return model;
    }
  }

  return null;
}
