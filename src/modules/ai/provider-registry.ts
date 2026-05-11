export const supportedAiProviders = [
  {
    code: "openai",
    role: "reasoning_planning",
    hosted: true,
  },
  {
    code: "claude",
    role: "reasoning_planning",
    hosted: true,
  },
  {
    code: "ollama",
    role: "reasoning_planning",
    hosted: false,
  },
  {
    code: "groq",
    role: "reasoning_planning",
    hosted: true,
  },
] as const;
