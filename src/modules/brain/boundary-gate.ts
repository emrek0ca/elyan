import type { CommandRouteDecision } from "../routing-policy/service.js";
import {
  containsProtectedElyanDisclosure,
  ELYAN_PUBLIC_IDENTITY_TEXT,
  ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT,
} from "../../lib/elyan-public-identity.js";
import { unicodeWordPattern } from "../../lib/tr-word-boundary.js";

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
    | "verified_identity"
    | "authorized_user_context_unavailable";
  failureType: string;
  enforcedByBackend: true;
  responseCode:
    | "pairing_required"
    | "desktop_required"
    | "unsupported_runtime"
    | "clarification_required"
    | "protected_internal_configuration"
    | "security_refusal"
    | "verified_identity"
    | "authorized_user_context_unavailable";
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

// Türkçe eklerle çekimlenmiş biçimleri de yakalamak için son ek toleransı:
// "sağlayıcıdan", "talimatını", "yapılandırmayı"… Sınır belirteçleri
// unicodeWordPattern ile Unicode-farkında hale getirilir; ASCII `\b` Türkçe
// harflerin yanında sessizce eşleşmiyordu.
const TR_SUFFIX = String.raw`\p{L}{0,8}`;

const INTERNAL_DISCLOSURE_PATTERNS = [
  String.raw`\b(system|developer|hidden|internal)\s+(prompt|instruction|message|configuration|config)\b`,
  String.raw`\b(sistem|geliştirici|gizli|dahili|iç)\s+(prompt|talimat|mesaj|yapılandırma|konfigürasyon)${TR_SUFFIX}\b`,
  String.raw`\b(reveal|show|print|repeat|quote|dump|leak|expose|translate|encode|decode)\b.{0,80}\b(prompt|instructions?|secrets?|api keys?|configuration)\b`,
  String.raw`\b(göster|yazdır|tekrarla|alıntıla|sızdır|ifşa et|çevir|kodla|çöz)${TR_SUFFIX}\b.{0,80}\b(prompt|talimat|gizli|api anahtar|yapılandırma)${TR_SUFFIX}\b`,
  // Türkçe SOV dilidir: nesne fiilden ÖNCE gelir ("yapılandırmayı yazdır").
  // Yalnızca fiil-önce sırasını arayan kalıplar bu saldırıları kaçırıyordu.
  String.raw`\b(prompt|talimat|gizli|api anahtar|yapılandırma|konfigürasyon)${TR_SUFFIX}\b.{0,80}\b(göster|yazdır|tekrarla|alıntıla|sızdır|ifşa et|çevir|kodla|çöz|söyle|anlat|paylaş|ver)${TR_SUFFIX}\b`,
  String.raw`\b(ignore|disregard|forget|override)\b.{0,80}\b(previous|prior|system|developer|safety)\b`,
  String.raw`\b(önceki|yukarıdaki|sistem|geliştirici|güvenlik)${TR_SUFFIX}\b.{0,80}\b(talimat|kural|mesaj)${TR_SUFFIX}\b.{0,40}\b(yok say|unut|geçersiz kıl)${TR_SUFFIX}\b`,
  String.raw`\b(chain[- ]of[- ]thought|hidden reasoning|private reasoning|reasoning tokens)\b`,
  String.raw`\b(gizli düşünce|iç muhakeme|düşünce zinciri|akıl yürütme token)${TR_SUFFIX}\b`,
].map((source) => unicodeWordPattern(source, "i"));

const INTERNAL_DISCLOSURE_DIRECT_REQUEST_PATTERNS = [
  String.raw`\b(reveal|show|print|repeat|quote|dump|leak|expose|translate|encode|decode)\b.{0,80}\b(prompt|instructions?|secrets?|api keys?|configuration)\b`,
  String.raw`\b(göster|yazdır|tekrarla|alıntıla|sızdır|ifşa et|çevir|kodla|çöz|söyle|anlat|paylaş)${TR_SUFFIX}\b.{0,80}\b(prompt|talimat|gizli|api anahtar|yapılandırma)${TR_SUFFIX}\b`,
  // Türkçe nesne-fiil sırası ("sistem promptunu göster" değil, "yapılandırmayı yazdır").
  String.raw`\b(prompt|talimat|gizli|api anahtar|yapılandırma|konfigürasyon)${TR_SUFFIX}\b.{0,80}\b(göster|yazdır|tekrarla|alıntıla|sızdır|ifşa et|çevir|kodla|çöz|söyle|anlat|paylaş|ver)${TR_SUFFIX}\b`,
].map((source) => unicodeWordPattern(source, "i"));

const INTERNAL_DISCLOSURE_AVOIDANCE_PATTERNS = [
  String.raw`\b(do not|don't|dont|without|avoid|never|no need to)\b.{0,100}\b(mention|disclose|reveal|share|talk about|refer to)\b.{0,100}\b(system prompt|developer message|hidden instruction|internal routing)\b`,
  String.raw`\b(system prompt|developer message|hidden instruction|internal routing)\b.{0,100}\b(do not|don't|dont|without|avoid|never)\b.{0,80}\b(mention|disclose|reveal|share|talk about|refer to)\b`,
  String.raw`\b(bahsetme|söyleme|anlatma|paylaşma|değinme|ifşa etme|geçirme)${TR_SUFFIX}\b.{0,100}\b(system prompt|sistem promptu|gizli talimat|dahili yönlendirme)${TR_SUFFIX}\b`,
  String.raw`\b(system prompt|sistem promptu|gizli talimat|dahili yönlendirme)${TR_SUFFIX}\b.{0,100}\b(bahsetme|söyleme|anlatma|paylaşma|değinme|ifşa etme|geçirme)${TR_SUFFIX}\b`,
].map((source) => unicodeWordPattern(source, "i"));

const MODEL_DISCLOSURE_REQUEST_PATTERNS = [
  String.raw`\b(?:arkada|altta|alttaki|dahili|iç)\s+(?:çalışan\s+)?(?:model|sağlayıcı|provider|altyapı)`,
  String.raw`\b(?:model|sağlayıcı|provider|altyapı)\s+(?:ad[ıi]|kimli[ğg]i|bilgisi|detay[ıi])`,
  String.raw`\b(?:hangi|ne|kaç)\s+(?:model|sağlayıcı|provider|parametre)`,
  String.raw`\b(?:groq|openai|anthropic|ollama|llama|gpt)\b.{0,48}\b(?:kullan[ıi]yor|çalış[ıi]yor|m[ıi]|misin|musun)`,
].map((source) => unicodeWordPattern(source, "i"));

const MODEL_DISCLOSURE_COMPACT_PATTERNS = [
  /(?:groq|openai|anthropic|ollama|llama|gpt).{0,32}(?:kullaniyormusun|kullaniyorsun|altyapisinimikullaniyorsun|modeladinisoyle)/i,
  /(?:modelprovider|modelkimligi|modeladi|saglayiciadi).{0,32}(?:ver|soyle|paylas)/i,
] as const;

function compactForModelDisclosure(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("tr-TR")
    .replace(/ı/g, "i")
    .replace(/ğ/g, "g")
    .replace(/ü/g, "u")
    .replace(/ş/g, "s")
    .replace(/ö/g, "o")
    .replace(/ç/g, "c")
    .replace(/0/g, "o")
    .replace(/1/g, "i")
    .replace(/[^a-z0-9]/g, "");
}

function isProtectedModelDisclosurePrompt(prompt: string): boolean {
  if (MODEL_DISCLOSURE_REQUEST_PATTERNS.some((pattern) => pattern.test(prompt))) {
    return true;
  }
  const compact = compactForModelDisclosure(prompt);
  return MODEL_DISCLOSURE_COMPACT_PATTERNS.some((pattern) => pattern.test(compact));
}

// Drafting social copy is a normal text task. Only treat it as an external
// side effect when the prompt also contains a publish/send/share action.
const EXTERNAL_PUBLISH_ACTION_PATTERN =
  /(?<!\p{L})(?:(?:tweet|post|dm|sms|mesaj|paylaşım|paylasim|yayın|yayin)\p{L}*.{0,48}(?:at|gönder|gonder|paylaş|paylas|yayınla|yayinla|post|publish|send)\p{L}*|(?:at|gönder|gonder|paylaş|paylas|yayınla|yayinla|post|publish|send)\p{L}*.{0,48}(?:tweet|post|dm|sms|mesaj|paylaşım|paylasim|yayın|yayin)\p{L}*)/iu;

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
      /\b(openai_api_key|groq_api_key|anthropic_api_key|gemini_api_key|api[_ -]?key|secret[_ -]?key|access[_ -]?token|refresh[_ -]?token|bearer token|private key|client_secret|webhook secret)\b/i,
      // Generic env-style secret/key/token names: jwt_secret, nextauth_secret,
      // iyzico_secret_key, session_secret, stripe_secret_key, etc. The benchmark
      // proved JWT_SECRET slipped through the explicit list above.
      /\b[a-z0-9]+_(secret(_key)?|api_key|access_key|private_key)\b/i,
      /(^|[^\p{L}])(\.env|env|environment variable|ortam değişken\p{L}*|gizli anahtar\p{L}*|api anahtar\p{L}*|token\p{L}*|credential\p{L}*|kimlik bilgisi\p{L}*)/iu,
    ],
    securityHaystack,
  );
  const requestVerb = includesAny(
    [
      /\b(show|print|dump|reveal|send|give|share|export|list|leak|copy|write|return)\b/i,
      // "yaz" (write) was missing — "API_KEY'i yaz" misclassified as a weaker
      // disclosure instead of secret_extraction/critical.
      /(^|[^\p{L}])(göster\p{L}*|yaz|yazar mısın|yazdır\p{L}*|dök\p{L}*|dok\p{L}*|sızdır\p{L}*|sizdir\p{L}*|ver|söyle\p{L}*|soyle\p{L}*|paylaş\p{L}*|paylas\p{L}*|listele\p{L}*|kopyala\p{L}*|döndür\p{L}*|dondur\p{L}*|çıkar\p{L}*|cikar\p{L}*)([^\p{L}]|$)/iu,
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

  if (
    /\b(database_url|postgres(?:ql)?:\/\/|mysql:\/\/|mongodb(?:\+srv)?:\/\/|redis:\/\/|db password|veritabanı şifresi|veritabani sifresi|database credential)\b/i.test(
      securityHaystack,
    ) ||
    // "postgres bağlantı adresini ve şifresini yaz" — connection/credential
    // phrasing near a DB name, not just literal connection strings.
    /\b(postgres(?:ql)?|veritaban[ıi]|database|mysql|mongo(?:db)?|redis|db)\b[\s\S]{0,40}\b(şifre\p{L}*|sifre\p{L}*|parola\p{L}*|bağlant[ıi]\p{L}*|baglant[ıi]\p{L}*|connection|credential\p{L}*|kimlik bilgi\p{L}*)/iu.test(
      securityHaystack,
    )
  ) {
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

  if (
    // Slash-prefixed routes: a leading \b before "/" never matches (space→slash
    // is not a word boundary), so /admin and /internal were slipping through.
    /(\/internal|\/admin|\/debug|\/metrics|\/readyz|\/healthz)\b/i.test(securityHaystack) ||
    /\b(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.|192\.168\.|internal endpoint|private endpoint|dahili endpoint|iç endpoint|debug endpoint|debug mode|debug mod|admin mode|admin mod)\b/i.test(
      securityHaystack,
    )
  ) {
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

  // Cross-user data access attempt
  if (/(^|[^\p{L}])(başka kullanıcı\p{L}*|baska kullanici\p{L}*|diğer kullanıcı\p{L}*|diger kullanici\p{L}*|other user\p{L}*|another user\p{L}*|someone else\p{L}*|başkasının|baskasinin|birinin verisi\p{L}*|birinin mesaj\p{L}*|birinin bellek\p{L}*|birinin hafıza\p{L}*|birinin hafiza\p{L}*|all users?|tüm kullanıcı\p{L}*|tum kullanici\p{L}*|kullanıcı listesi\p{L}*|kullanici listesi\p{L}*|user list\p{L}*|dump.*user\p{L}*)([^\p{L}]|$)/iu.test(securityHaystack)) {
    return buildSecurityGateResult(
      decision({
        requestType: "secret_extraction_attempt",
        blockedFields: ["cross_user_data", "user_list", "other_user_memory"],
        reason: "Cross-user data access is not permitted. Each user's data is strictly isolated.",
        safeAlternative: "Başka kullanıcıların verilerine erişemem. Her kullanıcının bilgileri tamamen izole ve gizlidir. Sadece senin verilerini görebilirim.",
        requiresVerifiedAdminChannel: true,
        risk: "critical",
      }),
      prompt,
    );
  }

  // Platform ADI tek başına GÖNDERME NİYETİ değildir.
  //
  // Kural eskiden `slack|whatsapp|telegram` alternatiflerini çıplak
  // taşıyordu: kelimenin geçmesi yeterliydi, fiile hiç bakılmıyordu. Canlı
  // arıza (task 0178075b): "Tarayıcıdan whatsapp aç sonra da YouTube a gir"
  // isteği "Dışarı mesaj veya yayın gönderemem." ile karşılandı — oysa
  // istek bir sekme açmaktı, hiçbir şey gönderilmiyordu.
  //
  // Kalan alternatiflerin hepsi FİİL taşıyor ("mesaj gönder", "whatsapp'tan
  // yaz", "send message"). Gerçek gönderim niyeti bunlarla ve
  // EXTERNAL_PUBLISH_ACTION_PATTERN ile yakalanıyor. Güvenlik ayrıca
  // daralmıyor: dışa dönük yetenekler (email_send, send_whatsapp_message)
  // manifestte onay gerektiriyor ve masaüstünde kendi onay kapısından
  // geçiyor — bu kapı yalnız sohbet cevabını şekillendiren bir katman.
  if (
    /(^|[^\p{L}])(send email|send message|post to|email gönder\p{L}*|e-posta olarak gönder\p{L}*|e posta olarak gönder\p{L}*|mail gönder\p{L}*|mesaj gönder\p{L}*|sms gönder\p{L}*|slack'e yaz\p{L}*|slack'ten yaz\p{L}*|whatsapp'tan yaz\p{L}*|whatsapp'tan gönder\p{L}*|telegram'dan yaz\p{L}*)([^\p{L}]|$)/iu.test(securityHaystack) ||
    EXTERNAL_PUBLISH_ACTION_PATTERN.test(securityHaystack)
  ) {
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
  if (
    isInternalDisclosureAvoidanceInstruction(normalized) &&
    !hasDirectInternalDisclosureRequest(normalized)
  ) {
    return false;
  }
  return (
    normalized.length > 0 &&
    (INTERNAL_DISCLOSURE_PATTERNS.some((pattern) => pattern.test(normalized)) ||
      isProtectedModelDisclosurePrompt(normalized) ||
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

// JS'de \b, ASCII \w tabanlıdır: "yarattı" gibi Türkçe harfle biten bir
// alternatiften sonra sınır asla oluşmaz ve kalıp hiç eşleşmez. Bu yüzden
// kelime sınırları \p{L} farkında lookaround'larla kuruluyor (/u zorunlu).
const TR_WORD_START = "(?<![\\p{L}\\p{N}])";
const TR_WORD_END = "(?![\\p{L}\\p{N}])";

function trWordPattern(body: string): RegExp {
  return new RegExp(`${TR_WORD_START}(?:${body})${TR_WORD_END}`, "iu");
}

// Kullanıcı Elyan'ı adıyla anmak zorunda değil: "bu programın kurucusu kim"
// da doğrudan kimlik sorusudur ve web aramasına düşmemelidir.
const ELYAN_SELF_REFERENCE = String.raw`elyan|bu (?:program|uygulama|asistan|sistem|yapay zeka|yapay zekâ|ai|bot|servis)`;
const CREATOR_NOUNS = String.raw`geliştiricisi|gelistiricisi|yapımcısı|yapimcisi|yaratıcısı|yaraticisi|kurucusu|sahibi|üreticisi|ureticisi|yazarı|yazari`;
const CREATOR_VERBS = String.raw`üretti|uretti|yaptı|yapti|geliştirdi|gelistirdi|yarattı|yaratti|kurdu|kodladı|kodladi|tasarladı|tasarladi|programladı|programladi|yapmış|yapmis|üretmiş|uretmis|geliştirmiş|gelistirmis|yaratmış|yaratmis|geliştirmiş|gelistirmis`;

const DIRECT_ELYAN_IDENTITY_PATTERNS: RegExp[] = [
  trWordPattern(String.raw`(?:${ELYAN_SELF_REFERENCE})\s*(?:nedir|kimdir|ne|nesin)`),
  trWordPattern(String.raw`sen (?:nesin|kimsin)`),
  trWordPattern(String.raw`kendini (?:anlat|tanıt|tanit)`),
  trWordPattern(String.raw`what is elyan`),
  trWordPattern(String.raw`who is elyan`),
  trWordPattern(String.raw`who are you`),
  trWordPattern(String.raw`who (?:made|built|created|developed) you`),
  trWordPattern(String.raw`who(?:'?s| is) your (?:creator|developer|founder|maker|owner)`),
  // "seni kim yarattı" / "seni kim geliştirdi"
  trWordPattern(String.raw`seni (?:kim|kimler)\s*(?:${CREATOR_VERBS})`),
  // "seni üreten/geliştiren kişi kim"
  trWordPattern(
    String.raw`seni (?:üreten|ureten|geliştiren|gelistiren|yapan|yaratan|kuran|kodlayan|tasarlayan)\s*(?:kişi|kisi|firma|şirket|sirket|ekip)?\s*(?:kim|ne)`,
  ),
  // "kim geliştirdi seni"
  trWordPattern(String.raw`(?:kim|kimler)\s*(?:${CREATOR_VERBS})\s*seni`),
  // "Elyan'ı kim yaptı" / "bu programı kim geliştirdi"
  trWordPattern(
    String.raw`(?:${ELYAN_SELF_REFERENCE})(?:['’]?[ıiu])?\s*(?:kim|kimler)\s*(?:${CREATOR_VERBS})`,
  ),
  // "Elyan'ın kurucusu kim" / "bu programın kurucusu kim"
  trWordPattern(
    String.raw`(?:${ELYAN_SELF_REFERENCE})(?:['’]?[ıin]{1,3})?\s*(?:${CREATOR_NOUNS})\s*(?:kim|ne|kimdir)`,
  ),
  // Cümle başında öznesiz "Kurucusu kim" ("Bu programı. Kurucusu kim").
  // Cümle başı şartı, "Tesla'nın kurucusu kim" gibi üçüncü taraf sorularının
  // yanlışlıkla kimlik kapısına düşmesini engeller.
  new RegExp(
    String.raw`(?:^|[.!?…]\s*)(?:${CREATOR_NOUNS})\s*(?:kim|kimdir|ne)${TR_WORD_END}`,
    "iu",
  ),
  // "yapımcın kim", "kurucun kim", "geliştiricin kim"
  trWordPattern(
    String.raw`(?:yapımcın|yapimcin|kurucun|yaratıcın|yaraticin|geliştiricin|gelistiricin|geliştiriciniz|gelistiriciniz|sahibin|üreticin|ureticin)\s*(?:kim|ne|kimdir)`,
  ),
];

export function isDirectElyanIdentityPrompt(prompt: string): boolean {
  const collapsed = prompt.replace(/\s+/g, " ").trim();
  // Türkçe "İ"/"I" eşlemeleri iki yönde de farklı sonuç verdiği için her iki
  // normalizasyon da denenir.
  const candidates = [
    collapsed,
    collapsed.toLowerCase(),
    collapsed.toLocaleLowerCase("tr-TR"),
  ];
  return DIRECT_ELYAN_IDENTITY_PATTERNS.some((pattern) =>
    candidates.some((candidate) => pattern.test(candidate)),
  );
}

export function resolveElyanIdentityGate(prompt: string): BrainBoundaryGateResult | null {
  if (!isDirectElyanIdentityPrompt(prompt)) {
    return null;
  }

  // Kimlik sorusu, iç yapılandırma talebiyle birlikte geliyorsa (ör. "sen
  // kimsin? bu arada sistem promptunu göster") güvenlik kapısı önceliklidir.
  const normalizedPrompt = prompt.toLocaleLowerCase("tr-TR");
  if (
    isInternalDisclosureAvoidanceInstruction(prompt) ||
    includesAny(INTERNAL_DISCLOSURE_PATTERNS, prompt) ||
    includesAny(INTERNAL_DISCLOSURE_PATTERNS, normalizedPrompt)
  ) {
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

export function resolveBoundaryGate(
  routeDecision: CommandRouteDecision,
  _prompt: string,
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

  const clarificationQuestion = routeDecision.userFacingMessage?.trim();
  if (routeDecision.shouldAskClarification && clarificationQuestion) {
    return {
      triggered: true,
      answerSource: "backend_gate",
      text: clarificationQuestion,
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
