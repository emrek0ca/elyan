import type { SharedBrainWorkload } from "./workloads.js";

export type GroqModelConfigSource = {
  GROQ_REASONING_MODEL?: string | null;
  GROQ_FAST_MODEL?: string | null;
  GROQ_FALLBACK_MODEL?: string | null;
  GROQ_ROUTING_MODEL?: string | null;
  GROQ_VISION_MODEL?: string | null;
  OPENAI_FRONTIER_MODEL?: string | null;
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
  frontierModel: string;
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
  // YÖNLENDİRME MODELİ — sohbet modelinden AYRI ve bilinçli olarak
  // reasoning-DIŞI.
  //
  // `intent`/`fast_route` iş yükleri modelden KATI JSON ister (yönlendirici
  // şeması iç içe `semanticDesktopContract` taşır). gpt-oss ailesi cevaptan
  // önce gizli bir düşünme turu yapar ve o turun token'ları bütçeye sayılır;
  // sonuçta görünür JSON hiç üretilmez (Groq json_validate_failed) ve tur
  // "yanıt oluşturamadım" fallback'ine düşer. Canlı ölçüm (2026-08-08):
  //   gpt-oss-20b  → görünür çıktı BOŞ, yönlendirici hiç karar veremedi
  //   llama-3.1-8b → finish_reason=stop, GEÇERLİ JSON, doğru karar
  // Yönlendirici karar veremeyince hiçbir görev masaüstüne yönlenmiyordu.
  // Sohbet yolları (`mobile_chat_*`) bu değişiklikten ETKİLENMEZ.
  const routingModel =
    compactText(config.GROQ_ROUTING_MODEL) || "llama-3.1-8b-instant";
  const fallbackModel =
    compactText(config.GROQ_FALLBACK_MODEL) ||
    "qwen/qwen3.6-27b";
  const visionModel =
    compactText(config.GROQ_VISION_MODEL) ||
    compactText(config.ELYAN_SHARED_BRAIN_VISION_MODEL) ||
    "qwen/qwen3.6-27b";
  const frontierModel = compactText(config.OPENAI_FRONTIER_MODEL) || "gpt-5.6-terra";
  const compoundModel =
    compactText(config.GROQ_COMPOUND_MODEL) || "groq/compound";
  const compoundMiniModel =
    compactText(config.GROQ_COMPOUND_MINI_MODEL) || "groq/compound-mini";

  return {
    reasoningModel,
    fastModel,
    fallbackModel,
    visionModel,
    frontierModel,
    compoundModel,
    compoundMiniModel,
    defaultModelByWorkload: {
      // intent/routing sınıflandırması hız-kritik ve kaliteye duyarsız: küçük
      // model yeterli, düşük gecikme önemli.
      intent: routingModel,
      fast_route: routingModel,
      // Ana sohbet yolu artık büyük reasoning modelinde (gpt-oss-120b): cevap
      // kalitesi ve "yaşıyor" hissi, ilk-token gecikmesinden önceliklidir.
      // Reasoning effort "medium"da tutulduğu için gizli düşünme turu saniyeler
      // mertebesinde kalır; token akışı yine kesintisizdir. Hız-kritik yollar
      // (intent/fast_route/desktop_handoff) hâlâ küçük modelde.
      // `mobile_chat_fast` adı gereği hız yolu ve yukarıdaki yorum da
      // "hız-kritik yollar hâlâ küçük modelde" diyor; buna rağmen büyük
      // reasoning modeline bağlıydı. Kısa/basit turlarda gizli düşünme turu
      // saniyeler ekliyor ve kalite farkı yaratmıyor.
      mobile_chat_fast: fastModel,
      mobile_chat_balanced: reasoningModel,
      mobile_chat_deep_refine: reasoningModel,
      document_analysis: fallbackModel,
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
    workload === "mobile_chat_deep_refine" ||
    workload === "public_research" ||
    workload === "public_quantum_research";
  const visionWorkload =
    workload === "vision_reasoning" || workload === "image_analyze";
  const preferredOrder =
    workload === "document_analysis"
      ? [catalog.fastModel, catalog.reasoningModel, catalog.fallbackModel]
    : workload === "public_deep_research"
      ? [catalog.reasoningModel, catalog.fastModel, catalog.fallbackModel]
      : chatWorkload || visionWorkload
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
