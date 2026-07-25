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
    maxTokens: 140,
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
    timeoutMs: 14_000,
    firstDeltaBudgetMs: 2_800,
    maxTokens: 1_600,
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
    maxTokens: 2_400,
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
