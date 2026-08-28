import type { PlanBrainProfile } from "../billing/catalog.js";
import type { SharedBrainWorkload } from "./workloads.js";
import { contentTerms } from "./lexical-turkish.js";

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
  /^(lan|la|olm|oğlum|oglum|kanka|dostum|bro)[!?.\s]*$/i,
  /\b(nasılsın|nasilsin|naber|napıyorsun|napiyorsun|ne yapıyorsun|ne yapiyorsun)\b/i,
  /\b(how are you|what'?s up|whats up)\b/i,
  /\b(keyifler nasıl|keyifler nasil)\b/i,
  /\b(teşekkürler|tesekkurler|teşekkür ederim|tesekkur ederim|sağ ol|sag ol|sağol|sagol|sağ olun|sag olun|kolay gelsin|iyi akşamlar|iyi aksamlar|iyi sabahlar|günaydın|gunaydin|iyi geceler)\b/i,
  /\b(görüşürüz|gorusuruz|hoşça kal|hosca kal|bye|good night)\b/i,
  /\b(sıkıldım|sikildim|canım sıkılıyor|canim sikiliyor|i(?:'|’)m bored)\b/i,
  /\b(seni seviyorum|iyi ki varsın|iyi ki varsin|love you)\b/i,
  /^(tamam|peki|olur|okey|okay)[!?.\s]*$/i,
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

/**
 * Math / formula / graph / plot signals — short prompts like "Z = x^5 - y^2
 * fonksiyonunun 3 boyutlu grafiğini çiz" are well under the length thresholds
 * that normally push a turn from fast → balanced, so the fast model
 * (gpt-oss-20b) was getting handed analytical work it can't reliably finish,
 * producing empty streams / placeholder Turkish like "Tamamlamak için eksik
 * yanıtı paylaşın". This pattern set escalates them to the reasoning model
 * (mobile_chat_balanced → gpt-oss-120b + reasoning_effort=medium) before the
 * length heuristics ever run.
 */
const MATH_REASONING_PATTERNS = [
  // Power / variable algebraic forms: x^2, y^3, z^n
  /\b[a-z]\s*\^\s*-?\d/i,
  // Function notation: f(x), g(t), h(x,y)
  /\b[a-z]\s*\(\s*[a-z](\s*,\s*[a-z])*\s*\)/i,
  // Equation with a power on the right side (Z = x^5 - y^2 etc.)
  /=\s*[^=]*[a-z]\s*\^/i,
  // Turkish math vocabulary
  /\b(fonksiyon(?:un|unu|un'?un)?|denklem(?:i|in|inin)?|t[üu]rev(?:i|in|ini|ler)?|integral(?:i|in|ini)?|matris(?:i|in|ler)?|polinom|limit|formül|kök(?:l[eü]r|ünü)?|olas[ıi]l[ıi]k|i̇statistik|istatistik|trigonometri|cebir|geometri|kalkulüs|kalk[üu]l[üu]s)\b/i,
  // University-course math vocabulary. Adding these because a plain
  // "Bana ileri analiz dersinden örnek soru yaz" was routing to
  // mobile_chat_fast (224 tokens) and getting cut off mid-`\begin{cases}`.
  // These keywords should surface a real reasoning budget.
  /\b((?:ileri|reel|karma[şs][ıi]k|complex|real)\s+analiz|analiz\s+dersi|kalk[üu]l[üu]s\s+dersi|topoloji|diferansiyel\s+denklem|linear\s+algebra|abstract\s+algebra|analiz\s+I|analiz\s+II)\b/i,
  // Analysis / topology concept words: presence of any is a strong signal.
  /\b(noktasal|uniform|s[üu]reklilik|continuity|yak[ıi]nsama|convergence|divergence|iraksama|dizinin|serinin|series|sequence|supremum|infimum|epsilon|delta|kompakt|compact|metrik|metric|norm|banach|hilbert|lebesgue|riemann|cauchy|fourier|taylor|maclaurin)\b/i,
  // Turkish graph / plot vocabulary
  /\b(grafi[ğg]ini|grafi[ğg]i\s+(?:[çc]iz|göster|olu[şs]tur)|grafi[ğg]ini\s+(?:[çc]iz|göster|olu[şs]tur)|grafi[ğg]ini\s+(?:hesapla)|grafi[ğg]i\b|grafik\s+[çc]iz|[çc]iz(?:dir|in)?\b|plot(?:la)?\b)\b/i,
  // 3D / N-D phrasing
  /\b(3\s*(?:d\b|boyut(?:lu|unda)?))\b/i,
  /\b(iki|üç|dört|beş|altı|three|two|four)\s+boyutlu\b/i,
  // Common math operators that signal real arithmetic, not chit-chat
  /\b(sin|cos|tan|cot|log|ln|exp|sqrt|abs|min|max|sum|prod)\s*\(/i,
  // Unicode math glyphs
  /[∫∑∏∂√≈≠≤≥π∞ƒ∇]/,
];

export function hasMathReasoningSignal(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized) return false;
  return MATH_REASONING_PATTERNS.some((pattern) => pattern.test(normalized));
}

const BALANCED_PROFILE_PATTERNS = [
  /\b(karşılaştır|karsilastir|compare|tradeoff|artı|arti|eksi|pros|cons)\b/i,
  /\b(adım adım|adim adim|step by step|detaylı|detayli|derinlemesine|deep dive)\b/i,
  /\b(neden|niye|how exactly|why|explain|açıkla|acikla|anlat)\b/i,
  /\b(örneklerle|orneklerle|examples|alternatif|alternatives|opsiyon)\b/i,
  /\b(özetle|ozetle|değerlendir|degerlendir|analyze|analiz et|incele)\b/i,
  // Lecture / homework / practice-question requests. "Bana örnek soru yaz"
  // used to fall through to mobile_chat_fast because none of the earlier
  // patterns matched — but the answer itself is inherently long (problem
  // statement + numbered parts + solution plan). Route to balanced instead.
  /\b(örnek\s+(?:soru|problem|sorular|problems)|example\s+(?:question|problem|exam)|sample\s+(?:question|problem)|practice\s+(?:question|problem|set)|homework|ödev|proje\s+sorusu|sınav\s+sorusu|midterm|final\s+sorusu|worksheet|problem\s+set|ders\s+notu|lecture\s+note)\b/i,
  /\b(yaz\s+bana|write\s+me|give\s+me|(?:bir|an?)\s+örnek\s+(?:ver|göster|yaz)|(?:kanıt|ispat|proof)\s+(?:yaz|göster|ver))\b/i,
  /\b(profesyonel(?:ce)?|imla|yeniden yaz|tekrar yaz|düzgün Türkçe|dogru turkce|doğru türkçe|kısa ve net|kisa ve net|madde madde|maddeler halinde)\b/i,
  /\b(pdf|docx|xlsx|pptx|belge|dokuman|döküman|dosya|görsel|gorsel|metin|içerik|icerik|özetini çıkar|ozetini cikar|bunda ne yazıyor|bunda ne yaziyo|içinde ne var|icinde ne var|tarat|tarama|ocr|çeviri|ceviri|tercüme|tercume|gramer|grammar|lehçe|lehce|alfabe|söz varlığı|soz varligi|kelime hazinesi)\b/i,
  /\b(türk dünyası|turkic|oğuz|oguz|kıpçak|kipchak|karluk|qipchak|qarluq|azerbaijani|kazakh|kyrgyz|uzbek|turkmen|uyghur|tatar|bashkir|gagauz|karakalpak|sakha|chuvash)\b/i,
  /\b(yarım bırakma|yarim birakma|yarım kalmasın|yarim kalmasin|tamamla|tamamlanmış|bitir|bozma|daha akıllı|daha zeki|net sonuç|uzatma ama eksik bırakma)\b/i,
  // Türkçe ek/çekim toleransı: "karşılaştırmanı", "özetler misin", "açıklar
  // mısın", "değerlendirmeni", "inceler misin" gibi çekimli analiz fiilleri
  // \b tabanlı desenlerden kaçıyordu (JS \b ASCII'dir: kökten sonra gelen ek
  // ASCII harfle başlayınca sınır oluşmaz ve eşleşme düşer). Kök + \p{L}* ile
  // tüm ek zincirine izin ver; (?<!\p{L}) kök başlangıcını kelime başına
  // sabitler.
  /(?<!\p{L})(karşılaştır|karsilastir|kıyasla|kiyasla|özetle|ozetle|açıkla|acikla|anlat|değerlendir|degerlendir|incele|analiz|detaylandır|detaylandir)\p{L}*/iu,
];

const REFERENTIAL_PRONOUN_PATTERN =
  /(?<!\p{L})(bunu|şunu|sunu|onu|buna|şuna|suna|ona|bundan|şundan|sundan|ondan|this|that|it)\p{L}*/iu;

const COMPARATIVE_STRUCTURE_PATTERNS = [
  /\b[\p{L}\d][^?\n]{0,48}\s+(?:vs\.?|versus)\s+[\p{L}\d]/iu,
  /(?<!\p{L})(hangisi|hangisini)\s+daha\p{L}*/iu,
  /(?<!\p{L})fark\p{L}{0,8}\s+(?:nedir|ne|neler|nelerdir|a[çc][ıi]kla|anlat)\b/iu,
  /(?<!\p{L})(arasında|arasinda|arasındaki|arasindaki)\s+(?:ne\s+)?fark\p{L}*/iu,
];

const CODE_CONTEXT_PATTERNS = [
  /```[\s\S]*?```/,
  /`[^`\n]+`/,
  /\.(?:ts|tsx|js|jsx|py|swift|dart|go|rs|java|kt|sql|json|yaml|yml|html|css)\b/i,
  /(?<!\p{L})(code|kod\p{L}*|function|class|const|let|var|import|export|async|await|return|try|catch|interface|type|enum|struct|widget|component)\b/iu,
];
const BRIEF_PROSE_PATTERNS = [
  /(?<!\p{L})(k[ıi]saca|[öo]zetle|[öo]zet halinde|paragraf halinde|paragraf olarak|tek c[üu]mle\p{L}*)(?!\p{L})/iu,
];
const CONTEXT_HEAVY_PROSE_PATTERNS = [
  /(?<!\p{L})(pdf|docx|xlsx|pptx|belge|dokuman|d[öo]k[üu]man|dosya|ekli|metin|i[çc]erik|ocr|tarama|profesyonel\p{L}*|d[üu]zenli|redakte|imla|gramer|grammar)(?!\p{L})/iu,
];

function hasReferentialPronoun(prompt: string): boolean {
  return REFERENTIAL_PRONOUN_PATTERN.test(prompt);
}

function hasComparativeStructure(prompt: string): boolean {
  return COMPARATIVE_STRUCTURE_PATTERNS.some((pattern) => pattern.test(prompt));
}

function hasCodeContext(prompt: string): boolean {
  return CODE_CONTEXT_PATTERNS.some((pattern) => pattern.test(prompt));
}

function hasBriefProsePreference(prompt: string): boolean {
  return BRIEF_PROSE_PATTERNS.some((pattern) => pattern.test(prompt));
}

function hasContextHeavyProseWork(prompt: string): boolean {
  return CONTEXT_HEAVY_PROSE_PATTERNS.some((pattern) => pattern.test(prompt));
}

/* ── Kısa takip mesajları ──────────────────────────────────────────────────
 * "anlamadım", "devam et", "onu düzelt" gibi mesajlar önceki tura referans
 * verir; bağlamsız yorumlanınca model alakasız yeni bir cevap üretiyor.
 * Bu tespit inference tarafında rollingSummary + lastAssistantBlocksDigest'i
 * zorunlu bağlam yapmak için kullanılır. */
const SHORT_FOLLOWUP_PATTERNS = [
  // \b yerine (?!\p{L}): Türkçe harfle biten köklerde ("olmadı", "anlamadım")
  // ASCII \b satır sonunda sınır üretmez ve desen sessizce kaçar.
  /^(anlamadım|anlamadim|anlayamadım|anlayamadim|anlamıyorum|anlamiyorum)(?!\p{L})/iu,
  /^(devam|devam et|devam eder misin|kaldığın yerden devam|kaldigin yerden devam|continue|go on)(?!\p{L})/iu,
  /^(onu|bunu|şunu|sunu)\s+(düzelt|duzelt|kısalt|kisalt|uzat|değiştir|degistir|düzenle|duzenle|çevir|cevir|tamamla|iyileştir|iyilestir|yeniden yaz|tekrar yaz|fix|redo|improve)\p{L}*$/iu,
  /^(tekrar|yeniden|bir daha)( dene| yap| yaz| dener misin| yapar mısın| yapar misin)?$/iu,
  /^daha (kısa|kisa|uzun|detaylı|detayli|basit|net|iyi|sade)( yaz| yap| anlat| olsun| açıkla| acikla)?$/iu,
  /^(olmadı|olmadi|olmamış|olmamis|beğenmedim|begenmedim)(?!\p{L})/iu,
  /^(yanlış|yanlis|hatalı|hatali)( oldu| olmuş| olmus| bu)?$/iu,
  /^(evet devam|tamam devam|peki devam)(?!\p{L})/iu,
];

export function isShortFollowUpPrompt(prompt: string): boolean {
  const normalized = compactText(prompt)
    .toLocaleLowerCase("tr-TR")
    .replace(/[?!.…]+$/u, "")
    .trim();
  if (!normalized || normalized.length > 40) {
    return false;
  }
  if (normalized.split(/\s+/).length > 5) {
    return false;
  }
  if (isSocialChatPrompt(normalized)) {
    return false;
  }
  return SHORT_FOLLOWUP_PATTERNS.some((pattern) => pattern.test(normalized));
}

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

/**
 * SOSYAL TURDA SELAM MESAJIN KENDİSİDİR — İÇİNDEKİ İÇERİK DEĞİL.
 *
 * ÖLÇÜLEN ARIZA (2026-08-28): "Bu cümleyi İngilizceye çevir: yarın
 * görüşürüz" isteği ucuz sosyal yola düşüyor ve kullanıcı çeviri yerine
 * "Görüşürüz." cevabını alıyordu. Model doğru cevabı üretiyordu ("See you
 * tomorrow."); tur ona hiç ulaşmıyordu. Aynı şekilde:
 *   "Şu cümleyi düzelt: merhaba nasilsin"
 *   "\"iyi geceler\" ne demek İngilizce?"
 *   "Günaydın kelimesinin kökeni nedir?"
 * Desenler istemin HERHANGİ bir yerinde eşleşiyordu; oysa o selamlar
 * kullanıcının SORDUĞU şeydi.
 *
 * Ayırt edici yapısaldır ve yeni kelime listesi gerektirmez: sosyal
 * eşleşmeler çıkarıldıktan sonra geriye ANLAMLI kelime kalıyor mu?
 *
 *   sosyal   "Merhaba, nasılsın?"          → 0 terim
 *            "Selam Elyan, nasıl gidiyor?" → 1 terim (bir isim)
 *   istek    "Şu cümleyi düzelt: …"        → 2 terim [cümle, düzelt]
 *            "Günaydın kelimesinin kökeni" → 3 terim [kelime, köken, nedir]
 *            "…İngilizceye çevir: …"       → 4 terim
 *
 * Bir artık kelime bir isim ya da dolgudur; iki ve üstü bir istektir.
 */
const MAX_SOCIAL_RESIDUE_TERMS = 1;

function socialResidueTermCount(normalized: string): number {
  let residue = normalized;
  for (const pattern of [...GREETING_PREFIX_PATTERNS, ...SOCIAL_CHAT_PATTERNS]) {
    residue = residue.replace(new RegExp(pattern.source, "giu"), " ");
  }
  for (const exact of GREETING_EXACT_MATCHES) {
    residue = residue.replaceAll(exact, " ");
  }
  return contentTerms(residue, { limit: 12 }).length;
}

export function isSocialChatPrompt(prompt: string): boolean {
  const normalized = compactText(prompt).toLowerCase();
  if (!normalized) {
    return false;
  }
  // Tam eşleşme zaten istemin TAMAMIDIR; artık kontrolüne gerek yok.
  if (GREETING_EXACT_MATCHES.has(normalized)) {
    return true;
  }
  const matchesSocial =
    isGreetingLikePrompt(normalized) ||
    SOCIAL_CHAT_PATTERNS.some((pattern) => pattern.test(normalized));
  if (!matchesSocial) {
    return false;
  }
  return socialResidueTermCount(normalized) <= MAX_SOCIAL_RESIDUE_TERMS;
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

export function buildSharedBrainAckText(workload: SharedBrainWorkload): string {
  void workload;
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

  // Math / formula / graph prompts can be very short ("Z=x^5-y^2 3D çiz") but
  // demand real reasoning. Route them straight to the reasoning model before
  // any length heuristic decides "small message → fast model". For premium
  // profiles, kick all the way up to planning so we get the full reasoning
  // budget for surfaces, integrals, fits, etc.
  const isMathReasoningTurn = hasMathReasoningSignal(normalized);
  const isPremiumReasoningProfileEarly =
    input.brainProfile?.tier === "premium" ||
    Number(input.brainProfile?.reasoningMultiplier ?? 1) >= 5;
  if (isMathReasoningTurn) {
    return isPremiumReasoningProfileEarly ? "planning" : "mobile_chat_balanced";
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
  const referentialPronoun = hasReferentialPronoun(normalized);
  const comparativeStructure = hasComparativeStructure(normalized);
  const codeContext = hasCodeContext(normalized);
  const briefProsePreference = hasBriefProsePreference(normalized);
  const contextHeavyProseWork = hasContextHeavyProseWork(normalized);
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

  const calibrationScore =
    (referentialPronoun ? 2 : 0) +
    (comparativeStructure ? 2 : 0) +
    (hasListStructure ? 1 : 0) +
    (hasMultiClauseQuestion ? 1 : 0) -
    (codeContext ? 2 : 0);
  const smallCodeContext =
    codeContext &&
    normalized.length < 180 &&
    wordCount < 32 &&
    questionCount <= 1 &&
    sentenceCount <= 2 &&
    !hasListStructure &&
    !comparativeStructure;

  if (smallCodeContext && calibrationScore <= 0) {
    return "mobile_chat_fast";
  }

  if (
    briefProsePreference &&
    wordCount <= 14 &&
    questionCount <= 1 &&
    sentenceCount <= 2 &&
    !referentialPronoun &&
    !comparativeStructure &&
    !codeContext &&
    !contextHeavyProseWork &&
    !hasListStructure
  ) {
    return "mobile_chat_fast";
  }

  const isBalancedByStructure =
    normalized.length >= 110 ||
    wordCount >= 18 ||
    questionCount >= 2 ||
    sentenceCount >= 2 ||
    hasListStructure ||
    hasLongSingleSentence ||
    hasMultiClauseQuestion;

  if (isBalancedByStructure || calibrationScore >= 2) {
    return "mobile_chat_balanced";
  }

  if (hasAnalysisSignals) {
    return "mobile_chat_balanced";
  }

  return "mobile_chat_fast";
}
