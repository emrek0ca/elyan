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

/**
 * These workloads are transported as machine JSON. They must never inherit a
 * reasoning-channel fallback: Groq can return an empty/invalid body when a
 * reasoning model is combined with a JSON response contract.
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
  // KATI-JSON ŞERİDİ — gpt-only politikasının BİLİNÇLİ İSTİSNASI.
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
  // `reasoning_effort: "low"` panzehir DEĞİL: ikinci ölçümde efor zaten
  // düşüktü ve yine 400 geldi. Bu yüzden şerit reasoning-DIŞI bir modele
  // sabitlenir; `gptOnlyModel` filtresinden bilerek geçirilmez.
  //
  // Kapsam dar: sohbet, akıl yürütme, planlama ve belge ÜRETİMİ tamamen gpt
  // kalır. Burada değişen yalnız "şemaya uyan JSON döndür" çağrıları.
  const structuredJsonModel =
    compactText(config.GROQ_ROUTING_MODEL) || "llama-3.1-8b-instant";
  const routingModel = structuredJsonModel;
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
      // Normal sohbetin iki mobil workload'u da hızlı modelde kalır. Zor
      // görevler `mobile_chat_deep_refine`/planning ile açıkça reasoning
      // kanalına yükseltilir; böylece her orta uzunlukta sohbet gizli 120B
      // düşünme turunu ödemez.
      mobile_chat_fast: fastModel,
      mobile_chat_balanced: fastModel,
      mobile_chat_deep_refine: reasoningModel,
      // KATI-JSON ŞERİDİ. Belge analizi şemaya uyan JSON döndürüyor; canlıda
      // (2026-08-13, görev a4924a76) bu iş yükünde önce gpt-oss-20b sonra
      // qwen 400 `json_validate_failed` verdi ve PDF isteği hiç üretilemedi.
      document_analysis: structuredJsonModel,
      document_generate: reasoningModel,
      table_generate: reasoningModel,
      image_analyze: visionModel,
      // KATI-JSON ŞERİDİ. Masaüstü plan materyalizasyonu ve eleştirisi
      // `response_format: json_schema` kullanıyor. Canlı 2026-08-14 görsel
      // poster görevinde planning → gpt-oss adayları Groq'ta 400
      // `json_validate_failed` verdi; Gemini adayı da veri paylaşımı izni
      // olmadan policy tarafından bloklandı. Mevcut reasoning/Gemini/Compound
      // modelleri korunur; yalnız bu şemalı iş yükü güvenilir JSON şeridine
      // alınır.
      planning: structuredJsonModel,
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
  if (isStructuredGroqWorkload(workload)) {
    // Structured JSON is a separate compatibility lane. Do not return the
    // generic gpt/qwen fallbacks here: the caller may use this value to build
    // a provider candidate list and would otherwise repeat a known-invalid
    // response_format + reasoning combination.
    return null;
  }
  const preferredOrder =
    workload === "public_deep_research"
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
