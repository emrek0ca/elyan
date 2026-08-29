import { buildGroqModelCatalog, type GroqModelConfigSource } from "./groq-models.js";
import type { SharedBrainWorkload } from "./workloads.js";
import type { SharedBrainConversationMessage } from "./provider-request.js";
import { trimOnly as compactText } from "../../lib/text.js";

/**
 * Groq Compound entegrasyonu — mevcut OpenAI uyumlu Groq sağlayıcı boru hattını
 * BOZMADAN, yerleşik ajan sistemini (web arama + kod yürütme) opsiyonel bir
 * model katmanı olarak ekler. Compound ayrı bir uç nokta değildir; aynı
 * `/chat/completions` yolunu `groq/compound` / `groq/compound-mini` model
 * adlarıyla kullanır. Bu modül üç saf yardımcı sağlar:
 *   1) isGroqCompoundModel  — model adından compound tespiti
 *   2) buildGroqCompoundRequestExtensions — arama ayarlarını gövdeye ekler
 *   3) extractGroqCompoundEvidence — cevabın koştuğu araç/atıf kanıtını çıkarır
 * Böylece compound bir modelse kalite artar; değilse hiçbir davranış değişmez.
 */

export type GroqCompoundConfigSource = GroqModelConfigSource & {
  GROQ_COMPOUND_ENABLED?: boolean | null;
  GROQ_COMPOUND_RESEARCH_ENABLED?: boolean | null;
  GROQ_COMPOUND_DEEP_ENABLED?: boolean | null;
  GROQ_COMPOUND_SEARCH_COUNTRY?: string | null;
  GROQ_COMPOUND_INCLUDE_DOMAINS?: string | null;
  GROQ_COMPOUND_EXCLUDE_DOMAINS?: string | null;
};

// Compound'un GERÇEKTEN kazandırdığı iş yükleri: çok-adımlı akıl yürütme +
// canlı web + hesaplama. Hız-kritik (intent/fast_route/mobile_chat_fast),
// vision ve BELGE iş yükleri HARİÇ: belge içeriğinin yerleşik web aramasına
// sızmaması için document_analysis kapsam dışıdır (gizlilik güvenliği).
const COMPOUND_ELIGIBLE_WORKLOADS: ReadonlySet<SharedBrainWorkload> = new Set([
  "planning",
  "mobile_chat_deep_refine",
  "public_research",
  "public_deep_research",
  "public_quantum_research",
]);

function splitDomains(value: unknown): string[] {
  return compactText(value)
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean)
    .slice(0, 32);
}

export function isGroqCompoundModel(model: unknown): boolean {
  const name = compactText(model).toLowerCase();
  if (!name) return false;
  // `groq/compound`, `groq/compound-mini` ve olası sürüm sonekleri.
  return name === "groq/compound" || name.startsWith("groq/compound");
}

/**
 * Compound'un birincil model olarak denenip denenmeyeceği. Bayrak kapalıysa
 * (varsayılan) veya iş yükü uygun değilse asla. `liveWebSignal` — turdaki web/
 * güncellik ipucu — uygun iş yükleri içinde önceliktir; uygun OLMAYAN bir iş
 * yükünü compound'a çeviremez.
 */
export function shouldUseGroqCompound(input: {
  config: GroqCompoundConfigSource;
  workload: SharedBrainWorkload;
  liveWebSignal?: boolean;
}): boolean {
  if (input.config.GROQ_COMPOUND_ENABLED !== true) return false;
  if (
    (input.workload === "public_research" ||
      input.workload === "public_quantum_research") &&
    input.config.GROQ_COMPOUND_RESEARCH_ENABLED !== true
  ) {
    return false;
  }
  if (
    (input.workload === "planning" ||
      input.workload === "mobile_chat_deep_refine" ||
      input.workload === "public_deep_research") &&
    input.config.GROQ_COMPOUND_DEEP_ENABLED !== true
  ) {
    return false;
  }
  // Canlı-web sinyali compound'u UYGUN iş yüklerinde öne çıkarır; uygunluğu
  // tek başına YARATMAZ.
  //
  // Eskiden bu satır her iş yükünü compound'a yönlendiriyordu. Yerel koşuda
  // sıradan bir sohbet turu ("Şu an saat kaç?") canlı-web sinyali taşıdığı
  // için compound'a gitti ve boş dönüşle turu uzattı — oysa o turun araç
  // döngüsüne ihtiyacı yoktu, yalnız saate ihtiyacı vardı ve o zaten
  // prompt'ta. Sinyal artık uygun iş yükleri içinde bir ÖNCELİK, kapının
  // kendisi değil.
  return COMPOUND_ELIGIBLE_WORKLOADS.has(input.workload);
}

/**
 * İş yüküne göre compound (derin) veya compound-mini (hızlı) modelini seçer.
 * Hız-duyarlı yollar mini'ye, kalite-öncelikli derin yollar tam compound'a gider.
 */
export function resolveGroqCompoundModel(
  config: GroqCompoundConfigSource,
  workload: SharedBrainWorkload,
): string {
  const catalog = buildGroqModelCatalog(config);
  const fast =
    workload === "intent" ||
    workload === "fast_route" ||
    workload === "mobile_chat_fast" ||
    workload === "desktop_handoff" ||
    workload === "public_research";
  return fast ? catalog.compoundMiniModel : catalog.compoundModel;
}


/**
 * Compound'a KENDİ araç sonuçlarının kanıt olduğunu söyleyen yönerge.
 *
 * CANLI ARIZA: "Maraş'ta hava durumu nasıl" sorusunda compound-mini yerleşik
 * web aramasını çalıştırdı, dört kaynak buldu (snippet'lerde sıcaklık bilgisi
 * dahil) ve ardından "yeterli kanıt yok, MGM sitesinden kontrol edin" dedi.
 *
 * Sebep: ortak sistem istemi "canlı veriyi SUNUCU getirir" diyor ve güçlü
 * uydurma-karşıtı kurallar taşıyor. Compound ise kanıtı KENDİSİ topluyor;
 * istemde bunun geçerli kanıt sayıldığı hiç yazmadığı için model kendi
 * bulduğu veriyi yok sayıp reddediyordu. Kullanıcı arama sonuçlarını
 * görüyor ama cevabı alamıyordu — mümkün olan en kötü kombinasyon.
 *
 * Bu yönerge YALNIZ compound modellerine eklenir; diğer modellerin davranışı
 * (kanıtı sunucudan bekleme) aynen korunur.
 */
const COMPOUND_EVIDENCE_DIRECTIVE = [
  "You have BUILT-IN web search and code execution. For questions about current or live information (weather, prices, rates, scores, news, schedules), run your search and then ANSWER FROM WHAT YOU FOUND.",
  "Your own search results ARE valid evidence. Never say you lack evidence, and never redirect the user to go check a website themselves, when your search returned relevant results — that is the one failure mode to avoid.",
  "State the concrete current value you found (temperature, price, score, date) in the first sentence, then add brief context. Mention the source name naturally in prose.",
  "Only if your search genuinely returns nothing usable, say plainly that the live value could not be retrieved right now.",
].join(" ");

/**
 * Compound modeline yönergeyi ekler. Compound değilse mesajlar aynen döner.
 */
export function withGroqCompoundGuidance(
  messages: SharedBrainConversationMessage[],
  model: unknown,
): SharedBrainConversationMessage[] {
  if (!isGroqCompoundModel(model)) return messages;
  const systemContent = messages
    .filter((message) => message.role === "system")
    .map((message) => compactText(message.content))
    .filter(Boolean)
    .join("\n\n");
  const conversation = messages.filter((message) => message.role !== "system");
  let lastUserIndex = -1;
  for (let index = conversation.length - 1; index >= 0; index -= 1) {
    if (conversation[index]?.role === "user") {
      lastUserIndex = index;
      break;
    }
  }
  const orderedConversation =
    lastUserIndex >= 0 && lastUserIndex !== conversation.length - 1
      ? [
          ...conversation.slice(0, lastUserIndex),
          ...conversation.slice(lastUserIndex + 1),
          conversation[lastUserIndex],
        ]
      : conversation;
  return [
    {
      role: "system",
      content: systemContent.includes(COMPOUND_EVIDENCE_DIRECTIVE)
        ? systemContent
        : [systemContent, COMPOUND_EVIDENCE_DIRECTIVE].filter(Boolean).join("\n\n"),
    },
    ...orderedConversation,
  ];
}

/**
 * `search_settings` gövde eklentisi (kökte). Yalnız model compound ise
 * VE en az bir ayar yapılandırılmışsa döner; aksi halde boş nesne (no-op).
 * Boş dönmesi compound'un varsayılan davranışını (tam web arama) korur.
 */
export function buildGroqCompoundRequestExtensions(
  config: GroqCompoundConfigSource,
  model: unknown,
  options: { requiresComputation?: boolean } = {},
): Record<string, unknown> {
  if (!isGroqCompoundModel(model)) return {};

  const includeDomains = splitDomains(config.GROQ_COMPOUND_INCLUDE_DOMAINS);
  const excludeDomains = splitDomains(config.GROQ_COMPOUND_EXCLUDE_DOMAINS);
  const country = compactText(config.GROQ_COMPOUND_SEARCH_COUNTRY).toLowerCase();

  const searchSettings: Record<string, unknown> = {};
  if (includeDomains.length > 0) searchSettings.include_domains = includeDomains;
  if (excludeDomains.length > 0) searchSettings.exclude_domains = excludeDomains;
  // `country` ISO kodu DEĞİL, ülke ADI bekler (Tavily şeması). Ölçüm:
  // `tr` → HTTP 400 "invalid country code: tr", `turkey` → 200.
  //
  // ISO kodu yazılması çok kolay bir yapılandırma hatası ve bedeli ağır: ayar
  // aramayı yerelleştirmek yerine HER compound isteğini düşürür, yani tüm
  // araştırma yolu sessizce fallback'e iner. İki harfli değeri göndermek yerine
  // düşürmek, kesinti yerine yalnız yerelleştirme kaybıdır.
  if (country && country.length > 2) {
    searchSettings.country = country;
  }

  const enabledTools = isGroqCompoundModel(model) && compactText(model).includes("mini")
    ? ["web_search"]
    : [
        "web_search",
        "visit_website",
        ...(options.requiresComputation === true ? ["code_interpreter"] : []),
      ];
  // `search_settings` GÖVDENİN KÖKÜNDE olmalı.
  //
  // Eskiden `compound_custom.search_settings` altında gönderiliyordu ve Groq
  // bunu SESSİZCE YOK SAYIYORDU — geçersiz bir ülke kodu bile hata
  // döndürmüyordu, yani ayarın işe yaramadığı fark edilemiyordu. Kökte
  // gönderildiğinde aynı geçersiz değer 400 veriyor, yani gerçekten okunuyor.
  // Sonuç: ülke/alan-adı filtreleri bugüne kadar ölü konfigürasyondu.
  return {
    ...(Object.keys(searchSettings).length > 0
      ? { search_settings: searchSettings }
      : {}),
    compound_custom: {
      tools: {
        enabled_tools: enabledTools,
      },
    },
  };
}

export type GroqCompoundCitation = {
  title: string;
  url: string;
  snippet?: string;
  observedAt?: string;
  toolType?: string;
  query?: string;
};

export type GroqCompoundEvidence = {
  toolsUsed: string[];
  searchQueries: string[];
  citations: GroqCompoundCitation[];
};

function readExecutedTools(message: Record<string, unknown>): unknown[] {
  const direct = message.executed_tools;
  if (Array.isArray(direct)) return direct;
  const alt = (message as Record<string, unknown>).tool_calls;
  return Array.isArray(alt) ? alt : [];
}

function collectCitationsFromOutput(
  output: unknown,
  citations: GroqCompoundCitation[],
  context: { toolType?: string; query?: string } = {},
): void {
  if (typeof output === "string") {
    const urls = output.match(/https?:\/\/[^\s<>{}\[\]"']+/giu) ?? [];
    for (const rawUrl of urls) {
      const url = rawUrl.replace(/[),.;:!?]+$/u, "").slice(0, 2048);
      if (!url) continue;
      const offset = output.indexOf(rawUrl);
      const before = output.slice(Math.max(0, offset - 180), offset);
      const title = compactText(before.split(/\r?\n/u).at(-1)) || url;
      const nearby = compactText(
        output.slice(Math.max(0, offset - 240), Math.min(output.length, offset + rawUrl.length + 360)),
      );
      const observedAt = normalizeEvidenceTimestamp(
        nearby.match(/\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b/u)?.[0],
      );
      citations.push({
        title: title.slice(0, 240),
        url,
        ...(nearby ? { snippet: nearby.slice(0, 700) } : {}),
        ...(observedAt ? { observedAt } : {}),
        ...context,
      });
    }
    return;
  }
  if (!output || typeof output !== "object") return;
  const record = output as Record<string, unknown>;
  const buckets = [
    record.results,
    record.search_results,
    record.citations,
    record.sources,
  ];
  const directUrl = compactText(record.url ?? record.link);
  if (directUrl) {
    const title = compactText(record.title ?? record.name) || directUrl;
    const snippet = compactText(
      record.snippet ?? record.content ?? record.description ?? record.text,
    );
    const observedAt = readEvidenceTimestamp(record);
    citations.push({
      title: title.slice(0, 240),
      url: directUrl.slice(0, 2048),
      ...(snippet ? { snippet: snippet.slice(0, 700) } : {}),
      ...(observedAt ? { observedAt } : {}),
      ...context,
    });
  }
  for (const bucket of buckets) {
    if (!Array.isArray(bucket)) continue;
    for (const entry of bucket) {
      if (!entry || typeof entry !== "object") continue;
      const item = entry as Record<string, unknown>;
      const url = compactText(item.url ?? item.link);
      if (!url) continue;
      const title = compactText(item.title ?? item.name) || url;
      const snippet = compactText(
        item.snippet ?? item.content ?? item.description ?? item.text,
      );
      const observedAt = readEvidenceTimestamp(item);
      citations.push({
        title: title.slice(0, 240),
        url: url.slice(0, 2048),
        ...(snippet ? { snippet: snippet.slice(0, 700) } : {}),
        ...(observedAt ? { observedAt } : {}),
        ...context,
      });
    }
  }
}

function normalizeEvidenceTimestamp(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const numeric = typeof value === "number" ? value : Number(value);
  const parsed = Number.isFinite(numeric) && String(value).trim().length <= 13
    ? new Date(numeric < 10_000_000_000 ? numeric * 1_000 : numeric)
    : new Date(String(value));
  const time = parsed.getTime();
  if (
    !Number.isFinite(time) ||
    parsed.getUTCFullYear() < 1990 ||
    time > Date.now() + 24 * 60 * 60_000
  ) {
    return null;
  }
  return parsed.toISOString();
}

function readEvidenceTimestamp(record: Record<string, unknown>): string | null {
  for (const key of [
    "observedAt",
    "observed_at",
    "publishedAt",
    "published_at",
    "publishedDate",
    "published_date",
    "last_updated_at",
    "lastUpdatedAt",
    "timestamp",
    "date",
    "time",
  ]) {
    const normalized = normalizeEvidenceTimestamp(record[key]);
    if (normalized) return normalized;
  }
  return null;
}

function collectFromExecutedTools(
  container: Record<string, unknown>,
  toolsUsed: Set<string>,
  searchQueries: string[],
  citations: GroqCompoundCitation[],
): void {
  const executed = readExecutedTools(container);
  for (const tool of executed) {
    if (!tool || typeof tool !== "object") continue;
    const toolRecord = tool as Record<string, unknown>;
    const type = compactText(toolRecord.type ?? toolRecord.name);
    if (type) toolsUsed.add(type.toLowerCase());
    let toolQuery = "";
    const args = toolRecord.arguments;
    if (typeof args === "string" && args.trim()) {
      try {
        const parsed = JSON.parse(args) as Record<string, unknown>;
        const query = compactText(parsed.query ?? parsed.q);
        if (query) {
          toolQuery = query.slice(0, 240);
          searchQueries.push(toolQuery);
        }
      } catch {
        const query = compactText(
          args.match(/(?:query|q)\s*[:=]\s*["']?([^\n"']+)/iu)?.[1],
        );
        if (query) {
          toolQuery = query.slice(0, 240);
          searchQueries.push(toolQuery);
        }
      }
    } else if (args && typeof args === "object") {
      const query = compactText((args as Record<string, unknown>).query);
      if (query) {
        toolQuery = query.slice(0, 240);
        searchQueries.push(toolQuery);
      }
    }
    const context = {
      ...(type ? { toolType: type.toLowerCase() } : {}),
      ...(toolQuery ? { query: toolQuery } : {}),
    };
    collectCitationsFromOutput(toolRecord.output, citations, context);
    collectCitationsFromOutput(toolRecord.search_results, citations, context);
    collectCitationsFromOutput(toolRecord, citations, context);
  }
}

function dedupeCitations(citations: GroqCompoundCitation[]): GroqCompoundCitation[] {
  const byUrl = new Map<string, GroqCompoundCitation>();
  for (const citation of citations) {
    const current = byUrl.get(citation.url);
    if (!current) {
      byUrl.set(citation.url, citation);
      continue;
    }
    byUrl.set(citation.url, {
      ...current,
      ...(citation.title.length > current.title.length
        ? { title: citation.title }
        : {}),
      ...(!current.snippet && citation.snippet
        ? { snippet: citation.snippet }
        : {}),
      ...(!current.observedAt && citation.observedAt
        ? { observedAt: citation.observedAt }
        : {}),
      ...(!current.toolType && citation.toolType
        ? { toolType: citation.toolType }
        : {}),
      ...(!current.query && citation.query ? { query: citation.query } : {}),
    });
  }
  return [...byUrl.values()];
}

/**
 * Compound cevabından (veya tek bir stream parçasından) yürütülen araçları,
 * arama sorgularını ve atıf/URL'leri güvenli şekilde çıkarır. API şekli
 * sürümler arası değiştiğinden hem `choices[].message` hem `choices[].delta`
 * üzerindeki `executed_tools` (ve iç içe `search_results`/`citations`) tolere
 * edilir. Streaming'de araç kanıtı genelde son parçada geldiğinden delta yolu
 * gereklidir. Elyan bu kanıtı grounding/atıf blokları için kullanır.
 */
export function extractGroqCompoundEvidence(payload: unknown): GroqCompoundEvidence {
  const empty: GroqCompoundEvidence = {
    toolsUsed: [],
    searchQueries: [],
    citations: [],
  };
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return empty;
  }

  const toolsUsed = new Set<string>();
  const searchQueries: string[] = [];
  const citations: GroqCompoundCitation[] = [];

  const record = payload as Record<string, unknown>;
  const choices = Array.isArray(record.choices) ? record.choices : [];
  for (const choice of choices) {
    if (!choice || typeof choice !== "object") continue;
    const choiceRecord = choice as Record<string, unknown>;
    for (const key of ["message", "delta"] as const) {
      const container = choiceRecord[key];
      if (!container || typeof container !== "object" || Array.isArray(container)) {
        continue;
      }
      collectFromExecutedTools(
        container as Record<string, unknown>,
        toolsUsed,
        searchQueries,
        citations,
      );
    }
  }

  return {
    toolsUsed: [...toolsUsed],
    searchQueries: [...new Set(searchQueries)].slice(0, 12),
    citations: dedupeCitations(citations).slice(0, 20),
  };
}

/** İki kanıt parçasını birleştirir (streaming biriktirme için). */
export function mergeGroqCompoundEvidence(
  base: GroqCompoundEvidence,
  next: GroqCompoundEvidence,
): GroqCompoundEvidence {
  return {
    toolsUsed: [...new Set([...base.toolsUsed, ...next.toolsUsed])],
    searchQueries: [...new Set([...base.searchQueries, ...next.searchQueries])].slice(0, 12),
    citations: dedupeCitations([...base.citations, ...next.citations]).slice(0, 20),
  };
}

export const EMPTY_GROQ_COMPOUND_EVIDENCE: GroqCompoundEvidence = {
  toolsUsed: [],
  searchQueries: [],
  citations: [],
};

export function hasGroqCompoundEvidence(evidence: GroqCompoundEvidence): boolean {
  return (
    evidence.citations.length > 0 ||
    evidence.toolsUsed.length > 0 ||
    evidence.searchQueries.length > 0
  );
}

/**
 * Birleşik okuyucu: nihai payload compound modelden geldiyse kanıtı döndürür.
 * Streaming yolunda sentezlenen payload ham `choices` taşımaz; bu durumda
 * biriktirilmiş kanıt `groqCompoundEvidence` taşıyıcı alanına konur ve önce o
 * okunur. Aksi halde ham (non-streaming) payload'dan çıkarılır.
 */
export function readGroqCompoundEvidence(
  payload: unknown,
  model: unknown,
): GroqCompoundEvidence {
  if (!isGroqCompoundModel(model)) return EMPTY_GROQ_COMPOUND_EVIDENCE;
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const carrier = (payload as Record<string, unknown>).groqCompoundEvidence;
    if (carrier && typeof carrier === "object" && !Array.isArray(carrier)) {
      const record = carrier as Record<string, unknown>;
      return {
        toolsUsed: Array.isArray(record.toolsUsed)
          ? record.toolsUsed.map((v) => compactText(v)).filter(Boolean)
          : [],
        searchQueries: Array.isArray(record.searchQueries)
          ? record.searchQueries.map((v) => compactText(v)).filter(Boolean)
          : [],
        citations: Array.isArray(record.citations)
          ? (record.citations as unknown[])
              .filter((c): c is Record<string, unknown> =>
                Boolean(c) && typeof c === "object" && !Array.isArray(c),
              )
              .map((c) => ({
                title: compactText(c.title),
                url: compactText(c.url),
              }))
              .filter((c) => c.url)
          : [],
      };
    }
  }
  return extractGroqCompoundEvidence(payload);
}
