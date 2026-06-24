import type { CommandRouteDecision } from "../routing-policy/service.js";
import {
  containsProtectedElyanDisclosure,
  ELYAN_PUBLIC_IDENTITY_TEXT,
  ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT,
} from "../../lib/elyan-public-identity.js";
import {
  buildClarificationPrompt,
  isMateriallyAmbiguousUserPrompt,
} from "./chat-heuristics.js";

export type BrainBoundaryGateResult = {
  triggered: boolean;
  answerSource: "backend_gate";
  text: string;
  gateRuleIds: string[];
  boundaryOutcome:
    | "pairing_required"
    | "desktop_required"
    | "clarification_required"
    | "protected_internal_configuration"
    | "verified_identity";
  failureType: string;
  enforcedByBackend: true;
  responseCode:
    | "pairing_required"
    | "desktop_required"
    | "unsupported_runtime"
    | "clarification_required"
    | "protected_internal_configuration"
    | "verified_identity";
  modelAnswerSkipped: true;
};

const INTERNAL_DISCLOSURE_PATTERNS = [
  /\b(system|developer|hidden|internal)\s+(prompt|instruction|message|configuration|config)\b/i,
  /\b(sistem|geliştirici|gizli|dahili|iç)\s+(prompt(?:u|unu)?|talimat(?:ı|ları|larını)?|mesaj(?:ı|ını)?|yapılandırma(?:yı|sını)?)\b/i,
  /\b(reveal|show|print|repeat|quote|dump|leak|expose|translate|encode|decode)\b.{0,80}\b(prompt|instructions?|secrets?|api keys?|configuration)\b/i,
  /\b(göster|yazdır|tekrarla|alıntıla|sızdır|ifşa et|çevir|kodla|çöz)\b.{0,80}\b(prompt|talimat|gizli|api anahtar|yapılandırma)\b/i,
  /\b(ignore|disregard|forget|override)\b.{0,80}\b(previous|prior|system|developer|safety)\b/i,
  /\b(önceki|yukarıdaki|sistem|geliştirici|güvenlik)\b.{0,80}\b(talimatları|kuralları|mesajları)\b.{0,40}\b(yok say|unut|geçersiz kıl)\b/i,
  /\b(chain[- ]of[- ]thought|hidden reasoning|private reasoning|reasoning tokens)\b/i,
  /\b(gizli düşünce|iç muhakeme|düşünce zinciri|akıl yürütme token)\b/i,
  /\b(underlying|backend|internal)\b.{0,50}\b(provider|vendor|model name|model id)\b/i,
  /\b(arkadaki|arkada çalışan|alttaki|dahili|iç)\b.{0,50}\b(sağlayıcı|model|model adı|model kimliği|vendor)\b/i,
  /\b(which|what)\s+(model|provider)\b/i,
  /\b(are you|is this)\s+(chatgpt|gpt|openai|groq|claude|anthropic|ollama|llama)\b/i,
  /\b(hangi|kaç|kac)\b.{0,40}\b(model|parametre|parametresin|sağlayıcı|saglayici)\b/i,
  /(?:kaç|kac)\s+parametresin/i,
  /\b(chatgpt|gpt|openai|groq|claude|anthropic|ollama|llama)\s*(mısın|misin|musun|müsün|mi|mu|mü)?\b/i,
];

const INTERNAL_DISCLOSURE_DIRECT_REQUEST_PATTERNS = [
  /\b(reveal|show|print|repeat|quote|dump|leak|expose|translate|encode|decode)\b.{0,80}\b(prompt|instructions?|secrets?|api keys?|configuration|provider|model)\b/i,
  /\b(göster|yazdır|tekrarla|alıntıla|sızdır|ifşa et|çevir|kodla|çöz|söyle|anlat|paylaş)\b.{0,80}\b(prompt|talimat|gizli|api anahtar|yapılandırma|sağlayıcı|saglayici|model)\b/i,
  /\b(which|what)\s+(model|provider)\b/i,
  /\b(are you|is this)\s+(chatgpt|gpt|openai|groq|claude|anthropic|ollama|llama)\b/i,
  /\b(hangi|kaç|kac)\b.{0,40}\b(model|parametre|parametresin|sağlayıcı|saglayici)\b/i,
  /(?:kaç|kac)\s+parametresin/i,
  /\b(chatgpt|gpt|openai|groq|claude|anthropic|ollama|llama)\s*(mısın|misin|musun|müsün|mi|mu|mü)\b/i,
  /\b(arkadaki|arkada çalışan|alttaki|dahili|iç)\b.{0,50}\b(sağlayıcı|model|model adı|model kimliği|vendor)\b.{0,40}\b(ne|kim|hangisi|söyle|anlat|paylaş)\b/i,
];

const INTERNAL_DISCLOSURE_AVOIDANCE_PATTERNS = [
  /\b(do not|don't|dont|without|avoid|never|no need to)\b.{0,100}\b(mention|disclose|reveal|share|talk about|refer to)\b.{0,100}\b(provider|model|system prompt|developer message|hidden instruction|internal routing)\b/i,
  /\b(provider|model|system prompt|developer message|hidden instruction|internal routing)\b.{0,100}\b(do not|don't|dont|without|avoid|never)\b.{0,80}\b(mention|disclose|reveal|share|talk about|refer to)\b/i,
  /\b(bahsetme|söyleme|anlatma|paylaşma|değinme|ifşa etme|geçirme)\b.{0,100}\b(iç model|ic model|sağlayıcı|saglayici|system prompt|sistem promptu|gizli talimat|dahili yönlendirme)\b/i,
  /\b(iç model|ic model|sağlayıcı|saglayici|system prompt|sistem promptu|gizli talimat|dahili yönlendirme)\b.{0,100}\b(bahsetme|söyleme|anlatma|paylaşma|değinme|ifşa etme|geçirme)\b/i,
];

function isInternalDisclosureAvoidanceInstruction(prompt: string): boolean {
  const normalized = prompt.toLocaleLowerCase("tr-TR");
  return INTERNAL_DISCLOSURE_AVOIDANCE_PATTERNS.some(
    (pattern) => pattern.test(prompt) || pattern.test(normalized),
  );
}

function hasDirectInternalDisclosureRequest(prompt: string): boolean {
  const normalized = prompt.toLocaleLowerCase("tr-TR");
  return INTERNAL_DISCLOSURE_DIRECT_REQUEST_PATTERNS.some(
    (pattern) => pattern.test(prompt) || pattern.test(normalized),
  );
}

export function isProtectedInternalDisclosurePrompt(prompt: string): boolean {
  const normalized = prompt.replace(/\s+/g, " ").trim();
  const lowered = normalized.toLocaleLowerCase("tr-TR");
  if (/^(chatgpt|openai)\s*(mısın|misin|musun|müsün|mi|mu|mü)\??$/.test(lowered)) {
    return false;
  }
  if (
    isInternalDisclosureAvoidanceInstruction(normalized) &&
    !hasDirectInternalDisclosureRequest(normalized)
  ) {
    return false;
  }
  return (
    normalized.length > 0 &&
    (INTERNAL_DISCLOSURE_PATTERNS.some((pattern) => pattern.test(normalized)) ||
      containsProtectedElyanDisclosure(normalized))
  );
}

export function resolvePromptSecurityGate(prompt: string): BrainBoundaryGateResult | null {
  if (!isProtectedInternalDisclosurePrompt(prompt)) {
    return null;
  }

  return {
    triggered: true,
    answerSource: "backend_gate",
    text: ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT,
    gateRuleIds: ["security.prompt_exfiltration", "security.internal_configuration"],
    boundaryOutcome: "protected_internal_configuration",
    failureType: "protected_internal_configuration",
    enforcedByBackend: true,
    responseCode: "protected_internal_configuration",
    modelAnswerSkipped: true,
  };
}

export function isDirectElyanIdentityPrompt(prompt: string): boolean {
  const normalized = prompt.replace(/\s+/g, " ").trim().toLowerCase();
  return [
    /\belyan nedir\b/,
    /\belyan kimdir\b/,
    /\bsen nesin\b/,
    /\bsen kimsin\b/,
    /\bkendini (anlat|tanıt|tanit)\b/,
    /\bwhat is elyan\b/,
    /\bwho is elyan\b/,
    /\bwho are you\b/,
    /\bchatgpt misin\b/,
    /\bopenai mısın\b/,
    /\bopenai misin\b/,
  ].some((pattern) => pattern.test(normalized));
}

export function resolveElyanIdentityGate(prompt: string): BrainBoundaryGateResult | null {
  if (!isDirectElyanIdentityPrompt(prompt)) {
    return null;
  }

  return {
    triggered: true,
    answerSource: "backend_gate",
    text: ELYAN_PUBLIC_IDENTITY_TEXT,
    gateRuleIds: ["identity.elyan_verified", "security.internal_configuration"],
    boundaryOutcome: "verified_identity",
    failureType: "verified_identity_response",
    enforcedByBackend: true,
    responseCode: "verified_identity",
    modelAnswerSkipped: true,
  };
}

export function isMateriallyAmbiguousPrompt(prompt: string): boolean {
  return isMateriallyAmbiguousUserPrompt(prompt);
}

export function resolveBoundaryGate(
  routeDecision: CommandRouteDecision,
  prompt: string,
): BrainBoundaryGateResult | null {
  if (routeDecision.route === "pairing_required") {
    return {
      triggered: true,
      answerSource: "backend_gate",
      text:
        routeDecision.userFacingMessage?.trim() ||
        "Bu işlem sunucu tarafında yapılamaz. Eşleşmiş masaüstü runtime gerekli.",
      gateRuleIds: ["boundary.pairing_required", "boundary.desktop_required"],
      boundaryOutcome: "pairing_required",
      failureType: "pairing_required_ignored",
      enforcedByBackend: true,
      responseCode: "pairing_required",
      modelAnswerSkipped: true,
    };
  }

  if (routeDecision.route === "unavailable") {
    return {
      triggered: true,
      answerSource: "backend_gate",
      text:
        routeDecision.userFacingMessage?.trim() ||
        "Bu işlem sunucu tarafında yapılamaz. Eşleşmiş masaüstü runtime gerekli.",
      gateRuleIds: ["boundary.desktop_required"],
      boundaryOutcome: "desktop_required",
      failureType: "unsupported_runtime_hallucination",
      enforcedByBackend: true,
      responseCode: "unsupported_runtime",
      modelAnswerSkipped: true,
    };
  }

  if (routeDecision.route === "desktop_runtime" || routeDecision.privacyClass === "local_private") {
    return {
      triggered: true,
      answerSource: "backend_gate",
      text:
        routeDecision.userFacingMessage?.trim() ||
        "Bu işlem sunucu tarafında yapılamaz. Eşleşmiş masaüstü runtime gerekli.",
      gateRuleIds: ["boundary.local_private", "boundary.desktop_required"],
      boundaryOutcome: "desktop_required",
      failureType: "local_private_hallucination",
      enforcedByBackend: true,
      responseCode: "desktop_required",
      modelAnswerSkipped: true,
    };
  }

  if (routeDecision.shouldAskClarification || isMateriallyAmbiguousPrompt(prompt)) {
    return {
      triggered: true,
      answerSource: "backend_gate",
      text: buildClarificationPrompt(prompt),
      gateRuleIds: ["clarification_on_ambiguity"],
      boundaryOutcome: "clarification_required",
      failureType: "missed_clarification",
      enforcedByBackend: true,
      responseCode: "clarification_required",
      modelAnswerSkipped: true,
    };
  }

  return null;
}
