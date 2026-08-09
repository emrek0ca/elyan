import type { SharedBrainProvider } from "./runtime.js";
import type { SharedBrainWorkload } from "./workloads.js";

export type ProviderModelCapabilities = {
  provider: SharedBrainProvider;
  model: string;
  nativeStreaming: boolean;
  vision: boolean;
  structuredOutput: boolean;
  toolCalling: boolean;
  reasoning: boolean;
  imageGeneration: boolean;
  maxImages: number;
  qualityTier: "fast" | "balanced" | "frontier";
  latencyTier: "ultra_fast" | "fast" | "balanced" | "deep";
};

function normalized(value: unknown): string {
  return String(value ?? "").trim().toLowerCase();
}

function isGeminiImageModel(model: string): boolean {
  return /gemini-3(?:\.1)?-(?:flash(?:-lite)?|pro)-image(?:-preview)?/u.test(
    model,
  );
}

function isGeminiModel(model: string): boolean {
  return model.startsWith("gemini-");
}

function isGroqVisionModel(model: string): boolean {
  return (
    model.includes("qwen/qwen3.6-27b") ||
    model.includes("qwen3.6-27b") ||
    model.includes("vision") ||
    model.includes("llama-4-scout") ||
    model.includes("llama-4-maverick") ||
    model.includes("pixtral")
  );
}

export function resolveProviderModelCapabilities(
  provider: SharedBrainProvider,
  model: string,
): ProviderModelCapabilities {
  const name = normalized(model);

  if (provider === "gemini" && isGeminiImageModel(name)) {
    const premium = name.includes("pro-image");
    return {
      provider,
      model,
      nativeStreaming: true,
      vision: true,
      structuredOutput: false,
      toolCalling: true,
      reasoning: premium,
      imageGeneration: true,
      maxImages: premium ? 6 : 10,
      qualityTier: premium ? "frontier" : "balanced",
      latencyTier: premium ? "deep" : "fast",
    };
  }

  if (provider === "gemini" && isGeminiModel(name)) {
    const lite = name.includes("flash-lite");
    const pro = name.includes("pro");
    return {
      provider,
      model,
      nativeStreaming: true,
      vision: true,
      structuredOutput: true,
      toolCalling: true,
      reasoning: !lite || pro,
      imageGeneration: false,
      maxImages: 20,
      qualityTier: pro ? "frontier" : lite ? "fast" : "balanced",
      latencyTier: lite ? "ultra_fast" : pro ? "deep" : "fast",
    };
  }

  if (provider === "groq" && isGroqVisionModel(name)) {
    return {
      provider,
      model,
      nativeStreaming: true,
      vision: true,
      structuredOutput: false,
      toolCalling: true,
      reasoning: true,
      imageGeneration: false,
      maxImages: 5,
      qualityTier: "balanced",
      latencyTier: "fast",
    };
  }

  if (provider === "groq" && name.includes("gpt-oss")) {
    return {
      provider,
      model,
      nativeStreaming: true,
      vision: false,
      structuredOutput: true,
      toolCalling: true,
      reasoning: true,
      imageGeneration: false,
      maxImages: 0,
      qualityTier: name.includes("120b") ? "frontier" : "balanced",
      latencyTier: name.includes("120b") ? "deep" : "fast",
    };
  }

  if (provider === "groq" && name.startsWith("groq/compound")) {
    return {
      provider,
      model,
      nativeStreaming: true,
      vision: false,
      structuredOutput: false,
      toolCalling: true,
      reasoning: true,
      imageGeneration: false,
      maxImages: 0,
      qualityTier: "frontier",
      latencyTier: name.includes("mini") ? "fast" : "deep",
    };
  }

  const local = provider === "ollama" || provider === "vllm" || provider === "llamacpp";
  return {
    provider,
    model,
    nativeStreaming:
      provider === "groq" ||
      provider === "openai" ||
      provider === "openrouter" ||
      local,
    vision: false,
    structuredOutput: provider !== "claude",
    toolCalling: provider !== "claude",
    reasoning: true,
    imageGeneration: false,
    maxImages: 0,
    qualityTier: local ? "balanced" : "frontier",
    latencyTier: local ? "balanced" : "fast",
  };
}

export function capabilityScoreForWorkload(
  capabilities: ProviderModelCapabilities,
  workload: SharedBrainWorkload,
  input: {
    vision?: boolean;
    structured?: boolean;
    profile?: "fast" | "balanced" | "detail";
  } = {},
): number {
  let score = 0;
  const fastWorkload =
    workload === "intent" ||
    workload === "fast_route" ||
    workload === "mobile_chat_fast" ||
    workload === "desktop_handoff";
  const deepWorkload =
    workload === "planning" ||
    workload === "public_deep_research" ||
    workload === "public_quantum_research" ||
    workload === "mobile_chat_deep_refine";

  if (input.vision) {
    score += capabilities.vision ? 50 : -100;
    if (input.profile === "fast") {
      score += capabilities.latencyTier === "ultra_fast" ? 18 : capabilities.latencyTier === "fast" ? 10 : 0;
    } else if (input.profile === "detail") {
      score += capabilities.qualityTier === "frontier" ? 18 : capabilities.qualityTier === "balanced" ? 8 : 0;
    }
  }
  if (input.structured) score += capabilities.structuredOutput ? 24 : -60;
  if (deepWorkload) score += capabilities.reasoning ? 18 : -20;
  if (fastWorkload) {
    score += capabilities.latencyTier === "ultra_fast" ? 22 : capabilities.latencyTier === "fast" ? 12 : -4;
  }
  if (capabilities.nativeStreaming) score += 8;
  return score;
}
