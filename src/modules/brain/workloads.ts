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
    timeoutMs: 5_500,
    firstDeltaBudgetMs: 1_800,
    maxTokens: 224,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "mobile_chat_balanced",
  },
  mobile_chat_balanced: {
    workload: "mobile_chat_balanced",
    timeoutMs: 7_000,
    firstDeltaBudgetMs: 2_100,
    maxTokens: 384,
    streamingEnabled: true,
    cachePolicy: "safe_ephemeral",
    fallbackWorkload: "mobile_chat_fast",
  },
  mobile_chat_deep_refine: {
    workload: "mobile_chat_deep_refine",
    timeoutMs: 9_500,
    firstDeltaBudgetMs: 2_400,
    maxTokens: 640,
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
    timeoutMs: 9_000,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 560,
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
