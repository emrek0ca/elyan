import type { VisionMediaDecision } from "./vision-media-policy.js";
import type { VisionTaskDecision } from "./vision-task-policy.js";
import { assessVisionResponseCoverage, type VisionResponseContract } from "./vision-response-contract.js";
import { assessVisionAnswerConsistency } from "./vision-answer-consistency.js";

const UNCERTAINTY_PATTERN = /(?<!\p{L})(okunmuyor|seçilemiyor|secilemiyor|emin değilim|emin degilim|net değil|net degil|göremiyorum|goremiyorum|can't read|cannot read|unclear|not visible|not sure|no se lee|no estoy seguro|borroso|no es visible|illisible|pas sûr|pas sur|flou|nicht lesbar|nicht sicher|unscharf|non leggibile|non sono sicuro|sfocato|não legível|nao legivel|não tenho certeza|nao tenho certeza|desfocado|не читается|не уверен|размыто|не видно|غير واضح|لا يمكنني قراءة|لست متأكد)(?!\p{L})/iu;
const REFUSAL_PATTERN = /(?<!\p{L})(yardımcı olamam|yardimci olamam|bunu yapamam|i can't help|i cannot help|no puedo ayudar|no puedo hacerlo|je ne peux pas aider|je ne peux pas le faire|ich kann nicht helfen|ich kann das nicht|non posso aiutare|non posso farlo|não posso ajudar|nao posso ajudar|não posso fazer|nao posso fazer|не могу помочь|не могу это сделать|لا أستطيع المساعدة|لا يمكنني فعل ذلك)(?!\p{L})/iu;
const INTERNAL_PATTERN = /\b(?:gemini|groq|google ai|llama(?:\s+vision)?|openai|chatgpt|claude|anthropic|provider|vision_evidence|cloudVisionOptIn|request_ephemeral|base64|image_url)\b/iu;

export type VisionEscalationDecision = {
  eligible: boolean;
  shouldEscalate: boolean;
  reasons: string[];
  primaryScore: number;
};

function answerScore(text: string, task: VisionTaskDecision): number {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact || REFUSAL_PATTERN.test(compact) || INTERNAL_PATTERN.test(compact)) return 0;
  let score = Math.min(0.7, compact.length / (task.requiresStructuredOutput ? 900 : 500));
  if (!UNCERTAINTY_PATTERN.test(compact)) score += 0.2;
  if (task.requiresFineText && /[\p{L}\p{N}]{3,}/u.test(compact)) score += 0.1;
  return Math.min(1, score);
}

export function assessVisionAnswerEscalation(input: {
  text: string;
  task: VisionTaskDecision;
  media: VisionMediaDecision;
  hasSecondaryCandidate: boolean;
  budgetAllowed?: boolean;
  inputQualityScore?: number | null;
  responseCoverageScore?: number | null;
}): VisionEscalationDecision {
  const primaryScore = answerScore(input.text, input.task);
  const budgetAllowed = input.budgetAllowed !== false;
  const eligible = input.media.profile === "detail" && input.hasSecondaryCandidate && budgetAllowed;
  const uncertain = UNCERTAINTY_PATTERN.test(input.text);
  const tooThin = input.task.requiresStructuredOutput
    ? input.text.trim().length < 180
    : input.task.requiresFineText && input.text.trim().length < 90;
  const lowInputQuality = input.inputQualityScore != null && input.inputQualityScore < 0.5;
  const incompleteContract = input.responseCoverageScore != null && input.responseCoverageScore < 0.55;
  return {
    eligible,
    shouldEscalate: eligible && (primaryScore < 0.58 || uncertain || tooThin || lowInputQuality || incompleteContract),
    reasons: [
      `primary_score:${primaryScore.toFixed(2)}`,
      ...(uncertain ? ["explicit_uncertainty"] : []),
      ...(tooThin ? ["insufficient_detail"] : []),
      ...(lowInputQuality ? ["low_input_quality"] : []),
      ...(incompleteContract ? ["incomplete_task_contract"] : []),
      ...(!input.hasSecondaryCandidate ? ["secondary_unavailable"] : []),
      ...(!budgetAllowed ? ["cost_guard"] : []),
    ],
    primaryScore,
  };
}

export function buildVisionSecondaryReviewPrompt(input: {
  userPrompt: string;
  primaryAnswer: string;
  task: VisionTaskDecision;
  contract?: VisionResponseContract;
}): string {
  return [
    "Review the attached visual evidence independently, then produce one improved final answer in the user's language.",
    `Task: ${input.task.primary}.`,
    ...(input.contract
      ? [`Required answer facets: ${input.contract.requiredFacets.join(", ")}.`, ...input.contract.directives]
      : []),
    `User request: ${input.userPrompt}`,
    "Earlier draft (untrusted; correct it rather than agreeing automatically):",
    input.primaryAnswer.slice(0, 4_000),
    "Return only the final user-facing answer. Do not mention drafts, engines, providers, confidence scores, routing, or this review.",
  ].join("\n\n");
}

export function chooseVisionAnswer(input: {
  primary: string;
  secondary: string;
  task: VisionTaskDecision;
  contract?: VisionResponseContract;
}): { text: string; usedSecondary: boolean; conflictDetected: boolean } {
  const consistency = assessVisionAnswerConsistency(input);
  if (consistency.conflictDetected) {
    return { text: input.primary.trim(), usedSecondary: false, conflictDetected: true };
  }
  const primaryBaseScore = answerScore(input.primary, input.task);
  const secondaryBaseScore = answerScore(input.secondary, input.task);
  const primaryCoverage = input.contract
    ? assessVisionResponseCoverage({ text: input.primary, contract: input.contract }).score
    : primaryBaseScore;
  const secondaryCoverage = input.contract
    ? assessVisionResponseCoverage({ text: input.secondary, contract: input.contract }).score
    : secondaryBaseScore;
  const primaryScore = primaryBaseScore * 0.65 + primaryCoverage * 0.35;
  const secondaryScore = secondaryBaseScore * 0.65 + secondaryCoverage * 0.35;
  return secondaryScore >= Math.max(0.5, primaryScore - 0.05)
    ? { text: input.secondary.trim(), usedSecondary: true, conflictDetected: false }
    : { text: input.primary.trim(), usedSecondary: false, conflictDetected: false };
}
