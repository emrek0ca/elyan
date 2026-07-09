import { and, desc, eq, gt, isNull, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import {
  brainMemoryEpisodes,
  brainMemoryFacts,
  cognitiveMemoryRevisions,
} from "../../db/schema.js";
import { withTenantTransaction, type TenantDb } from "../../db/tenant-context.js";
import { readDialogueStateOnDb } from "./dialogue-state.js";

const workingSchema = z.object({
  sessionId: z.string().uuid().nullable(),
  dialogueRevision: z.number().int().nonnegative(),
  memoryRevision: z.number().int().nonnegative(),
  goal: z.string().nullable(),
  stage: z.string().nullable(),
  openLoops: z.array(z.string()).max(12),
  salience: z.object({
    topics: z.array(z.string()).max(8),
    entities: z.array(z.string()).max(10),
    userIntent: z.string().nullable(),
    assistantCommitment: z.string().nullable(),
    emotionalTone: z.string().nullable(),
    unresolved: z.boolean(),
  }),
  recentTools: z.array(z.object({
    tool: z.string(),
    status: z.string(),
    at: z.string(),
  })).max(12),
  conversation: z.object({
    turnCount: z.number().int().nonnegative(),
    averageReplyChars: z.number().nonnegative(),
  }),
});

const semanticItemSchema = z.object({
  id: z.string().uuid(),
  key: z.string(),
  value: z.string(),
  confidence: z.number().min(0).max(1),
  revision: z.number().int().positive(),
  sourceKind: z.string(),
  observedAt: z.string(),
  validFrom: z.string(),
});

const episodicItemSchema = z.object({
  id: z.string().uuid(),
  topic: z.string(),
  summary: z.string(),
  confidence: z.number().min(0).max(1),
  revision: z.number().int().positive(),
  observedAt: z.string(),
  expiresAt: z.string(),
});

export const cognitiveContextPacketSchema = z.object({
  version: z.literal("cognitive_context.v2"),
  userId: z.string().uuid(),
  generatedAt: z.string(),
  working: workingSchema,
  semantic: z.array(semanticItemSchema),
  episodic: z.array(episodicItemSchema),
  uncertainty: z.object({
    contestedFactCount: z.number().int().nonnegative(),
    contestedKeys: z.array(z.string()).max(8),
    missingEvidence: z.array(z.string()).max(8),
    retrievalConfidence: z.number().min(0).max(1),
  }),
  budget: z.object({
    maxChars: z.number().int().positive(),
    usedChars: z.number().int().nonnegative(),
    semanticLimit: z.number().int().positive(),
    episodicLimit: z.number().int().positive(),
  }),
});

export type CognitiveContextPacket = z.output<typeof cognitiveContextPacketSchema>;

function clip(value: string, max: number): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length <= max ? compact : `${compact.slice(0, max - 1).trimEnd()}…`;
}

export async function buildCognitiveContextPacket(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId?: string | null;
    semanticLimit?: number;
    episodicLimit?: number;
    maxChars?: number;
    now?: Date;
  },
): Promise<CognitiveContextPacket> {
  return withTenantTransaction(app, input.userId, (db) =>
    buildCognitiveContextPacketOnDb(db, input),
  );
}

async function buildCognitiveContextPacketOnDb(
  db: TenantDb,
  input: {
    userId: string;
    sessionId?: string | null;
    semanticLimit?: number;
    episodicLimit?: number;
    maxChars?: number;
    now?: Date;
  },
): Promise<CognitiveContextPacket> {
  const now = input.now ?? new Date();
  const semanticLimit = Math.max(1, Math.min(input.semanticLimit ?? 16, 32));
  const episodicLimit = Math.max(1, Math.min(input.episodicLimit ?? 8, 16));
  const maxChars = Math.max(1_000, Math.min(input.maxChars ?? 6_000, 12_000));

  const [dialogue, revisionRows, factRows, episodeRows, contestedRows] = await Promise.all([
    input.sessionId
      ? readDialogueStateOnDb(db, { userId: input.userId, sessionId: input.sessionId })
      : Promise.resolve(null),
    db
      .select({ revision: cognitiveMemoryRevisions.revision })
      .from(cognitiveMemoryRevisions)
      .where(eq(cognitiveMemoryRevisions.userId, input.userId))
      .limit(1),
    db
      .select({
        id: brainMemoryFacts.id,
        key: brainMemoryFacts.canonicalKey,
        value: brainMemoryFacts.value,
        confidence: brainMemoryFacts.confidence,
        revision: brainMemoryFacts.revision,
        sourceKind: brainMemoryFacts.sourceKind,
        observedAt: brainMemoryFacts.observedAt,
        validFrom: brainMemoryFacts.validFrom,
      })
      .from(brainMemoryFacts)
      .where(and(
        eq(brainMemoryFacts.userId, input.userId),
        eq(brainMemoryFacts.conflictStatus, "active"),
        eq(brainMemoryFacts.lifecycleStatus, "active"),
        isNull(brainMemoryFacts.deletedAt),
        isNull(brainMemoryFacts.validTo),
      ))
      .orderBy(desc(brainMemoryFacts.importanceScore), desc(brainMemoryFacts.observedAt))
      .limit(semanticLimit),
    db
      .select({
        id: brainMemoryEpisodes.id,
        topic: brainMemoryEpisodes.episodeType,
        summary: brainMemoryEpisodes.summary,
        confidence: brainMemoryEpisodes.confidence,
        revision: brainMemoryEpisodes.revision,
        observedAt: brainMemoryEpisodes.observedAt,
        expiresAt: brainMemoryEpisodes.expiresAt,
      })
      .from(brainMemoryEpisodes)
      .where(and(
        eq(brainMemoryEpisodes.userId, input.userId),
        eq(brainMemoryEpisodes.lifecycleStatus, "active"),
        isNull(brainMemoryEpisodes.deletedAt),
        gt(brainMemoryEpisodes.expiresAt, now),
      ))
      .orderBy(desc(brainMemoryEpisodes.importanceScore), desc(brainMemoryEpisodes.observedAt))
      .limit(episodicLimit),
    db
      .select({ key: brainMemoryFacts.canonicalKey, count: sql<number>`count(*)` })
      .from(brainMemoryFacts)
      .where(and(
        eq(brainMemoryFacts.userId, input.userId),
        eq(brainMemoryFacts.conflictStatus, "contested"),
      ))
      .groupBy(brainMemoryFacts.canonicalKey)
      .orderBy(desc(sql`count(*)`))
      .limit(8),
  ]);

  let usedChars = 0;
  const semantic: CognitiveContextPacket["semantic"] = [];
  for (const row of factRows) {
    const value = clip(row.value, 800);
    const cost = row.key.length + value.length;
    if (usedChars + cost > maxChars) break;
    usedChars += cost;
    semantic.push({
      id: row.id,
      key: row.key,
      value,
      confidence: Math.max(0, Math.min(1, row.confidence / 100)),
      revision: row.revision,
      sourceKind: row.sourceKind,
      observedAt: row.observedAt.toISOString(),
      validFrom: row.validFrom.toISOString(),
    });
  }

  const episodic: CognitiveContextPacket["episodic"] = [];
  for (const row of episodeRows) {
    const summary = clip(row.summary, 1_000);
    const cost = row.topic.length + summary.length;
    if (usedChars + cost > maxChars) break;
    usedChars += cost;
    episodic.push({
      id: row.id,
      topic: row.topic,
      summary,
      confidence: Math.max(0, Math.min(1, row.confidence / 100)),
      revision: row.revision,
      observedAt: row.observedAt.toISOString(),
      expiresAt: row.expiresAt.toISOString(),
    });
  }

  const memoryRevision = revisionRows[0]?.revision ?? 0;
  const contestedFactCount = contestedRows.reduce((sum, row) => sum + Number(row.count), 0);
  const evidenceCount = semantic.length + episodic.length;
  return cognitiveContextPacketSchema.parse({
    version: "cognitive_context.v2",
    userId: input.userId,
    generatedAt: now.toISOString(),
    working: {
      sessionId: input.sessionId ?? null,
      dialogueRevision: dialogue?.revision ?? 0,
      memoryRevision,
      goal: dialogue?.state.goal ?? null,
      stage: dialogue?.state.stage ?? null,
      openLoops: dialogue?.state.openLoops ?? [],
      salience: {
        topics: dialogue?.state.salience.topics ?? [],
        entities: dialogue?.state.salience.entities ?? [],
        userIntent: dialogue?.state.salience.userIntent ?? null,
        assistantCommitment: dialogue?.state.salience.assistantCommitment ?? null,
        emotionalTone: dialogue?.state.salience.emotionalTone ?? null,
        unresolved: dialogue?.state.salience.unresolved ?? false,
      },
      recentTools: (dialogue?.state.toolHistory ?? []).slice(-12).map((item) => ({
        tool: item.tool,
        status: item.status,
        at: item.at,
      })),
      conversation: {
        turnCount: dialogue?.state.conversationDynamics.turnCount ?? 0,
        averageReplyChars: dialogue?.state.conversationDynamics.averageReplyChars ?? 0,
      },
    },
    semantic,
    episodic,
    uncertainty: {
      contestedFactCount,
      contestedKeys: contestedRows.map((row) => row.key),
      missingEvidence: evidenceCount === 0 ? ["no_durable_memory"] : [],
      retrievalConfidence:
        evidenceCount === 0
          ? 0
          : Math.max(0, Math.min(1, semantic.reduce((sum, item) => sum + item.confidence, 0) / Math.max(1, semantic.length))),
    },
    budget: { maxChars, usedChars, semanticLimit, episodicLimit },
  });
}

export function renderCognitiveContextPacket(packet: CognitiveContextPacket): string {
  return JSON.stringify(packet);
}
