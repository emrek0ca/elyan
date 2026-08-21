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
  /**
   * Compatibility fallback for machine-json calls. This is deliberately not
   * the primary model for routing or planning: those workloads should use the
   * configured OSS fast/deep model and only fall back here after a provider
   * rejection or malformed JSON response.
   */
  structuredJsonModel: string;
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

/**
 * These workloads are transported as machine JSON. Their response is always
 * parsed and validated by the typed caller. Routing and planning may start on
 * the configured OSS models; the provider-selection layer keeps one bounded
 * compatibility fallback for malformed JSON or provider rejection.
 */
export function isStructuredGroqWorkload(
  workload: SharedBrainWorkload | undefined,
): boolean {
  return (
    workload === "intent" ||
    workload === "fast_route" ||
    workload === "document_analysis" ||
    workload === "planning"
  );
}

const DEFAULT_STRUCTURED_JSON_MODEL = "qwen/qwen3.6-27b";
const RETIRED_STRUCTURED_JSON_MODELS = new Set(["llama-3.1-8b-instant"]);

function compactText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => compactText(value)).filter(Boolean))];
}

/** Model gpt ailesinden mi? */
function isGptFamilyModel(model: string): boolean {
  return model.toLowerCase().includes("gpt");
}

/**
 * MODEL POLİTİKASI: yalnız gpt ailesi.
 *
 * Politikayı env hijyenine bırakmıyoruz, YAPISAL yapıyoruz. Sebebi ölçüldü:
 * canlı `.env`'de `GROQ_REASONING_MODEL` hiç tanımlı değildi ve
 * `ELYAN_SHARED_BRAIN_MODEL=llama-3.1-8b-instant` zincirin ikinci halkasından
 * girip kodun `gpt-oss-120b` niyetini eziyordu. Sonuç: ana sohbet, planlama,
 * belge ve tablo üretiminin TAMAMI 8B bir modelde koşuyordu — kodun kendi
 * yorumu "ana sohbet yolu artık büyük reasoning modelinde" derken.
 *
 * Artık gpt DIŞI bir değer geldiğinde sessizce yok sayılıp gpt varsayılanına
 * düşülür; yani bayat bir env satırı bir daha model seçimini ele geçiremez.
 */
function gptOnlyModel(
  candidate: string | null | undefined,
  fallback: string,
): string {
  const value = compactText(candidate);
  if (!value) return fallback;
  return isGptFamilyModel(value) ? value : fallback;
}

export function buildGroqModelCatalog(config: GroqModelConfigSource): GroqModelCatalog {
  const reasoningModel = gptOnlyModel(
    compactText(config.GROQ_REASONING_MODEL) ||
      compactText(config.ELYAN_SHARED_BRAIN_MODEL),
    "openai/gpt-oss-120b",
  );
  const fastModel = gptOnlyModel(
    compactText(config.GROQ_FAST_MODEL) ||
      compactText(config.ELYAN_SHARED_BRAIN_FAST_MODEL),
    "openai/gpt-oss-20b",
  );
  // KATI-JSON UYUMLULUK ŞERİDİ — gpt-only politikasının BİLİNÇLİ İSTİSNASI.
  //
  // Bu şerit modelden şemaya birebir uyan JSON ister. gpt-oss ailesi cevaptan
  // önce gizli bir düşünme turu yapar ve o turun token'ları bütçeye sayılır;
  // geriye geçerli JSON kalmaz. İstek gövdesinde `response_format: json_schema`
  // ile `reasoning_effort` yan yana gidiyor (`provider-request.ts`), Groq da
  // bunu `json_validate_failed` ile 400'lüyor.
  //
  // İKİ AYRI CANLI ÖLÇÜM, aynı sonuç:
  //   2026-08-08 (yönlendirme): gpt-oss-20b → görünür çıktı BOŞ, yönlendirici
  //     karar veremedi, hiçbir görev masaüstüne gitmedi.
  //     llama-3.1-8b → finish_reason=stop, GEÇERLİ JSON, doğru karar.
  //   2026-08-13 (görev a4924a76, "3.sınıf matematik PDF yaz"):
  //     gpt-oss-20b → 400 json_validate_failed
  //     qwen3.6-27b → 400 json_validate_failed
  //     → server_brain_unavailable → kullanıcı "Bu turda yanıt oluşturulamadı"
  //       gördü ve PDF hiç üretilmedi.
  //
  // `reasoning_effort: "low"` tek başına panzehir değildir. Bu model yalnız
  // gpt-oss plan/routing çağrısı geçersiz dönerse fallback olarak kullanılır;
  // baştan tüm sistemi bu hatta kilitlemek kaliteyi ve modeli saklar.
  //
  // Kapsam dar: sohbet, akıl yürütme ve karmaşık planlama gpt-oss'ta kalır;
  // belge analizi gibi provider-şema hassas işleri bu uyumluluk modeli taşır.
  const configuredStructuredJsonModel = compactText(config.GROQ_ROUTING_MODEL);
  const structuredJsonModel =
    !configuredStructuredJsonModel ||
    RETIRED_STRUCTURED_JSON_MODELS.has(configuredStructuredJsonModel.toLowerCase())
      ? DEFAULT_STRUCTURED_JSON_MODEL
      : configuredStructuredJsonModel;
  // `GROQ_ROUTING_MODEL` is retained as the compatibility model, not as the
  // authoritative model selection. The previous implementation used it for
  // both routing and planning, so an old qwen value silently replaced the
  // configured gpt-oss-20b/120b pair. Fast routing is intentionally cheap;
  // complex desktop planning gets the deep model and has the compatibility
  // model as a bounded fallback.
  const routingModel = fastModel;
  const planningModel = gptOnlyModel(
    config.ELYAN_SHARED_BRAIN_PLANNING_MODEL,
    reasoningModel,
  );
  const fallbackModel = gptOnlyModel(
    config.GROQ_FALLBACK_MODEL,
    "openai/gpt-oss-120b",
  );
  // TEK İSTİSNA — GÖRME. Groq'ta gpt-oss ailesinin görsel girdisi yok; buraya
  // bir gpt adı yazmak vision'ı tamamen kırar. Bu yüzden politika dışında
  // bırakıldı ve BİLEREK belgelendi. Gerçek gpt görme istenirse yol Groq değil
  // frontier/OpenAI sağlayıcısıdır ve ayrı bir yönlendirme işidir.
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
    structuredJsonModel,
    fallbackModel,
    visionModel,
    frontierModel,
    compoundModel,
    compoundMiniModel,
    defaultModelByWorkload: {
      // intent/routing sınıflandırması hız-kritik: gpt-oss-20b ile çalışır.
      // JSON geçersiz olursa resolveGroqFallbackModel() compatibility
      // modeline tek kez düşürür; yönlendirme qwen'e kalıcı olarak kilitli
      // değildir.
      intent: routingModel,
      fast_route: routingModel,
      // Sıradan kısa sohbet hızlı modelde kalır. `mobile_chat_balanced`,
      // routing-policy'nin matematik/eğitim/debug ve belirsizlik gibi kalite
      // sinyalleriyle seçtiği hattır; bunu da 20B'ye indirmek, istek doğru
      // sınıflandırıldığı halde cevabı yine yüzeysel modele vermek demekti.
      // Derin/planlama hatlarıyla aynı 120B reasoning modelini kullanır;
      // yalnız gerçekten kısa/casual tur 20B'de kalır.
      mobile_chat_fast: fastModel,
      mobile_chat_balanced: reasoningModel,
      mobile_chat_deep_refine: reasoningModel,
      // KATI-JSON ŞERİDİ. Belge analizi şemaya uyan JSON döndürüyor; canlıda
      // (2026-08-13, görev a4924a76) bu iş yükünde önce gpt-oss-20b sonra
      // qwen 400 `json_validate_failed` verdi ve PDF isteği hiç üretilemedi.
      document_analysis: structuredJsonModel,
      document_generate: reasoningModel,
      table_generate: reasoningModel,
      image_analyze: visionModel,
      // Karmaşık planlama 120B'ye gider. Makine JSON sözleşmesi provider
      // response_format'a değil, plan prompt'u + typed validator'a dayanır;
      // bu nedenle gpt-oss'un kalite avantajını kullanabiliriz. Sağlayıcı
      // reddederse structuredJsonModel yedeklenir.
      planning: planningModel,
      public_research: reasoningModel,
      public_deep_research: reasoningModel,
      public_quantum_research: reasoningModel,
      desktop_handoff: fastModel,
      vision_reasoning: visionModel,
    },
    // `models` sağlayıcı aday/keşif listesidir. Katı-JSON modeli buraya
    // GİRMEZ — yönlendirme modeli de hiç girmiyordu. Şerit iş yükü bazında
    // seçilir; listeye eklemek sağlayıcı adaylarını sessizce değiştirirdi.
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
  const primary = compactText(primaryModel).toLowerCase();
  if (workload === "intent" || workload === "fast_route") {
    // Fast semantic routing must not fall through to the 120B model. If the
    // 20B output is rejected, use the known JSON-compatible model once.
    const fastStructuredOrder = [
      catalog.structuredJsonModel,
      catalog.reasoningModel,
    ];
    for (const model of fastStructuredOrder) {
      if (compactText(model).toLowerCase() !== primary) return model;
    }
    return null;
  }
  if (workload === "planning") {
    // Planning is quality-first. Keep the compatibility model as a bounded
    // fallback, but do not start every request on it.
    if (
      compactText(catalog.structuredJsonModel).toLowerCase() !== primary
    ) {
      return catalog.structuredJsonModel;
    }
    return null;
  }
  if (isStructuredGroqWorkload(workload)) {
    // Document/other strict JSON workloads retain their isolated
    // compatibility lane until their provider contract is migrated.
    return null;
  }
  const preferredOrder =
    workload === "public_deep_research"
      ? [catalog.reasoningModel, catalog.fastModel, catalog.fallbackModel]
      : chatWorkload || visionWorkload
        ? [catalog.fastModel, catalog.reasoningModel, catalog.fallbackModel]
        : [catalog.fallbackModel, catalog.reasoningModel, catalog.fastModel];
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
