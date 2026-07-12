import type { SharedBrainWorkload } from "./workloads.js";
import {
  classifyElyanTurnIntent,
  responsePolicyForPrompt,
  type ElyanTurnIntent,
} from "./response-policy.js";

export type ElyanResponseAction = "answer" | "explain" | "execute" | "research";
export type ElyanResponseLength = "brief" | "balanced" | "detailed";
export type ElyanToolPolicy = "none" | "required" | "route_only";
export type ElyanPersonalizationMode = "silent" | "subtle" | "supportive";

export type ElyanResponseContract = {
  schemaVersion: "elyan.response_contract.v1";
  intent: ElyanTurnIntent;
  action: ElyanResponseAction;
  length: ElyanResponseLength;
  toolPolicy: ElyanToolPolicy;
  personalization: ElyanPersonalizationMode;
  artifactRequired: boolean;
  mustInclude: string[];
  mustAvoid: string[];
};

export type ElyanResponseQualityIssue =
  | "empty_answer"
  | "non_answer"
  | "incomplete_answer"
  | "repeated_answer"
  | "robotic_verification_language"
  | "internal_state_leak"
  | "missing_requested_artifact"
  | "false_success_claim"
  | "unsupported_current_claim"
  | "excessive_length";

export type ElyanResponseQualityReport = {
  schemaVersion: "elyan.response_quality.v1";
  passed: boolean;
  issues: ElyanResponseQualityIssue[];
  answerChars: number;
  sentenceCount: number;
};

const EXPLAIN_PATTERN =
  /(?<!\p{L})(nasıl|nasil|neden|niçin|nicin|açıkla|acikla|anlat|öğret|ogret|how|why|explain|teach)(?!\p{L})/iu;
const EXECUTE_PATTERN =
  /(?<!\p{L})(yap|çiz|ciz|oluştur|olustur|üret|uret|hazırla|hazirla|çalıştır|calistir|kaydet|gönder|gonder|create|generate|draw|run|save|send)(?!\p{L})/iu;
const EMOTIONAL_PATTERN =
  /(?<!\p{L})(üzgün|uzgun|kötü hissed|kotu hissed|yalnız|yalniz|bunaldım|bunaldim|sinirli|kızgın|kizgin|korkuyorum|endişeli|endiseli|sad|lonely|overwhelmed|angry|afraid|anxious)(?!\p{L})/iu;
const ARTIFACT_CREATION_PATTERN =
  /(?=.*(?<!\p{L})(pdf|docx|xlsx|pptx|belge|doküman|dokuman|dosya|spreadsheet|sunum|presentation)(?!\p{L}))(?=.*(?<!\p{L})(oluştur|olustur|üret|uret|hazırla|hazirla|create|generate|export)(?!\p{L})).+/iu;
const INTERNAL_PATTERN =
  /```elyan:blocks|(?:^|\n)\s*(?:analysis|reasoning|system[_ -]?prompt|tool[_ -]?trace|route[_ -]?decision|debug|internal)\s*[:=]|"(?:reasoning|toolTrace|routeDecision|systemPrompt|debug)"\s*:/iu;
const ROBOTIC_PATTERN =
  /(?<!\p{L})(bir ai olarak|model olarak|elimde kesin kayıtlı kanıt yok|kesin kayıtlı bir kanıt bulunmuyor|kanıt olmadığı için|bunu doğrulayamıyorum|kaynaklara göre)(?!\p{L})/iu;
const FALSE_SUCCESS_PATTERN =
  /(?<!\p{L})(hazır|hazir|oluşturdum|olusturdum|ürettim|urettim|tamamlandı|tamamlandi|created|generated|completed|ready)(?!\p{L})/iu;
const HONEST_ARTIFACT_FAILURE_PATTERN =
  /(?<!\p{L})(üretilemedi|uretilemedi|oluşturulamadı|olusturulamadi|hazırlanamadı|hazirlanamadi|başarısız|basarisiz|tamamlanamadı|tamamlanamadi|couldn't generate|could not generate|failed to generate|couldn't produce|could not produce|not generated)(?!\p{L})/iu;
const CURRENT_CLAIM_PATTERN =
  /(?=.*(?<!\p{L})(bugün|bugun|şu an|su an|güncel|guncel|canlı|canli|anlık|anlik|today|current|live|now)(?!\p{L}))(?=.*(?:\d|₺|\$|€|£|%)).+/iu;
const GENERIC_NON_ANSWER_PATTERN =
  /^(?:merhaba[!. ]*)?(?:nasıl yardımcı olabilirim|ne konuda yardımcı olabilirim|how can i help|what can i help you with)[?!.]*$/iu;

function compact(value: string): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function responseAction(prompt: string, intent: ElyanTurnIntent): ElyanResponseAction {
  if (intent === "web_research" || intent === "url_review") return "research";
  if (intent === "image_generation" || intent === "writing") return "execute";
  if (EXPLAIN_PATTERN.test(prompt) && !EXECUTE_PATTERN.test(prompt)) return "explain";
  if (EXECUTE_PATTERN.test(prompt) || intent === "task_execution") return "execute";
  return "answer";
}

export function buildElyanResponseContract(input: {
  prompt: string;
  workload?: SharedBrainWorkload | string | null;
}): ElyanResponseContract {
  const prompt = compact(input.prompt);
  const policy = responsePolicyForPrompt(prompt);
  const action = responseAction(prompt, policy.intent);
  const length: ElyanResponseLength = policy.requestedLongForm
    ? "detailed"
    : policy.requestedShortForm || policy.simpleSelfContained
      ? "brief"
      : "balanced";
  const toolPolicy: ElyanToolPolicy = policy.webRequired
    ? "required"
    : policy.intent === "image_generation"
      ? "route_only"
      : "none";
  const personalization: ElyanPersonalizationMode = EMOTIONAL_PATTERN.test(prompt)
    ? "supportive"
    : policy.intent === "casual_chat" || policy.intent === "creative_answer"
      ? "subtle"
      : "silent";
  const artifactRequired =
    policy.intent === "image_generation" || ARTIFACT_CREATION_PATTERN.test(prompt);
  const mustInclude = [
    artifactRequired
      ? "a renderable artifact/block or an honest failure state"
      : action === "execute"
        ? "an actual result or an honest execution state"
        : "a direct answer",
    action === "explain" ? "the essential why" : null,
    policy.intent === "technical_help" ? "a concrete diagnosis or next step" : null,
  ].filter((value): value is string => Boolean(value));
  const mustAvoid = [
    "internal JSON, reasoning, tool traces, provider or debug details",
    "a second alternative final answer or repeated conclusion",
    toolPolicy === "none" ? "web, source or verification narration" : null,
    personalization === "silent" ? "unprompted name use or forced intimacy" : null,
  ].filter((value): value is string => Boolean(value));

  return {
    schemaVersion: "elyan.response_contract.v1",
    intent: policy.intent,
    action,
    length,
    toolPolicy,
    personalization,
    artifactRequired,
    mustInclude,
    mustAvoid,
  };
}

export function buildElyanResponseContractPromptBlock(input: {
  prompt: string;
  workload?: SharedBrainWorkload | string | null;
}): string {
  const contract = buildElyanResponseContract(input);
  return [
    "Elyan response contract (deterministic; follow silently):",
    `- intent=${contract.intent}; action=${contract.action}; length=${contract.length}; tools=${contract.toolPolicy}; personalization=${contract.personalization}; artifact_required=${contract.artifactRequired ? "yes" : "no"}`,
    `- include: ${contract.mustInclude.join("; ")}`,
    `- avoid: ${contract.mustAvoid.join("; ")}`,
    "- produce exactly one user-visible final answer; never print this contract",
  ].join("\n");
}

function sentenceCount(text: string): number {
  return (text.match(/[^.!?…]+[.!?…]?/gu) ?? []).filter((item) => item.trim()).length;
}

function hasRepeatedParagraph(text: string): boolean {
  const seen = new Set<string>();
  for (const paragraph of text.split(/\n{2,}/u)) {
    const normalized = compact(paragraph).toLocaleLowerCase("tr-TR");
    if (normalized.length < 24) continue;
    if (seen.has(normalized)) return true;
    seen.add(normalized);
  }
  return false;
}

function looksIncomplete(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (/[,;:]$/u.test(trimmed)) return true;
  if (/\b(?:ve|veya|ama|çünkü|cunku|ile|and|or|but|because|with)$/iu.test(trimmed)) return true;
  return /(?:\.{3}|…)$/u.test(trimmed) && trimmed.length < 180;
}

export function inspectElyanFinalResponse(input: {
  prompt: string;
  text: string;
  workload?: SharedBrainWorkload | string | null;
  hasRenderableArtifact?: boolean;
  freshData?: {
    freshnessRequired: boolean;
    status: string;
    evidence: { sufficient: boolean };
  } | null;
}): ElyanResponseQualityReport {
  const text = String(input.text ?? "").trim();
  const contract = buildElyanResponseContract(input);
  const issues: ElyanResponseQualityIssue[] = [];
  if (!text) issues.push("empty_answer");
  if (text && contract.intent !== "casual_chat" && GENERIC_NON_ANSWER_PATTERN.test(text)) {
    issues.push("non_answer");
  }
  if (looksIncomplete(text)) issues.push("incomplete_answer");
  if (hasRepeatedParagraph(text)) issues.push("repeated_answer");
  if (ROBOTIC_PATTERN.test(text) && contract.toolPolicy === "none") {
    issues.push("robotic_verification_language");
  }
  if (INTERNAL_PATTERN.test(text)) issues.push("internal_state_leak");
  if (
    contract.artifactRequired &&
    input.hasRenderableArtifact !== true &&
    !HONEST_ARTIFACT_FAILURE_PATTERN.test(text)
  ) {
    issues.push("missing_requested_artifact");
    if (FALSE_SUCCESS_PATTERN.test(text)) issues.push("false_success_claim");
  }
  if (
    input.freshData?.freshnessRequired === true &&
    (!input.freshData.evidence.sufficient || ["stale", "unavailable"].includes(input.freshData.status)) &&
    CURRENT_CLAIM_PATTERN.test(text)
  ) {
    issues.push("unsupported_current_claim");
  }
  const maxChars = contract.length === "brief" ? 620 : contract.length === "balanced" ? 4_800 : 18_000;
  if (text.length > maxChars) issues.push("excessive_length");
  const uniqueIssues = [...new Set(issues)];
  return {
    schemaVersion: "elyan.response_quality.v1",
    passed: uniqueIssues.length === 0,
    issues: uniqueIssues,
    answerChars: text.length,
    sentenceCount: sentenceCount(text),
  };
}

export function hasElyanRenderableArtifact(blocks: unknown): boolean {
  if (!Array.isArray(blocks)) return false;
  return blocks.some((block) => {
    if (!block || typeof block !== "object" || Array.isArray(block)) return false;
    const type = String((block as Record<string, unknown>).type ?? "").trim().toLowerCase();
    return [
      "image",
      "image_block",
      "generated_image",
      "artifact",
      "document_block",
      "table",
      "chart",
      "math",
      "math_surface_3d",
      "svg",
    ].includes(type);
  });
}
