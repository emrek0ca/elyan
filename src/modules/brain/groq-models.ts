import type { SharedBrainWorkload } from "./workloads.js";

export type GroqModelConfigSource = {
  GROQ_REASONING_MODEL?: string | null;
  GROQ_FAST_MODEL?: string | null;
  GROQ_FALLBACK_MODEL?: string | null;
  GROQ_VISION_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_FAST_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_BALANCED_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_PLANNING_MODEL?: string | null;
  ELYAN_SHARED_BRAIN_VISION_MODEL?: string | null;
  GROQ_COMPOUND_MODEL?: string | null;
  GROQ_COMPOUND_MINI_MODEL?: string | null;
};

export type GroqModelCatalog = {
  reasoningModel: string;
  fastModel: string;
  fallbackModel: string;
  visionModel: string;
  // Groq Compound ajan sistemi modelleri. `models` listesine dahil DEĞİLdir:
  // compound ayrı bir yürütme yolu (yerleşik web/kod araçları) olduğundan
  // gizlilik/atıf/klasik-model varsayımlarına karışmaz.
  compoundModel: string;
  compoundMiniModel: string;
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
  const visionModel =
    compactText(config.GROQ_VISION_MODEL) ||
    compactText(config.ELYAN_SHARED_BRAIN_VISION_MODEL) ||
    "meta-llama/llama-4-scout-17b-16e-instruct";
  const compoundModel =
    compactText(config.GROQ_COMPOUND_MODEL) || "groq/compound";
  const compoundMiniModel =
    compactText(config.GROQ_COMPOUND_MINI_MODEL) || "groq/compound-mini";

  return {
    reasoningModel,
    fastModel,
    fallbackModel,
    visionModel,
    compoundModel,
    compoundMiniModel,
    defaultModelByWorkload: {
      // intent/routing sınıflandırması hız-kritik ve kaliteye duyarsız: küçük
      // model yeterli, düşük gecikme önemli.
      intent: fastModel,
      fast_route: fastModel,
      // Ana sohbet yolu artık büyük reasoning modelinde (gpt-oss-120b): cevap
      // kalitesi ve "yaşıyor" hissi, ilk-token gecikmesinden önceliklidir.
      // Reasoning effort "medium"da tutulduğu için gizli düşünme turu saniyeler
      // mertebesinde kalır; token akışı yine kesintisizdir. Hız-kritik yollar
      // (intent/fast_route/desktop_handoff) hâlâ küçük modelde.
      mobile_chat_fast: reasoningModel,
      mobile_chat_balanced: reasoningModel,
      mobile_chat_deep_refine: reasoningModel,
      document_analysis: fallbackModel,
      document_generate: reasoningModel,
      table_generate: reasoningModel,
      image_analyze: visionModel,
      planning: reasoningModel,
      desktop_handoff: fastModel,
      vision_reasoning: visionModel,
    },
    models: uniqueStrings([reasoningModel, fastModel, fallbackModel, visionModel]),
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
  // Sohbet yolları için fallback sırası: primary 120b düşerse HIZLI ve
  // GÜVENİLİR 20b'ye in (qwen json_validate_failed 400'leriyle kırılgan;
  // ikinci sıraya alındı). Böylece ana modelin nadir düşüşünde bile cevap
  // üretilir, continuity cümlesine düşülmez.
  const chatWorkload =
    workload === "mobile_chat_fast" ||
    workload === "fast_route" ||
    workload === "mobile_chat_balanced" ||
    workload === "mobile_chat_deep_refine";
  const preferredOrder =
    workload === "document_analysis"
      ? [catalog.fastModel, catalog.reasoningModel, catalog.fallbackModel]
      : chatWorkload
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
