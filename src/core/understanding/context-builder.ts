import { and, desc, eq, gt, inArray, isNull, or } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { normalizePersonalName } from "./identity-name.js";
import { authIdentities, learningEvents, subscriptions, users } from "../../db/schema.js";
import {
  prioritizeCanonicalMemoryState,
  readCachedCanonicalMemoryState,
  searchBrainMemory,
} from "../../modules/brain/memory.js";
import {
  buildContextPacketsFromMetadata,
  fuseWorldSignalRecordsByKind,
  summarizeContextFreshness,
} from "./context-packets.js";
import { buildMemoryProfileSnapshot, EPISODIC_LABELS } from "./memory-profile.js";
import { filterRetrievedMemory } from "./personalization-policy.js";
import { extractProjectHints } from "./project-context.js";
import { buildDerivedHintBuckets, deriveLearningSignalsFromWorldSignals, toDerivedSignalInput } from "./world-signal-derived.js";
import { isShortFollowUpPrompt } from "../../modules/brain/chat-heuristics.js";
import type {
  ActiveGoalContext,
  ContextPacket,
  ContinuityBoundary,
  IntentClassification,
  MemoryProfileSnapshot,
  RetrievedMemory,
  TaskUnderstandingInput,
  UserProfileSnapshot,
  UserUnderstandingContext,
} from "./types.js";
import { listFreshWorldSignals } from "../../modules/mobile/service.js";
import { getActiveGoalForContext } from "../../modules/goals/service.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";
import {
  sanitizeInboundContextRecord,
  sanitizeInboundContextText,
} from "../../lib/context-text-sanitizer.js";
import {
  buildCanonicalUserModel,
  buildMemoryRecallPackage,
} from "../../modules/brain/user-model.js";
import { isTrustedDialogueStateMetadata } from "../../modules/brain/dialogue-state.js";
import { buildCognitiveContextPacket } from "../../modules/brain/cognitive-context.js";
import {
  isCognitiveFoundationEnabled,
  isCognitiveShadowReadEnabled,
  recordCognitiveFoundationSignal,
} from "../../modules/brain/cognitive-foundation-policy.js";
import { detectAffectiveTurn, type AffectiveTurnSignal } from "./affective-turn.js";
import {
  resolveInteractionContext,
  type InteractionContext,
} from "./interaction-context.js";

const MAX_HINTS = 12;
const MAX_CHARS = 4000;
const PLANNING_TOPIC_PATTERN =
  /\b(plan|planla|planning|program|schedule|günlük|gunluk|haftalık|haftalik|çalışma|calisma|task|görev|gorev|roadmap|routine|rutin)\b/i;
const DEBUG_TOPIC_PATTERN =
  /\b(auth|login|oauth|session|token|bug|hata|error|debug|fix|backend|api|pipeline|refresh|403|401)\b/i;
const SOCIAL_CHAT_FAST_PATH_PATTERN =
  /^(selam|merhaba|slm|hey|hi|hello|günaydın|gunaydin|iyi sabahlar|iyi akşamlar|iyi aksamlar)\b|\b(nasılsın|nasilsin|naber|napıyorsun|napiyorsun|how are you|what'?s up|whats up)\b/i;
const UNDERSTANDING_PROFILE_CACHE_TTL_MS = 60_000;
const UNDERSTANDING_WORLD_CACHE_TTL_MS = 30_000;
const EXPLICIT_NAME_PATTERNS = [
  /\b(?:benim adım|adım)\s+([A-Za-zÇĞİÖŞÜçğıöşü'-]+(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü'-]+){0,2})/iu,
  /\bmy name is\s+([A-Za-z][A-Za-z' -]{1,60})/iu,
];
const SUSPICIOUS_NAME_TOKENS = new Set([
  "adım",
  "benim",
  "merhaba",
  "selam",
  "hey",
  "hello",
  "bugün",
  "neden",
  "niye",
  "kaç",
  "nasılsın",
  "nasilsin",
  "yardım",
  "yardim",
  "lütfen",
  "lutfen",
  "artık",
  "artik",
]);

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function clipCompactText(value: string, maxChars: number): string {
  const compact = compactText(value);
  if (compact.length <= maxChars) return compact;
  return `${compact.slice(0, Math.max(0, maxChars - 3)).trim()}...`;
}

type UnderstandingCacheStore = {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlMs?: number): Promise<void>;
};

function getUnderstandingCacheStore(app: FastifyInstance): UnderstandingCacheStore | null {
  const store = (app.services as { reliability?: { store?: unknown } } | undefined)
    ?.reliability?.store;
  if (
    store &&
    typeof (store as UnderstandingCacheStore).get === "function" &&
    typeof (store as UnderstandingCacheStore).set === "function"
  ) {
    return store as UnderstandingCacheStore;
  }
  return null;
}

function readCachedEnvelope<T>(
  raw: string | null,
  revive?: (value: unknown) => T,
): T | undefined {
  if (!raw) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(raw) as { value?: unknown };
    return revive ? revive(parsed.value) : (parsed.value as T);
  } catch {
    return undefined;
  }
}

async function readUnderstandingCache<T>(
  app: FastifyInstance,
  key: string,
  revive?: (value: unknown) => T,
): Promise<T | undefined> {
  const store = getUnderstandingCacheStore(app);
  if (!store) {
    return undefined;
  }
  return readCachedEnvelope<T>(await store.get(key).catch(() => null), revive);
}

async function writeUnderstandingCache(
  app: FastifyInstance,
  key: string,
  value: unknown,
  ttlMs: number,
) {
  const store = getUnderstandingCacheStore(app);
  if (!store) {
    return;
  }
  await store
    .set(key, JSON.stringify({ value }), ttlMs)
    .catch(() => undefined);
}

function isLikelySocialChatMessage(value: string): boolean {
  return SOCIAL_CHAT_FAST_PATH_PATTERN.test(compactText(value));
}

/**
 * Facts that must survive every retrieval decision.
 *
 * Who the user is is not a *relevant* fact, it is a *constant* one. Retrieval
 * here is relevance-ranked (BM25 + recency), gated on `isSocialTurn`, capped at
 * `MAX_HINTS`, and its durable fallback is further capped at the last 40 rows.
 * The user's name loses on every one of those axes: "nasılsın" is a social turn
 * so retrieval is skipped entirely; "nasılsın" shares no tokens with
 * `preferred_name=Emre` so BM25 ranks it last; and a name learned weeks ago
 * falls out of the 40-row window. The result is an assistant that is told
 * nothing about who it is talking to precisely when it is being addressed
 * personally.
 *
 * So identity is pinned instead of retrieved. These keys are read
 * unconditionally and prepended after ranking.
 */
const IDENTITY_ANCHOR_KEYS = [
  "preferred_name",
  "name",
  "preferred_language",
  "timezone",
] as const;

const IDENTITY_ANCHOR_KEY_SET: ReadonlySet<string> = new Set(
  IDENTITY_ANCHOR_KEYS,
);

function isIdentityAnchorMemory(item: { type?: string; key?: string }): boolean {
  return (
    item.type === "identity" &&
    typeof item.key === "string" &&
    IDENTITY_ANCHOR_KEY_SET.has(item.key)
  );
}

/**
 * Keeps the newest row per identity key. A name stated twice must not occupy
 * two of the few slots the prompt has, and the later statement is the one the
 * user meant ("call me Emre" after "my name is Emre Koca").
 */
function dedupeIdentityAnchors<
  T extends { key: string; createdAt: Date; confidence: number },
>(rows: T[]): T[] {
  const best = new Map<string, T>();
  for (const row of rows) {
    const current = best.get(row.key);
    if (!current || row.createdAt.getTime() > current.createdAt.getTime()) {
      best.set(row.key, row);
    }
  }
  return [...best.values()];
}

function normalizePersonalNameCandidate(value: string | null | undefined): string | null {
  // Delegates to the shared normalizer so read and write agree on what a name
  // is — the "bundan" greeting happened precisely because they did not. The
  // suspicious-token list stays as an extra local guard for greeting words
  // specific to this surface.
  const normalized = normalizePersonalName(
    compactText(String(value ?? "")).replace(/[.,;:!?]+$/g, ""),
  );
  if (!normalized) return null;
  for (const part of normalized.split(" ")) {
    if (SUSPICIOUS_NAME_TOKENS.has(part.toLocaleLowerCase("tr-TR"))) {
      return null;
    }
  }
  return normalized;
}

function extractExplicitSelfIdentifiedName(message: string): string | null {
  const text = compactText(message);
  for (const pattern of EXPLICIT_NAME_PATTERNS) {
    const match = text.match(pattern);
    const normalized = normalizePersonalNameCandidate(match?.[1]);
    if (normalized) {
      return normalized;
    }
  }
  return null;
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readStringValue(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readBooleanValue(record: Record<string, unknown> | null, key: string): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function readPersonalizationPrompt(metadata: Record<string, unknown> | undefined): string | null {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const candidates = [
    readStringValue(root, "userPersonalizationPrompt"),
    readStringValue(compactContext, "userPersonalizationPrompt"),
  ];
  for (const candidate of candidates) {
    const compact = compactText(candidate ?? "");
    if (compact) {
      return compact.slice(0, 200);
    }
  }
  return null;
}

function tokenize(value: string): Set<string> {
  return new Set(
    value
      .toLowerCase()
      .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
      .split(/\s+/)
      .filter((token) => token.length >= 3)
      .slice(0, 80),
  );
}

function overlapScore(query: string, text: string): number {
  const queryTokens = tokenize(query);
  const textTokens = tokenize(text);
  let overlap = 0;
  for (const token of queryTokens) {
    if (textTokens.has(token)) {
      overlap += 1;
    }
  }
  return overlap;
}

function tokenOverlapRatio(left: string, right: string): number {
  const leftTokens = tokenize(left);
  const rightTokens = tokenize(right);
  if (leftTokens.size === 0 || rightTokens.size === 0) {
    return 0;
  }
  let overlap = 0;
  for (const token of leftTokens) {
    if (rightTokens.has(token)) {
      overlap += 1;
    }
  }
  return overlap / Math.max(1, Math.min(leftTokens.size, rightTokens.size));
}

function getIntentTypeBoost(memType: string, intent: string): number {
  // Her intent için hangi memory tipleri daha değerli
  const intentBoostMap: Record<string, string[]> = {
    coding:       ["technical_stack", "project_context", "style"],
    debugging:    ["technical_stack", "project_context", "correction"],
    planning:     ["project_context", "workflow", "preference"],
    writing:      ["style", "preference", "identity"],
    research:     ["preference", "project_context"],
    automation:   ["technical_stack", "project_context", "routing"],
    browser:      ["routing", "technical_stack"],
    computer:     ["routing", "technical_stack"],
    document:     ["style", "preference"],
    math:         ["preference", "style"],
    chat:         ["identity", "preference", "episodic"],
    unknown:      ["identity", "preference"],
  };
  const boostedTypes = intentBoostMap[intent] ?? [];
  return boostedTypes.includes(memType) ? 0.35 : 0;
}

function scoreMemory(item: RetrievedMemory, queryTokens: Set<string>, now = Date.now()): number {
  const text = `${item.type} ${item.key} ${item.value}`;
  const itemTokens = tokenize(text);
  let overlap = 0;

  for (const token of queryTokens) {
    if (itemTokens.has(token)) {
      overlap += 1;
    }
  }

  const referenceTime = item.lastVerifiedAt?.getTime() ?? item.createdAt.getTime();
  const ageDays = Math.max(0, (now - referenceTime) / 86_400_000);
  const recency = Math.max(0, 1 - ageDays / 120);
  const stalenessPenalty =
    item.staleness === "contested" ? -1 : item.staleness === "stale" ? -0.5 : 0.14;
  const conflictPenalty =
    item.conflictStatus === "contested" ? -0.72 : item.conflictStatus === "superseded" ? -1 : 0.08;
  const pinBoost = item.isPinned ? 0.44 : 0;
  const verifiedBoost = item.lastVerifiedAt ? Math.max(0.08, Math.min(0.28, 0.28 - ageDays / 360)) : 0;
  return overlap * 1.8 + item.confidence + recency + stalenessPenalty + conflictPenalty + pinBoost + verifiedBoost;
}

function pushBounded(target: string[], value: string, state: { chars: number }) {
  const compact = compactText(value);

  if (!compact || target.includes(compact) || target.length >= MAX_HINTS || state.chars + compact.length > MAX_CHARS) {
    return;
  }

  target.push(compact);
  state.chars += compact.length;
}

function readFactValue(
  snapshot: MemoryProfileSnapshot | undefined,
  keys: string[],
): string | null {
  const facts = [...(snapshot?.identityFacts ?? []), ...(snapshot?.preferenceFacts ?? [])];

  for (const key of keys) {
    const match = facts.find((item) => item.key === key && compactText(item.value));
    if (match) {
      return compactText(match.value);
    }
  }

  return null;
}

function pushDigestLine(target: string[], value: string | null, maxItems = 6) {
  const compact = compactText(value ?? "");
  if (!compact || target.includes(compact) || target.length >= maxItems) {
    return;
  }
  target.push(compact);
}

function hasWarmCloseTeachingStyle(value: string): boolean {
  const normalized = value.replace(/[_-]+/g, " ");
  return /\b(warm|close|natural|personable|samimi|sıcakkanlı|sicakkanli|yakın|yakin|mature|olgun|teaching|öğretici|ogretici|explanatory|açıklayıcı|aciklayici)\b/i.test(normalized);
}

function describeResponseStylePreference(value: string): string {
  const normalized = value.toLowerCase();
  if (hasWarmCloseTeachingStyle(normalized)) {
    return "warm, close, mature, explanatory, and teaching-oriented without becoming theatrical or clingy";
  }
  if (normalized.includes("professional")) {
    return "precise, calm, and professional";
  }
  if (normalized.includes("formal")) {
    return "formal and restrained";
  }
  return value;
}

function readSnapshotFact(
  snapshot: MemoryProfileSnapshot | undefined,
  keys: string[],
): { key: string; value: string } | null {
  const facts = [
    ...(snapshot?.identityFacts ?? []),
    ...(snapshot?.preferenceFacts ?? []),
    ...(snapshot?.projectFacts ?? []),
    ...(snapshot?.derivedFacts ?? []),
    ...(snapshot?.recentEpisodes ?? []),
  ];

  for (const key of keys) {
    const match = facts.find((item) => item.key === key && compactText(item.value));
    if (match) {
      return { key: match.key, value: compactText(match.value) };
    }
  }

  return null;
}

function buildRelationshipContextDigest(input: {
  userProfile?: UserProfileSnapshot;
  memorySnapshot?: MemoryProfileSnapshot;
  continuitySummary: UserUnderstandingContext["continuitySummary"];
  continuityBoundary: ContinuityBoundary;
  projectHints: string[];
  technicalHints: string[];
}): string[] {
  const digest: string[] = [];
  const preferredName = input.userProfile?.preferredName ?? input.userProfile?.displayName;
  const preferredLanguage = input.userProfile?.preferredLanguage;
  const answerLength = readSnapshotFact(input.memorySnapshot, ["answer_length", "brevity_preference"]);
  const responseStyle = readSnapshotFact(input.memorySnapshot, [
    "response_style_preference",
    "preferred_tone",
  ]);
  const recentTopics = readSnapshotFact(input.memorySnapshot, ["self_model_recent_topics"]);
  const interests = readSnapshotFact(input.memorySnapshot, ["self_model_interests"]);

  if (preferredName) {
    pushDigestLine(digest, `Use the user's name naturally and sparingly: ${preferredName}.`);
  }
  if (preferredLanguage) {
    pushDigestLine(digest, `Default response language preference: ${preferredLanguage}.`);
  }
  if (answerLength) {
    pushDigestLine(digest, `Stable answer length preference: ${answerLength.value}.`);
  }
  if (responseStyle) {
    pushDigestLine(
      digest,
      `Stable response style preference: ${describeResponseStylePreference(responseStyle.value)}.`,
    );
  }
  if (recentTopics) {
    pushDigestLine(digest, recentTopics.value);
  }
  if (interests) {
    pushDigestLine(
      digest,
      `Stable interests inferred from repeated interactions: ${interests.value}.`,
    );
  }
  if (input.continuityBoundary.carryContinuity && input.continuitySummary.userGoal) {
    pushDigestLine(digest, `Continuing user goal: ${input.continuitySummary.userGoal}`);
  }
  if (input.continuityBoundary.carryContinuity && input.continuitySummary.openLoops.length > 0) {
    pushDigestLine(digest, `Open follow-up to keep track of: ${input.continuitySummary.openLoops[0]}`);
  }
  if (input.projectHints.length > 0) {
    pushDigestLine(digest, `Relevant project context: ${input.projectHints[0]}`);
  }
  if (input.technicalHints.length > 0) {
    pushDigestLine(digest, `Relevant technical context: ${input.technicalHints[0]}`);
  }

  return digest;
}

function buildMemoryRelevanceSummary(input: {
  memory: RetrievedMemory[];
  continuitySummary: UserUnderstandingContext["continuitySummary"];
  continuityBoundary: ContinuityBoundary;
}): string[] {
  const summary: string[] = [];
  const seen = new Set<string>();

  for (const item of input.memory) {
    const metadata = readRecord(item.metadata);
    if (readStringValue(metadata, "sourceCategory") === "world_signal_derived") {
      continue;
    }
    const line = compactText(`${item.key}: ${item.value}`);
    const key = line.toLowerCase();
    if (!line || seen.has(key)) {
      continue;
    }
    seen.add(key);
    summary.push(line);
    if (summary.length >= 3) {
      break;
    }
  }

  if (summary.length < 3 && input.continuityBoundary.carryContinuity && input.continuitySummary.userGoal) {
    summary.push(`current_goal: ${input.continuitySummary.userGoal}`);
  }

  if (summary.length < 3 && input.continuityBoundary.carryContinuity && input.continuitySummary.openLoops.length > 0) {
    summary.push(`open_follow_up: ${input.continuitySummary.openLoops[0]}`);
  }

  return summary.slice(0, 4);
}

function isWorldDerivedMemory(item: RetrievedMemory): boolean {
  const metadata = readRecord(item.metadata);
  return readStringValue(metadata, "sourceCategory") === "world_signal_derived";
}

function continuityBucketForMemory(item: RetrievedMemory):
  | "identity"
  | "preference"
  | "project"
  | "technical"
  | "correction"
  | "episodic"
  | "other" {
  if (item.source === "episodic_memory" || item.type === "episodic") {
    return "episodic";
  }
  if (item.type === "identity") {
    return "identity";
  }
  if (item.type === "preference" || item.type === "style") {
    return "preference";
  }
  if (item.type === "project_context") {
    return "project";
  }
  if (item.type === "technical_stack" || item.type === "routing" || item.type === "bridge") {
    return "technical";
  }
  if (item.type === "correction") {
    return "correction";
  }
  return "other";
}

function continuityBucketLimit(bucket: ReturnType<typeof continuityBucketForMemory>): number {
  switch (bucket) {
    case "identity":
      return 2;
    case "preference":
      return 2;
    case "project":
      return 2;
    case "technical":
      return 2;
    case "correction":
      return 1;
    case "episodic":
      return 1;
    default:
      return 1;
  }
}

function scoreContinuityCandidate(input: {
  item: RetrievedMemory;
  queryTokens: Set<string>;
  intent: IntentClassification;
  continuitySummary: UserUnderstandingContext["continuitySummary"];
}): number {
  const base = scoreMemory(input.item, input.queryTokens);
  const bucket = continuityBucketForMemory(input.item);
  const pinnedBoost = input.item.isPinned ? 0.3 : 0;
  const verifiedBoost = input.item.lastVerifiedAt ? 0.12 : 0;
  const freshnessBoost = input.item.staleness === "fresh" ? 0.14 : input.item.staleness === "stale" ? -0.12 : -0.5;
  const bucketBoost =
    bucket === "episodic"
      ? 0.1
      : bucket === "identity" || bucket === "preference"
        ? 0.16
        : bucket === "project" || bucket === "technical"
          ? 0.12
          : 0;
  const continuityText = `${input.continuitySummary.userGoal ?? ""} ${(input.continuitySummary.openLoops ?? []).join(" ")}`;
  const continuityMatch =
    continuityText.trim().length > 0
      ? overlapScore(continuityText, `${input.item.key} ${input.item.value}`) * 0.08
      : 0;
  const sharedPenalty = input.item.scope === "shared" ? -1.4 : 0;
  const worldDerivedPenalty = isWorldDerivedMemory(input.item) ? -1.2 : 0;
  const stalePenalty =
    input.item.conflictStatus === "superseded" || input.item.conflictStatus === "contested"
      ? -2
      : 0;

  return (
    base +
    pinnedBoost +
    verifiedBoost +
    freshnessBoost +
    bucketBoost +
    continuityMatch +
    sharedPenalty +
    worldDerivedPenalty +
    stalePenalty
  );
}

/* ─────────────────────────────────────────────────────────────────────
 * Retrieval-tetikli memory injection
 *
 * Şu ana kadar davranış: her turda searchBrainMemory sonucu (12'ye kadar
 * fact) tamamen memory profile'a dökülüp prompt'a giriyordu. Sonuç: bir
 * "React'te useEffect nasıl kırılır?" sorusuna kullanıcı profilinin tam
 * dökümü ekleniyordu — alakasız veri, sızıntı yüzeyi, model dikkati dağılır.
 *
 * Yeni davranış: retrieval skoruna göre ÜÇ MOD:
 *
 *   • broad    — top-1 score >= 1.2:  turla güçlü alakalı bir fact var,
 *                mevcut sonuç setini olduğu gibi geçir (eski davranış).
 *
 *   • surgical — top-1 score 0.7..1.2: sadece top-3 fact + pinned tut.
 *                Alakalı ama daha az güçlü sinyal; profil dökümü yerine
 *                cerrahi ekleme.
 *
 *   • off      — top-1 score < 0.7:   turla alakalı fact yok. Memory
 *                enjeksiyonu kesilir; sadece pinned + kritik importance
 *                (>=85) fact'ler geçer (güvenlik/kimlik gibi her zaman
 *                doğru olması gereken sabitler).
 *
 * scoreMemoryRecallCandidate (memory.ts) blended score dönüyor: semantic
 * (weight 0.32) + lexical (0.22) + confidence (0.18) + importance (0.14)
 * + pin/verified/recency bonuslar. Alakasız bir fact intrinsik özellikleri
 * ile ~0.4-0.6 puan alabilir; RELEVANCE_MODERATE=0.7 bu seviyeyi biraz
 * geçiyor, gerçek query overlap'i olmadan geçemez.
 */
type RelevanceMode = "off" | "surgical" | "broad";
export const MEMORY_RELEVANCE_STRONG_THRESHOLD = 1.2;
export const MEMORY_RELEVANCE_MODERATE_THRESHOLD = 0.7;

type ScoredMemoryHit = {
  score: number;
  isPinned: boolean;
  importanceScore?: number;
};

export function selectMemoryByRelevance<T extends ScoredMemoryHit>(
  results: readonly T[],
): { mode: RelevanceMode; results: T[] } {
  const topScore = results[0]?.score ?? 0;
  const mode: RelevanceMode =
    topScore >= MEMORY_RELEVANCE_STRONG_THRESHOLD
      ? "broad"
      : topScore >= MEMORY_RELEVANCE_MODERATE_THRESHOLD
        ? "surgical"
        : "off";
  if (mode === "broad") {
    return { mode, results: [...results] };
  }
  if (mode === "surgical") {
    // İlk 3 + pinned (topluca 4'ü geçmesin, sızıntı yüzeyi minimal kalsın).
    const surgical: T[] = [];
    const seen = new Set<T>();
    for (let i = 0; i < results.length && surgical.length < 4; i += 1) {
      const item = results[i];
      if (i < 3 || item.isPinned) {
        if (!seen.has(item)) {
          seen.add(item);
          surgical.push(item);
        }
      }
    }
    return { mode, results: surgical };
  }
  // "off": pinned + high-importance koru; kalanları düşür.
  return {
    mode,
    results: results.filter(
      (r) => r.isPinned || (r.importanceScore ?? 0) >= 85,
    ),
  };
}

export function selectContinuityMemory(input: {
  memory: RetrievedMemory[];
  queryTokens: Set<string>;
  intent: IntentClassification;
  continuitySummary: UserUnderstandingContext["continuitySummary"];
  continuityBoundary?: ContinuityBoundary;
  limit?: number;
}): RetrievedMemory[] {
  const selected: RetrievedMemory[] = [];
  const bucketCounts = new Map<string, number>();
  const seen = new Set<string>();
  const limit = Math.max(4, Math.min(input.limit ?? MAX_HINTS, MAX_HINTS));

  const ordered = [...input.memory]
    .filter((item) => item.scope === "user")
    .filter((item) => !isWorldDerivedMemory(item))
    .filter((item) => item.conflictStatus !== "superseded" && item.conflictStatus !== "contested")
    .sort(
      (left, right) =>
        scoreContinuityCandidate({
          item: right,
          queryTokens: input.queryTokens,
          intent: input.intent,
          continuitySummary: input.continuitySummary,
        }) -
          scoreContinuityCandidate({
            item: left,
            queryTokens: input.queryTokens,
            intent: input.intent,
            continuitySummary: input.continuitySummary,
          }) ||
        right.confidence - left.confidence,
    );

  for (const item of ordered) {
    const bucket = continuityBucketForMemory(item);
    const bucketCount = bucketCounts.get(bucket) ?? 0;
    const bucketLimit =
      input.continuityBoundary?.carryContinuity === false && bucket === "episodic"
        ? 0
        : input.continuityBoundary?.carryContinuity === false && (bucket === "project" || bucket === "technical")
          ? 1
          : continuityBucketLimit(bucket);
    if (bucketCount >= bucketLimit) {
      continue;
    }

    const dedupeKey = `${bucket}:${item.key}:${item.value.toLowerCase()}`;
    if (seen.has(dedupeKey)) {
      continue;
    }

    seen.add(dedupeKey);
    bucketCounts.set(bucket, bucketCount + 1);
    selected.push(item);

    if (selected.length >= limit) {
      break;
    }
  }

  return selected;
}

function buildSpeakingStyleDirectives(input: {
  intent: IntentClassification;
  userProfile?: UserProfileSnapshot;
  memorySnapshot?: MemoryProfileSnapshot;
  continuityBoundary: ContinuityBoundary;
  currentAffect?: AffectiveTurnSignal;
}): string[] {
  const directives: string[] = [];
  const answerLength = readSnapshotFact(input.memorySnapshot, ["answer_length", "brevity_preference"])?.value.toLowerCase() ?? "";
  const preferredTone = readSnapshotFact(input.memorySnapshot, [
    "preferred_tone",
    "response_style_preference",
  ])?.value.toLowerCase() ?? "";
  const continuityStyle = readSnapshotFact(input.memorySnapshot, ["reflective_continuity_style"])?.value ?? "";
  const preferredLanguage = input.userProfile?.preferredLanguage ?? null;

  if (
    input.currentAffect &&
    input.currentAffect.mood !== "neutral" &&
    input.currentAffect.confidence >= 0.55
  ) {
    directives.push(input.currentAffect.responseDirective);
  }
  if (preferredLanguage) {
    directives.push(`Answer in ${preferredLanguage} unless the user clearly requests another language.`);
  }
  if (answerLength.includes("concise") || answerLength.includes("short")) {
    directives.push("Start with the direct answer, then add only the minimum supporting detail.");
  } else if (answerLength.includes("detailed") || answerLength.includes("long")) {
    directives.push("Give a fuller explanation when needed, but keep the structure clean and deliberate.");
  }
  if (hasWarmCloseTeachingStyle(preferredTone)) {
    directives.push("Use a warm, close, mature, explanatory, and teaching-oriented tone in the user's language.");
    directives.push("Be sincere and human, but do not overdo intimacy, praise, or repeated name use.");
  } else if (preferredTone.includes("professional")) {
    directives.push("Keep the tone precise, calm, and professional.");
  }
  if (input.intent.primaryIntent === "chat") {
    directives.push("Sound natural, warm, and human; avoid filler, hype, or repetitive reassurance.");
  }
  if (input.userProfile?.preferredName) {
    directives.push("Use the user's name only when it adds warmth or clarity, not as a default opener.");
  }
  if (!input.continuityBoundary.carryContinuity) {
    directives.push("Do not drag prior chat context into the answer when the user has clearly shifted topics.");
  }
  if (continuityStyle) {
    directives.push(continuityStyle);
  }

  return directives.slice(0, 6);
}

function buildReasoningDirectives(input: {
  intent: IntentClassification;
  continuityBoundary: ContinuityBoundary;
  clarificationDiagnostics: UserUnderstandingContext["clarificationDiagnostics"];
  memorySnapshot?: MemoryProfileSnapshot;
}): string[] {
  const directives = ["Infer the real task before answering the surface wording."];
  const reflectiveReasoningStyle = readSnapshotFact(input.memorySnapshot, ["reflective_reasoning_style"])?.value;

  if (input.intent.primaryIntent === "debugging") {
    directives.push("Separate symptom, likely root cause, proof path, and fix path.");
  } else if (input.intent.primaryIntent === "coding") {
    directives.push("Prefer the smallest safe implementation change that preserves the current architecture.");
  } else if (input.intent.primaryIntent === "planning") {
    directives.push("Break the request into decisions, constraints, tradeoffs, and the smallest reliable next steps.");
  } else if (input.intent.primaryIntent === "research") {
    directives.push("Distinguish verified facts, inference, and unknowns explicitly.");
  } else if (input.intent.primaryIntent === "writing") {
    directives.push("Preserve meaning first, then improve clarity, flow, and tone.");
  } else if (input.intent.primaryIntent === "chat") {
    directives.push("If the user implies a real task under casual wording, surface and answer that task directly.");
  }

  if (input.continuityBoundary.mode !== "same_topic") {
    directives.push("Treat prior chat state as optional background, not as the default frame for the answer.");
  }
  if (input.clarificationDiagnostics.shouldClarify) {
    directives.push("Ask a clarification only if the missing detail would materially change the answer or action.");
  }
  if (reflectiveReasoningStyle) {
    directives.push(reflectiveReasoningStyle);
  }

  return directives.slice(0, 6);
}

function buildUserProfileSnapshot(input: {
  profile?: Partial<UserProfileSnapshot> | null;
  memorySnapshot?: MemoryProfileSnapshot;
}): UserProfileSnapshot | undefined {
  const displayName = normalizePersonalNameCandidate(String(input.profile?.displayName ?? ""));
  const preferredName =
    normalizePersonalNameCandidate(readFactValue(input.memorySnapshot, ["preferred_name", "name"])) ??
    normalizePersonalNameCandidate(String(input.profile?.preferredName ?? ""));
  const preferredLanguage =
    readFactValue(input.memorySnapshot, ["preferred_language", "language"]) ??
    compactText(String(input.profile?.preferredLanguage ?? ""));
  const planCode = compactText(String(input.profile?.planCode ?? "")).toLowerCase();
  const subscriptionStatus = compactText(String(input.profile?.subscriptionStatus ?? "")).toLowerCase();

  const snapshot: UserProfileSnapshot = {
    displayName: displayName || null,
    preferredName: preferredName || null,
    planCode: planCode || null,
    subscriptionStatus: subscriptionStatus || null,
    preferredLanguage: preferredLanguage || null,
  };

  return Object.values(snapshot).some((value) => value != null) ? snapshot : undefined;
}

async function loadSafeUserProfile(
  app: FastifyInstance,
  userId: string,
): Promise<Partial<UserProfileSnapshot> | null> {
  try {
    const [userRows, identityRows] = await Promise.all([
      app.db
        .select({
          displayName: users.displayName,
          planCode: subscriptions.planCode,
          subscriptionStatus: subscriptions.status,
        })
        .from(users)
        .leftJoin(subscriptions, eq(subscriptions.userId, users.id))
        .where(eq(users.id, userId))
        .limit(1),
      app.db
        .select({ displayName: authIdentities.displayName })
        .from(authIdentities)
        .where(eq(authIdentities.userId, userId))
        .limit(1),
    ]);

    const row = userRows[0];
    if (!row) {
      return null;
    }

    const displayName =
      normalizePersonalNameCandidate(String(row.displayName ?? "")) ||
      normalizePersonalNameCandidate(String(identityRows[0]?.displayName ?? "")) ||
      null;

    return {
      displayName,
      planCode: compactText(String(row.planCode ?? "")).toLowerCase() || null,
      subscriptionStatus: compactText(String(row.subscriptionStatus ?? "")).toLowerCase() || null,
    };
  } catch {
    return null;
  }
}

async function loadCachedSafeUserProfile(
  app: FastifyInstance,
  userId: string,
): Promise<Partial<UserProfileSnapshot> | null> {
  const cacheKey = `understanding:profile:${userId}`;
  const cached = await readUnderstandingCache<Partial<UserProfileSnapshot> | null>(
    app,
    cacheKey,
  );
  if (cached !== undefined) {
    return cached;
  }
  const profile = await loadSafeUserProfile(app, userId);
  await writeUnderstandingCache(
    app,
    cacheKey,
    profile,
    UNDERSTANDING_PROFILE_CACHE_TTL_MS,
  );
  return profile;
}

type FreshWorldSignals = Awaited<ReturnType<typeof listFreshWorldSignals>>;

function sanitizeCachedWorldSignalRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? sanitizeInboundContextRecord(value as Record<string, unknown>, {
        maxDepth: 2,
        maxStringLength: 160,
      })
    : {};
}

function reviveFreshWorldSignals(value: unknown): FreshWorldSignals {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => {
    const record = item && typeof item === "object" && !Array.isArray(item)
      ? (item as Record<string, unknown>)
      : {};
    return {
      signalId: String(record.signalId ?? ""),
      source: String(record.source ?? ""),
      kind: String(record.kind ?? ""),
      summary: sanitizeInboundContextText(String(record.summary ?? ""), 480).text,
      confidence:
        typeof record.confidence === "number" && Number.isFinite(record.confidence)
          ? record.confidence
          : 0,
      facts: sanitizeCachedWorldSignalRecord(record.facts),
      privacy: sanitizeCachedWorldSignalRecord(record.privacy),
      renderHints: sanitizeCachedWorldSignalRecord(record.renderHints),
      visibility: record.visibility,
      createdAt:
        record.createdAt instanceof Date
          ? record.createdAt
          : new Date(String(record.createdAt ?? Date.now())),
    };
  }) as FreshWorldSignals;
}

async function listCachedFreshWorldSignals(
  app: FastifyInstance,
  input: {
    userId: string;
    limit: number;
    maxAgeHours: number;
    sessionId?: string | null;
  },
): Promise<FreshWorldSignals> {
  const cacheKey = `understanding:world:${input.userId}:${input.sessionId ?? "global"}`;
  const cached = await readUnderstandingCache<FreshWorldSignals>(
    app,
    cacheKey,
    reviveFreshWorldSignals,
  );
  if (cached !== undefined) {
    return cached;
  }
  const signals = await listFreshWorldSignals(app, input);
  await writeUnderstandingCache(
    app,
    cacheKey,
    signals,
    UNDERSTANDING_WORLD_CACHE_TTL_MS,
  );
  return signals;
}

function extractEcosystemHints(input: {
  title?: string;
  message?: string;
  metadata?: Record<string, unknown>;
}): string[] {
  const text = `${input.title ?? ""} ${input.message ?? ""}`.toLowerCase();
  const hints = new Set<string>();

  if (/\belyan\b/i.test(text)) {
    hints.add("elyan_ecosystem");
  }
  if (/\b(desktop|runtime|pairing|pair|local runtime|local_runtime)\b/i.test(text)) {
    hints.add("desktop_runtime");
  }
  if (/\b(mobile|flutter|ios|android)\b/i.test(text)) {
    hints.add("mobile_surface");
  }
  if (/\b(backend|server|api|control plane|control-plane|control_plane)\b/i.test(text)) {
    hints.add("backend_control_plane");
  }
  if (/\b(fastify|drizzle|postgres|sql|api|backend|server)\b/i.test(text)) {
    hints.add("backend_control_plane");
  }
  if (/\b(brain|memory|retrieval|rag|learning|understanding)\b/i.test(text)) {
    hints.add("brain_understanding");
  }
  if (/\b(quota|billing|auth|subscription|credit|usage)\b/i.test(text)) {
    hints.add("policy_and_quota");
  }
  if (typeof input.metadata?.projectName === "string" && input.metadata.projectName.trim()) {
    hints.add(`project:${input.metadata.projectName.trim()}`);
    if (input.metadata.projectName.trim().toLowerCase() === "elyan") {
      hints.add("elyan_ecosystem");
    }
  }

  return [...hints].slice(0, 6);
}

function deriveTaskFrame(input: {
  intent: IntentClassification;
  message: string;
}): UserUnderstandingContext["taskFrame"] {
  return {
    goal: input.intent.taskFrame.goal,
    likelyAnswerShape: input.intent.taskFrame.likelyAnswerShape,
    reasoningMode: input.intent.taskFrame.reasoningMode,
    shouldClarify:
      input.intent.taskFrame.shouldClarify ||
      /^(bunu|şunu|sunu|this|that|it)\b/i.test(input.message.trim()) ||
      /^(düzelt|duzelt|fix it|improve this|optimize this)\b/i.test(input.message.trim()),
  };
}

function resolveMemoryEnabled(metadata: Record<string, unknown> | undefined): boolean {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const direct = readBooleanValue(root, "memoryEnabled");
  const nested = readBooleanValue(compactContext, "memoryEnabled");
  return nested ?? direct ?? true;
}

const OPEN_LOOP_PATTERNS = [
  /\b(yarın|sonra|daha sonra|ilerleyen|bir sonraki|devam edelim|takip edelim|hatırlat|tomorrow|later|next time|follow up|remind me|let's continue|we'll do|we can do)\b/i,
  /\b(bekliyor|bekleyecek|onay bekleniyor|cevap bekliyor|waiting for|pending|needs approval|to be done)\b/i,
  /\?$/,
];
const REFERENTIAL_FOLLOWUP_PATTERN =
  /^(bunu|şunu|sunu|buradaki|bundaki|aynı|ayni|same|that|this|it|devam|sürdür|surdur)\b|\b(az önceki|az onceki|önceki|onceki|son söylediğin|son soyledigin|son cevabın|son cevabin|bununla bağlantılı|bununla baglantili|ona göre|ona gore|buna göre|buna gore|aynı şekilde|ayni sekilde|aynı mantıkla|ayni mantikla|same logic|devam et|continue|as above|like before)\b/i;

function extractOpenLoopsFromMessages(
  messages: Array<{ role: string; content: string }>,
): string[] {
  const loops: string[] = [];
  // Son 4 mesaja bak, kullanıcı mesajlarında açık döngü sinyali ara
  for (const msg of messages.slice(-4)) {
    if (msg.role !== "user") continue;
    const text = compactText(msg.content);
    if (OPEN_LOOP_PATTERNS.some((p) => p.test(text))) {
      const snippet = text.length > 100 ? `${text.slice(0, 97)}…` : text;
      if (!loops.includes(snippet)) loops.push(snippet);
    }
  }
  return loops.slice(0, 3);
}

function extractTurnTracesFromMetadata(
  metadata: Record<string, unknown> | undefined,
  input: { userId: string; sessionId?: string | null },
): Array<{ user: string; assistant: string | null; workload: string | null }> {
  const root = readRecord(metadata);
  const compactContext = isTrustedDialogueStateMetadata(metadata, input)
    ? readRecord(root?.compactContext)
    : null;
  const rawTurns = Array.isArray(compactContext?.turns) ? compactContext.turns : [];
  return rawTurns
    .map((item) => {
      const record = readRecord(item);
      const user = readStringValue(record, "user");
      if (!user) {
        return null;
      }
      return {
        user,
        assistant: readStringValue(record, "assistant"),
        workload: readStringValue(record, "workload"),
      };
    })
    .filter((item): item is { user: string; assistant: string | null; workload: string | null } => item != null)
    .slice(0, 8);
}

function extractSalienceFromMetadata(
  metadata: Record<string, unknown> | undefined,
  input: { userId: string; sessionId?: string | null },
): {
  topics: string[];
  entities: string[];
  userIntent: string | null;
  assistantCommitment: string | null;
  emotionalTone: string | null;
  affectiveDirective: string | null;
  unresolved: boolean;
} {
  const root = readRecord(metadata);
  const compactContext = isTrustedDialogueStateMetadata(metadata, input)
    ? readRecord(root?.compactContext)
    : null;
  const salience = readRecord(compactContext?.salience);
  const affectiveStance = readRecord(compactContext?.affectiveStance);
  const topics = Array.isArray(salience?.topics)
    ? salience.topics.map(String).filter(Boolean).slice(0, 8)
    : [];
  const entities = Array.isArray(salience?.entities)
    ? salience.entities.map(String).filter(Boolean).slice(0, 10)
    : [];
  return {
    topics,
    entities,
    userIntent: readStringValue(salience, "userIntent"),
    assistantCommitment: readStringValue(salience, "assistantCommitment"),
    emotionalTone: readStringValue(salience, "emotionalTone"),
    affectiveDirective: readStringValue(affectiveStance, "directive"),
    unresolved: readBooleanValue(salience, "unresolved") === true,
  };
}

function buildTurnTraceText(turns: Array<{ user: string; assistant: string | null; workload: string | null }>): string {
  return compactText(
    turns
      .slice(0, 6)
      .map((turn) => `${turn.workload ?? "turn"} user=${turn.user} assistant=${turn.assistant ?? ""}`)
      .join(" "),
  );
}

function deriveGoalFromRecentMessages(
  messages: Array<{ role: string; content: string }>,
): string | null {
  // En son kullanıcı mesajından hedef türet
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  if (!lastUser) return null;
  const text = compactText(lastUser.content);
  return text.length > 180 ? `${text.slice(0, 177)}…` : text;
}

function deriveContinuitySummary(
  metadata: Record<string, unknown> | undefined,
  input?: { userId: string; sessionId?: string | null },
) {
  const root = readRecord(metadata);
  const trustedDialogueMetadata = input
    ? isTrustedDialogueStateMetadata(metadata, input)
    : false;
  const compactContext = trustedDialogueMetadata ? readRecord(root?.compactContext) : null;
  const chatContext = trustedDialogueMetadata ? readRecord(root?.chatContext) : null;

  // Önce mevcut rollingSummary'ye bak (mobil veya önceki backend geçişinden)
  const rollingSummary = readRecord(
    compactContext?.rollingSummary ?? chatContext?.rollingSummary,
  );
  const storedGoal = readStringValue(rollingSummary, "userGoal");
  const storedState = readStringValue(rollingSummary, "assistantState");
  const storedLoopsRaw = Array.isArray(rollingSummary?.openLoops) ? rollingSummary.openLoops : [];
  const storedLoops = storedLoopsRaw
    .map((item) => String(item ?? "").trim())
    .filter(Boolean)
    .slice(0, 4);

  // recentMessages varsa açık döngüleri ve hedefi onlardan da türet
  const recentRaw = Array.isArray(compactContext?.recentMessages)
    ? (compactContext.recentMessages as unknown[])
    : [];
  const recentMessages = recentRaw
    .map((item) => {
      const r = readRecord(item as unknown);
      if (!r) return null;
      const role = typeof r.role === "string" ? r.role : null;
      const content = typeof r.content === "string" ? r.content : null;
      if (!role || !content) return null;
      return { role, content };
    })
    .filter((m): m is { role: string; content: string } => m !== null);
  const recentTurns = input ? extractTurnTracesFromMetadata(metadata, input) : [];
  const salience = input
    ? extractSalienceFromMetadata(metadata, input)
    : { topics: [], entities: [], userIntent: null, assistantCommitment: null, emotionalTone: null, affectiveDirective: null, unresolved: false };

  const derivedLoops =
    storedLoops.length === 0
      ? extractOpenLoopsFromMessages([
          ...recentMessages,
          ...recentTurns.map((turn) => ({ role: "user", content: turn.user })),
        ])
      : storedLoops;
  const derivedGoal =
    storedGoal ??
    salience.userIntent ??
    (recentTurns[0]?.user
      ? clipCompactText(recentTurns[0].user, 180)
      : recentMessages.length > 0
        ? deriveGoalFromRecentMessages(recentMessages)
        : null);
  const derivedState =
    storedState ??
    salience.assistantCommitment ??
    (recentTurns[0]?.assistant
      ? clipCompactText(recentTurns[0].assistant, 180)
      : null);

  return {
    userGoal: derivedGoal,
    assistantState: derivedState,
    openLoops:
      salience.unresolved && salience.userIntent && !derivedLoops.includes(salience.userIntent)
        ? [salience.userIntent, ...derivedLoops].slice(0, 4)
        : derivedLoops,
  };
}

function deriveContinuityBoundary(input: {
  metadata: Record<string, unknown> | undefined;
  message: string;
  continuitySummary: UserUnderstandingContext["continuitySummary"];
  intent: IntentClassification;
  userId: string;
  sessionId?: string | null;
}): ContinuityBoundary {
  const current = compactText(input.message);
  const recentTurns = extractTurnTracesFromMetadata(input.metadata, {
    userId: input.userId,
    sessionId: input.sessionId,
  });
  const salience = extractSalienceFromMetadata(input.metadata, {
    userId: input.userId,
    sessionId: input.sessionId,
  });
  if (
    !current ||
    (!input.continuitySummary.userGoal &&
      !input.continuitySummary.assistantState &&
      input.continuitySummary.openLoops.length === 0 &&
      recentTurns.length === 0 &&
      salience.topics.length === 0 &&
      salience.entities.length === 0)
  ) {
    return {
      mode: "new_topic",
      reason: "no_prior_context",
      carryContinuity: false,
    };
  }

  const root = readRecord(input.metadata);
  const compactContext = isTrustedDialogueStateMetadata(input.metadata, {
    userId: input.userId,
    sessionId: input.sessionId,
  })
    ? readRecord(root?.compactContext)
    : null;
  const recentRaw = Array.isArray(compactContext?.recentMessages)
    ? (compactContext.recentMessages as unknown[])
    : [];
  const recentMessages = recentRaw
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item !== null)
    .map((item) => ({
      role: typeof item.role === "string" ? item.role : "",
      content: typeof item.content === "string" ? item.content : "",
    }))
    .filter((item) => item.role && item.content);
  const lastUserMessage = [...recentMessages].reverse().find((item) => item.role === "user")?.content ?? "";
  const rollingSummary = readRecord(compactContext?.rollingSummary);
  const contextNotes = Array.isArray(rollingSummary?.contextNotes)
    ? rollingSummary.contextNotes.map(String).filter(Boolean).slice(0, 4).join(" ")
    : "";
  const priorText = compactText(
    [
      input.continuitySummary.userGoal ?? "",
      input.continuitySummary.assistantState ?? "",
      input.continuitySummary.openLoops.join(" "),
      lastUserMessage,
      contextNotes,
      salience.userIntent ?? "",
      salience.assistantCommitment ?? "",
      salience.topics.join(" "),
      salience.entities.join(" "),
      buildTurnTraceText(recentTurns),
    ].join(" "),
  );

  if (REFERENTIAL_FOLLOWUP_PATTERN.test(current)) {
    return {
      mode: "same_topic",
      reason: "referential_followup",
      carryContinuity: true,
    };
  }

  const overlap = overlapScore(current, priorText);
  const overlapRatio = tokenOverlapRatio(current, priorText);
  if (overlap >= 2 || overlapRatio >= 0.24) {
    return {
      mode: "same_topic",
      reason: recentTurns.length > 0 ? "session_turn_overlap" : "lexical_topic_overlap",
      carryContinuity: true,
    };
  }

  const taskShapeOverlap =
    (input.intent.primaryIntent === "planning" &&
      PLANNING_TOPIC_PATTERN.test(current) &&
      PLANNING_TOPIC_PATTERN.test(priorText)) ||
    ((input.intent.primaryIntent === "coding" || input.intent.primaryIntent === "debugging") &&
      DEBUG_TOPIC_PATTERN.test(current) &&
      DEBUG_TOPIC_PATTERN.test(priorText));
  if (taskShapeOverlap) {
    return {
      mode: "same_topic",
      reason: "task_shape_overlap",
      carryContinuity: true,
    };
  }

  if (["planning", "coding", "debugging", "document", "research"].includes(input.intent.primaryIntent)) {
    return {
      mode: "new_topic",
      reason: "task_reset_without_topic_overlap",
      carryContinuity: false,
    };
  }

  return {
    mode: "possible_shift",
    reason: "weak_topic_overlap",
    carryContinuity: false,
  };
}

function deriveClarificationDiagnostics(input: {
  intent: IntentClassification;
  message: string;
  continuity: { userGoal: string | null; assistantState: string | null; openLoops: string[] };
}): UserUnderstandingContext["clarificationDiagnostics"] {
  const text = compactText(input.message).toLowerCase();
  // Short follow-ups ("anlamadım", "onu düzelt", "devam et") are ambiguous
  // ONLY when there is no prior-turn context to resolve them against. When we
  // DO have userGoal / assistantState / openLoops the answer is well-defined
  // (continue / re-explain / revise the previous turn) — asking for
  // clarification there just frustrates the user.
  if (isShortFollowUpPrompt(input.message)) {
    const hasPriorContext = Boolean(
      input.continuity.userGoal ||
        input.continuity.assistantState ||
        input.continuity.openLoops.length > 0,
    );
    if (!hasPriorContext) {
      return {
        shouldClarify: true,
        ambiguityKind: "ambiguous_followup",
        reason: "short_followup_without_prior_turn_context",
      };
    }
    return {
      shouldClarify: false,
      ambiguityKind: "none",
      reason: "short_followup_resolved_by_prior_turn_context",
    };
  }
  if (!input.intent.taskFrame.shouldClarify) {
    return {
      shouldClarify: false,
      ambiguityKind: "none",
      reason: "intent_confident_enough",
    };
  }
  if (/^(bunu|şunu|sunu|this|that|it|buradaki|bundaki)\b/.test(text)) {
    return {
      shouldClarify: true,
      ambiguityKind: "ambiguous_followup",
      reason: "referential_followup_without_clear_target",
    };
  }
  if (/^(düzelt|duzelt|fix|optimize|improve|rewrite|yenile)\b/.test(text)) {
    return {
      shouldClarify: true,
      ambiguityKind: "missing_target",
      reason: "action_requested_without_explicit_target",
    };
  }
  if (input.continuity.openLoops.length > 0 && /(ama|however|instead|yalnız|yalniz|fakat)/.test(text)) {
    return {
      shouldClarify: true,
      ambiguityKind: "conflicting_constraints",
      reason: "followup_may_change_prior_constraint_or_goal",
    };
  }
  return {
    shouldClarify: true,
    ambiguityKind: "insufficient_evidence",
    reason: "low_confidence_or_short_prompt",
  };
}

export function buildUserContextFromMemory(input: {
  userId: string;
  accountId: string;
  intent: IntentClassification;
  task: TaskUnderstandingInput;
  memory: RetrievedMemory[];
  profile?: Partial<UserProfileSnapshot> | null;
  contextPackets?: ContextPacket[];
  activeGoal?: ActiveGoalContext | null;
  interactionContext?: InteractionContext;
  currentAffect?: AffectiveTurnSignal;
}): UserUnderstandingContext {
  const eligibleMemory = filterRetrievedMemory(input.memory);
  // World signals are short-lived request context, not durable profile facts.
  // Keep them available to the relevance-aware derived-hint builder below,
  // but never let them enter the user's memory/profile snapshot or generic
  // personalization hints.
  const profileMemory = eligibleMemory
    .filter((item) => !isWorldDerivedMemory(item))
    .slice(0, MAX_HINTS);
  const worldContextMemory = eligibleMemory
    .filter((item) => isWorldDerivedMemory(item))
    .slice(0, MAX_HINTS);
  const memorySnapshot = buildMemoryProfileSnapshot(profileMemory);
  const userProfile = buildUserProfileSnapshot({
    profile: input.profile,
    memorySnapshot,
  });
  const state = { chars: 0 };
  const ecosystemHints = extractEcosystemHints(input.task);
  const personalizationHints: string[] = [];
  const projectHints: string[] = [];
  const styleHints: string[] = [];
  const technicalHints: string[] = [];
  const safetyHints: string[] = [];
  const situationalHints: string[] = [];
  const behavioralHints: string[] = [];
  const environmentHints: string[] = [];
  const continuitySummary = deriveContinuitySummary(input.task.metadata, {
    userId: input.userId,
  });
  const turnSalience = extractSalienceFromMetadata(input.task.metadata, {
    userId: input.userId,
  });
  const continuityBoundary = deriveContinuityBoundary({
    metadata: input.task.metadata,
    message: input.task.message,
    continuitySummary,
    intent: input.intent,
    userId: input.userId,
  });
  const clarificationDiagnostics = deriveClarificationDiagnostics({
    intent: input.intent,
    message: input.task.message,
    continuity: continuitySummary,
  });
  const memoryEnabled = resolveMemoryEnabled(input.task.metadata);
  const personalizationPrompt = readPersonalizationPrompt(input.task.metadata);
  const interactionContext =
    input.interactionContext ?? resolveInteractionContext(input.task);
  const contextPackets = (input.contextPackets ?? []).slice(0, 10);
  const packetKinds = Array.from(new Set(contextPackets.map((packet) => packet.kind)));
  const healthContextUsed = packetKinds.includes("health_context");
  if (turnSalience.topics.length > 0) {
    pushBounded(
      situationalHints,
      `Session topics to keep coherent: ${turnSalience.topics.slice(0, 5).join(", ")}`,
      state,
    );
  }
  if (turnSalience.entities.length > 0) {
    pushBounded(
      situationalHints,
      `Referenced entities from this conversation: ${turnSalience.entities.slice(0, 5).join(", ")}`,
      state,
    );
  }
  if (turnSalience.assistantCommitment) {
    pushBounded(
      behavioralHints,
      `Assistant commitment to honor if relevant: ${turnSalience.assistantCommitment}`,
      state,
    );
  }
  // Biriken duygusal duruş (moodTrend + yakınlık + oynaklıktan türetilmiş) tek
  // seferlik tone kelimesinin yerini alır: model, oturum boyunca taşınan bir ruh
  // haline göre davranır. Duruş yoksa eski tek-tur sinyaline düşer.
  if (turnSalience.affectiveDirective) {
    pushBounded(
      behavioralHints,
      `Affective stance (persistent): ${turnSalience.affectiveDirective}`,
      state,
    );
  } else if (turnSalience.emotionalTone) {
    pushBounded(
      behavioralHints,
      `User affect signal: ${turnSalience.emotionalTone}; adapt warmth without mentioning the signal.`,
      state,
    );
  }
  for (const hint of extractProjectHints(input.task)) {
    pushBounded(projectHints, hint, state);
  }

  const now = Date.now();
  for (const item of profileMemory) {
    // Temporal etiket: ne kadar önce öğrenildi
    const ageDays = Math.max(
      0,
      (now - (item.lastVerifiedAt?.getTime() ?? item.createdAt.getTime())) / 86_400_000,
    );
    const ageLabel =
      ageDays < 2
        ? "bugün/dün"
        : ageDays < 7
          ? "bu hafta"
          : ageDays < 30
            ? "bu ay"
            : ageDays < 90
              ? "son 3 ayda"
              : "daha önce";
    // Güven etiketi
    const confLabel =
      item.confidence >= 0.8
        ? "çok güçlü"
        : item.confidence >= 0.6
          ? "güçlü"
          : item.confidence >= 0.4
            ? "orta"
            : "zayıf";
    const hint = `${item.key}: ${item.value} (${confLabel}, ${ageLabel})`;

    if (item.type === "style") {
      pushBounded(styleHints, hint, state);
    } else if (item.type === "technical_stack") {
      pushBounded(technicalHints, hint, state);
    } else if (item.type === "project_context") {
      pushBounded(projectHints, hint, state);
    } else if (item.type === "correction") {
      pushBounded(safetyHints, hint, state);
    } else if (item.type === "episodic" || Object.keys(EPISODIC_LABELS).includes(item.key)) {
      // Epizodik anılar: kullanıcıyla ilişki bağlamı için ayrı kova
      pushBounded(situationalHints, hint, state);
    } else {
      pushBounded(personalizationHints, hint, state);
    }
  }

  const derivedHints = buildDerivedHintBuckets({
    memory: worldContextMemory.map((item) => ({
      key: item.key,
      value: item.value,
      metadata:
        typeof item === "object" && item != null && "metadata" in item
          ? ((item as RetrievedMemory & { metadata?: Record<string, unknown> }).metadata ?? {})
          : {},
      staleness: item.staleness,
    })),
    requestText: input.task.message,
    contextPackets,
  });

  for (const hint of derivedHints.situationalHints) {
    pushBounded(situationalHints, hint, state);
  }
  for (const hint of derivedHints.behavioralHints) {
    pushBounded(behavioralHints, hint, state);
  }
  for (const hint of derivedHints.environmentHints) {
    pushBounded(environmentHints, hint, state);
  }

  if (input.intent.privacyRisk === "high" || input.intent.requiresLocalRuntime) {
    pushBounded(safetyHints, "Keep private local runtime data local unless the user explicitly allows sharing.", state);
  }

  if (input.intent.requiresCitation) {
    pushBounded(personalizationHints, "Prefer cited, source-grounded answers for this request.", state);
  }

  if (personalizationPrompt) {
    pushBounded(
      personalizationHints,
      `Explicit user personalization from settings: ${personalizationPrompt}`,
      state,
    );
  }

  if (healthContextUsed) {
    pushBounded(
      safetyHints,
      "Use health context only as short-lived wellbeing/readiness context; never diagnose, prescribe, or persist it as a permanent profile fact.",
      state,
    );
  }

  if (packetKinds.includes("calendar_context")) {
    pushBounded(
      safetyHints,
      "Use calendar context only as a derived schedule/load signal; never quote event titles, attendees, notes, or private calendar bodies.",
      state,
    );
  }

  if (packetKinds.includes("notification_context")) {
    pushBounded(
      safetyHints,
      "Use notification context only as attention/urgency context; never quote notification content or infer private relationships from it.",
      state,
    );
  }

  if (packetKinds.includes("device_context")) {
    pushBounded(
      safetyHints,
      "Use device context to adapt pacing and reliability expectations; never expose device identifiers, local paths, or private diagnostics.",
      state,
    );
  }

  const relationshipContextDigest = buildRelationshipContextDigest({
    userProfile,
    memorySnapshot,
    continuitySummary,
    continuityBoundary,
    projectHints,
    technicalHints,
  });
  const speakingStyleDirectives = buildSpeakingStyleDirectives({
    intent: input.intent,
    userProfile,
    memorySnapshot,
    continuityBoundary,
    currentAffect: input.currentAffect,
  });
  const reasoningDirectives = buildReasoningDirectives({
    intent: input.intent,
    continuityBoundary,
    clarificationDiagnostics,
    memorySnapshot,
  });

  return {
    userId: input.userId,
    accountId: input.accountId,
    intent: input.intent.primaryIntent,
    taskFrame: deriveTaskFrame({
      intent: input.intent,
      message: input.task.message,
    }),
    ecosystemHints,
    personalizationHints,
    projectHints,
    styleHints,
    speakingStyleDirectives,
    reasoningDirectives,
    technicalHints,
    safetyHints,
    situationalHints,
    behavioralHints,
    environmentHints,
    continuitySummary,
    activeGoal: input.activeGoal ?? null,
    continuityBoundary,
    relationshipContextDigest,
    clarificationDiagnostics,
    memoryEnabled,
    interactionContext,
    ...(input.currentAffect ? { currentAffect: input.currentAffect } : {}),
    personalizationPrompt,
    memoryRelevanceSummary: buildMemoryRelevanceSummary({
      memory: profileMemory,
      continuitySummary,
      continuityBoundary,
    }),
    contextPackets,
    healthContextUsed,
    packetKinds,
    freshness: summarizeContextFreshness(contextPackets),
    retrievedMemory: profileMemory,
    memorySnapshot,
    userProfile,
    tokenBudget: {
      maxHints: MAX_HINTS,
      maxChars: MAX_CHARS,
    },
  };
}

/* ── Extract quick user facts from the current message via C daemon ───── */
async function extractQuickFacts(message: string): Promise<{ name?: string; city?: string }> {
  const facts = await nlpDaemon.extractFacts(message).catch(() => []);
  const result: { name?: string; city?: string } = {};
  for (const f of facts) {
    if (f.k === "name" && f.v) result.name = f.v;
    if (f.k === "city" && f.v) result.city = f.v;
  }
  return result;
}

export async function buildUserContext(
  app: FastifyInstance,
  input: TaskUnderstandingInput & { intent: IntentClassification },
): Promise<UserUnderstandingContext> {
  const accountId    = input.accountId ?? input.userId;
  const memoryEnabled = resolveMemoryEnabled(input.metadata);
  const query        = `${input.title ?? ""} ${input.message ?? ""} ${input.intent.primaryIntent}`;
  const queryTokens  = tokenize(query);
  const now          = new Date();
  const foundationEnabled = isCognitiveFoundationEnabled(app, input.userId);
  const shadowReadEnabled = !foundationEnabled && isCognitiveShadowReadEnabled(app);
  const metadataChat = readRecord(input.metadata?.chat);
  const sessionId =
    typeof metadataChat?.sessionId === "string" && metadataChat.sessionId.trim()
      ? metadataChat.sessionId.trim()
      : null;
  const isSocialTurn =
    input.intent.primaryIntent === "chat" && isLikelySocialChatMessage(input.message);

  const contextPackets = app.config.ELYAN_WORLD_CONTEXT_PACKETS_ENABLED
    ? buildContextPacketsFromMetadata(input.metadata, {
        now,
        requestText: input.message,
        intent: input.intent.primaryIntent,
      })
    : [];

  /* Run all async ops in parallel for minimum latency */
  const cognitiveReadStartedAt = Date.now();
  const [
    memorySearch,
    canonicalMemory,
    userProfile,
    quickFacts,
    freshWorldSignals,
    cognitiveContext,
    currentAffect,
    activeGoal,
  ] = await Promise.all([
    memoryEnabled && !isSocialTurn && !foundationEnabled
      ? searchBrainMemory(app, { userId: input.userId, query, limit: MAX_HINTS }).catch(() => ({ results: [] }))
      : Promise.resolve({ results: [] }),
    memoryEnabled && !foundationEnabled
      ? readCachedCanonicalMemoryState(app, input.userId).catch(() => [])
      : Promise.resolve([]),
    loadCachedSafeUserProfile(app, input.userId),
    /* Quick C-based fact extraction from the current message */
    !isSocialTurn && nlpDaemon.isAvailable()
      ? extractQuickFacts(input.message).catch(() => ({ name: undefined, city: undefined }))
      : Promise.resolve({ name: undefined, city: undefined }),
    !isSocialTurn && contextPackets.some((packet) => packet.source === "world_signal")
      ? listCachedFreshWorldSignals(app, {
          userId: input.userId,
          sessionId,
          limit: 48,
          maxAgeHours: 24,
        }).catch(() => [])
      : Promise.resolve([]),
    (foundationEnabled || shadowReadEnabled) && memoryEnabled
      ? buildCognitiveContextPacket(app, {
          userId: input.userId,
          sessionId,
          semanticLimit: MAX_HINTS,
          episodicLimit: 8,
          maxChars: MAX_CHARS,
          includeEpisodes: !isSocialTurn,
          includeContested: !isSocialTurn,
          now,
        }).catch(() => null)
      : Promise.resolve(null),
    detectAffectiveTurn(input.message).catch(() => null),
    isSocialTurn
      ? Promise.resolve(null)
      : getActiveGoalForContext(app, {
          userId: input.userId,
          sessionId,
        }).catch(() => null),
  ]);

  /* Enrich profile only from explicit self-identification, never from arbitrary message fragments. */
  let enrichedProfile = userProfile;
  const explicitName = extractExplicitSelfIdentifiedName(input.message);
  if (!userProfile?.displayName && explicitName) {
    enrichedProfile = { ...userProfile, displayName: explicitName };
  }

  const mergedMemory = prioritizeCanonicalMemoryState(
    [...canonicalMemory, ...memorySearch.results],
    MAX_HINTS,
  );
  const { mode: relevanceMode, results: filteredResults } = selectMemoryByRelevance(
    mergedMemory,
  );
  void relevanceMode; // gelecek observability için; bırakıyoruz.

  const legacyStableMemory = filteredResults.map((result) => ({
    id:             result.id,
    type:           result.memoryType,
    key:            result.title,
    value:          result.content,
    confidence:     result.confidence / 100,
    scope:          result.scope,
    source:         result.memorySource,
    createdAt:      new Date(result.updatedAt),
    staleness:      result.staleness,
    conflictStatus: result.conflictStatus,
    lastVerifiedAt: result.lastVerifiedAt ? new Date(result.lastVerifiedAt) : null,
    importanceScore: result.importanceScore,
    isPinned:       result.isPinned,
    metadata:       result.metadata,
  }));

  const cognitiveStableMemory: RetrievedMemory[] = cognitiveContext
    ? [
        ...cognitiveContext.semantic.map((item) => ({
          id: item.id,
          type: "semantic",
          key: item.key,
          value: item.value,
          confidence: item.confidence,
          scope: "user" as const,
          source: "memory_fact",
          createdAt: new Date(item.observedAt),
          staleness: "fresh" as const,
          conflictStatus: "active" as const,
          lastVerifiedAt: new Date(item.observedAt),
          importanceScore: 80,
          isPinned: false,
          metadata: { cognitiveRevision: item.revision, sourceKind: item.sourceKind },
        })),
        ...cognitiveContext.episodic.map((item) => ({
          id: item.id,
          type: "episode",
          key: item.topic,
          value: item.summary,
          confidence: item.confidence,
          scope: "user" as const,
          source: "memory_episode",
          createdAt: new Date(item.observedAt),
          staleness: "fresh" as const,
          conflictStatus: "active" as const,
          lastVerifiedAt: new Date(item.observedAt),
          importanceScore: 70,
          isPinned: false,
          metadata: { cognitiveRevision: item.revision, expiresAt: item.expiresAt },
        })),
      ]
    : [];
  if (foundationEnabled || shadowReadEnabled) {
    recordCognitiveFoundationSignal({
      ok: cognitiveContext != null,
      latencyMs: Date.now() - cognitiveReadStartedAt,
    });
  }
  const stableMemory = foundationEnabled ? cognitiveStableMemory : legacyStableMemory;

  const fallbackRows =
    foundationEnabled ||
    !memoryEnabled ||
    isSocialTurn ||
    stableMemory.length >= Math.min(4, MAX_HINTS)
      ? []
      : await app.db
          .select({
            id:         learningEvents.id,
            type:       learningEvents.type,
            key:        learningEvents.key,
            value:      learningEvents.value,
            confidence: learningEvents.confidence,
            scope:      learningEvents.scope,
            source:     learningEvents.source,
            metadata:   learningEvents.metadata,
            expiresAt:  learningEvents.expiresAt,
            createdAt:  learningEvents.createdAt,
          })
          .from(learningEvents)
          .where(
            and(
              eq(learningEvents.userId, input.userId),
              or(isNull(learningEvents.expiresAt), gt(learningEvents.expiresAt, now)),
            ),
          )
          .orderBy(desc(learningEvents.createdAt))
          .limit(40);

  // The DB-backed signal path may enrich a packet with safe derived facts, but
  // it must inherit the typed packet's permission, relevance and TTL decision.
  // A signal kind absent from the current packet set is never injected.
  const relevantSignalTtlHours = new Map<string, number>();
  for (const packet of contextPackets) {
    if (packet.source !== "world_signal") continue;
    const createdAt = packet.createdAt ? new Date(packet.createdAt) : null;
    const expiresAt = packet.expiresAt ? new Date(packet.expiresAt) : null;
    const ttlHours =
      createdAt &&
      expiresAt &&
      Number.isFinite(createdAt.getTime()) &&
      Number.isFinite(expiresAt.getTime())
        ? Math.max(0, (expiresAt.getTime() - createdAt.getTime()) / 3_600_000)
        : 0;
    if (ttlHours <= 0) continue;
    for (const kind of packet.signalKinds) {
      relevantSignalTtlHours.set(
        kind.toLowerCase(),
        Math.max(relevantSignalTtlHours.get(kind.toLowerCase()) ?? 0, ttlHours),
      );
    }
  }
  const relevantWorldSignals = fuseWorldSignalRecordsByKind(
    freshWorldSignals,
    { now },
  ).filter((signal) => {
    const ttlHours = relevantSignalTtlHours.get(signal.kind.toLowerCase());
    if (!ttlHours) return false;
    const ageHours = Math.max(0, now.getTime() - signal.createdAt.getTime()) / 3_600_000;
    return Number.isFinite(ageHours) && ageHours <= ttlHours;
  });

  const worldDerivedMemory = !memoryEnabled
    ? []
    : deriveLearningSignalsFromWorldSignals(
        relevantWorldSignals.map((signal) =>
          toDerivedSignalInput({
            signalId:   signal.signalId,
            kind:       signal.kind,
            summary:    signal.summary,
            confidence: signal.confidence,
            facts:      signal.facts,
            privacy:    signal.privacy,
            createdAt:  signal.createdAt,
          }),
        ),
      ).map((signal, index) => ({
        id:             `world-derived-${index}-${signal.key}`,
        type:           signal.type,
        key:            signal.key,
        value:          signal.value,
        confidence:     signal.confidence,
        scope:          signal.scope,
        source:         signal.source,
        createdAt:      new Date(),
        staleness:      "fresh" as const,
        conflictStatus: "active" as const,
        lastVerifiedAt: new Date(),
        importanceScore: 72,
        isPinned:       false,
        metadata:       signal.metadata,
      }));

  const durableFallbackMemory = fallbackRows
    .map((row) => ({ ...row, confidence: row.confidence / 100 }))
    .filter((row) => !isWorldDerivedMemory(row as RetrievedMemory));

  // Identity is read on every turn, including social ones and including turns
  // where `stableMemory` already filled the fallback budget. This is the query
  // that makes "benim adım Emre" survive into the next conversation.
  const identityAnchorRows = !memoryEnabled
    ? []
    : await app.db
        .select({
          id:         learningEvents.id,
          type:       learningEvents.type,
          key:        learningEvents.key,
          value:      learningEvents.value,
          confidence: learningEvents.confidence,
          scope:      learningEvents.scope,
          source:     learningEvents.source,
          metadata:   learningEvents.metadata,
          expiresAt:  learningEvents.expiresAt,
          createdAt:  learningEvents.createdAt,
        })
        .from(learningEvents)
        .where(
          and(
            eq(learningEvents.userId, input.userId),
            eq(learningEvents.type, "identity"),
            inArray(learningEvents.key, [...IDENTITY_ANCHOR_KEYS]),
            or(isNull(learningEvents.expiresAt), gt(learningEvents.expiresAt, now)),
          ),
        )
        .orderBy(desc(learningEvents.createdAt))
        .limit(12)
        .catch(() => []);

  const identityAnchorMemory = dedupeIdentityAnchors(
    identityAnchorRows.map((row) => ({
      ...row,
      confidence: row.confidence / 100,
      // Marked pinned so any downstream consumer that honours pinning keeps
      // these too, not just the ranking bypass below.
      isPinned: true,
    })),
  );
  const identityAnchorIds = new Set(identityAnchorMemory.map((row) => row.id));

  const allMemory = [
    ...stableMemory,
    ...worldDerivedMemory,
    ...durableFallbackMemory,
    // Anything the anchor query already returned is dropped here so the same
    // fact cannot appear twice once the anchors are prepended after ranking.
  ].filter((item) => !identityAnchorIds.has((item as { id?: unknown }).id as never));

  /* Average document length for BM25 normalization */
  const avgDocLen = allMemory.length > 0
    ? allMemory.reduce((sum, m) => sum + tokenize(`${m.key} ${m.value}`).size, 0) / allMemory.length
    : 20;

  /* Score with BM25 (C daemon) when available; fall back to JS overlap scorer */
  let memory: typeof allMemory;
  if (nlpDaemon.isAvailable() && allMemory.length > 0) {
    /* Single IPC round-trip for all documents via bm25_batch */
    const docs = allMemory.map((item) => `${(item as { type?: string }).type ?? ""} ${item.key} ${item.value}`);
    const bm25Scores = await nlpDaemon.bm25Batch(query, docs, avgDocLen).catch(() => null);

    const scoringNow = Date.now();
    const scores = allMemory.map((item, i) => {
      const mem = item as RetrievedMemory;
      const bm25 = bm25Scores?.[i] ?? null;
      const referenceTime = mem.lastVerifiedAt?.getTime() ?? mem.createdAt.getTime();
      const ageDays       = Math.max(0, (scoringNow - referenceTime) / 86_400_000);
      const recency       = Math.max(0, 1 - ageDays / 120);
      const stalenessPenalty  = mem.staleness === "contested" ? -1 : mem.staleness === "stale" ? -0.5 : 0.14;
      const conflictPenalty   = mem.conflictStatus === "contested" ? -0.72 : mem.conflictStatus === "superseded" ? -1 : 0.08;
      const pinBoost      = mem.isPinned ? 0.44 : 0;
      const verifiedBoost = mem.lastVerifiedAt ? Math.max(0.08, Math.min(0.28, 0.28 - ageDays / 360)) : 0;
      // Intent-aware type boost: request ile eşleşen memory tiplerine öncelik ver
      const intentTypeBoost = getIntentTypeBoost(mem.type, input.intent.primaryIntent);
      const relevance     = bm25 != null ? bm25 * 2.2 : scoreMemory(mem, queryTokens, scoringNow);
      return relevance + mem.confidence + recency + stalenessPenalty + conflictPenalty + pinBoost + verifiedBoost + intentTypeBoost;
    });

    memory = allMemory
      .map((item, i) => ({ item, score: scores[i] ?? 0 }))
      .sort((a, b) => b.score - a.score)
      .map(({ item }) => item)
      .slice(0, MAX_HINTS);
  } else {
    memory = allMemory
      .sort((left, right) => scoreMemory(right as RetrievedMemory, queryTokens) - scoreMemory(left as RetrievedMemory, queryTokens))
      .slice(0, MAX_HINTS);
  }

  // Prepended *after* the cap, not merged before it: identity must not have to
  // out-score a topically relevant fact to be present. The cap is raised by the
  // anchor count rather than evicting a ranked hint, since these are a handful
  // of very short rows.
  if (identityAnchorMemory.length > 0) {
    memory = [
      ...(identityAnchorMemory as unknown as typeof memory),
      ...memory,
    ] as typeof memory;
  }

  const legacyContinuitySummary = deriveContinuitySummary(input.metadata, {
    userId: input.userId,
    sessionId,
  });
  const continuitySummary = foundationEnabled && cognitiveContext
    ? {
        userGoal: cognitiveContext.working.goal,
        assistantState: cognitiveContext.working.stage,
        openLoops: cognitiveContext.working.openLoops,
      }
    : legacyContinuitySummary;
  const continuityBoundary = deriveContinuityBoundary({
    metadata: input.metadata,
    message: input.message,
    continuitySummary,
    intent: input.intent,
    userId: input.userId,
    sessionId,
  });
  const selectedContinuityMemory = selectContinuityMemory({
    memory: memory as RetrievedMemory[],
    queryTokens,
    intent: input.intent,
    continuitySummary,
    continuityBoundary,
    limit: Math.max(6, MAX_HINTS - 3),
  });
  const derivedPromptMemory = (memory as RetrievedMemory[])
    .filter((item) => isWorldDerivedMemory(item))
    .slice(0, 3);
  // `selectContinuityMemory` re-filters on relevance, so the anchors are
  // re-attached here as well; otherwise they survive ranking only to be
  // dropped one step later.
  const continuityWithoutAnchors = selectedContinuityMemory.filter(
    (item) => !identityAnchorIds.has((item as { id?: unknown }).id as never),
  );
  const promptMemory = [
    ...(identityAnchorMemory as unknown as RetrievedMemory[]),
    ...continuityWithoutAnchors,
    ...derivedPromptMemory,
  ];

  const ctx = buildUserContextFromMemory({
    userId:      input.userId,
    accountId,
    intent:      input.intent,
    task:        input,
    memory:      promptMemory,
    profile:     enrichedProfile,
    contextPackets,
    activeGoal,
    interactionContext: resolveInteractionContext(input),
    ...(currentAffect ? { currentAffect } : {}),
  });
  if (cognitiveContext) {
    ctx.cognitiveReadMs = Date.now() - cognitiveReadStartedAt;
    if (foundationEnabled) {
      ctx.cognitiveContext = cognitiveContext;
    } else {
      const legacyKeys = new Set(legacyStableMemory.map((item) => item.key));
      const cognitiveKeys = new Set(cognitiveContext.semantic.map((item) => item.key));
      ctx.cognitiveShadow = {
        legacyFactCount: legacyStableMemory.length,
        cognitiveFactCount: cognitiveContext.semantic.length,
        keyMismatchCount: new Set(
          [...legacyKeys, ...cognitiveKeys].filter(
            (key) => !legacyKeys.has(key) || !cognitiveKeys.has(key),
          ),
        ).size,
        cognitiveRevision: cognitiveContext.working.memoryRevision,
      };
      recordCognitiveFoundationSignal({
        ok: true,
        keyMismatchCount: ctx.cognitiveShadow.keyMismatchCount,
      });
    }
  }
  if (app.config.ELYAN_USER_MODEL_V2_ENABLED === true) {
    const userModel = buildCanonicalUserModel({
      memory: stableMemory as RetrievedMemory[],
      profile: enrichedProfile,
    });
    ctx.userModel = userModel;
    ctx.memoryRecall = buildMemoryRecallPackage({
      memory: memory as RetrievedMemory[],
      userModel,
      now,
    });
  }

  return ctx;
}
