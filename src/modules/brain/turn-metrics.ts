import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { turnMetrics } from "../../db/schema.js";

const uuidSchema = z.string().uuid();
const safeIdSchema = z.string().trim().min(1).max(160);
const workloadSchema = z.string().trim().min(1).max(80);
const nonNegativeIntSchema = z.preprocess(
  (value) => (typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.round(value)) : value),
  z.number().finite().int().nonnegative(),
);
const nullableTimingSchema = nonNegativeIntSchema.nullable().default(null);

export const turnMetricTimingsSchema = z.object({
  understand_ms: nullableTimingSchema,
  retrieval_ms: nullableTimingSchema,
  memory_ms: nullableTimingSchema,
  grounding_ms: nullableTimingSchema,
  first_delta_ms: nullableTimingSchema,
  total_ms: nullableTimingSchema,
  tool_loop_iterations: nonNegativeIntSchema.default(0),
  tool_ms: nullableTimingSchema,
});

export const turnMetricQualitySchema = z.object({
  envelope_parse_ok: z.boolean().nullable().default(null),
  fallback_used: z.boolean().default(false),
  dump_detected: z.boolean().default(false),
  salvage_used: z.boolean().default(false),
  blocks_emitted: z.array(z.string().trim().min(1).max(80)).max(40).default([]),
  model_call_count: nonNegativeIntSchema.default(1),
  reasoning_passes: nonNegativeIntSchema.default(1),
  refinement_applied: z.boolean().default(false),
  rate_limited: z.boolean().default(false),
  deduped_inflight: z.boolean().default(false),
  cheap_social_turn: z.boolean().default(false),
  estimated_cost_bucket: z.string().trim().max(80).nullable().default(null),
  memory_ops_count: nonNegativeIntSchema.default(0),
  follow_ups_count: nonNegativeIntSchema.default(0),
  memory_forget_count: nonNegativeIntSchema.default(0),
  canonical_user_model_used: z.boolean().default(false),
  dialogue_state_revision: nonNegativeIntSchema.nullable().default(null),
  stale_recall_count: nonNegativeIntSchema.default(0),
  memory_recall_fact_count: nonNegativeIntSchema.default(0),
  memory_recall_episode_count: nonNegativeIntSchema.default(0),
});

export const turnMetricInputSchema = z.object({
  turnId: safeIdSchema,
  userId: uuidSchema,
  sessionId: uuidSchema.nullable().default(null),
  workload: workloadSchema,
  timings: turnMetricTimingsSchema.default({}),
  quality: turnMetricQualitySchema.default({}),
});

export type TurnMetricInput = z.input<typeof turnMetricInputSchema>;
export type NormalizedTurnMetricInput = z.output<typeof turnMetricInputSchema>;

function readRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.round(value))
    : null;
}

function readBoolean(value: unknown): boolean {
  return value === true;
}

function readNullableBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function extractSessionId(requestMetadata: unknown): string | null {
  const metadata = readRecord(requestMetadata);
  const direct = readString(metadata?.sessionId);
  if (direct && uuidSchema.safeParse(direct).success) {
    return direct;
  }
  const chat = readRecord(metadata?.chat);
  const chatSessionId = readString(chat?.sessionId);
  return chatSessionId && uuidSchema.safeParse(chatSessionId).success ? chatSessionId : null;
}

function extractBlockTypes(metadata: Record<string, unknown>): string[] {
  const blocks = Array.isArray(metadata.blocks) ? metadata.blocks : [];
  const blockTypes: string[] = [];
  for (const block of blocks) {
    const blockRecord = readRecord(block);
    const type = readString(blockRecord?.type);
    if (type && !blockTypes.includes(type)) {
      blockTypes.push(type);
    }
  }
  return blockTypes;
}

export function buildTurnMetricInputFromInference(input: {
  userId: string;
  taskId?: string;
  requestMetadata?: Record<string, unknown>;
  latencyMs: number;
  metadata: Record<string, unknown>;
}): TurnMetricInput {
  const firstDeltaMs = readNumber(input.metadata.firstDeltaMs);
  const totalMs = readNumber(input.metadata.completionLatencyMs) ?? readNumber(input.latencyMs);
  const toolLoopIterations = readNumber(input.metadata.toolLoopIterations) ?? 0;
  const toolMs = readNumber(input.metadata.toolMs);
  return {
    turnId: input.taskId ?? randomUUID(),
    userId: input.userId,
    sessionId: extractSessionId(input.requestMetadata),
    workload: readString(input.metadata.workload) ?? "unknown",
    timings: {
      understand_ms: null,
      retrieval_ms: null,
      memory_ms: null,
      grounding_ms: null,
      first_delta_ms: firstDeltaMs,
      total_ms: totalMs,
      tool_loop_iterations: toolLoopIterations,
      tool_ms: toolMs,
    },
    quality: {
      envelope_parse_ok: readNullableBoolean(input.metadata.turnEnvelopeParseOk),
      fallback_used: readBoolean(input.metadata.fallbackUsed),
      dump_detected: readBoolean(input.metadata.reasoningDumpDetected),
      salvage_used:
        readBoolean(input.metadata.repairApplied) ||
        readBoolean(input.metadata.salvageUsed),
      blocks_emitted: extractBlockTypes(input.metadata),
      model_call_count: readNumber(input.metadata.modelCallCount) ?? 1,
      reasoning_passes: readNumber(input.metadata.reasoningPasses) ?? 1,
      refinement_applied: readBoolean(input.metadata.refinementApplied),
      rate_limited: readBoolean(input.metadata.rateLimited),
      deduped_inflight: readBoolean(input.metadata.dedupedInflight),
      cheap_social_turn: readBoolean(input.metadata.cheapSocialTurn),
      estimated_cost_bucket: readString(input.metadata.estimatedCostBucket),
      memory_ops_count: readNumber(input.metadata.memoryOpsCount) ?? 0,
      follow_ups_count: readNumber(input.metadata.followUpsCount) ?? 0,
      memory_forget_count: readNumber(input.metadata.memoryForgetCount) ?? 0,
      canonical_user_model_used: readBoolean(input.metadata.canonicalUserModelUsed),
      dialogue_state_revision: readNumber(input.metadata.dialogueStateRevision),
      stale_recall_count: readNumber(input.metadata.staleRecallCount) ?? 0,
      memory_recall_fact_count: readNumber(input.metadata.memoryRecallFactCount) ?? 0,
      memory_recall_episode_count: readNumber(input.metadata.memoryRecallEpisodeCount) ?? 0,
    },
  };
}

export async function recordTurnMetric(
  app: FastifyInstance,
  input: TurnMetricInput,
): Promise<void> {
  try {
    const parsed = turnMetricInputSchema.parse(input);
    await app.db.insert(turnMetrics).values({
      turnId: parsed.turnId,
      userId: parsed.userId,
      sessionId: parsed.sessionId,
      workload: parsed.workload,
      timings: parsed.timings,
      quality: parsed.quality,
    });
  } catch (error) {
    app.log.debug(
      { err: error instanceof Error ? error.message : "turn_metrics_write_failed" },
      "turn metrics write skipped",
    );
  }
}
