import {
  compileOutputContract,
  type OutputReference,
} from "./output-contract.js";

export type ConversationReferenceInput = {
  message: string;
  metadata?: Record<string, unknown> | null;
  conversation?: Array<{ role?: string; content?: string | null }>;
  sessionArtifacts?: Array<Record<string, unknown>>;
};

export type ConversationReferenceResolution = {
  sourceReference: OutputReference;
  sourceText: string | null;
  artifactId: string | null;
  confidence: number;
};

function compact(value: unknown, max = 2_000): string | null {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text ? text.slice(0, max) : null;
}

function latestAssistantText(
  conversation: ConversationReferenceInput["conversation"],
): string | null {
  return [...(conversation ?? [])]
    .reverse()
    .find((item) => item?.role === "assistant" && compact(item.content))
    ?.content?.replace(/\s+/g, " ")
    .trim()
    .slice(0, 2_000) ?? null;
}

function latestArtifact(
  artifacts: ConversationReferenceInput["sessionArtifacts"],
): Record<string, unknown> | null {
  return artifacts?.find((item) => item && typeof item === "object") ?? null;
}

export function resolveConversationReference(
  input: ConversationReferenceInput,
): ConversationReferenceResolution {
  const artifact = latestArtifact(input.sessionArtifacts);
  const contract = compileOutputContract({
    message: input.message,
    metadata: {
      ...(input.metadata ?? {}),
      hasLatestArtifact: artifact != null,
    },
  });
  if (contract.sourceReference === "latest_artifact" && artifact) {
    return {
      sourceReference: "latest_artifact",
      sourceText:
        compact(artifact.revisedPrompt) ??
        compact(artifact.prompt) ??
        compact(artifact.previewText) ??
        compact(artifact.name),
      artifactId: compact(artifact.id, 160),
      confidence: Math.max(0.76, contract.confidence),
    };
  }
  if (contract.sourceReference === "previous_answer") {
    return {
      sourceReference: "previous_answer",
      sourceText: latestAssistantText(input.conversation),
      artifactId: null,
      confidence: contract.confidence,
    };
  }
  return {
    sourceReference: contract.sourceReference,
    sourceText: contract.sourceReference === "current_prompt" ? compact(input.message) : null,
    artifactId: null,
    confidence: contract.confidence,
  };
}
