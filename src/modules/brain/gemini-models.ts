import type { SharedBrainWorkload } from "./workloads.js";

type GeminiModelConfigSource = {
  GEMINI_TEXT_MODEL?: string | null;
  GEMINI_FAST_MODEL?: string | null;
  GEMINI_REASONING_MODEL?: string | null;
  GEMINI_VISION_MODEL?: string | null;
  GEMINI_IMAGE_MODEL?: string | null;
  GEMINI_IMAGE_PRO_MODEL?: string | null;
};

export type GeminiModelCatalog = {
  textModel: string;
  fastModel: string;
  reasoningModel: string;
  visionModel: string;
  imageModel: string;
  defaultModelByWorkload: Record<SharedBrainWorkload, string>;
  models: string[];
};

function compactText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => compactText(value)).filter(Boolean))];
}

export function buildGeminiModelCatalog(
  config: GeminiModelConfigSource,
): GeminiModelCatalog {
  const fastModel = compactText(config.GEMINI_FAST_MODEL) || "gemini-3.1-flash-lite";
  const reasoningModel =
    compactText(config.GEMINI_REASONING_MODEL) || "gemini-3.5-flash";
  const textModel = compactText(config.GEMINI_TEXT_MODEL) || reasoningModel;
  const visionModel = compactText(config.GEMINI_VISION_MODEL) || "gemini-3.5-flash";
  const imageModel =
    compactText(config.GEMINI_IMAGE_MODEL) || "gemini-3.1-flash-image-preview";

  return {
    textModel,
    fastModel,
    reasoningModel,
    visionModel,
    imageModel,
    defaultModelByWorkload: {
      intent: fastModel,
      fast_route: fastModel,
      mobile_chat_fast: fastModel,
      mobile_chat_balanced: textModel,
      mobile_chat_deep_refine: reasoningModel,
      document_analysis: textModel,
      document_generate: reasoningModel,
      table_generate: reasoningModel,
      image_analyze: visionModel,
      planning: reasoningModel,
      public_research: reasoningModel,
      public_deep_research: reasoningModel,
      public_quantum_research: reasoningModel,
      desktop_handoff: fastModel,
      vision_reasoning: visionModel,
    },
    models: uniqueStrings([
      textModel,
      fastModel,
      reasoningModel,
      visionModel,
      imageModel,
    ]),
  };
}

export function resolveGeminiFallbackModel(
  config: GeminiModelConfigSource,
  primaryModel?: string | null,
): string | null {
  const catalog = buildGeminiModelCatalog(config);
  const primary = compactText(primaryModel).toLowerCase();

  for (const model of [
    catalog.fastModel,
    catalog.textModel,
    catalog.reasoningModel,
    catalog.visionModel,
  ]) {
    if (compactText(model).toLowerCase() !== primary) {
      return model;
    }
  }

  return null;
}
