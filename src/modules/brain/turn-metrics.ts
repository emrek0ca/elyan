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
  block_schema_valid: z.boolean().nullable().default(null),
  block_fallback_used: z.boolean().default(false),
  render_recipe_preflight_ok: z.boolean().nullable().default(null),
  document_requirements_count: nonNegativeIntSchema.default(0),
  data_input_bytes_bucket: z.string().trim().max(80).nullable().default(null),
  heavy_context_truncated: z.boolean().default(false),
  worker_offloaded: z.boolean().default(false),
  queue_wait_ms: nullableTimingSchema,
  cognitive_write_ms: nullableTimingSchema,
  cognitive_foundation_used: z.boolean().default(false),
  cognitive_memory_revision: nonNegativeIntSchema.nullable().default(null),
  cognitive_shadow_key_mismatch_count: nonNegativeIntSchema.default(0),
  agent_engine_version: z.string().trim().max(40).nullable().default(null),
  agent_run_state: z.string().trim().max(32).nullable().default(null),
  agent_run_id: z.string().trim().max(160).nullable().default(null),
  agent_verification_passed: z.boolean().default(false),
  claim_confidence_avg: z.number().min(0).max(1).nullable().default(null),
  low_confidence_claims: nonNegativeIntSchema.default(0),
  uncertainty_action: z.string().trim().max(40).nullable().default(null),
  tool_called_for_uncertainty: z.boolean().default(false),
  clarification_requested: z.boolean().default(false),
  missing_evidence_count: nonNegativeIntSchema.default(0),
  verified_evidence_count: nonNegativeIntSchema.default(0),
  contested_memory_count: nonNegativeIntSchema.default(0),
  claim_self_check_applied: z.boolean().default(false),
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

function readRatio(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value)
    ? Number(Math.max(0, Math.min(1, value)).toFixed(2))
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

function readBlockQuality(metadata: Record<string, unknown>): Record<string, unknown> | null {
  return readRecord(metadata.blockQuality);
}

function readBlockQualityMetrics(metadata: Record<string, unknown>): Record<string, unknown> | null {
  return readRecord(readBlockQuality(metadata)?.metrics);
}

function countDocumentRequirements(value: unknown): number {
  const record = readRecord(value);
  if (!record) {
    return 0;
  }
  let count = 0;
  const mustInclude = Array.isArray(record.must_include) ? record.must_include : [];
  count += mustInclude.length;
  const moneyAmounts = Array.isArray(record.money_amounts) ? record.money_amounts : [];
  count += moneyAmounts.length;
  if (record.footer_text || record.signature_text) {
    count += 1;
  }
  if (readRecord(record.spreadsheet)) {
    count += 1;
  }
  return count;
}

function extractDocumentRequirementsCount(metadata: Record<string, unknown>): number {
  const direct = readNumber(metadata.documentRequirementsCount);
  if (direct !== null) {
    return direct;
  }
  const renderRecipe = readRecord(metadata.renderRecipe);
  const renderRecipeMetadata = readRecord(renderRecipe?.metadata);
  return countDocumentRequirements(
    metadata.document_requirements ??
      metadata.documentRequirements ??
      renderRecipeMetadata?.document_requirements,
  );
}

function bucketByteSize(value: unknown): string | null {
  const size = readNumber(value);
  if (size === null) {
    return null;
  }
  if (size === 0) {
    return "zero";
  }
  if (size <= 16_384) {
    return "le_16kb";
  }
  if (size <= 65_536) {
    return "le_64kb";
  }
  if (size <= 262_144) {
    return "le_256kb";
  }
  if (size <= 1_048_576) {
    return "le_1mb";
  }
  return "gt_1mb";
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
  const blockQuality = readBlockQuality(input.metadata);
  const blockQualityMetrics = readBlockQualityMetrics(input.metadata);
  const schemaInvalidCount = readNumber(blockQualityMetrics?.schemaInvalidBlockCount);
  const fallbackToTextCount = readNumber(blockQualityMetrics?.fallbackToTextCount);
  const renderRecipe = readRecord(input.metadata.renderRecipe);
  const renderRecipeMetadata = readRecord(renderRecipe?.metadata);
  const cognitiveShadow = readRecord(input.metadata.cognitiveShadow);
  return {
    turnId: input.taskId ?? randomUUID(),
    userId: input.userId,
    sessionId: extractSessionId(input.requestMetadata),
    workload: readString(input.metadata.workload) ?? "unknown",
    timings: {
      understand_ms: null,
      retrieval_ms: null,
      memory_ms: readNumber(input.metadata.cognitiveReadMs),
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
      block_schema_valid:
        readNullableBoolean(input.metadata.blockSchemaValid) ??
        (schemaInvalidCount === null ? null : schemaInvalidCount === 0),
      block_fallback_used:
        readBoolean(input.metadata.blockFallbackUsed) ||
        (fallbackToTextCount ?? 0) > 0,
      render_recipe_preflight_ok:
        readNullableBoolean(input.metadata.renderRecipePreflightOk) ??
        readNullableBoolean(renderRecipeMetadata?.preflight_required),
      document_requirements_count: extractDocumentRequirementsCount(input.metadata),
      data_input_bytes_bucket:
        readString(input.metadata.dataInputBytesBucket) ??
        bucketByteSize(input.metadata.dataInputBytes),
      heavy_context_truncated: readBoolean(input.metadata.heavyContextTruncated),
      worker_offloaded: readBoolean(input.metadata.workerOffloaded),
      queue_wait_ms: readNumber(input.metadata.queueWaitMs),
      cognitive_write_ms: readNumber(input.metadata.cognitiveWriteMs),
      cognitive_foundation_used: readBoolean(input.metadata.cognitiveFoundationUsed),
      cognitive_memory_revision: readNumber(input.metadata.cognitiveMemoryRevision),
      cognitive_shadow_key_mismatch_count:
        readNumber(cognitiveShadow?.keyMismatchCount) ?? 0,
      agent_engine_version: readString(input.metadata.agentEngineVersion),
      agent_run_state: readString(input.metadata.agentRunState),
      agent_run_id: readString(input.metadata.agentRunId),
      agent_verification_passed: readString(input.metadata.agentRunState) === "completed",
      claim_confidence_avg: readRatio(input.metadata.claimConfidence),
      low_confidence_claims: readNumber(input.metadata.lowConfidenceClaims) ?? 0,
      uncertainty_action: readString(input.metadata.uncertaintyAction),
      tool_called_for_uncertainty: readBoolean(input.metadata.toolCalledForUncertainty),
      clarification_requested: readBoolean(input.metadata.clarificationRequested),
      missing_evidence_count: readNumber(input.metadata.missingEvidenceCount) ?? 0,
      verified_evidence_count: readNumber(input.metadata.verifiedEvidenceCount) ?? 0,
      contested_memory_count: readNumber(input.metadata.contestedMemoryCount) ?? 0,
      claim_self_check_applied: readBoolean(input.metadata.selfCheckApplied),
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
