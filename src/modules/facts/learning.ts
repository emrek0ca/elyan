import type { FastifyInstance } from "fastify";
import { and, eq } from "drizzle-orm";
import { learningEvents } from "../../db/schema.js";
import type { FactAnswer } from "./types.js";

const STABLE_PROVIDERS = new Set(["world_bank", "crossref"]);

export async function recordStableFactCandidate(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId?: string | null;
    answer?: FactAnswer | null;
  },
): Promise<void> {
  const answer = input.answer;
  if (
    !input.taskId ||
    !answer?.source ||
    !STABLE_PROVIDERS.has(answer.providerId) ||
    answer.source.verificationState !== "verified"
  ) {
    return;
  }
  const key = `retrieval_candidate:${answer.source.sourceHash.slice(0, 64)}`;
  const [existing] = await app.db
    .select({ id: learningEvents.id })
    .from(learningEvents)
    .where(
      and(
        eq(learningEvents.type, "retrieval_distillation_candidate"),
        eq(learningEvents.scope, "shared"),
        eq(learningEvents.key, key),
      ),
    )
    .limit(1);
  if (existing) return;
  await app.db
    .insert(learningEvents)
    .values({
      userId: input.userId,
      accountId: input.userId,
      taskId: input.taskId,
      type: "retrieval_distillation_candidate",
      key,
      value: answer.snippet.slice(0, 2_000),
      confidence: Math.round(answer.confidence * 100),
      scope: "shared",
      source: "verified_public_evidence",
      privacyLevel: "safe",
      metadata: {
        retrievalOnly: true,
        providerId: answer.providerId,
        authority: answer.source.authority,
        sourceHash: answer.source.sourceHash,
        observedAt: answer.source.observedAt,
        verificationState: answer.source.verificationState,
      },
    })
    .onConflictDoNothing();
}
