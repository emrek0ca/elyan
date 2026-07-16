import { buildHashedKnowledgeEmbedding } from "../../modules/brain/retrieval.js";
import {
  embedQueryForStorage,
  embedTextsForStorage,
} from "../../modules/brain/semantic-embedder.js";
import type { UnderstandingIntent } from "./types.js";

/**
 * Semantic fallback for the regex intent classifier.
 *
 * The rule-based classifier in `intent-classifier.ts` is fast and precise for
 * known phrasings, but it loses the intent entirely when a prompt is paraphrased
 * in a way no pattern anticipated (it then falls back to "chat"/"unknown"). This
 * module fills that gap: each classifiable intent has a small set of seed phrases
 * whose hashed embeddings are averaged into a prototype vector at module load.
 * A prompt is then assigned the nearest prototype by cosine similarity.
 *
 * It reuses the exact same hashed-embedding algorithm the C NLP core mirrors
 * (`buildHashedKnowledgeEmbedding` ↔ C `embed_256`), so the math is consistent
 * across the stack and stays cheap (no model, fully synchronous). The embedding
 * compute is only paid on the rare no-regex-match path.
 */

const INTENT_SEED_PHRASES: Partial<Record<UnderstandingIntent, string[]>> = {
  coding: [
    "bu fonksiyonu refactor et",
    "typescript ile bir api yaz",
    "şu kodu implemente et",
    "write a python function for this",
    "add a unit test for this module",
  ],
  debugging: [
    "kod çalışmıyor hata veriyor",
    "bu exception'ı düzelt",
    "uygulama crash oluyor neden",
    "fix this failing build",
    "why does this throw a stack trace",
  ],
  research: [
    "bunu araştır ve kaynak göster",
    "güncel verilerle karşılaştır",
    "en son gelişmeleri incele",
    "find sources and cite them",
    "verify these facts online",
  ],
  writing: [
    "bu metni düzenle ve akıcı yap",
    "bir mail taslağı yaz",
    "şunu profesyonelce özetle",
    "rewrite this paragraph politely",
    "proofread and fix the grammar",
  ],
  math: [
    "bu denklemi çöz",
    "integralini hesapla",
    "şu problemi adım adım çöz",
    "solve this equation",
    "compute the derivative",
  ],
  document: [
    "bu pdf'i oku ve özetle",
    "belgenin içinde ne yazıyor",
    "excel tablosunu dışa aktar",
    "extract the text from this document",
    "convert this file to docx",
  ],
  image: [
    "bu görseli analiz et",
    "fotoğraftan metni çıkar",
    "bir resim oluştur",
    "describe what is in this photo",
    "generate an image of a landscape",
  ],
  automation: [
    "bunu her sabah otomatik çalıştır",
    "bir iş akışı kur",
    "şu görevi zamanla ve tetikle",
    "automate this workflow",
    "schedule a recurring task",
  ],
  browser: [
    "şu siteyi aç ve gez",
    "web sayfasından veri çek",
    "tarayıcıda bu butona tıkla",
    "navigate to this website",
    "scrape this web page",
  ],
  computer: [
    "masaüstünde şu dosyayı aç",
    "ekran görüntüsü al",
    "bilgisayarda bir pencere aç",
    "take a screenshot of the desktop",
    "press a hotkey on my machine",
  ],
  planning: [
    "bir yol haritası çıkar",
    "bu projeyi adımlara böl",
    "stratejiyi ve mimariyi planla",
    "break this down into a roadmap",
    "design the system architecture",
  ],
};

function averagePrototype(phrases: string[]): number[] {
  const vectors = phrases.map((phrase) => buildHashedKnowledgeEmbedding(phrase));
  const dim = vectors[0]?.length ?? 0;
  const sum = new Array<number>(dim).fill(0);
  for (const vector of vectors) {
    for (let i = 0; i < dim; i += 1) {
      sum[i] += vector[i] ?? 0;
    }
  }
  const magnitude = Math.sqrt(sum.reduce((acc, value) => acc + value * value, 0));
  if (magnitude <= 0) {
    return sum;
  }
  return sum.map((value) => value / magnitude);
}

const INTENT_PROTOTYPES: Array<{ intent: UnderstandingIntent; vector: number[] }> = Object.entries(
  INTENT_SEED_PHRASES,
).map(([intent, phrases]) => ({
  intent: intent as UnderstandingIntent,
  vector: averagePrototype(phrases ?? []),
}));

function dot(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  let sum = 0;
  for (let i = 0; i < n; i += 1) {
    sum += a[i] * b[i];
  }
  return sum;
}

export type SemanticTextCandidate = {
  id: string;
  description: string;
};

export type SemanticTextCandidateMatch = {
  id: string;
  score: number;
  margin: number;
  source: "transformer" | "hash";
};

function bestCandidateMatch(
  queryVector: number[],
  candidates: SemanticTextCandidate[],
  vectors: number[][],
): { id: string; score: number; margin: number } | null {
  // A capability may expose several multilingual semantic descriptions. Score
  // each description, then keep only the strongest score per capability id so
  // aliases/prototypes do not compete with themselves and inflate the margin.
  const bestScoreById = new Map<string, number>();
  candidates.forEach((candidate, index) => {
    const score = dot(queryVector, vectors[index] ?? []);
    const previous = bestScoreById.get(candidate.id);
    if (previous === undefined || score > previous) {
      bestScoreById.set(candidate.id, score);
    }
  });
  const ranked = [...bestScoreById.entries()]
    .map(([id, score]) => ({ id, score }))
    .sort((left, right) => right.score - left.score);
  const best = ranked[0];
  if (!best) return null;
  return {
    ...best,
    margin: best.score - (ranked[1]?.score ?? 0),
  };
}

/**
 * Generic semantic registry matcher. Callers supply current registry/catalog
 * descriptions, so adding a new tool or MCP app teaches the router through its
 * existing contract instead of adding another user-sentence regex.
 *
 * The multilingual e5 worker is primary. The existing hash embedding remains
 * a cheap degraded-mode signal and is explicitly identified in the result so
 * permission-sensitive callers can choose to fail closed.
 */
export async function rankSemanticTextCandidates(
  text: string,
  candidates: SemanticTextCandidate[],
  options: {
    transformerMinScore?: number;
    transformerMinMargin?: number;
    transformerTimeoutMs?: number;
    hashMinScore?: number;
    hashMinMargin?: number;
  } = {},
): Promise<SemanticTextCandidateMatch | null> {
  const trimmed = text.replace(/\s+/g, " ").trim();
  const usableCandidates = candidates.filter(
    (candidate) => candidate.id.trim() && candidate.description.trim(),
  );
  if (!trimmed || usableCandidates.length === 0) return null;

  const [semanticVectors, semanticQuery] = await Promise.all([
    embedTextsForStorage(
      usableCandidates.map((candidate) => candidate.description),
      undefined,
      "understanding-semantic-registry-v1",
      options.transformerTimeoutMs,
    ),
    embedQueryForStorage(
      trimmed,
      undefined,
      undefined,
      options.transformerTimeoutMs,
    ),
  ]).catch(() => [null, null] as const);
  if (semanticVectors && semanticQuery) {
    const match = bestCandidateMatch(
      semanticQuery,
      usableCandidates,
      semanticVectors,
    );
    if (
      match &&
      match.score >= (options.transformerMinScore ?? 0.62) &&
      match.margin >= (options.transformerMinMargin ?? 0.015)
    ) {
      return { ...match, source: "transformer" };
    }
    return null;
  }

  const hashMatch = bestCandidateMatch(
    buildHashedKnowledgeEmbedding(trimmed),
    usableCandidates,
    usableCandidates.map((candidate) =>
      buildHashedKnowledgeEmbedding(candidate.description),
    ),
  );
  if (
    !hashMatch ||
    hashMatch.score < (options.hashMinScore ?? 0.18) ||
    hashMatch.margin < (options.hashMinMargin ?? 0.04)
  ) {
    return null;
  }
  return { ...hashMatch, source: "hash" };
}

/**
 * Returns the nearest intent prototype to `text` by cosine similarity, or null
 * when the text is empty or the best match is too weak to be meaningful.
 * Both the query and prototype vectors are L2-normalized, so the dot product is
 * the cosine similarity directly.
 */
export function classifyIntentSemantic(
  text: string,
  minScore = 0.18,
): { intent: UnderstandingIntent; score: number } | null {
  const trimmed = text.trim();
  if (trimmed.length === 0) {
    return null;
  }
  const queryVector = buildHashedKnowledgeEmbedding(trimmed);
  let best: { intent: UnderstandingIntent; score: number } | null = null;
  for (const prototype of INTENT_PROTOTYPES) {
    const score = dot(queryVector, prototype.vector);
    if (!best || score > best.score) {
      best = { intent: prototype.intent, score };
    }
  }
  if (!best || best.score < minScore) {
    return null;
  }
  return best;
}

// ── Transformer-based intent classification (real semantic) ──────────────────
//
// Hash embeddings are essentially bag-of-tokens — they miss paraphrases and
// mostly-different-words synonyms. The e5-small model already loaded for
// storage embeddings gives true multilingual semantic matching at ~50ms per
// call (warm). When the model is unavailable, the hash path above is kept as
// a synchronous fallback.

let transformerPrototypesPromise:
  | Promise<Array<{ intent: UnderstandingIntent; vector: number[] }> | null>
  | null = null;

async function loadTransformerPrototypes(): Promise<
  Array<{ intent: UnderstandingIntent; vector: number[] }> | null
> {
  if (transformerPrototypesPromise) return transformerPrototypesPromise;
  transformerPrototypesPromise = (async () => {
    // Build one consolidated "passage" per intent by joining its seed phrases.
    // This gives a single 384-dim prototype per intent rather than averaging
    // multiple embeddings (which is what the e5 model is trained for: pooled
    // passage representation).
    const entries = Object.entries(INTENT_SEED_PHRASES).filter(
      ([, phrases]) => Array.isArray(phrases) && phrases.length > 0,
    );
    const passages = entries.map(([, phrases]) => phrases!.join(". "));
    const vectors = await embedTextsForStorage(passages);
    if (!vectors) return null;
    return entries.map(([intent], index) => ({
      intent: intent as UnderstandingIntent,
      vector: vectors[index]!,
    }));
  })();
  return transformerPrototypesPromise;
}

/**
 * Real semantic intent classification using the e5-small storage embedder.
 * Returns null when the model is unavailable so callers can fall back to the
 * synchronous hash classifier. The transformer call is ~50ms warm; only worth
 * paying for the no-regex-match path (caller is intent-classifier.ts).
 */
export async function classifyIntentTransformer(
  text: string,
  minScore = 0.62,
): Promise<{ intent: UnderstandingIntent; score: number } | null> {
  const trimmed = text.trim();
  if (trimmed.length === 0) return null;
  const [prototypes, queryVector] = await Promise.all([
    loadTransformerPrototypes(),
    embedQueryForStorage(trimmed),
  ]);
  if (!prototypes || !queryVector) return null;
  let best: { intent: UnderstandingIntent; score: number } | null = null;
  for (const prototype of prototypes) {
    const score = dot(queryVector, prototype.vector);
    if (!best || score > best.score) {
      best = { intent: prototype.intent, score };
    }
  }
  // e5 vectors live in a tighter similarity range than hash vectors, so a
  // higher minScore guards against weak matches polluting routing decisions.
  if (!best || best.score < minScore) return null;
  return best;
}
