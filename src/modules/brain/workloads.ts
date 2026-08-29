export const sharedBrainWorkloadValues = [
  "intent",
  "fast_route",
  "mobile_chat_fast",
  "mobile_chat_balanced",
  "mobile_chat_deep_refine",
  "document_analysis",
  "document_generate",
  "table_generate",
  "image_analyze",
  "planning",
  "public_research",
  "public_deep_research",
  "public_quantum_research",
  "desktop_handoff",
  "vision_reasoning",
] as const;

export type SharedBrainWorkload = (typeof sharedBrainWorkloadValues)[number];

export type WorkloadProfile = {
  workload: SharedBrainWorkload;
  timeoutMs: number;
  firstDeltaBudgetMs: number | null;
  maxTokens: number;
  streamingEnabled: boolean;
  cachePolicy: "off" | "safe_ephemeral";
  fallbackWorkload: SharedBrainWorkload | null;
};

export const SHARED_BRAIN_WORKLOAD_PROFILES: Record<
  SharedBrainWorkload,
  WorkloadProfile
> = {
  intent: {
    workload: "intent",
    timeoutMs: 5_500,
    firstDeltaBudgetMs: 1_800,
    maxTokens: 96,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "mobile_chat_fast",
  },
  fast_route: {
    workload: "fast_route",
    timeoutMs: 5_500,
    firstDeltaBudgetMs: 1_800,
    // 140 → 700. Bu iş yükü semantik YÖNLENDİRİCİYİ koşturur ve ondan iç içe
    // `semanticDesktopContract` alanı olan bir JSON nesnesi ister. 140 token o
    // şemayı yazmaya YETMİYORDU: ölçüm (2026-08-08, llama-3.1-8b-instant,
    // gerçek router prompt'u) → max_tokens=140 `finish_reason=length` ile
    // JSON'u ortasında kesiyor, çıktı geçersiz oluyor ve tur "yanıt
    // oluşturamadım" fallback'ine düşüyordu; max_tokens=700 ile aynı model
    // `finish_reason=stop` ve GEÇERLİ JSON döndürüp doğru cevabı
    // ("desktop_runtime") veriyor.
    //
    // Yani yönlendirici yanlış karar vermiyordu — kararını YAZMAYI
    // bitiremiyordu. Bu tek sayı yüzünden hiçbir görev masaüstüne
    // yönlenmiyordu. max_tokens bir TAVANdır: kısa çıktı stop token'da erken
    // biter, fatura gerçek kullanımadır — tavanı yükseltmek maliyeti artırmaz.
    maxTokens: 700,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "mobile_chat_fast",
  },
  mobile_chat_fast: {
    workload: "mobile_chat_fast",
    timeoutMs: 7_000,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 384,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "mobile_chat_balanced",
  },
  mobile_chat_balanced: {
    workload: "mobile_chat_balanced",
    // timeoutMs artık STALL süresi (postStreamingJson): aktif akan stream'i
    // kesmez, sadece 7sn sessizlikte takılı stream'i düşürür. Bu yüzden token
    // tavanını yükseltmek timeout riski taşımıyor.
    timeoutMs: 7_000,
    firstDeltaBudgetMs: 2_100,
    // 512 → 768: uzun cevaplar timeout yerine length'e takılıp continuation
    // turu tüketiyordu; base tavanı yükselince tek turda tamamlanıyor.
    maxTokens: 768,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "mobile_chat_fast",
  },
  mobile_chat_deep_refine: {
    workload: "mobile_chat_deep_refine",
    timeoutMs: 12_000,
    firstDeltaBudgetMs: 3_000,
    maxTokens: 1024,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "mobile_chat_balanced",
  },
  document_analysis: {
    workload: "document_analysis",
    timeoutMs: 8_500,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 640,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "mobile_chat_balanced",
  },
  /* AI generates a structured multi-section document */
  document_generate: {
    workload: "document_generate",
    // 30 sn + 4096 token: `planning` ile AYNI ARIZA, orada çözülmüş burada
    // kalmıştı. Bu iş yükü `reasoning_effort: "high"` ile koşuyor
    // (generation-policy.ts) ve gpt-oss'ta gizli düşünme turu max_tokens'a
    // SAYILIR. 1.600 token, çok bölümlü bir belgenin JSON gövdesine tek
    // başına yetmezken düşünme turuyla PAYLAŞILIYORDU.
    //
    // CANLI ÖLÇÜM (2026-08-30 02:03, görev d3d62fa8): "Bunu bana pdf olarak
    // verir misin" turunda 13 sağlayıcı denemesinin TAMAMI düştü. İki belirti,
    // tek kök:
    //   json_validate_failed (400) → JSON yarıda kesildi, Groq reddetti
    //   empty_stream_response (503) → düşünme bütçeyi bitirdi, görünür token yok
    // Zincir tükenince `server_brain_unavailable` ve kullanıcı "Şu anda
    // düşünme servisine ulaşamıyorum" gördü.
    //
    // Belge bir plandan büyüktür; taban `planning` ile aynı yerde. max_tokens
    // bir TAVANdır: kısa belge erken durur, fatura gerçek kullanıma.
    // İlk delta bütçesi de büyüdü — gizli düşünme ilk GÖRÜNÜR token'ı geciktirir.
    timeoutMs: 30_000,
    firstDeltaBudgetMs: 4_500,
    maxTokens: 4_096,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "document_analysis",
  },
  /* AI generates or edits a structured table from natural language */
  table_generate: {
    workload: "table_generate",
    timeoutMs: 9_000,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 800,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "mobile_chat_balanced",
  },
  /* Thumbnail + OCR text analysis — no raw file, vision model optional */
  image_analyze: {
    workload: "image_analyze",
    timeoutMs: 12_000,
    firstDeltaBudgetMs: 3_000,
    maxTokens: 640,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "document_analysis",
  },
  planning: {
    workload: "planning",
    // 30 sn + 2400 token: planlama reasoning modeliyle (gpt-oss) çalışır ve
    // gizli düşünme turu max_tokens'a SAYILIR. Önceki 560 token tabanında model
    // düşünmede tükenip görünür JSON'u hiç üretemiyordu → Groq her çağrıda
    // json_validate_failed(boş) → /desktop/plan HİÇ başarılı olamıyordu.
    // Ayrıca desktop-plan'ın 2400 override'ı Math.min ile bu tabana EZİLİR —
    // override tabanı yükseltemez, o yüzden taban burada doğru olmak zorunda.
    // max_tokens bir TAVANdır: kısa plan erken durur, fatura gerçek kullanıma.
    timeoutMs: 30_000,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 4_096,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "mobile_chat_balanced",
  },
  public_research: {
    workload: "public_research",
    timeoutMs: 9_000,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 768,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "mobile_chat_balanced",
  },
  public_deep_research: {
    workload: "public_deep_research",
    timeoutMs: 14_000,
    firstDeltaBudgetMs: 3_000,
    maxTokens: 1_200,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "public_research",
  },
  public_quantum_research: {
    workload: "public_quantum_research",
    timeoutMs: 12_000,
    firstDeltaBudgetMs: 2_800,
    maxTokens: 1_024,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "mobile_chat_balanced",
  },
  desktop_handoff: {
    workload: "desktop_handoff",
    timeoutMs: 0,
    firstDeltaBudgetMs: null,
    maxTokens: 0,
    streamingEnabled: false,
    cachePolicy: "off",
    fallbackWorkload: null,
  },
  vision_reasoning: {
    workload: "vision_reasoning",
    timeoutMs: 12_000,
    firstDeltaBudgetMs: 3_500,
    maxTokens: 768,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "mobile_chat_balanced",
  },
};

export function getSharedBrainWorkloadProfile(
  workload: SharedBrainWorkload | undefined | null,
): WorkloadProfile {
  return SHARED_BRAIN_WORKLOAD_PROFILES[workload ?? "mobile_chat_fast"];
}

export function getSharedBrainFallbackWorkload(
  workload: SharedBrainWorkload | undefined | null,
): SharedBrainWorkload | null {
  return getSharedBrainWorkloadProfile(workload).fallbackWorkload;
}

export function resolveAttachmentAwareSharedBrainWorkload(input: {
  route?: string | null;
  selectedWorkload?: SharedBrainWorkload | null;
  attachmentContextUsed?: boolean;
  hasVisionImage?: boolean;
}): SharedBrainWorkload {
  const selectedWorkload = input.selectedWorkload ?? "mobile_chat_fast";
  if (
    selectedWorkload === "planning" ||
    selectedWorkload === "desktop_handoff" ||
    selectedWorkload === "document_generate" ||
    selectedWorkload === "table_generate" ||
    selectedWorkload === "image_analyze"
    || selectedWorkload === "public_research"
    || selectedWorkload === "public_deep_research"
    || selectedWorkload === "public_quantum_research"
  ) {
    return selectedWorkload;
  }
  if (input.hasVisionImage === true) {
    return "vision_reasoning";
  }
  if (selectedWorkload === "document_analysis") {
    return "document_analysis";
  }
  if (
    input.route === "server_brain" &&
    input.attachmentContextUsed === true &&
    (selectedWorkload === "mobile_chat_fast" || selectedWorkload === "mobile_chat_balanced")
  ) {
    return "document_analysis";
  }
  return selectedWorkload;
}
