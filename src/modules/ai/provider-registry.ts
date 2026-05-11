export type SupportedAiProvider = {
  code: "openai" | "claude" | "ollama" | "groq" | "openrouter";
  displayName: string;
  hosted: boolean;
  workloads: Array<"intent" | "planning" | "fast_route">;
  models: string[];
  defaultModelByWorkload: Record<"intent" | "planning" | "fast_route", string>;
  timeoutMsByWorkload: Record<"intent" | "planning" | "fast_route", number>;
};

export const supportedAiProviders: SupportedAiProvider[] = [
  {
    code: "openai",
    displayName: "OpenAI",
    hosted: true,
    workloads: ["intent", "planning", "fast_route"],
    models: ["gpt-4.1", "gpt-4o-mini"],
    defaultModelByWorkload: {
      intent: "gpt-4o-mini",
      planning: "gpt-4.1",
      fast_route: "gpt-4o-mini",
    },
    timeoutMsByWorkload: {
      intent: 12_000,
      planning: 25_000,
      fast_route: 8_000,
    },
  },
  {
    code: "claude",
    displayName: "Claude",
    hosted: true,
    workloads: ["intent", "planning"],
    models: ["claude-3-7-sonnet-latest", "claude-3-5-haiku-latest"],
    defaultModelByWorkload: {
      intent: "claude-3-5-haiku-latest",
      planning: "claude-3-7-sonnet-latest",
      fast_route: "claude-3-5-haiku-latest",
    },
    timeoutMsByWorkload: {
      intent: 12_000,
      planning: 25_000,
      fast_route: 8_000,
    },
  },
  {
    code: "ollama",
    displayName: "Ollama",
    hosted: false,
    workloads: ["intent", "planning"],
    models: ["llama3.1:8b", "qwen2.5:7b"],
    defaultModelByWorkload: {
      intent: "llama3.1:8b",
      planning: "qwen2.5:7b",
      fast_route: "llama3.1:8b",
    },
    timeoutMsByWorkload: {
      intent: 18_000,
      planning: 30_000,
      fast_route: 10_000,
    },
  },
  {
    code: "groq",
    displayName: "Groq",
    hosted: true,
    workloads: ["intent", "fast_route"],
    models: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    defaultModelByWorkload: {
      intent: "llama-3.3-70b-versatile",
      planning: "llama-3.3-70b-versatile",
      fast_route: "llama-3.1-8b-instant",
    },
    timeoutMsByWorkload: {
      intent: 10_000,
      planning: 20_000,
      fast_route: 6_000,
    },
  },
  {
    code: "openrouter",
    displayName: "OpenRouter",
    hosted: true,
    workloads: ["intent", "planning", "fast_route"],
    models: ["openai/gpt-4.1-mini", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.3-70b-instruct"],
    defaultModelByWorkload: {
      intent: "openai/gpt-4.1-mini",
      planning: "anthropic/claude-3.5-sonnet",
      fast_route: "meta-llama/llama-3.3-70b-instruct",
    },
    timeoutMsByWorkload: {
      intent: 12_000,
      planning: 25_000,
      fast_route: 8_000,
    },
  },
] as const;
