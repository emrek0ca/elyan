import type { UnderstandingEnvelope } from "../../core/understanding/types.js";

export type SemanticResponseGateInput = {
  prompt: string;
  text: string;
  blocks?: unknown;
  workload?: string | null;
  turnKind?: string | null;
  priorAssistant?: {
    visibleSummary?: string | null;
    blockTypes?: string[];
  } | null;
  understandingEnvelope?: UnderstandingEnvelope | null;
  evidence?: {
    webGroundingUsed?: boolean;
    webSourceCount?: number;
    toolCallCount?: number;
    verifiedEvidenceCount?: number;
    artifactEvidence?: boolean;
    agentVerified?: boolean;
    retrievalLowConfidence?: boolean;
    knowledgeEvidenceState?: "none" | "verified" | "insufficient";
  };
};

export type SemanticResponseGateResult = {
  accepted: boolean;
  reason: string | null;
  evidenceState: "none" | "verified" | "insufficient";
  outputContract: string;
};

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function clean(value: unknown, max = 8_000): string {
  return typeof value === "string"
    ? value.replace(/\s+/g, " ").trim().slice(0, max)
    : "";
}

function normalized(value: unknown): string {
  return clean(value)
    .toLocaleLowerCase("tr-TR")
    .replace(/[\p{P}\p{S}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function blockTypes(value: unknown): string[] {
  return (Array.isArray(value) ? value : [])
    .map(record)
    .filter((item): item is Record<string, unknown> => item != null)
    .map((item) => String(item.type ?? "").trim().toLowerCase())
    .filter(Boolean);
}

function hasExplicitArtifactContract(
  envelope: UnderstandingEnvelope | null | undefined,
): boolean {
  if (!envelope) return false;
  if (envelope.output_contract?.requiresArtifact === true) return true;
  return envelope.desired_outputs.some(
    (output) => output.kind !== "chat_reply" && output.confidence >= 0.58,
  );
}

function isChatReplyExpected(input: SemanticResponseGateInput): boolean {
  if (hasExplicitArtifactContract(input.understandingEnvelope)) return false;
  const workload = String(input.workload ?? "").toLowerCase();
  return (
    workload.includes("chat") ||
    workload === "fast_route" ||
    workload === "shared_brain" ||
    workload === "mobile_chat_deep_refine" ||
    workload === ""
  );
}

function hasUnsupportedSourceClaim(text: string): boolean {
  const value = normalized(text);
  if (!value) return false;
  return (
    /kaynak doğrulaması yapılamadığı için/.test(value) ||
    /kaynak doğrulanamadığı için/.test(value) ||
    /belge oluşturmadım/.test(value) ||
    /document (was )?not created/.test(value) ||
    /could not verify (the )?source/.test(value)
  );
}

function repeatsPriorAnswer(
  text: string,
  priorAssistant: SemanticResponseGateInput["priorAssistant"],
): boolean {
  const current = normalized(text);
  const previous = normalized(priorAssistant?.visibleSummary);
  if (!current || !previous || current.length < 48 || previous.length < 48) {
    return false;
  }
  return current === previous || current.includes(previous) || previous.includes(current);
}

function hasUnverifiedCompletionClaim(input: SemanticResponseGateInput): boolean {
  const value = normalized(input.text);
  const actionWorkload = /planning|document|desktop|automation|action|task/.test(
    String(input.workload ?? "").toLowerCase(),
  );
  if (!actionWorkload) return false;
  if (!/(tamamlandı|tamamlandi|oluşturuldu|olusturuldu|yapıldı|yapildi|completed|created|done)/u.test(value)) {
    return false;
  }
  const evidence = input.evidence ?? {};
  return !(
    evidence.artifactEvidence === true ||
    (evidence.toolCallCount ?? 0) > 0 ||
    (evidence.verifiedEvidenceCount ?? 0) > 0 ||
    evidence.agentVerified === true
  );
}

function hasDoneGoalWithoutEvidence(input: SemanticResponseGateInput): boolean {
  const done = (Array.isArray(input.blocks) ? input.blocks : [])
    .map(record)
    .filter((item): item is Record<string, unknown> => item != null)
    .filter((item) => String(item.type ?? "").toLowerCase() === "goal_progress")
    .some((item) => {
      const data = record(item.data) ?? item;
      return data.done === true;
    });
  if (!done) return false;
  const evidence = input.evidence ?? {};
  return !(
    evidence.artifactEvidence === true ||
    (evidence.toolCallCount ?? 0) > 0 ||
    (evidence.verifiedEvidenceCount ?? 0) > 0 ||
    evidence.agentVerified === true
  );
}

function hasSpecificFactualClaim(text: string): boolean {
  const value = clean(text);
  return (
    /\d/u.test(value) ||
    /(?<!\p{L})[A-ZÇĞİÖŞÜ][\p{L}'’.-]{2,}\s+[A-ZÇĞİÖŞÜ][\p{L}'’.-]{2,}(?!\p{L})/u.test(
      value,
    )
  );
}

function isEvidenceLimitationResponse(text: string): boolean {
  const value = normalized(text);
  return /(?:doğrulanmış|dogrulanmis|yeterli|güvenilir|guvenilir)\s+(?:kanıt|kanit|kaynak|veri).{0,36}(?:yok|bulamadım|bulamadim|ulaşılamadı|ulasilamadi)|(?:kanıt|kanit|kaynak|veri).{0,36}(?:yetersiz|bulunamadı|bulunamadi)/u.test(
    value,
  );
}

export function evaluateSemanticResponseGate(
  input: SemanticResponseGateInput,
): SemanticResponseGateResult {
  const types = blockTypes(input.blocks);
  const evidence = input.evidence ?? {};
  const hasWebEvidence =
    evidence.webGroundingUsed === true || (evidence.webSourceCount ?? 0) > 0;
  const chatExpected = isChatReplyExpected(input);
  const outputContract = hasExplicitArtifactContract(input.understandingEnvelope)
    ? String(
        input.understandingEnvelope?.output_contract?.outputKind ?? "artifact",
      )
    : "chat_reply";
  const evidenceState = evidence.knowledgeEvidenceState === "insufficient"
    ? "insufficient"
    : evidence.knowledgeEvidenceState === "verified"
      ? "verified"
      : evidence.retrievalLowConfidence === true
    ? "insufficient"
    : hasWebEvidence || (evidence.verifiedEvidenceCount ?? 0) > 0
      ? "verified"
      : evidence.toolCallCount || evidence.artifactEvidence
        ? "insufficient"
        : "none";

  let reason: string | null = null;
  if (chatExpected && types.some((type) => ["document_block", "document_block_skeleton"].includes(type))) {
    reason = "chat_output_contract_document_block";
  } else if (
    evidenceState === "insufficient" &&
    types.some((type) => ["web_search", "table", "chart"].includes(type))
  ) {
    reason = "low_confidence_retrieval_structured_claim";
  } else if (
    evidence.knowledgeEvidenceState === "insufficient" &&
    hasSpecificFactualClaim(input.text) &&
    !isEvidenceLimitationResponse(input.text)
  ) {
    reason = "required_evidence_missing_for_factual_claim";
  } else if (types.includes("web_search") && !hasWebEvidence) {
    reason = "web_block_without_evidence";
  } else if (hasUnsupportedSourceClaim(input.text) && !hasWebEvidence) {
    reason = "unsupported_source_or_document_claim";
  } else if (input.turnKind === "correction" && repeatsPriorAnswer(input.text, input.priorAssistant)) {
    reason = "correction_repeated_prior_answer";
  } else if (hasUnverifiedCompletionClaim(input)) {
    reason = "completion_claim_without_evidence";
  } else if (hasDoneGoalWithoutEvidence(input)) {
    reason = "goal_done_without_verification";
  } else {
    const ids = (Array.isArray(input.blocks) ? input.blocks : [])
      .map(record)
      .filter((item): item is Record<string, unknown> => item != null)
      .map((item) => String(item.blockId ?? item.stableBlockId ?? "").trim())
      .filter(Boolean);
    if (new Set(ids).size !== ids.length) reason = "duplicate_block_id";
  }

  return {
    accepted: reason == null,
    reason,
    evidenceState,
    outputContract,
  };
}
