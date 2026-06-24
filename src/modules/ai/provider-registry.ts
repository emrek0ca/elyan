import type { SharedBrainWorkload } from "../brain/workloads.js";

export type SupportedAiProvider = {
  code: "groq";
  displayName: string;
  hosted: boolean;
  workloads: SharedBrainWorkload[];
  models: string[];
  defaultModelByWorkload: Record<SharedBrainWorkload, string>;
  timeoutMsByWorkload: Record<SharedBrainWorkload, number>;
};

export const supportedAiProviders: SupportedAiProvider[] = [
  {
    code: "groq",
    displayName: "Groq",
    hosted: true,
    workloads: [
      "intent",
      "planning",
      "fast_route",
      "mobile_chat_fast",
      "mobile_chat_balanced",
      "document_analysis",
      "desktop_handoff",
    ],
    models: [
      "openai/gpt-oss-120b",
      "openai/gpt-oss-20b",
      "qwen/qwen3.6-27b",
    ],
    defaultModelByWorkload: {
      intent: "openai/gpt-oss-20b",
      planning: "openai/gpt-oss-120b",
      fast_route: "openai/gpt-oss-20b",
      mobile_chat_fast: "openai/gpt-oss-20b",
      mobile_chat_balanced: "openai/gpt-oss-120b",
      document_analysis: "qwen/qwen3.6-27b",
      desktop_handoff: "openai/gpt-oss-20b",
    },
    timeoutMsByWorkload: {
      intent: 10_000,
      planning: 20_000,
      fast_route: 6_000,
      mobile_chat_fast: 5_500,
      mobile_chat_balanced: 6_500,
      document_analysis: 8_500,
      desktop_handoff: 0,
    },
  },
] as const;
