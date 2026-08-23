import { and, eq, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import {
  cognitiveMemoryRevisions,
  cognitiveMutationOutbox,
  brainMemoryEpisodes,
  brainMemoryFacts,
  learningEvents,
} from "../../db/schema.js";
import {
  recordTurnMemoryOpsOnDb,
  canonicalizeMemoryKey,
  type TurnMemoryOpsWriteResult,
} from "./memory-fabric.js";
import type { TurnEnvelope } from "./turn-envelope.js";
import { setTenantContext } from "../../db/tenant-context.js";
import {
  recordDialogueStateTurnOnDb,
  type DialogueStateTurnInput,
} from "./dialogue-state.js";
import { recordCognitiveFoundationSignal } from "./cognitive-foundation-policy.js";
import { invalidateCanonicalMemoryCache } from "./memory-context-cache.js";
import { redactAgentTrajectoryRecords } from "../tasks/agent-trajectory.js";

const evidenceSchema = z.object({
  type: z.string().trim().min(1).max(64),
  key: z.string().trim().min(1).max(120),
  value: z.string().max(4_000),
  confidence: z.number().min(0).max(1),
  scope: z.enum(["user", "account", "project"]).default("user"),
  source: z.string().trim().min(1).max(64).default("interaction"),
  privacyLevel: z.enum(["safe", "sensitive", "restricted"]).default("safe"),
  ttlDays: z.number().int().positive().max(3650).optional(),
  metadata: z.record(z.unknown()).default({}),
});

export type CognitiveEvidence = z.input<typeof evidenceSchema>;

export type CognitiveMemoryWriteResult = TurnMemoryOpsWriteResult & {
  revision: number;
  evidenceWritten: number;
  factIds: string[];
  episodeIds: string[];
};

function emptyWriteResult(revision = 0): CognitiveMemoryWriteResult {
  return {
    revision,
    evidenceWritten: 0,
    factIds: [],
    episodeIds: [],
    processed: 0,
    factsWritten: 0,
    episodesWritten: 0,
    contested: 0,
    forgotten: 0,
    skipped: 0,
  };
}

async function allocateRevision(
  db: FastifyInstance["db"],
  userId: string,
  now: Date,
): Promise<number> {
  const rows = await db
    .insert(cognitiveMemoryRevisions)
    .values({ userId, revision: 1, updatedAt: now })
    .onConflictDoUpdate({
      target: cognitiveMemoryRevisions.userId,
      set: {
        revision: sql`${cognitiveMemoryRevisions.revision} + 1`,
        updatedAt: now,
      },
    })
    .returning({ revision: cognitiveMemoryRevisions.revision });
  return rows[0]?.revision ?? 1;
}

export class CognitiveMemoryRepository {
  constructor(private readonly app: FastifyInstance) {}

  async writeTurn(input: {
    userId: string;
    accountId?: string;
    taskId?: string;
    sessionId?: string | null;
    requestId?: string;
    sourceKind: "turn_envelope" | "explicit_signal" | "async_extraction" | "system";
    sourceId?: string | null;
    envelope?: TurnEnvelope | null;
    evidence?: CognitiveEvidence[];
    dialogue?: Omit<DialogueStateTurnInput, "userId" | "sessionId" | "memoryRefs">;
    now?: Date;
  }): Promise<CognitiveMemoryWriteResult> {
    const evidence = (input.evidence ?? []).map((item) => evidenceSchema.parse(item));
    const ops = input.envelope?.memory_ops ?? [];
    if (evidence.length === 0 && ops.length === 0 && !input.dialogue) {
      return emptyWriteResult();
    }

    const now = input.now ?? new Date();
    return this.app.db.transaction(async (tx) => {
      const db = tx as FastifyInstance["db"];
      await setTenantContext(db, { userId: input.userId });
      const revision = await allocateRevision(db, input.userId, now);

      if (evidence.length > 0) {
        await tx.insert(learningEvents).values(
          evidence.map((item) => ({
            userId: input.userId,
            accountId: input.accountId ?? input.userId,
            taskId: input.taskId,
            type: item.type,
            key: item.key,
            value: item.value,
            confidence: Math.round(item.confidence * 100),
            scope: item.scope,
            source: item.source,
            privacyLevel: item.privacyLevel,
            metadata: {
              ...item.metadata,
              requestId: input.requestId,
              cognitiveRevision: revision,
            },
            expiresAt: item.ttlDays
              ? new Date(now.getTime() + item.ttlDays * 86_400_000)
              : null,
          })),
        );
      }

      const forgottenKeys = [...new Set(
        ops.filter((op) => op.op === "forget").map((op) => op.key),
      )];
      for (const key of forgottenKeys) {
        await tx
          .update(learningEvents)
          .set({ privacyLevel: "restricted", expiresAt: now })
          .where(and(eq(learningEvents.userId, input.userId), eq(learningEvents.key, key)));

        // Explicit trajectory forget is additive to the existing memory
        // tombstone. The learning dataset must stop seeing the episode too;
        // retaining a row for audit is fine, but it is no longer trainable.
        const canonicalKey = canonicalizeMemoryKey(key);
        const trajectoryTaskId = canonicalKey.startsWith("agent_trajectory:")
          ? canonicalKey.slice("agent_trajectory:".length) || null
          : canonicalKey === "trajectory"
            ? input.taskId ?? null
            : null;
        if (canonicalKey === "agent_trajectory" || canonicalKey === "trajectory" || trajectoryTaskId) {
          await redactAgentTrajectoryRecords(db, {
            userId: input.userId,
            taskId: trajectoryTaskId,
            now,
            reason: "explicit_user_forget",
          });
        }
      }

      const memory = await recordTurnMemoryOpsOnDb(db, {
        userId: input.userId,
        sessionId: input.sessionId ?? null,
        envelope: input.envelope,
        now,
        revision,
        sourceKind: input.sourceKind,
        sourceId: input.sourceId ?? input.requestId ?? input.taskId ?? input.sessionId ?? null,
      });

      const [factRefs, episodeRefs] = await Promise.all([
            tx
              .select({ id: brainMemoryFacts.id })
              .from(brainMemoryFacts)
              .where(and(
                eq(brainMemoryFacts.userId, input.userId),
                eq(brainMemoryFacts.revision, revision),
              ))
              .limit(80),
            tx
              .select({ id: brainMemoryEpisodes.id })
              .from(brainMemoryEpisodes)
              .where(and(
                eq(brainMemoryEpisodes.userId, input.userId),
                eq(brainMemoryEpisodes.revision, revision),
              ))
              .limit(40),
          ]);

      if (input.dialogue && input.sessionId) {
        const dialogue = await recordDialogueStateTurnOnDb(
          db,
          {
            ...input.dialogue,
            userId: input.userId,
            sessionId: input.sessionId,
            memoryRefs: {
              revision,
              factIds: factRefs.map((row) => row.id),
              episodeIds: episodeRefs.map((row) => row.id),
            },
          },
          { foundationEnabled: true },
        );
        if (!dialogue) {
          throw new Error("cognitive_dialogue_revision_conflict");
        }
      }

      await tx.insert(cognitiveMutationOutbox).values({
        userId: input.userId,
        sessionId: input.sessionId ?? null,
        revision,
        eventType: "cognitive.memory.committed",
        payload: {
          evidenceCount: evidence.length,
          memoryOpsCount: memory.processed,
          factsWritten: memory.factsWritten,
          episodesWritten: memory.episodesWritten,
          forgotten: memory.forgotten,
          contested: memory.contested,
          sourceKind: input.sourceKind,
        },
      });

      return {
        ...memory,
        revision,
        evidenceWritten: evidence.length,
        factIds: factRefs.map((row) => row.id),
        episodeIds: episodeRefs.map((row) => row.id),
      };
    }).then(async (result) => {
      if (
        result.factsWritten > 0 ||
        result.contested > 0 ||
        result.forgotten > 0
      ) {
        await invalidateCanonicalMemoryCache(this.app, input.userId);
      }
      recordCognitiveFoundationSignal({ ok: true });
      return result;
    }).catch((error) => {
      recordCognitiveFoundationSignal({ ok: false });
      throw error;
    });
  }
}

export function cognitiveMemoryRepository(app: FastifyInstance): CognitiveMemoryRepository {
  return new CognitiveMemoryRepository(app);
}
