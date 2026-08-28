import type { OutputContract } from "../../core/understanding/output-contract.js";
import type { IntentClassification } from "../../core/understanding/types.js";

export const KNOWLEDGE_NEED_CONTRACT = "elyan.knowledge_need.v1" as const;

export type KnowledgeNeedSource =
  | "conversation_reference"
  | "memory"
  | "private_corpus"
  | "public_web";

export type KnowledgeNeed = {
  contract: typeof KNOWLEDGE_NEED_CONTRACT;
  need: "none" | "optional" | "required";
  sources: KnowledgeNeedSource[];
  freshness: "none" | "stable" | "current";
  query: {
    subject: string | null;
    entities: string[];
    subquestions: string[];
  };
  reason: string;
};

type KnowledgeClassification = Pick<
  IntentClassification,
  "primaryIntent" | "requiresRetrieval" | "requiresCitation" | "reason"
>;

export function resolveKnowledgeEvidenceState(input: {
  knowledgeNeed: KnowledgeNeed;
  referenceAvailable: boolean;
  memoryResultCount: number;
  retrievalEvidenceState: "none" | "verified" | "insufficient";
  webEvidenceSufficient: boolean;
}): "none" | "verified" | "insufficient" {
  const sourceSatisfied = input.knowledgeNeed.sources.some((source) => {
    if (source === "conversation_reference") return input.referenceAvailable;
    if (source === "memory") return input.memoryResultCount > 0;
    if (source === "private_corpus") return input.retrievalEvidenceState === "verified";
    return input.webEvidenceSufficient;
  });
  if (input.knowledgeNeed.need === "none") return "none";
  if (sourceSatisfied) return "verified";
  return input.knowledgeNeed.need === "required" ? "insufficient" : "none";
}

function compact(value: unknown, max = 500): string {
  const text = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  return text.slice(0, max);
}

function unique(values: readonly unknown[], max: number): string[] {
  return [...new Set(values.map((value) => compact(value, 240)).filter(Boolean))].slice(0, max);
}

export function deriveKnowledgeNeed(input: {
  query: string;
  subject?: string | null;
  entities?: readonly string[];
  subquestions?: readonly string[];
  classification?: KnowledgeClassification | null;
  outputContract?: OutputContract | null;
  referenceAvailable: boolean;
  socialTurn: boolean;
  freshPublicDataRequired: boolean;
  publicWebExplicitlyRequired: boolean;
  attachmentContextUsed: boolean;
}): KnowledgeNeed {
  const query = compact(input.query);
  const queryShape = {
    subject: compact(input.subject, 300) || null,
    entities: unique(input.entities ?? [], 8),
    subquestions: unique(input.subquestions?.length ? input.subquestions : [query], 4),
  };
  const output = input.outputContract;
  const sourceReference = output?.sourceReference ?? "none";
  const referencedTurn =
    input.referenceAvailable &&
    (sourceReference === "previous_answer" || sourceReference === "latest_artifact");
  if (referencedTurn && !input.freshPublicDataRequired && !input.publicWebExplicitlyRequired) {
    return {
      contract: KNOWLEDGE_NEED_CONTRACT,
      need: "required",
      sources: ["conversation_reference"],
      freshness: "none",
      query: queryShape,
      reason: "authoritative_conversation_reference",
    };
  }
  if (input.socialTurn || input.attachmentContextUsed) {
    return {
      contract: KNOWLEDGE_NEED_CONTRACT,
      need: "none",
      sources: [],
      freshness: "none",
      query: queryShape,
      reason: input.socialTurn ? "social_turn" : "attachment_is_authority",
    };
  }
  const selfContainedStructuredInput =
    sourceReference === "current_prompt" &&
    (output?.outputKind === "table" || output?.outputKind === "chart") &&
    !input.freshPublicDataRequired &&
    !input.publicWebExplicitlyRequired;
  if (selfContainedStructuredInput) {
    return {
      contract: KNOWLEDGE_NEED_CONTRACT,
      need: "none",
      sources: [],
      freshness: "none",
      query: queryShape,
      reason: "self_contained_structured_input",
    };
  }
  if (input.freshPublicDataRequired || input.publicWebExplicitlyRequired) {
    return {
      contract: KNOWLEDGE_NEED_CONTRACT,
      need: "required",
      sources: ["public_web"],
      freshness: "current",
      query: queryShape,
      reason: "fresh_public_evidence_required",
    };
  }
  const classification = input.classification;
  if (classification?.reason === "user_identity_query") {
    return {
      contract: KNOWLEDGE_NEED_CONTRACT,
      need: "required",
      sources: ["memory"],
      freshness: "stable",
      query: queryShape,
      reason: "current_user_memory_required",
    };
  }
  if (
    classification?.primaryIntent === "research" ||
    classification?.requiresRetrieval === true ||
    classification?.requiresCitation === true
  ) {
    return {
      contract: KNOWLEDGE_NEED_CONTRACT,
      need: "required",
      sources: ["private_corpus", "public_web"],
      freshness: "stable",
      query: queryShape,
      reason: "factual_evidence_required",
    };
  }
  if (
    classification?.primaryIntent === "document" ||
    classification?.primaryIntent === "writing"
  ) {
    return {
      contract: KNOWLEDGE_NEED_CONTRACT,
      need: "optional",
      sources: ["private_corpus"],
      freshness: "stable",
      query: queryShape,
      reason: "optional_corpus_context",
    };
  }
  return {
    contract: KNOWLEDGE_NEED_CONTRACT,
    need: "none",
    sources: [],
    freshness: "none",
    query: queryShape,
    reason: "self_contained_turn",
  };
}
