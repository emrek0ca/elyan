import { sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  searchKnowledge as searchKnowledgeCore,
  type RetrievalSearchResult,
} from "./retrieval.js";

/**
 * RAG orkestratörü — Elyan beyninin gelişmiş retrieval katmanı.
 *
 * Mevcut çekirdek (vector: e5-small/pgvector + hash fallback, lexical: ILIKE,
 * opsiyonel semantic rerank) üzerine dört teknik ekler:
 *
 * 1. Keyword RAG (BM25 sınıfı): Postgres full-text (websearch_to_tsquery +
 *    ts_rank_cd) — tam kelime/ifade eşleşmesi gereken sorgularda vektör
 *    benzerliğinin kaçırdığı sonuçları getirir.
 * 2. Hybrid füzyon (RRF): vector/lexical/keyword listeleri Reciprocal Rank
 *    Fusion ile birleşir — skor ölçekleri uyumsuz olsa bile adil sıralama.
 * 3. Adaptive + Agentic strateji: sorgu şekline göre hangi arama kollarının
 *    koşacağına ve ağırlıklara orkestratör karar verir (tırnaklı/kimlikli
 *    sorgu → keyword ağırlıklı; ilişkisel çok-varlıklı soru → multi-hop).
 * 4. Multi-hop + Self-RAG lite: bileşik sorular deterministik alt-sorgulara
 *    ayrılır ve ayrı aramalar birleştirilir; kapsama (coverage) düşükse
 *    anahtar-terim reformülasyonuyla ikinci tur atılır. Sonuçta hâlâ zayıfsa
 *    çağırana lowConfidence işareti döner (halüsinasyon freni).
 * 5. Graph-lite bağlam genişletme: en iyi eşleşmelerin aynı dokümandaki
 *    komşu chunk'ları (ordinal ±1) düşük skorla eklenir — parçalanmış
 *    bilgiler bağlamıyla gelir.
 *
 * Hepsi LLM çağrısı olmadan, deterministik ve tek istek bütçesi içinde
 * çalışır; çekirdek arama başarısız olursa davranış çekirdekle aynıdır.
 */

export type RetrievalStrategy = "hybrid" | "keyword_heavy" | "multi_hop";

export type OrchestratedRetrieval = {
  retrievalMode: string;
  results: RetrievalSearchResult[];
  retrievalResultCount: number;
  degradedReason: string | null;
  /** Orkestratör telemetrisi — prompt'a girmez, teşhis içindir. */
  orchestration: {
    strategy: RetrievalStrategy;
    hops: string[];
    keywordCandidates: number;
    coreCandidates: number;
    coverage: number;
    evidenceAcceptance: {
      score: number;
      threshold: number;
      subquestionCount: number;
      supportedSubquestionCount: number;
      unsupportedSubquestionCount: number;
    };
    neuralPolicy: {
      semanticRerankAdmitted: boolean;
      selfCheckSensitivity: "normal" | "strict";
      reason: string;
    };
    selfCheckRetried: boolean;
    lowConfidence: boolean;
    neighborExpanded: number;
  };
};

const RRF_K = 60;
const COVERAGE_RETRY_THRESHOLD = 0.34;
const EVIDENCE_ACCEPTANCE_THRESHOLD = 0.45;
const NEIGHBOR_EXPANSION_TOP = 3;

const _TR_STOPWORDS = new Set([
  "acaba", "ama", "ancak", "bana", "bazı", "belki", "ben", "beni", "bir", "biraz",
  "biri", "bize", "bu", "bunu", "bunun", "da", "daha", "de", "değil", "diye",
  "en", "gibi", "hangi", "hem", "her", "hiç", "için", "ile", "ise", "işte",
  "kadar", "kim", "mi", "mı", "mu", "mü", "ne", "neden", "nasıl", "nerede",
  "niye", "o", "olan", "olarak", "sana", "sen", "sonra", "şey", "şu", "the",
  "ve", "veya", "ya", "yani", "zaman", "and", "or", "what", "when", "where",
  "how", "who", "is", "are", "was", "a", "an", "of", "in", "on", "to", "for",
]);

function foldTr(value: string): string {
  return value
    .replace(/İ/g, "i")
    .replace(/I/g, "i")
    .replace(/ı/g, "i")
    .toLowerCase();
}

function keyTerms(query: string, limit = 8): string[] {
  const tokens = foldTr(query)
    .split(/[^a-zçğıöşü0-9_.-]+/i)
    .map((token) => token.trim())
    .filter((token) => token.length >= 3 && !_TR_STOPWORDS.has(token));
  return [...new Set(tokens)].slice(0, limit);
}

/** Adaptive/agentic strateji seçimi — sorgu şekline göre arama planı. */
export function classifyRetrievalStrategy(query: string): RetrievalStrategy {
  const compact = query.trim();
  // Tırnaklı ifade, dosya adı/uzantı, kod kimliği, sayı-ağırlıklı sorgu →
  // tam eşleşme kritik: keyword kolu ağır bassın.
  if (
    /["'«»][^"'«»]{3,}["'«»]/.test(compact) ||
    /\.\w{2,4}\b/.test(compact) ||
    /\b[A-Z0-9_]{2,}[-_][A-Z0-9_]+\b/i.test(compact) ||
    /\b\d{4,}\b/.test(compact)
  ) {
    return "keyword_heavy";
  }
  // Bileşik/ilişkisel soru: iki+ cümlecik, karşılaştırma veya zincir soru →
  // multi-hop ayrıştırma dener.
  const folded = foldTr(compact);
  // Desen kelimeleri foldTr çıktısıyla (ı→i) hizalı; \b Türkçe harflerde
  // güvenilmez olduğundan boşluk sınırlı eşleşme kullanılır.
  const connectorHits = (folded.match(/(?:^|\s)(ve ayrica|ayrica|hem de|önce|sonra|ardindan|karşilaştir|farki|arasinda)(?=\s|$|[.,;:!?])/g) ?? []).length;
  const questionMarks = (compact.match(/\?/g) ?? []).length;
  if (connectorHits >= 1 && compact.length > 60) return "multi_hop";
  if (questionMarks >= 2) return "multi_hop";
  return "hybrid";
}

/** Bileşik sorguyu deterministik alt-sorgulara ayırır (LLM'siz multi-hop). */
export function decomposeQuery(query: string): string[] {
  const parts = query
    .split(/\?|(?:\b(?:ve ayrıca|ayrıca|hem de|ardından|sonra da)\b)|;|\n/gi)
    .map((part) => part.trim())
    .filter((part) => part.length >= 12);
  if (parts.length <= 1) return [query];
  return [query, ...parts.slice(0, 3)];
}

/** BM25 sınıfı keyword arama: Postgres FTS, turkish → simple fallback. */
async function searchKnowledgeKeyword(
  app: FastifyInstance,
  input: { userId: string; query: string; limit: number },
): Promise<RetrievalSearchResult[]> {
  const terms = keyTerms(input.query);
  if (terms.length === 0) return [];
  const tsQuery = terms.join(" ");
  const run = async (config: string) => {
    const rows = await app.db.execute(sql`
      select
        kd.id as "documentId",
        kd.title as "title",
        kd.source_type as "sourceType",
        kd.source_uri as "sourceUri",
        kd.summary as "summary",
        kc.scope as "scope",
        kc.id as "chunkId",
        kc.ordinal as "ordinal",
        kc.content as "content",
        kc.token_estimate as "tokenEstimate",
        kc.metadata as "metadata",
        kd.updated_at as "updatedAt",
        ts_rank_cd(
          to_tsvector(${config}::regconfig, coalesce(kc.content, '')),
          websearch_to_tsquery(${config}::regconfig, ${tsQuery})
        ) as "keywordScore"
      from knowledge_chunks kc
      inner join knowledge_documents kd on kd.id = kc.document_id
      where kd.status = 'ready'
        and (kc.scope = 'shared' or kc.owner_user_id = ${input.userId})
        -- İfade 0044 GIN indeksiyle birebir aynı (content-only) — title
        -- eşleşmesini lexical/vector kolları zaten kapsıyor.
        and to_tsvector(${config}::regconfig, coalesce(kc.content, ''))
            @@ websearch_to_tsquery(${config}::regconfig, ${tsQuery})
      order by "keywordScore" desc
      limit ${Math.max(input.limit * 3, 12)}
    `);
    return Array.isArray(rows)
      ? rows
      : ((rows as { rows?: Array<Record<string, unknown>> }).rows ?? []);
  };
  let rawRows: Array<Record<string, unknown>>;
  try {
    rawRows = await run("turkish");
  } catch {
    try {
      rawRows = await run("simple");
    } catch {
      return [];
    }
  }
  return rawRows.map((row) => ({
    documentId: String(row.documentId),
    chunkId: String(row.chunkId),
    title: String(row.title ?? ""),
    scope: String(row.scope ?? "user") as RetrievalSearchResult["scope"],
    sourceType: String(row.sourceType ?? "note"),
    sourceUri: row.sourceUri == null ? null : String(row.sourceUri),
    summary: row.summary == null ? null : String(row.summary),
    content: String(row.content ?? ""),
    tokenEstimate: Number(row.tokenEstimate ?? 0),
    ordinal: Number(row.ordinal ?? 0),
    metadata: row.metadata ?? {},
    score: Number(Number(row.keywordScore ?? 0).toFixed(4)),
    updatedAt:
      row.updatedAt instanceof Date
        ? row.updatedAt
        : new Date(String(row.updatedAt ?? Date.now())),
  }));
}

/** Reciprocal Rank Fusion — skor ölçeğinden bağımsız adil liste birleşimi. */
export function fuseWithRrf(
  lists: Array<{ results: RetrievalSearchResult[]; weight: number }>,
): RetrievalSearchResult[] {
  const fused = new Map<string, { item: RetrievalSearchResult; score: number }>();
  for (const { results, weight } of lists) {
    results.forEach((item, rank) => {
      const key = item.chunkId;
      const contribution = weight / (RRF_K + rank + 1);
      const existing = fused.get(key);
      if (existing) {
        existing.score += contribution;
      } else {
        fused.set(key, { item, score: contribution });
      }
    });
  }
  return [...fused.values()]
    .sort((left, right) => right.score - left.score)
    .map(({ item, score }) => ({ ...item, score: Number(score.toFixed(6)) }));
}

/** Self-RAG lite kapsama ölçütü: sorgu anahtar terimlerinin top sonuçlarda
 * görülme oranı. Düşükse kanıt zayıf demektir. */
export function coverageScore(query: string, results: RetrievalSearchResult[]): number {
  const terms = keyTerms(query);
  if (terms.length === 0 || results.length === 0) return results.length > 0 ? 1 : 0;
  const haystack = foldTr(
    results
      .slice(0, 5)
      .map((result) => `${result.title} ${result.content}`)
      .join(" "),
  );
  const hits = terms.filter((term) => haystack.includes(term)).length;
  return hits / terms.length;
}

function supportScoreForQuestion(
  question: string,
  results: RetrievalSearchResult[],
): number {
  const terms = keyTerms(question, 10);
  if (terms.length === 0) return results.length > 0 ? 1 : 0;
  if (results.length === 0) return 0;
  const topResults = results.slice(0, 5);
  const titleHits = new Set<string>();
  const contentHits = new Set<string>();
  for (const result of topResults) {
    const title = foldTr(result.title);
    const content = foldTr(result.content);
    for (const term of terms) {
      if (title.includes(term)) titleHits.add(term);
      if (content.includes(term)) contentHits.add(term);
    }
  }
  const titleCoverage = titleHits.size / terms.length;
  const contentCoverage = contentHits.size / terms.length;
  return Math.max(contentCoverage, titleCoverage * 0.75);
}

function evidenceAcceptanceScore(
  query: string,
  hops: string[],
  results: RetrievalSearchResult[],
): OrchestratedRetrieval["orchestration"]["evidenceAcceptance"] {
  const subquestions = [...new Set([query, ...hops])]
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
    .slice(0, 4);
  if (subquestions.length === 0) {
    return {
      score: results.length > 0 ? 1 : 0,
      threshold: EVIDENCE_ACCEPTANCE_THRESHOLD,
      subquestionCount: 0,
      supportedSubquestionCount: results.length > 0 ? 1 : 0,
      unsupportedSubquestionCount: results.length > 0 ? 0 : 1,
    };
  }
  const scores = subquestions.map((question) =>
    supportScoreForQuestion(question, results),
  );
  const supportedSubquestionCount = scores.filter(
    (score) => score >= EVIDENCE_ACCEPTANCE_THRESHOLD,
  ).length;
  const score =
    scores.reduce((sum, value) => sum + value, 0) / Math.max(1, scores.length);
  return {
    score: Number(score.toFixed(3)),
    threshold: EVIDENCE_ACCEPTANCE_THRESHOLD,
    subquestionCount: subquestions.length,
    supportedSubquestionCount,
    unsupportedSubquestionCount: subquestions.length - supportedSubquestionCount,
  };
}

/** Graph-lite: en iyi eşleşmelerin komşu chunk'larını (aynı doküman, ordinal
 * ±1) getirir — bölünmüş bilgi bağlamıyla tamamlanır. */
async function expandNeighbors(
  app: FastifyInstance,
  userId: string,
  top: RetrievalSearchResult[],
  exclude: Set<string>,
): Promise<RetrievalSearchResult[]> {
  const targets = top.slice(0, NEIGHBOR_EXPANSION_TOP);
  if (targets.length === 0) return [];
  const clauses = targets.map(
    (t) =>
      sql`(kc.document_id = ${t.documentId} and kc.ordinal in (${t.ordinal - 1}, ${t.ordinal + 1}))`,
  );
  let whereNeighbors = clauses[0]!;
  for (const clause of clauses.slice(1)) {
    whereNeighbors = sql`${whereNeighbors} or ${clause}`;
  }
  try {
    const rows = await app.db.execute(sql`
      select
        kd.id as "documentId",
        kd.title as "title",
        kd.source_type as "sourceType",
        kd.source_uri as "sourceUri",
        kd.summary as "summary",
        kc.scope as "scope",
        kc.id as "chunkId",
        kc.ordinal as "ordinal",
        kc.content as "content",
        kc.token_estimate as "tokenEstimate",
        kc.metadata as "metadata",
        kd.updated_at as "updatedAt"
      from knowledge_chunks kc
      inner join knowledge_documents kd on kd.id = kc.document_id
      where kd.status = 'ready'
        and (kc.scope = 'shared' or kc.owner_user_id = ${userId})
        and (${whereNeighbors})
      limit 8
    `);
    const rawRows = Array.isArray(rows)
      ? rows
      : ((rows as { rows?: Array<Record<string, unknown>> }).rows ?? []);
    return rawRows
      .filter((row) => !exclude.has(String(row.chunkId)))
      .map((row) => ({
        documentId: String(row.documentId),
        chunkId: String(row.chunkId),
        title: String(row.title ?? ""),
        scope: String(row.scope ?? "user") as RetrievalSearchResult["scope"],
        sourceType: String(row.sourceType ?? "note"),
        sourceUri: row.sourceUri == null ? null : String(row.sourceUri),
        summary: row.summary == null ? null : String(row.summary),
        content: String(row.content ?? ""),
        tokenEstimate: Number(row.tokenEstimate ?? 0),
        ordinal: Number(row.ordinal ?? 0),
        metadata: { ...(typeof row.metadata === "object" && row.metadata !== null ? row.metadata : {}), neighborExpansion: true },
        score: 0.01,
        updatedAt:
          row.updatedAt instanceof Date
            ? row.updatedAt
            : new Date(String(row.updatedAt ?? Date.now())),
      }));
  } catch {
    return [];
  }
}

/**
 * Gelişmiş bilgi araması — çekirdek searchKnowledge'ın drop-in üstünü.
 * Dönüş şekli çekirdekle geriye dönük uyumludur (retrievalMode/results/
 * degradedReason) + orchestration telemetrisi.
 */
export async function searchKnowledge(
  app: FastifyInstance,
  input: {
    userId: string;
    query: string;
    limit: number;
    neuralPolicy?: {
      neuralReady?: boolean;
      embeddingReady?: boolean;
      evaluationReady?: boolean;
    };
  },
): Promise<OrchestratedRetrieval> {
  const strategy = classifyRetrievalStrategy(input.query);
  const hops = strategy === "multi_hop" ? decomposeQuery(input.query) : [input.query];
  const semanticRerankAdmitted =
    input.neuralPolicy?.neuralReady === true ||
    input.neuralPolicy?.embeddingReady === true;
  const selfCheckSensitivity =
    input.neuralPolicy?.evaluationReady === true ? "normal" : "strict";
  const evidenceThreshold =
    selfCheckSensitivity === "strict"
      ? Math.max(EVIDENCE_ACCEPTANCE_THRESHOLD, 0.55)
      : EVIDENCE_ACCEPTANCE_THRESHOLD;

  // Arama kolları: her hop için çekirdek (vector+lexical+rerank) + keyword.
  const coreWeight = strategy === "keyword_heavy" ? 0.7 : 1.0;
  const keywordWeight = strategy === "keyword_heavy" ? 1.0 : 0.6;

  const [coreRuns, keywordRuns] = await Promise.all([
    Promise.all(
      hops.map((hop) =>
        searchKnowledgeCore(app, {
          ...input,
          query: hop,
          semanticRerankReady: semanticRerankAdmitted,
        }).catch(() => null),
      ),
    ),
    Promise.all(
      hops.map((hop) =>
        searchKnowledgeKeyword(app, { ...input, query: hop }).catch(() => [] as RetrievalSearchResult[]),
      ),
    ),
  ]);

  const primaryCore = coreRuns[0];
  const lists: Array<{ results: RetrievalSearchResult[]; weight: number }> = [];
  coreRuns.forEach((run, index) => {
    if (run?.results?.length) {
      // İlk hop (tam sorgu) tam ağırlık; alt-hop'lar hafif düşük.
      lists.push({ results: run.results, weight: coreWeight * (index === 0 ? 1 : 0.8) });
    }
  });
  keywordRuns.forEach((results, index) => {
    if (results.length) {
      lists.push({ results, weight: keywordWeight * (index === 0 ? 1 : 0.8) });
    }
  });

  let fused = fuseWithRrf(lists);
  let coverage = coverageScore(input.query, fused);
  let selfCheckRetried = false;

  // Self-RAG lite: kanıt zayıfsa anahtar-terim reformülasyonuyla bir tur daha.
  if (coverage < COVERAGE_RETRY_THRESHOLD) {
    const reformulated = keyTerms(input.query).join(" ");
    if (reformulated && foldTr(reformulated) !== foldTr(input.query.trim())) {
      selfCheckRetried = true;
      const [retryCore, retryKeyword] = await Promise.all([
        searchKnowledgeCore(app, {
          ...input,
          query: reformulated,
          semanticRerankReady: semanticRerankAdmitted,
        }).catch(() => null),
        searchKnowledgeKeyword(app, { ...input, query: reformulated }).catch(
          () => [] as RetrievalSearchResult[],
        ),
      ]);
      const retryLists = [...lists];
      if (retryCore?.results?.length) retryLists.push({ results: retryCore.results, weight: 0.7 });
      if (retryKeyword.length) retryLists.push({ results: retryKeyword, weight: 0.7 });
      const retryFused = fuseWithRrf(retryLists);
      const retryCoverage = coverageScore(input.query, retryFused);
      if (retryCoverage > coverage) {
        fused = retryFused;
        coverage = retryCoverage;
      }
    }
  }

  const top = fused.slice(0, input.limit);
  // Graph-lite bağlam genişletme: limit dolmadıysa komşu chunk'larla doldur.
  let neighborExpanded = 0;
  if (top.length > 0 && top.length < input.limit) {
    const exclude = new Set(fused.map((result) => result.chunkId));
    const neighbors = await expandNeighbors(app, input.userId, top, exclude);
    neighborExpanded = Math.min(neighbors.length, input.limit - top.length);
    top.push(...neighbors.slice(0, input.limit - top.length));
  }
  const evidenceAcceptance = evidenceAcceptanceScore(input.query, hops, top);
  const evidenceAcceptanceForPolicy = {
    ...evidenceAcceptance,
    threshold: evidenceThreshold,
  };

  const keywordCandidates = keywordRuns.reduce((sum, list) => sum + list.length, 0);
  const coreCandidates = coreRuns.reduce(
    (sum, run) => sum + (run?.results?.length ?? 0),
    0,
  );
  return {
    retrievalMode: primaryCore?.retrievalMode ?? "lexical_fallback",
    results: top,
    retrievalResultCount: top.length,
    degradedReason: primaryCore?.degradedReason ?? (coreCandidates === 0 && keywordCandidates === 0 ? "retrieval_unavailable" : null),
    orchestration: {
      strategy,
      hops,
      keywordCandidates,
      coreCandidates,
      coverage: Number(coverage.toFixed(3)),
      evidenceAcceptance: evidenceAcceptanceForPolicy,
      neuralPolicy: {
        semanticRerankAdmitted,
        selfCheckSensitivity,
        reason: semanticRerankAdmitted
          ? "neural_readiness_admitted_semantic_rerank"
          : "neural_readiness_withheld_semantic_rerank",
      },
      selfCheckRetried,
      lowConfidence:
        top.length > 0 &&
        (coverage < COVERAGE_RETRY_THRESHOLD ||
          evidenceAcceptance.score < evidenceThreshold ||
          evidenceAcceptance.unsupportedSubquestionCount > 0),
      neighborExpanded,
    },
  };
}
