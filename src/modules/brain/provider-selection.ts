import type { FastifyInstance } from "fastify";
import { buildGeminiModelCatalog, resolveGeminiFallbackModel } from "./gemini-models.js";
import { buildGroqModelCatalog, resolveGroqFallbackModel } from "./groq-models.js";
import {
  listSharedBrainProviderCandidates,
  type SharedBrainProvider,
  type SharedBrainRuntimeSnapshot,
} from "./runtime.js";
import type { SharedBrainWorkload } from "./workloads.js";
import type { VisionMediaProfile } from "./vision-media-policy.js";
import type { VisionMediaDecision } from "./vision-media-policy.js";
import { isGeminiFreeModelAllowed } from "./gemini-free-tier-guard.js";

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

export function isHostedVisionProviderPrivacyEligible(
  provider: "groq" | "gemini",
  sensitivity: VisionMediaDecision["sensitivity"] | undefined,
  attestations: { groq?: boolean; gemini?: boolean },
): boolean {
  if (sensitivity === "restricted") return false;
  if (sensitivity !== "sensitive") return true;
  return provider === "groq" ? attestations.groq === true : attestations.gemini === true;
}

function isPrivateRuntimeBaseUrl(baseUrl: string): boolean {
  try {
    const hostname = new URL(baseUrl).hostname.toLowerCase();
    if (hostname === "localhost" || hostname === "::1" || hostname === "[::1]") return true;
    if (/^127\./.test(hostname) || /^10\./.test(hostname) || /^192\.168\./.test(hostname)) return true;
    const match = hostname.match(/^172\.(\d{1,3})\./);
    return Boolean(match && Number(match[1]) >= 16 && Number(match[1]) <= 31);
  } catch {
    return false;
  }
}

function buildHostedProviderCandidates(
  app: FastifyInstance,
  workload: SharedBrainWorkload,
  visionProfile?: VisionMediaProfile,
  visionSensitivity?: VisionMediaDecision["sensitivity"],
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
  const geminiPrimaryModel =
    isVisionWorkload(workload) &&
    (visionProfile === "fast" || visionProfile === "balanced")
      ? geminiCatalog.fastModel
      : workload === "document_analysis"
        ? geminiCatalog.fastModel
      : geminiCatalog.defaultModelByWorkload[workload];
  const geminiFallbackModel =
    workload === "document_analysis" && geminiPrimaryModel === geminiCatalog.fastModel
      ? geminiCatalog.textModel
      : isVisionWorkload(workload) && geminiPrimaryModel === geminiCatalog.fastModel
        ? geminiCatalog.visionModel
        : resolveGeminiFallbackModel(app.config, geminiPrimaryModel) ??
          geminiCatalog.fastModel;
  if (geminiApiKey && geminiBaseUrl && geminiPrimaryModel) {
    const preferredModels = [geminiPrimaryModel, geminiFallbackModel].filter(
      (model, index, values): model is string =>
        Boolean(model) &&
        values.indexOf(model) === index &&
        (app.config.GEMINI_FREE_ONLY !== true ||
          isGeminiFreeModelAllowed(app, model)),
    );
    if (preferredModels.length > 0) {
      hostedCandidates.push({
        provider: "gemini",
        baseUrl: geminiBaseUrl,
        preferredModels,
        hosted: true,
      });
    }
  }

  if (!isVisionWorkload(workload) && workload !== "document_analysis") {
    return hostedCandidates;
  }

  const privacyEligibleCandidates = visionSensitivity === "restricted"
    ? []
    : visionSensitivity === "sensitive"
      ? hostedCandidates.filter((candidate) =>
          (candidate.provider === "groq" || candidate.provider === "gemini") &&
          isHostedVisionProviderPrivacyEligible(
            candidate.provider,
            visionSensitivity,
            {
              groq: app.config.GROQ_VISION_SENSITIVE_DATA_ATTESTED,
              gemini: app.config.GEMINI_VISION_SENSITIVE_DATA_ATTESTED,
            },
          ),
        )
      : hostedCandidates;

  // Gemini is the canonical multimodal adapter. The low-cost Flash-Lite model
  // handles fast/balanced requests; Groq remains a bounded provider fallback.
  const preferredProvider = "gemini";
  if (
    app.config.GEMINI_FREE_ONLY === true &&
    privacyEligibleCandidates.some(
      (candidate) => candidate.provider === preferredProvider,
    )
  ) {
    return privacyEligibleCandidates.filter(
      (candidate) => candidate.provider === preferredProvider,
    );
  }
  return [
    ...privacyEligibleCandidates.filter((candidate) => candidate.provider === preferredProvider),
    ...privacyEligibleCandidates.filter((candidate) => candidate.provider !== preferredProvider),
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

function filterAllowedProviders(
  candidates: SharedBrainProviderCandidate[],
  allowedProviders?: readonly SharedBrainProvider[],
): SharedBrainProviderCandidate[] {
  if (!allowedProviders?.length) {
    return candidates;
  }
  const allowed = new Set(allowedProviders);
  return candidates.filter((candidate) => allowed.has(candidate.provider));
}

export function buildInferenceProviderCandidates(input: {
  app: FastifyInstance;
  workload: SharedBrainWorkload;
  runtime: SharedBrainRuntimeSnapshot;
  localModels: string[];
  visionProfile?: VisionMediaProfile;
  visionSensitivity?: VisionMediaDecision["sensitivity"];
  allowedProviders?: readonly SharedBrainProvider[];
}) {
  const localCandidates = listSharedBrainProviderCandidates(input.app).map(
    (candidate) => ({
      provider: candidate.provider,
      baseUrl: candidate.baseUrl,
      preferredModels: input.localModels,
      hosted: false,
    }),
  ) satisfies SharedBrainProviderCandidate[];
  const privacySafeLocalCandidates =
    input.visionSensitivity && input.visionSensitivity !== "none"
      ? localCandidates.filter((candidate) => isPrivateRuntimeBaseUrl(candidate.baseUrl))
      : localCandidates;
  const hostedCandidates = buildHostedProviderCandidates(
    input.app,
    input.workload,
    input.visionProfile,
    input.visionSensitivity,
  );
  const preferredLocalCandidate = input.runtime.ready
    ? {
        provider: input.runtime.provider,
        baseUrl: input.runtime.baseUrl,
        preferredModels: input.localModels,
        hosted: false,
      }
    : null;
  const privacySafePreferredLocalCandidate = preferredLocalCandidate &&
    (!input.visionSensitivity || input.visionSensitivity === "none" ||
      isPrivateRuntimeBaseUrl(preferredLocalCandidate.baseUrl))
    ? preferredLocalCandidate
    : null;

  if (!hostedCandidates.length) {
    return filterAllowedProviders(
      buildCandidateOrder(privacySafeLocalCandidates, privacySafePreferredLocalCandidate),
      input.allowedProviders,
    );
  }

  return filterAllowedProviders(
    buildCandidateOrder(
      [...hostedCandidates, ...privacySafeLocalCandidates],
      hostedCandidates[0],
    ),
    input.allowedProviders,
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
