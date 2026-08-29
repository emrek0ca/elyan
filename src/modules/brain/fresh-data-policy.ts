import { collapseWhitespace as compactText } from "../../lib/text.js";
import { asRecord as readRecord } from "../../lib/record.js";
export type FreshDataDomain =
  | "news"
  | "market"
  | "weather"
  | "sports"
  | "regulation"
  | "software_security"
  | "software_release"
  | "url_review"
  | "general";

export type FreshDataPolicy = {
  schemaVersion: "elyan.fresh_data_policy.v1";
  domain: FreshDataDomain;
  freshnessRequired: boolean;
  cacheTtlMs: number;
  refreshAfterMs: number;
  sourceMaxAgeMs: number;
  staleIfErrorMs: number;
  allowStaleIfError: boolean;
  minimumSources: number;
  minimumVerifiedSources: number;
  minimumDatedSources: number;
  preferredHosts: string[];
  searchCategory: "general" | "news" | "science" | "it";
  reasons: string[];
};

export type FreshDataPolicyContext = {
  socialTurn?: boolean;
  publicKnowledgeRequest?: boolean;
};

export type FreshDataStatus =
  | "fresh"
  | "aging"
  | "stale"
  | "undated"
  | "unavailable";

export type FreshDataEnvelope = {
  schemaVersion: "elyan.fresh_data.v1";
  domain: FreshDataDomain;
  status: FreshDataStatus;
  freshnessRequired: boolean;
  requestedAt: string;
  retrievedAt: string | null;
  freshUntil: string | null;
  staleUntil: string | null;
  ageMs: number | null;
  cache: {
    state: "miss" | "fresh_hit" | "stale_fallback";
    shared: boolean;
  };
  evidence: {
    sourceCount: number;
    freshSourceCount: number;
    verifiedSourceCount: number;
    freshVerifiedSourceCount: number;
    datedSourceCount: number;
    freshDatedSourceCount: number;
    independentHostCount: number;
    minimumSources: number;
    minimumVerifiedSources: number;
    minimumDatedSources: number;
    numericCorroborated: boolean | null;
    sufficient: boolean;
  };
  reasons: string[];
};

const FRESH_DATA_DOMAINS: readonly FreshDataDomain[] = [
  "news",
  "market",
  "weather",
  "sports",
  "regulation",
  "software_security",
  "software_release",
  "url_review",
  "general",
];
const FRESH_DATA_STATUSES: readonly FreshDataStatus[] = [
  "fresh",
  "aging",
  "stale",
  "undated",
  "unavailable",
];
const FRESH_DATA_CACHE_STATES: readonly FreshDataEnvelope["cache"]["state"][] = [
  "miss",
  "fresh_hit",
  "stale_fallback",
];

const URL_PATTERN = /https?:\/\/[^\s<>"')]+/iu;
const NEWS_PATTERN =
  /(?<!\p{L})(haber\p{L}*|news|son dakika|gündem\p{L}*|gundem\p{L}*|headlines?|breaking)(?!\p{L})/iu;
const MARKET_PATTERN =
  /(?<!\p{L})(dolar|usd|euro|eur|avro|sterlin|gbp|döviz|doviz|kur|altın|altin|gümüş|gumus|bitcoin|btc|ethereum|eth|kripto|borsa|bist|nasdaq|s&p|hisse|emtia|gram altın|gram altin|ons)(?!\p{L})/iu;
const WEATHER_PATTERN =
  /(?<!\p{L})(hava durumu|hava nasıl|hava nasil|kaç derece|kac derece|yağmur|yagmur|kar yağ|kar yag|rüzgar|ruzgar|weather|forecast)(?!\p{L})/iu;
const SPORTS_PATTERN =
  /(?<!\p{L})(maç|mac|skor|puan durumu|fikstür|fikstur|lig|şampiyon|sampiyon|formula 1|f1|nba|nfl|nhl|mlb|uefa|fifa|score|standings|fixture)(?!\p{L})/iu;
const REGULATION_PATTERN =
  /(?<!\p{L})(mevzuat|kanun|yasa|yönetmelik|yonetmelik|tebliğ|teblig|resmi gazete|regülasyon|regulasyon|regulation|legal|compliance)(?!\p{L})/iu;
const SOFTWARE_SECURITY_PATTERN =
  /(?<!\p{L})(cve-\d{4}-\d+|cve|vulnerability|zero.?day|security advisory|güvenlik açığı|guvenlik acigi|security fix)(?!\p{L})/iu;
const SOFTWARE_RELEASE_PATTERN =
  /(?<!\p{L})(son\s+s[üu]r[üu]m\p{L}*|latest version|release notes?|changelog|stable release|lts|deprecated|end of life|eol|npm|pypi|pub\.dev|crate|sdk|framework|library|kütüphane|kutuphane|paket|package)(?!\p{L})/iu;
const EXPLICIT_FRESHNESS_PATTERN =
  /(?<!\p{L})(bugün|bugun|şu an|su an|güncel|guncel|latest|recent|today|canlı|canli|anlık|anlik|son durum|doğrula|dogrula)(?!\p{L})/iu;
const GENERAL_INFORMATION_REQUEST_PATTERN =
  /\?|(?<!\p{L})(kim|nedir|neydi|ne\s+oldu|kaç|kac|hangi|nerede|where|who|what|when|how\s+many|bul|araştır|arastir|göster|goster|söyle|soyle|ver)(?!\p{L})/iu;

const DOMAIN_CONFIG: Record<
  FreshDataDomain,
  Omit<FreshDataPolicy, "schemaVersion" | "domain" | "freshnessRequired" | "reasons">
> = {
  news: {
    cacheTtlMs: 2 * 60_000,
    refreshAfterMs: 45_000,
    sourceMaxAgeMs: 48 * 60 * 60_000,
    staleIfErrorMs: 5 * 60_000,
    allowStaleIfError: false,
    minimumSources: 2,
    minimumVerifiedSources: 1,
    minimumDatedSources: 0,
    preferredHosts: ["aa.com.tr", "reuters.com", "apnews.com", "bbc.com", "trthaber.com"],
    searchCategory: "news",
  },
  market: {
    cacheTtlMs: 30_000,
    refreshAfterMs: 12_000,
    sourceMaxAgeMs: 24 * 60 * 60_000,
    staleIfErrorMs: 2 * 60_000,
    allowStaleIfError: false,
    minimumSources: 2,
    minimumVerifiedSources: 2,
    minimumDatedSources: 1,
    preferredHosts: ["tcmb.gov.tr", "borsaistanbul.com", "kap.org.tr", "investing.com", "tradingview.com"],
    searchCategory: "general",
  },
  weather: {
    cacheTtlMs: 5 * 60_000,
    refreshAfterMs: 2 * 60_000,
    sourceMaxAgeMs: 24 * 60 * 60_000,
    staleIfErrorMs: 15 * 60_000,
    allowStaleIfError: false,
    minimumSources: 1,
    minimumVerifiedSources: 1,
    minimumDatedSources: 0,
    preferredHosts: ["mgm.gov.tr", "open-meteo.com", "weather.com", "accuweather.com"],
    searchCategory: "general",
  },
  sports: {
    cacheTtlMs: 45_000,
    refreshAfterMs: 15_000,
    sourceMaxAgeMs: 24 * 60 * 60_000,
    staleIfErrorMs: 3 * 60_000,
    allowStaleIfError: false,
    minimumSources: 2,
    minimumVerifiedSources: 1,
    minimumDatedSources: 0,
    preferredHosts: ["uefa.com", "fifa.com", "nba.com", "nfl.com", "formula1.com"],
    searchCategory: "news",
  },
  regulation: {
    cacheTtlMs: 6 * 60 * 60_000,
    refreshAfterMs: 60 * 60_000,
    sourceMaxAgeMs: 365 * 24 * 60 * 60_000,
    staleIfErrorMs: 24 * 60 * 60_000,
    allowStaleIfError: true,
    minimumSources: 1,
    minimumVerifiedSources: 1,
    minimumDatedSources: 0,
    preferredHosts: ["resmigazete.gov.tr", "mevzuat.gov.tr", "eur-lex.europa.eu"],
    searchCategory: "general",
  },
  software_security: {
    cacheTtlMs: 10 * 60_000,
    refreshAfterMs: 3 * 60_000,
    sourceMaxAgeMs: 365 * 24 * 60 * 60_000,
    staleIfErrorMs: 30 * 60_000,
    allowStaleIfError: true,
    minimumSources: 1,
    minimumVerifiedSources: 1,
    minimumDatedSources: 1,
    preferredHosts: ["nvd.nist.gov", "cve.org", "github.com", "cisa.gov"],
    searchCategory: "it",
  },
  software_release: {
    cacheTtlMs: 30 * 60_000,
    refreshAfterMs: 10 * 60_000,
    sourceMaxAgeMs: 180 * 24 * 60 * 60_000,
    staleIfErrorMs: 2 * 60 * 60_000,
    allowStaleIfError: true,
    minimumSources: 1,
    minimumVerifiedSources: 1,
    minimumDatedSources: 0,
    preferredHosts: ["github.com", "npmjs.com", "pypi.org", "pub.dev"],
    searchCategory: "it",
  },
  url_review: {
    cacheTtlMs: 5 * 60_000,
    refreshAfterMs: 2 * 60_000,
    sourceMaxAgeMs: 30 * 24 * 60 * 60_000,
    staleIfErrorMs: 15 * 60_000,
    allowStaleIfError: true,
    minimumSources: 1,
    minimumVerifiedSources: 1,
    minimumDatedSources: 0,
    preferredHosts: [],
    searchCategory: "general",
  },
  general: {
    cacheTtlMs: 15 * 60_000,
    refreshAfterMs: 5 * 60_000,
    sourceMaxAgeMs: 30 * 24 * 60 * 60_000,
    staleIfErrorMs: 60 * 60_000,
    allowStaleIfError: true,
    minimumSources: 1,
    minimumVerifiedSources: 0,
    minimumDatedSources: 0,
    preferredHosts: [],
    searchCategory: "general",
  },
};

function readEnum<T extends string>(value: unknown, allowed: readonly T[]): T | null {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? value as T
    : null;
}

function readFiniteNonNegativeInteger(value: unknown, max = 10_000): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return Math.max(0, Math.min(max, Math.round(value)));
}

function readFiniteNonNegativeNumber(value: unknown, max = 365 * 24 * 60 * 60_000): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return Math.max(0, Math.min(max, value));
}

function normalizeIsoString(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 64) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString() : null;
}

function normalizeReasonList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(
    value
      .map((item) => compactText(String(item ?? "")).slice(0, 80))
      .filter(Boolean),
  )].slice(0, 8);
}

export function classifyFreshDataDomain(prompt: string): {
  domain: FreshDataDomain;
  reasons: string[];
} {
  const normalized = compactText(prompt);
  if (URL_PATTERN.test(normalized)) return { domain: "url_review", reasons: ["url_present"] };
  if (SOFTWARE_SECURITY_PATTERN.test(normalized)) return { domain: "software_security", reasons: ["software_security"] };
  if (REGULATION_PATTERN.test(normalized)) return { domain: "regulation", reasons: ["regulation"] };
  if (MARKET_PATTERN.test(normalized)) return { domain: "market", reasons: ["volatile_market"] };
  if (WEATHER_PATTERN.test(normalized)) return { domain: "weather", reasons: ["weather"] };
  if (SPORTS_PATTERN.test(normalized)) return { domain: "sports", reasons: ["live_sports"] };
  if (NEWS_PATTERN.test(normalized)) return { domain: "news", reasons: ["news"] };
  if (SOFTWARE_RELEASE_PATTERN.test(normalized)) return { domain: "software_release", reasons: ["software_release"] };
  return { domain: "general", reasons: [] };
}

export function resolveFreshDataPolicy(
  prompt: string,
  context?: FreshDataPolicyContext,
): FreshDataPolicy {
  const classified = classifyFreshDataDomain(prompt);
  const normalized = compactText(prompt);
  const explicitFreshness = EXPLICIT_FRESHNESS_PATTERN.test(normalized);
  const contextualGeneralFreshness =
    context == null
      ? explicitFreshness
      : explicitFreshness &&
        context.socialTurn !== true &&
        (context.publicKnowledgeRequest === true ||
          GENERAL_INFORMATION_REQUEST_PATTERN.test(normalized));
  const freshnessRequired =
    classified.domain !== "general" || contextualGeneralFreshness;
  return freshDataPolicyForDomain(classified.domain, {
    freshnessRequired,
    reasons: [
      ...classified.reasons,
      ...(contextualGeneralFreshness ? ["explicit_freshness"] : []),
    ],
  });
}

export function freshDataPolicyForDomain(
  domain: FreshDataDomain,
  overrides?: {
    freshnessRequired?: boolean;
    reasons?: string[];
  },
): FreshDataPolicy {
  const config = DOMAIN_CONFIG[domain];
  return {
    schemaVersion: "elyan.fresh_data_policy.v1",
    domain,
    freshnessRequired: overrides?.freshnessRequired ?? domain !== "general",
    ...config,
    reasons: [...new Set(overrides?.reasons ?? [])],
  };
}

export function sourceTrustScore(input: {
  host: string;
  authority: "official" | "trusted" | "standard" | "low";
  policy: FreshDataPolicy;
}): number {
  const normalizedHost = input.host.replace(/^www\./iu, "").toLocaleLowerCase("en-US");
  const authorityBase = {
    official: 0.92,
    trusted: 0.82,
    standard: 0.62,
    low: 0.25,
  }[input.authority];
  const preferred = input.policy.preferredHosts.some(
    (host) => normalizedHost === host || normalizedHost.endsWith(`.${host}`),
  );
  return Number(Math.min(1, authorityBase + (preferred ? 0.08 : 0)).toFixed(2));
}

function validDate(value: string | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

export function sourceFreshnessStatus(input: {
  publishedAt?: string;
  observedAt?: string;
  policy: FreshDataPolicy;
  now?: Date;
}): FreshDataStatus {
  const now = input.now ?? new Date();
  const publishedAt = validDate(input.publishedAt);
  const observedAt = validDate(input.observedAt);
  const usePublicationAge = input.policy.domain === "news" && publishedAt !== null;
  const timestamp = usePublicationAge ? publishedAt : observedAt ?? publishedAt;
  if (!timestamp) return "undated";
  const ageMs = Math.max(0, now.getTime() - timestamp.getTime());
  if (usePublicationAge) {
    if (ageMs <= Math.min(6 * 60 * 60_000, input.policy.sourceMaxAgeMs / 2)) return "fresh";
    if (ageMs <= input.policy.sourceMaxAgeMs) return "aging";
    return "stale";
  }
  if (ageMs <= input.policy.refreshAfterMs) return "fresh";
  if (ageMs <= input.policy.cacheTtlMs) return "aging";
  return "stale";
}

export function buildFreshDataEnvelope(input: {
  policy: FreshDataPolicy;
  requestedAt: Date;
  retrievedAt?: string;
  cacheState: FreshDataEnvelope["cache"]["state"];
  sourceCount: number;
  freshSourceCount?: number;
  verifiedSourceCount: number;
  freshVerifiedSourceCount?: number;
  datedSourceCount: number;
  freshDatedSourceCount?: number;
  independentHostCount: number;
  staleFallbackUsed?: boolean;
  reasons?: string[];
}): FreshDataEnvelope {
  const retrievedAt = validDate(input.retrievedAt);
  const freshSourceCount = input.freshSourceCount ?? input.sourceCount;
  const freshVerifiedSourceCount = input.freshVerifiedSourceCount ?? input.verifiedSourceCount;
  const freshDatedSourceCount = input.freshDatedSourceCount ?? input.datedSourceCount;
  const ageMs = retrievedAt
    ? Math.max(0, input.requestedAt.getTime() - retrievedAt.getTime())
    : null;
  const status: FreshDataStatus =
    input.sourceCount === 0
      ? "unavailable"
      : input.staleFallbackUsed
        ? "stale"
        : ageMs === null
          ? "undated"
          : ageMs <= input.policy.refreshAfterMs
            ? "fresh"
            : ageMs <= input.policy.cacheTtlMs
              ? "aging"
              : "stale";
  const sufficient =
    input.independentHostCount >= input.policy.minimumSources &&
    freshSourceCount >= input.policy.minimumSources &&
    freshVerifiedSourceCount >= input.policy.minimumVerifiedSources &&
    freshDatedSourceCount >= input.policy.minimumDatedSources &&
    (!input.policy.freshnessRequired || status === "fresh" || status === "aging");
  return {
    schemaVersion: "elyan.fresh_data.v1",
    domain: input.policy.domain,
    status,
    freshnessRequired: input.policy.freshnessRequired,
    requestedAt: input.requestedAt.toISOString(),
    retrievedAt: retrievedAt?.toISOString() ?? null,
    freshUntil: retrievedAt
      ? new Date(retrievedAt.getTime() + input.policy.cacheTtlMs).toISOString()
      : null,
    staleUntil: retrievedAt
      ? new Date(retrievedAt.getTime() + input.policy.cacheTtlMs + input.policy.staleIfErrorMs).toISOString()
      : null,
    ageMs,
    cache: {
      state: input.cacheState,
      shared: input.cacheState !== "miss",
    },
    evidence: {
      sourceCount: input.sourceCount,
      freshSourceCount,
      verifiedSourceCount: input.verifiedSourceCount,
      freshVerifiedSourceCount,
      datedSourceCount: input.datedSourceCount,
      freshDatedSourceCount,
      independentHostCount: input.independentHostCount,
      minimumSources: input.policy.minimumSources,
      minimumVerifiedSources: input.policy.minimumVerifiedSources,
      minimumDatedSources: input.policy.minimumDatedSources,
      numericCorroborated: null,
      sufficient,
    },
    reasons: [...new Set([...input.policy.reasons, ...(input.reasons ?? [])])].slice(0, 8),
  };
}

export function normalizeFreshDataEnvelope(value: unknown): FreshDataEnvelope | null {
  const record = readRecord(value);
  if (!record || record.schemaVersion !== "elyan.fresh_data.v1") {
    return null;
  }
  const domain = readEnum(record.domain, FRESH_DATA_DOMAINS);
  const status = readEnum(record.status, FRESH_DATA_STATUSES);
  const requestedAt = normalizeIsoString(record.requestedAt);
  const retrievedAt = record.retrievedAt === null ? null : normalizeIsoString(record.retrievedAt);
  const freshUntil = record.freshUntil === null ? null : normalizeIsoString(record.freshUntil);
  const staleUntil = record.staleUntil === null ? null : normalizeIsoString(record.staleUntil);
  const cache = readRecord(record.cache);
  const evidence = readRecord(record.evidence);
  if (
    !domain ||
    !status ||
    typeof record.freshnessRequired !== "boolean" ||
    !requestedAt ||
    !cache ||
    !evidence
  ) {
    return null;
  }
  const cacheState = readEnum(cache.state, FRESH_DATA_CACHE_STATES);
  if (!cacheState || typeof cache.shared !== "boolean") {
    return null;
  }
  const sourceCount = readFiniteNonNegativeInteger(evidence.sourceCount);
  const verifiedSourceCount = readFiniteNonNegativeInteger(evidence.verifiedSourceCount);
  const datedSourceCount = readFiniteNonNegativeInteger(evidence.datedSourceCount);
  const independentHostCount = readFiniteNonNegativeInteger(evidence.independentHostCount);
  const minimumSources = readFiniteNonNegativeInteger(evidence.minimumSources);
  const minimumVerifiedSources = readFiniteNonNegativeInteger(evidence.minimumVerifiedSources);
  const minimumDatedSources = readFiniteNonNegativeInteger(evidence.minimumDatedSources);
  if (
    sourceCount === null ||
    verifiedSourceCount === null ||
    datedSourceCount === null ||
    independentHostCount === null ||
    minimumSources === null ||
    minimumVerifiedSources === null ||
    minimumDatedSources === null ||
    typeof evidence.sufficient !== "boolean"
  ) {
    return null;
  }
  const freshSourceCount = readFiniteNonNegativeInteger(evidence.freshSourceCount) ?? sourceCount;
  const freshVerifiedSourceCount =
    readFiniteNonNegativeInteger(evidence.freshVerifiedSourceCount) ?? verifiedSourceCount;
  const freshDatedSourceCount =
    readFiniteNonNegativeInteger(evidence.freshDatedSourceCount) ?? datedSourceCount;
  const numericCorroborated =
    typeof evidence.numericCorroborated === "boolean" ? evidence.numericCorroborated : null;
  return {
    schemaVersion: "elyan.fresh_data.v1",
    domain,
    status,
    freshnessRequired: record.freshnessRequired,
    requestedAt,
    retrievedAt,
    freshUntil,
    staleUntil,
    ageMs: record.ageMs === null ? null : readFiniteNonNegativeNumber(record.ageMs),
    cache: {
      state: cacheState,
      shared: cache.shared,
    },
    evidence: {
      sourceCount,
      freshSourceCount,
      verifiedSourceCount,
      freshVerifiedSourceCount,
      datedSourceCount,
      freshDatedSourceCount,
      independentHostCount,
      minimumSources,
      minimumVerifiedSources,
      minimumDatedSources,
      numericCorroborated,
      sufficient: evidence.sufficient,
    },
    reasons: normalizeReasonList(record.reasons),
  };
}

export function buildFreshSearchSuffix(policy: FreshDataPolicy, now = new Date()): string {
  const date = now.toISOString().slice(0, 10);
  switch (policy.domain) {
    case "news":
      return `${date} latest news`;
    case "market":
      return `${date} live price official`;
    case "weather":
      return `${date} current forecast official`;
    case "sports":
      return `${date} live score official`;
    case "regulation":
      return "official current regulation";
    case "software_security":
      return `${date} official security advisory`;
    case "software_release":
      return "official latest release";
    case "url_review":
    case "general":
      return "";
  }
}
