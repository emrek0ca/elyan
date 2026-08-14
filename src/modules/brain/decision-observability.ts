import type { FastifyInstance } from "fastify";
import type { SemanticContract } from "../../core/understanding/intent-semantic.js";

export type BrainDecisionResult =
  | "queued"
  | "running"
  | "success"
  | "fallback"
  | "error";

export type BrainDecisionObservationInput = {
  taskId?: string | null;
  workload?: string | null;
  route?: string | null;
  model?: string | null;
  responseFormat?: string | null;
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
    workload: safeNullableText(input.workload),
    route: safeNullableText(input.route),
    model: safeNullableText(input.model),
    response_format: safeNullableText(input.responseFormat),
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
