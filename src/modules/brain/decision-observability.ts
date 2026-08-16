import type { FastifyInstance } from "fastify";
import type { SemanticContract } from "../../core/understanding/intent-semantic.js";

export type BrainDecisionResult =
  | "queued"
  | "running"
  | "success"
  | "fallback"
  | "error"
  | "stale_write_rejected";

export type BrainDecisionObservationInput = {
  taskId?: string | null;
  sessionId?: string | null;
  assistantMessageId?: string | null;
  generationAttemptId?: string | null;
  promptDigest?: string | null;
  historyDigest?: string | null;
  historyRevision?: {
    lastCompletedMessageId?: string | null;
    lastCompletedAt?: string | null;
  } | null;
  turnKind?: string | null;
  understandingSource?: string | null;
  understandingConfidence?: number | null;
  workload?: string | null;
  route?: string | null;
  model?: string | null;
  responseFormat?: string | null;
  reasoningMode?: string | null;
  modelSelectionReason?: string | null;
  fallbackReason?: string | null;
  toolSelectionSource?: string | null;
  toolSelectionMs?: number | null;
  reasoningEffort?: string | null;
  outputContract?: string | null;
  blockTypes?: string[] | null;
  blockSchemaValid?: boolean | null;
  semanticGateResult?: string | null;
  evidenceState?: string | null;
  staleWriteRejected?: boolean | null;
  acceptedMs?: number | null;
  firstDeltaMs?: number | null;
  totalMs?: number | null;
  result: BrainDecisionResult;
  durationMs: number;
  semanticContract?: SemanticContract | null;
};

function safeNullableText(value: string | null | undefined): string | null {
  const normalized = typeof value === "string" ? value.trim() : "";
  return normalized ? normalized.slice(0, 120) : null;
}

function safeDurationMs(value: number): number {
  return Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
}

export function buildBrainDecisionObservation(
  input: BrainDecisionObservationInput,
): Record<string, unknown> {
  const contract = input.semanticContract ?? null;
  return {
    task_id: safeNullableText(input.taskId),
    ...(input.sessionId != null
      ? { session_id: safeNullableText(input.sessionId) }
      : {}),
    ...(input.assistantMessageId != null
      ? { assistant_message_id: safeNullableText(input.assistantMessageId) }
      : {}),
    ...(input.generationAttemptId != null
      ? { generation_attempt_id: safeNullableText(input.generationAttemptId) }
      : {}),
    ...(input.promptDigest != null
      ? { prompt_digest: safeNullableText(input.promptDigest) }
      : {}),
    ...(input.historyDigest != null
      ? { history_digest: safeNullableText(input.historyDigest) }
      : {}),
    ...(input.historyRevision != null
      ? {
          history_revision: {
            last_completed_message_id: safeNullableText(
              input.historyRevision.lastCompletedMessageId,
            ),
            last_completed_at: safeNullableText(
              input.historyRevision.lastCompletedAt,
            ),
          },
        }
      : {}),
    ...(input.turnKind != null ? { turn_kind: safeNullableText(input.turnKind) } : {}),
    ...(input.understandingSource != null
      ? { understanding_source: safeNullableText(input.understandingSource) }
      : {}),
    ...(input.understandingConfidence != null
      ? { understanding_confidence: Math.max(0, Math.min(1, input.understandingConfidence)) }
      : {}),
    workload: safeNullableText(input.workload),
    route: safeNullableText(input.route),
    model: safeNullableText(input.model),
    response_format: safeNullableText(input.responseFormat),
    reasoning_mode: safeNullableText(input.reasoningMode),
    model_selection_reason: safeNullableText(input.modelSelectionReason),
    fallback_reason: safeNullableText(input.fallbackReason),
    tool_selection_source: safeNullableText(input.toolSelectionSource),
    ...(input.toolSelectionMs != null
      ? { tool_selection_ms: safeDurationMs(input.toolSelectionMs) }
      : {}),
    ...(input.reasoningEffort != null
      ? { reasoning_effort: safeNullableText(input.reasoningEffort) }
      : {}),
    ...(input.outputContract != null
      ? { output_contract: safeNullableText(input.outputContract) }
      : {}),
    ...(input.blockTypes != null
      ? {
          block_types: Array.from(
            new Set(
              input.blockTypes
                .filter((type) => typeof type === "string")
                .map((type) => type.trim().toLowerCase())
                .filter(Boolean),
            ),
          ).slice(0, 32),
        }
      : {}),
    ...(input.blockSchemaValid != null
      ? { block_schema_valid: input.blockSchemaValid }
      : {}),
    ...(input.semanticGateResult != null
      ? { semantic_gate_result: safeNullableText(input.semanticGateResult) }
      : {}),
    ...(input.evidenceState != null
      ? { evidence_state: safeNullableText(input.evidenceState) }
      : {}),
    ...(input.staleWriteRejected != null
      ? { stale_write_rejected: input.staleWriteRejected }
      : {}),
    ...(input.acceptedMs != null
      ? { accepted_ms: safeDurationMs(input.acceptedMs) }
      : {}),
    ...(input.firstDeltaMs != null
      ? { first_delta_ms: safeDurationMs(input.firstDeltaMs) }
      : {}),
    ...(input.totalMs != null
      ? { total_ms: safeDurationMs(input.totalMs) }
      : {}),
    result: input.result,
    duration_ms: safeDurationMs(input.durationMs),
    ...(contract
      ? {
          semantic_contract: {
            schema_version: contract.schemaVersion,
            conversation_mode: contract.conversationMode,
            surface: contract.surface,
            intent: contract.intent,
            artifact: contract.artifact,
            required_context: contract.requiredContext,
            side_effect: contract.sideEffect,
            privacy_class: contract.privacyClass,
            required_capabilities: contract.requiredCapabilities,
            needs_approval: contract.needsApproval,
            confidence: contract.confidence,
            ambiguity: contract.ambiguity,
            evidence: contract.evidence,
          },
        }
      : {}),
  };
}

export function logBrainDecisionObservation(
  app: FastifyInstance,
  input: BrainDecisionObservationInput,
): void {
  if (typeof app.log?.info !== "function") return;
  app.log.info(
    buildBrainDecisionObservation(input),
    "brain decision",
  );
}
