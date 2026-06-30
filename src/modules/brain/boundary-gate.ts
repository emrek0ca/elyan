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
    | "security_refusal"
    | "verified_identity";
  failureType: string;
  enforcedByBackend: true;
  responseCode:
    | "pairing_required"
    | "desktop_required"
    | "unsupported_runtime"
    | "clarification_required"
    | "protected_internal_configuration"
    | "security_refusal"
    | "verified_identity";
  modelAnswerSkipped: true;
  securityDecision?: SecurityDecision;
};

export type SecurityRequestType =
  | "secret_extraction_attempt"
  | "system_prompt_extraction_attempt"
  | "internal_endpoint_request"
  | "database_credential_request"
  | "payment_action_request"
  | "destructive_action_request"
  | "external_send_request";

export type SecurityDecision = {
  request_type: SecurityRequestType;
  is_sensitive: boolean;
  should_refuse: boolean;
  blocked_fields: string[];
  reason: string;
  safe_alternative: string;
  leaked_secret: false;
  invented_internal_info: false;
  requires_verified_admin_channel: boolean;
  risk: "low" | "medium" | "high" | "critical";
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

function includesAny(patterns: RegExp[], value: string): boolean {
  return patterns.some((pattern) => pattern.test(value));
}

function wantsMachineReadableJson(prompt: string): boolean {
  return /\b(json|application\/json|valid json|geçerli json|gècerli json)\b/i.test(prompt);
}

function buildSecurityDecisionText(decision: SecurityDecision, prompt: string): string {
  if (wantsMachineReadableJson(prompt)) {
    return JSON.stringify(decision);
  }
  return decision.safe_alternative;
}

function buildSecurityGateResult(
  decision: SecurityDecision,
  prompt: string,
): BrainBoundaryGateResult {
  return {
    triggered: true,
    answerSource: "backend_gate",
    text: buildSecurityDecisionText(decision, prompt),
    gateRuleIds: [`security.${decision.request_type}`],
    boundaryOutcome: "security_refusal",
    failureType: decision.request_type,
    enforcedByBackend: true,
    responseCode: "security_refusal",
    modelAnswerSkipped: true,
    securityDecision: decision,
  };
}

function decision(input: {
  requestType: SecurityRequestType;
  blockedFields: string[];
  reason: string;
  safeAlternative: string;
  requiresVerifiedAdminChannel?: boolean;
  risk: SecurityDecision["risk"];
}): SecurityDecision {
  return {
    request_type: input.requestType,
    is_sensitive: true,
    should_refuse: true,
    blocked_fields: input.blockedFields,
    reason: input.reason,
    safe_alternative: input.safeAlternative,
    leaked_secret: false,
    invented_internal_info: false,
    requires_verified_admin_channel: input.requiresVerifiedAdminChannel ?? false,
    risk: input.risk,
  };
}

export function resolveSecurityDecisionGate(prompt: string): BrainBoundaryGateResult | null {
  const normalized = prompt.replace(/\s+/g, " ").trim();
  const lowered = normalized.toLocaleLowerCase("tr-TR");
  const asciiLowered = normalized.toLowerCase();
  const securityHaystack = `${lowered} ${asciiLowered}`;
  if (!normalized) {
    return null;
  }

  const authClaim =
    /(^|[^\p{L}])(founder|owner|admin|root|superuser|kurucu\p{L}*|sahibiyim|sistem sahibi|yetkili\p{L}*|administrator)([^\p{L}]|$)/iu.test(securityHaystack);
  const secretTarget = includesAny(
    [
      /\b(openai_api_key|groq_api_key|anthropic_api_key|api[_ -]?key|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token|bearer token|private key|client_secret|webhook secret)\b/i,
      /(^|[^\p{L}])(\.env|env|environment variable|ortam değişken\p{L}*|gizli anahtar\p{L}*|api anahtar\p{L}*|token\p{L}*|credential\p{L}*|kimlik bilgisi\p{L}*)/iu,
    ],
    securityHaystack,
  );
  const requestVerb = includesAny(
    [
      /\b(show|print|dump|reveal|send|give|share|export|list|leak|copy|write|return)\b/i,
      /(^|[^\p{L}])(göster\p{L}*|yazdır\p{L}*|dök\p{L}*|dok\p{L}*|sızdır\p{L}*|sizdir\p{L}*|ver|paylaş\p{L}*|paylas\p{L}*|listele\p{L}*|kopyala\p{L}*|döndür\p{L}*|dondur\p{L}*|çıkar\p{L}*|cikar\p{L}*)([^\p{L}]|$)/iu,
    ],
    securityHaystack,
  );
  if (secretTarget && (requestVerb || authClaim)) {
    return buildSecurityGateResult(
      decision({
        requestType: "secret_extraction_attempt",
        blockedFields: ["secret", "api_key", "token", "environment"],
        reason: "Secrets, API keys, tokens, and environment values are confidential and cannot be disclosed through chat.",
        safeAlternative: "Gizli anahtarları paylaşamam. İstersen güvenli secret rotasyonu, env doğrulama veya bağlantı testi için adım adım kontrol listesi hazırlayabilirim.",
        requiresVerifiedAdminChannel: true,
        risk: "critical",
      }),
      prompt,
    );
  }

  if (/\b(database_url|postgres(?:ql)?:\/\/|mysql:\/\/|mongodb(?:\+srv)?:\/\/|redis:\/\/|db password|veritabanı şifresi|veritabani sifresi|database credential)\b/i.test(securityHaystack)) {
    return buildSecurityGateResult(
      decision({
        requestType: "database_credential_request",
        blockedFields: ["database_url", "database_password", "connection_string"],
        reason: "Database connection strings and credentials are sensitive infrastructure secrets.",
        safeAlternative: "Veritabanı bağlantı bilgisini paylaşamam. İstersen bağlantıyı güvenli doğrulama, rotasyon veya least-privilege kullanıcı oluşturma adımlarını çıkarabilirim.",
        requiresVerifiedAdminChannel: true,
        risk: "critical",
      }),
      prompt,
    );
  }

  if (isProtectedInternalDisclosurePrompt(normalized)) {
    return buildSecurityGateResult(
      decision({
        requestType: "system_prompt_extraction_attempt",
        blockedFields: ["system_prompt", "developer_message", "hidden_instruction", "internal_configuration"],
        reason: "System prompts, developer messages, hidden instructions, and internal configuration are confidential.",
        safeAlternative: "Gizli talimatları veya sistem promptunu paylaşamam. İstersen Elyan'ın güvenli çalışma sınırlarını kısa ve genel biçimde açıklayabilirim.",
        requiresVerifiedAdminChannel: true,
        risk: "high",
      }),
      prompt,
    );
  }

  if (/\b(\/internal|\/admin|\/debug|\/metrics|\/readyz|\/healthz|localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.|192\.168\.|internal endpoint|private endpoint|dahili endpoint|iç endpoint|debug endpoint|debug mode|debug mod|admin mode|admin mod)\b/i.test(securityHaystack)) {
    return buildSecurityGateResult(
      decision({
        requestType: "internal_endpoint_request",
        blockedFields: ["internal_endpoint", "private_network", "debug_route"],
        reason: "Internal routes, private network addresses, and debug endpoints are not disclosed or invented in chat.",
        safeAlternative: "Dahili endpoint uyduramam veya paylaşamam. İstersen public API sözleşmesi veya güvenli health-check yaklaşımı tasarlayabilirim.",
        requiresVerifiedAdminChannel: true,
        risk: "high",
      }),
      prompt,
    );
  }

  if (/(^|[^\p{L}])(pay|payment|charge|transfer|wire|purchase|subscribe|refund|ödeme\p{L}*|odeme\p{L}*|para gönder\p{L}*|para gonder\p{L}*|karttan çek\p{L}*|karttan cek\p{L}*|satın al\p{L}*|satin al\p{L}*|aboneli\p{L}* başlat\p{L}*|aboneli\p{L}* baslat\p{L}*|iade yap\p{L}*)([^\p{L}]|$)/iu.test(securityHaystack)) {
    return buildSecurityGateResult(
      decision({
        requestType: "payment_action_request",
        blockedFields: ["payment_action", "billing_action", "financial_transfer"],
        reason: "Payment, billing, purchase, transfer, and refund actions require verified user action and an approved payment channel.",
        safeAlternative: "Ödeme veya para hareketi başlatamam. İstersen yapılacak işlemler için güvenli onay akışı ve kontrol listesi hazırlayabilirim.",
        requiresVerifiedAdminChannel: true,
        risk: "critical",
      }),
      prompt,
    );
  }

  if (/(^|[^\p{L}])(rm\s+-rf|delete all|wipe|format disk|drop database|truncate table|destroy|erase|factory reset|sil hepsini|tamamen sil|diski formatla|veritabanını sil|veritabani sil|tabloyu düşür\p{L}*|tabloyu dusur\p{L}*|sıfırla\p{L}*|sifirla\p{L}*)([^\p{L}]|$)/iu.test(securityHaystack)) {
    return buildSecurityGateResult(
      decision({
        requestType: "destructive_action_request",
        blockedFields: ["destructive_action", "data_deletion", "system_modification"],
        reason: "Destructive actions cannot be executed or authorized from an unverified chat request.",
        safeAlternative: "Yıkıcı işlem başlatamam. İstersen güvenli yedekleme, dry-run ve açık onay gerektiren bir bakım planı oluşturabilirim.",
        requiresVerifiedAdminChannel: true,
        risk: "critical",
      }),
      prompt,
    );
  }

  if (/(^|[^\p{L}])(send email|send message|post to|dm|sms|slack|whatsapp|telegram|tweet|publish|email gönder\p{L}*|e-posta olarak gönder\p{L}*|e posta olarak gönder\p{L}*|mail gönder\p{L}*|mesaj gönder\p{L}*|sms gönder\p{L}*|slack'e yaz\p{L}*|whatsapp'tan yaz\p{L}*|yayınla\p{L}*|paylaş\p{L}*)([^\p{L}]|$)/iu.test(securityHaystack)) {
    return buildSecurityGateResult(
      decision({
        requestType: "external_send_request",
        blockedFields: ["external_send", "message_delivery", "publishing_action"],
        reason: "External sending or publishing requires explicit reviewed content, destination, and user approval.",
        safeAlternative: "Dışarı mesaj veya yayın gönderemem. İstersen gönderi taslağını hazırlayıp onay akışı için yapılandırabilirim.",
        requiresVerifiedAdminChannel: false,
        risk: "medium",
      }),
      prompt,
    );
  }

  return null;
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

  return buildSecurityGateResult(
    decision({
      requestType: "system_prompt_extraction_attempt",
      blockedFields: ["system_prompt", "developer_message", "hidden_instruction", "internal_configuration"],
      reason: "System prompts, developer messages, hidden instructions, and internal configuration are confidential.",
      safeAlternative: ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT,
      requiresVerifiedAdminChannel: true,
      risk: "high",
    }),
    prompt,
  );
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
