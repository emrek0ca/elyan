import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { and, desc, eq } from "drizzle-orm";
import { aiProviderInvocations } from "../../db/schema.js";
import { buildGeminiModelCatalog, resolveGeminiFallbackModel } from "./gemini-models.js";
import {
  buildGroqModelCatalog,
  isStructuredGroqWorkload,
  resolveGroqFallbackModel,
} from "./groq-models.js";
import { resolveGroqCompoundModel, shouldUseGroqCompound } from "./groq-compound.js";
import {
  listSharedBrainProviderCandidates,
  type SharedBrainProvider,
  type SharedBrainRuntimeSnapshot,
} from "./runtime.js";
import type { SharedBrainWorkload } from "./workloads.js";
import type { VisionMediaProfile } from "./vision-media-policy.js";
import type { VisionMediaDecision } from "./vision-media-policy.js";
import { isGeminiFreeModelAllowed } from "./gemini-free-tier-guard.js";
import {
  capabilityScoreForWorkload,
  resolveProviderModelCapabilities,
} from "./provider-capabilities.js";

export type SharedBrainProviderCandidate = {
  provider: SharedBrainProvider;
  baseUrl: string;
  compatibilityBaseUrl?: string;
  preferredModels: string[];
  hosted: boolean;
  routingScore?: number;
};

export type ModelRouteDecision = {
  provider: SharedBrainProvider;
  modelFamily: "gpt_oss" | "groq_compound" | "openai_frontier" | "gemini" | "local" | "other";
  workload: SharedBrainWorkload;
  compoundUsed: boolean;
  privacyGate: "public_safe" | "local_private" | "sensitive_vision" | "restricted" | "none";
  fallbackUsed: boolean;
};

export function getConfiguredProviderApiKey(
  app: FastifyInstance,
  provider: "groq" | "gemini" | "openai",
): string {
  return getConfiguredProviderApiKeys(app, provider)[0] ?? "";
}

export function getConfiguredProviderApiKeys(
  app: FastifyInstance,
  provider: "groq" | "gemini" | "openai",
): string[] {
  const normalize = (value: unknown) => {
    if (typeof value !== "string") {
      return [];
    }
    return value
      .split(",")
      .map((entry) => entry.trim())
      .filter((entry) => entry.length > 0);
  };
  switch (provider) {
    case "groq":
      return normalize(app.config.GROQ_API_KEY);
    case "gemini":
      return normalize(app.config.GEMINI_API_KEY);
    case "openai":
      return normalize(app.config.OPENAI_API_KEY);
    default:
      return [];
  }
}

export function getConfiguredProviderKeySlot(
  app: FastifyInstance,
  provider: "groq" | "gemini" | "openai",
  requestKeySeed?: string,
): number {
  const keys = getConfiguredProviderApiKeys(app, provider);
  if (keys.length <= 1 || !requestKeySeed?.trim()) return 0;
  const digest = createHash("sha256").update(requestKeySeed).digest();
  return digest.readUInt32BE(0) % keys.length;
}

export function getConfiguredProviderBaseUrl(
  app: FastifyInstance,
  provider: "groq" | "gemini" | "openai",
): string | null {
  const normalize = (value: unknown) => {
    const trimmed = typeof value === "string" ? value.trim() : "";
    return trimmed || null;
  };
  switch (provider) {
    case "groq":
      return normalize(app.config.GROQ_BASE_URL);
    case "gemini":
      // Shared-brain Gemini calls use the native Interactions API. Keep the
      // OpenAI-compatible base URL for utility clients that still need it.
      return (
        normalize(app.config.GEMINI_INTERACTIONS_BASE_URL) ??
        normalize(app.config.GEMINI_BASE_URL)?.replace(/\/openai\/?$/i, "") ??
        null
      );
    case "openai":
      return normalize(app.config.OPENAI_BASE_URL);
    default:
      return null;
  }
}

function getConfiguredGeminiCompatibilityBaseUrl(
  app: FastifyInstance,
): string | null {
  const value = typeof app.config.GEMINI_BASE_URL === "string"
    ? app.config.GEMINI_BASE_URL.trim()
    : "";
  return value || null;
}

function isVisionWorkload(workload: SharedBrainWorkload): boolean {
  return workload === "vision_reasoning" || workload === "image_analyze";
}

function isPublicResearchWorkload(workload: SharedBrainWorkload): boolean {
  return (
    workload === "public_research" ||
    workload === "public_deep_research" ||
    workload === "public_quantum_research"
  );
}

function compactText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function modelFamilyFor(provider: SharedBrainProvider, model: string): ModelRouteDecision["modelFamily"] {
  const normalized = model.toLowerCase();
  if (provider === "groq" && normalized.startsWith("openai/gpt-oss")) return "gpt_oss";
  if (provider === "groq" && normalized.startsWith("groq/compound")) return "groq_compound";
  if (provider === "openai") return "openai_frontier";
  if (provider === "gemini") return "gemini";
  if (["ollama", "vllm", "llamacpp"].includes(provider)) return "local";
  return "other";
}

export function buildModelRouteDecision(input: {
  provider: SharedBrainProvider;
  model: string;
  workload: SharedBrainWorkload;
  hosted: boolean;
  fallbackUsed?: boolean;
  visionSensitivity?: VisionMediaDecision["sensitivity"];
}): ModelRouteDecision {
  const compoundUsed = input.provider === "groq" && input.model.toLowerCase().startsWith("groq/compound");
  const privacyGate =
    input.visionSensitivity === "restricted"
      ? "restricted"
      : input.visionSensitivity === "sensitive"
        ? "sensitive_vision"
        : input.hosted && !isPublicResearchWorkload(input.workload) && input.workload === "document_analysis"
          ? "local_private"
          : input.hosted
            ? "public_safe"
            : "none";
  return {
    provider: input.provider,
    modelFamily: modelFamilyFor(input.provider, input.model),
    workload: input.workload,
    compoundUsed,
    privacyGate,
    fallbackUsed: input.fallbackUsed === true,
  };
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
  structuredOutputRequired?: boolean,
  structuredGeminiEligible?: boolean,
  /** Derinlik-router: turda canlı web / güncel veri ihtiyacı sinyali. Compound
   * bayrağı açıkken bu, uygun olmayan iş yüklerinde bile compound'u güçlendirir
   * (bkz. shouldUseGroqCompound). Bayrak kapalıysa etkisizdir. */
  liveWebSignal?: boolean,
): SharedBrainProviderCandidate[] {
  const hostedCandidates: SharedBrainProviderCandidate[] = [];
  const strictStructuredOutput =
    structuredOutputRequired === true || isStructuredGroqWorkload(workload);

  const groqApiKey = getConfiguredProviderApiKey(app, "groq");
  const groqBaseUrl = getConfiguredProviderBaseUrl(app, "groq");
  const groqCatalog = buildGroqModelCatalog(app.config);
  const groqPrimaryModel = groqCatalog.defaultModelByWorkload[workload];
  const groqFallbackModel =
    resolveGroqFallbackModel(app.config, groqPrimaryModel, workload) ??
    groqCatalog.fallbackModel;
  // Groq Compound (opsiyonel): bayrak açık, iş yükü uygun ve içerik gizlilik-
  // duyarlı DEĞİLse compound birincil olarak denenir. Ardından mevcut gpt-oss
  // zinciri fallback kalır — compound boş/başarısız dönerse kalite gerilemez,
  // başarılı olursa canlı web + kod yürütmeyle grounding artar.
  // Compound bir ARAÇ KULLANAN ajan modelidir: canlı web/kod turu koşar ve
  // düzyazı + araç izi döndürür. Katı JSON isteyen rotalarda (desktop planlama,
  // response schema zorunlu turlar) her çağrıda boş/geçersiz çıktı verip
  // zinciri tüketiyordu — canlı kanıt: `groq/compound ... invalid_output:
  // empty_response` iki denemede, ardından gerçek modele sıra gelmeden gecikme.
  // Yapısal çıktı gerektiğinde compound zincire HİÇ girmez; gpt-oss birincil olur.
  const compoundEligible =
    strictStructuredOutput !== true &&
    (!visionSensitivity || visionSensitivity === "none") &&
    shouldUseGroqCompound({ config: app.config, workload, liveWebSignal });
  const groqCompoundModel = compoundEligible
    ? resolveGroqCompoundModel(app.config, workload)
    : "";
  // Machine-json routes normally start on the workload's configured OSS
  // model. For routing/planning we still keep one compatibility fallback so a
  // malformed/unsupported JSON response does not collapse the whole task.
  // Document-analysis keeps its isolated lane until its provider contract is
  // migrated, so it deliberately has no cross-model fallback here.
  const structuredFallbackModel =
    workload === "intent" ||
    workload === "fast_route" ||
    workload === "planning"
      ? groqFallbackModel
      : "";
  if (groqApiKey && groqBaseUrl && groqPrimaryModel) {
    hostedCandidates.push({
      provider: "groq",
      baseUrl: groqBaseUrl,
      preferredModels: [
        groqCompoundModel,
        groqPrimaryModel,
        ...(strictStructuredOutput
          ? [structuredFallbackModel]
          : [structuredFallbackModel, groqFallbackModel]),
      ].filter(
        (model, index, values): model is string =>
          Boolean(model) && values.indexOf(model) === index,
      ),
      hosted: true,
    });
  }

  const openAiApiKey = getConfiguredProviderApiKey(app, "openai");
  const openAiBaseUrl = getConfiguredProviderBaseUrl(app, "openai");
  const openAiFrontierModel = compactText(app.config.OPENAI_FRONTIER_MODEL);
  if (
    openAiApiKey &&
    openAiBaseUrl &&
    openAiFrontierModel &&
    workload === "public_deep_research" &&
    (!visionSensitivity || visionSensitivity === "none")
  ) {
    hostedCandidates.push({
      provider: "openai",
      baseUrl: openAiBaseUrl,
      preferredModels: [openAiFrontierModel],
      hosted: true,
    });
  }

  const geminiApiKey = getConfiguredProviderApiKey(app, "gemini");
  const geminiBaseUrl = getConfiguredProviderBaseUrl(app, "gemini");
  const geminiCompatibilityBaseUrl = getConfiguredGeminiCompatibilityBaseUrl(app);
  const geminiCatalog = buildGeminiModelCatalog(app.config);
  // Gemini Flash is the primary multimodal lane. It receives native image
  // parts and the provider-specific visual resolution controls; Groq remains
  // the ordered fallback when Gemini is unavailable or policy removes it.
  const geminiPrimaryModel = isVisionWorkload(workload)
    ? geminiCatalog.visionModel
    : workload === "document_analysis"
      ? geminiCatalog.fastModel
      : geminiCatalog.defaultModelByWorkload[workload];
  const geminiFallbackModel =
    isVisionWorkload(workload) && geminiPrimaryModel === geminiCatalog.visionModel
      ? geminiCatalog.fastModel
      : workload === "document_analysis" && geminiPrimaryModel === geminiCatalog.fastModel
        ? geminiCatalog.textModel
        : resolveGeminiFallbackModel(app.config, geminiPrimaryModel) ??
          geminiCatalog.fastModel;
  const allowStructuredGemini =
    strictStructuredOutput !== true || structuredGeminiEligible === true;
  if (geminiApiKey && geminiBaseUrl && geminiPrimaryModel && allowStructuredGemini) {
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
        ...(geminiCompatibilityBaseUrl
          ? { compatibilityBaseUrl: geminiCompatibilityBaseUrl }
          : {}),
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

  // Keep Gemini first for every cloud visual turn so Flash's native
  // multimodal path is authoritative. Groq remains an ordered fallback.
  const preferredProvider = "gemini";
  if (
    app.config.GEMINI_FREE_ONLY === true &&
    privacyEligibleCandidates.some(
      (candidate) => candidate.provider === "gemini",
    )
  ) {
    return privacyEligibleCandidates.filter(
      (candidate) => candidate.provider === "gemini",
    );
  }
  return [
    ...privacyEligibleCandidates.filter((candidate) => candidate.provider === preferredProvider),
    ...privacyEligibleCandidates.filter((candidate) => candidate.provider !== preferredProvider),
  ];
}

type ProviderPerformance = {
  samples: number;
  failures: number;
  firstDelta: number[];
  completion: number[];
};

type ProviderPerformanceCacheEntry = {
  expiresAt: number;
  values: Map<string, ProviderPerformance>;
  pending?: Promise<Map<string, ProviderPerformance>>;
};

const providerPerformanceCache = new WeakMap<
  FastifyInstance,
  Map<SharedBrainWorkload, ProviderPerformanceCacheEntry>
>();
const PROVIDER_PERFORMANCE_CACHE_TTL_MS = 15_000;
const PROVIDER_PERFORMANCE_ERROR_CACHE_TTL_MS = 5_000;

function readMetadataNumber(metadata: unknown, key: string): number | null {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return null;
  const value = (metadata as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function percentile(samples: number[], ratio: number): number | null {
  if (samples.length === 0) return null;
  const sorted = [...samples].sort((left, right) => left - right);
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil(sorted.length * ratio) - 1),
  );
  return sorted[index] ?? null;
}

function performanceKey(provider: string, model: string): string {
  return `${provider}:${model}`.toLowerCase();
}

async function loadRecentProviderPerformance(
  app: FastifyInstance,
  workload: SharedBrainWorkload,
): Promise<Map<string, ProviderPerformance>> {
  const appCache =
    providerPerformanceCache.get(app) ??
    new Map<SharedBrainWorkload, ProviderPerformanceCacheEntry>();
  providerPerformanceCache.set(app, appCache);
  const now = Date.now();
  const existing = appCache.get(workload);
  if (existing && existing.expiresAt > now) return existing.values;
  if (existing?.pending) return existing.pending;

  const entry: ProviderPerformanceCacheEntry = existing ?? {
    expiresAt: 0,
    values: new Map(),
  };
  const pending = (async () => {
    try {
      const rows = await app.db
        .select({
          provider: aiProviderInvocations.provider,
          model: aiProviderInvocations.model,
          status: aiProviderInvocations.status,
          latencyMs: aiProviderInvocations.latencyMs,
          metadata: aiProviderInvocations.metadata,
        })
        .from(aiProviderInvocations)
        .where(
          and(
            eq(aiProviderInvocations.route, "shared_brain"),
            eq(aiProviderInvocations.workload, workload),
          ),
        )
        .orderBy(desc(aiProviderInvocations.createdAt))
        .limit(160);

      const values = new Map<string, ProviderPerformance>();
      for (const row of rows) {
        const key = performanceKey(row.provider, row.model);
        const current = values.get(key) ?? {
          samples: 0,
          failures: 0,
          firstDelta: [],
          completion: [],
        };
        current.samples += 1;
        if (row.status !== "success" && row.status !== "fallback") {
          current.failures += 1;
        }
        const firstDelta = readMetadataNumber(row.metadata, "firstDeltaMs");
        const completion =
          readMetadataNumber(row.metadata, "completionLatencyMs") ?? row.latencyMs;
        if (firstDelta != null) current.firstDelta.push(firstDelta);
        if (completion != null) current.completion.push(completion);
        values.set(key, current);
      }
      entry.values = values;
      entry.expiresAt = Date.now() + PROVIDER_PERFORMANCE_CACHE_TTL_MS;
      return values;
    } catch {
      entry.values = new Map();
      entry.expiresAt = Date.now() + PROVIDER_PERFORMANCE_ERROR_CACHE_TTL_MS;
      return entry.values;
    } finally {
      entry.pending = undefined;
    }
  })();
  entry.pending = pending;
  appCache.set(workload, entry);
  return pending;
}

/**
 * Ranks the already policy-filtered candidates using recent provider
 * telemetry. This is deliberately a soft ranking: missing metrics never
 * remove a provider, and the existing circuit/privacy/fallback gates remain
 * authoritative.
 */
export async function rankInferenceProviderCandidates(input: {
  app: FastifyInstance;
  candidates: SharedBrainProviderCandidate[];
  workload: SharedBrainWorkload;
  vision?: boolean;
  visionProfile?: VisionMediaProfile;
  structuredOutputRequired?: boolean;
}): Promise<SharedBrainProviderCandidate[]> {
  if (!input.candidates.length || !input.app.db) return input.candidates;

  // Structured output is a compatibility contract, not a latency contest.
  // Keep the policy order (Groq structured lane, then an eligible Gemini
  // candidate) instead of allowing historical latency to promote a provider
  // that cannot satisfy the schema.
  const strictStructuredOutput =
    input.structuredOutputRequired === true ||
    isStructuredGroqWorkload(input.workload);
  if (strictStructuredOutput) {
    return input.candidates.map((candidate) => ({
      ...candidate,
      preferredModels: [...candidate.preferredModels],
    }));
  }

  const performance = await loadRecentProviderPerformance(
    input.app,
    input.workload,
  );

  const scoreModel = (provider: SharedBrainProvider, model: string): number => {
    const capabilities = resolveProviderModelCapabilities(provider, model);
    let score = capabilityScoreForWorkload(capabilities, input.workload, {
      vision: input.vision,
      profile:
        input.visionProfile === "restricted"
          ? undefined
          : input.visionProfile,
      structured: strictStructuredOutput,
    });
    const stats = performance.get(performanceKey(provider, model));
    if (!stats) return score;
    const latencySamples =
      input.vision ||
      input.workload === "mobile_chat_fast" ||
      input.workload === "fast_route" ||
      input.workload === "intent"
        ? stats.firstDelta
        : stats.completion;
    const p75 = percentile(latencySamples, 0.75);
    if (p75 != null) score -= Math.min(36, p75 / 180);
    score -= Math.min(48, (stats.failures / Math.max(1, stats.samples)) * 80);
    return score;
  };

  const ranked = input.candidates
    .map((candidate, candidateIndex) => {
      const preferredModels = [...candidate.preferredModels].sort((left, right) => {
        const difference = scoreModel(candidate.provider, right) - scoreModel(candidate.provider, left);
        return difference || candidate.preferredModels.indexOf(left) - candidate.preferredModels.indexOf(right);
      });
      const routingScore = preferredModels[0]
        ? scoreModel(candidate.provider, preferredModels[0])
        : Number.NEGATIVE_INFINITY;
      return {
        candidate: { ...candidate, preferredModels, routingScore },
        candidateIndex,
      };
    })
    .sort((left, right) => right.candidate.routingScore! - left.candidate.routingScore! || left.candidateIndex - right.candidateIndex)
    .map((entry) => entry.candidate);

  // Telemetry may improve model ordering, but it must not silently replace
  // the multimodal provider policy. Gemini stays first when visual input is
  // present; the remaining candidates keep their measured order.
  if (input.vision && ranked.some((candidate) => candidate.provider === "gemini")) {
    return [
      ...ranked.filter((candidate) => candidate.provider === "gemini"),
      ...ranked.filter((candidate) => candidate.provider !== "gemini"),
    ];
  }
  return ranked;
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
  /** Katı JSON bekleniyor (plan zarfı / response schema): araç-ajanı modeller
   * zincire alınmaz — düzyazı döndürüp turu boşa harcarlar. */
  structuredOutputRequired?: boolean;
  /** Paid Gemini structured fallback is legal only after consent validation. */
  structuredGeminiEligible?: boolean;
  /** Derinlik-router sinyali: turda canlı web / güncel veri ihtiyacı. Compound
   * bayrağı açıkken doğru turlarda compound'u tercih ettirir; kapalıysa no-op. */
  liveWebSignal?: boolean;
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
    input.structuredOutputRequired,
    input.structuredGeminiEligible,
    input.liveWebSignal,
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
  requestKeySeed?: string,
): Record<string, string> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  if (provider !== "groq" && provider !== "gemini" && provider !== "openai") {
    return headers;
  }

  const apiKey =
    provider === "groq" || provider === "gemini" || provider === "openai"
      ? getConfiguredProviderApiKeys(app, provider)[
          getConfiguredProviderKeySlot(app, provider, requestKeySeed)
        ] ?? ""
      : "";
  if (apiKey) {
    headers.Authorization = `Bearer ${apiKey}`;
  }

  return headers;
}
