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

type MemoryOp = TurnEnvelope["memory_ops"][number];
type MemoryDb = FastifyInstance["db"];

export type TurnMemoryOpsWriteResult = {
  processed: number;
  factsWritten: number;
  episodesWritten: number;
  contested: number;
  forgotten: number;
  skipped: number;
};

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

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

async function writeFactOp(
  db: MemoryDb,
  input: {
    userId: string;
    sessionId: string | null;
    op: MemoryOp;
    now: Date;
  },
): Promise<"written" | "contested" | "forgotten" | "skipped"> {
  const key = canonicalizeMemoryKey(input.op.key);
  const value = compactText(input.op.value).slice(0, 2_000);
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

  if (input.op.op === "forget") {
    await db
      .update(brainMemoryFacts)
      .set({
        conflictStatus: "superseded",
        lifecycleStatus: "soft_deleted",
        deletedAt: input.now,
        deletedReason: "explicit_user_forget",
        staleAt: input.now,
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

  if (singleValue || input.op.op === "update") {
    const currentId = existingRows[0]?.id;
    await db
      .update(brainMemoryFacts)
      .set({
        conflictStatus: "superseded",
        lifecycleStatus: "superseded",
        staleAt: input.now,
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
  },
): Promise<"written" | "forgotten" | "skipped"> {
  const episodeType = canonicalizeMemoryKey(input.op.key);
  const summary = compactText(input.op.value).slice(0, 2_000);
  if (!episodeType || (input.op.op !== "forget" && !summary)) return "skipped";

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
  return executeWithDb(app, async (db) => {
    for (const op of ops) {
      summary.processed += 1;
      if (op.kind === "episode") {
        const result = await writeEpisodeOp(db, {
          userId: input.userId,
          sessionId: input.sessionId ?? null,
          op,
          now,
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
        now,
      });
      if (result === "written") summary.factsWritten += 1;
      else if (result === "contested") summary.contested += 1;
      else if (result === "forgotten") summary.forgotten += 1;
      else summary.skipped += 1;
    }
    return summary;
  });
}
