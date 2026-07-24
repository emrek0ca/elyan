import { buildGroqModelCatalog, type GroqModelConfigSource } from "./groq-models.js";
import type { SharedBrainWorkload } from "./workloads.js";

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

function compactText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

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
 * güncellik ipucu — verildiyse uygunluğu güçlendirir ama tek başına zorunlu
 * değildir; operatör bayrağı açtığında uygun iş yükleri compound'a yönelir.
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
  if (input.liveWebSignal === true) return true;
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
 * compound_custom / search_settings gövde eklentisi. Yalnız model compound ise
 * VE en az bir ayar yapılandırılmışsa döner; aksi halde boş nesne (no-op).
 * Boş dönmesi compound'un varsayılan davranışını (tam web arama) korur.
 */
export function buildGroqCompoundRequestExtensions(
  config: GroqCompoundConfigSource,
  model: unknown,
): Record<string, unknown> {
  if (!isGroqCompoundModel(model)) return {};

  const includeDomains = splitDomains(config.GROQ_COMPOUND_INCLUDE_DOMAINS);
  const excludeDomains = splitDomains(config.GROQ_COMPOUND_EXCLUDE_DOMAINS);
  const country = compactText(config.GROQ_COMPOUND_SEARCH_COUNTRY).toLowerCase();

  const searchSettings: Record<string, unknown> = {};
  if (includeDomains.length > 0) searchSettings.include_domains = includeDomains;
  if (excludeDomains.length > 0) searchSettings.exclude_domains = excludeDomains;
  if (country) searchSettings.country = country;

  if (Object.keys(searchSettings).length === 0) return {};
  return {
    compound_custom: {
      search_settings: searchSettings,
    },
  };
}

export type GroqCompoundCitation = {
  title: string;
  url: string;
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
): void {
  if (!output || typeof output !== "object") return;
  const record = output as Record<string, unknown>;
  const buckets = [record.results, record.search_results, record.citations];
  for (const bucket of buckets) {
    if (!Array.isArray(bucket)) continue;
    for (const entry of bucket) {
      if (!entry || typeof entry !== "object") continue;
      const item = entry as Record<string, unknown>;
      const url = compactText(item.url ?? item.link);
      if (!url) continue;
      const title = compactText(item.title ?? item.name) || url;
      citations.push({ title: title.slice(0, 240), url: url.slice(0, 2048) });
    }
  }
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
    const args = toolRecord.arguments;
    if (typeof args === "string" && args.trim()) {
      try {
        const parsed = JSON.parse(args) as Record<string, unknown>;
        const query = compactText(parsed.query ?? parsed.q);
        if (query) searchQueries.push(query.slice(0, 240));
      } catch {
        // arguments düz metinse sorgu olarak alma; gürültüyü önle.
      }
    } else if (args && typeof args === "object") {
      const query = compactText((args as Record<string, unknown>).query);
      if (query) searchQueries.push(query.slice(0, 240));
    }
    collectCitationsFromOutput(toolRecord.output, citations);
    collectCitationsFromOutput(toolRecord.search_results, citations);
  }
}

function dedupeCitations(citations: GroqCompoundCitation[]): GroqCompoundCitation[] {
  const seenUrls = new Set<string>();
  return citations.filter((citation) => {
    if (seenUrls.has(citation.url)) return false;
    seenUrls.add(citation.url);
    return true;
  });
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
