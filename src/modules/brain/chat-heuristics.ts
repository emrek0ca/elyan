import type { PlanBrainProfile } from "../billing/catalog.js";
import type { SharedBrainWorkload } from "./workloads.js";

const GREETING_EXACT_MATCHES = new Set([
  "selam",
  "merhaba",
  "slm",
  "hey",
  "hi",
  "hello",
  "iyi sabahlar",
  "iyi aksamlar",
  "iyi akşamlar",
  "gunaydin",
  "günaydın",
]);

const GREETING_PREFIX_PATTERNS = [
  /^(selam|merhaba|slm|hey|hi|hello)\b/i,
  /^(iyi sabahlar|günaydın|gunaydin|iyi akşamlar|iyi aksamlar)\b/i,
];

const SOCIAL_CHAT_PATTERNS = [
  /\b(nasılsın|nasilsin|naber|napıyorsun|napiyorsun)\b/i,
  /\b(how are you|what'?s up|whats up)\b/i,
  /\b(keyifler nasıl|keyifler nasil)\b/i,
  /\b(teşekkürler|tesekkurler|teşekkür ederim|tesekkur ederim|sağ ol|sag ol|sağol|sagol|sağ olun|sag olun|kolay gelsin|iyi akşamlar|iyi aksamlar|iyi sabahlar|günaydın|gunaydin|iyi geceler)\b/i,
];

const AMBIGUOUS_REFERENCE_PATTERNS = [
  /^(bunu|şunu|sunu|this|that)$/i,
  /^(buna|şuna|suna|this|that) bak$/i,
  /^(bakar mısın|bakar misin|look at this)$/i,
  /^(yardım et|yardim et|help me|yardımcı ol|yardimci ol)$/i,
  /^(düzelt|duzelt|fix it|improve this|optimize this)$/i,
  /^(bunu|şunu|sunu|this|that) (düzelt|duzelt|iyileştir|iyilestir|daha iyi yap|fix|improve|optimize)$/i,
  /^(bunu|şunu|sunu|this|that) (aç|ac|anlat|explain|summarize)$/i,
];

const BALANCED_PROFILE_PATTERNS = [
  /\b(karşılaştır|karsilastir|compare|tradeoff|artı|arti|eksi|pros|cons)\b/i,
  /\b(adım adım|adim adim|step by step|detaylı|detayli|derinlemesine|deep dive)\b/i,
  /\b(neden|niye|how exactly|why|explain|açıkla|acikla|anlat)\b/i,
  /\b(örneklerle|orneklerle|examples|alternatif|alternatives|opsiyon)\b/i,
  /\b(özetle|ozetle|değerlendir|degerlendir|analyze|analiz et|incele)\b/i,
  /\b(profesyonel(?:ce)?|imla|yeniden yaz|tekrar yaz|düzgün Türkçe|dogru turkce|doğru türkçe|kısa ve net|kisa ve net|madde madde|maddeler halinde)\b/i,
  /\b(pdf|docx|xlsx|pptx|belge|dokuman|döküman|dosya|görsel|gorsel|metin|içerik|icerik|özetini çıkar|ozetini cikar|bunda ne yazıyor|bunda ne yaziyo|içinde ne var|icinde ne var|tarat|tarama|ocr|çeviri|ceviri|tercüme|tercume|gramer|grammar|lehçe|lehce|alfabe|söz varlığı|soz varligi|kelime hazinesi)\b/i,
  /\b(türk dünyası|turkic|oğuz|oguz|kıpçak|kipchak|karluk|qipchak|qarluq|azerbaijani|kazakh|kyrgyz|uzbek|turkmen|uyghur|tatar|bashkir|gagauz|karakalpak|sakha|chuvash)\b/i,
  /\b(yarım bırakma|yarim birakma|yarım kalmasın|yarim kalmasin|tamamla|tamamlanmış|bitir|bozma|daha akıllı|daha zeki|net sonuç|uzatma ama eksik bırakma)\b/i,
];

export function compactText(value: string): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function isGreetingLikePrompt(prompt: string): boolean {
  const normalized = compactText(prompt).toLowerCase();
  if (!normalized) {
    return false;
  }
  if (GREETING_EXACT_MATCHES.has(normalized)) {
    return true;
  }
  return GREETING_PREFIX_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isSocialChatPrompt(prompt: string): boolean {
  const normalized = compactText(prompt).toLowerCase();
  if (!normalized) {
    return false;
  }
  if (isGreetingLikePrompt(normalized)) {
    return true;
  }
  return SOCIAL_CHAT_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isMateriallyAmbiguousUserPrompt(prompt: string): boolean {
  const normalized = compactText(prompt).toLowerCase();
  if (!normalized) {
    return true;
  }
  if (isSocialChatPrompt(normalized)) {
    return false;
  }
  return AMBIGUOUS_REFERENCE_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function buildSharedBrainAckText(_workload: SharedBrainWorkload): string {
  // Return empty — frontend loading indicator handles the pending state.
  // Legacy ack strings are tracked separately in TRANSIENT_ASSISTANT_ACKS
  // in inference.ts so existing sessions in DB are still filtered correctly.
  return "";
}

export function buildClarificationPrompt(prompt: string): string {
  const normalized = compactText(prompt).toLowerCase();
  if (/^(bunu|şunu|sunu|this|that)$/i.test(normalized)) {
    return "Netleştireyim: tam olarak hangi şeyi kastediyorsun?";
  }
  if (/(düzelt|duzelt|fix|improve|optimize|iyileştir|iyilestir)/i.test(normalized)) {
    return "Netleştireyim: tam olarak hangi kısmı iyileştirmemi istiyorsun?";
  }
  if (/(anlat|açıkla|acikla|summarize|explain)/i.test(normalized)) {
    return "Netleştireyim: hangi konuya odaklanmamı istiyorsun?";
  }
  return "Netleştireyim: tam olarak neyi yapmamı istiyorsun?";
}

export function selectHybridMobileChatWorkload(input: {
  message: string;
  primaryIntent: string;
  brainProfile?: PlanBrainProfile | null;
}): Extract<SharedBrainWorkload, "mobile_chat_fast" | "mobile_chat_balanced" | "planning"> {
  if (input.primaryIntent === "planning") {
    return "planning";
  }

  const normalized = compactText(input.message);
  if (!normalized || isSocialChatPrompt(normalized)) {
    return "mobile_chat_fast";
  }

  const questionCount = (normalized.match(/\?/g) ?? []).length;
  const sentenceCount = normalized
    .split(/[.!?]+/)
    .map((part) => part.trim())
    .filter(Boolean).length;
  const wordCount = normalized.split(/\s+/).filter(Boolean).length;
  const hasListStructure = /\n|[:]\s*$|(^|\s)(1\.|2\.|3\.|- )/m.test(normalized);
  const hasLongSingleSentence =
    sentenceCount <= 1 &&
    (normalized.length >= 120 || wordCount >= 18);
  const hasMultiClauseQuestion =
    questionCount >= 1 &&
    (/\b(ve|ama|çünkü|how|why|neden|nasıl|acikla|açıkla)\b/i.test(normalized) || wordCount >= 16);
  const isPremiumReasoningProfile =
    input.brainProfile?.tier === "premium" || Number(input.brainProfile?.reasoningMultiplier ?? 1) >= 5;
  const isEnhancedReasoningProfile =
    isPremiumReasoningProfile ||
    input.brainProfile?.qualityProfile === "solo_enhanced" ||
    Number(input.brainProfile?.reasoningMultiplier ?? 1) >= 3;
  const hasAnalysisSignals = BALANCED_PROFILE_PATTERNS.some((pattern) => pattern.test(normalized));

  if (isPremiumReasoningProfile) {
    const shouldUsePlanning =
      (normalized.length >= 220 || wordCount >= 40 || questionCount >= 2 || sentenceCount >= 4) &&
      (hasAnalysisSignals || hasListStructure || normalized.length >= 260);

    if (shouldUsePlanning) {
      return "planning";
    }

    const isBalancedByStructure =
      normalized.length >= 110 ||
      wordCount >= 20 ||
      sentenceCount >= 2 ||
      hasListStructure ||
      hasLongSingleSentence ||
      hasMultiClauseQuestion;

    if (isBalancedByStructure || hasAnalysisSignals) {
      return "mobile_chat_balanced";
    }

    return "mobile_chat_fast";
  }

  if (isEnhancedReasoningProfile) {
    const shouldUsePlanning =
      (normalized.length >= 260 || wordCount >= 44 || questionCount >= 3 || sentenceCount >= 4) &&
      (hasAnalysisSignals || hasListStructure);

    if (shouldUsePlanning) {
      return "planning";
    }

    if (
      hasAnalysisSignals ||
      normalized.length >= 140 ||
      wordCount >= 24 ||
      questionCount >= 2 ||
      sentenceCount >= 2 ||
      hasListStructure ||
      hasLongSingleSentence ||
      hasMultiClauseQuestion
    ) {
      return "mobile_chat_balanced";
    }
  }

  const isBalancedByStructure =
    normalized.length >= 110 ||
    wordCount >= 18 ||
    questionCount >= 2 ||
    sentenceCount >= 2 ||
    hasListStructure ||
    hasLongSingleSentence ||
    hasMultiClauseQuestion;

  if (isBalancedByStructure) {
    return "mobile_chat_balanced";
  }

  if (hasAnalysisSignals) {
    return "mobile_chat_balanced";
  }

  return "mobile_chat_fast";
}
