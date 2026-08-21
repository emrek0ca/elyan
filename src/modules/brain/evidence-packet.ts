import { createHash } from "node:crypto";
import type { MemorySearchHit } from "./memory.js";

export const retrievalNamespaceValues = [
  "user_preferences",
  "semantic_memory",
  "episodic_memory",
  "active_goal_task",
  "previous_task_results",
  "capability_skill_catalog",
  "desktop_runtime_state",
  "knowledge_base",
] as const;

export type RetrievalNamespace = (typeof retrievalNamespaceValues)[number];

export type EvidencePacketEntry = {
  sourceId: string;
  sourceType: string;
  title: string;
  excerpt: string;
  confidence: number;
  score: number;
  createdAt: string | null;
  lastVerifiedAt: string | null;
  lifecycle: "active";
  sourceSessionId: string | null;
  sourceMessageId: string | null;
  provenance: Record<string, unknown>;
};

export type EvidencePacket = {
  contract: "elyan.evidence_packet.v1";
  userId: string;
  sessionId: string | null;
  taskId: string | null;
  goalId: string | null;
  namespace: RetrievalNamespace;
  queryHash: string;
  memoryRevision: number | null;
  entries: EvidencePacketEntry[];
  usedChars: number;
};

type EvidenceCandidate = {
  id: string;
  sourceId?: string | null;
  sourceType?: string | null;
  title?: string | null;
  content?: string | null;
  excerpt?: string | null;
  confidence?: number | null;
  score?: number | null;
  createdAt?: string | Date | null;
  lastVerifiedAt?: string | Date | null;
  lifecycle?: string | null;
  scope?: "user" | "shared" | null;
  ownerUserId?: string | null;
  sourceSessionId?: string | null;
  sourceMessageId?: string | null;
  metadata?: Record<string, unknown> | null;
};

const MAX_PACKET_CHARS = 6_000;
const MAX_PACKET_ENTRIES: Record<RetrievalNamespace, number> = {
  user_preferences: 8,
  semantic_memory: 8,
  episodic_memory: 4,
  active_goal_task: 8,
  previous_task_results: 8,
  capability_skill_catalog: 12,
  desktop_runtime_state: 8,
  knowledge_base: 12,
};

function compact(value: unknown, max: number): string {
  const text = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

function iso(value: string | Date | null | undefined): string | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value.toISOString();
  const text = compact(value, 80);
  if (!text) return null;
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function queryHash(query: string): string {
  return createHash("sha256")
    .update(query.normalize("NFKC").replace(/\s+/g, " ").trim().toLocaleLowerCase("tr-TR"))
    .digest("hex")
    .slice(0, 32);
}

function admissible(candidate: EvidenceCandidate, userId: string): boolean {
  if (candidate.ownerUserId && candidate.ownerUserId !== userId) return false;
  if (candidate.scope === "user" && candidate.ownerUserId !== userId) return false;
  return !["contested", "superseded", "soft_deleted", "expired", "stale"].includes(
    compact(candidate.lifecycle, 40).toLowerCase(),
  );
}

export function buildEvidencePacket(input: {
  userId: string;
  sessionId?: string | null;
  taskId?: string | null;
  goalId?: string | null;
  namespace: RetrievalNamespace;
  query: string;
  memoryRevision?: number | null;
  candidates: EvidenceCandidate[];
  maxChars?: number;
  maxEntries?: number;
}): EvidencePacket {
  const maxChars = Math.max(500, Math.min(input.maxChars ?? MAX_PACKET_CHARS, MAX_PACKET_CHARS));
  const maxEntries = Math.max(
    1,
    Math.min(input.maxEntries ?? MAX_PACKET_ENTRIES[input.namespace], MAX_PACKET_ENTRIES[input.namespace]),
  );
  const bestById = new Map<string, EvidenceCandidate>();
  for (const candidate of input.candidates) {
    if (!candidate.id || !admissible(candidate, input.userId)) continue;
    const current = bestById.get(candidate.id);
    if (!current || Number(candidate.score ?? 0) > Number(current.score ?? 0)) {
      bestById.set(candidate.id, candidate);
    }
  }
  const sorted = [...bestById.values()].sort(
    (left, right) =>
      Number(right.score ?? 0) - Number(left.score ?? 0) ||
      Number(right.confidence ?? 0) - Number(left.confidence ?? 0),
  );
  const entries: EvidencePacketEntry[] = [];
  let usedChars = 0;
  for (const candidate of sorted) {
    if (entries.length >= maxEntries) break;
    const excerpt = compact(candidate.excerpt ?? candidate.content, 1_000);
    if (!excerpt) continue;
    const title = compact(candidate.title, 180);
    const cost = title.length + excerpt.length;
    if (usedChars + cost > maxChars) break;
    usedChars += cost;
    entries.push({
      sourceId: compact(candidate.sourceId ?? candidate.id, 180),
      sourceType: compact(candidate.sourceType ?? "unknown", 80) || "unknown",
      title,
      excerpt,
      confidence: Math.max(0, Math.min(1, Number(candidate.confidence ?? 0))),
      score: Math.max(0, Math.min(1, Number(candidate.score ?? 0))),
      createdAt: iso(candidate.createdAt),
      lastVerifiedAt: iso(candidate.lastVerifiedAt),
      lifecycle: "active",
      sourceSessionId: compact(candidate.sourceSessionId, 160) || null,
      sourceMessageId: compact(candidate.sourceMessageId, 160) || null,
      provenance: { ...(candidate.metadata ?? {}) },
    });
  }
  return {
    contract: "elyan.evidence_packet.v1",
    userId: input.userId,
    sessionId: compact(input.sessionId, 160) || null,
    taskId: compact(input.taskId, 160) || null,
    goalId: compact(input.goalId, 160) || null,
    namespace: input.namespace,
    queryHash: queryHash(input.query),
    memoryRevision: input.memoryRevision == null ? null : Math.max(0, Math.floor(input.memoryRevision)),
    entries,
    usedChars,
  };
}

export function memoryHitsToEvidencePackets(input: {
  userId: string;
  sessionId?: string | null;
  taskId?: string | null;
  goalId?: string | null;
  query: string;
  memoryRevision?: number | null;
  hits: MemorySearchHit[];
}): EvidencePacket[] {
  const groups = new Map<RetrievalNamespace, MemorySearchHit[]>();
  for (const hit of input.hits) {
    if (
      hit.conflictStatus !== "active" ||
      hit.lifecycleStatus !== "active" ||
      hit.staleness !== "fresh" ||
      hit.deletedAt != null ||
      hit.metadata.retrievalAllowed === false ||
      hit.metadata.approved === false
    ) {
      continue;
    }
    const namespace: RetrievalNamespace =
      hit.memorySource === "episodic_memory" ? "episodic_memory" : "semantic_memory";
    const list = groups.get(namespace) ?? [];
    list.push(hit);
    groups.set(namespace, list);
  }
  return [...groups.entries()].map(([namespace, hits]) =>
    buildEvidencePacket({
      userId: input.userId,
      sessionId: input.sessionId,
      taskId: input.taskId,
      goalId: input.goalId,
      query: input.query,
      memoryRevision: input.memoryRevision,
      namespace,
      candidates: hits.map((hit) => ({
        id: hit.id,
        sourceId: hit.id,
        sourceType: hit.memoryType,
        title: hit.title,
        content: hit.content,
        confidence: hit.confidence > 1 ? hit.confidence / 100 : hit.confidence,
        score: hit.score,
        lastVerifiedAt: hit.lastVerifiedAt,
        lifecycle: hit.lifecycleStatus,
        scope: hit.scope,
        ownerUserId: input.userId,
        metadata: hit.metadata,
      })),
    }),
  );
}

export function retrievalResultsToEvidencePacket(input: {
  userId: string;
  query: string;
  memoryRevision?: number | null;
  results: Array<{
    documentId: string;
    chunkId: string;
    title: string;
    sourceType: string;
    sourceUri: string | null;
    scope: "user" | "shared";
    content: string;
    score: number;
    updatedAt: Date;
    metadata: Record<string, unknown>;
  }>;
}): EvidencePacket {
  return buildEvidencePacket({
    userId: input.userId,
    query: input.query,
    memoryRevision: input.memoryRevision,
    namespace: "knowledge_base",
    candidates: input.results.map((result) => ({
      id: `${result.documentId}:${result.chunkId}`,
      sourceId: result.chunkId,
      sourceType: result.sourceType,
      title: result.title,
      content: result.content,
      confidence: result.score,
      score: result.score,
      createdAt: result.updatedAt,
      lastVerifiedAt: result.updatedAt,
      lifecycle: "active",
      scope: result.scope,
      ownerUserId: result.scope === "user" ? input.userId : null,
      metadata: {
        ...result.metadata,
        documentId: result.documentId,
        sourceUri: result.sourceUri,
      },
    })),
  });
}
