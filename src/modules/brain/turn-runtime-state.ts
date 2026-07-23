export type TurnRuntimeStateInput = {
  prompt: string;
  conversation?: Array<{ role?: string; content?: string | null }>;
  requestMetadata?: Record<string, unknown> | null;
  route?: string | null;
  workload?: string | null;
  taskId?: string | null;
};

type SessionArtifact = {
  id: string;
  type: string;
  name: string;
  prompt?: string;
};

type ReferenceResolution = {
  mode: "new_topic" | "follow_up";
  operation:
    | "answer"
    | "continue"
    | "revise"
    | "image_variation"
    | "style_transfer"
    | "document_revision";
  target: "none" | "last_assistant" | "last_artifact";
  mustUseTarget: boolean;
  preserve: string[];
  change: string[];
};

const REFERENTIAL_RE =
  /\b(bunu|şunu|sunu|onu|son|önceki|onceki|aynı|ayni|hayır|hayir|hani|devam|daha|başka|baska|farklı|farkli|renkte|sinematik|beyaz|siyah|mavi|kırmızı|kirmizi)\b/iu;

const IMAGE_FOLLOWUP_RE =
  /\b(görsel|gorsel|resim|fotoğraf|fotograf|çiz|ciz|renk|renkte|sinematik|cinematic|beyaz|siyah|mavi|kırmızı|kirmizi|stil|tarz)\b/iu;

const DOCUMENT_FOLLOWUP_RE =
  /\b(belge|dilekçe|dilekce|rapor|metin|yazı|yazi|paragraf|taslak|pdf|docx)\b/iu;

const GREETING_ONLY_RE =
  /^\s*(?:selam|merhaba|mrb|hey|hi|hello|naber)(?:\s+(?:elyan|nasılsın|nasilsin|ne\s+haber))?[\s?!.,]*$/iu;

function cleanText(value: unknown, max = 360): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.replace(/\s+/g, " ").trim();
  return cleaned ? cleaned.slice(0, max) : null;
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function readArtifacts(metadata: Record<string, unknown> | null): SessionArtifact[] {
  return readArray(metadata?.sessionArtifacts)
    .map(readRecord)
    .filter((item): item is Record<string, unknown> => item != null)
    .map((item, index) => {
      const type =
        cleanText(item.artifactType, 80) ??
        cleanText(item.type, 80) ??
        cleanText(item.contentFamily, 80) ??
        "artifact";
      return {
        id: cleanText(item.id, 120) ?? `recent_${index + 1}`,
        type: type.toLowerCase(),
        name: cleanText(item.name, 160) ?? "untitled",
        prompt:
          cleanText(item.revisedPrompt, 420) ??
          cleanText(item.prompt, 420) ??
          cleanText(item.previewText, 420) ??
          undefined,
      };
    })
    .slice(0, 6);
}

function latestByRole(
  conversation: TurnRuntimeStateInput["conversation"],
  role: "user" | "assistant",
): string | null {
  return [...(conversation ?? [])]
    .reverse()
    .find((item) => item?.role === role && cleanText(item.content, 260))
    ?.content?.replace(/\s+/g, " ")
    .trim()
    .slice(0, 260) ?? null;
}

function resolveReference(prompt: string, artifacts: SessionArtifact[]): ReferenceResolution {
  const normalized = prompt.replace(/\s+/g, " ").trim();
  const shortPrompt = normalized.split(/\s+/).filter(Boolean).length <= 6;
  const greetingOnly = GREETING_ONLY_RE.test(normalized);
  const isReferential = !greetingOnly && (shortPrompt || REFERENTIAL_RE.test(normalized));
  const latestArtifact = artifacts[0];
  const latestIsImage =
    latestArtifact?.type === "image" || latestArtifact?.type === "hosted_image";
  const latestIsDocument = ["document", "pdf", "docx", "text"].includes(
    latestArtifact?.type ?? "",
  );

  if (isReferential && latestIsImage && IMAGE_FOLLOWUP_RE.test(normalized)) {
    const styleChange = /\b(sinematik|cinematic|stil|tarz|gerçekçi|gercekci)\b/iu.test(
      normalized,
    );
    return {
      mode: "follow_up",
      operation: styleChange ? "style_transfer" : "image_variation",
      target: "last_artifact",
      mustUseTarget: true,
      preserve: ["main_subject", "composition", "intent", "session_continuity"],
      change: [normalized],
    };
  }

  if (isReferential && latestIsDocument && DOCUMENT_FOLLOWUP_RE.test(normalized)) {
    return {
      mode: "follow_up",
      operation: "document_revision",
      target: "last_artifact",
      mustUseTarget: true,
      preserve: ["document_purpose", "facts", "structure"],
      change: [normalized],
    };
  }

  if (isReferential) {
    return {
      mode: "follow_up",
      operation: /\b(devam|sürdür|surdur)\b/iu.test(normalized)
        ? "continue"
        : "revise",
      target: latestArtifact ? "last_artifact" : "last_assistant",
      mustUseTarget: true,
      preserve: ["topic", "user_goal", "prior_answer"],
      change: [normalized],
    };
  }

  return {
    mode: "new_topic",
    operation: "answer",
    target: "none",
    mustUseTarget: false,
    preserve: [],
    change: [normalized],
  };
}

export function buildTurnRuntimeStatePromptBlock(
  input: TurnRuntimeStateInput,
): string | null {
  const metadata = readRecord(input.requestMetadata);
  const artifacts = readArtifacts(metadata);
  const reference = resolveReference(input.prompt, artifacts);
  const lastUser = latestByRole(input.conversation, "user");
  const lastAssistant = latestByRole(input.conversation, "assistant");
  const latestArtifact = artifacts[0];
  const lines = [
    "[TURN_RUNTIME_STATE]",
    `self: route=${input.route ?? "shared_brain"}; workload=${input.workload ?? "unknown"}; task=${input.taskId ?? "none"}; has_last_artifact=${latestArtifact ? "yes" : "no"}`,
    `reference: mode=${reference.mode}; operation=${reference.operation}; target=${reference.target}; must_use_target=${reference.mustUseTarget ? "yes" : "no"}`,
    reference.preserve.length
      ? `preserve: ${reference.preserve.join(", ")}`
      : null,
    reference.change.length ? `requested_change: ${reference.change[0]}` : null,
    lastUser ? `last_user: ${lastUser}` : null,
    lastAssistant ? `last_assistant: ${lastAssistant}` : null,
    latestArtifact
      ? `latest_artifact: id=${latestArtifact.id}; type=${latestArtifact.type}; name=${latestArtifact.name}${latestArtifact.prompt ? `; prompt=${latestArtifact.prompt}` : ""}`
      : null,
    artifacts.length > 1
      ? `recent_artifacts: ${artifacts
          .slice(1, 4)
          .map((item) => `${item.id}/${item.type}/${item.name}`)
          .join(" | ")}`
      : null,
    "context_priority: current user message > turn runtime state > latest session artifact > recent turns > rolling summary > long-term memory.",
    "rule: if must_use_target=yes, do not answer as a fresh standalone task; keep the previous subject/data and apply only requested_change.",
  ].filter((line): line is string => Boolean(line));

  return lines.length > 2 ? lines.join("\n") : null;
}
