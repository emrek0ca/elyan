import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { and, eq, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { knowledgeChunks, knowledgeDocuments } from "../../db/schema.js";
import { indexKnowledgeChunksForDocument } from "./retrieval.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";
import { contentTerms } from "./lexical-turkish.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";
import {
  embedQueryForStorage,
  embedTextsForStorage,
} from "./semantic-embedder.js";
import {
  searchKnowledge as searchKnowledgeOrchestrated,
  type OrchestratedRetrieval,
} from "./retrieval-orchestrator.js";
import { retrievalResultsToEvidencePacket } from "./evidence-packet.js";

export const ELYAN_BRAIN_CORPUS_VERSION = "2026-08-v3";

export type BrainCorpusDomain =
  | "memory"
  | "skills"
  | "design"
  | "code"
  | "language"
  | "data"
  | "reasoning"
  | "safety"
  | "product"
  | "onboarding"
  | "support"
  | "tasks"
  | "capabilities";

type BrainCorpusSource = {
  id: string;
  domain: BrainCorpusDomain;
  title: string;
  fileName: string;
  tags: string[];
  priority: number;
  purpose: "policy" | "knowledge";
  intents: string[];
};

export type BrainCorpusDocumentManifest = BrainCorpusSource & {
  version: string;
  sourceUri: string;
  contentHash: string;
  characterCount: number;
};

const CORPUS_SOURCES: BrainCorpusSource[] = [
  {
    id: "elyan.brain.memory",
    domain: "memory",
    title: "Elyan Memory Protocol",
    fileName: "memory.md",
    tags: ["memory", "episodic", "facts", "profile", "retention"],
    priority: 90,
    purpose: "policy",
    intents: [],
  },
  {
    id: "elyan.brain.skills",
    domain: "skills",
    title: "Elyan Skill and Capability Protocol",
    fileName: "skills.md",
    tags: ["skills", "routing", "tools", "attachments", "desktop-runtime"],
    priority: 88,
    purpose: "policy",
    intents: [],
  },
  {
    id: "elyan.brain.design",
    domain: "design",
    title: "Elyan Design Language",
    fileName: "design.md",
    tags: ["design", "website", "pdf", "presentation", "visual-output"],
    priority: 86,
    purpose: "policy",
    intents: [],
  },
  {
    id: "elyan.brain.code",
    domain: "code",
    title: "Elyan Code Engineering Protocol",
    fileName: "code.md",
    tags: ["code", "debug", "tests", "architecture", "refactor"],
    priority: 86,
    purpose: "policy",
    intents: [],
  },
  {
    id: "elyan.brain.language",
    domain: "language",
    title: "Elyan Language Protocol",
    fileName: "language.md",
    tags: ["language", "turkish", "english", "translation", "writing"],
    priority: 82,
    purpose: "policy",
    intents: [],
  },
  {
    id: "elyan.brain.data",
    domain: "data",
    title: "Elyan Data and Document Protocol",
    fileName: "data.md",
    tags: ["data", "documents", "tables", "charts", "citations"],
    priority: 84,
    purpose: "policy",
    intents: [],
  },
  {
    id: "elyan.brain.reasoning",
    domain: "reasoning",
    title: "Elyan Reasoning Protocol",
    fileName: "reasoning.md",
    tags: ["reasoning", "planning", "verification", "uncertainty"],
    priority: 84,
    purpose: "policy",
    intents: [],
  },
  {
    id: "elyan.brain.safety",
    domain: "safety",
    title: "Elyan Safety Protocol",
    fileName: "safety.md",
    tags: ["safety", "privacy", "permissions", "boundary", "disclosure"],
    priority: 92,
    purpose: "policy",
    intents: [],
  },
  {
    id: "elyan.knowledge.product",
    domain: "product",
    title: "Elyan Product Architecture",
    fileName: "product.md",
    tags: ["elyan", "mobile", "backend", "desktop", "local-first", "privacy"],
    priority: 98,
    purpose: "knowledge",
    intents: [
      "Elyan nedir ve nasıl çalışır?",
      "Elyan masaüstü ne işe yarar?",
      "Mobil uygulama ile masaüstü arasındaki fark nedir?",
      "Elyan özel verilerimi nerede işler?",
    ],
  },
  {
    id: "elyan.knowledge.capabilities",
    domain: "capabilities",
    title: "Elyan Capabilities",
    fileName: "capabilities.md",
    tags: ["yetenek", "ne yapabilir", "sınır", "kaynak", "güncellik", "biçim"],
    priority: 97,
    purpose: "knowledge",
    intents: [
      "Elyan neler yapabilir?",
      "Sen ne işe yararsın?",
      "Hangi konularda yardım edebilirsin?",
      "Bilgiyi nereden alıyorsun?",
      "Neden internete bakmadın?",
    ],
  },
  {
    id: "elyan.knowledge.onboarding",
    domain: "onboarding",
    title: "Elyan Onboarding Guide",
    fileName: "onboarding.md",
    tags: ["başlangıç", "eşleştirme", "cihaz", "izin", "ilk görev"],
    priority: 96,
    purpose: "knowledge",
    intents: [
      "Elyan'ı ilk kez nasıl kullanırım?",
      "Masaüstü cihazımı nasıl eşleştiririm?",
      "Mobil uygulamadan nasıl görev veririm?",
      "İzin ve onay kartları nasıl çalışır?",
    ],
  },
  {
    id: "elyan.knowledge.support",
    domain: "support",
    title: "Elyan Support Guide",
    fileName: "support.md",
    tags: ["destek", "bağlantı", "görev", "bekliyor", "hata", "artifact"],
    priority: 96,
    purpose: "knowledge",
    intents: [
      "Masaüstü neden bağlı görünmüyor?",
      "Görev neden bekliyor?",
      "Üretilen dosyayı nereden indiririm?",
      "Bir görev başarısız olduğunda ne yapmalıyım?",
    ],
  },
  {
    id: "elyan.knowledge.tasks",
    domain: "tasks",
    title: "Elyan Task Examples",
    fileName: "tasks.md",
    tags: ["örnek", "görev", "belge", "araştırma", "otomasyon", "çıktı"],
    priority: 94,
    purpose: "knowledge",
    intents: [
      "Elyan'a nasıl iyi görev verilir?",
      "Belge veya tablo istemek için nasıl yazmalıyım?",
      "Hangi görevleri sunucu yapar, hangilerini masaüstü yapar?",
      "Görev sonucunu nasıl doğrularım?",
    ],
  },
];

export type BrainCorpusSelection = {
  domain: BrainCorpusDomain;
  score: number;
  source: "semantic" | "registry";
};

const KNOWLEDGE_CORPUS_SOURCES = CORPUS_SOURCES.filter(
  (source) => source.purpose === "knowledge",
);
const CORPUS_SEMANTIC_THRESHOLD = 0.82;
const CORPUS_SEMANTIC_MARGIN = 0.012;
let corpusIntentVectors: Array<{
  source: BrainCorpusSource;
  vectors: number[][];
}> | null = null;
let corpusIntentVectorsPromise: Promise<void> | null = null;

function cosine(left: number[], right: number[]): number {
  let dot = 0;
  for (let index = 0; index < left.length && index < right.length; index += 1) {
    dot += left[index] * right[index];
  }
  return dot;
}

async function ensureCorpusIntentVectors(
  logger?: FastifyInstance["log"],
): Promise<void> {
  if (corpusIntentVectors) return;
  if (!corpusIntentVectorsPromise) {
    corpusIntentVectorsPromise = (async () => {
      const built: Array<{ source: BrainCorpusSource; vectors: number[][] }> = [];
      for (const source of KNOWLEDGE_CORPUS_SOURCES) {
        const vectors = await embedTextsForStorage(
          source.intents,
          logger,
          `corpus:intents:${source.id}`,
          60_000,
        );
        if (!vectors) {
          corpusIntentVectorsPromise = null;
          return;
        }
        built.push({ source, vectors });
      }
      corpusIntentVectors = built;
    })();
  }
  await corpusIntentVectorsPromise;
}

function registryCorpusSelection(prompt: string): BrainCorpusSelection[] {
  const terms = new Set(
    compactText(prompt)
      .toLocaleLowerCase("tr-TR")
      .split(/[^\p{L}\p{N}]+/u)
      .filter((term) => term.length >= 3),
  );
  return KNOWLEDGE_CORPUS_SOURCES.map((source) => {
    const descriptor = [source.title, ...source.tags, ...source.intents]
      .join(" ")
      .toLocaleLowerCase("tr-TR");
    const overlap = [...terms].filter((term) => descriptor.includes(term)).length;
    return {
      domain: source.domain,
      score: terms.size > 0 ? overlap / terms.size : 0,
      source: "registry" as const,
    };
  })
    .filter((entry) => entry.score >= 0.34)
    .sort((left, right) => right.score - left.score)
    .slice(0, 2);
}

export async function selectBrainCorpusDomains(input: {
  prompt: string;
  queryVector?: number[] | null;
  logger?: FastifyInstance["log"];
}): Promise<BrainCorpusSelection[]> {
  await ensureCorpusIntentVectors(input.logger).catch(() => undefined);
  const queryVector =
    input.queryVector === undefined
      ? await embedQueryForStorage(
          input.prompt,
          input.logger,
          "corpus:query",
          2_500,
        ).catch(() => null)
      : input.queryVector;
  if (!queryVector || !corpusIntentVectors) {
    return registryCorpusSelection(input.prompt);
  }
  const ranked = corpusIntentVectors
    .map(({ source, vectors }) => ({
      domain: source.domain,
      score: vectors.reduce(
        (best, vector) => Math.max(best, cosine(queryVector, vector)),
        -1,
      ),
      source: "semantic" as const,
    }))
    .sort((left, right) => right.score - left.score);
  const top = ranked[0];
  if (!top || top.score < CORPUS_SEMANTIC_THRESHOLD) {
    return registryCorpusSelection(input.prompt);
  }
  const runnerUp = ranked[1];
  if (runnerUp && top.score - runnerUp.score < CORPUS_SEMANTIC_MARGIN) {
    return registryCorpusSelection(input.prompt);
  }
  return [top];
}

export async function primeBrainCorpusSelection(
  logger?: FastifyInstance["log"],
): Promise<boolean> {
  await ensureCorpusIntentVectors(logger).catch(() => undefined);
  return corpusIntentVectors != null;
}

type StableCorpusCachePayload = Omit<OrchestratedRetrieval, "evidencePacket">;

const STABLE_CORPUS_CACHE_TTL_MS = 24 * 60 * 60_000;
const stableCorpusInflight = new WeakMap<
  FastifyInstance,
  Map<string, Promise<StableCorpusCachePayload>>
>();

function stableCorpusCacheKey(query: string, limit: number): string {
  const digest = hashText(
    `${ELYAN_BRAIN_CORPUS_VERSION}:${limit}:${compactText(query)
      .toLocaleLowerCase("tr-TR")}`,
  );
  return `brain:stable-corpus:v2:${digest}`;
}

function normalizeStableCorpusCachePayload(
  value: unknown,
): StableCorpusCachePayload | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (!Array.isArray(record.results) || !record.orchestration) return null;
  return {
    retrievalMode: String(record.retrievalMode ?? "lexical_fallback"),
    results: record.results.flatMap((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return [];
      const result = item as Record<string, unknown>;
      const updatedAt = new Date(String(result.updatedAt ?? ""));
      if (!result.documentId || !result.chunkId || Number.isNaN(updatedAt.getTime())) {
        return [];
      }
      return [{ ...result, updatedAt }] as OrchestratedRetrieval["results"];
    }),
    retrievalResultCount: Number(record.retrievalResultCount ?? 0),
    degradedReason:
      typeof record.degradedReason === "string" ? record.degradedReason : null,
    orchestration: record.orchestration as OrchestratedRetrieval["orchestration"],
  };
}

function hydrateStableCorpusResult(
  userId: string,
  query: string,
  payload: StableCorpusCachePayload,
): OrchestratedRetrieval {
  return {
    ...payload,
    evidencePacket: retrievalResultsToEvidencePacket({
      userId,
      query,
      results: payload.results.map((result) => ({
        ...result,
        metadata:
          result.metadata &&
          typeof result.metadata === "object" &&
          !Array.isArray(result.metadata)
            ? (result.metadata as Record<string, unknown>)
            : {},
      })),
    }),
  };
}

export async function searchStableBrainCorpus(
  app: FastifyInstance,
  input: {
    userId: string;
    query: string;
    limit: number;
    evidenceRequired: boolean;
    queryVector?: number[] | null;
    neuralPolicy?: {
      neuralReady?: boolean;
      embeddingReady?: boolean;
      evaluationReady?: boolean;
    };
  },
): Promise<OrchestratedRetrieval> {
  const key = stableCorpusCacheKey(input.query, input.limit);
  const store = app.services?.reliability?.store;
  if (store) {
    try {
      const cached = await store.get(key);
      const parsed = cached
        ? normalizeStableCorpusCachePayload(JSON.parse(cached))
        : null;
      if (parsed) return hydrateStableCorpusResult(input.userId, input.query, parsed);
    } catch {
      // Cache failure must not block corpus retrieval.
    }
  }

  let inflight = stableCorpusInflight.get(app);
  if (!inflight) {
    inflight = new Map();
    stableCorpusInflight.set(app, inflight);
  }
  let pending = inflight.get(key);
  if (!pending) {
    pending = searchKnowledgeOrchestrated(app, {
      ...input,
      scope: "system_corpus",
    })
      .then(async ({ evidencePacket: _evidencePacket, ...payload }) => {
        if (
          store &&
          payload.results.length > 0 &&
          payload.orchestration.lowConfidence !== true
        ) {
          await store
            .set(key, JSON.stringify(payload), STABLE_CORPUS_CACHE_TTL_MS)
            .catch(() => undefined);
        }
        return payload;
      })
      .finally(() => inflight?.delete(key));
    inflight.set(key, pending);
  }
  const payload = await pending;
  return hydrateStableCorpusResult(input.userId, input.query, payload);
}

function hashText(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function corpusDir(): string {
  return join(process.cwd(), "src", "modules", "brain", "corpus");
}

async function readCorpusFile(fileName: string): Promise<string> {
  return readFile(join(corpusDir(), fileName), "utf8");
}

function chunkMarkdown(content: string): Array<{ content: string; tokenEstimate: number; metadata: Record<string, unknown> }> {
  const sections = content
    .split(/\n(?=##\s+)/g)
    .map((section) => section.trim())
    .filter(Boolean);
  const chunks = sections.length ? sections : [content.trim()].filter(Boolean);
  return chunks.map((chunk, index) => ({
    content: chunk,
    tokenEstimate: Math.max(1, Math.ceil(compactText(chunk).length / 4)),
    metadata: {
      chunkSource: "system_corpus_markdown",
      chunkIndex: index,
    },
  }));
}

export function detectBrainCorpusDomains(prompt: string): BrainCorpusDomain[] {
  const normalized = prompt.toLowerCase();
  const domains: BrainCorpusDomain[] = [];
  const add = (domain: BrainCorpusDomain) => {
    if (!domains.includes(domain)) {
      domains.push(domain);
    }
  };

  if (/\b(design|website|web site|landing|ui|ux|pdf|presentation|sunum|tasar|gorsel|visual|layout|typography)\b/u.test(normalized)) {
    add("design");
  }
  if (/\b(code|kod|debug|bug|test|refactor|api|typescript|python|flutter|electron|sql|migrate|deploy)\b/u.test(normalized)) {
    add("code");
  }
  if (/\b(cevir|translate|dil|language|rewrite|writing|metin|yazi|ozet|summary|tone|uslup|turkce|english)\b/u.test(normalized)) {
    add("language");
  }
  if (/\b(data|veri|tablo|csv|excel|spreadsheet|chart|grafik|document|belge|pdf|ocr|rapor|analyze|analiz)\b/u.test(normalized)) {
    add("data");
  }
  if (/\b(skill|beceri|tool|arac|mcp|runtime|desktop|operator|attachment|ek|dosya)\b/u.test(normalized)) {
    add("skills");
  }
  if (/\b(memory|hafiza|hatirla|remember|profil|preference|tercih|gecmis)\b/u.test(normalized)) {
    add("memory");
  }
  if (/\b(plan|reason|dusun|karar|verify|dogrula|belirsiz|uncertain|risk)\b/u.test(normalized)) {
    add("reasoning");
  }
  if (/\b(safety|guvenlik|gizli|private|permission|izin|provider|model|prompt|credential|token)\b/u.test(normalized)) {
    add("safety");
  }
  if (/\b(yapabilir|yapabilirsin|yetenek|capability|capabilities|ne ise yarar|neler yapar|sinirlarin|limitations)\b/u.test(normalized)) {
    add("capabilities");
  }

  return domains;
}

// ── Deterministic corpus guidance injection (RAM-cached, C-BM25 ranked) ──────
//
// The corpus is also seeded into the knowledge DB for RAG, but prod retrieval is
// lexical-fallback (no embeddings), so design/skill guidance was not reliably
// surfacing for "rapor/tablo/pdf yap" prompts. Here we inject it deterministically:
//   * corpus markdown is read from disk ONCE and cached in-process (a few KB total,
//     no per-request I/O, no DB query — saves server storage + RAM churn),
//   * for the detected domain we pick the single most relevant `##` section using
//     the C NLP daemon's BM25 (fast, native), falling back to a tiny lexical scorer,
//   * only that capped section is injected, keeping the prompt token-cheap.

const corpusSectionCache = new Map<BrainCorpusDomain, string[]>();
const GUIDANCE_DOMAIN_LIMIT = 2;
const GUIDANCE_SECTION_CHARS = 620;

async function loadCorpusSectionsCached(
  domain: BrainCorpusDomain,
): Promise<string[]> {
  const cached = corpusSectionCache.get(domain);
  if (cached) {
    return cached;
  }
  const source = CORPUS_SOURCES.find((entry) => entry.domain === domain);
  if (!source) {
    corpusSectionCache.set(domain, []);
    return [];
  }
  try {
    const content = await readCorpusFile(source.fileName);
    const sections = content
      .split(/\n(?=##\s+)/g)
      .map((section) => section.trim())
      // İlk parça dokümanın `#` BAŞLIĞIDIR, bir rehber bölümü değil.
      // Aday listesinde kaldığı için hiçbir bölüm eşleşmeyen turlarda o
      // seçiliyor ve isteme yalnız başlık giriyordu: "Neden internete
      // bakmadın?" turunda enjekte edilen blok 106 karakterdi ve tek bir
      // yönerge içermiyordu.
      .filter((section) => section.startsWith("##"));
    corpusSectionCache.set(domain, sections);
    return sections;
  } catch {
    corpusSectionCache.set(domain, []);
    return [];
  }
}

/**
 * Sözcük örtüşme puanı — BM25 yedeği.
 *
 * İKİ AYRI KUSUR VARDI, İKİSİ DE SESSİZDİ:
 *
 *   1. Yalnız "en iyi indeks" döndürüyordu; çağıran onu 1/0 işaretleyicisine
 *      çeviriyordu. Bu, "ikinci bölüm de yeterince alakalıysa al" kuralını
 *      C daemon'ı olmayan HER ortamda etkisiz bırakıyordu — ikinci bölümün
 *      puanı tanımı gereği 0 ve hiçbir eşiği geçemez.
 *
 *   2. Ham `includes` ile boşluğa göre bölünmüş token karşılaştırıyordu.
 *      Türkçe eklemeli bir dil: "bilgiyi" hiçbir zaman "Bilgi nereden gelir"
 *      başlığına takılmıyor, buna karşılık "neler"/"ve" gibi durak kelimeler
 *      her bölümü eşit puanlıyordu. Ölçüldü: "Neler yapabilirsin ve bilgiyi
 *      nereden alıyorsun?" sorusu ikinci bölüm olarak "Neler yapamaz"ı
 *      seçiyordu — soruda geçmeyen bir konu.
 *
 * `contentTerms` bu kod tabanında zaten var ve ikisini de çözüyor: aksan
 * katlar, durak kelimeleri atar, kök bulur. Skorlayıcı onu kullanmıyordu.
 */
/**
 * KÖK BULUCU AYNI KELİMEYİ BAĞLAMA GÖRE FARKLI KÖKE İNDİRİYOR.
 *
 * Ölçüldü: başlıktaki "Bilgi" → `bilg`, sorudaki "bilgiyi" → `bilgi`.
 * `stemTurkish` tek geçişte TEK ek atar; hangi ekin atılacağı kelimenin
 * yazımına bağlı olduğu için aynı kavram iki farklı anahtara düşebiliyor.
 * Sonuç: "bilgiyi nereden alıyorsun?" sorusu "## Bilgi nereden gelir"
 * bölümüne takılmıyordu.
 *
 * `stemTurkish` getirim yolunda da kullanılıyor; onu değiştirmek bu turun
 * çok ötesine dokunur. Bunun yerine KARŞILAŞTIRMA ek-toleranslı: biri
 * diğerinin öneki ve fark küçükse aynı kavram sayılır. Asgari uzunluk ve
 * azami fark, "bir"/"birim" gibi ilgisiz çiftleri dışarıda tutar.
 */
const TERM_PREFIX_MIN_LENGTH = 4;
const TERM_PREFIX_MAX_DELTA = 3;

function termsMatch(left: string, right: string): boolean {
  if (left === right) return true;
  const [shorter, longer] = left.length <= right.length ? [left, right] : [right, left];
  return (
    shorter.length >= TERM_PREFIX_MIN_LENGTH &&
    longer.length - shorter.length <= TERM_PREFIX_MAX_DELTA &&
    longer.startsWith(shorter)
  );
}

function matchesAnyTerm(term: string, candidates: Set<string>): boolean {
  if (candidates.has(term)) return true;
  for (const candidate of candidates) {
    if (termsMatch(term, candidate)) return true;
  }
  return false;
}

function lexicalSectionScore(terms: Set<string>, section: string): number {
  if (terms.size === 0) return 0;
  // BAŞLIK İKİ KAT SAYAR. Ölçüldü: gövde üzerinden düz örtüşme üç bölümü
  // 0.200'de BERABERE bırakıyor ("neler" her ikisinde de geçiyor) ve sıralama
  // doküman sırasına düşüyor — "bilgiyi nereden alıyorsun?" sorusu ikinci
  // bölüm olarak "Neler yapamaz"ı seçiyordu. Bölümün konusunu söyleyen yer
  // başlığıdır: "## Bilgi nereden gelir" sorunun iki terimini de taşır.
  const [headingLine, ...bodyLines] = section.split("\n");
  const headingTerms = new Set(contentTerms(headingLine, { limit: 16 }));
  const bodyTerms = new Set(contentTerms(bodyLines.join(" "), { limit: 120 }));
  let score = 0;
  for (const term of terms) {
    if (matchesAnyTerm(term, headingTerms)) score += 2;
    else if (matchesAnyTerm(term, bodyTerms)) score += 1;
  }
  return score / (terms.size * 2);
}

function lexicalSectionTerms(prompt: string): Set<string> {
  return new Set(contentTerms(prompt, { limit: 24 }));
}

/**
 * ÇOK PARÇALI SORU TEK BÖLÜMLE CEVAPLANMAZ.
 *
 * ÖLÇÜLEN ARIZA: "Neler yapabilirsin ve bilgiyi nereden alıyorsun?" turunda
 * yalnız `## Neler yapabilir` enjekte edildi; `## Bilgi nereden gelir`
 * isteme hiç girmedi ve model kaynak sırasını UYDURDU — "önce sohbet,
 * ardından güncel web kaynakları ve eğitim verilerim" dedi. Korpusun
 * yazdığı sıra ise konuşma → hafıza → tipli sağlayıcı → korpus → (gerekiyorsa)
 * web. Yani kullanıcıya sistemin kendi mimarisi yanlış anlatıldı.
 *
 * İkinci bölüm BEDAVA DEĞİL, hak ederek gelir: yalnız tek alan eşleştiğinde
 * (yani soru tek konuda ama çok parçalı olduğunda) ve puanı en iyinin yarısına
 * ulaştığında alınır. Böylece iki alanlı istemlerin token bütçesi büyümez.
 */
const SECOND_SECTION_SCORE_RATIO = 0.5;

async function rankCorpusSections(
  prompt: string,
  sections: string[],
): Promise<Array<{ section: string; score: number }>> {
  try {
    const scores = await nlpDaemon.bm25Batch(
      prompt,
      sections.map((section) => compactText(section)),
    );
    if (scores && scores.length === sections.length) {
      return sections
        .map((section, index) => ({ section, score: scores[index] }))
        .sort((left, right) => right.score - left.score);
    }
  } catch {
    // daemon unavailable — fall through to lexical
  }
  const terms = lexicalSectionTerms(prompt);
  return sections
    .map((section) => ({ section, score: lexicalSectionScore(terms, section) }))
    .sort((left, right) => right.score - left.score);
}

async function pickCorpusSections(
  prompt: string,
  sections: string[],
  limit: number,
): Promise<string[]> {
  if (sections.length === 0) return [];
  if (sections.length === 1 || limit <= 1) {
    if (sections.length === 1) return [sections[0]];
    const ranked = await rankCorpusSections(prompt, sections);
    return ranked[0] ? [ranked[0].section] : [];
  }
  const ranked = await rankCorpusSections(prompt, sections);
  const best = ranked[0];
  if (!best) return [];
  const picked = [best.section];
  const runnerUp = ranked[1];
  if (
    runnerUp &&
    best.score > 0 &&
    runnerUp.score >= best.score * SECOND_SECTION_SCORE_RATIO
  ) {
    picked.push(runnerUp.section);
  }
  return picked.slice(0, limit);
}

/**
 * Builds a compact, token-disciplined guidance block from the brain corpus for
 * the detected domains. Used to make Elyan actually apply its design / skill /
 * data language when producing tables, PDFs, reports, and visual output.
 */
export async function buildBrainCorpusGuidanceBlock(
  prompt: string,
  domains: BrainCorpusDomain[],
): Promise<string | null> {
  if (domains.length === 0) {
    return null;
  }
  const orderedDomains = CORPUS_SOURCES.filter((entry) =>
    domains.includes(entry.domain),
  )
    .sort((left, right) => right.priority - left.priority)
    .map((entry) => entry.domain)
    .slice(0, GUIDANCE_DOMAIN_LIMIT);

  // Tek alan eşleştiyse soru muhtemelen tek konuda ama çok parçalı; ikinci
  // bölüme yer var. İki alan eşleştiyse bütçe zaten iki bölüme gidiyor.
  const sectionsPerDomain = orderedDomains.length === 1 ? 2 : 1;
  const picked: string[] = [];
  for (const domain of orderedDomains) {
    const sections = await loadCorpusSectionsCached(domain);
    for (const section of await pickCorpusSections(
      prompt,
      sections,
      sectionsPerDomain,
    )) {
      picked.push(section.slice(0, GUIDANCE_SECTION_CHARS).trim());
    }
  }
  if (picked.length === 0) {
    return null;
  }
  return `Elyan brain corpus guidance (apply the relevant points, do not quote this verbatim):\n\n${picked.join("\n\n")}`;
}

export function buildBrainCorpusRetrievalQuery(prompt: string): string {
  const domains = detectBrainCorpusDomains(prompt);
  if (!domains.length) {
    return prompt;
  }

  const taggedContext = CORPUS_SOURCES
    .filter((source) => domains.includes(source.domain))
    .sort((left, right) => right.priority - left.priority)
    .flatMap((source) => [source.domain, source.title, ...source.tags])
    .join(" ");

  return `${prompt}\n\nElyan brain corpus domains: ${taggedContext}`;
}

export async function getBrainCorpusManifest(): Promise<BrainCorpusDocumentManifest[]> {
  return Promise.all(
    CORPUS_SOURCES.map(async (source) => {
      const content = await readCorpusFile(source.fileName);
      return {
        ...source,
        version: ELYAN_BRAIN_CORPUS_VERSION,
        sourceUri: `brain://system-corpus/${ELYAN_BRAIN_CORPUS_VERSION}/${source.fileName}`,
        contentHash: hashText(content),
        characterCount: content.length,
      };
    }),
  );
}

export async function getBrainCorpusReadinessSummary(app: Pick<FastifyInstance, "db">) {
  const result = await app.db.execute(sql`
    select
      kd.metadata->>'elyanCorpusDomain' as "domain",
      kd.metadata->>'elyanCorpusVersion' as "version",
      count(distinct kd.id) as "documents",
      count(kc.id) as "chunks",
      max(kd.updated_at) as "latestUpdatedAt"
    from knowledge_documents kd
    left join knowledge_chunks kc on kc.document_id = kd.id
    where kd.scope = 'shared'
      and kd.status = 'ready'
      and kd.metadata->>'elyanCorpus' = 'true'
    group by kd.metadata->>'elyanCorpusDomain', kd.metadata->>'elyanCorpusVersion'
  `);
  const rows = Array.isArray(result) ? result : (result as { rows?: Array<Record<string, unknown>> }).rows ?? [];

  const categories = rows
    .map((row) => ({
      domain: String(row.domain ?? ""),
      version: String(row.version ?? ""),
      readyDocuments: Number(row.documents ?? 0),
      readyChunks: Number(row.chunks ?? 0),
      latestUpdatedAt: row.latestUpdatedAt instanceof Date ? row.latestUpdatedAt.toISOString() : null,
    }))
    .filter((row) => row.domain && row.version)
    .sort((left, right) => left.domain.localeCompare(right.domain));

  return {
    enabled: true,
    corpusVersion: ELYAN_BRAIN_CORPUS_VERSION,
    expectedDocuments: CORPUS_SOURCES.length,
    readyDocuments: categories.reduce((total, item) => total + item.readyDocuments, 0),
    readyChunks: categories.reduce((total, item) => total + item.readyChunks, 0),
    domains: categories.map((item) => item.domain),
    categories,
  };
}

export async function seedBrainCorpus(app: Pick<FastifyInstance, "db" | "log">) {
  const manifest = await getBrainCorpusManifest();
  const results: Array<{ id: string; domain: BrainCorpusDomain; documentId: string | null; action: "created" | "reused"; chunkCount: number }> = [];

  for (const entry of manifest) {
    const content = await readCorpusFile(entry.fileName);
    const existingRows = await app.db
      .select({
        id: knowledgeDocuments.id,
      })
      .from(knowledgeDocuments)
      .where(
        and(
          eq(knowledgeDocuments.scope, "shared"),
          eq(knowledgeDocuments.contentHash, entry.contentHash),
          eq(knowledgeDocuments.status, "ready"),
        ),
      )
      .limit(1);

    if (existingRows[0]) {
      await indexKnowledgeChunksForDocument(app as FastifyInstance, { documentId: existingRows[0].id }).catch((error) => {
        app.log?.warn?.({ error, corpusId: entry.id }, "brain corpus indexing skipped");
      });
      results.push({
        id: entry.id,
        domain: entry.domain,
        documentId: existingRows[0].id,
        action: "reused",
        chunkCount: 0,
      });
      continue;
    }

    await app.db
      .update(knowledgeDocuments)
      .set({
        status: "archived",
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(knowledgeDocuments.scope, "shared"),
          sql`${knowledgeDocuments.metadata}->>'elyanCorpusId' = ${entry.id}`,
        ),
      );

    const chunks = chunkMarkdown(content);
    const insertedDocuments = await app.db
      .insert(knowledgeDocuments)
      .values({
        ownerUserId: null,
        scope: "shared",
        title: entry.title,
        sourceType: "dataset",
        status: "ready",
        sourceUri: entry.sourceUri,
        contentHash: entry.contentHash,
        summary: compactText(content).slice(0, 700),
        metadata: {
          elyanCorpus: true,
          elyanCorpusId: entry.id,
          elyanCorpusDomain: entry.domain,
          elyanCorpusVersion: entry.version,
          elyanCorpusPurpose: entry.purpose,
          priority: entry.priority,
          tags: entry.tags,
          sourceFile: entry.fileName,
          characterCount: entry.characterCount,
        },
      })
      .returning({
        id: knowledgeDocuments.id,
      });
    const documentId = insertedDocuments[0]?.id;
    if (!documentId) {
      results.push({
        id: entry.id,
        domain: entry.domain,
        documentId: null,
        action: "created",
        chunkCount: 0,
      });
      continue;
    }

    await app.db.insert(knowledgeChunks).values(
      chunks.map((chunk, ordinal) => ({
        documentId,
        ownerUserId: null,
        scope: "shared" as const,
        ordinal,
        content: chunk.content,
        tokenEstimate: chunk.tokenEstimate,
        metadata: {
          ...chunk.metadata,
          elyanCorpus: true,
          elyanCorpusId: entry.id,
          elyanCorpusDomain: entry.domain,
          elyanCorpusVersion: entry.version,
          elyanCorpusPurpose: entry.purpose,
          sourceUri: entry.sourceUri,
        },
      })),
    );

    await indexKnowledgeChunksForDocument(app as FastifyInstance, { documentId }).catch((error) => {
      app.log?.warn?.({ error, corpusId: entry.id }, "brain corpus indexing skipped");
    });
    results.push({
      id: entry.id,
      domain: entry.domain,
      documentId,
      action: "created",
      chunkCount: chunks.length,
    });
  }

  return {
    corpusVersion: ELYAN_BRAIN_CORPUS_VERSION,
    expectedDocuments: manifest.length,
    created: results.filter((item) => item.action === "created").length,
    reused: results.filter((item) => item.action === "reused").length,
    results,
  };
}
