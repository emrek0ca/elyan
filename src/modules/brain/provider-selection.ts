import type { FastifyInstance } from "fastify";
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
  provider: "groq",
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
    default:
      return "";
  }
}

function getConfiguredProviderBaseUrl(
  app: FastifyInstance,
  provider: "groq",
): string | null {
  const normalize = (value: unknown) => {
    const trimmed = typeof value === "string" ? value.trim() : "";
    return trimmed || null;
  };
  switch (provider) {
    case "groq":
      return normalize(app.config.GROQ_BASE_URL);
    default:
      return null;
  }
}

function buildHostedProviderCandidates(
  app: FastifyInstance,
  workload: SharedBrainWorkload,
): SharedBrainProviderCandidate[] {
  const providerCode = "groq" as const;
  const apiKey = getConfiguredProviderApiKey(app, providerCode);
  const baseUrl = getConfiguredProviderBaseUrl(app, providerCode);
  const catalog = buildGroqModelCatalog(app.config);
  const primaryModel = catalog.defaultModelByWorkload[workload];
  const fallbackModel =
    resolveGroqFallbackModel(app.config, primaryModel) ?? catalog.fallbackModel;
  if (!apiKey || !baseUrl || !primaryModel) {
    return [];
  }

  return [
    {
      provider: providerCode,
      baseUrl,
      preferredModels: [primaryModel, fallbackModel].filter(
        (model, index, values): model is string =>
          Boolean(model) && values.indexOf(model) === index,
      ),
      hosted: true,
    },
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

  if (provider !== "groq") {
    return headers;
  }

  const apiKey = getConfiguredProviderApiKey(app, "groq");
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }

  return headers;
}
