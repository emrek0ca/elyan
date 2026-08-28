import {
  GEMINI_MODELS,
  isRetiredGeminiModel,
} from "../../config/model-policy.js";
import type { SharedBrainWorkload } from "./workloads.js";
import { trimOnly as compactText } from "../../lib/text.js";

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

/**
 * Gemini image model ids changed from preview aliases to stable ids. Keep the
 * compatibility mapping in one place so an old server .env cannot re-enable
 * models that the provider no longer exposes.
 */
export function normalizeGeminiImageModel(value: unknown): string {
  const model = compactText(value).replace(/^models\//i, "");
  const aliases: Record<string, string> = {
    "gemini-2.0-flash-preview-image-generation": "gemini-3.1-flash-lite-image",
    "gemini-2.5-flash-image-preview": "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-image-preview": "gemini-3.1-flash-image",
    // `gemini-3-pro-image` artık kullanılmıyor: kalite ucu 3.1-flash-image.
    // Sunucudaki bayat `.env` bu kimliği taşıyorsa sessizce doğru uca çevrilir
    // — bu eşlemenin var oluş sebebi tam olarak bu.
    "gemini-3-pro-image-preview": "gemini-3.1-flash-image",
    "gemini-3-pro-image": "gemini-3.1-flash-image",
  };
  return aliases[model.toLowerCase()] ?? model;
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => compactText(value)).filter(Boolean))];
}

/**
 * Yapılandırılan model adı EMEKLİ ise rol varsayılanına düşer.
 *
 * Politika `retired` listesini zaten tutuyor; eksik olan tek şey ona
 * bakmaktı. Emekli bir ad yapılandırmada kaldığında sağlayıcı 404 döner ve
 * o modele bağlı her şey sessizce devre dışı kalır.
 */
function resolveConfiguredModel(configured: string, fallback: string): string {
  if (!configured) return fallback;
  if (isRetiredGeminiModel(configured)) return fallback;
  return configured;
}

export function buildGeminiModelCatalog(
  config: GeminiModelConfigSource,
): GeminiModelCatalog {
  // Elle yazılmış yedek ad, model politikası dışına çıkan İKİNCİ bir liste
  // demekti; emekli bir ad buradan da sızabiliyordu (2026-08-22).
  //
  // AYNI ARIZA YAPILANDIRMADAN GERİ GELDİ (2026-08-28). `GEMINI_FAST_MODEL`
  // `gemini-2.5-flash-lite` idi; o ad model politikasının kendi `retired`
  // listesinde duruyor ve sağlayıcı ona **404** dönüyor
  // (`gemini-2.5-flash` aynı uçta 200). Sonuç: her yardımcı çağrı 404 alıp
  // sessizce `null` dönüyordu ve ona bağlı olan eylem-iddia kapısı — Elyan'ın
  // yapmadığı bir işi yaptım demesini engelleyen kontrol — TAMAMEN kapalıydı.
  //
  // `isRetiredGeminiModel` zaten vardı; yapılandırılan değere hiç
  // uygulanmıyordu. Politika bir adı emekli ilan ettiyse yapılandırma onu geri
  // getiremez: rol varsayılanına düşülür ve durum yazılır. Sessizce ölü bir
  // modele çağrı yapmak, hiç çağrı yapmamaktan kötüdür — çünkü çalıştığı
  // sanılır.
  const fastModel = resolveConfiguredModel(
    compactText(config.GEMINI_FAST_MODEL),
    GEMINI_MODELS.roles.fast_utility,
  );
  const reasoningModel = resolveConfiguredModel(
    compactText(config.GEMINI_REASONING_MODEL),
    "gemini-3.6-flash",
  );
  const textModel = resolveConfiguredModel(
    compactText(config.GEMINI_TEXT_MODEL),
    reasoningModel,
  );
  const visionModel = resolveConfiguredModel(
    compactText(config.GEMINI_VISION_MODEL),
    "gemini-3.1-flash-lite",
  );
  const imageModel =
    normalizeGeminiImageModel(config.GEMINI_IMAGE_MODEL) ||
    "gemini-3.1-flash-lite-image";

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
