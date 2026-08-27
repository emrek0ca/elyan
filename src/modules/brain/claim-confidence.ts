import { z } from "zod";
import type { CommandRouteDecision } from "../routing-policy/service.js";
import type { UserUnderstandingContext } from "../../core/understanding/types.js";
import { asRecord as readRecord } from "../../lib/record.js";
import {
  asFiniteNumber as readNumber,
  asNonEmptyString as readString,
} from "../../lib/text.js";

export const claimSourceSchema = z.enum([
  "known_fact",
  "memory",
  "tool_verified",
  "inference",
  "missing",
]);
export type ClaimSource = z.output<typeof claimSourceSchema>;

export const uncertaintyActionSchema = z.enum([
  "answer",
  "call_tool",
  "ask_clarification",
  "limit_answer",
  "block_or_refuse",
]);
export type UncertaintyAction = z.output<typeof uncertaintyActionSchema>;

export const claimRecordSchema = z.object({
  id: z.string().trim().min(1).max(120),
  source: claimSourceSchema,
  confidence: z.number().min(0).max(1),
  evidenceRefs: z.array(z.string().trim().min(1).max(160)).max(12).default([]),
  factRevision: z.number().int().positive().nullable().default(null),
  toolResultId: z.string().trim().min(1).max(160).nullable().default(null),
  staleness: z.enum(["fresh", "stale", "contested", "unknown"]).default("unknown"),
  contested: z.boolean().default(false),
  requiredForAnswer: z.boolean().default(false),
});
export type ClaimRecord = z.output<typeof claimRecordSchema>;

const sourceCountsSchema = z.object({
  known_fact: z.number().int().nonnegative().default(0),
  memory: z.number().int().nonnegative().default(0),
  tool_verified: z.number().int().nonnegative().default(0),
  inference: z.number().int().nonnegative().default(0),
  missing: z.number().int().nonnegative().default(0),
});
export type ClaimSourceCounts = z.output<typeof sourceCountsSchema>;

export const claimLedgerSchema = z.object({
  version: z.literal("claim_confidence.v1"),
  generatedAt: z.string().datetime(),
  claims: z.array(claimRecordSchema).max(80),
  summary: z.object({
    claimConfidence: z.number().min(0).max(1),
    claimSourceCounts: sourceCountsSchema,
    lowConfidenceClaims: z.number().int().nonnegative(),
    missingEvidenceCount: z.number().int().nonnegative(),
    verifiedEvidenceCount: z.number().int().nonnegative(),
    contestedMemoryCount: z.number().int().nonnegative(),
    uncertaintyAction: uncertaintyActionSchema,
    selfCheckApplied: z.boolean(),
    toolCalledForUncertainty: z.boolean(),
    clarificationRequested: z.boolean(),
  }),
});
export type ClaimLedger = z.output<typeof claimLedgerSchema>;

export type ClaimConfidenceInput = {
  userId?: string | null;
  route?: string | null;
  workload?: string | null;
  routeDecision?: CommandRouteDecision | null;
  requestMetadata?: Record<string, unknown> | null;
  inferenceMetadata?: Record<string, unknown> | null;
  understandingContext?: UserUnderstandingContext | null;
  toolResults?: Array<Record<string, unknown>> | null;
  now?: Date;
};

type ClaimConfidenceConfig = {
  ELYAN_CLAIM_CONFIDENCE_V1_ENABLED?: boolean;
  ELYAN_CLAIM_CONFIDENCE_SHADOW_ENABLED?: boolean;
  ELYAN_SELF_CHECK_MODEL_FALLBACK_ENABLED?: boolean;
};

type ClaimConfidenceApp = {
  config?: ClaimConfidenceConfig;
};

function readBoolean(value: unknown): boolean {
  return value === true;
}

function normalizeConfidence(value: unknown, fallback = 0.5): number {
  const number = readNumber(value);
  if (number == null) {
    return fallback;
  }
  const normalized = number > 1 ? number / 100 : number;
  return Math.max(0, Math.min(1, normalized));
}

function countArray(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

function readMetadataNumber(metadata: Record<string, unknown>, key: string): number {
  const value = readNumber(metadata[key]);
  return value == null ? 0 : Math.max(0, Math.round(value));
}

function addClaim(claims: ClaimRecord[], claim: z.input<typeof claimRecordSchema>) {
  const parsed = claimRecordSchema.parse(claim);
  if (claims.some((item) => item.id === parsed.id)) {
    return;
  }
  claims.push(parsed);
}

function inferBaseEvidenceConfidence(metadata: Record<string, unknown>): number {
  const dataConfidence = readString(metadata.dataConfidence);
  if (dataConfidence === "high") return 0.9;
  if (dataConfidence === "medium") return 0.7;
  if (dataConfidence === "needs_clarification") return 0.35;
  if (dataConfidence === "low") return 0.35;
  const evidenceSufficiency = readString(metadata.evidenceSufficiency);
  if (evidenceSufficiency === "strong") return 0.86;
  if (evidenceSufficiency === "partial") return 0.64;
  if (evidenceSufficiency === "ambiguous") return 0.35;
  if (evidenceSufficiency === "weak") return 0.34;
  return 0.58;
}

function extractUnderstandingRecord(input: ClaimConfidenceInput): Record<string, unknown> | null {
  const metadata = input.requestMetadata ?? {};
  const direct = readRecord(metadata.understanding);
  if (direct) {
    return direct;
  }
  return readRecord(metadata.metadata)?.understanding
    ? readRecord(readRecord(metadata.metadata)?.understanding)
    : null;
}

function extractEnvelopeRecord(input: ClaimConfidenceInput): Record<string, unknown> | null {
  const understanding = extractUnderstandingRecord(input);
  return readRecord(understanding?.envelope) ?? readRecord(input.requestMetadata?.envelope);
}

function requiredCapabilityNames(input: ClaimConfidenceInput): string[] {
  const envelope = extractEnvelopeRecord(input);
  const capabilities = Array.isArray(envelope?.required_capabilities)
    ? envelope.required_capabilities
    : [];
  const names = capabilities
    .map((item) => readString(readRecord(item)?.name))
    .filter((item): item is string => Boolean(item));
  const routeCapabilities = Array.isArray(input.routeDecision?.capabilities)
    ? input.routeDecision.capabilities.filter((item): item is string => typeof item === "string")
    : [];
  return [...new Set([...names, ...routeCapabilities])];
}

function desiredOutputKinds(input: ClaimConfidenceInput): string[] {
  const envelope = extractEnvelopeRecord(input);
  const desiredOutputs = Array.isArray(envelope?.desired_outputs)
    ? envelope.desired_outputs
    : [];
  return desiredOutputs
    .map((item) => readString(readRecord(item)?.kind))
    .filter((item): item is string => Boolean(item));
}

function ambiguityCount(input: ClaimConfidenceInput): number {
  const envelope = extractEnvelopeRecord(input);
  return countArray(envelope?.ambiguities);
}

function envelopeConfidence(input: ClaimConfidenceInput): number | null {
  const understanding = extractUnderstandingRecord(input);
  const direct = readNumber(understanding?.envelopeConfidence);
  if (direct != null) return normalizeConfidence(direct);
  const envelope = extractEnvelopeRecord(input);
  const fromEnvelope = readNumber(envelope?.confidence);
  return fromEnvelope == null ? null : normalizeConfidence(fromEnvelope);
}

function hasRequiredToolOpportunity(input: ClaimConfidenceInput): boolean {
  const capabilities = requiredCapabilityNames(input);
  const outputs = desiredOutputKinds(input);
  if (
    input.routeDecision?.requiredRuntime === "desktop" ||
    input.routeDecision?.requiredRuntime === "both" ||
    input.routeDecision?.privacyClass === "local_private" ||
    input.route === "desktop_required"
  ) {
    return true;
  }
  return capabilities.some((name) =>
    [
      "browser.read",
      "document.read",
      "document.write",
      "document.export",
      "spreadsheet.write",
      "desktop.file_access",
      "desktop.runtime",
      "automation.schedule",
      "memory.write",
      "goal.update",
    ].includes(name),
  ) || outputs.some((kind) => ["pdf", "docx", "xlsx", "artifact", "task_result", "action"].includes(kind));
}

function collectToolResults(input: ClaimConfidenceInput): Array<Record<string, unknown>> {
  const explicit = input.toolResults ?? [];
  const fromMetadata = Array.isArray(input.inferenceMetadata?.toolResults)
    ? input.inferenceMetadata.toolResults
        .map((item) => readRecord(item))
        .filter((item): item is Record<string, unknown> => Boolean(item))
    : [];
  return [...explicit, ...fromMetadata].slice(0, 24);
}

function buildClaims(input: ClaimConfidenceInput): ClaimRecord[] {
  const claims: ClaimRecord[] = [];
  const metadata = input.inferenceMetadata ?? {};
  const context = input.understandingContext ?? null;

  addClaim(claims, {
    id: "current_request",
    source: "known_fact",
    confidence: envelopeConfidence(input) ?? 0.72,
    evidenceRefs: ["current_turn"],
    staleness: "fresh",
    requiredForAnswer: true,
  });

  for (const [index, item] of (context?.retrievedMemory ?? []).slice(0, 16).entries()) {
    const staleness =
      item.staleness === "fresh" || item.staleness === "stale" || item.staleness === "contested"
        ? item.staleness
        : "unknown";
    addClaim(claims, {
      id: `memory_retrieved_${index + 1}`,
      source: "memory",
      confidence: normalizeConfidence(item.confidence, 0.55),
      evidenceRefs: [`memory:${item.id}`],
      staleness,
      contested: staleness === "contested" || item.conflictStatus === "contested",
      requiredForAnswer: Boolean(item.isPinned) || item.type === "identity" || item.type === "preference",
    });
  }

  for (const [index, item] of (context?.memoryRecall?.facts ?? []).slice(0, 12).entries()) {
    addClaim(claims, {
      id: `memory_recall_fact_${index + 1}`,
      source: "memory",
      confidence: normalizeConfidence(item.confidence, 0.6),
      evidenceRefs: [`memory_recall:${index + 1}`],
      staleness: "fresh",
    });
  }

  for (const [index, item] of (context?.cognitiveContext?.semantic ?? []).slice(0, 16).entries()) {
    addClaim(claims, {
      id: `cognitive_fact_${index + 1}`,
      source: "memory",
      confidence: normalizeConfidence(item.confidence, 0.65),
      evidenceRefs: [`cognitive_fact:${item.id}`],
      factRevision: item.revision,
      staleness: "fresh",
      requiredForAnswer: item.key === "preferred_name" || item.key === "name",
    });
  }

  for (const key of context?.cognitiveContext?.uncertainty.contestedKeys ?? []) {
    addClaim(claims, {
      id: `contested_memory_${claims.filter((item) => item.id.startsWith("contested_memory_")).length + 1}`,
      source: "memory",
      confidence: 0.25,
      evidenceRefs: [`contested:${key.slice(0, 80)}`],
      staleness: "contested",
      contested: true,
      requiredForAnswer: true,
    });
  }

  if (readBoolean(metadata.webGroundingUsed) || readMetadataNumber(metadata, "webSourceCount") > 0) {
    addClaim(claims, {
      id: "web_grounding",
      source: "tool_verified",
      confidence: Math.max(0.78, inferBaseEvidenceConfidence(metadata)),
      evidenceRefs: [`web_sources:${readMetadataNumber(metadata, "webSourceCount")}`],
      staleness: "fresh",
      requiredForAnswer: true,
    });
  }

  if (
    readBoolean(metadata.attachmentContextUsed) ||
    readMetadataNumber(metadata, "documentSourceCount") > 0 ||
    readMetadataNumber(metadata, "retrievalResultCount") > 0
  ) {
    addClaim(claims, {
      id: "retrieval_or_attachment",
      source: "tool_verified",
      confidence: Math.max(0.72, inferBaseEvidenceConfidence(metadata)),
      evidenceRefs: [
        `documents:${readMetadataNumber(metadata, "documentSourceCount")}`,
        `retrieval:${readMetadataNumber(metadata, "retrievalResultCount")}`,
      ],
      staleness: "fresh",
      requiredForAnswer: true,
    });
  }

  for (const [index, result] of collectToolResults(input).entries()) {
    if (result.ok !== true) continue;
    addClaim(claims, {
      id: `tool_result_${index + 1}`,
      source: "tool_verified",
      confidence: 0.9,
      evidenceRefs: [`tool:${readString(result.tool) ?? "unknown"}`],
      toolResultId: readString(result.id) ?? readString(result.tool) ?? null,
      staleness: "fresh",
      requiredForAnswer: true,
    });
  }

  if (readString(metadata.agentRunState) === "completed" || readBoolean(metadata.agentVerificationPassed)) {
    addClaim(claims, {
      id: "agent_verification",
      source: "tool_verified",
      confidence: 0.92,
      evidenceRefs: [readString(metadata.agentRunId) ? `agent_run:${readString(metadata.agentRunId)}` : "agent_run"],
      staleness: "fresh",
      requiredForAnswer: true,
    });
  }

  if ((readMetadataNumber(metadata, "modelCallCount") ?? 1) > 0 || readString(metadata.answerSource) === "model") {
    addClaim(claims, {
      id: "model_inference",
      source: "inference",
      confidence: inferBaseEvidenceConfidence(metadata),
      evidenceRefs: ["model_output"],
      staleness: "unknown",
      requiredForAnswer: false,
    });
  }

  const missingEvidence = context?.cognitiveContext?.uncertainty.missingEvidence ?? [];
  for (const [index, _item] of missingEvidence.slice(0, 8).entries()) {
    addClaim(claims, {
      id: `missing_cognitive_evidence_${index + 1}`,
      source: "missing",
      confidence: 0,
      evidenceRefs: [`missing:${index + 1}`],
      staleness: "unknown",
      requiredForAnswer: true,
    });
  }

  if (
    readString(metadata.evidenceSufficiency) === "weak" ||
    readString(metadata.dataConfidence) === "low" ||
    readString(metadata.dataConfidence) === "needs_clarification"
  ) {
    addClaim(claims, {
      id: "missing_external_evidence",
      source: "missing",
      confidence: 0.1,
      evidenceRefs: ["evidence_sufficiency"],
      staleness: "unknown",
      requiredForAnswer: true,
    });
  }

  if (
    readBoolean(metadata.needsClarification) ||
    context?.clarificationDiagnostics?.shouldClarify === true ||
    readString(metadata.evidenceSufficiency) === "ambiguous" ||
    ambiguityCount(input) > 0
  ) {
    addClaim(claims, {
      id: "missing_user_clarification",
      source: "missing",
      confidence: 0,
      evidenceRefs: ["clarification_required"],
      staleness: "unknown",
      requiredForAnswer: true,
    });
  }

  if (hasRequiredToolOpportunity(input) && !claims.some((claim) => claim.source === "tool_verified")) {
    addClaim(claims, {
      id: "missing_required_tool_evidence",
      source: "missing",
      confidence: 0.05,
      evidenceRefs: ["required_capability"],
      staleness: "unknown",
      requiredForAnswer: true,
    });
  }

  return claims;
}

function summarizeClaims(input: ClaimConfidenceInput, claims: ClaimRecord[]): ClaimLedger["summary"] {
  const sourceCounts: ClaimSourceCounts = {
    known_fact: 0,
    memory: 0,
    tool_verified: 0,
    inference: 0,
    missing: 0,
  };
  let confidenceSum = 0;
  let confidenceWeight = 0;
  let lowConfidenceClaims = 0;
  let missingEvidenceCount = 0;
  let verifiedEvidenceCount = 0;
  let contestedMemoryCount = 0;

  for (const claim of claims) {
    sourceCounts[claim.source] += 1;
    const weight = claim.requiredForAnswer ? 2 : 1;
    confidenceSum += claim.confidence * weight;
    confidenceWeight += weight;
    if (claim.confidence < 0.55) lowConfidenceClaims += 1;
    if (claim.source === "missing") missingEvidenceCount += 1;
    if (claim.source === "tool_verified") verifiedEvidenceCount += 1;
    if (claim.source === "memory" && claim.contested) contestedMemoryCount += 1;
  }

  const hasFailClosed =
    Boolean(input.routeDecision?.failClosedReason) ||
    readString(input.inferenceMetadata?.boundaryOutcome) === "security_blocked";
  const needsClarification =
    claims.some((claim) => claim.id === "missing_user_clarification") ||
    input.understandingContext?.clarificationDiagnostics?.shouldClarify === true;
  const needsTool =
    claims.some((claim) => claim.id === "missing_required_tool_evidence") ||
    (hasRequiredToolOpportunity(input) && verifiedEvidenceCount === 0);
  const hasContestedRequiredMemory = claims.some(
    (claim) => claim.source === "memory" && claim.contested && claim.requiredForAnswer,
  );
  const claimConfidence =
    confidenceWeight === 0 ? 0 : Math.max(0, Math.min(1, confidenceSum / confidenceWeight));
  const uncertaintyAction: UncertaintyAction = hasFailClosed
    ? "block_or_refuse"
    : needsClarification
      ? "ask_clarification"
      : needsTool
        ? "call_tool"
        : hasContestedRequiredMemory || missingEvidenceCount > 0 || claimConfidence < 0.55
          ? "limit_answer"
          : "answer";

  return {
    claimConfidence: Number(claimConfidence.toFixed(2)),
    claimSourceCounts: sourceCounts,
    lowConfidenceClaims,
    missingEvidenceCount,
    verifiedEvidenceCount,
    contestedMemoryCount,
    uncertaintyAction,
    selfCheckApplied: true,
    toolCalledForUncertainty: uncertaintyAction === "call_tool",
    clarificationRequested: uncertaintyAction === "ask_clarification",
  };
}

export function buildClaimLedger(input: ClaimConfidenceInput): ClaimLedger {
  const claims = buildClaims(input);
  return claimLedgerSchema.parse({
    version: "claim_confidence.v1",
    generatedAt: (input.now ?? new Date()).toISOString(),
    claims,
    summary: summarizeClaims(input, claims),
  });
}

export function buildClaimConfidenceMetadata(ledger: ClaimLedger): Record<string, unknown> {
  return {
    claimConfidenceVersion: ledger.version,
    claimConfidence: ledger.summary.claimConfidence,
    claimSourceCounts: ledger.summary.claimSourceCounts,
    uncertaintyAction: ledger.summary.uncertaintyAction,
    missingEvidenceCount: ledger.summary.missingEvidenceCount,
    verifiedEvidenceCount: ledger.summary.verifiedEvidenceCount,
    contestedMemoryCount: ledger.summary.contestedMemoryCount,
    lowConfidenceClaims: ledger.summary.lowConfidenceClaims,
    selfCheckApplied: ledger.summary.selfCheckApplied,
    toolCalledForUncertainty: ledger.summary.toolCalledForUncertainty,
    clarificationRequested: ledger.summary.clarificationRequested,
  };
}

export function buildClaimConfidenceRuntimeMetadata(
  app: ClaimConfidenceApp,
  ledger: ClaimLedger | null | undefined,
): Record<string, unknown> {
  if (!ledger || !shouldComputeClaimConfidence(app)) {
    return {};
  }
  return {
    ...buildClaimConfidenceMetadata(ledger),
    claimConfidenceMode: isClaimConfidenceV1Enabled(app) ? "enabled" : "shadow",
  };
}

export function isClaimConfidenceV1Enabled(app: ClaimConfidenceApp): boolean {
  return app.config?.ELYAN_CLAIM_CONFIDENCE_V1_ENABLED === true;
}

export function isClaimConfidenceShadowEnabled(app: ClaimConfidenceApp): boolean {
  return app.config?.ELYAN_CLAIM_CONFIDENCE_SHADOW_ENABLED === true;
}

export function shouldComputeClaimConfidence(app: ClaimConfidenceApp): boolean {
  return isClaimConfidenceV1Enabled(app) || isClaimConfidenceShadowEnabled(app);
}

export function applyClaimConfidenceMetadata(
  app: ClaimConfidenceApp,
  input: ClaimConfidenceInput & { metadata: Record<string, unknown> },
): Record<string, unknown> {
  if (!shouldComputeClaimConfidence(app)) {
    return input.metadata;
  }
  const ledger = buildClaimLedger({
    ...input,
    inferenceMetadata: input.metadata,
  });
  return {
    ...input.metadata,
    ...buildClaimConfidenceMetadata(ledger),
    claimConfidenceMode: isClaimConfidenceV1Enabled(app) ? "enabled" : "shadow",
  };
}

export function buildClaimConfidencePromptDirective(
  app: ClaimConfidenceApp,
  ledger: ClaimLedger,
): string | null {
  if (!isClaimConfidenceV1Enabled(app)) {
    return null;
  }
  const action = ledger.summary.uncertaintyAction;
  if (action === "answer") {
    return "Uncertainty directive: answer normally, but mark unsupported or inferred details as uncertain instead of presenting them as verified.";
  }
  if (action === "ask_clarification") {
    return "Uncertainty directive: required evidence is ambiguous. Ask one short clarification before making specific claims.";
  }
  if (action === "call_tool") {
    return "Uncertainty directive: the task needs tool or artifact evidence. Do not claim the work is done unless a typed tool result, artifact hash, or server read-back is present.";
  }
  if (action === "block_or_refuse") {
    return "Uncertainty directive: safety or privacy evidence is insufficient. Refuse or limit the answer without revealing hidden policy.";
  }
  return "Uncertainty directive: evidence is incomplete. Give a bounded answer and state the missing evidence briefly; do not fake certainty.";
}
