import type { OutputContract } from "../../core/understanding/output-contract.js";
import type { IntentClassification } from "../../core/understanding/types.js";

export const KNOWLEDGE_NEED_CONTRACT = "elyan.knowledge_need.v2" as const;

export type KnowledgeNeedSource =
  | "none"
  | "conversation"
  | "memory"
  | "provider"
  | "corpus"
  | "web";

export type KnowledgeNeedFallback = "none" | "model" | "web" | "abstain";

export type KnowledgeNeed = {
  contract: typeof KNOWLEDGE_NEED_CONTRACT;
  source: KnowledgeNeedSource;
  freshness: "none" | "stable" | "current";
  evidenceRequired: boolean;
  fallback: KnowledgeNeedFallback;
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
  providerEvidenceSufficient: boolean;
  retrievalEvidenceState: "none" | "verified" | "insufficient";
  webEvidenceSufficient: boolean;
}): "none" | "verified" | "insufficient" {
  const sourceSatisfied =
    input.knowledgeNeed.source === "conversation"
      ? input.referenceAvailable
      : input.knowledgeNeed.source === "memory"
        ? input.memoryResultCount > 0
        : input.knowledgeNeed.source === "provider"
          ? input.providerEvidenceSufficient
          : input.knowledgeNeed.source === "corpus"
            ? input.retrievalEvidenceState === "verified"
            : input.knowledgeNeed.source === "web"
              ? input.webEvidenceSufficient
              : true;
  if (input.knowledgeNeed.source === "none") return "none";
  if (sourceSatisfied) return "verified";
  return input.knowledgeNeed.evidenceRequired ? "insufficient" : "none";
}

function compact(value: unknown, max = 500): string {
  const text = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
  return text.slice(0, max);
}

function unique(values: readonly unknown[], max: number): string[] {
  return [...new Set(values.map((value) => compact(value, 240)).filter(Boolean))].slice(0, max);
}

function result(input: {
  source: KnowledgeNeedSource;
  freshness: KnowledgeNeed["freshness"];
  evidenceRequired: boolean;
  fallback: KnowledgeNeedFallback;
  query: KnowledgeNeed["query"];
  reason: string;
}): KnowledgeNeed {
  return { contract: KNOWLEDGE_NEED_CONTRACT, ...input };
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
  providerAvailable?: boolean;
  corpusAvailable?: boolean;
  multiSourceResearch?: boolean;
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
    return result({
      source: "conversation",
      freshness: "none",
      evidenceRequired: true,
      fallback: "abstain",
      query: queryShape,
      reason: "authoritative_conversation_reference",
    });
  }
  if (input.socialTurn || input.attachmentContextUsed) {
    return result({
      source: "none",
      freshness: "none",
      evidenceRequired: false,
      fallback: "model",
      query: queryShape,
      reason: input.socialTurn ? "social_turn" : "attachment_is_authority",
    });
  }
  const selfContainedStructuredInput =
    sourceReference === "current_prompt" &&
    (output?.outputKind === "table" || output?.outputKind === "chart") &&
    !input.freshPublicDataRequired &&
    !input.publicWebExplicitlyRequired;
  if (selfContainedStructuredInput) {
    return result({
      source: "none",
      freshness: "none",
      evidenceRequired: false,
      fallback: "model",
      query: queryShape,
      reason: "self_contained_structured_input",
    });
  }
  if (input.classification?.reason === "user_identity_query") {
    return result({
      source: "memory",
      freshness: "stable",
      evidenceRequired: true,
      fallback: "abstain",
      query: queryShape,
      reason: "current_user_memory_required",
    });
  }
  if (input.providerAvailable) {
    return result({
      source: "provider",
      freshness: input.freshPublicDataRequired ? "current" : "stable",
      evidenceRequired: true,
      fallback: input.freshPublicDataRequired ? "web" : "abstain",
      query: queryShape,
      reason: "typed_provider_selected",
    });
  }
  if (input.corpusAvailable && !input.freshPublicDataRequired) {
    return result({
      source: "corpus",
      freshness: "stable",
      evidenceRequired: false,
      fallback: "model",
      query: queryShape,
      reason: "stable_corpus_selected",
    });
  }
  if (
    input.freshPublicDataRequired ||
    input.publicWebExplicitlyRequired ||
    input.multiSourceResearch
  ) {
    return result({
      source: "web",
      freshness: input.freshPublicDataRequired ? "current" : "stable",
      evidenceRequired: true,
      fallback: "abstain",
      query: queryShape,
      reason: input.multiSourceResearch
        ? "multi_source_research_required"
        : "public_web_evidence_required",
    });
  }
  return result({
    source: "none",
    freshness: "none",
    evidenceRequired: false,
    fallback: "model",
    query: queryShape,
    reason: "self_contained_or_model_knowledge",
  });
}
