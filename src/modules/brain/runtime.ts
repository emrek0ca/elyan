import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";
import {
  getCircuitState,
  isCircuitCallAllowed,
  recordCircuitFailure,
  recordCircuitSuccess,
  summarizeCircuitState,
  type CircuitStateName,
} from "../../lib/reliability/circuit-breaker.js";

export type SharedBrainProvider =
  | "vllm"
  | "ollama"
  | "llamacpp"
  | "openai"
  | "claude"
  | "groq"
  | "gemini"
  | "openrouter";

export type SharedBrainRuntimeSnapshot = {
  provider: SharedBrainProvider;
  baseUrl: string;
  ready: boolean;
  checkedAt: Date;
  source: "config" | "probe";
};

type SharedBrainProviderCandidate = {
  provider: SharedBrainProvider;
  baseUrl: string;
};

type SharedBrainCacheEntry = {
  snapshot: SharedBrainRuntimeSnapshot;
  expiresAt: number;
  pending?: Promise<SharedBrainRuntimeSnapshot>;
};

const runtimeCache = new WeakMap<FastifyInstance, SharedBrainCacheEntry>();
const HEALTHY_CACHE_TTL_MS = 60_000;
const UNHEALTHY_CACHE_TTL_MS = 10_000;
const PROBE_TIMEOUT_MS = 2_500;

function normalizeProvider(raw: string): SharedBrainProvider {
  const normalized = raw.trim().toLowerCase().replace(/[_\s.-]+/g, "");

  if (normalized === "ollama") {
    return "ollama";
  }

  if (normalized === "openai") {
    return "openai";
  }

  if (normalized === "claude" || normalized === "anthropic") {
    return "claude";
  }

  if (normalized === "groq") {
    return "groq";
  }

  if (normalized === "gemini" || normalized === "google" || normalized === "googleai") {
    return "gemini";
  }

  if (normalized === "openrouter") {
    return "openrouter";
  }

  if (normalized === "llamacpp" || normalized === "llamacppserver") {
    return "llamacpp";
  }

  return "vllm";
}

function normalizeBaseUrl(raw: string | undefined | null): string {
  return String(raw ?? "").trim().replace(/\/$/, "");
}

function getConfiguredProviderApiKey(app: FastifyInstance, provider: SharedBrainProvider): string {
  const normalize = (value: unknown) => (typeof value === "string" ? value.trim() : "");
  switch (provider) {
    case "openai":
      return normalize(app.config.OPENAI_API_KEY);
    case "claude":
      return normalize(app.config.ANTHROPIC_API_KEY);
    case "groq":
      // GROQ_API_KEY may be a comma-separated pool; the provider expects a
      // single bearer token, so use the first non-empty entry.
      return (
        String(app.config.GROQ_API_KEY ?? "")
          .split(",")
          .map((entry) => entry.trim())
          .find((entry) => entry.length > 0) ?? ""
      );
    case "gemini":
      return normalize(app.config.GEMINI_API_KEY);
    case "openrouter":
      return normalize(app.config.OPENROUTER_API_KEY);
    default:
      return "";
  }
}

function joinProviderUrl(baseUrl: string, path: string): string {
  const normalizedBase = baseUrl.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`.replace(/\/v1\/v1\//g, "/v1/");
}

function buildCandidateSnapshot(
  candidate: SharedBrainProviderCandidate,
  ready: boolean,
  source: "config" | "probe",
): SharedBrainRuntimeSnapshot {
  return {
    provider: candidate.provider,
    baseUrl: candidate.baseUrl,
    ready,
    checkedAt: new Date(),
    source,
  };
}

function getPrimaryProviderCandidate(app: FastifyInstance): SharedBrainProviderCandidate {
  return {
    provider: normalizeProvider(app.config.ELYAN_SHARED_BRAIN_PROVIDER),
    baseUrl: normalizeBaseUrl(app.config.ELYAN_SHARED_BRAIN_BASE_URL),
  };
}

function getFallbackProviderCandidate(app: FastifyInstance): SharedBrainProviderCandidate | null {
  const provider = String(app.config.ELYAN_SHARED_BRAIN_FALLBACK_PROVIDER ?? "").trim();
  const baseUrl = normalizeBaseUrl(app.config.ELYAN_SHARED_BRAIN_FALLBACK_BASE_URL || app.config.ELYAN_SHARED_BRAIN_BASE_URL);

  if (!provider) {
    return null;
  }

  return {
    provider: normalizeProvider(provider),
    baseUrl,
  };
}

export function listSharedBrainProviderCandidates(app: FastifyInstance): SharedBrainProviderCandidate[] {
  const candidates = [getPrimaryProviderCandidate(app), getFallbackProviderCandidate(app)].filter(
    (candidate): candidate is SharedBrainProviderCandidate => Boolean(candidate && candidate.baseUrl),
  );
  const unique = new Map<string, SharedBrainProviderCandidate>();

  for (const candidate of candidates) {
    unique.set(`${candidate.provider}:${candidate.baseUrl}`, candidate);
  }

  return [...unique.values()];
}

function getProbePaths(provider: SharedBrainProvider): string[] {
  if (provider === "ollama") {
    return ["/api/tags"];
  }

  if (provider === "openai" || provider === "groq" || provider === "gemini" || provider === "openrouter") {
    return ["/models", "/v1/models"];
  }

  if (provider === "claude") {
    return ["/messages", "/v1/messages"];
  }

  return ["/health", "/v1/models"];
}

async function probeUrl(
  url: string,
  timeoutMs = PROBE_TIMEOUT_MS,
  headers: Record<string, string> = {},
): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method: "GET",
      headers,
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function probeSharedBrainCandidate(
  app: FastifyInstance,
  candidate: SharedBrainProviderCandidate,
): Promise<boolean> {
  const apiKey = getConfiguredProviderApiKey(app, candidate.provider);
  const headers: Record<string, string> = {};

  if (apiKey && (candidate.provider === "openai" || candidate.provider === "groq" || candidate.provider === "gemini" || candidate.provider === "openrouter")) {
    headers.Authorization = `Bearer ${apiKey}`;
  } else if (apiKey && candidate.provider === "claude") {
    headers["x-api-key"] = apiKey;
  }

  for (const path of getProbePaths(candidate.provider)) {
    if (await probeUrl(joinProviderUrl(candidate.baseUrl, path), PROBE_TIMEOUT_MS, headers)) {
      return true;
    }
  }

  return false;
}

export function getBrainCircuitKey(candidate: SharedBrainProviderCandidate): string {
  const digest = createHash("sha256").update(`${candidate.provider}:${candidate.baseUrl}`).digest("hex").slice(0, 24);
  return `circuit:brain:${candidate.provider}:${digest}`;
}

async function probeSharedBrainCandidateWithCircuit(
  app: FastifyInstance,
  candidate: SharedBrainProviderCandidate,
): Promise<boolean> {
  const reliability = app.services?.reliability;
  if (!reliability) {
    return probeSharedBrainCandidate(app, candidate);
  }

  const key = getBrainCircuitKey(candidate);
  const allowed = await isCircuitCallAllowed(reliability.store, key);
  if (!allowed) {
    return false;
  }

  const ready = await probeSharedBrainCandidate(app, candidate);
  if (ready) {
    await recordCircuitSuccess(reliability.store, key, app.config.BRAIN_CIRCUIT_OPEN_MS);
    return true;
  }

  await recordCircuitFailure(
    reliability.store,
    key,
    {
      failureThreshold: app.config.BRAIN_CIRCUIT_FAILURE_THRESHOLD,
      openMs: app.config.BRAIN_CIRCUIT_OPEN_MS,
    },
    "server_brain_unavailable",
  );
  return false;
}

export async function getSharedBrainProviderCircuitState(app: FastifyInstance): Promise<CircuitStateName> {
  const reliability = app.services?.reliability;
  if (!reliability) {
    return "closed";
  }
  const candidates = listSharedBrainProviderCandidates(app);
  const states = await Promise.all(
    candidates.map((candidate) => getCircuitState(reliability.store, getBrainCircuitKey(candidate))),
  );

  if (states.some((state) => state.state === "closed")) {
    return "closed";
  }
  if (states.some((state) => state.state === "half_open")) {
    return "half_open";
  }
  return summarizeCircuitState(states[0] ?? { state: "closed", failureCount: 0, openedUntil: null, lastFailureCode: null });
}

function getCacheEntry(app: FastifyInstance): SharedBrainCacheEntry | null {
  return runtimeCache.get(app) ?? null;
}

function storeCacheEntry(app: FastifyInstance, snapshot: SharedBrainRuntimeSnapshot): SharedBrainRuntimeSnapshot {
  runtimeCache.set(app, {
    snapshot,
    expiresAt: Date.now() + (snapshot.ready ? HEALTHY_CACHE_TTL_MS : UNHEALTHY_CACHE_TTL_MS),
  });

  return snapshot;
}

export function getSharedBrainRuntimeSnapshot(app: FastifyInstance): SharedBrainRuntimeSnapshot {
  const cached = getCacheEntry(app);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.snapshot;
  }

  const candidate = getPrimaryProviderCandidate(app);
  return buildCandidateSnapshot(candidate, false, "config");
}

export async function warmSharedBrainRuntime(app: FastifyInstance): Promise<SharedBrainRuntimeSnapshot> {
  const cached = getCacheEntry(app);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.snapshot;
  }

  if (cached?.pending) {
    return cached.pending;
  }

  const candidates = listSharedBrainProviderCandidates(app);
  const selectedPromise = (async () => {
    for (const candidate of candidates) {
      const ready = await probeSharedBrainCandidateWithCircuit(app, candidate);
      if (ready) {
        return storeCacheEntry(app, buildCandidateSnapshot(candidate, true, "probe"));
      }
    }

    const fallbackCandidate = candidates[0] ?? getPrimaryProviderCandidate(app);
    return storeCacheEntry(app, buildCandidateSnapshot(fallbackCandidate, false, "probe"));
  })();

  runtimeCache.set(app, {
    snapshot: cached?.snapshot ?? buildCandidateSnapshot(getPrimaryProviderCandidate(app), false, "config"),
    expiresAt: Date.now() + UNHEALTHY_CACHE_TTL_MS,
    pending: selectedPromise,
  });

  return selectedPromise;
}

export async function selectSharedBrainRuntime(
  app: FastifyInstance,
  options: { skipProbe?: boolean } = {},
): Promise<SharedBrainRuntimeSnapshot> {
  const snapshot = getSharedBrainRuntimeSnapshot(app);
  if (snapshot.ready) {
    return snapshot;
  }

  // The latency-critical hosted lane already has an authenticated provider
  // configured. A health probe adds a network round trip before the real
  // request and can be stale by the time it returns; let the request/circuit
  // path own failure handling instead.
  if (options.skipProbe) {
    const candidate = getPrimaryProviderCandidate(app);
    const hostedProvider =
      candidate.provider === "groq" ||
      candidate.provider === "gemini" ||
      candidate.provider === "openai" ||
      candidate.provider === "openrouter" ||
      candidate.provider === "claude";
    if (hostedProvider && getConfiguredProviderApiKey(app, candidate.provider)) {
      return storeCacheEntry(app, buildCandidateSnapshot(candidate, true, "config"));
    }
  }

  return warmSharedBrainRuntime(app);
}
