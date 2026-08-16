import { buildHashedKnowledgeEmbedding } from "../../modules/brain/retrieval.js";
import {
  embedQueryForStorage,
  embedTextsForStorage,
} from "../../modules/brain/semantic-embedder.js";
import { isSemanticComputeWorkerWarm } from "../../modules/brain/semantic-compute-client.js";
import type {
  IntentClassification,
  UnderstandingIntent,
} from "./types.js";
import type { OutputContract } from "./output-contract.js";

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
    "bu fonksiyon yanlış sonuç veriyor neden",
    "kodun sonucu beklediğimden farklı, sebebini bul",
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
    "ileri analiz dersinden örnek soru hazırla",
    "kalkülüs dersi için problem üret",
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
    /** Do not wait for the asynchronous E5 startup warmup on request paths. */
    requireWarmWorker?: boolean;
    hashMinScore?: number;
    hashMinMargin?: number;
  } = {},
): Promise<SemanticTextCandidateMatch | null> {
  const trimmed = text.replace(/\s+/g, " ").trim();
  const usableCandidates = candidates.filter(
    (candidate) => candidate.id.trim() && candidate.description.trim(),
  );
  if (!trimmed || usableCandidates.length === 0) return null;
  if (options.requireWarmWorker && !isSemanticComputeWorkerWarm()) return null;

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
  minScore = 0.28,
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

export const semanticContractConversationModeValues = [
  "chat",
  "execute",
  "hybrid",
] as const;

export const semanticContractSurfaceValues = [
  "server_brain",
  "desktop_runtime",
  "hybrid",
] as const;

export const semanticContractIntentValues = [
  "answer",
  "research",
  "create",
  "inspect",
  "modify",
  "automate",
] as const;

export const semanticContractArtifactValues = [
  "none",
  "text",
  "image",
  "document",
  "data",
] as const;

export const semanticContractContextValues = [
  "none",
  "local_files",
  "screen",
  "browser",
  "app",
] as const;

export const semanticContractSideEffectValues = [
  "none",
  "read",
  "write",
  "destructive",
] as const;

export const semanticContractPrivacyValues = [
  "public",
  "account",
  "local_private",
] as const;

export type SemanticContract = {
  schemaVersion: "elyan.semantic_contract.v1";
  conversationMode: (typeof semanticContractConversationModeValues)[number];
  surface: (typeof semanticContractSurfaceValues)[number];
  intent: (typeof semanticContractIntentValues)[number];
  artifact: (typeof semanticContractArtifactValues)[number];
  requiredContext: Array<(typeof semanticContractContextValues)[number]>;
  sideEffect: (typeof semanticContractSideEffectValues)[number];
  privacyClass: (typeof semanticContractPrivacyValues)[number];
  requiredCapabilities: string[];
  needsApproval: boolean;
  confidence: number;
  ambiguity: number;
  evidence: string[];
};

function clampSemanticScore(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, Number(value.toFixed(3))));
}

function uniqueSemanticValues(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function semanticIntentForClassification(
  classification: IntentClassification,
  outputContract: OutputContract,
): SemanticContract["intent"] {
  if (classification.requiresLocalRuntime) return "automate";
  if (outputContract.operation === "edit") {
    return "modify";
  }
  if (outputContract.requiresArtifact) return "create";
  if (classification.primaryIntent === "research") return "research";
  if (
    classification.primaryIntent === "document" ||
    classification.primaryIntent === "image"
  ) {
    return "inspect";
  }
  return "answer";
}

function semanticArtifactForOutput(
  outputContract: OutputContract,
): SemanticContract["artifact"] {
  if (!outputContract.requiresArtifact) return "none";
  if (outputContract.outputKind === "image" || outputContract.outputKind === "svg") {
    return "image";
  }
  if (outputContract.outputKind === "document") return "document";
  if (
    outputContract.outputKind === "table" ||
    outputContract.outputKind === "chart"
  ) {
    return "data";
  }
  return "text";
}

function semanticContextForClassification(
  classification: IntentClassification,
): SemanticContract["requiredContext"] {
  if (!classification.requiresLocalRuntime) return ["none"];
  if (
    classification.primaryIntent === "browser" ||
    classification.secondaryIntents.includes("browser")
  ) {
    return ["browser"];
  }
  if (
    classification.primaryIntent === "computer" ||
    classification.secondaryIntents.includes("computer")
  ) {
    return ["screen", "app"];
  }
  return ["local_files"];
}

function semanticSideEffectForTurn(input: {
  classification: IntentClassification;
  outputContract: OutputContract;
}): SemanticContract["sideEffect"] {
  if (!input.classification.requiresLocalRuntime) return "none";
  if (input.outputContract.operation === "edit") return "write";
  if (
    input.classification.primaryIntent === "automation" ||
    input.outputContract.operation === "create" ||
    input.outputContract.operation === "export" ||
    input.outputContract.operation === "transform"
  ) {
    return "write";
  }
  return "read";
}

function requiredCapabilitiesForContract(input: {
  classification: IntentClassification;
  artifact: SemanticContract["artifact"];
  sideEffect: SemanticContract["sideEffect"];
}): string[] {
  const capabilities: string[] = [];
  const primary = input.classification.primaryIntent;
  if (primary === "research" || input.classification.requiresCitation) {
    capabilities.push("web_research");
  }
  if (primary === "document") capabilities.push("document.read");
  if (primary === "image") capabilities.push("image.read");
  if (primary === "browser") capabilities.push("browser.read");
  if (primary === "computer") capabilities.push("desktop.runtime");
  if (primary === "automation") capabilities.push("automation.schedule");
  if (input.artifact === "document") capabilities.push("document.write");
  if (input.artifact === "data") capabilities.push("data.generate");
  if (input.artifact === "image") capabilities.push("image.generate");
  if (input.sideEffect === "write") capabilities.push("filesystem.write");
  return uniqueSemanticValues(capabilities);
}

/**
 * Builds the single request-scoped semantic contract consumed by routing and
 * the worker. Raw text interpretation belongs here; downstream layers must
 * use this typed result and runtime evidence instead of independently
 * reclassifying the user's sentence.
 */
export function buildSemanticContract(input: {
  classification: IntentClassification;
  outputContract: OutputContract;
  additionalEvidence?: string[];
}): SemanticContract {
  const intent = semanticIntentForClassification(
    input.classification,
    input.outputContract,
  );
  const artifact = semanticArtifactForOutput(input.outputContract);
  const requiredContext = semanticContextForClassification(input.classification);
  const sideEffect = semanticSideEffectForTurn(input);
  const privacyClass = input.classification.requiresLocalRuntime
    ? "local_private"
    : "public";
  const surface = input.classification.requiresLocalRuntime
    ? artifact === "none"
      ? "desktop_runtime"
      : "hybrid"
    : "server_brain";
  const conversationMode = input.classification.requiresLocalRuntime
    ? artifact === "none"
      ? "execute"
      : "hybrid"
    : "chat";
  const confidence = clampSemanticScore(
    Math.max(
      input.classification.confidence,
      input.outputContract.requiresArtifact
        ? input.outputContract.confidence
        : 0,
    ),
  );
  const ambiguity = input.classification.taskFrame.shouldClarify
    ? clampSemanticScore(1 - confidence)
    : 0.02;
  const evidence = uniqueSemanticValues([
    `classifier:${input.classification.reason}`,
    `classifier_intent:${input.classification.primaryIntent}`,
    `reasoning:${input.classification.taskFrame.reasoningMode}`,
    `intent:${intent}`,
    `artifact:${artifact}`,
    `context:${requiredContext.join(",")}`,
    ...(input.outputContract.reasons ?? []).slice(0, 4),
    ...(input.additionalEvidence ?? []).slice(0, 4),
  ]).slice(0, 12);

  return {
    schemaVersion: "elyan.semantic_contract.v1",
    conversationMode,
    surface,
    intent,
    artifact,
    requiredContext,
    sideEffect,
    privacyClass,
    requiredCapabilities: requiredCapabilitiesForContract({
      classification: input.classification,
      artifact,
      sideEffect,
    }),
    needsApproval: sideEffect === "write" || sideEffect === "destructive",
    confidence,
    ambiguity,
    evidence,
  };
}

/**
 * Applies the trusted route/runtime result to the contract without reopening
 * raw-prompt classification. This is the hand-off point from understanding
 * to execution policy.
 */
export function finalizeSemanticContractForRoute(input: {
  contract: SemanticContract;
  route: "server_brain" | "desktop_runtime" | "pairing_required" | "unavailable";
  requiresApproval: boolean;
  capabilities: string[];
  reason: string;
}): SemanticContract {
  const desktopRoute =
    input.route === "desktop_runtime" ||
    input.route === "pairing_required" ||
    input.route === "unavailable";
  const surface = desktopRoute
    ? input.contract.artifact === "none"
      ? "desktop_runtime"
      : "hybrid"
    : input.contract.surface;
  const conversationMode = desktopRoute
    ? input.contract.artifact === "none"
      ? "execute"
      : "hybrid"
    : input.contract.conversationMode;
  return {
    ...input.contract,
    conversationMode,
    surface,
    requiredCapabilities: uniqueSemanticValues([
      ...input.contract.requiredCapabilities,
      ...input.capabilities,
    ]),
    needsApproval: input.contract.needsApproval || input.requiresApproval,
    evidence: uniqueSemanticValues([
      ...input.contract.evidence,
      `route:${input.route}`,
      // Route reasons may originate from a model response. Keep the contract
      // and its content-free logs categorical; never copy free-form text here.
      `route_reason:${input.route}`,
    ]).slice(0, 16),
  };
}
