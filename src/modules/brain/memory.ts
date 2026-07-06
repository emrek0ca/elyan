import { and, desc, eq, gt, inArray, isNull, lt, ne, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  isSingleValueMemoryKey,
  resolveCanonicalMemoryKey,
} from "./memory-key-policy.js";
import {
  brainMemoryEpisodes,
  brainMemoryFacts,
  brainMemoryLinks,
  brainMemoryRuns,
  learningEvents,
  trainingJobs,
} from "../../db/schema.js";
import { cognitiveMemoryRepository } from "./cognitive-memory-repository.js";
import { isCognitiveFoundationEnabled } from "./cognitive-foundation-policy.js";
import type { TurnEnvelope } from "./turn-envelope.js";
import { notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import { invalidateBrainProfileCache } from "./profile-cache.js";
import {
  buildHashedKnowledgeEmbedding,
  canUseHybridRetrieval,
  getRetrievalStatus,
  RETRIEVAL_EMBEDDING_MODEL,
} from "./retrieval.js";
import {
  embedQueryForStorage,
  embedTextsForStorage,
  STORAGE_SEMANTIC_MODEL_TAG,
} from "./semantic-embedder.js";
import { rerankSemanticCandidates } from "./semantic-rerank.js";
import {
  buildContinuityEnrichmentBaseline,
  refineContinuityEnrichmentWithPython,
} from "../../lib/python-continuity-enricher.js";

const MEMORY_VECTOR_DIMENSIONS = 256;
const MEMORY_EXTRACTION_BATCH = 120;
const MEMORY_INDEX_BATCH = 200;
const MEMORY_ACTIVE_JOB_STATUSES = ["queued", "running"] as const;
const MEMORY_FACT_RETENTION_DAYS = 365;
const MEMORY_EPISODE_RETENTION_DAYS = 120;
const MEMORY_STALE_FACT_RETENTION_DAYS = 45;
const MEMORY_STALE_EPISODE_RETENTION_DAYS = 60;
const MEMORY_IMPORTANCE_DECAY_BATCH = 500;
const MEMORY_IMPORTANCE_DECAY_BUDGET_MS = 800;
const MEMORY_IMPORTANCE_DECAY_PER_WEEK = 0.5;
const MEMORY_IMPORTANCE_VERIFIED_BOOST = 3;

type ExecuteRow = Record<string, unknown>;
type MemoryRunKind = "memory_extraction" | "memory_consolidation" | "memory_reconsolidation" | "memory_index";
type MemoryLifecycleStatus = "active" | "contested" | "superseded" | "soft_deleted" | "stale";
type MemorySearchHit = {
  id: string;
  memorySource: "episodic_memory" | "semantic_memory" | "self_model_memory" | "reflective_memory";
  memoryType: string;
  title: string;
  content: string;
  confidence: number;
  staleness: "fresh" | "stale" | "contested";
  importanceScore: number;
  isPinned: boolean;
  conflictStatus: "active" | "contested" | "superseded";
  lifecycleStatus: MemoryLifecycleStatus;
  scope: "user" | "shared";
  score: number;
  lastVerifiedAt: string | null;
  deletedAt: string | null;
  deletedReason: string | null;
  updatedAt: string;
  metadata: Record<string, unknown>;
};

type BrainMemoryRecord = {
  id: string;
  entityType: "fact" | "episode";
  memorySource: MemorySearchHit["memorySource"];
  memoryType: string;
  title: string;
  content: string;
  confidence: number;
  importanceScore: number;
  isPinned: boolean;
  scope: "user" | "shared";
  conflictStatus: "active" | "contested" | "superseded";
  lifecycleStatus: MemoryLifecycleStatus;
  lastVerifiedAt: string | null;
  deletedAt: string | null;
  deletedReason: string | null;
  staleAt: string | null;
  updatedAt: string;
  createdAt: string;
  sourceRunId: string | null;
  metadata: Record<string, unknown>;
};

export type MemoryImportanceDecayInput = {
  factType?: string | null;
  key?: string | null;
  canonicalKey?: string | null;
  importanceScore: number;
  confidence?: number | null;
  isPinned?: boolean | null;
  updatedAt: string | Date;
  lastVerifiedAt?: string | Date | null;
  now?: string | Date;
};

export function resolveMemoryImportanceBaseline(input: {
  factType?: string | null;
  key?: string | null;
  canonicalKey?: string | null;
  isPinned?: boolean | null;
}): number {
  if (input.isPinned === true) {
    return 100;
  }
  const factType = String(input.factType ?? "").toLowerCase();
  const key = `${input.key ?? ""} ${input.canonicalKey ?? ""}`.toLowerCase();
  if (
    factType === "safety" ||
    ["safety", "security", "boundary", "guardrail"].some((token) =>
      key.includes(token),
    )
  ) {
    return 90;
  }
  if (factType === "self_model" || key.startsWith("self_model_")) {
    return 80;
  }
  if (
    factType === "preference" ||
    ["preference", "preferred", "tone", "style"].some((token) =>
      key.includes(token),
    )
  ) {
    return 60;
  }
  if (
    factType === "project_context" ||
    ["project", "stack", "architecture", "constraint", "repo", "route"].some(
      (token) => key.includes(token),
    )
  ) {
    return 50;
  }
  return 30;
}

export function resolveDecayedMemoryImportance(input: MemoryImportanceDecayInput) {
  const now = input.now instanceof Date ? input.now : new Date(input.now ?? Date.now());
  const updatedAt = input.updatedAt instanceof Date ? input.updatedAt : new Date(input.updatedAt);
  const lastVerifiedAt =
    input.lastVerifiedAt == null
      ? null
      : input.lastVerifiedAt instanceof Date
        ? input.lastVerifiedAt
        : new Date(input.lastVerifiedAt);
  const ageDays = Number.isFinite(updatedAt.getTime())
    ? Math.max(0, (now.getTime() - updatedAt.getTime()) / 86_400_000)
    : 0;
  const decay = (ageDays / 7) * MEMORY_IMPORTANCE_DECAY_PER_WEEK;
  const recentlyVerified =
    lastVerifiedAt != null &&
    Number.isFinite(lastVerifiedAt.getTime()) &&
    now.getTime() - lastVerifiedAt.getTime() <= 7 * 86_400_000;
  const verifiedBoost =
    Number(input.confidence ?? 0) >= 80 && recentlyVerified
      ? MEMORY_IMPORTANCE_VERIFIED_BOOST
      : 0;
  const baseline = resolveMemoryImportanceBaseline(input);
  const next = Math.max(
    baseline,
    Math.min(100, Math.round(Number(input.importanceScore) - decay + verifiedBoost)),
  );

  return {
    importanceScore: next,
    baseline,
    decay,
    verifiedBoost,
  };
}

const SYNTHETIC_MEMORY_PRESENTATION: Record<string, { title: string; description: string }> = {
  self_model_recent_topics: {
    title: "Recent Topics",
    description: "Recently recurring conversation themes inferred from your own memory history.",
  },
  reflective_continuity_style: {
    title: "Continuity Style",
    description: "How Elyan should carry multi-turn work forward for you.",
  },
  reflective_reasoning_style: {
    title: "Reasoning Style",
    description: "How Elyan should reason through ongoing work based on prior interaction patterns.",
  },
};

export type MemoryRecallCandidate = {
  memorySource: MemorySearchHit["memorySource"];
  memoryType: string;
  confidence: number;
  staleness: MemorySearchHit["staleness"];
  importanceScore: number;
  isPinned: boolean;
  conflictStatus: MemorySearchHit["conflictStatus"];
  updatedAt: string;
  lastVerifiedAt?: string | null;
  lexicalScore?: number;
  semanticScore?: number;
  metadata?: Record<string, unknown>;
};

function toRows(input: unknown): ExecuteRow[] {
  if (Array.isArray(input)) {
    return input as ExecuteRow[];
  }
  if (input && typeof input === "object" && Array.isArray((input as { rows?: unknown[] }).rows)) {
    return (input as { rows: ExecuteRow[] }).rows;
  }
  return [];
}

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function cleanSyntheticMemoryContent(value: string): string {
  return compactText(value)
    .replace(/^Recent recurring topics:\s*/i, "")
    .replace(/\s*;\s*/g, ". ");
}

function applyMemoryPresentation(record: BrainMemoryRecord): BrainMemoryRecord {
  const preset = SYNTHETIC_MEMORY_PRESENTATION[record.title] ?? SYNTHETIC_MEMORY_PRESENTATION[record.memoryType];
  if (!preset) {
    return record;
  }

  return {
    ...record,
    title: preset.title,
    content: cleanSyntheticMemoryContent(record.content),
    metadata: {
      ...record.metadata,
      presentation: {
        kind: "synthetic_profile_memory",
        editable: true,
        deletable: true,
        description: preset.description,
      },
    },
  };
}

function normalizeMemoryValue(value: string): string {
  return compactText(value).toLowerCase();
}

function tokenize(text: string): string[] {
  return compactText(text)
    .toLowerCase()
    .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
    .split(/\s+/)
    .filter((token) => token.length >= 2)
    .slice(0, 80);
}

function vectorLiteral(vector: number[]): string {
  return `[${vector.map((value) => Number(value.toFixed(6))).join(",")}]`;
}

export function buildVectorSql(vector: number[]) {
  return sql`${vectorLiteral(vector)}::vector`;
}

const memorySemanticV2Ready = new WeakMap<FastifyInstance, Promise<boolean>>();

async function ensureMemorySemanticV2Columns(app: FastifyInstance): Promise<boolean> {
  const cached = memorySemanticV2Ready.get(app);
  if (cached) return cached;
  const pending = (async () => {
    try {
      await app.db.execute(sql`
        create extension if not exists vector
      `);
      await app.db.execute(sql`
        alter table brain_memory_facts
          add column if not exists embedding_v2 vector(384),
          add column if not exists embedding_v2_model varchar(96)
      `);
      await app.db.execute(sql`
        alter table brain_memory_episodes
          add column if not exists embedding_v2 vector(384),
          add column if not exists embedding_v2_model varchar(96)
      `);
      return true;
    } catch (error) {
      app.log?.warn?.({ error }, "memory semantic v2 columns unavailable");
      return false;
    }
  })();
  memorySemanticV2Ready.set(app, pending);
  return pending;
}

function lexicalOverlapScore(query: string, text: string): number {
  const haystack = compactText(text).toLowerCase();
  const tokens = tokenize(query);
  const overlap = tokens.reduce((count, token) => count + (haystack.includes(token) ? 1 : 0), 0);
  const exactBonus = haystack.includes(compactText(query).toLowerCase()) ? 4 : 0;
  return exactBonus + overlap * 2;
}

function safeMetadata(input: unknown): Record<string, unknown> {
  return input && typeof input === "object" && !Array.isArray(input) ? (input as Record<string, unknown>) : {};
}

function parseBoolean(value: unknown): boolean {
  return value === true || value === "t" || value === "true" || value === 1;
}

function normalizeDateString(value: unknown): string | null {
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return null;
}

function normalizeLifecycleStatus(value: unknown): MemoryLifecycleStatus {
  return value === "contested" ||
    value === "superseded" ||
    value === "soft_deleted" ||
    value === "stale"
    ? value
    : "active";
}

function deriveLifecycleFromState(input: {
  lifecycleStatus?: unknown;
  conflictStatus?: unknown;
  staleAt?: unknown;
  deletedAt?: unknown;
}): MemoryLifecycleStatus {
  if (input.deletedAt) {
    return "soft_deleted";
  }
  const direct = normalizeLifecycleStatus(input.lifecycleStatus);
  if (direct !== "active") {
    return direct;
  }
  if (input.conflictStatus === "superseded") {
    return "superseded";
  }
  if (input.conflictStatus === "contested") {
    return "contested";
  }
  if (input.staleAt) {
    return "stale";
  }
  return "active";
}

function agePenalty(updatedAt: string): number {
  const timestamp = Date.parse(updatedAt);
  if (!Number.isFinite(timestamp)) {
    return 0;
  }
  const ageDays = Math.max(0, (Date.now() - timestamp) / 86_400_000);
  if (ageDays <= 7) {
    return 0.14;
  }
  if (ageDays <= 30) {
    return 0.06;
  }
  if (ageDays <= 90) {
    return 0;
  }
  return -0.08;
}

function verificationFreshnessScore(lastVerifiedAt: string | null | undefined): number {
  if (!lastVerifiedAt) {
    return 0;
  }

  const timestamp = Date.parse(lastVerifiedAt);
  if (!Number.isFinite(timestamp)) {
    return 0;
  }

  const ageDays = Math.max(0, (Date.now() - timestamp) / 86_400_000);
  if (ageDays <= 7) {
    return 0.24;
  }
  if (ageDays <= 30) {
    return 0.16;
  }
  if (ageDays <= 90) {
    return 0.08;
  }
  return 0.03;
}

function getMemorySourcePriority(input: MemoryRecallCandidate): number {
  const projectCritical = parseBoolean(input.metadata?.projectCritical);
  if (input.memorySource === "semantic_memory" && (input.isPinned || projectCritical)) {
    return 1;
  }
  if (input.memorySource === "episodic_memory") {
    return 0.72;
  }
  if (input.memorySource === "self_model_memory" || input.memorySource === "reflective_memory") {
    return 0.52;
  }
  return 0.34;
}

export function scoreMemoryRecallCandidate(input: MemoryRecallCandidate): number {
  const lexicalComponent = Math.min(1, Math.max(0, (input.lexicalScore ?? 0) / 12));
  const semanticComponent = Math.min(1, Math.max(0, input.semanticScore ?? 0));
  const confidenceComponent = Math.min(1, Math.max(0, input.confidence / 100));
  const importanceComponent = Math.min(1, Math.max(0, input.importanceScore / 100));
  const sourcePriority = getMemorySourcePriority(input);
  const stalenessPenalty = input.staleness === "contested" ? -0.8 : input.staleness === "stale" ? -0.35 : 0.12;
  const conflictPenalty =
    input.conflictStatus === "contested" ? -0.68 : input.conflictStatus === "superseded" ? -0.86 : 0.06;
  const pinBoost = input.isPinned ? 0.36 : 0;
  const recencyComponent = agePenalty(input.updatedAt);
  const verifiedBoost = verificationFreshnessScore(input.lastVerifiedAt);

  return Number(
    (
      sourcePriority +
      semanticComponent * 0.32 +
      lexicalComponent * 0.22 +
      confidenceComponent * 0.18 +
      importanceComponent * 0.14 +
      pinBoost +
      verifiedBoost +
      recencyComponent +
      stalenessPenalty +
      conflictPenalty
    ).toFixed(4),
  );
}

function normalizeMemorySource(memoryType: string): MemorySearchHit["memorySource"] {
  if (memoryType === "self_model") {
    return "self_model_memory";
  }
  if (memoryType === "reflective") {
    return "reflective_memory";
  }
  return "semantic_memory";
}

function buildMemoryHit(input: {
  id: unknown;
  memorySource: MemorySearchHit["memorySource"];
  memoryType: unknown;
  title: unknown;
  content: unknown;
  confidence: unknown;
  staleness: MemorySearchHit["staleness"];
  importanceScore: unknown;
  isPinned: unknown;
  conflictStatus: unknown;
  lifecycleStatus?: unknown;
  scope: unknown;
  lexicalScore?: unknown;
  semanticScore?: unknown;
  lastVerifiedAt?: unknown;
  deletedAt?: unknown;
  deletedReason?: unknown;
  updatedAt: unknown;
  metadata: unknown;
}): MemorySearchHit {
  const metadata = safeMetadata(input.metadata);
  const confidence = Number(input.confidence ?? 50);
  const importanceScore = Number(input.importanceScore ?? 50);
  const updatedAt = normalizeDateString(input.updatedAt) ?? new Date().toISOString();
  const conflictStatus =
    input.conflictStatus === "contested" || input.conflictStatus === "superseded"
      ? input.conflictStatus
      : "active";

  return {
    id: String(input.id),
    memorySource: input.memorySource,
    memoryType: String(input.memoryType ?? "semantic"),
    title: String(input.title ?? ""),
    content: String(input.content ?? ""),
    confidence,
    staleness: input.staleness,
    importanceScore,
    isPinned: parseBoolean(input.isPinned),
    conflictStatus,
    lifecycleStatus: deriveLifecycleFromState({
      lifecycleStatus: input.lifecycleStatus,
      conflictStatus,
      deletedAt: input.deletedAt,
      staleAt: input.staleness === "stale" || input.staleness === "contested" ? true : null,
    }),
    scope: (input.scope === "shared" ? "shared" : "user") as "shared" | "user",
    score: scoreMemoryRecallCandidate({
      memorySource: input.memorySource,
      memoryType: String(input.memoryType ?? "semantic"),
      confidence,
      staleness: input.staleness,
      importanceScore,
      isPinned: parseBoolean(input.isPinned),
      conflictStatus,
      updatedAt,
      lexicalScore: Number(input.lexicalScore ?? 0),
      semanticScore: Number(input.semanticScore ?? 0),
      metadata,
      lastVerifiedAt: normalizeDateString(input.lastVerifiedAt),
    }),
    lastVerifiedAt: normalizeDateString(input.lastVerifiedAt),
    deletedAt: normalizeDateString(input.deletedAt),
    deletedReason: typeof input.deletedReason === "string" && input.deletedReason.trim() ? input.deletedReason : null,
    updatedAt,
    metadata,
  };
}

export async function readCanonicalMemoryState(
  app: FastifyInstance,
  userId: string,
): Promise<MemorySearchHit[]> {
  const rows = await app.db
    .select({
      id: brainMemoryFacts.id,
      memoryType: brainMemoryFacts.factType,
      title: brainMemoryFacts.canonicalKey,
      content: brainMemoryFacts.value,
      confidence: brainMemoryFacts.confidence,
      importanceScore: brainMemoryFacts.importanceScore,
      scope: brainMemoryFacts.scope,
      lastVerifiedAt: brainMemoryFacts.lastVerifiedAt,
      updatedAt: brainMemoryFacts.updatedAt,
      metadata: brainMemoryFacts.metadata,
    })
    .from(brainMemoryFacts)
    .where(
      and(
        eq(brainMemoryFacts.userId, userId),
        eq(brainMemoryFacts.conflictStatus, "active"),
        eq(brainMemoryFacts.lifecycleStatus, "active"),
        isNull(brainMemoryFacts.deletedAt),
        inArray(brainMemoryFacts.canonicalKey, [
          "name",
          "preferred_name",
          "preferred_language",
          "preferred_tone",
          "response_style_preference",
          "timezone",
        ]),
      ),
    )
    .orderBy(desc(brainMemoryFacts.updatedAt))
    .limit(8);

  return rows.map((row) =>
    buildMemoryHit({
      ...row,
      memorySource: normalizeMemorySource(row.memoryType),
      staleness: "fresh",
      isPinned: true,
      conflictStatus: "active",
      lifecycleStatus: "active",
      lexicalScore: 12,
      semanticScore: 1,
      deletedAt: null,
      deletedReason: null,
    }),
  );
}

function dedupeMemoryHits(results: MemorySearchHit[]): MemorySearchHit[] {
  const bestByKey = new Map<string, MemorySearchHit>();
  for (const result of results) {
    const key = `${result.memorySource}:${result.id}`;
    const current = bestByKey.get(key);
    if (!current || result.score > current.score) {
      bestByKey.set(key, result);
    }
  }
  return [...bestByKey.values()];
}

export function prioritizeCanonicalMemoryState(
  results: MemorySearchHit[],
  limit: number,
): MemorySearchHit[] {
  const deduped = dedupeMemoryHits(results);
  const canonical = deduped
    .filter(
      (result) =>
        result.memorySource !== "episodic_memory" &&
        result.conflictStatus === "active" &&
        result.lifecycleStatus === "active" &&
        isSingleValueMemoryKey(result.title),
    )
    .sort(
      (left, right) =>
        Date.parse(right.updatedAt) - Date.parse(left.updatedAt) ||
        right.confidence - left.confidence,
    );
  const canonicalIds = new Set(canonical.map((result) => result.id));
  return [
    ...canonical,
    ...deduped.filter((result) => !canonicalIds.has(result.id)),
  ].slice(0, Math.max(1, limit));
}

function isHighValueLearningKey(key: string): boolean {
  return [
    "name",
    "preferred_name",
    "job_title",
    "company",
    "location",
    "timezone",
    "preferred_language",
    "preferred_tone",
    "response_style_preference",
    "humor_level",
    "humor_feedback",
    "task_handoff_helpfulness",
    "mobile_sync_quality",
    "session_recovered",
    "task_completed",
    "task_not_completed",
    "emotional_signal",
    "user_mood",
    "user_excitement",
    "user_frustration",
    "important_decision",
    "life_event",
    "conversation_highlight",
    "positive_feedback",
    "negative_feedback",
    "project_constraint",
    "routing_mode",
    "energy_rhythm",
    "planning_style",
    "schedule_pressure_pattern",
    "mobility_context",
    "local_preference_context",
    "notification_attention_pattern",
    "preferred_working_window",
    "common_city",
    "preferred_planning_granularity",
  ].includes(key);
}

function inferFactType(key: string): "semantic" | "self_model" | "reflective" {
  if (key.startsWith("self_model_")) {
    return "self_model";
  }
  if ([
    "task_handoff_helpfulness",
    "mobile_sync_quality",
    "positive_feedback",
    "negative_feedback",
    "emotional_signal",
    "user_mood",
    "user_excitement",
    "user_frustration",
    "energy_rhythm",
    "planning_style",
    "schedule_pressure_pattern",
    "notification_attention_pattern",
    "preferred_planning_granularity",
  ].includes(key)) {
    return "reflective";
  }
  return "semantic";
}

function readMetadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readMetadataString(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function computeLearningValueScore(input: {
  key: string;
  value: string;
  type: string;
  source: string;
  confidence: number;
  metadata: Record<string, unknown>;
}): number {
  const key = input.key;
  let score = Math.max(0, Math.min(1, input.confidence / 100)) * 42;

  if ([
    "name",
    "preferred_name",
    "preferred_language",
    "preferred_tone",
    "response_style_preference",
    "project_constraint",
    "implementation_boundary",
    "privacy_boundary",
  ].includes(key)) {
    score += 34;
  }
  if ([
    "important_decision",
    "life_event",
    "conversation_highlight",
    "negative_feedback",
    "positive_feedback",
    "task_handoff_helpfulness",
  ].includes(key)) {
    score += 28;
  }
  if ([
    "emotional_signal",
    "user_mood",
    "user_excitement",
    "user_frustration",
    "energy_rhythm",
    "planning_style",
    "schedule_pressure_pattern",
  ].includes(key)) {
    score += 18;
  }
  if (input.type === "style" || input.type === "preference") score += 10;
  if (input.type === "technical_stack" || input.type === "project_context") score += 8;
  if (input.source === "feedback") score += 14;
  if (input.source === "runtime") score -= 8;
  if (input.metadata.explicit === true) score += 18;
  if (readMetadataString(input.metadata, "sourceBlobHash")) score += 8;

  const sentimentScore = readMetadataNumber(input.metadata, "sentimentScore");
  if (sentimentScore != null && sentimentScore >= 0.72) score += 8;
  const tokenCount = readMetadataNumber(input.metadata, "tokenCount");
  if (tokenCount != null && tokenCount >= 18) score += 5;

  const compactValue = compactText(input.value);
  if (compactValue.length < 2) score -= 20;
  if (compactValue.length > 240 && key !== "project_constraint") score -= 10;
  if (key === "message_keywords") score -= 28;
  if (/^(ok|tamam|evet|hayır|hayir|thanks|teşekkürler?)$/i.test(compactValue)) score -= 20;

  return Math.max(0, Math.min(100, Math.round(score)));
}

function shouldPromoteLearningEvent(input: {
  key: string;
  type: string;
  confidence: number;
  metadata: Record<string, unknown>;
  learningValueScore: number;
}): boolean {
  if (!isHighValueLearningKey(input.key)) {
    return false;
  }
  if (input.metadata.explicit === true) {
    return true;
  }
  if ([
    "name",
    "preferred_name",
    "preferred_language",
    "project_constraint",
    "privacy_boundary",
    "implementation_boundary",
    "negative_feedback",
  ].includes(input.key)) {
    return input.confidence >= 55;
  }
  if (input.type === "workflow" && input.key === "task_completed") {
    return input.learningValueScore >= 72;
  }
  return input.learningValueScore >= 58;
}

function computeImportanceScore(input: { key: string; count: number; confidence: number; learningValueScore?: number }): number {
  const base =
    ["name", "preferred_name", "job_title", "company", "location", "timezone"].includes(input.key)
      ? 88
      : input.key === "preferred_language"
        ? 84
        : input.key === "preferred_tone" || input.key === "response_style_preference"
      ? 82
      : input.key === "task_handoff_helpfulness" || input.key === "mobile_sync_quality"
        ? 76
        : input.key === "emotional_signal" || input.key === "user_mood" || input.key === "user_frustration"
          ? 74
          : input.key === "planning_style" || input.key === "energy_rhythm" || input.key === "schedule_pressure_pattern"
            ? 72
        : input.key === "positive_feedback" || input.key === "negative_feedback"
          ? 68
          : 60;
  const learningBoost = input.learningValueScore == null ? 0 : Math.round((input.learningValueScore - 50) * 0.28);
  return Math.max(1, Math.min(99, Math.round(base + input.count * 3 + input.confidence * 0.1 + learningBoost)));
}

function summarizeEpisode(key: string, value: string): string {
  if (key === "name") {
    return `User explicitly shared their name as ${value}.`;
  }
  if (key === "preferred_name") {
    return `User explicitly shared their preferred name as ${value}.`;
  }
  if (key === "job_title") {
    return `User explicitly shared their job title as ${value}.`;
  }
  if (key === "company") {
    return `User explicitly shared their company as ${value}.`;
  }
  if (key === "location") {
    return `User explicitly shared their location as ${value}.`;
  }
  if (key === "timezone") {
    return `User explicitly shared their timezone as ${value}.`;
  }
  if (key === "preferred_language") {
    return `User explicitly shared their preferred language as ${value}.`;
  }
  if (key === "session_recovered") {
    return "Mobile session recovered successfully after reconnect.";
  }
  if (key === "task_handoff_helpfulness") {
    return `Task handoff outcome: ${value}.`;
  }
  if (key === "negative_feedback") {
    return `User marked an answer as unhelpful: ${value}.`;
  }
  if (key === "positive_feedback") {
    return `User marked an answer as helpful: ${value}.`;
  }
  if (key === "emotional_signal" || key === "user_mood") {
    return `User's recent emotional state in the conversation was ${value}.`;
  }
  if (key === "user_frustration") {
    return `User showed frustration about: ${value}.`;
  }
  if (key === "user_excitement") {
    return `User showed excitement about: ${value}.`;
  }
  if (key === "important_decision") {
    return `Important decision captured from the conversation: ${value}.`;
  }
  if (key === "life_event") {
    return `User shared a meaningful life event: ${value}.`;
  }
  if (key === "conversation_highlight") {
    return `Conversation highlight: ${value}.`;
  }
  return `${key}: ${value}`;
}

function requiresRepeatedEvidenceForSemanticFact(key: string): boolean {
  return ![
    "name",
    "preferred_name",
    "job_title",
    "company",
    "location",
    "timezone",
    "preferred_language",
    "preferred_tone",
    "response_style_preference",
    "project_constraint",
  ].includes(key);
}

export async function getBrainMemoryStatus(app: FastifyInstance, userId: string) {
  if (typeof (app.db as { execute?: unknown }).execute !== "function") {
    return {
      pipelineReady: false,
      episodicMemoryCount: 0,
      semanticMemoryCount: 0,
      selfModelMemoryCount: 0,
      reflectiveMemoryCount: 0,
      pinnedMemoryCount: 0,
      softDeletedCount: 0,
      staleMemoryCount: 0,
      contestedMemoryCount: 0,
      lastConsolidatedAt: null,
      lastReconsolidatedAt: null,
      lastSelfModelUpdatedAt: null,
      lastIndexedAt: null,
      memoryIndexCoverage: 0,
      memorySources: [],
    };
  }

  try {
    const [episodeCounts, factCounts, runCounts] = await Promise.all([
      app.db.execute(sql`
        select
          count(*) filter (where coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "episodicCount",
          count(*) filter (where embedding_model is not null and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "episodicIndexedCount",
          count(*) filter (where stale_at is not null and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "episodicStaleCount",
          count(*) filter (where is_pinned = true and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "episodicPinnedCount",
          count(*) filter (where coalesce(lifecycle_status, 'active') = 'soft_deleted') as "episodicSoftDeletedCount"
        from brain_memory_episodes
        where user_id = ${userId}
      `),
      app.db.execute(sql`
        select
          count(*) filter (where fact_type = 'semantic' and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "semanticCount",
          count(*) filter (where fact_type = 'self_model' and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "selfModelCount",
          count(*) filter (where fact_type = 'reflective' and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "reflectiveCount",
          count(*) filter (where embedding_model is not null and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "factIndexedCount",
          count(*) filter (where is_pinned = true and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "pinnedCount",
          count(*) filter (where stale_at is not null and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "factStaleCount",
          count(*) filter (where conflict_status = 'contested' and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "contestedCount",
          count(*) filter (where coalesce(lifecycle_status, 'active') = 'soft_deleted') as "factSoftDeletedCount",
          max(updated_at) filter (where fact_type = 'self_model' and coalesce(lifecycle_status, 'active') <> 'soft_deleted') as "lastSelfModelUpdatedAt"
        from brain_memory_facts
        where user_id = ${userId}
      `),
      app.db.execute(sql`
        select
          max(completed_at) filter (where run_kind = 'memory_consolidation' and status = 'completed') as "lastConsolidatedAt",
          max(completed_at) filter (where run_kind = 'memory_reconsolidation' and status = 'completed') as "lastReconsolidatedAt",
          max(completed_at) filter (where run_kind = 'memory_index' and status = 'completed') as "lastIndexedAt"
        from brain_memory_runs
        where user_id = ${userId}
      `),
    ]);

    const episodeRow = toRows(episodeCounts)[0] ?? {};
    const factRow = toRows(factCounts)[0] ?? {};
    const runRow = toRows(runCounts)[0] ?? {};

    const episodicMemoryCount = Number(episodeRow.episodicCount ?? 0);
    const semanticMemoryCount = Number(factRow.semanticCount ?? 0);
    const selfModelMemoryCount = Number(factRow.selfModelCount ?? 0);
    const reflectiveMemoryCount = Number(factRow.reflectiveCount ?? 0);
    const episodicIndexedCount = Number(episodeRow.episodicIndexedCount ?? 0);
    const factIndexedCount = Number(factRow.factIndexedCount ?? 0);
    const totalMemoryRecords =
      episodicMemoryCount + semanticMemoryCount + selfModelMemoryCount + reflectiveMemoryCount;
    const indexedMemoryRecords = episodicIndexedCount + factIndexedCount;

    return {
      pipelineReady: true,
      episodicMemoryCount,
      semanticMemoryCount,
      selfModelMemoryCount,
      reflectiveMemoryCount,
      pinnedMemoryCount: Number(factRow.pinnedCount ?? 0) + Number(episodeRow.episodicPinnedCount ?? 0),
      softDeletedCount: Number(factRow.factSoftDeletedCount ?? 0) + Number(episodeRow.episodicSoftDeletedCount ?? 0),
      staleMemoryCount: Number(episodeRow.episodicStaleCount ?? 0) + Number(factRow.factStaleCount ?? 0),
      contestedMemoryCount: Number(factRow.contestedCount ?? 0),
      lastConsolidatedAt:
        runRow.lastConsolidatedAt instanceof Date
          ? runRow.lastConsolidatedAt.toISOString()
          : runRow.lastConsolidatedAt == null
            ? null
            : String(runRow.lastConsolidatedAt),
      lastReconsolidatedAt:
        runRow.lastReconsolidatedAt instanceof Date
          ? runRow.lastReconsolidatedAt.toISOString()
          : runRow.lastReconsolidatedAt == null
            ? null
            : String(runRow.lastReconsolidatedAt),
      lastIndexedAt:
        runRow.lastIndexedAt instanceof Date
          ? runRow.lastIndexedAt.toISOString()
          : runRow.lastIndexedAt == null
            ? null
            : String(runRow.lastIndexedAt),
      lastSelfModelUpdatedAt:
        factRow.lastSelfModelUpdatedAt instanceof Date
          ? factRow.lastSelfModelUpdatedAt.toISOString()
          : factRow.lastSelfModelUpdatedAt == null
            ? null
            : String(factRow.lastSelfModelUpdatedAt),
      memoryIndexCoverage:
        totalMemoryRecords <= 0 ? 0 : Number(((indexedMemoryRecords / totalMemoryRecords) * 100).toFixed(1)),
      memorySources: [
        { source: "episodic_memory", count: episodicMemoryCount, indexed: episodicIndexedCount },
        { source: "semantic_memory", count: semanticMemoryCount, indexed: factIndexedCount },
        { source: "self_model_memory", count: selfModelMemoryCount, indexed: factIndexedCount },
        { source: "reflective_memory", count: reflectiveMemoryCount, indexed: factIndexedCount },
      ],
    };
  } catch {
    return {
      pipelineReady: false,
      episodicMemoryCount: 0,
      semanticMemoryCount: 0,
      selfModelMemoryCount: 0,
      reflectiveMemoryCount: 0,
      pinnedMemoryCount: 0,
      softDeletedCount: 0,
      staleMemoryCount: 0,
      contestedMemoryCount: 0,
      lastConsolidatedAt: null,
      lastReconsolidatedAt: null,
      lastSelfModelUpdatedAt: null,
      lastIndexedAt: null,
      memoryIndexCoverage: 0,
      memorySources: [],
    };
  }
}

/**
 * Total wall-clock budget for the DB portion of memory retrieval. Beyond this,
 * we return an empty lexical fallback so the inference path is never blocked
 * by a slow Postgres — memory is best-effort context, never a critical
 * dependency. 800ms is generous vs the typical <30ms actual query time; only
 * pathological cases (locked table, primary failover, pool exhaustion) can
 * cross it, and we should degrade fast when they do.
 */
const MEMORY_SEARCH_BUDGET_MS = 800;
const MEMORY_BUDGET_EXPIRED = Symbol("memory_search_budget_expired");

function withMemoryBudget<T>(work: Promise<T>, budgetMs: number): Promise<T | typeof MEMORY_BUDGET_EXPIRED> {
  return new Promise((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve(MEMORY_BUDGET_EXPIRED);
    }, budgetMs);
    work.then(
      (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(MEMORY_BUDGET_EXPIRED);
      },
    );
  });
}

export async function processMemoryImportanceDecay(
  app: FastifyInstance,
  input: { now?: Date } = {},
) {
  if (typeof (app.db as { execute?: unknown }).execute !== "function") {
    return {
      status: "skipped" as const,
      processedCount: 0,
      updatedCount: 0,
      reason: "memory_execute_unavailable" as const,
    };
  }

  const now = input.now ?? new Date();
  const nowIso = now.toISOString();
  const result = await withMemoryBudget(
    (async () => {
      const rows = toRows(
        await app.db.execute(sql`
          select
            id,
            fact_type as "factType",
            key,
            canonical_key as "canonicalKey",
            confidence,
            importance_score as "importanceScore",
            is_pinned as "isPinned",
            updated_at as "updatedAt",
            last_verified_at as "lastVerifiedAt",
            metadata
          from brain_memory_facts
          where coalesce(lifecycle_status, 'active') = 'active'
            and deleted_at is null
            and (
              metadata->>'lastImportanceDecayedAt' is null
              or (metadata->>'lastImportanceDecayedAt')::timestamptz < ${new Date(now.getTime() - 7 * 86_400_000)}
            )
          order by updated_at asc
          limit ${MEMORY_IMPORTANCE_DECAY_BATCH}
        `),
      );

      let updatedCount = 0;
      for (const row of rows) {
        const computed = resolveDecayedMemoryImportance({
          factType: typeof row.factType === "string" ? row.factType : null,
          key: typeof row.key === "string" ? row.key : null,
          canonicalKey:
            typeof row.canonicalKey === "string" ? row.canonicalKey : null,
          importanceScore: Number(row.importanceScore ?? 50),
          confidence: Number(row.confidence ?? 0),
          isPinned: parseBoolean(row.isPinned),
          updatedAt:
            row.updatedAt instanceof Date || typeof row.updatedAt === "string"
              ? row.updatedAt
              : now,
          lastVerifiedAt:
            row.lastVerifiedAt instanceof Date ||
            typeof row.lastVerifiedAt === "string"
              ? row.lastVerifiedAt
              : null,
          now,
        });
        const metadata = {
          ...safeMetadata(row.metadata),
          lastImportanceDecayedAt: nowIso,
          importanceDecay: {
            baseline: computed.baseline,
            decay: Number(computed.decay.toFixed(4)),
            verifiedBoost: computed.verifiedBoost,
          },
        };
        await app.db
          .update(brainMemoryFacts)
          .set({
            importanceScore: computed.importanceScore,
            metadata,
          })
          .where(eq(brainMemoryFacts.id, String(row.id)));
        updatedCount += 1;
      }

      return {
        status: "completed" as const,
        processedCount: rows.length,
        updatedCount,
      };
    })(),
    MEMORY_IMPORTANCE_DECAY_BUDGET_MS,
  );

  if (result === MEMORY_BUDGET_EXPIRED) {
    return {
      status: "skipped" as const,
      processedCount: 0,
      updatedCount: 0,
      reason: "memory_decay_budget_expired" as const,
    };
  }

  return result;
}

export async function searchBrainMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    query: string;
    limit: number;
  },
) {
  if (typeof (app.db as { execute?: unknown }).execute !== "function") {
    return {
      retrievalMode: "lexical_fallback" as const,
      results: [] as MemorySearchHit[],
      degradedReason: "memory_execute_unavailable" as const,
    };
  }

  try {
    const startedAt = Date.now();
    // hybridReady is cached, but the first call in a fresh process hits the DB
    // (pgvector + column checks). Include it in the total budget so a slow
    // Postgres never blocks retrieval even before the main queries start.
    const hybridProbe = await withMemoryBudget(
      canUseHybridRetrieval(app),
      MEMORY_SEARCH_BUDGET_MS,
    );
    if (hybridProbe === MEMORY_BUDGET_EXPIRED) {
      return {
        retrievalMode: "lexical_fallback" as const,
        results: [] as MemorySearchHit[],
        degradedReason: "memory_search_budget_expired" as const,
      };
    }
    const hybridReady = hybridProbe;
    const remainingBudget = Math.max(
      50,
      MEMORY_SEARCH_BUDGET_MS - (Date.now() - startedAt),
    );
    const queryVector = buildVectorSql(buildHashedKnowledgeEmbedding(input.query));
    const semanticV2Ready = hybridReady
      ? await ensureMemorySemanticV2Columns(app)
      : false;
    const semanticQueryVector = semanticV2Ready
      ? await embedQueryForStorage(input.query, app.log).catch(() => null)
      : null;
    const semanticV2QueryVector = semanticQueryVector
      ? buildVectorSql(semanticQueryVector)
      : null;

    // Lexical + (optionally) semantic queries all run in parallel: they hit
    // independent rows via independent indices, and the total wall-clock is
    // dominated by the slowest query instead of the sum. `withMemoryBudget`
    // caps the whole retrieval at MEMORY_SEARCH_BUDGET_MS so a pathologically
    // slow query returns "budget expired" rather than blocking the caller.
    const lexicalFactsQuery = app.db.execute(sql`
      select
        id,
        fact_type as "memoryType",
        canonical_key as "title",
        value as "content",
        confidence,
        importance_score as "importanceScore",
        is_pinned as "isPinned",
        scope,
        conflict_status as "conflictStatus",
        lifecycle_status as "lifecycleStatus",
        deleted_at as "deletedAt",
        deleted_reason as "deletedReason",
        stale_at as "staleAt",
        last_verified_at as "lastVerifiedAt",
        metadata,
        updated_at as "updatedAt"
      from brain_memory_facts
      where user_id = ${input.userId}
        and conflict_status = 'active'
        and lifecycle_status = 'active'
        and deleted_at is null
      order by
        case when canonical_key in ('name', 'preferred_name', 'preferred_language', 'preferred_tone', 'response_style_preference', 'timezone') then 0 else 1 end,
        updated_at desc
      limit ${Math.max(input.limit * 4, 20)}
    `);
    const lexicalEpisodesQuery = app.db.execute(sql`
      select
        id,
        episode_type as "memoryType",
        episode_type as "title",
        summary as "content",
        confidence,
        importance_score as "importanceScore",
        is_pinned as "isPinned",
        scope,
        lifecycle_status as "lifecycleStatus",
        deleted_at as "deletedAt",
        deleted_reason as "deletedReason",
        case when stale_at is null then 'active' else 'stale' end as "conflictStatus",
        stale_at as "staleAt",
        null::timestamp as "lastVerifiedAt",
        metadata,
        updated_at as "updatedAt"
      from brain_memory_episodes
      where user_id = ${input.userId}
        and lifecycle_status = 'active'
        and deleted_at is null
      order by updated_at desc
      limit ${Math.max(input.limit * 4, 20)}
    `);

    // Semantic queries only fire when hybrid retrieval is ready. Starting them
    // OUTSIDE the parallel block keeps a lexical-only path (no pgvector) from
    // paying for phantom semantic waits.
    const semanticFactsQuery = hybridReady
      ? semanticV2QueryVector
        ? app.db.execute(sql`
      select
        id,
        fact_type as "memoryType",
        canonical_key as "title",
        value as "content",
        confidence,
        importance_score as "importanceScore",
        is_pinned as "isPinned",
        scope,
        conflict_status as "conflictStatus",
        lifecycle_status as "lifecycleStatus",
        deleted_at as "deletedAt",
        deleted_reason as "deletedReason",
        stale_at as "staleAt",
        last_verified_at as "lastVerifiedAt",
        metadata,
        updated_at as "updatedAt",
        case
          when embedding_v2 is not null then 1 - (embedding_v2 <=> ${semanticV2QueryVector})
          else 1 - (embedding <=> ${queryVector})
        end as "semanticScore"
      from brain_memory_facts
      where user_id = ${input.userId}
        and (embedding_v2 is not null or embedding_model is not null)
        and conflict_status = 'active'
        and lifecycle_status = 'active'
        and deleted_at is null
      order by
        case
          when embedding_v2 is not null then embedding_v2 <=> ${semanticV2QueryVector}
          else embedding <=> ${queryVector}
        end
      limit ${Math.max(input.limit * 2, 10)}
    `)
        : app.db.execute(sql`
      select
        id,
        fact_type as "memoryType",
        canonical_key as "title",
        value as "content",
        confidence,
        importance_score as "importanceScore",
        is_pinned as "isPinned",
        scope,
        conflict_status as "conflictStatus",
        lifecycle_status as "lifecycleStatus",
        deleted_at as "deletedAt",
        deleted_reason as "deletedReason",
        stale_at as "staleAt",
        last_verified_at as "lastVerifiedAt",
        metadata,
        updated_at as "updatedAt",
        1 - (embedding <=> ${queryVector}) as "semanticScore"
      from brain_memory_facts
      where user_id = ${input.userId}
        and embedding_model is not null
        and conflict_status = 'active'
        and lifecycle_status = 'active'
        and deleted_at is null
      order by embedding <=> ${queryVector}
      limit ${Math.max(input.limit * 2, 10)}
    `)
      : Promise.resolve(null);
    const semanticEpisodesQuery = hybridReady
      ? semanticV2QueryVector
        ? app.db.execute(sql`
      select
        id,
        episode_type as "memoryType",
        episode_type as "title",
        summary as "content",
        confidence,
        importance_score as "importanceScore",
        is_pinned as "isPinned",
        scope,
        lifecycle_status as "lifecycleStatus",
        deleted_at as "deletedAt",
        deleted_reason as "deletedReason",
        stale_at as "staleAt",
        null::timestamp as "lastVerifiedAt",
        metadata,
        updated_at as "updatedAt",
        case
          when embedding_v2 is not null then 1 - (embedding_v2 <=> ${semanticV2QueryVector})
          else 1 - (embedding <=> ${queryVector})
        end as "semanticScore"
      from brain_memory_episodes
      where user_id = ${input.userId}
        and (embedding_v2 is not null or embedding_model is not null)
        and lifecycle_status = 'active'
        and deleted_at is null
      order by
        case
          when embedding_v2 is not null then embedding_v2 <=> ${semanticV2QueryVector}
          else embedding <=> ${queryVector}
        end
      limit ${Math.max(input.limit * 2, 10)}
    `)
        : app.db.execute(sql`
      select
        id,
        episode_type as "memoryType",
        episode_type as "title",
        summary as "content",
        confidence,
        importance_score as "importanceScore",
        is_pinned as "isPinned",
        scope,
        lifecycle_status as "lifecycleStatus",
        deleted_at as "deletedAt",
        deleted_reason as "deletedReason",
        stale_at as "staleAt",
        null::timestamp as "lastVerifiedAt",
        metadata,
        updated_at as "updatedAt",
        1 - (embedding <=> ${queryVector}) as "semanticScore"
      from brain_memory_episodes
      where user_id = ${input.userId}
        and embedding_model is not null
        and lifecycle_status = 'active'
        and deleted_at is null
      order by embedding <=> ${queryVector}
      limit ${Math.max(input.limit * 2, 10)}
    `)
      : Promise.resolve(null);

    const budgetResult = await withMemoryBudget(
      Promise.all([
        lexicalFactsQuery,
        lexicalEpisodesQuery,
        semanticFactsQuery,
        semanticEpisodesQuery,
      ]),
      remainingBudget,
    );
    if (budgetResult === MEMORY_BUDGET_EXPIRED) {
      return {
        retrievalMode: "lexical_fallback" as const,
        results: [] as MemorySearchHit[],
        degradedReason: "memory_search_budget_expired" as const,
      };
    }
    const [lexicalFacts, lexicalEpisodes, semanticFactsRaw, semanticEpisodesRaw] = budgetResult;

    const lexicalResults = [
      ...toRows(lexicalFacts).map((row) =>
        buildMemoryHit({
          id: row.id,
          memorySource: normalizeMemorySource(String(row.memoryType ?? "semantic")),
          memoryType: row.memoryType,
          title: row.title,
          content: row.content,
          confidence: row.confidence,
          staleness:
            row.conflictStatus === "contested"
              ? "contested"
              : row.staleAt
                ? "stale"
                : "fresh",
          importanceScore: row.importanceScore,
          isPinned: row.isPinned,
          conflictStatus: row.conflictStatus,
          lifecycleStatus: row.lifecycleStatus,
          scope: row.scope,
          lexicalScore: lexicalOverlapScore(input.query, `${row.title ?? ""} ${row.content ?? ""}`),
          lastVerifiedAt: row.lastVerifiedAt,
          deletedAt: row.deletedAt,
          deletedReason: row.deletedReason,
          updatedAt: row.updatedAt,
          metadata: row.metadata,
        }),
      ),
      ...toRows(lexicalEpisodes).map((row) =>
        buildMemoryHit({
          id: row.id,
          memorySource: "episodic_memory",
          memoryType: row.memoryType,
          title: row.title,
          content: row.content,
          confidence: row.confidence,
          staleness: row.staleAt ? "stale" : "fresh",
          importanceScore: row.importanceScore,
          isPinned: row.isPinned,
          lexicalScore: lexicalOverlapScore(input.query, `${row.title ?? ""} ${row.content ?? ""}`),
          conflictStatus: row.staleAt ? "superseded" : "active",
          lifecycleStatus: row.lifecycleStatus,
          scope: row.scope,
          lastVerifiedAt: row.lastVerifiedAt,
          deletedAt: row.deletedAt,
          deletedReason: row.deletedReason,
          updatedAt: row.updatedAt,
          metadata: row.metadata,
        }),
      ),
    ]
      .sort((left, right) => right.score - left.score || right.confidence - left.confidence);

    if (!hybridReady) {
      const rerankedLexical = await rerankSemanticCandidates({
        query: input.query,
        candidates: lexicalResults,
        enabled: app.config.ELYAN_RAG_SEMANTIC_RERANK_ENABLED,
        modelName: app.config.ELYAN_RAG_SEMANTIC_RERANK_MODEL,
        windowSize: app.config.ELYAN_RAG_SEMANTIC_RERANK_WINDOW,
        logger: app.log,
      });
      return {
        retrievalMode: "lexical_fallback" as const,
        results: prioritizeCanonicalMemoryState(
          [...lexicalResults, ...rerankedLexical.results],
          input.limit,
        ),
        degradedReason: "hybrid_retrieval_unavailable" as const,
      };
    }

    // Hybrid path: reuse the already-awaited semantic query results.
    const semanticFacts = semanticFactsRaw ?? [];
    const semanticEpisodes = semanticEpisodesRaw ?? [];

    const semanticResults = [
      ...toRows(semanticFacts).map((row) =>
        buildMemoryHit({
          id: row.id,
          memorySource: normalizeMemorySource(String(row.memoryType ?? "semantic")),
          memoryType: row.memoryType,
          title: row.title,
          content: row.content,
          confidence: row.confidence,
          staleness:
            row.conflictStatus === "contested"
              ? "contested"
              : row.staleAt
                ? "stale"
                : "fresh",
          importanceScore: row.importanceScore,
          isPinned: row.isPinned,
          conflictStatus: row.conflictStatus,
          lifecycleStatus: row.lifecycleStatus,
          scope: row.scope,
          lexicalScore: lexicalOverlapScore(input.query, `${row.title ?? ""} ${row.content ?? ""}`),
          semanticScore: Number(row.semanticScore ?? 0),
          lastVerifiedAt: row.lastVerifiedAt,
          deletedAt: row.deletedAt,
          deletedReason: row.deletedReason,
          updatedAt: row.updatedAt,
          metadata: row.metadata,
        }),
      ),
      ...toRows(semanticEpisodes).map((row) =>
        buildMemoryHit({
          id: row.id,
          memorySource: "episodic_memory",
          memoryType: row.memoryType,
          title: row.title,
          content: row.content,
          confidence: row.confidence,
          staleness: row.staleAt ? "stale" : "fresh",
          importanceScore: row.importanceScore,
          isPinned: row.isPinned,
          lexicalScore: lexicalOverlapScore(input.query, `${row.title ?? ""} ${row.content ?? ""}`),
          semanticScore: Number(row.semanticScore ?? 0),
          conflictStatus: row.staleAt ? "superseded" : "active",
          lifecycleStatus: row.lifecycleStatus,
          scope: row.scope,
          lastVerifiedAt: row.lastVerifiedAt,
          deletedAt: row.deletedAt,
          deletedReason: row.deletedReason,
          updatedAt: row.updatedAt,
          metadata: row.metadata,
        }),
      ),
    ]
      .sort((left, right) => right.score - left.score || right.confidence - left.confidence);

    const reranked = await rerankSemanticCandidates({
      query: input.query,
      candidates: dedupeMemoryHits([...semanticResults, ...lexicalResults]).sort(
        (left, right) => right.score - left.score || right.confidence - left.confidence,
      ),
      enabled: app.config.ELYAN_RAG_SEMANTIC_RERANK_ENABLED,
      modelName: app.config.ELYAN_RAG_SEMANTIC_RERANK_MODEL,
      windowSize: app.config.ELYAN_RAG_SEMANTIC_RERANK_WINDOW,
      logger: app.log,
    });

    return {
      retrievalMode: "hybrid" as const,
      results: prioritizeCanonicalMemoryState(
        [...lexicalResults, ...reranked.results],
        input.limit,
      ),
      degradedReason: null,
    };
  } catch {
    return {
      retrievalMode: "lexical_fallback" as const,
      results: [] as MemorySearchHit[],
      degradedReason: "memory_retrieval_failed" as const,
    };
  }
}

function deriveMemorySourceFromFactType(factType: string): MemorySearchHit["memorySource"] {
  if (factType === "self_model") {
    return "self_model_memory";
  }
  if (factType === "reflective") {
    return "reflective_memory";
  }
  return "semantic_memory";
}

function shapeBrainMemoryRecord(input: {
  entityType: "fact" | "episode";
  row: ExecuteRow;
}): BrainMemoryRecord {
  const row = input.row;
  const conflictStatus =
    row.conflictStatus === "contested" || row.conflictStatus === "superseded" ? row.conflictStatus : "active";
  const lifecycleStatus = deriveLifecycleFromState({
    lifecycleStatus: row.lifecycleStatus,
    conflictStatus,
    staleAt: row.staleAt,
    deletedAt: row.deletedAt,
  });
  const memoryType = String(row.memoryType ?? (input.entityType === "fact" ? "semantic" : "episode"));

  return applyMemoryPresentation({
    id: String(row.id),
    entityType: input.entityType,
    memorySource:
      input.entityType === "episode" ? "episodic_memory" : deriveMemorySourceFromFactType(memoryType),
    memoryType,
    title: String(row.title ?? memoryType),
    content: String(row.content ?? ""),
    confidence: Number(row.confidence ?? 50),
    importanceScore: Number(row.importanceScore ?? 50),
    isPinned: parseBoolean(row.isPinned),
    scope: row.scope === "shared" ? "shared" : "user",
    conflictStatus,
    lifecycleStatus,
    lastVerifiedAt: normalizeDateString(row.lastVerifiedAt),
    deletedAt: normalizeDateString(row.deletedAt),
    deletedReason: typeof row.deletedReason === "string" && row.deletedReason.trim() ? row.deletedReason : null,
    staleAt: normalizeDateString(row.staleAt),
    updatedAt: normalizeDateString(row.updatedAt) ?? new Date().toISOString(),
    createdAt: normalizeDateString(row.createdAt) ?? new Date().toISOString(),
    sourceRunId:
      typeof safeMetadata(row.metadata).sourceRunId === "string"
        ? String(safeMetadata(row.metadata).sourceRunId)
        : typeof safeMetadata(row.metadata).sourceTrainingJobId === "string"
          ? String(safeMetadata(row.metadata).sourceTrainingJobId)
          : null,
    metadata: safeMetadata(row.metadata),
  });
}

async function fetchBrainMemoryFacts(app: FastifyInstance, userId: string, limit: number) {
  return app.db.execute(sql`
    select
      id,
      fact_type as "memoryType",
      canonical_key as "title",
      value as "content",
      confidence,
      importance_score as "importanceScore",
      is_pinned as "isPinned",
      scope,
      conflict_status as "conflictStatus",
      lifecycle_status as "lifecycleStatus",
      last_verified_at as "lastVerifiedAt",
      deleted_at as "deletedAt",
      deleted_reason as "deletedReason",
      stale_at as "staleAt",
      metadata,
      created_at as "createdAt",
      updated_at as "updatedAt"
    from brain_memory_facts
    where user_id = ${userId}
    order by updated_at desc
    limit ${limit}
  `);
}

async function fetchBrainMemoryEpisodes(app: FastifyInstance, userId: string, limit: number) {
  return app.db.execute(sql`
    select
      id,
      episode_type as "memoryType",
      episode_type as "title",
      summary as "content",
      confidence,
      importance_score as "importanceScore",
      is_pinned as "isPinned",
      scope,
      case when stale_at is not null then 'superseded' else 'active' end as "conflictStatus",
      lifecycle_status as "lifecycleStatus",
      null::timestamp as "lastVerifiedAt",
      deleted_at as "deletedAt",
      deleted_reason as "deletedReason",
      stale_at as "staleAt",
      metadata,
      created_at as "createdAt",
      updated_at as "updatedAt"
    from brain_memory_episodes
    where user_id = ${userId}
    order by updated_at desc
    limit ${limit}
  `);
}

function filterVisibleMemory(
  records: BrainMemoryRecord[],
  input: {
    includeSoftDeleted: boolean;
    lifecycle: MemoryLifecycleStatus[];
    isAdmin: boolean;
  },
) {
  const requestedLifecycle = input.lifecycle;
  return records.filter((record) => {
    if (!input.includeSoftDeleted && record.lifecycleStatus === "soft_deleted") {
      return false;
    }
    if (requestedLifecycle.length > 0) {
      return requestedLifecycle.includes(record.lifecycleStatus);
    }
    if (input.isAdmin) {
      return record.lifecycleStatus !== "soft_deleted" || input.includeSoftDeleted;
    }
    if (record.isPinned) {
      return true;
    }
    return record.lifecycleStatus === "active" || record.lifecycleStatus === "contested";
  });
}

function summarizeMemoryLifecycle(records: BrainMemoryRecord[]) {
  const summary = {
    total: records.length,
    active: 0,
    contested: 0,
    superseded: 0,
    softDeleted: 0,
    stale: 0,
    facts: 0,
    episodes: 0,
  };
  for (const record of records) {
    if (record.entityType === "fact") {
      summary.facts += 1;
    } else {
      summary.episodes += 1;
    }
    if (record.lifecycleStatus === "active") {
      summary.active += 1;
    } else if (record.lifecycleStatus === "contested") {
      summary.contested += 1;
    } else if (record.lifecycleStatus === "superseded") {
      summary.superseded += 1;
    } else if (record.lifecycleStatus === "soft_deleted") {
      summary.softDeleted += 1;
    } else if (record.lifecycleStatus === "stale") {
      summary.stale += 1;
    }
  }
  return summary;
}

export async function listBrainMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    limit: number;
    includeSoftDeleted: boolean;
    surface: "all" | "facts" | "episodes";
    lifecycle: MemoryLifecycleStatus[];
    isAdmin: boolean;
  },
) {
  const [factRows, episodeRows] = await Promise.all([
    input.surface === "episodes" ? Promise.resolve({ rows: [] }) : fetchBrainMemoryFacts(app, input.userId, input.limit * 2),
    input.surface === "facts" ? Promise.resolve({ rows: [] }) : fetchBrainMemoryEpisodes(app, input.userId, input.limit * 2),
  ]);
  const all = [
    ...toRows(factRows).map((row) => shapeBrainMemoryRecord({ entityType: "fact", row })),
    ...toRows(episodeRows).map((row) => shapeBrainMemoryRecord({ entityType: "episode", row })),
  ].sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt));
  const visible = filterVisibleMemory(all, {
    includeSoftDeleted: input.includeSoftDeleted,
    lifecycle: input.lifecycle,
    isAdmin: input.isAdmin,
  }).slice(0, input.limit);

  return {
    items: visible,
    summary: summarizeMemoryLifecycle(all),
  };
}

export async function getBrainMemoryById(
  app: FastifyInstance,
  input: {
    userId: string;
    memoryId: string;
  },
) {
  const [factRows, episodeRows] = await Promise.all([
    app.db.execute(sql`
      select
        id,
        fact_type as "memoryType",
        canonical_key as "title",
        value as "content",
        confidence,
        importance_score as "importanceScore",
        is_pinned as "isPinned",
        scope,
        conflict_status as "conflictStatus",
        lifecycle_status as "lifecycleStatus",
        last_verified_at as "lastVerifiedAt",
        deleted_at as "deletedAt",
        deleted_reason as "deletedReason",
        stale_at as "staleAt",
        metadata,
        created_at as "createdAt",
        updated_at as "updatedAt"
      from brain_memory_facts
      where id = ${input.memoryId} and user_id = ${input.userId}
      limit 1
    `),
    app.db.execute(sql`
      select
        id,
        episode_type as "memoryType",
        episode_type as "title",
        summary as "content",
        confidence,
        importance_score as "importanceScore",
        is_pinned as "isPinned",
        scope,
        case when stale_at is not null then 'superseded' else 'active' end as "conflictStatus",
        lifecycle_status as "lifecycleStatus",
        null::timestamp as "lastVerifiedAt",
        deleted_at as "deletedAt",
        deleted_reason as "deletedReason",
        stale_at as "staleAt",
        metadata,
        created_at as "createdAt",
        updated_at as "updatedAt"
      from brain_memory_episodes
      where id = ${input.memoryId} and user_id = ${input.userId}
      limit 1
    `),
  ]);

  const fact = toRows(factRows)[0];
  if (fact) {
    return shapeBrainMemoryRecord({ entityType: "fact", row: fact });
  }
  const episode = toRows(episodeRows)[0];
  if (episode) {
    return shapeBrainMemoryRecord({ entityType: "episode", row: episode });
  }
  throw notFound("Brain memory not found");
}

async function createMemoryRun(
  app: FastifyInstance,
  input: {
    userId: string | null;
    scope: "user" | "shared";
    runKind: MemoryRunKind;
    sourceTrainingJobId: string;
    processedCount: number;
    status: "completed" | "skipped" | "failed";
    metadata: Record<string, unknown>;
  },
) {
  await app.db.insert(brainMemoryRuns).values({
    userId: input.userId,
    scope: input.scope,
    runKind: input.runKind,
    status: input.status,
    sourceTrainingJobId: input.sourceTrainingJobId,
    processedCount: input.processedCount,
    metadata: input.metadata,
    startedAt: new Date(),
    completedAt: new Date(),
  });
}

async function ensureNoActiveMemoryJob(
  app: FastifyInstance,
  input: {
    userId: string;
    kind: MemoryRunKind;
  },
) {
  const rows = await app.db
    .select({
      id: trainingJobs.id,
    })
    .from(trainingJobs)
    .where(
      and(
        eq(trainingJobs.ownerUserId, input.userId),
        eq(trainingJobs.kind, input.kind),
        or(...MEMORY_ACTIVE_JOB_STATUSES.map((status) => eq(trainingJobs.status, status))),
      ),
    )
    .limit(1);

  return rows[0] ?? null;
}

async function queueMemoryJob(
  app: FastifyInstance,
  input: {
    userId: string;
    kind: MemoryRunKind;
    name: string;
    trigger: string;
    metadata?: Record<string, unknown>;
  },
) {
  if (typeof (app.db as { select?: unknown; insert?: unknown }).select !== "function") {
    return { created: false, reason: "db_select_unavailable" as const };
  }
  const active = await ensureNoActiveMemoryJob(app, {
    userId: input.userId,
    kind: input.kind,
  }).catch(() => null);
  if (active) {
    return { created: false, reason: "active_memory_job_exists" as const };
  }

  await app.db.insert(trainingJobs).values({
    ownerUserId: input.userId,
    scope: "user",
    name: input.name,
    kind: input.kind,
    status: "queued",
    baseModel: app.config.ELYAN_SHARED_BRAIN_MODEL.trim() || "llama3.2",
    config: {
      trigger: input.trigger,
    },
    metadata: {
      ...input.metadata,
      trigger: input.trigger,
    },
  });

  return { created: true, reason: "queued_memory_job" as const };
}

export async function maybeQueueMemoryExtractionJob(
  app: FastifyInstance,
  input: {
    userId: string;
    persistedSignals: number;
    trigger: string;
    requestId?: string;
  },
) {
  if (input.persistedSignals <= 0) {
    app.log.debug?.({ trigger: input.trigger }, "memory extraction skipped, no signals");
    return { created: false, reason: "no_persisted_signals" as const };
  }

  app.log.info?.({ userId: input.userId, persistedSignals: input.persistedSignals, trigger: input.trigger }, "memory extraction job queued");
  return queueMemoryJob(app, {
    userId: input.userId,
    kind: "memory_extraction",
    name: "Elyan memory extraction",
    trigger: input.trigger,
    metadata: {
      persistedSignals: input.persistedSignals,
      requestId: input.requestId ?? null,
    },
  }).catch(() => ({ created: false, reason: "memory_job_queue_failed" as const }));
}

/**
 * Returns a one-line continuity hint when the user opens a fresh chat and we
 * have a meaningful recent episode (≤ N days, importance ≥ 60, active). Used
 * to seed the system prompt so Elyan can naturally reference where you left
 * off — the "kaldığımız yer" effect.
 *
 * Bounded query: one row, indexed on user+updated, no joins. Cheap enough to
 * run on every fresh session start.
 */
export async function findRecentContinuityEpisode(
  app: FastifyInstance,
  input: { userId: string; withinDays?: number; minImportance?: number },
): Promise<{
  summary: string;
  episodeType: string;
  updatedAt: Date;
  importance: number;
  sourceSessionId: string | null;
} | null> {
  const withinDays = input.withinDays ?? 7;
  const minImportance = input.minImportance ?? 60;
  const cutoff = new Date(Date.now() - withinDays * 86_400_000);

  const rows = await app.db
    .select({
      summary: brainMemoryEpisodes.summary,
      episodeType: brainMemoryEpisodes.episodeType,
      updatedAt: brainMemoryEpisodes.updatedAt,
      importance: brainMemoryEpisodes.importanceScore,
      sourceSessionId: brainMemoryEpisodes.sourceSessionId,
    })
    .from(brainMemoryEpisodes)
    .where(
      and(
        eq(brainMemoryEpisodes.userId, input.userId),
        eq(brainMemoryEpisodes.lifecycleStatus, "active"),
        gt(brainMemoryEpisodes.updatedAt, cutoff),
        gt(brainMemoryEpisodes.importanceScore, minImportance - 1),
      ),
    )
    .orderBy(desc(brainMemoryEpisodes.updatedAt))
    .limit(1);

  const row = rows[0];
  if (!row) return null;
  return {
    summary: row.summary,
    episodeType: row.episodeType,
    updatedAt: row.updatedAt,
    importance: row.importance,
    sourceSessionId: row.sourceSessionId,
  };
}

async function extractMemoryCandidates(app: FastifyInstance, userId: string) {
  const lastRunRows = await app.db
    .select({
      completedAt: brainMemoryRuns.completedAt,
    })
    .from(brainMemoryRuns)
    .where(and(eq(brainMemoryRuns.userId, userId), eq(brainMemoryRuns.runKind, "memory_extraction")))
    .orderBy(desc(brainMemoryRuns.completedAt))
    .limit(1);

  const lastCompletedAt = lastRunRows[0]?.completedAt ?? null;
  const eventRows = await app.db
    .select({
      id: learningEvents.id,
      taskId: learningEvents.taskId,
      key: learningEvents.key,
      value: learningEvents.value,
      type: learningEvents.type,
      source: learningEvents.source,
      confidence: learningEvents.confidence,
      scope: learningEvents.scope,
      metadata: learningEvents.metadata,
      createdAt: learningEvents.createdAt,
    })
    .from(learningEvents)
    .where(
      and(
        eq(learningEvents.userId, userId),
        eq(learningEvents.privacyLevel, "safe"),
        lastCompletedAt ? gt(learningEvents.createdAt, lastCompletedAt) : sql`true`,
      ),
    )
    .orderBy(desc(learningEvents.createdAt))
    .limit(MEMORY_EXTRACTION_BATCH);

  const facts = new Map<
    string,
    {
      key: string;
      value: string;
      scope: "user" | "shared";
      factType: "semantic" | "self_model" | "reflective";
      count: number;
      confidenceTotal: number;
      learningValueTotal: number;
      latestAt: Date;
      taskId: string | null;
      metadata: Record<string, unknown>;
    }
  >();
  const episodes = new Map<
    string,
    {
      sourceTaskId: string | null;
      sourceSessionId: string | null;
      episodeType: string;
      summary: string;
      scope: "user" | "shared";
      confidence: number;
      importanceScore: number;
      createdAt: Date;
      metadata: Record<string, unknown>;
    }
  >();

  for (const event of eventRows) {
    const eventMetadata = safeMetadata(event.metadata);
    const eventConfidence = Number(event.confidence ?? 50);
    const learningValueScore = computeLearningValueScore({
      key: event.key,
      value: event.value,
      type: event.type,
      source: event.source,
      confidence: eventConfidence,
      metadata: eventMetadata,
    });

    if (!shouldPromoteLearningEvent({
      key: event.key,
      type: event.type,
      confidence: eventConfidence,
      metadata: eventMetadata,
      learningValueScore,
    })) {
      continue;
    }

    const factType = inferFactType(event.key);
    const mapKey = `${factType}:${event.key}:${normalizeMemoryValue(event.value)}`;
    const existing = facts.get(mapKey);
    facts.set(mapKey, {
      key: event.key,
      value: event.value,
      scope: event.scope === "shared" ? "shared" : "user",
      factType,
      count: (existing?.count ?? 0) + 1,
      confidenceTotal: (existing?.confidenceTotal ?? 0) + eventConfidence,
      learningValueTotal: (existing?.learningValueTotal ?? 0) + learningValueScore,
      latestAt:
        existing && existing.latestAt.getTime() > event.createdAt.getTime() ? existing.latestAt : event.createdAt,
      taskId: event.taskId ?? existing?.taskId ?? null,
      metadata: {
        ...(existing?.metadata ?? {}),
        latestSource: event.source,
        latestType: event.type,
        explicit: eventMetadata.explicit === true,
        learningValueScore,
        extractorVersion:
          typeof eventMetadata.extractorVersion === "string" ? eventMetadata.extractorVersion : undefined,
        sourceTurnId:
          typeof eventMetadata.sourceTurnId === "string"
            ? eventMetadata.sourceTurnId
            : event.taskId ?? undefined,
        sourceBlobHash:
          typeof eventMetadata.sourceBlobHash === "string" ? eventMetadata.sourceBlobHash : undefined,
      },
    });

    if (
      event.taskId ||
      ["session_recovered", "task_handoff_helpfulness", "positive_feedback", "negative_feedback"].includes(event.key)
    ) {
      const sourceSessionId =
        typeof eventMetadata.chatSessionId === "string" && eventMetadata.chatSessionId.trim()
          ? eventMetadata.chatSessionId.trim()
          : null;
      const summary = summarizeEpisode(event.key, event.value);
      const episodeKey = [
        event.key,
        sourceSessionId ?? "no-session",
        event.taskId ?? "no-task",
        normalizeMemoryValue(summary),
      ].join(":");
      const candidate: {
        sourceTaskId: string | null;
        sourceSessionId: string | null;
        episodeType: string;
        summary: string;
        scope: "user" | "shared";
        confidence: number;
        importanceScore: number;
        createdAt: Date;
        metadata: Record<string, unknown>;
      } = {
        sourceTaskId: event.taskId ?? null,
        sourceSessionId,
        episodeType: event.key,
        summary,
        scope: event.scope === "shared" ? "shared" : "user",
        confidence: eventConfidence,
        importanceScore: computeImportanceScore({ key: event.key, count: 1, confidence: eventConfidence, learningValueScore }),
        createdAt: event.createdAt,
        metadata: {
          sourceEventId: event.id,
          value: event.value,
          explicit: eventMetadata.explicit === true,
          learningValueScore,
          extractorVersion:
            typeof eventMetadata.extractorVersion === "string" ? eventMetadata.extractorVersion : undefined,
          sourceTurnId:
            typeof eventMetadata.sourceTurnId === "string"
              ? eventMetadata.sourceTurnId
              : event.taskId ?? undefined,
          sourceBlobHash:
            typeof eventMetadata.sourceBlobHash === "string" ? eventMetadata.sourceBlobHash : undefined,
        },
      };
      const existingEpisode = episodes.get(episodeKey);
      if (
        !existingEpisode ||
        candidate.confidence > existingEpisode.confidence ||
        (candidate.confidence === existingEpisode.confidence && candidate.createdAt > existingEpisode.createdAt)
      ) {
        episodes.set(episodeKey, candidate);
      }
    }
  }

  return {
    facts: [...facts.values()],
    episodes: [...episodes.values()],
    sourceEventCount: eventRows.length,
  };
}

export async function upsertMemoryFact(
  app: FastifyInstance,
  input: {
    userId: string;
    key: string;
    value: string;
    scope: "user" | "shared";
    factType: "semantic" | "self_model" | "reflective";
    confidence: number;
    importanceScore: number;
    metadata: Record<string, unknown>;
    sourceRunId?: string | null;
  },
) {
  const canonicalKey = resolveCanonicalMemoryKey(input.key);
  const normalizedValue = normalizeMemoryValue(input.value);
  if (isCognitiveFoundationEnabled(app, input.userId)) {
    const kind: TurnEnvelope["memory_ops"][number]["kind"] =
      input.factType === "semantic" ? "fact" : "self_model";
    const write = await cognitiveMemoryRepository(app).writeTurn({
      userId: input.userId,
      taskId:
        typeof input.metadata.taskId === "string" ? input.metadata.taskId : undefined,
      sourceKind: "async_extraction",
      sourceId: input.sourceRunId ?? null,
      envelope: buildRepositoryMemoryEnvelope([{
        op: isSingleValueMemoryKey(canonicalKey) ? "update" : "write",
        kind,
        key: canonicalKey,
        value: input.value,
        confidence: Math.max(0.01, Math.min(0.99, input.confidence / 100)),
      }]),
    });
    return write.factIds[0] ?? null;
  }
  const forgetTombstones = await app.db
    .select({ id: brainMemoryFacts.id })
    .from(brainMemoryFacts)
    .where(
      and(
        eq(brainMemoryFacts.userId, input.userId),
        eq(brainMemoryFacts.canonicalKey, canonicalKey),
        eq(brainMemoryFacts.lifecycleStatus, "soft_deleted"),
        sql`${brainMemoryFacts.metadata}->>'forgetTombstone' = 'true'`,
      ),
    )
    .limit(1);
  if (forgetTombstones[0]) {
    return null;
  }
  const existingRows = await app.db
    .select({
      id: brainMemoryFacts.id,
      confidence: brainMemoryFacts.confidence,
      importanceScore: brainMemoryFacts.importanceScore,
      metadata: brainMemoryFacts.metadata,
    })
    .from(brainMemoryFacts)
    .where(
      and(
        eq(brainMemoryFacts.userId, input.userId),
        eq(brainMemoryFacts.canonicalKey, canonicalKey),
        sql`lower(${brainMemoryFacts.value}) = ${normalizedValue}`,
        eq(brainMemoryFacts.factType, input.factType),
      ),
    )
    .limit(1);

  if (isSingleValueMemoryKey(canonicalKey)) {
    const currentId = existingRows[0]?.id;
    await app.db
      .update(brainMemoryFacts)
      .set({
        conflictStatus: "superseded",
        lifecycleStatus: "superseded",
        staleAt: new Date(),
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(brainMemoryFacts.userId, input.userId),
          eq(brainMemoryFacts.canonicalKey, canonicalKey),
          eq(brainMemoryFacts.factType, input.factType),
          eq(brainMemoryFacts.conflictStatus, "active"),
          ...(currentId ? [ne(brainMemoryFacts.id, currentId)] : []),
        ),
      );
  }

  if (existingRows[0]) {
    await app.db
      .update(brainMemoryFacts)
      .set({
        confidence: Math.max(Number(existingRows[0].confidence ?? 50), input.confidence),
        importanceScore: Math.max(Number(existingRows[0].importanceScore ?? 50), input.importanceScore),
        staleAt: null,
        deletedAt: null,
        deletedReason: null,
        lifecycleStatus: "active",
        lastVerifiedAt: new Date(),
        metadata: {
          ...safeMetadata(existingRows[0].metadata),
          ...(input.sourceRunId ? { sourceRunId: input.sourceRunId } : {}),
          ...input.metadata,
        },
        updatedAt: new Date(),
      })
      .where(eq(brainMemoryFacts.id, existingRows[0].id));
    return existingRows[0].id;
  }

  const insertedRows = await app.db
    .insert(brainMemoryFacts)
    .values({
      userId: input.userId,
      accountId: input.userId,
      scope: input.scope,
      factType: input.factType,
      canonicalKey,
      key: input.key,
      value: input.value,
      confidence: input.confidence,
      importanceScore: input.importanceScore,
      isPinned: false,
      conflictStatus: "active",
      lastVerifiedAt: new Date(),
      metadata: {
        ...(input.sourceRunId ? { sourceRunId: input.sourceRunId } : {}),
        ...input.metadata,
      },
      lifecycleStatus: "active",
    })
    .returning({
      id: brainMemoryFacts.id,
    });

  return insertedRows[0]?.id ?? null;
}

async function insertMemoryEpisode(
  app: FastifyInstance,
  input: {
    userId: string;
    sourceTaskId: string | null;
    sourceSessionId: string | null;
    episodeType: string;
    summary: string;
    scope: "user" | "shared";
    confidence: number;
    importanceScore: number;
    createdAt: Date;
    metadata: Record<string, unknown>;
    sourceRunId?: string | null;
  },
) {
  const normalizedSummary = normalizeMemoryValue(input.summary);
  if (isCognitiveFoundationEnabled(app, input.userId)) {
    const write = await cognitiveMemoryRepository(app).writeTurn({
      userId: input.userId,
      taskId: input.sourceTaskId ?? undefined,
      sessionId: input.sourceSessionId,
      sourceKind: "async_extraction",
      sourceId: input.sourceRunId ?? input.sourceTaskId,
      envelope: buildRepositoryMemoryEnvelope([{
        op: "write",
        kind: "episode",
        key: input.episodeType,
        value: input.summary,
        confidence: Math.max(0.01, Math.min(0.99, input.confidence / 100)),
        ttl_days: 90,
      }]),
    });
    return write.episodeIds[0] ?? null;
  }
  const forgetTombstones = await app.db
    .select({ id: brainMemoryEpisodes.id })
    .from(brainMemoryEpisodes)
    .where(
      and(
        eq(brainMemoryEpisodes.userId, input.userId),
        eq(brainMemoryEpisodes.episodeType, input.episodeType),
        eq(brainMemoryEpisodes.lifecycleStatus, "soft_deleted"),
        sql`${brainMemoryEpisodes.metadata}->>'forgetTombstone' = 'true'`,
      ),
    )
    .limit(1);
  if (forgetTombstones[0]) {
    return null;
  }
  const existingRows = await app.db
    .select({
      id: brainMemoryEpisodes.id,
    })
    .from(brainMemoryEpisodes)
    .where(
        and(
          eq(brainMemoryEpisodes.userId, input.userId),
          eq(brainMemoryEpisodes.episodeType, input.episodeType),
          sql`lower(${brainMemoryEpisodes.summary}) = ${normalizedSummary}`,
          input.sourceTaskId ? eq(brainMemoryEpisodes.sourceTaskId, input.sourceTaskId) : isNull(brainMemoryEpisodes.sourceTaskId),
        ),
      )
    .limit(1);

  if (existingRows[0]) {
    return existingRows[0].id;
  }

  const insertedRows = await app.db
    .insert(brainMemoryEpisodes)
    .values({
      userId: input.userId,
      accountId: input.userId,
      scope: input.scope,
      sourceSessionId: input.sourceSessionId,
      sourceTaskId: input.sourceTaskId,
      episodeType: input.episodeType,
      summary: input.summary,
      participants: ["user", "elyan"],
      startedAt: input.createdAt,
      endedAt: input.createdAt,
      confidence: input.confidence,
      importanceScore: input.importanceScore,
      privacyLevel: "safe",
      lifecycleStatus: "active",
      metadata: {
        ...(input.sourceRunId ? { sourceRunId: input.sourceRunId } : {}),
        ...input.metadata,
      },
    })
    .returning({
      id: brainMemoryEpisodes.id,
    });

  return insertedRows[0]?.id ?? null;
}

function buildRepositoryMemoryEnvelope(
  memoryOps: TurnEnvelope["memory_ops"],
): TurnEnvelope {
  return {
    reply: { text: "", lang: "tr", tone: "neutral" },
    blocks: [],
    memory_ops: memoryOps,
    goal_ops: [],
    follow_ups: [],
    tool_requests: [],
    affect: { user_mood_guess: "unknown", energy: "mid", register: "neutral" },
  };
}

async function queueFollowUpMemoryJobs(app: FastifyInstance, userId: string) {
  await queueMemoryJob(app, {
    userId,
    kind: "memory_consolidation",
    name: "Elyan memory consolidation",
    trigger: "memory_extraction_completed",
  }).catch(() => undefined);
  await queueMemoryJob(app, {
    userId,
    kind: "memory_index",
    name: "Elyan memory index refresh",
    trigger: "memory_extraction_completed",
  }).catch(() => undefined);
  await queueMemoryJob(app, {
    userId,
    kind: "memory_reconsolidation",
    name: "Elyan memory reconsolidation",
    trigger: "memory_consolidation_completed",
  }).catch(() => undefined);
}

async function applyMemoryRetentionCompaction(app: FastifyInstance, userId: string, now: Date) {
  const factRetentionCutoff = new Date(now.getTime() - MEMORY_FACT_RETENTION_DAYS * 86_400_000);
  const staleFactCutoff = new Date(now.getTime() - MEMORY_STALE_FACT_RETENTION_DAYS * 86_400_000);
  const episodeRetentionCutoff = new Date(now.getTime() - MEMORY_EPISODE_RETENTION_DAYS * 86_400_000);
  const staleEpisodeCutoff = new Date(now.getTime() - MEMORY_STALE_EPISODE_RETENTION_DAYS * 86_400_000);

  const factRows = await app.db
    .select({
      id: brainMemoryFacts.id,
      lifecycleStatus: brainMemoryFacts.lifecycleStatus,
      conflictStatus: brainMemoryFacts.conflictStatus,
      isPinned: brainMemoryFacts.isPinned,
      updatedAt: brainMemoryFacts.updatedAt,
      staleAt: brainMemoryFacts.staleAt,
      metadata: brainMemoryFacts.metadata,
    })
    .from(brainMemoryFacts)
    .where(eq(brainMemoryFacts.userId, userId));

  const episodeRows = await app.db
    .select({
      id: brainMemoryEpisodes.id,
      lifecycleStatus: brainMemoryEpisodes.lifecycleStatus,
      isPinned: brainMemoryEpisodes.isPinned,
      updatedAt: brainMemoryEpisodes.updatedAt,
      createdAt: brainMemoryEpisodes.createdAt,
      staleAt: brainMemoryEpisodes.staleAt,
      metadata: brainMemoryEpisodes.metadata,
    })
    .from(brainMemoryEpisodes)
    .where(eq(brainMemoryEpisodes.userId, userId));

  let prunedFacts = 0;
  for (const row of factRows) {
    const rowUpdatedAt = row.updatedAt instanceof Date ? row.updatedAt : new Date(row.updatedAt ?? now);
    const isOld = rowUpdatedAt < factRetentionCutoff;
    const isStaleEnough = rowUpdatedAt < staleFactCutoff || (row.staleAt instanceof Date ? row.staleAt < staleFactCutoff : false);
    const isPrunable =
      row.isPinned !== true &&
      row.lifecycleStatus !== "active" &&
      row.lifecycleStatus !== "soft_deleted" &&
      (row.conflictStatus === "superseded" || row.conflictStatus === "contested" || isStaleEnough || isOld);

    if (!isPrunable) {
      continue;
    }

    await app.db
      .update(brainMemoryFacts)
      .set({
        lifecycleStatus: "soft_deleted",
        conflictStatus: "superseded",
        deletedAt: now,
        deletedReason: "retention_compaction",
        staleAt: now,
        embeddingModel: null,
        metadata: {
          compactedAt: now.toISOString(),
          compactionReason: "retention_compaction",
          sourceRunId: safeMetadata(row.metadata).sourceRunId ?? null,
        },
        updatedAt: now,
      })
      .where(eq(brainMemoryFacts.id, row.id));
    prunedFacts += 1;
  }

  let prunedEpisodes = 0;
  for (const row of episodeRows) {
    const rowUpdatedAt = row.updatedAt instanceof Date ? row.updatedAt : new Date(row.updatedAt ?? now);
    const rowCreatedAt = row.createdAt instanceof Date ? row.createdAt : new Date(row.createdAt ?? now);
    const isOld = rowCreatedAt < episodeRetentionCutoff || rowUpdatedAt < episodeRetentionCutoff;
    const isStaleEnough = rowUpdatedAt < staleEpisodeCutoff || (row.staleAt instanceof Date ? row.staleAt < staleEpisodeCutoff : false);
    const isPrunable =
      row.isPinned !== true &&
      row.lifecycleStatus !== "active" &&
      row.lifecycleStatus !== "soft_deleted" &&
      (isStaleEnough || isOld);

    if (!isPrunable) {
      continue;
    }

    await app.db
      .update(brainMemoryEpisodes)
      .set({
        lifecycleStatus: "soft_deleted",
        deletedAt: now,
        deletedReason: "retention_compaction",
        staleAt: now,
        embeddingModel: null,
        metadata: {
          compactedAt: now.toISOString(),
          compactionReason: "retention_compaction",
          sourceRunId: safeMetadata(row.metadata).sourceRunId ?? null,
        },
        updatedAt: now,
      })
      .where(eq(brainMemoryEpisodes.id, row.id));
    prunedEpisodes += 1;
  }

  return {
    prunedFacts,
    prunedEpisodes,
  };
}

async function synthesizeSelfModelSummary(app: FastifyInstance, userId: string) {
  const [memoryStatus, retrievalStatus, recentSignals] = await Promise.all([
    getBrainMemoryStatus(app, userId),
    getRetrievalStatus(app, userId).catch(() => ({
      mode: "lexical_fallback" as const,
      embeddingCoverage: 0,
      pendingIndexJobs: 0,
      lastIndexedAt: null,
      hybridReady: false,
    })),
    app.db
      .select({
        key: learningEvents.key,
        value: learningEvents.value,
        createdAt: learningEvents.createdAt,
      })
      .from(learningEvents)
      .where(
        and(
          eq(learningEvents.userId, userId),
          eq(learningEvents.privacyLevel, "safe"),
          or(
            eq(learningEvents.key, "negative_feedback"),
            eq(learningEvents.key, "task_handoff_helpfulness"),
            eq(learningEvents.key, "mobile_sync_quality"),
          ),
        ),
      )
      .orderBy(desc(learningEvents.createdAt))
      .limit(12),
  ]);

  const limitations: string[] = [];
  if (retrievalStatus.mode !== "hybrid") {
    limitations.push("retrieval_hybrid_unavailable");
  }
  if (memoryStatus.memoryIndexCoverage <= 0) {
    limitations.push("memory_index_cold");
  }
  if (memoryStatus.contestedMemoryCount > 0) {
    limitations.push("contested_memory_present");
  }
  if (memoryStatus.staleMemoryCount > Math.max(3, memoryStatus.episodicMemoryCount)) {
    limitations.push("stale_memory_pressure");
  }

  const recentFailurePatterns = recentSignals
    .slice(0, 6)
    .map((row) => `${row.key}:${compactText(String(row.value ?? "")).slice(0, 80)}`)
    .filter(Boolean);

  const surfacesSummary = [
    `retrieval=${retrievalStatus.mode}`,
    `memoryIndexCoverage=${memoryStatus.memoryIndexCoverage}%`,
    `contestedMemory=${memoryStatus.contestedMemoryCount}`,
    `staleMemory=${memoryStatus.staleMemoryCount}`,
  ].join("; ");
  const riskSummary = limitations.length > 0 ? limitations.join(", ") : "none";

  return {
    surfacesSummary,
    riskSummary,
    limitations,
    recentFailurePatterns,
    updatedAt: new Date().toISOString(),
  };
}

async function synthesizeContinuityProfileMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    sourceRunId: string;
  },
) {
  const [factRows, episodeRows] = await Promise.all([
    app.db
      .select({
        key: brainMemoryFacts.key,
        value: brainMemoryFacts.value,
        factType: brainMemoryFacts.factType,
      })
      .from(brainMemoryFacts)
      .where(
        and(
          eq(brainMemoryFacts.userId, input.userId),
          eq(brainMemoryFacts.scope, "user"),
          eq(brainMemoryFacts.lifecycleStatus, "active"),
        ),
      )
      .orderBy(desc(brainMemoryFacts.updatedAt))
      .limit(20),
    app.db
      .select({
        episodeType: brainMemoryEpisodes.episodeType,
        summary: brainMemoryEpisodes.summary,
      })
      .from(brainMemoryEpisodes)
      .where(
        and(
          eq(brainMemoryEpisodes.userId, input.userId),
          eq(brainMemoryEpisodes.scope, "user"),
          eq(brainMemoryEpisodes.lifecycleStatus, "active"),
        ),
      )
      .orderBy(desc(brainMemoryEpisodes.updatedAt))
      .limit(12),
  ]);

  const seed = {
    facts: factRows.map((row) => ({
      key: row.key,
      value: row.value,
      factType: row.factType,
    })),
    episodes: episodeRows.map((row) => ({
      episodeType: row.episodeType,
      summary: row.summary,
    })),
  };

  const baseline = buildContinuityEnrichmentBaseline(seed);
  const pythonRefined = await refineContinuityEnrichmentWithPython(seed).catch(() => null);
  const effective = pythonRefined ?? baseline;

  if (!effective) {
    return {
      continuityProfile: null,
    };
  }

  if (effective.recentTopics) {
    await upsertSynthesisFact(app, {
      userId: input.userId,
      key: "self_model_recent_topics",
      value: effective.recentTopics,
      factType: "self_model",
      importanceScore: 76,
      metadata: {
        sourceRunId: input.sourceRunId,
        synthesis: "continuity_profile",
        continuitySource: effective.source,
        topicTokens: effective.topicTokens,
        evidenceCount: effective.evidenceCount,
      },
    });
  }

  if (effective.continuityStyle) {
    await upsertSynthesisFact(app, {
      userId: input.userId,
      key: "reflective_continuity_style",
      value: effective.continuityStyle,
      factType: "reflective",
      importanceScore: 72,
      metadata: {
        sourceRunId: input.sourceRunId,
        synthesis: "continuity_profile",
        continuitySource: effective.source,
        evidenceCount: effective.evidenceCount,
      },
    });
  }

  if (effective.reasoningStyle) {
    await upsertSynthesisFact(app, {
      userId: input.userId,
      key: "reflective_reasoning_style",
      value: effective.reasoningStyle,
      factType: "reflective",
      importanceScore: 74,
      metadata: {
        sourceRunId: input.sourceRunId,
        synthesis: "continuity_profile",
        continuitySource: effective.source,
        evidenceCount: effective.evidenceCount,
      },
    });
  }

  return {
    continuityProfile: {
      source: effective.source,
      topicTokens: effective.topicTokens,
      evidenceCount: effective.evidenceCount,
      hasRecentTopics: Boolean(effective.recentTopics),
      hasContinuityStyle: Boolean(effective.continuityStyle),
      hasReasoningStyle: Boolean(effective.reasoningStyle),
    },
  };
}

async function upsertSynthesisFact(
  app: FastifyInstance,
  input: {
    userId: string;
    key: string;
    value: string;
    factType: "self_model" | "reflective";
    importanceScore: number;
    metadata: Record<string, unknown>;
  },
) {
  return upsertMemoryFact(app, {
    userId: input.userId,
    key: input.key,
    value: input.value,
    scope: "user",
    factType: input.factType,
    confidence: 88,
    importanceScore: input.importanceScore,
    metadata: input.metadata,
  });
}

async function synthesizeSelfModelAndReflectiveMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    sourceRunId: string;
  },
) {
  const summary = await synthesizeSelfModelSummary(app, input.userId);
  const continuityProfile = await synthesizeContinuityProfileMemory(app, input).catch(() => ({
    continuityProfile: null,
  }));

  await upsertSynthesisFact(app, {
    userId: input.userId,
    key: "self_model_surfaces",
    value: summary.surfacesSummary,
    factType: "self_model",
    importanceScore: 84,
    metadata: {
      sourceRunId: input.sourceRunId,
      synthesis: "self_model",
      limitations: summary.limitations,
      updatedAt: summary.updatedAt,
    },
  });

  await upsertSynthesisFact(app, {
    userId: input.userId,
    key: "self_model_limitations",
    value: summary.riskSummary,
    factType: "self_model",
    importanceScore: 81,
    metadata: {
      sourceRunId: input.sourceRunId,
      synthesis: "self_model",
      limitations: summary.limitations,
      updatedAt: summary.updatedAt,
    },
  });

  if (summary.recentFailurePatterns.length > 0) {
    await upsertSynthesisFact(app, {
      userId: input.userId,
      key: "reflective_failure_patterns",
      value: summary.recentFailurePatterns.join(" | "),
      factType: "reflective",
      importanceScore: 74,
      metadata: {
        sourceRunId: input.sourceRunId,
        synthesis: "reflective",
        updatedAt: summary.updatedAt,
      },
    });
  }

  return {
    selfModelSummary: {
      surfaces: summary.surfacesSummary,
      risks: summary.riskSummary,
      limitations: summary.limitations,
    },
    reflectivePromotions: summary.recentFailurePatterns,
    ...(continuityProfile.continuityProfile
      ? { continuityProfile: continuityProfile.continuityProfile }
      : {}),
  };
}

/**
 * Rolls the per-event style signals captured by recordConversationExchangeLearning
 * (preferred_language, answer_length, vocabulary_richness, tone, etc.) into a
 * single durable "communication style" snapshot the prompt can adapt to.
 *
 * Pure aggregation over learning_events; no LLM, no external service. Runs as
 * part of the in-process memory extraction job so it costs no extra resources.
 */
async function aggregateCommunicationStyleSnapshot(
  app: FastifyInstance,
  userId: string,
  sourceRunId: string,
): Promise<boolean> {
  const lookback = new Date(Date.now() - 30 * 86_400_000);
  const rows = await app.db
    .select({
      key: learningEvents.key,
      value: learningEvents.value,
      confidence: learningEvents.confidence,
    })
    .from(learningEvents)
    .where(
      and(
        eq(learningEvents.userId, userId),
        eq(learningEvents.privacyLevel, "safe"),
        gt(learningEvents.createdAt, lookback),
      ),
    )
    .limit(500);

  if (rows.length < 4) {
    // Not enough evidence yet — better no profile than a noisy one.
    return false;
  }

  const tallies = new Map<string, Map<string, { count: number; confidence: number }>>();
  for (const row of rows) {
    const key = row.key;
    if (
      key !== "preferred_language" &&
      key !== "answer_length" &&
      key !== "vocabulary_richness" &&
      key !== "preferred_tone" &&
      key !== "response_style_preference"
    ) {
      continue;
    }
    const bucket = tallies.get(key) ?? new Map();
    const slot = bucket.get(row.value) ?? { count: 0, confidence: 0 };
    slot.count += 1;
    slot.confidence += row.confidence;
    bucket.set(row.value, slot);
    tallies.set(key, bucket);
  }

  if (tallies.size === 0) return false;

  // Pick the dominant value per dimension (count first, then average confidence).
  function dominant(key: string): string | null {
    const bucket = tallies.get(key);
    if (!bucket) return null;
    let bestValue: string | null = null;
    let bestCount = 0;
    let bestConf = 0;
    for (const [value, slot] of bucket) {
      const avgConf = slot.confidence / slot.count;
      if (
        slot.count > bestCount ||
        (slot.count === bestCount && avgConf > bestConf)
      ) {
        bestValue = value;
        bestCount = slot.count;
        bestConf = avgConf;
      }
    }
    return bestValue;
  }

  const profile = [
    ["language", dominant("preferred_language")],
    ["response length", dominant("answer_length")],
    ["vocabulary", dominant("vocabulary_richness")],
    ["tone", dominant("preferred_tone")],
    ["overall style", dominant("response_style_preference")],
  ]
    .filter(([, value]) => Boolean(value))
    .map(([label, value]) => `${label}: ${value}`);

  if (profile.length === 0) return false;

  const totalEvidence = Array.from(tallies.values())
    .flatMap((bucket) => Array.from(bucket.values()))
    .reduce((sum, slot) => sum + slot.count, 0);
  const confidence = Math.min(95, 45 + Math.min(40, totalEvidence));

  await upsertMemoryFact(app, {
    userId,
    key: "self_model_communication_style",
    value: profile.join("; "),
    scope: "user",
    factType: "self_model",
    confidence,
    importanceScore: 70,
    metadata: {
      evidenceCount: totalEvidence,
      lookbackDays: 30,
      derivedFrom: Array.from(tallies.keys()),
    },
    sourceRunId,
  });
  return true;
}

async function processMemoryExtractionJob(app: FastifyInstance, job: typeof trainingJobs.$inferSelect) {
  const userId = job.ownerUserId;
  if (!userId) {
    return {
      status: "failed" as const,
      processedCount: 0,
      metadata: {
        reason: "memory_extraction_requires_user_scope",
      },
    };
  }

  const extracted = await extractMemoryCandidates(app, userId);
  let factCount = 0;
  let episodeCount = 0;
  const linkedPairs: Array<{ episodeId: string; factId: string; linkType: string }> = [];

  for (const fact of extracted.facts) {
    if (fact.factType === "semantic" && requiresRepeatedEvidenceForSemanticFact(fact.key) && fact.count < 2) {
      continue;
    }
    const factId = await upsertMemoryFact(app, {
      userId,
      key: fact.key,
      value: fact.value,
      scope: fact.scope,
      factType: fact.factType,
      confidence: Math.max(1, Math.min(99, Math.round(fact.confidenceTotal / Math.max(1, fact.count)))),
      importanceScore: computeImportanceScore({
        key: fact.key,
        count: fact.count,
        confidence: Math.round(fact.confidenceTotal / Math.max(1, fact.count)),
        learningValueScore: Math.round(fact.learningValueTotal / Math.max(1, fact.count)),
      }),
      metadata: {
        sourceCount: fact.count,
        averageLearningValueScore: Math.round(fact.learningValueTotal / Math.max(1, fact.count)),
        latestAt: fact.latestAt.toISOString(),
        taskId: fact.taskId,
        ...fact.metadata,
      },
      sourceRunId: job.id,
    });
    if (factId) {
      factCount += 1;
    }
  }

  for (const episode of extracted.episodes) {
    const episodeId = await insertMemoryEpisode(app, {
      userId,
      ...episode,
      sourceRunId: job.id,
    });
    if (episodeId) {
      episodeCount += 1;
      const linkedFact = extracted.facts.find((fact) => fact.key === episode.episodeType);
      if (linkedFact) {
        const factRows = await app.db
          .select({
            id: brainMemoryFacts.id,
          })
          .from(brainMemoryFacts)
          .where(
            and(
              eq(brainMemoryFacts.userId, userId),
              eq(brainMemoryFacts.key, linkedFact.key),
              eq(brainMemoryFacts.value, linkedFact.value),
            ),
          )
          .limit(1);
        if (factRows[0]?.id) {
          linkedPairs.push({
            episodeId,
            factId: factRows[0].id,
            linkType:
              linkedFact.key === "preferred_language"
                ? "fact_reflects_preference"
                : ["name", "preferred_name", "job_title", "company", "location", "timezone"].includes(linkedFact.key)
                  ? "episode_mentions_identity"
                  : "episode_supports_fact",
          });
        }
      }
    }
  }

  for (const pair of linkedPairs) {
    await app.db.insert(brainMemoryLinks).values({
      userId,
      sourceEpisodeId: pair.episodeId,
      targetFactId: pair.factId,
      linkType: pair.linkType,
      confidence: 70,
      metadata: {},
    });
  }

  // Roll per-event style signals into a stable user style snapshot. Best-
  // effort: failure here doesn't fail the whole extraction job.
  const styleApplied = await aggregateCommunicationStyleSnapshot(
    app,
    userId,
    job.id,
  ).catch(() => false);

  await queueFollowUpMemoryJobs(app, userId);

  return {
    status: "completed" as const,
    processedCount: factCount + episodeCount + (styleApplied ? 1 : 0),
    metadata: {
      sourceEventCount: extracted.sourceEventCount,
      extractedFactCount: factCount,
      extractedEpisodeCount: episodeCount,
      linkedMemoryCount: linkedPairs.length,
      communicationStyleApplied: styleApplied,
      promotedSemanticFacts: extracted.facts.filter((fact) => fact.factType === "semantic" && fact.count >= 2).length,
    },
  };
}

async function processMemoryConsolidationJob(app: FastifyInstance, job: typeof trainingJobs.$inferSelect) {
  const userId = job.ownerUserId;
  if (!userId) {
    return {
      status: "failed" as const,
      processedCount: 0,
      metadata: {
        reason: "memory_consolidation_requires_user_scope",
      },
    };
  }

  const factRows = await app.db
    .select({
      id: brainMemoryFacts.id,
      canonicalKey: brainMemoryFacts.canonicalKey,
      value: brainMemoryFacts.value,
      confidence: brainMemoryFacts.confidence,
      updatedAt: brainMemoryFacts.updatedAt,
      createdAt: brainMemoryFacts.createdAt,
      conflictStatus: brainMemoryFacts.conflictStatus,
    })
    .from(brainMemoryFacts)
    .where(eq(brainMemoryFacts.userId, userId))
    .orderBy(desc(brainMemoryFacts.updatedAt));

  const byKey = new Map<string, typeof factRows>();
  for (const row of factRows) {
    const bucket = byKey.get(row.canonicalKey) ?? [];
    bucket.push(row);
    byKey.set(row.canonicalKey, bucket);
  }

  let contestedCount = 0;
  let supersededCount = 0;
  const now = new Date();
  for (const rows of byKey.values()) {
    const distinctValues = [...new Set(rows.map((row) => row.value))];
    const primary = rows[0];
    if (!primary) {
      continue;
    }
    if (distinctValues.length > 1) {
      for (const row of rows.slice(1)) {
        await app.db
          .update(brainMemoryFacts)
          .set({
            conflictStatus: "contested",
            staleAt: now,
            lifecycleStatus: "contested",
            updatedAt: now,
          })
          .where(eq(brainMemoryFacts.id, row.id));
        contestedCount += 1;
      }
      await app.db
        .update(brainMemoryFacts)
        .set({
          conflictStatus: "active",
          staleAt: null,
          deletedAt: null,
          deletedReason: null,
          lifecycleStatus: "active",
          lastVerifiedAt: now,
          updatedAt: now,
        })
        .where(eq(brainMemoryFacts.id, primary.id));
    } else {
      for (const row of rows.slice(1)) {
        await app.db
          .update(brainMemoryFacts)
        .set({
          conflictStatus: "superseded",
          supersedesFactId: primary.id,
          staleAt: now,
          lifecycleStatus: "superseded",
          updatedAt: now,
        })
          .where(eq(brainMemoryFacts.id, row.id));
      supersededCount += 1;
      }
    }
  }

  const compaction = await applyMemoryRetentionCompaction(app, userId, now);

  await app.db
    .update(brainMemoryEpisodes)
    .set({
      staleAt: now,
      lifecycleStatus: "stale",
      updatedAt: now,
    })
    .where(
      and(
        eq(brainMemoryEpisodes.userId, userId),
        isNull(brainMemoryEpisodes.staleAt),
        lt(brainMemoryEpisodes.createdAt, new Date(Date.now() - 45 * 86_400_000)),
      ),
    );

  const synthesis = await synthesizeSelfModelAndReflectiveMemory(app, {
    userId,
    sourceRunId: job.id,
  });

  return {
    status: "completed" as const,
    processedCount: contestedCount + supersededCount + compaction.prunedFacts + compaction.prunedEpisodes,
    metadata: {
      contestedFacts: contestedCount,
      supersededFacts: supersededCount,
      compactedFacts: compaction.prunedFacts,
      compactedEpisodes: compaction.prunedEpisodes,
      decayedEpisodes: contestedCount + supersededCount > 0 ? 1 : 0,
      retrievalQualityCorrections: contestedCount,
      ...synthesis,
    },
  };
}

async function processMemoryReconsolidationJob(app: FastifyInstance, job: typeof trainingJobs.$inferSelect) {
  const userId = job.ownerUserId;
  if (!userId) {
    return {
      status: "failed" as const,
      processedCount: 0,
      metadata: {
        reason: "memory_reconsolidation_requires_user_scope",
      },
    };
  }

  const contestedRows = await app.db
    .select({
      id: brainMemoryFacts.id,
      canonicalKey: brainMemoryFacts.canonicalKey,
    })
    .from(brainMemoryFacts)
    .where(and(eq(brainMemoryFacts.userId, userId), eq(brainMemoryFacts.conflictStatus, "contested")))
    .limit(100);

  let processedCount = 0;
  for (const row of contestedRows) {
    const activeRows = await app.db
      .select({
        id: brainMemoryFacts.id,
      })
      .from(brainMemoryFacts)
      .where(
        and(
          eq(brainMemoryFacts.userId, userId),
          eq(brainMemoryFacts.canonicalKey, row.canonicalKey),
          eq(brainMemoryFacts.conflictStatus, "active"),
        ),
      )
      .limit(1);

    if (activeRows[0]?.id) {
      await app.db
        .update(brainMemoryFacts)
        .set({
          supersedesFactId: activeRows[0].id,
          lifecycleStatus: "superseded",
          updatedAt: new Date(),
        })
        .where(eq(brainMemoryFacts.id, row.id));
      processedCount += 1;
    }
  }

  return {
    status: "completed" as const,
    processedCount,
    metadata: {
      reconciledContestedFacts: processedCount,
    },
  };
}

async function processMemoryIndexJob(app: FastifyInstance, job: typeof trainingJobs.$inferSelect) {
  const userId = job.ownerUserId;
  if (!userId) {
    return {
      status: "failed" as const,
      processedCount: 0,
      metadata: {
        reason: "memory_index_requires_user_scope",
      },
    };
  }

  if (!(await canUseHybridRetrieval(app))) {
    return {
      status: "skipped" as const,
      processedCount: 0,
      metadata: {
        skippedReason: "hybrid_retrieval_unavailable",
      },
    };
  }

  const semanticV2Ready = await ensureMemorySemanticV2Columns(app);
  const facts = await app.db
    .select({
      id: brainMemoryFacts.id,
      text: brainMemoryFacts.value,
      embeddingModel: brainMemoryFacts.embeddingModel,
    })
    .from(brainMemoryFacts)
    .where(
      and(
        eq(brainMemoryFacts.userId, userId),
        semanticV2Ready
          ? or(isNull(brainMemoryFacts.embeddingModel), isNull(brainMemoryFacts.embeddingV2))
          : isNull(brainMemoryFacts.embeddingModel),
        sql`coalesce(${brainMemoryFacts.lifecycleStatus}, 'active') <> 'soft_deleted'`,
      ),
    )
    .limit(MEMORY_INDEX_BATCH);
  const episodes = await app.db
    .select({
      id: brainMemoryEpisodes.id,
      text: brainMemoryEpisodes.summary,
      embeddingModel: brainMemoryEpisodes.embeddingModel,
    })
    .from(brainMemoryEpisodes)
    .where(
      and(
        eq(brainMemoryEpisodes.userId, userId),
        semanticV2Ready
          ? or(isNull(brainMemoryEpisodes.embeddingModel), isNull(brainMemoryEpisodes.embeddingV2))
          : isNull(brainMemoryEpisodes.embeddingModel),
        sql`coalesce(${brainMemoryEpisodes.lifecycleStatus}, 'active') <> 'soft_deleted'`,
      ),
    )
    .limit(MEMORY_INDEX_BATCH);

  const indexedAt = new Date().toISOString();
  const factV2Vectors = semanticV2Ready
    ? await embedTextsForStorage(
        facts.map((fact) => fact.text),
        app.log,
      ).catch(() => null)
    : null;
  const episodeV2Vectors = semanticV2Ready
    ? await embedTextsForStorage(
        episodes.map((episode) => episode.text),
        app.log,
      ).catch(() => null)
    : null;
  for (const fact of facts) {
    const embedding = buildVectorSql(buildHashedKnowledgeEmbedding(fact.text));
    await app.db.execute(sql`
      update brain_memory_facts
      set
        embedding = ${embedding},
        embedding_model = ${RETRIEVAL_EMBEDDING_MODEL},
        metadata = jsonb_set(coalesce(metadata, '{}'::jsonb), '{indexedAt}', to_jsonb(${indexedAt}::text), true),
        updated_at = now()
      where id = ${fact.id}
    `);
    const v2Index = facts.findIndex((candidate) => candidate.id === fact.id);
    if (factV2Vectors?.[v2Index]) {
      const v2 = buildVectorSql(factV2Vectors[v2Index]!);
      await app.db.execute(sql`
        update brain_memory_facts
        set
          embedding_v2 = ${v2},
          embedding_v2_model = ${STORAGE_SEMANTIC_MODEL_TAG},
          metadata = jsonb_set(coalesce(metadata, '{}'::jsonb), '{semanticIndexedAt}', to_jsonb(${indexedAt}::text), true),
          updated_at = now()
        where id = ${fact.id}
      `);
    }
  }
  for (const episode of episodes) {
    const embedding = buildVectorSql(buildHashedKnowledgeEmbedding(episode.text));
    await app.db.execute(sql`
      update brain_memory_episodes
      set
        embedding = ${embedding},
        embedding_model = ${RETRIEVAL_EMBEDDING_MODEL},
        metadata = jsonb_set(coalesce(metadata, '{}'::jsonb), '{indexedAt}', to_jsonb(${indexedAt}::text), true),
        updated_at = now()
      where id = ${episode.id}
    `);
    const v2Index = episodes.findIndex((candidate) => candidate.id === episode.id);
    if (episodeV2Vectors?.[v2Index]) {
      const v2 = buildVectorSql(episodeV2Vectors[v2Index]!);
      await app.db.execute(sql`
        update brain_memory_episodes
        set
          embedding_v2 = ${v2},
          embedding_v2_model = ${STORAGE_SEMANTIC_MODEL_TAG},
          metadata = jsonb_set(coalesce(metadata, '{}'::jsonb), '{semanticIndexedAt}', to_jsonb(${indexedAt}::text), true),
          updated_at = now()
        where id = ${episode.id}
      `);
    }
  }

  return {
    status: "completed" as const,
    processedCount: facts.length + episodes.length,
    metadata: {
      indexedFactCount: facts.length,
      indexedEpisodeCount: episodes.length,
      retrievalMode: "hybrid",
      semanticV2Ready,
      semanticV2FactCount: factV2Vectors?.filter(Boolean).length ?? 0,
      semanticV2EpisodeCount: episodeV2Vectors?.filter(Boolean).length ?? 0,
    },
  };
}

function restoredLifecycleStatus(record: BrainMemoryRecord): MemoryLifecycleStatus {
  if (record.conflictStatus === "superseded") {
    return "superseded";
  }
  if (record.conflictStatus === "contested") {
    return "contested";
  }
  if (record.staleAt) {
    return "stale";
  }
  return "active";
}

export async function setBrainMemoryPinning(
  app: FastifyInstance,
  input: {
    userId: string;
    memoryId: string;
    pinned: boolean;
    reason: string | null;
    actorUserId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const record = await getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
  const now = new Date();
  if (record.entityType === "fact") {
    await app.db
      .update(brainMemoryFacts)
      .set({
        isPinned: input.pinned,
        updatedAt: now,
        metadata: {
          ...record.metadata,
          pinReason: input.reason,
          lastPinnedAt: now.toISOString(),
        },
      })
      .where(and(eq(brainMemoryFacts.id, record.id), eq(brainMemoryFacts.userId, input.userId)));
  } else {
    await app.db
      .update(brainMemoryEpisodes)
      .set({
        isPinned: input.pinned,
        updatedAt: now,
        metadata: {
          ...record.metadata,
          pinReason: input.reason,
          lastPinnedAt: now.toISOString(),
        },
      })
      .where(and(eq(brainMemoryEpisodes.id, record.id), eq(brainMemoryEpisodes.userId, input.userId)));
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.actorUserId,
    action: input.pinned ? "brain.memory.pin" : "brain.memory.unpin",
    resourceType: "brain_memory",
    resourceId: record.id,
    status: "success",
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      previousPinned: record.isPinned,
      newPinned: input.pinned,
      reason: input.reason,
      entityType: record.entityType,
    },
  });

  invalidateBrainProfileCache(app, input.userId);
  return getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
}

export async function setBrainMemoryContest(
  app: FastifyInstance,
  input: {
    userId: string;
    memoryId: string;
    supersedesMemoryId: string | null;
    reason: string | null;
    actorUserId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const record = await getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
  const now = new Date();
  if (record.entityType === "fact") {
    await app.db
      .update(brainMemoryFacts)
      .set({
        conflictStatus: "contested",
        lifecycleStatus: "contested",
        staleAt: now,
        supersedesFactId: input.supersedesMemoryId,
        updatedAt: now,
        metadata: {
          ...record.metadata,
          contestReason: input.reason,
          contestedAt: now.toISOString(),
        },
      })
      .where(and(eq(brainMemoryFacts.id, record.id), eq(brainMemoryFacts.userId, input.userId)));
  } else {
    await app.db
      .update(brainMemoryEpisodes)
      .set({
        lifecycleStatus: "contested",
        staleAt: now,
        supersedesEpisodeId: input.supersedesMemoryId,
        updatedAt: now,
        metadata: {
          ...record.metadata,
          contestReason: input.reason,
          contestedAt: now.toISOString(),
        },
      })
      .where(and(eq(brainMemoryEpisodes.id, record.id), eq(brainMemoryEpisodes.userId, input.userId)));
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.actorUserId,
    action: "brain.memory.contest",
    resourceType: "brain_memory",
    resourceId: record.id,
    status: "success",
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      previousState: record.lifecycleStatus,
      newState: "contested",
      supersedesMemoryId: input.supersedesMemoryId,
      reason: input.reason,
      entityType: record.entityType,
    },
  });

  invalidateBrainProfileCache(app, input.userId);
  return getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
}

export async function updateBrainMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    memoryId: string;
    title?: string | null;
    content: string;
    reason: string | null;
    actorUserId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const record = await getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
  const now = new Date();
  const normalizedContent = compactText(input.content).slice(0, 1000);
  const normalizedTitle = compactText(input.title ?? "").slice(0, 120);
  const nextMetadata = {
    ...record.metadata,
    userEditedAt: now.toISOString(),
    userEditReason: input.reason,
    userEdited: true,
  };

  if (record.entityType === "fact") {
    await app.db
      .update(brainMemoryFacts)
      .set({
        key: normalizedTitle || record.title,
        value: normalizedContent,
        staleAt: null,
        deletedAt: null,
        deletedReason: null,
        lifecycleStatus: "active",
        conflictStatus: "active",
        lastVerifiedAt: now,
        metadata: nextMetadata,
        updatedAt: now,
      })
      .where(and(eq(brainMemoryFacts.id, record.id), eq(brainMemoryFacts.userId, input.userId)));
  } else {
    await app.db
      .update(brainMemoryEpisodes)
      .set({
        summary: normalizedContent,
        staleAt: null,
        deletedAt: null,
        deletedReason: null,
        lifecycleStatus: "active",
        metadata: nextMetadata,
        updatedAt: now,
      })
      .where(and(eq(brainMemoryEpisodes.id, record.id), eq(brainMemoryEpisodes.userId, input.userId)));
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.actorUserId,
    action: "brain.memory.update",
    resourceType: "brain_memory",
    resourceId: record.id,
    status: "success",
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      entityType: record.entityType,
      previousTitle: record.title,
      previousContent: record.content.slice(0, 240),
      newTitle: normalizedTitle || record.title,
      newContent: normalizedContent.slice(0, 240),
      reason: input.reason,
    },
  });

  invalidateBrainProfileCache(app, input.userId);
  return getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
}

export async function softDeleteBrainMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    memoryId: string;
    reason: string;
    actorUserId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const record = await getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
  const now = new Date();
  const nextMetadata = {
    ...record.metadata,
    softDeletedAt: now.toISOString(),
    softDeleteReason: input.reason,
  };
  if (record.entityType === "fact") {
    await app.db
      .update(brainMemoryFacts)
      .set({
        lifecycleStatus: "soft_deleted",
        deletedAt: now,
        deletedReason: input.reason,
        updatedAt: now,
        metadata: nextMetadata,
      })
      .where(and(eq(brainMemoryFacts.id, record.id), eq(brainMemoryFacts.userId, input.userId)));
  } else {
    await app.db
      .update(brainMemoryEpisodes)
      .set({
        lifecycleStatus: "soft_deleted",
        deletedAt: now,
        deletedReason: input.reason,
        updatedAt: now,
        metadata: nextMetadata,
      })
      .where(and(eq(brainMemoryEpisodes.id, record.id), eq(brainMemoryEpisodes.userId, input.userId)));
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.actorUserId,
    action: "brain.memory.soft_delete",
    resourceType: "brain_memory",
    resourceId: record.id,
    status: "success",
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      previousState: record.lifecycleStatus,
      newState: "soft_deleted",
      reason: input.reason,
      entityType: record.entityType,
    },
  });

  invalidateBrainProfileCache(app, input.userId);
  return getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
}

export async function restoreBrainMemory(
  app: FastifyInstance,
  input: {
    userId: string;
    memoryId: string;
    reason: string | null;
    actorUserId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const record = await getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
  const lifecycleStatus = restoredLifecycleStatus(record);
  const now = new Date();
  if (record.entityType === "fact") {
    await app.db
      .update(brainMemoryFacts)
      .set({
        lifecycleStatus,
        deletedAt: null,
        deletedReason: null,
        updatedAt: now,
        metadata: {
          ...record.metadata,
          restoredAt: now.toISOString(),
          restoreReason: input.reason,
        },
      })
      .where(and(eq(brainMemoryFacts.id, record.id), eq(brainMemoryFacts.userId, input.userId)));
  } else {
    await app.db
      .update(brainMemoryEpisodes)
      .set({
        lifecycleStatus,
        deletedAt: null,
        deletedReason: null,
        updatedAt: now,
        metadata: {
          ...record.metadata,
          restoredAt: now.toISOString(),
          restoreReason: input.reason,
        },
      })
      .where(and(eq(brainMemoryEpisodes.id, record.id), eq(brainMemoryEpisodes.userId, input.userId)));
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.actorUserId,
    action: "brain.memory.restore",
    resourceType: "brain_memory",
    resourceId: record.id,
    status: "success",
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      previousState: record.lifecycleStatus,
      newState: lifecycleStatus,
      reason: input.reason,
      entityType: record.entityType,
    },
  });

  invalidateBrainProfileCache(app, input.userId);
  return getBrainMemoryById(app, {
    userId: input.userId,
    memoryId: input.memoryId,
  });
}

export async function processMemoryTrainingJob(app: FastifyInstance, job: typeof trainingJobs.$inferSelect) {
  if (
    job.kind !== "memory_extraction" &&
    job.kind !== "memory_consolidation" &&
    job.kind !== "memory_reconsolidation" &&
    job.kind !== "memory_index"
  ) {
    return null;
  }

  const processor =
    job.kind === "memory_extraction"
      ? processMemoryExtractionJob
      : job.kind === "memory_consolidation"
        ? processMemoryConsolidationJob
        : job.kind === "memory_reconsolidation"
          ? processMemoryReconsolidationJob
          : processMemoryIndexJob;

  const outcome = await processor(app, job);
  const now = new Date();
  await app.db
    .update(trainingJobs)
    .set({
      status: outcome.status === "failed" ? "failed" : "completed",
      completedAt: now,
      updatedAt: now,
      error: outcome.status === "failed" ? String(outcome.metadata.reason ?? job.kind) : null,
      metrics: {
        processedCount: outcome.processedCount,
      },
      metadata: {
        ...safeMetadata(job.metadata),
        workerStatus: outcome.status,
        phase: job.kind,
        ...outcome.metadata,
      },
    })
    .where(and(eq(trainingJobs.id, job.id), eq(trainingJobs.status, "running")));

  await createMemoryRun(app, {
    userId: job.ownerUserId,
    scope: job.scope,
    runKind: job.kind,
    sourceTrainingJobId: job.id,
    processedCount: outcome.processedCount,
    status: outcome.status,
    metadata: outcome.metadata,
  });

  return outcome;
}
