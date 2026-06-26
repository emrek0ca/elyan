import type { FastifyInstance } from "fastify";
import type { SharedBrainWorkload } from "./workloads.js";
import {
  buildTurkicWebQueryVariants,
  isTurkicLanguageResearchPrompt,
} from "../../core/understanding/turkic-language.js";

export type WebGroundingSearchResult = {
  title: string;
  url: string;
  snippet: string;
  sourceHost: string;
  verificationState: "verified" | "partial" | "unverified";
  queryHits: number;
  score: number;
};

export type WebGroundingResult = {
  enabled: boolean;
  used: boolean;
  query: string;
  queries: string[];
  source: "duckduckgo_html";
  results: WebGroundingSearchResult[];
  degradedReason: string | null;
  confidence: "high" | "medium" | "low";
  retrievedAt?: string;
  decisionReasons?: string[];
};

type WebGroundingCacheEntry = {
  expiresAt: number;
  value: WebGroundingResult | Promise<WebGroundingResult>;
};

const WEB_RESEARCH_PATTERNS = [
  /\b(internet|web|online|çevrim içi|cevrim ici|internetten|webden)\b/i,
  /\b(araştır|arastir|araştırma|arastirma|research)\b/i,
  /\b(güncel|guncel|latest|recent|son durum|bugün|today|news|haber)\b/i,
  /\b(karşılaştır|karsilastir|compare|benchmark|farkı|farki|difference|artı eksi|arti eksi)\b/i,
  /\b(resmi|official|dokümantasyon|documentation|kaynak|source)\b/i,
  /\b(fiyat|price|kur|rate|release note|release notes?|changelog|son sürüm|son surum|duyuru|announcement)\b/i,
  /\b(veri|veriler|data|istatistik|istatistikler|statistics?|rapor|report|anket|survey|trend|piyasa|market)\b/i,
  /\b(yasa|kanun|mevzuat|regulation|legal|uyumluluk|compliance|standart|standard|kılavuz|kilavuz|guideline)\b/i,
  /\b(dil|lehçe|lehce|gramer|grammar|etimoloji|etymology|alfabe|alphabet|çeviri|ceviri|transliteration|kelime hazinesi|söz varlığı|soz varligi)\b/i,
  /\b(türk dünyası|turkic|oğuz|oguz|kıpçak|kipchak|karluk|qipchak|qarluq|azerbaijani|kazakh|kyrgyz|uzbek|turkmen|uyghur|tatar|bashkir|gagauz|karakalpak|sakha|chuvash)\b/i,
];

const PERSONAL_ONLY_PATTERNS = [
  /\b(beni|bana|benim|hesabım|hesabim|profilim|geçmişim|gecmisim|mesajlarım|mesajlarim|dosyam|dosyalarım|dosyalarim|sağlığım|sagligim)\b/i,
  /\b(my account|my profile|my messages|my files|my health|about me)\b/i,
];

const EXPLICIT_WEB_PATTERNS = [
  /\b(internetten|webden|online|web araştır|web arastir|internet araştır|internet arastir|search the web|look up|browse)\b/i,
  /\b(kaynaklı|kaynaklarla|kaynak göster|source-backed|with sources|cite sources)\b/i,
];

// ── Factuality gate ──────────────────────────────────────────────────────
// Volatile, externally-verifiable facts that change frequently and where the
// model's parametric memory is almost always stale → ground even without an
// explicit "araştır/internetten" keyword. Kept conservative to avoid grounding
// general-knowledge or personal chit-chat (those add latency without value).

// Turkish letters break JS `\b` word boundaries (ç/ı/ş… are not ASCII word
// chars), so we use Unicode-letter lookarounds instead.
//
// Currency / market / price entities that are volatile by nature. The existing
// WEB_RESEARCH_PATTERNS only catch the literal words "fiyat/kur/price"; users
// usually ask "dolar kaç TL" / "bitcoin ne kadar" without them.
const VOLATILE_MARKET_PATTERN =
  /(?<!\p{L})(dolar|euro|sterlin|avro|usd|eur|gbp|altın|altin|gram altın|gram altin|gümüş|gumus|bitcoin|btc|ethereum|eth|borsa|bist|nasdaq|s&p|hisse|döviz|doviz|enflasyon|faiz)(?!\p{L})/iu;

// "is it out yet / when does it release / was it announced" — availability and
// release-timing questions are inherently fresh facts.
const VOLATILE_RELEASE_PATTERN =
  /(?<!\p{L})(çıktı mı|cikti mi|çıkacak mı|cikacak mi|ne zaman çık|ne zaman cik|yayınlandı mı|yayinlandi mi|piyasaya|vizyon tarihi|release date|çıkış tarihi|cikis tarihi|son sürüm|son surum|en son sürüm|latest version|kaçıncı sürüm|kacinci surum)(?!\p{L})/iu;

// Live events / scores / weather — always fresh.
const VOLATILE_EVENT_PATTERN =
  /(?<!\p{L})(hava durumu|hava nasıl|hava nasil|kaç derece|kac derece|yağmur yağ|yagmur yag|maç sonucu|mac sonucu|skor kaç|skor kac|kim kazandı|kim kazandi|kaç kaç|kac kac|puan durumu|şampiyon oldu|sampiyon oldu|son dakika|seçim sonuc|secim sonuc|deprem oldu|kaç şiddet|kac siddet)(?!\p{L})/iu;

// Quantity questions about external entities: "X kaç TL", "Y ne kadar".
const VOLATILE_QUANTITY_PATTERN = /(?<!\p{L})(kaç|kac|ne kadar)(?!\p{L})/iu;

// Turkish/English factual interrogatives. Combined with a proper-noun entity
// these flag "who/what/when is <NamedEntity>" questions where parametric
// knowledge is most likely outdated or hallucinated.
const FACTUAL_INTERROGATIVE_PATTERN =
  /(?<!\p{L})(kim|kimdir|kimin|nedir|ne demek|ne zaman|nerede|neresi|nereli|hangi|kaç yıl|kac yil|kaç yaşında|kac yasinda|ne iş yap|ne is yap|who is|what is|when (is|was|did)|where is|how many|how much)(?!\p{L})/iu;

// Common Turkish/English sentence-initial words whose capitalisation is NOT a
// proper-noun signal (question words, pronouns, greetings, fillers).
const SENTENCE_INITIAL_STOPWORDS = new Set([
  "bugün", "bugun", "nasıl", "nasil", "neden", "niye", "niçin", "nicin", "hangi",
  "kim", "kimdir", "nedir", "ne", "nerede", "neresi", "nereli", "kaç", "kac",
  "lütfen", "lutfen", "bana", "benim", "ben", "sen", "siz", "biz", "bu", "şu", "su",
  "evet", "hayır", "hayir", "selam", "merhaba", "peki", "acaba", "en", "bir",
  "the", "what", "who", "when", "where", "how", "why", "is", "can", "does", "a", "an",
]);

// Proper-noun detector over the ORIGINAL-case prompt: an all-caps acronym (≥2
// chars), or a capitalised token (incl. sentence-initial unless it is a common
// stopword). Turkish capitals İ Ğ Ü Ş Ö Ç included.
const PROPER_NOUN_TOKEN = /^[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıiöşü0-9'’.]*$/;
const ALLCAPS_ACRONYM = /^[A-ZÇĞİÖŞÜ]{2,}$/;

function hasProperNounEntity(originalPrompt: string): boolean {
  const tokens = originalPrompt.split(/\s+/).filter(Boolean);
  for (let i = 0; i < tokens.length; i += 1) {
    const raw = tokens[i].replace(/^[^A-Za-zÇĞİÖŞÜçğıiöşü0-9]+|[^A-Za-zÇĞİÖŞÜçğıiöşü0-9]+$/g, "");
    if (raw.length < 2) {
      continue;
    }
    if (ALLCAPS_ACRONYM.test(raw)) {
      return true;
    }
    if (!PROPER_NOUN_TOKEN.test(raw) || !/[a-zçğıiöşü]/.test(raw)) {
      continue;
    }
    // Sentence-initial capitalisation is only a signal if it is not a common word.
    if (i === 0 && SENTENCE_INITIAL_STOPWORDS.has(raw.toLocaleLowerCase("tr-TR"))) {
      continue;
    }
    return true;
  }
  return false;
}

/**
 * Detect prompts that need fresh, externally-verifiable facts even when the user
 * did not use an explicit web-research keyword. This is the core anti-hallucination
 * gate: it errs toward grounding volatile facts (prices, releases, live events) and
 * named-entity factual questions, while leaving general knowledge and personal
 * prompts ungrounded.
 */
export function detectFactualityGrounding(prompt: string): {
  triggered: boolean;
  reason: string | null;
} {
  const normalized = compactText(prompt);
  if (!normalized) {
    return { triggered: false, reason: null };
  }
  const lower = normalized.toLocaleLowerCase("tr-TR");
  const isQuestion = normalized.includes("?") || FACTUAL_INTERROGATIVE_PATTERN.test(lower);

  if (VOLATILE_MARKET_PATTERN.test(lower) && (VOLATILE_QUANTITY_PATTERN.test(lower) || isQuestion)) {
    return { triggered: true, reason: "volatile_market_fact" };
  }
  if (VOLATILE_RELEASE_PATTERN.test(lower)) {
    return { triggered: true, reason: "release_or_availability_fact" };
  }
  if (VOLATILE_EVENT_PATTERN.test(lower)) {
    return { triggered: true, reason: "live_event_fact" };
  }
  if (isQuestion && hasProperNounEntity(normalized)) {
    return { triggered: true, reason: "named_entity_factual_question" };
  }
  return { triggered: false, reason: null };
}

const SOURCE_AUTHORITY_HOST_PATTERNS = [
  /\.(gov|edu)(\.[a-z]{2})?$/i,
  /\.go\.tr$/i,
  /\.edu\.tr$/i,
  /(^|\.)who\.int$/i,
  /(^|\.)oecd\.org$/i,
  /(^|\.)worldbank\.org$/i,
  /(^|\.)europa\.eu$/i,
  /(^|\.)apple\.com$/i,
  /(^|\.)developer\.apple\.com$/i,
  /(^|\.)openai\.com$/i,
  /(^|\.)github\.com$/i,
];

const LOW_AUTHORITY_HOST_PATTERNS = [
  /(^|\.)pinterest\./i,
  /(^|\.)facebook\./i,
  /(^|\.)instagram\./i,
  /(^|\.)tiktok\./i,
];

const WEB_QUERY_STOPWORDS = new Set([
  "ve",
  "ile",
  "icin",
  "için",
  "ya",
  "ya da",
  "veya",
  "bir",
  "bu",
  "şu",
  "sunu",
  "bunu",
  "nasıl",
  "nasil",
  "nedir",
  "ne",
  "kim",
  "hangi",
  "neden",
  "niye",
  "nasılsın",
  "naber",
  "araştır",
  "arastir",
  "araştırma",
  "arastirma",
  "özetle",
  "ozetle",
  "incele",
  "compare",
  "benchmark",
  "news",
  "haber",
  "today",
  "latest",
  "recent",
  "resmi",
  "official",
  "kaynak",
  "source",
]);

const WEB_QUERY_MAX_RESULTS = 3;
const webGroundingCache = new WeakMap<FastifyInstance, Map<string, WebGroundingCacheEntry>>();

function createAbortController(): AbortController {
  const controller = new AbortController();
  return controller;
}

function createTimedAbortController(timeoutMs: number): { controller: AbortController; timeout: ReturnType<typeof setTimeout> } {
  const controller = createAbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  return { controller, timeout };
}

function compactText(value: string): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function decodeHtmlEntities(value: string): string {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ");
}

function stripHtml(value: string): string {
  return decodeHtmlEntities(value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
}

function stripQueryNoise(value: string): string {
  return compactText(value)
    .replace(/^[^a-z0-9çğıöşü]+/gi, "")
    .replace(/[^\p{L}\p{N}\s#:+.-]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function hostFromUrl(rawUrl: string): string {
  try {
    return new URL(rawUrl).hostname.replace(/^www\./i, "");
  } catch {
    return "";
  }
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const normalized = compactText(value).toLowerCase();
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    output.push(compactText(value));
  }
  return output;
}

function getWebQueryLimit(workload: SharedBrainWorkload): number {
  switch (workload) {
    case "planning":
      return 3;
    case "mobile_chat_balanced":
      return 2;
    case "mobile_chat_fast":
      return 2;
    case "fast_route":
    case "intent":
      return 1;
    case "desktop_handoff":
      return 1;
  }

  return 2;
}

function getWebVerificationLimit(workload: SharedBrainWorkload): number {
  return workload === "planning" ? 3 : workload === "mobile_chat_balanced" ? 2 : 2;
}

function getWebGroundingCacheTtlMs(workload: SharedBrainWorkload): number {
  switch (workload) {
    case "planning":
      return 45_000;
    case "mobile_chat_balanced":
      return 30_000;
    case "mobile_chat_fast":
      return 20_000;
    case "fast_route":
    case "intent":
      return 15_000;
    case "desktop_handoff":
      return 0;
  }

  return 20_000;
}

function buildWebQueries(prompt: string, limit = WEB_QUERY_MAX_RESULTS): string[] {
  const base = stripQueryNoise(prompt).slice(0, 240);
  const tokens = base
    .split(/\s+/)
    .map((token) => token.replace(/[^\p{L}\p{N}#:+.-]+/gu, ""))
    .filter(Boolean);
  const focused = tokens.filter((token) => {
    const lowered = token.toLowerCase();
    if (token.length <= 2) {
      return false;
    }
    return !WEB_QUERY_STOPWORDS.has(lowered);
  });
  const focusQuery = stripQueryNoise(focused.slice(0, 8).join(" ")).slice(0, 180);
  const condensedQuery = stripQueryNoise(
    tokens
      .filter((token) => {
        const lowered = token.toLowerCase();
        return token.length > 3 && !WEB_QUERY_STOPWORDS.has(lowered);
      })
      .slice(0, 12)
      .join(" "),
  ).slice(0, 200);
  const turkicVariants = buildTurkicWebQueryVariants(base);
  const prioritizeTurkicQueries = isTurkicLanguageResearchPrompt(base);
  const orderedTurkicVariants = prioritizeTurkicQueries ? turkicVariants : [];
  const deferredTurkicVariants = prioritizeTurkicQueries ? [] : turkicVariants;

  return uniqueStrings([base, ...orderedTurkicVariants, focusQuery, condensedQuery, ...deferredTurkicVariants]).slice(
    0,
    Math.max(1, limit),
  );
}

function getWebGroundingCache(app: FastifyInstance): Map<string, WebGroundingCacheEntry> {
  const existing = webGroundingCache.get(app);
  if (existing) {
    return existing;
  }
  const created = new Map<string, WebGroundingCacheEntry>();
  webGroundingCache.set(app, created);
  return created;
}

function buildWebGroundingCacheKey(input: {
  query: string;
  workload: SharedBrainWorkload;
  searchBaseUrl: string;
  maxResults: number;
}): string {
  return JSON.stringify({
    query: compactText(input.query).toLowerCase(),
    workload: input.workload,
    searchBaseUrl: compactText(input.searchBaseUrl).toLowerCase(),
    maxResults: input.maxResults,
  });
}

function cloneWebGroundingResult(input: WebGroundingResult): WebGroundingResult {
  return {
    ...input,
    queries: [...input.queries],
    decisionReasons: [...(input.decisionReasons ?? [])],
    results: input.results.map((result) => ({ ...result })),
  };
}

function normalizeDuckDuckGoHref(rawHref: string): string | null {
  const href = decodeHtmlEntities(rawHref).trim();
  if (!href) {
    return null;
  }
  try {
    const parsed = new URL(href, "https://duckduckgo.com");
    if (parsed.hostname.includes("duckduckgo.com")) {
      const redirected = parsed.searchParams.get("uddg");
      if (redirected) {
        return decodeURIComponent(redirected);
      }
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

async function fetchTextWithTimeout(url: string, timeoutMs: number, headers: Record<string, string> = {}): Promise<Response> {
  const { controller, timeout } = createTimedAbortController(timeoutMs);
  try {
    return await fetch(url, {
      method: "GET",
      signal: controller.signal,
      headers,
    });
  } finally {
    clearTimeout(timeout);
  }
}

function extractMetaContent(html: string, names: string[]): string {
  for (const name of names) {
    const match = html.match(
      new RegExp(
        `<meta[^>]+(?:name|property)=["']${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}["'][^>]+content=["']([^"']+)["']`,
        "i",
      ),
    );
    if (match?.[1]) {
      return stripHtml(match[1]);
    }
  }
  return "";
}

function extractPageTitle(html: string): string {
  const match = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  return stripHtml(match?.[1] ?? "");
}

function extractFirstParagraph(html: string): string {
  const match = html.match(/<p[^>]*>([\s\S]{0,350}?)<\/p>/i);
  return stripHtml(match?.[1] ?? "");
}

async function fetchSearchQuery(
  app: FastifyInstance,
  query: string,
): Promise<{
  query: string;
  results: WebGroundingSearchResult[];
  degradedReason: string | null;
}> {
  const { controller, timeout } = createTimedAbortController(app.config.ELYAN_WEB_GROUNDING_TIMEOUT_MS);
  try {
    const searchUrl = new URL(app.config.ELYAN_WEB_SEARCH_BASE_URL);
    searchUrl.searchParams.set("q", query);
    searchUrl.searchParams.set("kl", "tr-tr");

    const response = await fetch(searchUrl, {
      method: "GET",
      signal: controller.signal,
      headers: {
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
        accept: "text/html,application/xhtml+xml",
      },
    });

    if (!response.ok) {
      return {
        query,
        results: [],
        degradedReason: `web_search_http_${response.status}`,
      };
    }

    const html = await response.text();
    return {
      query,
      results: parseDuckDuckGoHtml({
        html,
        limit: app.config.ELYAN_WEB_GROUNDING_MAX_RESULTS,
      }).map((result) => ({
        ...result,
        sourceHost: hostFromUrl(result.url),
        verificationState: "unverified" as const,
        queryHits: 1,
        score: 1,
      })),
      degradedReason: null,
    };
  } catch (error) {
    return {
      query,
      results: [],
      degradedReason:
        error instanceof Error && error.name === "AbortError"
          ? "web_search_timeout"
          : "web_search_failed",
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function verifyResult(
  app: FastifyInstance,
  input: WebGroundingSearchResult,
): Promise<WebGroundingSearchResult> {
  const verificationTimeoutMs = Math.max(1200, Math.min(app.config.ELYAN_WEB_GROUNDING_TIMEOUT_MS, 2500));
  try {
    const response = await fetchTextWithTimeout(
      input.url,
      verificationTimeoutMs,
      {
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
        accept: "text/html,application/xhtml+xml",
      },
    );

    if (!response.ok) {
      return {
        ...input,
        verificationState: "unverified",
        score: input.score - 0.2,
      };
    }

    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().includes("text/html") && !contentType.toLowerCase().includes("application/xhtml+xml")) {
      return {
        ...input,
        verificationState: "partial",
        score: input.score - 0.05,
      };
    }

    const html = await response.text();
    const fetchedTitle = extractPageTitle(html);
    const fetchedDescription = extractMetaContent(html, ["description", "og:description"]);
    const fetchedParagraph = extractFirstParagraph(html);
    const verifiedSnippet = fetchedDescription || fetchedParagraph || input.snippet;
    const verificationState =
      fetchedTitle || fetchedDescription ? "verified" : input.snippet ? "partial" : "unverified";
    const title = fetchedTitle || input.title;
    const snippet = verifiedSnippet || input.snippet;
    const queryMatchBoost =
      [title, snippet]
        .join(" ")
        .toLowerCase()
        .includes(input.title.toLowerCase())
        ? 0.15
        : 0;

    return {
      ...input,
      title,
      snippet,
      verificationState,
      score:
        input.score +
        (verificationState === "verified" ? 0.35 : verificationState === "partial" ? 0.12 : 0) +
        queryMatchBoost,
    };
  } catch {
    return {
      ...input,
      verificationState: input.snippet ? "partial" : "unverified",
      score: input.score - 0.15,
    };
  }
}

function scoreResult(input: WebGroundingSearchResult): number {
  const verificationBoost =
    input.verificationState === "verified" ? 0.35 : input.verificationState === "partial" ? 0.12 : 0;
  const queryHitBoost = Math.min(input.queryHits, 3) * 0.22;
  const snippetBoost = input.snippet ? 0.08 : 0;
  const authorityBoost = SOURCE_AUTHORITY_HOST_PATTERNS.some((pattern) => pattern.test(input.sourceHost)) ? 0.16 : 0;
  const lowAuthorityPenalty = LOW_AUTHORITY_HOST_PATTERNS.some((pattern) => pattern.test(input.sourceHost)) ? -0.22 : 0;
  return Number((input.score + verificationBoost + queryHitBoost + snippetBoost + authorityBoost + lowAuthorityPenalty).toFixed(4));
}

function confidenceFromResults(results: WebGroundingSearchResult[]): "high" | "medium" | "low" {
  if (!results.length) {
    return "low";
  }

  const top = results[0];
  if (top?.verificationState === "verified" && top.score >= 1.25) {
    return "high";
  }
  if (results.some((result) => result.verificationState === "verified") || top?.score >= 0.9) {
    return "medium";
  }
  return "low";
}

export function shouldUseWebGrounding(input: {
  prompt: string;
  workload: SharedBrainWorkload;
}): boolean {
  const normalized = compactText(input.prompt);
  if (!normalized) {
    return false;
  }
  const lower = normalized.toLocaleLowerCase("tr-TR");
  const explicitWebIntent = EXPLICIT_WEB_PATTERNS.some((pattern) => pattern.test(lower));
  const researchIntent = WEB_RESEARCH_PATTERNS.some((pattern) => pattern.test(lower));
  const personalOnlyIntent = PERSONAL_ONLY_PATTERNS.some((pattern) => pattern.test(lower)) && !explicitWebIntent;
  if (personalOnlyIntent && !researchIntent) {
    return false;
  }
  if (explicitWebIntent || researchIntent || isTurkicLanguageResearchPrompt(normalized)) {
    return true;
  }
  // Anti-hallucination gate: fresh/volatile or named-entity factual questions
  // get grounded even without an explicit research keyword (unless personal-only).
  if (!personalOnlyIntent && detectFactualityGrounding(normalized).triggered) {
    return true;
  }
  if (input.workload === "planning" && !personalOnlyIntent) {
    return true;
  }
  return false;
}

function webGroundingDecisionReasons(input: {
  prompt: string;
  workload: SharedBrainWorkload;
}): string[] {
  const normalized = compactText(input.prompt);
  if (!normalized) {
    return [];
  }
  const lower = normalized.toLocaleLowerCase("tr-TR");
  const reasons: string[] = [];
  if (EXPLICIT_WEB_PATTERNS.some((pattern) => pattern.test(lower))) {
    reasons.push("explicit_web_request");
  }
  if (WEB_RESEARCH_PATTERNS.some((pattern) => pattern.test(lower))) {
    reasons.push("external_or_fresh_fact_request");
  }
  if (isTurkicLanguageResearchPrompt(normalized)) {
    reasons.push("turkic_research_request");
  }
  const personalOnly =
    PERSONAL_ONLY_PATTERNS.some((pattern) => pattern.test(lower)) &&
    !EXPLICIT_WEB_PATTERNS.some((pattern) => pattern.test(lower));
  if (!personalOnly) {
    const factuality = detectFactualityGrounding(normalized);
    if (factuality.triggered && factuality.reason) {
      reasons.push(factuality.reason);
    }
  }
  if (input.workload === "planning" && reasons.length === 0) {
    reasons.push("planning_workload_context_check");
  }
  return uniqueStrings(reasons);
}

export function parseDuckDuckGoHtml(input: {
  html: string;
  limit: number;
}): WebGroundingSearchResult[] {
  const matches = [...input.html.matchAll(/<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi)];
  const results: WebGroundingSearchResult[] = [];

  for (const match of matches) {
    if (results.length >= input.limit) {
      break;
    }
    const href = normalizeDuckDuckGoHref(match[1] ?? "");
    const title = stripHtml(match[2] ?? "");
    if (!href || !title) {
      continue;
    }
    const startIndex = match.index ?? 0;
    const block = input.html.slice(startIndex, startIndex + 1800);
    const snippetMatch =
      block.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/(?:a|div)>/i) ??
      block.match(/class="result-snippet"[^>]*>([\s\S]*?)<\/td>/i);
    const snippet = stripHtml(snippetMatch?.[1] ?? "");
    results.push({
      title,
      url: href,
      snippet,
      sourceHost: hostFromUrl(href),
      verificationState: "unverified",
      queryHits: 1,
      score: 1,
    });
  }

  return results;
}

export async function searchPublicWebGrounding(
  app: FastifyInstance,
  input: {
    prompt: string;
    workload: SharedBrainWorkload;
  },
): Promise<WebGroundingResult> {
  const query = compactText(input.prompt).slice(0, 320);
  const decisionReasons = webGroundingDecisionReasons(input);
  if (!app.config.ELYAN_WEB_GROUNDING_ENABLED || !query || !shouldUseWebGrounding(input)) {
    return {
      enabled: app.config.ELYAN_WEB_GROUNDING_ENABLED,
      used: false,
      query,
      queries: [],
      source: "duckduckgo_html",
      results: [],
      degradedReason: null,
      confidence: "low",
      retrievedAt: new Date().toISOString(),
      decisionReasons,
    };
  }

  const cacheTtlMs = getWebGroundingCacheTtlMs(input.workload);
  const cacheKey = buildWebGroundingCacheKey({
    query,
    workload: input.workload,
    searchBaseUrl: String(app.config.ELYAN_WEB_SEARCH_BASE_URL ?? ""),
    maxResults: Number(app.config.ELYAN_WEB_GROUNDING_MAX_RESULTS ?? WEB_QUERY_MAX_RESULTS),
  });
  const cache = cacheTtlMs > 0 ? getWebGroundingCache(app) : null;
  const cached = cache?.get(cacheKey);
  if (cached && cached.expiresAt > Date.now()) {
    return cloneWebGroundingResult(await cached.value);
  }

  const run = (async () => {
    try {
      const queries = buildWebQueries(query, getWebQueryLimit(input.workload));
      const searchRuns = await Promise.allSettled(queries.map((candidate) => fetchSearchQuery(app, candidate)));
      const degradedReasons: string[] = [];
      const merged = new Map<string, WebGroundingSearchResult>();

      for (const run of searchRuns) {
        if (run.status === "rejected") {
          degradedReasons.push("web_search_failed");
          continue;
        }

        if (run.value.degradedReason) {
          degradedReasons.push(run.value.degradedReason);
        }

        for (const result of run.value.results) {
          const key = result.url.toLowerCase();
          const current = merged.get(key);
          if (!current) {
            merged.set(key, { ...result, queryHits: 1, score: scoreResult(result) });
            continue;
          }

          const updated: WebGroundingSearchResult = {
            ...current,
            title: current.title.length >= result.title.length ? current.title : result.title,
            snippet: current.snippet.length >= result.snippet.length ? current.snippet : result.snippet,
            queryHits: current.queryHits + 1,
            verificationState:
              current.verificationState === "verified" || result.verificationState === "verified"
                ? "verified"
                : current.verificationState === "partial" || result.verificationState === "partial"
                  ? "partial"
                  : "unverified",
            score: Math.max(current.score, result.score),
          };
          merged.set(key, {
            ...updated,
            score: scoreResult(updated),
          });
        }
      }

      const mergedResults = [...merged.values()].sort((left, right) => scoreResult(right) - scoreResult(left));
      const verifiedCandidates = mergedResults.slice(0, getWebVerificationLimit(input.workload));
      const verifiedResults = await Promise.allSettled(verifiedCandidates.map((result) => verifyResult(app, result)));
      for (let index = 0; index < verifiedCandidates.length; index += 1) {
        const settled = verifiedResults[index];
        if (settled?.status === "fulfilled") {
          const next = settled.value;
          merged.set(next.url.toLowerCase(), { ...next, score: scoreResult(next) });
        }
      }

      const finalResults = [...merged.values()]
        .map((result) => ({ ...result, score: scoreResult(result) }))
        .sort((left, right) => right.score - left.score)
        .slice(0, app.config.ELYAN_WEB_GROUNDING_MAX_RESULTS);
      const used = finalResults.length > 0;
      const confidence = confidenceFromResults(finalResults);

      const result: WebGroundingResult = {
        enabled: true,
        used,
        query,
        queries: buildWebQueries(query, getWebQueryLimit(input.workload)),
        source: "duckduckgo_html",
        results: finalResults,
        degradedReason: used ? (degradedReasons.length > 0 ? uniqueStrings(degradedReasons).join(",") : null) : "web_search_no_results",
        confidence,
        retrievedAt: new Date().toISOString(),
        decisionReasons,
      };
      return result;
    } catch (error) {
      const result: WebGroundingResult = {
        enabled: true,
        used: false,
        query,
        queries: buildWebQueries(query, getWebQueryLimit(input.workload)),
        source: "duckduckgo_html",
        results: [],
        degradedReason:
          error instanceof Error && error.name === "AbortError"
            ? "web_search_timeout"
            : "web_search_failed",
        confidence: "low",
        retrievedAt: new Date().toISOString(),
        decisionReasons,
      };
      return result;
    }
  })();

  if (cache && cacheTtlMs > 0) {
    cache.set(cacheKey, {
      expiresAt: Date.now() + cacheTtlMs,
      value: run,
    });
  }

  const result = await run;
  if (cache && cacheTtlMs > 0) {
    cache.set(cacheKey, {
      expiresAt: Date.now() + cacheTtlMs,
      value: result,
    });
  }

  return cloneWebGroundingResult(result);
}

export function buildWebGroundingPromptBlock(input: WebGroundingResult): string | null {
  if (!input.used || input.results.length === 0) {
    return null;
  }
  return [
    "PUBLIC WEB GROUNDING",
    `Query: ${input.query}`,
    input.queries.length > 1 ? `Queries used: ${input.queries.join(" | ")}` : null,
    input.retrievedAt ? `Retrieved at: ${input.retrievedAt}` : null,
    input.decisionReasons?.length ? `Research reasons: ${input.decisionReasons.join(", ")}` : null,
    `Grounding confidence: ${input.confidence}`,
    input.degradedReason ? `Grounding note: ${input.degradedReason}` : null,
    ...input.results.map(
      (result, index) =>
        `${index + 1}. [${result.verificationState}] ${result.title} (${result.sourceHost || hostFromUrl(result.url)})\nURL: ${result.url}\nSnippet: ${result.snippet || "No snippet provided."}\nQuery hits: ${result.queryHits}`,
    ),
    "Use these public web results only when they help. If they conflict or seem weak, say so briefly instead of overstating certainty.",
    "When the answer depends on web results, synthesize the findings and include a short source basis using source names or URLs; do not dump unrelated links.",
    "Do not let public web results override established project identity or memory facts about Elyan itself.",
  ].join("\n");
}

/**
 * When web grounding was attempted for a fresh/volatile/factual prompt but
 * produced no usable results (timeout, failure, or empty), return an explicit
 * abstention instruction so the model says it could not verify instead of
 * fabricating figures, dates, prices, versions, names, or current events.
 * Returns null when grounding was never attempted (ordinary chat) or when
 * usable results exist (the normal grounding block handles that case).
 */
export function buildWebGroundingAbstentionBlock(input: WebGroundingResult): string | null {
  if (!input.enabled) {
    return null;
  }
  const attempted = (input.decisionReasons?.length ?? 0) > 0 || input.degradedReason != null;
  const hasUsableResults = input.used && input.results.length > 0;
  if (!attempted || hasUsableResults) {
    return null;
  }
  return [
    "WEB VERIFICATION UNAVAILABLE",
    input.degradedReason
      ? `Note: ${input.degradedReason}`
      : "Note: no usable public web results were found.",
    "This question depends on fresh or externally-verifiable facts that could not be verified just now.",
    "Do not fabricate specific figures, prices, exchange rates, dates, version numbers, names, scores, or current events.",
    "State plainly that you could not verify up-to-date information, share only what is reliably stable, and suggest the user retry or check an authoritative source.",
    "Answer in the user's language.",
  ].join("\n");
}
