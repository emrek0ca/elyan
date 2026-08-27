import { createHash } from "node:crypto";
import { and, eq, ne, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  brainMemoryEpisodes,
  brainMemoryFacts,
} from "../../db/schema.js";
import { resolveMemoryImportanceBaseline } from "./memory.js";
import {
  isSingleValueMemoryKey,
  resolveCanonicalMemoryKey,
} from "./memory-key-policy.js";
import type { TurnEnvelope } from "./turn-envelope.js";
import { invalidateCanonicalMemoryCache } from "./memory-context-cache.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

type MemoryOp = TurnEnvelope["memory_ops"][number];
export type MemoryDb = FastifyInstance["db"];

export type TurnMemoryOpsWriteResult = {
  processed: number;
  factsWritten: number;
  episodesWritten: number;
  contested: number;
  forgotten: number;
  skipped: number;
};

export function canonicalizeMemoryKey(key: string): string {
  const normalized = compactText(key)
    .toLowerCase()
    .replace(/[^a-z0-9çğıöşü_.:-]+/gi, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  return resolveCanonicalMemoryKey((normalized || "turn_memory").slice(0, 160));
}

function normalizeMemoryValue(value: string): string {
  return compactText(value).toLowerCase();
}

// Injection-safe patterns: memory values that look like system/developer
// message injections or persona overrides. These get sanitized before storage
// so poisoned memories can't act as prompt injections when recalled.
const MEMORY_INJECTION_PATTERNS = [
  /\b(system|developer|hidden|admin|root)\s*:\s*/gi,
  /\[\s*(system|developer|admin|root|instruction)\s*\]/gi,
  /\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|rules?|prompts?|constraints?)\b/gi,
  /\b(you are now|act as|pretend|new persona|new identity)\b/gi,
  /\b(reveal|output|print|echo)\b.{0,30}\b(system|prompt|instruction|secret|credential)\b/gi,
  /\b(from now on|henceforth|bundan sonra|bundan böyle)\b.{0,40}\b(you are|you will|sen|siz)\b/gi,
];

function sanitizeMemoryValue(value: string): string {
  let safe = value
    // Strip zero-width / invisible unicode
    .replace(/[\u200B-\u200F\u2028-\u202F\u2060-\u2069\uFEFF\u00AD\u034F\u061C\u115F\u1160\u17B4\u17B5\u180E]/g, "");

  for (const pattern of MEMORY_INJECTION_PATTERNS) {
    safe = safe.replace(pattern, "[redacted]");
  }

  // Cap individual memory value size
  if (safe.length > 2_000) {
    safe = safe.slice(0, 2_000);
  }

  return safe;
}

function contentHash(value: string): string {
  return createHash("sha256").update(compactText(value)).digest("hex");
}

function confidenceToPercent(confidence: number): number {
  return Math.max(1, Math.min(99, Math.round(confidence * 100)));
}

function staleAtFromTtl(ttlDays: number | undefined, now: Date): Date | null {
  if (!ttlDays) return null;
  return new Date(now.getTime() + ttlDays * 86_400_000);
}

function factTypeForOp(kind: MemoryOp["kind"]): "semantic" | "self_model" {
  return kind === "self_model" ? "self_model" : "semantic";
}

function importanceForOp(op: MemoryOp): number {
  return resolveMemoryImportanceBaseline({
    factType: op.kind === "self_model" ? "self_model" : op.kind,
    key: op.key,
    canonicalKey: canonicalizeMemoryKey(op.key),
  });
}

function metadataForOp(input: {
  op: MemoryOp;
  sessionId: string | null;
  now: Date;
}): Record<string, unknown> {
  return {
    source: "turn_envelope",
    op: input.op.op,
    kind: input.op.kind,
    sourceSessionId: input.sessionId,
    ttlDays: input.op.ttl_days ?? null,
    writtenAt: input.now.toISOString(),
  };
}

async function executeWithDb<T>(
  app: FastifyInstance,
  run: (db: MemoryDb) => Promise<T>,
): Promise<T> {
  const transaction = (app.db as {
    transaction?: (cb: (db: MemoryDb) => Promise<T>) => Promise<T>;
  }).transaction;
  if (typeof transaction === "function") {
    return transaction.call(app.db, run);
  }
  return run(app.db);
}

async function lockMemoryKey(
  db: MemoryDb,
  input: { userId: string; canonicalKey: string },
): Promise<void> {
  const executable = db as MemoryDb & {
    execute?: (query: ReturnType<typeof sql>) => Promise<unknown>;
  };
  if (typeof executable.execute !== "function") {
    return;
  }
  await executable.execute(
    sql`select pg_advisory_xact_lock(hashtextextended(${`${input.userId}:${input.canonicalKey}`}, 0))`,
  );
}

async function writeFactOp(
  db: MemoryDb,
  input: {
    userId: string;
    sessionId: string | null;
    op: MemoryOp;
    now: Date;
    revision?: number;
    sourceKind?: string;
    sourceId?: string | null;
  },
): Promise<"written" | "contested" | "forgotten" | "skipped"> {
  const key = canonicalizeMemoryKey(input.op.key);
  const value = sanitizeMemoryValue(compactText(input.op.value));
  if (!key || (input.op.op !== "forget" && !value)) return "skipped";

  const factType = factTypeForOp(input.op.kind);
  const confidence = confidenceToPercent(input.op.confidence);
  const importanceScore = importanceForOp(input.op);
  const staleAt = staleAtFromTtl(input.op.ttl_days, input.now);
  const metadata = metadataForOp({
    op: input.op,
    sessionId: input.sessionId,
    now: input.now,
  });
  const singleValue = isSingleValueMemoryKey(key);
  const revision = input.revision ?? 1;
  const sourceKind = input.sourceKind ?? "turn_envelope";
  const sourceId = input.sourceId ?? input.sessionId;

  // Serialize updates for the same user's canonical fact. This keeps a pair of
  // concurrent turns from producing two active values or losing the correction.
  await lockMemoryKey(db, { userId: input.userId, canonicalKey: key });

  if (input.op.op === "forget") {
    await db
      .update(brainMemoryFacts)
      .set({
        conflictStatus: "superseded",
        lifecycleStatus: "soft_deleted",
        deletedAt: input.now,
        deletedReason: "explicit_user_forget",
        staleAt: input.now,
        validTo: input.now,
        revision,
        sourceKind,
        sourceId,
        updatedAt: input.now,
      })
      .where(
        and(
          eq(brainMemoryFacts.userId, input.userId),
          eq(brainMemoryFacts.canonicalKey, key),
          ne(brainMemoryFacts.lifecycleStatus, "soft_deleted"),
        ),
      );
    await db.insert(brainMemoryFacts).values({
      userId: input.userId,
      accountId: input.userId,
      scope: "user",
      factType,
      canonicalKey: key,
      key,
      value: "__forgotten__",
      confidence: 99,
      importanceScore: 100,
      isPinned: false,
      conflictStatus: "superseded",
      lifecycleStatus: "soft_deleted",
      deletedAt: input.now,
      deletedReason: "explicit_user_forget",
      staleAt: input.now,
      validFrom: input.now,
      validTo: input.now,
      observedAt: input.now,
      revision,
      sourceKind,
      sourceId,
      contentHash: contentHash("__forgotten__"),
      metadata: { ...metadata, forgetTombstone: true },
      updatedAt: input.now,
    });
    return "forgotten";
  }

  // A later explicit turn may intentionally replace a previously forgotten key.
  await db
    .update(brainMemoryFacts)
    .set({
      lifecycleStatus: "superseded",
      conflictStatus: "superseded",
      updatedAt: input.now,
    })
    .where(
      and(
        eq(brainMemoryFacts.userId, input.userId),
        eq(brainMemoryFacts.canonicalKey, key),
        eq(brainMemoryFacts.lifecycleStatus, "soft_deleted"),
        sql`${brainMemoryFacts.metadata}->>'forgetTombstone' = 'true'`,
      ),
    );

  if (input.op.op === "contest") {
    await db
      .update(brainMemoryFacts)
      .set({
        conflictStatus: "contested",
        lifecycleStatus: "contested",
        staleAt: input.now,
        validTo: input.now,
        revision,
        sourceKind,
        sourceId,
        metadata,
        updatedAt: input.now,
      })
      .where(
        and(
          eq(brainMemoryFacts.userId, input.userId),
          eq(brainMemoryFacts.canonicalKey, key),
          eq(brainMemoryFacts.factType, factType),
          ne(brainMemoryFacts.lifecycleStatus, "soft_deleted"),
        ),
      );

    await db.insert(brainMemoryFacts).values({
      userId: input.userId,
      accountId: input.userId,
      scope: "user",
      factType,
      canonicalKey: key,
      key,
      value,
      confidence,
      importanceScore,
      isPinned: false,
      conflictStatus: "contested",
      lifecycleStatus: "contested",
      staleAt: input.now,
      validFrom: input.now,
      validTo: input.now,
      observedAt: input.now,
      revision,
      sourceKind,
      sourceId,
      contentHash: contentHash(value),
      lastVerifiedAt: input.now,
      metadata,
      updatedAt: input.now,
    });
    return "contested";
  }

  const existingRows = await db
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
        eq(brainMemoryFacts.canonicalKey, key),
        eq(brainMemoryFacts.factType, factType),
        sql`lower(${brainMemoryFacts.value}) = ${normalizeMemoryValue(value)}`,
      ),
    )
    .limit(1);

  const activeRows = singleValue || input.op.op === "update"
    ? await db
        .select({ id: brainMemoryFacts.id })
        .from(brainMemoryFacts)
        .where(
          and(
            eq(brainMemoryFacts.userId, input.userId),
            eq(brainMemoryFacts.canonicalKey, key),
            eq(brainMemoryFacts.factType, factType),
            eq(brainMemoryFacts.conflictStatus, "active"),
            eq(brainMemoryFacts.lifecycleStatus, "active"),
          ),
        )
        .limit(1)
    : [];

  if (singleValue || input.op.op === "update") {
    const currentId = existingRows[0]?.id;
    await db
      .update(brainMemoryFacts)
      .set({
        conflictStatus: "superseded",
        lifecycleStatus: "superseded",
        staleAt: input.now,
        validTo: input.now,
        revision,
        updatedAt: input.now,
      })
      .where(
        and(
          eq(brainMemoryFacts.userId, input.userId),
          eq(brainMemoryFacts.canonicalKey, key),
          eq(brainMemoryFacts.factType, factType),
          eq(brainMemoryFacts.conflictStatus, "active"),
          ...(currentId ? [ne(brainMemoryFacts.id, currentId)] : []),
        ),
      );
  }

  if (existingRows[0]) {
    await db
      .update(brainMemoryFacts)
      .set({
        confidence: Math.max(Number(existingRows[0].confidence ?? 50), confidence),
        importanceScore: Math.max(
          Number(existingRows[0].importanceScore ?? 50),
          importanceScore,
        ),
        staleAt,
        validTo: null,
        observedAt: input.now,
        revision,
        sourceKind,
        sourceId,
        contentHash: contentHash(value),
        deletedAt: null,
        deletedReason: null,
        conflictStatus: "active",
        lifecycleStatus: "active",
        lastVerifiedAt: input.now,
        metadata: {
          ...(existingRows[0].metadata && typeof existingRows[0].metadata === "object"
            ? existingRows[0].metadata
            : {}),
          ...metadata,
        },
        updatedAt: input.now,
      })
      .where(eq(brainMemoryFacts.id, existingRows[0].id));
    return "written";
  }

  await db.insert(brainMemoryFacts).values({
    userId: input.userId,
    accountId: input.userId,
    scope: "user",
    factType,
    canonicalKey: key,
    key,
    value,
    confidence,
    importanceScore,
    isPinned: false,
    conflictStatus: "active",
    lifecycleStatus: "active",
    staleAt,
    supersedesFactId: activeRows[0]?.id ?? null,
    validFrom: input.now,
    validTo: null,
    observedAt: input.now,
    revision,
    sourceKind,
    sourceId,
    contentHash: contentHash(value),
    lastVerifiedAt: input.now,
    metadata,
    updatedAt: input.now,
  });
  return "written";
}

async function writeEpisodeOp(
  db: MemoryDb,
  input: {
    userId: string;
    sessionId: string | null;
    op: MemoryOp;
    now: Date;
    revision?: number;
    sourceKind?: string;
    sourceId?: string | null;
  },
): Promise<"written" | "forgotten" | "skipped"> {
  const episodeType = canonicalizeMemoryKey(input.op.key);
  const summary = sanitizeMemoryValue(compactText(input.op.value));
  if (!episodeType || (input.op.op !== "forget" && !summary)) return "skipped";
  const revision = input.revision ?? 1;
  const sourceKind = input.sourceKind ?? "turn_envelope";
  const sourceId = input.sourceId ?? input.sessionId;

  if (input.op.op === "forget") {
    await db
      .update(brainMemoryEpisodes)
      .set({
        lifecycleStatus: "soft_deleted",
        deletedAt: input.now,
        deletedReason: "explicit_user_forget",
        staleAt: input.now,
        updatedAt: input.now,
      })
      .where(
        and(
          eq(brainMemoryEpisodes.userId, input.userId),
          eq(brainMemoryEpisodes.episodeType, episodeType),
          ne(brainMemoryEpisodes.lifecycleStatus, "soft_deleted"),
        ),
      );
    await db.insert(brainMemoryEpisodes).values({
      userId: input.userId,
      accountId: input.userId,
      scope: "user",
      sourceSessionId: input.sessionId,
      episodeType,
      summary: "__forgotten__",
      confidence: 99,
      importanceScore: 100,
      isPinned: false,
      privacyLevel: "safe",
      lifecycleStatus: "soft_deleted",
      deletedAt: input.now,
      deletedReason: "explicit_user_forget",
      staleAt: input.now,
      observedAt: input.now,
      expiresAt: input.now,
      revision,
      sourceKind,
      sourceId,
      contentHash: contentHash("__forgotten__"),
      metadata: {
        ...metadataForOp({ op: input.op, sessionId: input.sessionId, now: input.now }),
        forgetTombstone: true,
      },
      updatedAt: input.now,
    });
    return "forgotten";
  }

  await db.insert(brainMemoryEpisodes).values({
    userId: input.userId,
    accountId: input.userId,
    scope: "user",
    sourceSessionId: input.sessionId,
    episodeType,
    summary,
    confidence: confidenceToPercent(input.op.confidence),
    importanceScore: importanceForOp(input.op),
    isPinned: false,
    privacyLevel: "safe",
    lifecycleStatus: input.op.op === "contest" ? "contested" : "active",
    staleAt: staleAtFromTtl(input.op.ttl_days, input.now),
    observedAt: input.now,
    expiresAt: new Date(
      input.now.getTime() + Math.min(input.op.ttl_days ?? 90, 90) * 86_400_000,
    ),
    revision,
    sourceKind,
    sourceId,
    contentHash: contentHash(summary),
    metadata: metadataForOp({
      op: input.op,
      sessionId: input.sessionId,
      now: input.now,
    }),
    updatedAt: input.now,
  });
  return "written";
}

export async function recordTurnMemoryOps(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId?: string | null;
    envelope: TurnEnvelope | null | undefined;
    now?: Date;
  },
): Promise<TurnMemoryOpsWriteResult> {
  const ops = input.envelope?.memory_ops ?? [];
  const summary: TurnMemoryOpsWriteResult = {
    processed: 0,
    factsWritten: 0,
    episodesWritten: 0,
    contested: 0,
    forgotten: 0,
    skipped: 0,
  };
  if (ops.length === 0) return summary;

  const now = input.now ?? new Date();
  const result = await executeWithDb(app, async (db) => {
    return recordTurnMemoryOpsOnDb(db, {
      ...input,
      now,
    });
  });
  if (
    result.factsWritten > 0 ||
    result.contested > 0 ||
    result.forgotten > 0
  ) {
    await invalidateCanonicalMemoryCache(app, input.userId);
  }
  return result;
}

export async function recordTurnMemoryOpsOnDb(
  db: MemoryDb,
  input: {
    userId: string;
    sessionId?: string | null;
    envelope: TurnEnvelope | null | undefined;
    now: Date;
    revision?: number;
    sourceKind?: string;
    sourceId?: string | null;
  },
): Promise<TurnMemoryOpsWriteResult> {
  const ops = input.envelope?.memory_ops ?? [];
  const summary: TurnMemoryOpsWriteResult = {
    processed: 0,
    factsWritten: 0,
    episodesWritten: 0,
    contested: 0,
    forgotten: 0,
    skipped: 0,
  };
  if (ops.length === 0) return summary;

  for (const op of ops) {
      summary.processed += 1;
      if (op.kind === "episode") {
        const result = await writeEpisodeOp(db, {
          userId: input.userId,
          sessionId: input.sessionId ?? null,
          op,
          now: input.now,
          revision: input.revision,
          sourceKind: input.sourceKind,
          sourceId: input.sourceId,
        });
        if (result === "written") summary.episodesWritten += 1;
        else if (result === "forgotten") summary.forgotten += 1;
        else summary.skipped += 1;
        continue;
      }

      const result = await writeFactOp(db, {
        userId: input.userId,
        sessionId: input.sessionId ?? null,
        op,
        now: input.now,
        revision: input.revision,
        sourceKind: input.sourceKind,
        sourceId: input.sourceId,
      });
      if (result === "written") summary.factsWritten += 1;
      else if (result === "contested") summary.contested += 1;
      else if (result === "forgotten") summary.forgotten += 1;
      else summary.skipped += 1;
  }
  return summary;
}
