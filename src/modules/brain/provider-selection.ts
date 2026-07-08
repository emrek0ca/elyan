import type { FastifyInstance } from "fastify";
import { buildGeminiModelCatalog, resolveGeminiFallbackModel } from "./gemini-models.js";
import { buildGroqModelCatalog, resolveGroqFallbackModel } from "./groq-models.js";
import {
  listSharedBrainProviderCandidates,
  type SharedBrainProvider,
  type SharedBrainRuntimeSnapshot,
} from "./runtime.js";
import type { SharedBrainWorkload } from "./workloads.js";

export type SharedBrainProviderCandidate = {
  provider: SharedBrainProvider;
  baseUrl: string;
  preferredModels: string[];
  hosted: boolean;
};

export function getConfiguredProviderApiKey(
  app: FastifyInstance,
  provider: "groq" | "gemini",
): string {
  const normalize = (value: unknown) => {
    if (typeof value !== "string") {
      return "";
    }
    const first = value
      .split(",")
      .map((entry) => entry.trim())
      .find((entry) => entry.length > 0);
    return first ?? "";
  };
  switch (provider) {
    case "groq":
      return normalize(app.config.GROQ_API_KEY);
    case "gemini":
      return normalize(app.config.GEMINI_API_KEY);
    default:
      return "";
  }
}

function getConfiguredProviderBaseUrl(
  app: FastifyInstance,
  provider: "groq" | "gemini",
): string | null {
  const normalize = (value: unknown) => {
    const trimmed = typeof value === "string" ? value.trim() : "";
    return trimmed || null;
  };
  switch (provider) {
    case "groq":
      return normalize(app.config.GROQ_BASE_URL);
    case "gemini":
      return normalize(app.config.GEMINI_BASE_URL);
    default:
      return null;
  }
}

function isVisionWorkload(workload: SharedBrainWorkload): boolean {
  return workload === "vision_reasoning" || workload === "image_analyze";
}

function buildHostedProviderCandidates(
  app: FastifyInstance,
  workload: SharedBrainWorkload,
): SharedBrainProviderCandidate[] {
  const hostedCandidates: SharedBrainProviderCandidate[] = [];

  const groqApiKey = getConfiguredProviderApiKey(app, "groq");
  const groqBaseUrl = getConfiguredProviderBaseUrl(app, "groq");
  const groqCatalog = buildGroqModelCatalog(app.config);
  const groqPrimaryModel = groqCatalog.defaultModelByWorkload[workload];
  const groqFallbackModel =
    resolveGroqFallbackModel(app.config, groqPrimaryModel, workload) ??
    groqCatalog.fallbackModel;
  if (groqApiKey && groqBaseUrl && groqPrimaryModel) {
    hostedCandidates.push({
      provider: "groq",
      baseUrl: groqBaseUrl,
      preferredModels: [groqPrimaryModel, groqFallbackModel].filter(
        (model, index, values): model is string =>
          Boolean(model) && values.indexOf(model) === index,
      ),
      hosted: true,
    });
  }

  const geminiApiKey = getConfiguredProviderApiKey(app, "gemini");
  const geminiBaseUrl = getConfiguredProviderBaseUrl(app, "gemini");
  const geminiCatalog = buildGeminiModelCatalog(app.config);
  const geminiPrimaryModel = geminiCatalog.defaultModelByWorkload[workload];
  const geminiFallbackModel =
    resolveGeminiFallbackModel(app.config, geminiPrimaryModel) ??
    geminiCatalog.fastModel;
  if (geminiApiKey && geminiBaseUrl && geminiPrimaryModel) {
    hostedCandidates.push({
      provider: "gemini",
      baseUrl: geminiBaseUrl,
      preferredModels: [geminiPrimaryModel, geminiFallbackModel].filter(
        (model, index, values): model is string =>
          Boolean(model) && values.indexOf(model) === index,
      ),
      hosted: true,
    });
  }

  if (!isVisionWorkload(workload)) {
    return hostedCandidates;
  }

  return [
    ...hostedCandidates.filter((candidate) => candidate.provider === "gemini"),
    ...hostedCandidates.filter((candidate) => candidate.provider !== "gemini"),
  ];
}

function buildCandidateOrder(
  candidates: SharedBrainProviderCandidate[],
  preferred?: SharedBrainProviderCandidate | null,
) {
  const ordered = preferred ? [preferred, ...candidates] : [...candidates];
  const unique = new Map<string, SharedBrainProviderCandidate>();

  for (const candidate of ordered) {
    const key = `${candidate.provider}:${candidate.baseUrl}`;
    if (!unique.has(key)) {
      unique.set(key, candidate);
    }
  }

  return [...unique.values()];
}

export function buildInferenceProviderCandidates(input: {
  app: FastifyInstance;
  workload: SharedBrainWorkload;
  runtime: SharedBrainRuntimeSnapshot;
  localModels: string[];
}) {
  const localCandidates = listSharedBrainProviderCandidates(input.app).map(
    (candidate) => ({
      provider: candidate.provider,
      baseUrl: candidate.baseUrl,
      preferredModels: input.localModels,
      hosted: false,
    }),
  ) satisfies SharedBrainProviderCandidate[];
  const hostedCandidates = buildHostedProviderCandidates(
    input.app,
    input.workload,
  );
  const preferredLocalCandidate = input.runtime.ready
    ? {
        provider: input.runtime.provider,
        baseUrl: input.runtime.baseUrl,
        preferredModels: input.localModels,
        hosted: false,
      }
    : null;

  if (!hostedCandidates.length) {
    return buildCandidateOrder(localCandidates, preferredLocalCandidate);
  }

  return buildCandidateOrder(
    [...hostedCandidates, ...localCandidates],
    hostedCandidates[0],
  );
}

export function buildProviderHeaders(
  app: FastifyInstance,
  provider: SharedBrainProvider,
): Record<string, string> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  if (provider !== "groq" && provider !== "gemini") {
    return headers;
  }

  const apiKey = getConfiguredProviderApiKey(app, provider);
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }

  return headers;
}
