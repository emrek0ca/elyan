export const sharedBrainWorkloadValues = [
  "intent",
  "fast_route",
  "mobile_chat_fast",
  "mobile_chat_balanced",
  "document_analysis",
  "planning",
  "desktop_handoff",
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
  document_analysis: {
    workload: "document_analysis",
    timeoutMs: 8_500,
    firstDeltaBudgetMs: 2_200,
    maxTokens: 640,
    streamingEnabled: true,
    cachePolicy: "off",
    fallbackWorkload: "mobile_chat_balanced",
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
}): SharedBrainWorkload {
  const selectedWorkload = input.selectedWorkload ?? "mobile_chat_fast";
  if (selectedWorkload === "planning" || selectedWorkload === "desktop_handoff") {
    return selectedWorkload;
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
