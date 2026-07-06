import type { FastifyInstance } from "fastify";
import {
  isCircuitCallAllowed,
  recordCircuitFailure,
  recordCircuitSuccess,
} from "../../lib/reliability/circuit-breaker.js";
import type { SharedBrainWorkload } from "./workloads.js";
import {
  buildTurkicWebQueryVariants,
  isTurkicLanguageResearchPrompt,
} from "../../core/understanding/turkic-language.js";
import { Readability } from "@mozilla/readability";
import { parseHTML } from "linkedom";
import { LRUCache } from "lru-cache";
import { nlpDaemon } from "../../lib/nlp-daemon.js";

export type WebGroundingSearchResult = {
  title: string;
  url: string;
  snippet: string;
  sourceHost: string;
  verificationState: "verified" | "partial" | "unverified";
  queryHits: number;
  score: number;
  pageContent?: string;
};

export type WebGroundingResult = {
  enabled: boolean;
  used: boolean;
  query: string;
  queries: string[];
  source: "duckduckgo_html" | "brave" | "searxng";
  results: WebGroundingSearchResult[];
  degradedReason: string | null;
  confidence: "high" | "medium" | "low";
  retrievedAt?: string;
  decisionReasons?: string[];
};

const WEB_RESEARCH_PATTERNS = [
  /\b(internet|web|online|çevrim içi|cevrim ici|internetten|webden)\b/i,
  /\b(araştır|arastir|araştırma|arastirma|research)\b/i,
  /\b(güncel|guncel|latest|recent|son durum|bugün|today|news|haber)\b/i,
  /\b(karşılaştır|karsilastir|compare|benchmark|farkı|farki|difference|artı eksi|arti eksi|avantaj|dezavantaj|pros|cons)\b/i,
  /\b(resmi|official|dokümantasyon|documentation|kaynak|source)\b/i,
  /\b(fiyat|price|kur|rate|release note|release notes?|changelog|son sürüm|son surum|duyuru|announcement)\b/i,
  /\b(veri|veriler|data|istatistik|istatistikler|statistics?|rapor|report|anket|survey|trend|piyasa|market)\b/i,
  /\b(yasa|kanun|mevzuat|regulation|legal|uyumluluk|compliance|standart|standard|kılavuz|kilavuz|guideline)\b/i,
  /\b(dil|lehçe|lehce|gramer|grammar|etimoloji|etymology|alfabe|alphabet|çeviri|ceviri|transliteration|kelime hazinesi|söz varlığı|soz varligi)\b/i,
  /\b(türk dünyası|turkic|oğuz|oguz|kıpçak|kipchak|karluk|qipchak|qarluq|azerbaijani|kazakh|kyrgyz|uzbek|turkmen|uyghur|tatar|bashkir|gagauz|karakalpak|sakha|chuvash)\b/i,
  /\b(tarih|tarihsel|historical|olaylar|events|kronoloji|chronolog|tarihçe|tarihce)\b/i,
  /\b(nüfus|nufus|population|gdp|gsyih|gsyh|büyüme|buyume|growth|ekonomi|economy|ihracat|ithalat|export|import)\b/i,
  /\b(film|dizi|series|yönetmen|yonetmen|oyuncu|actor|imdb|rotten|metacritic|vizyonda|gösterimde|gosterimde)\b/i,
  /\b(api|sdk|framework|library|kütüphane|kutuphane|paket|package|npm|pip|pub\.dev|crate|gem)\b/i,
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

// Live events / scores / weather / politics / science — always fresh.
const VOLATILE_EVENT_PATTERN =
  /(?<!\p{L})(hava durumu|hava nasıl|hava nasil|kaç derece|kac derece|yağmur yağ|yagmur yag|maç sonucu|mac sonucu|skor kaç|skor kac|kim kazandı|kim kazandi|kaç kaç|kac kac|puan durumu|şampiyon oldu|sampiyon oldu|son dakika|seçim sonuc|secim sonuc|deprem oldu|kaç şiddet|kac siddet|cumhurbaşkan|baskan|başbakan|basbakan|bakan oldu|atandı|atandi|istifa|görevden|gorevden|savaş|savas|ateşkes|ateskes|çatışma|catisma|olimpiyat|dünya kupası|dunya kupasi|şampiyonlar ligi|sampiyonlar ligi|formula 1|f1 yarış|nobel|ödül kazandı|odul kazandi)(?!\p{L})/iu;

// Quantity questions about external entities: "X kaç TL", "Y ne kadar".
const VOLATILE_QUANTITY_PATTERN = /(?<!\p{L})(kaç|kac|ne kadar)(?!\p{L})/iu;

// Technology/science questions that need current facts (frameworks, languages, tools, specs).
const VOLATILE_TECH_PATTERN =
  /(?<!\p{L})(son sürüm|son surum|latest version|yeni özellik|yeni ozellik|new feature|deprecated|kullanımdan kaldır|kullanimdan kaldir|end of life|eol|lts|stable release|beta|alpha|roadmap|breaking change|migration guide|güncelleme|guncelleme|update|upgrade|patch|security fix|vulnerability|cve|zero.?day)(?!\p{L})/iu;

// "How to" / tutorial / best practice questions — often need current best practices.
const VOLATILE_HOWTO_PATTERN =
  /(?<!\p{L})(en iyi yöntem|en iyi yontem|best practice|önerilen|onerilen|recommended|nasıl yapılır|nasil yapilir|how to|step by step|adım adım|adim adim|rehber|guide|tutorial|örnek|ornek|example)(?!\p{L})/iu;

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
  // Sayı kelimeleri: "İki sayının toplamı 10..." gibi saf matematik sorularında
  // cümle başı büyük harf özel-isim sinyali sayılıp gereksiz web grounding
  // tetikliyordu (benchmark math-003: required_web_but_should_not).
  "iki", "üç", "uc", "dört", "dort", "beş", "bes", "altı", "alti", "yedi",
  "sekiz", "dokuz", "on", "yüz", "yuz", "bin", "sıfır", "sifir",
  "the", "what", "who", "when", "where", "how", "why", "is", "can", "does", "a", "an",
  "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
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
  if (VOLATILE_TECH_PATTERN.test(lower) && (isQuestion || hasProperNounEntity(normalized))) {
    return { triggered: true, reason: "technology_freshness_fact" };
  }
  if (isQuestion && hasProperNounEntity(normalized)) {
    return { triggered: true, reason: "named_entity_factual_question" };
  }
  if (VOLATILE_HOWTO_PATTERN.test(lower) && hasProperNounEntity(normalized)) {
    return { triggered: true, reason: "howto_with_named_entity" };
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
const webGroundingCache = new WeakMap<
  FastifyInstance,
  LRUCache<string, WebGroundingResult | Promise<WebGroundingResult>>
>();

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

function getWebGroundingCache(
  app: FastifyInstance,
): LRUCache<string, WebGroundingResult | Promise<WebGroundingResult>> {
  const existing = webGroundingCache.get(app);
  if (existing) {
    return existing;
  }
  /* max 200 unique queries, TTL set per-entry at write time */
  const created = new LRUCache<string, WebGroundingResult | Promise<WebGroundingResult>>({
    max: 200,
    ttlAutopurge: false,
  });
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

function extractMainContent(html: string, maxChars = 700): string {
  try {
    const { document } = parseHTML(html);
    const article = new Readability(document as unknown as Document).parse();
    if (article?.textContent) {
      return article.textContent.replace(/\s{2,}/g, " ").trim().slice(0, maxChars);
    }
  } catch {
    /* fall through to regex fallback */
  }

  /* Regex fallback when Readability cannot parse (e.g. fragment HTML) */
  const cleaned = html
    .replace(/<(script|style|nav|header|footer|aside|form|button|input|select|textarea)[^>]*>[\s\S]*?<\/\1>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ");
  const parts: string[] = [];
  const tagRe = /<(p|li|h[1-3]|td)[^>]*>([\s\S]{1,400}?)<\/\1>/gi;
  let match: RegExpExecArray | null;
  let total = 0;
  while ((match = tagRe.exec(cleaned)) !== null && total < maxChars) {
    const text = stripHtml(match[2] ?? "").trim();
    if (text.length < 20) continue;
    parts.push(text);
    total += text.length + 1;
  }
  return parts.join(" ").slice(0, maxChars).trim();
}

/* ════════════════════════════════════════════════════════════════════════
 * Brave Search API provider
 * Docs: https://api.search.brave.com/app/documentation/web-search/get-started
 * Free tier: 2 000 req/month, 1 req/s
 * ════════════════════════════════════════════════════════════════════════ */

type BraveWebResult = {
  title?: string;
  url?: string;
  description?: string;
  page_age?: string;
  extra_snippets?: string[];
};

async function fetchBraveSearchQuery(
  app: FastifyInstance,
  query: string,
): Promise<{
  query: string;
  results: WebGroundingSearchResult[];
  degradedReason: string | null;
}> {
  const apiKey = app.config.BRAVE_SEARCH_API_KEY;
  if (!apiKey) {
    return { query, results: [], degradedReason: "brave_api_key_missing" };
  }

  const url = new URL("https://api.search.brave.com/res/v1/web/search");
  url.searchParams.set("q", query);
  url.searchParams.set("count", String(Math.min(app.config.ELYAN_WEB_GROUNDING_MAX_RESULTS + 2, 10)));
  url.searchParams.set("country", "TR");
  url.searchParams.set("search_lang", "tr");
  url.searchParams.set("safesearch", "moderate");
  url.searchParams.set("extra_snippets", "true");

  const { controller, timeout } = createTimedAbortController(app.config.ELYAN_WEB_GROUNDING_TIMEOUT_MS);
  try {
    const response = await fetch(url.toString(), {
      method: "GET",
      signal: controller.signal,
      headers: {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": apiKey,
      },
    });

    if (!response.ok) {
      return { query, results: [], degradedReason: `brave_http_${response.status}` };
    }

    const json = await response.json() as { web?: { results?: BraveWebResult[] } };
    const raw = json?.web?.results ?? [];

    const results: WebGroundingSearchResult[] = raw
      .filter((r): r is BraveWebResult & { url: string; title: string } => Boolean(r.url && r.title))
      .map((r) => {
        const snippet = [r.description, ...(r.extra_snippets ?? [])].filter(Boolean).join(" ").slice(0, 350);
        return {
          title: r.title,
          url: r.url,
          snippet,
          sourceHost: hostFromUrl(r.url),
          verificationState: "partial" as const,
          queryHits: 1,
          score: 1.1,
        };
      });

    return { query, results, degradedReason: results.length === 0 ? "brave_no_results" : null };
  } catch (error) {
    return {
      query,
      results: [],
      degradedReason:
        error instanceof Error && error.name === "AbortError"
          ? "brave_timeout"
          : "brave_failed",
    };
  } finally {
    clearTimeout(timeout);
  }
}

/* ════════════════════════════════════════════════════════════════════════
 * SearXNG provider — self-hosted meta search (free, no rate limits)
 * Aggregates: Google, Bing, DuckDuckGo, Brave, Yahoo, Wikipedia + more
 * API: GET /search?q=...&format=json&language=tr-TR&categories=general
 * ════════════════════════════════════════════════════════════════════════ */

type SearXNGResult = {
  title?: string;
  url?: string;
  content?: string;
  score?: number;
  engine?: string;
  engines?: string[];
  category?: string;
};

async function fetchSearXNGQuery(
  app: FastifyInstance,
  query: string,
): Promise<{
  query: string;
  results: WebGroundingSearchResult[];
  degradedReason: string | null;
}> {
  const baseUrl = app.config.SEARXNG_BASE_URL;
  if (!baseUrl) {
    return { query, results: [], degradedReason: "searxng_not_configured" };
  }

  /* Strip stopwords for a cleaner, more signal-rich SearXNG query */
  const cleanedQuery = nlpDaemon.isAvailable()
    ? await nlpDaemon.cleanSearchQuery(query).catch(() => query)
    : query;

  const url = new URL(`${baseUrl}/search`);
  url.searchParams.set("q", cleanedQuery);
  url.searchParams.set("format", "json");
  url.searchParams.set("language", "tr-TR");
  url.searchParams.set("categories", "general");
  url.searchParams.set("engines", "google,bing,duckduckgo,brave,yahoo,wikipedia");
  url.searchParams.set("pageno", "1");

  const { controller, timeout } = createTimedAbortController(app.config.ELYAN_WEB_GROUNDING_TIMEOUT_MS);
  try {
    const response = await fetch(url.toString(), {
      method: "GET",
      signal: controller.signal,
      headers: {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
      },
    });

    if (!response.ok) {
      return { query, results: [], degradedReason: `searxng_http_${response.status}` };
    }

    const json = await response.json() as { results?: SearXNGResult[] };
    const raw = json?.results ?? [];

    const results: WebGroundingSearchResult[] = raw
      .filter((r): r is SearXNGResult & { url: string; title: string } => Boolean(r.url && r.title))
      .slice(0, app.config.ELYAN_WEB_GROUNDING_MAX_RESULTS + 2)
      .map((r) => {
        /* SearXNG score: higher = better; normalize to 0-1 range */
        const engineCount = (r.engines ?? (r.engine ? [r.engine] : [])).length;
        const rawScore = typeof r.score === "number" ? r.score : 1;
        const normalizedScore = Math.min(1 + rawScore * 0.1 + engineCount * 0.15, 2.5);
        return {
          title: r.title,
          url: r.url,
          snippet: (r.content ?? "").slice(0, 350),
          sourceHost: hostFromUrl(r.url),
          verificationState: "partial" as const,
          queryHits: engineCount || 1,
          score: normalizedScore,
        };
      });

    return {
      query,
      results,
      degradedReason: results.length === 0 ? "searxng_no_results" : null,
    };
  } catch (error) {
    return {
      query,
      results: [],
      degradedReason:
        error instanceof Error && error.name === "AbortError"
          ? "searxng_timeout"
          : "searxng_failed",
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchSearchQuery(
  app: FastifyInstance,
  query: string,
): Promise<{
  query: string;
  results: WebGroundingSearchResult[];
  degradedReason: string | null;
}> {
  /* SearXNG: self-hosted meta search, free and most capable */
  if (app.config.ELYAN_SEARCH_PROVIDER === "searxng" && app.config.SEARXNG_BASE_URL) {
    return fetchSearXNGQuery(app, query);
  }

  /* Route to Brave when configured and API key is present */
  if (app.config.ELYAN_SEARCH_PROVIDER === "brave" && app.config.BRAVE_SEARCH_API_KEY) {
    return fetchBraveSearchQuery(app, query);
  }

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
  /* When Jina Reader is enabled, use it for clean markdown content */
  if (app.config.JINA_READER_ENABLED) {
    return verifyResultViaJina(app, input);
  }
  return verifyResultViaHtml(app, input);
}

async function verifyResultViaJina(
  app: FastifyInstance,
  input: WebGroundingSearchResult,
): Promise<WebGroundingSearchResult> {
  const jinaUrl = `https://r.jina.ai/${input.url}`;
  const timeoutMs = Math.max(3000, Math.min(app.config.ELYAN_WEB_GROUNDING_TIMEOUT_MS, 7000));
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(jinaUrl, {
      method: "GET",
      signal: controller.signal,
      headers: {
        "Accept": "text/plain,text/markdown",
        "X-Return-Format": "markdown",
        "User-Agent": "Mozilla/5.0 (compatible; ElyanBot/1.0)",
      },
    });

    if (!response.ok) {
      return { ...input, verificationState: "partial", score: input.score - 0.05 };
    }

    const text = await response.text();
    const titleMatch = text.match(/^Title:\s*(.+)$/m);
    const jinaTitle = titleMatch?.[1]?.trim() || "";
    const contentStart = text.indexOf("\n\n");
    const raw = contentStart >= 0 ? text.slice(contentStart + 2) : text;
    const pageContent = raw.replace(/\n{3,}/g, "\n\n").trim().slice(0, 700) || undefined;

    const title = jinaTitle || input.title;
    const queryMatchBoost = title.toLowerCase().includes(input.title.slice(0, 20).toLowerCase()) ? 0.12 : 0;

    return {
      ...input,
      title,
      pageContent,
      verificationState: pageContent ? "verified" : "partial",
      score: input.score + (pageContent ? 0.35 : 0.1) + queryMatchBoost,
    };
  } catch {
    return { ...input, verificationState: "partial", score: input.score - 0.1 };
  } finally {
    clearTimeout(timer);
  }
}

async function verifyResultViaHtml(
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
    const pageContent = extractMainContent(html, 700);
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
      pageContent: pageContent || undefined,
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

/* ── Web grounding circuit breaker ───────────────────────────────────────
 * Arama sağlayıcısı (SearXNG/Brave/DDG) çöktüğünde her chat isteği timeout
 * süresi kadar bekleyip başarısız oluyordu. Devre açıkken arama hiç denenmez;
 * istek anında degrade olur ve abstention bloğu devreye girer. */

const WEB_GROUNDING_CIRCUIT_KEY = "circuit:external:web_grounding";

function getReliabilityStore(app: FastifyInstance) {
  return app.services?.reliability?.store ?? null;
}

async function isWebGroundingCircuitOpen(app: FastifyInstance): Promise<boolean> {
  const store = getReliabilityStore(app);
  if (!store) {
    return false;
  }
  try {
    return !(await isCircuitCallAllowed(store, WEB_GROUNDING_CIRCUIT_KEY));
  } catch {
    return false;
  }
}

const PROVIDER_FAILURE_REASON_PATTERN =
  /timeout|failed|http_5\d{2}|http_429|unavailable/i;

async function reportWebGroundingCircuitOutcome(
  app: FastifyInstance,
  outcome: { hadUsableResults: boolean; degradedReasons: string[] },
): Promise<void> {
  const store = getReliabilityStore(app);
  if (!store) {
    return;
  }
  const openMs = Number(app.config.BRAIN_CIRCUIT_OPEN_MS ?? 30_000);
  try {
    if (outcome.hadUsableResults) {
      await recordCircuitSuccess(store, WEB_GROUNDING_CIRCUIT_KEY, openMs);
      return;
    }
    // "Sonuç yok" sağlayıcı arızası değildir; yalnız ağ/timeout/5xx tarzı
    // arızalarda devreyi besle.
    const providerFailure =
      outcome.degradedReasons.length > 0 &&
      outcome.degradedReasons.every((reason) => PROVIDER_FAILURE_REASON_PATTERN.test(reason));
    if (providerFailure) {
      await recordCircuitFailure(
        store,
        WEB_GROUNDING_CIRCUIT_KEY,
        {
          failureThreshold: Number(app.config.BRAIN_CIRCUIT_FAILURE_THRESHOLD ?? 3),
          openMs,
        },
        "web_search_provider_failure",
      );
    }
  } catch {
    /* devre kaydı hiçbir zaman ana akışı düşürmesin */
  }
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
  const searchSource =
    app.config.ELYAN_SEARCH_PROVIDER === "searxng" && app.config.SEARXNG_BASE_URL
      ? "searxng" as const
      : app.config.ELYAN_SEARCH_PROVIDER === "brave" && app.config.BRAVE_SEARCH_API_KEY
        ? "brave" as const
        : "duckduckgo_html" as const;
  if (!app.config.ELYAN_WEB_GROUNDING_ENABLED || !query || !shouldUseWebGrounding(input)) {
    return {
      enabled: app.config.ELYAN_WEB_GROUNDING_ENABLED,
      used: false,
      query,
      queries: [],
      source: searchSource,
      results: [],
      degradedReason: null,
      confidence: "low",
      retrievedAt: new Date().toISOString(),
      decisionReasons,
    };
  }

  if (await isWebGroundingCircuitOpen(app)) {
    return {
      enabled: true,
      used: false,
      query,
      queries: [],
      source: searchSource,
      results: [],
      degradedReason: "web_grounding_circuit_open",
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
  if (cached !== undefined) {
    return cloneWebGroundingResult(await cached);
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
      void reportWebGroundingCircuitOutcome(app, {
        hadUsableResults: used,
        degradedReasons: uniqueStrings(degradedReasons),
      });

      const result: WebGroundingResult = {
        enabled: true,
        used,
        query,
        queries: buildWebQueries(query, getWebQueryLimit(input.workload)),
        source: searchSource,
        results: finalResults,
        degradedReason: used ? (degradedReasons.length > 0 ? uniqueStrings(degradedReasons).join(",") : null) : "web_search_no_results",
        confidence,
        retrievedAt: new Date().toISOString(),
        decisionReasons,
      };
      return result;
    } catch (error) {
      void reportWebGroundingCircuitOutcome(app, {
        hadUsableResults: false,
        degradedReasons: [
          error instanceof Error && error.name === "AbortError"
            ? "web_search_timeout"
            : "web_search_failed",
        ],
      });
      const result: WebGroundingResult = {
        enabled: true,
        used: false,
        query,
        queries: buildWebQueries(query, getWebQueryLimit(input.workload)),
        source: searchSource,
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
    cache.set(cacheKey, run, { ttl: cacheTtlMs });
  }

  const result = await run;
  if (cache && cacheTtlMs > 0) {
    cache.set(cacheKey, result, { ttl: cacheTtlMs });
  }

  return cloneWebGroundingResult(result);
}

/* ════════════════════════════════════════════════════════════════════════
 * Structured numeric evidence extraction
 *
 * Grounding snippets often carry no usable numeric series (e.g. a gold-price
 * question returns "grafiği şurada bulabilirsiniz" link farms). The model then
 * either fabricates chart values or emits an empty chart. This layer parses
 * number/date pairs out of the snippets + verified page content so the prompt
 * can carry REAL values — and when none exist, an explicit "no data, do not
 * chart" signal instead.
 * ════════════════════════════════════════════════════════════════════════ */

export type GroundedNumericPoint = {
  value: number;
  unit: string | null;
  date: string | null;
  context: string;
  sourceHost: string;
};

export type GroundedNumericEvidence = {
  points: GroundedNumericPoint[];
  hasNumericFacts: boolean;
  /** ≥2 points sharing a unit (or ≥2 dated points) — enough for a chart/table. */
  hasChartableSeries: boolean;
};

const MAX_NUMERIC_POINTS_TOTAL = 16;
const MAX_NUMERIC_POINTS_PER_RESULT = 6;

const NUMERIC_UNIT_ALIASES: Array<[RegExp, string]> = [
  [/^(₺|tl|try|lira)$/i, "TL"],
  [/^(\$|usd|dolar|dollar)$/i, "USD"],
  [/^(€|eur|euro|avro)$/i, "EUR"],
  [/^(£|gbp|sterlin|pound)$/i, "GBP"],
  [/^%$/, "%"],
  [/^(puan|bp)$/i, "puan"],
];

function normalizeNumericUnit(raw: string | undefined): string | null {
  const value = String(raw ?? "").trim();
  if (!value) {
    return null;
  }
  for (const [pattern, unit] of NUMERIC_UNIT_ALIASES) {
    if (pattern.test(value)) {
      return unit;
    }
  }
  return value.toLocaleLowerCase("tr-TR");
}

/**
 * Parses localized number strings: "4.250,75" (TR), "4,250.75" (EN),
 * "4250.75", "4,25" (TR decimal), "4.250" (thousands). Returns null when the
 * shape is not a clean number.
 */
export function parseLocalizedNumber(raw: string): number | null {
  const compact = String(raw ?? "").replace(/\s+/g, "");
  if (!compact || !/^\d/.test(compact)) {
    return null;
  }
  const hasDot = compact.includes(".");
  const hasComma = compact.includes(",");
  let normalized = compact;
  if (hasDot && hasComma) {
    // Rightmost separator is the decimal mark; the other is thousands.
    normalized =
      compact.lastIndexOf(",") > compact.lastIndexOf(".")
        ? compact.replace(/\./g, "").replace(",", ".")
        : compact.replace(/,/g, "");
  } else if (hasComma) {
    normalized = /^\d{1,3}(,\d{3})+$/.test(compact)
      ? compact.replace(/,/g, "")
      : compact.replace(",", ".");
  } else if (hasDot) {
    normalized = /^\d{1,3}(\.\d{3})+$/.test(compact)
      ? compact.replace(/\./g, "")
      : compact;
  }
  if (!/^\d+(\.\d+)?$/.test(normalized) || normalized.length > 15) {
    return null;
  }
  const value = Number(normalized);
  return Number.isFinite(value) ? value : null;
}

const TR_MONTHS: Record<string, string> = {
  ocak: "01", şubat: "02", subat: "02", mart: "03", nisan: "04",
  mayıs: "05", mayis: "05", haziran: "06", temmuz: "07", ağustos: "08",
  agustos: "08", eylül: "09", eylul: "09", ekim: "10", kasım: "11",
  kasim: "11", aralık: "12", aralik: "12",
  january: "01", february: "02", march: "03", april: "04", may: "05",
  june: "06", july: "07", august: "08", september: "09", october: "10",
  november: "11", december: "12",
};

function pad2(value: string): string {
  return value.length === 1 ? `0${value}` : value;
}

/** Finds the first recognizable date in a text window; returns ISO or null. */
export function extractDateFromText(text: string): string | null {
  const iso = text.match(/\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})\b/);
  if (iso) {
    return `${iso[1]}-${iso[2]}-${iso[3]}`;
  }
  const dotted = text.match(/\b(\d{1,2})[./](\d{1,2})[./](20\d{2}|19\d{2})\b/);
  if (dotted) {
    return `${dotted[3]}-${pad2(dotted[2])}-${pad2(dotted[1])}`;
  }
  const named = text.match(
    /\b(\d{1,2})\s+(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik|january|february|march|april|may|june|july|august|september|october|november|december)\s*(20\d{2}|19\d{2})?\b/i,
  );
  if (named) {
    const month = TR_MONTHS[named[2].toLocaleLowerCase("tr-TR")];
    if (month) {
      const year = named[3] ?? String(new Date().getFullYear());
      return `${year}-${month}-${pad2(named[1])}`;
    }
  }
  return null;
}

// A number token with optional leading currency symbol and optional trailing
// unit word. Word-ish boundaries via lookarounds so TR letters work.
const NUMERIC_FACT_PATTERN =
  /(₺|\$|€|£)?\s*(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,4})?|\d+[.,]\d{1,4}|\d+)\s*(%|₺|\$|€|£|tl|try|lira|dolar|dollar|usd|euro|eur|avro|gbp|sterlin|pound|puan|bp)?(?![\p{L}\d])/giu;

function looksLikeBareYear(raw: string, value: number, unit: string | null): boolean {
  return unit === null && Number.isInteger(value) && value >= 1900 && value <= 2100 && /^\d{4}$/.test(raw.trim());
}

function extractNumericPointsFromText(
  text: string,
  sourceHost: string,
): GroundedNumericPoint[] {
  const compact = compactText(text);
  if (!compact) {
    return [];
  }
  const points: GroundedNumericPoint[] = [];
  for (const match of compact.matchAll(NUMERIC_FACT_PATTERN)) {
    if (points.length >= MAX_NUMERIC_POINTS_PER_RESULT) {
      break;
    }
    const index = match.index ?? 0;
    // Skip numbers that are part of a URL.
    const before = compact.slice(Math.max(0, index - 40), index);
    if (/https?:\/\/\S*$/i.test(before) || /www\.\S*$/i.test(before)) {
      continue;
    }
    const rawNumber = match[2] ?? "";
    const value = parseLocalizedNumber(rawNumber);
    if (value === null) {
      continue;
    }
    const unit = normalizeNumericUnit(match[3] ?? match[1]);
    if (looksLikeBareYear(rawNumber, value, unit)) {
      continue;
    }
    // Unit-less small integers are almost never a fact worth charting
    // (list indexes, counts of results, page numbers).
    if (unit === null && Number.isInteger(value) && value < 100 && !rawNumber.includes(",") && !rawNumber.includes(".")) {
      continue;
    }
    const windowStart = Math.max(0, index - 70);
    const windowEnd = Math.min(compact.length, index + (match[0]?.length ?? 0) + 70);
    const context = compact.slice(windowStart, windowEnd).trim();
    points.push({
      value,
      unit,
      date: extractDateFromText(context),
      context: context.slice(0, 160),
      sourceHost,
    });
  }
  return points;
}

export function extractNumericEvidenceFromGrounding(
  input: WebGroundingResult,
): GroundedNumericEvidence {
  const points: GroundedNumericPoint[] = [];
  const seen = new Set<string>();
  for (const result of input.results) {
    if (points.length >= MAX_NUMERIC_POINTS_TOTAL) {
      break;
    }
    const host = result.sourceHost || hostFromUrl(result.url);
    const combined = [result.snippet, result.pageContent ?? ""].filter(Boolean).join("\n");
    for (const point of extractNumericPointsFromText(combined, host)) {
      const key = `${point.value}|${point.unit ?? ""}|${point.date ?? ""}|${host}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      points.push(point);
      if (points.length >= MAX_NUMERIC_POINTS_TOTAL) {
        break;
      }
    }
  }

  const unitCounts = new Map<string, number>();
  let datedCount = 0;
  for (const point of points) {
    if (point.unit) {
      unitCounts.set(point.unit, (unitCounts.get(point.unit) ?? 0) + 1);
    }
    if (point.date) {
      datedCount += 1;
    }
  }
  const hasChartableSeries =
    [...unitCounts.values()].some((count) => count >= 2) || datedCount >= 2;

  return {
    points,
    hasNumericFacts: points.length > 0,
    hasChartableSeries,
  };
}

function buildNumericEvidencePromptLines(evidence: GroundedNumericEvidence): string[] {
  if (!evidence.hasNumericFacts) {
    return [
      "NUMERIC DATA UNAVAILABLE: the web evidence above contains no extractable numeric values or date/value pairs.",
      "Do NOT invent numbers and do NOT emit a chart or table of fabricated live data.",
      "If the user asked for a chart/graph of live data, state honestly that the numeric data could not be retrieved right now, point to the sources above, and suggest retrying or checking an authoritative source.",
    ];
  }
  const lines = [
    "STRUCTURED NUMERIC EVIDENCE (parsed from the sources above):",
    ...evidence.points.map((point) => {
      const segments = [
        `${point.value}${point.unit ? ` ${point.unit}` : ""}`,
        point.date ? `date: ${point.date}` : null,
        point.sourceHost || null,
        `"${point.context}"`,
      ].filter((segment): segment is string => Boolean(segment));
      return `- ${segments.join(" | ")}`;
    }),
  ];
  lines.push(
    evidence.hasChartableSeries
      ? "Chart/table rule: when emitting a chart or table from this live data, use EXACTLY these extracted values (and dates when present); never extrapolate, interpolate, or add values that are not listed."
      : "Chart/table rule: the extracted values above are isolated facts, not a series. State them in prose; do NOT stretch them into a multi-point chart by inventing additional values.",
  );
  return lines;
}

export function buildWebGroundingPromptBlock(input: WebGroundingResult): string | null {
  if (!input.used || input.results.length === 0) {
    return null;
  }
  const numericEvidence = extractNumericEvidenceFromGrounding(input);
  return [
    "PUBLIC WEB GROUNDING",
    `Query: ${input.query}`,
    input.queries.length > 1 ? `Queries used: ${input.queries.join(" | ")}` : null,
    input.retrievedAt ? `Retrieved at: ${input.retrievedAt}` : null,
    input.decisionReasons?.length ? `Research reasons: ${input.decisionReasons.join(", ")}` : null,
    `Grounding confidence: ${input.confidence}`,
    input.degradedReason ? `Grounding note: ${input.degradedReason}` : null,
    ...input.results.map(
      (result, index) => {
        const lines = [
          `${index + 1}. [${result.verificationState}] ${result.title} (${result.sourceHost || hostFromUrl(result.url)})`,
          `URL: ${result.url}`,
          `Snippet: ${result.snippet || "No snippet provided."}`,
        ];
        /* Include page content for top 2 verified results to avoid context bloat */
        if (index < 2 && result.pageContent && result.pageContent.length > 60) {
          lines.push(`Page content: ${result.pageContent}`);
        }
        lines.push(`Query hits: ${result.queryHits}`);
        return lines.join("\n");
      },
    ),
    ...buildNumericEvidencePromptLines(numericEvidence),
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
