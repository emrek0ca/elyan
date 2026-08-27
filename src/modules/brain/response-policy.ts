import type { SharedBrainWorkload } from "./workloads.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

export type ElyanTurnIntent =
  | "casual_chat"
  | "creative_answer"
  | "writing"
  | "technical_help"
  | "math"
  | "web_research"
  | "url_review"
  | "image_generation"
  | "vision_or_attachment"
  | "document_help"
  | "task_execution"
  | "unknown";

const URL_PATTERN = /https?:\/\/[^\s<>"')]+/i;
const IMAGE_GENERATION_PATTERN =
  /(?<!\p{L})(görsel\p{L}*|gorsel\p{L}*|resm\p{L}*|foto\p{L}*|image|picture|illustration|poster|afiş\p{L}*|afis\p{L}*)(?!\p{L}).{0,50}(?<!\p{L})(çiz\p{L}*|ciz\p{L}*|oluştur\p{L}*|olustur\p{L}*|üret\p{L}*|uret\p{L}*|generate|create|draw|make)(?!\p{L})|(?<!\p{L})(çiz\p{L}*|ciz\p{L}*|oluştur\p{L}*|olustur\p{L}*|üret\p{L}*|uret\p{L}*|generate|create|draw|make)(?!\p{L}).{0,50}(?<!\p{L})(görsel\p{L}*|gorsel\p{L}*|resm\p{L}*|foto\p{L}*|image|picture|illustration|poster|afiş\p{L}*|afis\p{L}*)(?!\p{L})/iu;
const CASUAL_CHAT_PATTERN =
  /^(?:selam|merhaba|slm|hey|hi|hello|naber|nasılsın|nasilsin|teşekkürler|tesekkurler|sağ ol|sag ol|sağol|sagol|lan|la|olm|oğlum|oglum|kanka|dostum|bro)(?:\s+(?:nasılsın|nasilsin|naber|how are you))?[.!?\s]*$/iu;
const CREATIVE_PATTERN =
  /(?<!\p{L})(garip|tuhaf|değişik|degisik|bilinmeyen|yaratıcı|yaratici|komik|ilginç|ilginc|hikaye|şiir|siir|isim|slogan|fikir|öner|oner)(?!\p{L})/iu;
const WRITING_PATTERN =
  /(?<!\p{L})(tweet|x paylaşımı|x paylasimi|mail|e-?posta|metin|caption|başlık|baslik|bio|duyuru|ilan|yaz|düzenle|duzenle|yeniden yaz|rewrite|çevir|cevir|özetle|ozetle)(?!\p{L})/iu;
const TECHNICAL_PATTERN =
  /(?<!\p{L})(kod|code|debug|hata|error|stack trace|typescript|javascript|python|swift|flutter|dart|sql|api|backend|frontend|regex|bug)(?!\p{L})/iu;
const MATH_PATTERN =
  /(?<!\p{L})(matematik\p{L}*|denklem\p{L}*|integral|türev\p{L}*|turev\p{L}*|limit|olasılık\p{L}*|olasilik\p{L}*|formül\p{L}*|formula|hesapla\p{L}*|çöz\p{L}*|coz\p{L}*)(?!\p{L})|[∫∑∏√≈≠≤≥π∞]|\d+\s*[+\-−×xX*÷/^]\s*\d+/iu;
const DOCUMENT_PATTERN =
  /(?<!\p{L})(pdf|docx|xlsx|pptx|belge|doküman|dokuman|dosya|ocr|scan|tarama|özetini çıkar|ozetini cikar)(?!\p{L})/iu;
const VISION_PATTERN =
  /(?<!\p{L})(görseli oku|gorseli oku|resimde|fotoğrafta|fotografta|ekran görüntüsü|ekran goruntusu|vision|ocr)(?!\p{L})/iu;
const TASK_EXECUTION_PATTERN =
  /(?<!\p{L})(yap|oluştur|olustur|hazırla|hazirla|çalıştır|calistir|araştır|arastir|incele|kontrol et|kaydet|export)(?!\p{L})/iu;
const EXPLICIT_WEB_RESEARCH_PATTERN =
  /(?<!\p{L})(kaynaklı|kaynakli|kaynak göster|kaynak goster|source-backed|cite sources|webden|internetten|internette ara|web search|search the web|look up|browse|araştır|arastir)(?!\p{L})/iu;
const EXPLICIT_WEB_REQUIRED_PATTERN =
  /(?<!\p{L})(kaynak\p{L}*|resmi kaynak\p{L}*|source-backed|cite sources|with sources|official sources|online|webden|internetten|internette ara|web araştır|web arastir|internet araştır|internet arastir|web search|search the web|look up|browse)(?!\p{L})/iu;
const LIVE_DATA_SUBJECT_PATTERN =
  /(?<!\p{L})(haber|news|fiyat|price|kur|dolar|usd|euro|eur|altın|altin|bitcoin|btc|ethereum|eth|kripto|borsa|hisse|hava durumu|weather|forecast|maç sonucu|mac sonucu|skor|puan durumu|fikstür|fikstur|cve|vulnerability|güvenlik açığı|guvenlik acigi|son sürüm|son surum|latest version|release notes?|changelog)(?!\p{L})/iu;
const VERIFICATION_REQUIRED_SUBJECT_PATTERN =
  /(?<!\p{L})(mevzuat|yasa|kanun|yönetmelik|yonetmelik|regülasyon|regulasyon|regulation|resmi gazete)(?!\p{L})/iu;
const LONG_FORM_PATTERN =
  /(?<!\p{L})(detaylı|detayli|uzun|adım adım|adim adim|kapsamlı|kapsamli|derinlemesine|rapor|makale|essay|long form)(?!\p{L})/iu;
const SHORT_FORM_PATTERN =
  /(?<!\p{L})(kısaca|kisaca|çok kısa|cok kisa|tek cümle|tek cumle|uzatma|kısa ve net|kisa ve net)(?!\p{L})/iu;

const ROBOTIC_PHRASE_PATTERNS = [
  /(?:elimde|bende)\s+kesin\s+kayıtlı\s+kanıt\s+yok/iu,
  /kesin\s+kayıtlı\s+bir\s+kanıt\s+bulunmuyor/iu,
  /bunu\s+doğrulayamıyorum/iu,
  /doğrulayamıyorum/iu,
  /kanıt\s+olmadığı\s+için/iu,
  /bir\s+ai\s+olarak/iu,
  /model\s+olarak/iu,
  /kaynaklara\s+göre/iu,
];

const INTERNAL_FENCE_PATTERN = /```elyan:blocks\s*[\s\S]*?```/giu;
const INTERNAL_LINE_PATTERN =
  /^\s*(?:route[_ -]?decision|selected[_ -]?workload|tool[_ -]?trace|debug|metadata|reasoning|analysis|intent|system[_ -]?prompt|developer[_ -]?message|fresh[_ -]?data|web[_ -]?grounding|provider|model|raw|internal)\s*[:=]/iu;
const INTERNAL_JSON_KEY_PATTERN =
  /"(?:route[_ -]?decision|selected[_ -]?workload|tool[_ -]?trace|debug|metadata|reasoning|analysis|intent|system[_ -]?prompt|developer[_ -]?message|fresh[_ -]?data|web[_ -]?grounding|provider|model|raw|internal)"\s*:/iu;
const JSONISH_LINE_PATTERN = /^\s*(?:\{[\s\S]*\}|\[[\s\S]*\])\s*[,;]?\s*$/u;
const CURRENT_NUMERIC_CLAIM_PATTERN =
  /(?=.*(?<!\p{L})(bugün|bugun|şu an|su an|güncel|guncel|canlı|canli|anlık|anlik|today|current|currently|live|now)(?!\p{L}))(?=.*(?:\d|₺|\$|€|£|%)).+/iu;
const CURRENT_STATUS_CLAIM_PATTERN =
  /^(?!.*(?<!\p{L})(doğrula\p{L}*|dogrula\p{L}*|bulamad\p{L}*|ulaşamad\p{L}*|ulasamad\p{L}*|erişemed\p{L}*|erise\p{L}*|alamad\p{L}*|yetersiz|emin değil\p{L}*|emin degil\p{L}*|can't|cannot|couldn't|unable|not enough|unverified)(?!\p{L}))(?=.*(?<!\p{L})(bugün|bugun|şu an|su an|güncel|guncel|canlı|canli|today|current|currently|live|now|latest)(?!\p{L})).+/iu;
const IMAGE_SUCCESS_WITHOUT_ARTIFACT_PATTERN =
  /(?<!\p{L})(görsel|gorsel|resim|foto|image|picture)(?!\p{L}).{0,80}(?<!\p{L})(hazır|hazir|oluşturdum|olusturdum|ürettim|urettim|created|generated|ready)(?!\p{L})|(?<!\p{L})(hazır|hazir|oluşturdum|olusturdum|ürettim|urettim|created|generated|ready)(?!\p{L}).{0,80}(?<!\p{L})(görsel|gorsel|resim|foto|image|picture)(?!\p{L})/iu;
const ARTIFACT_SUCCESS_WITHOUT_OUTPUT_PATTERN =
  /(?<!\p{L})(pdf|docx|xlsx|pptx|belge|doküman|dokuman|dosya|spreadsheet|sunum|presentation|çıktı|cikti|output)(?!\p{L}).{0,80}(?<!\p{L})(hazır|hazir|oluşturdum|olusturdum|ürettim|urettim|tamamlandı|tamamlandi|created|generated|completed|ready)(?!\p{L})|(?<!\p{L})(hazır|hazir|oluşturdum|olusturdum|ürettim|urettim|tamamlandı|tamamlandi|created|generated|completed|ready)(?!\p{L}).{0,80}(?<!\p{L})(pdf|docx|xlsx|pptx|belge|doküman|dokuman|dosya|spreadsheet|sunum|presentation|çıktı|cikti|output)(?!\p{L})/iu;

export function classifyElyanTurnIntent(prompt: string): ElyanTurnIntent {
  const normalized = compactText(prompt);
  if (!normalized) return "unknown";
  if (URL_PATTERN.test(normalized)) return "url_review";
  if (IMAGE_GENERATION_PATTERN.test(normalized)) return "image_generation";
  if (
    EXPLICIT_WEB_RESEARCH_PATTERN.test(normalized) ||
    LIVE_DATA_SUBJECT_PATTERN.test(normalized) ||
    VERIFICATION_REQUIRED_SUBJECT_PATTERN.test(normalized)
  ) return "web_research";
  if (VISION_PATTERN.test(normalized)) return "vision_or_attachment";
  if (DOCUMENT_PATTERN.test(normalized)) return "document_help";
  if (MATH_PATTERN.test(normalized)) return "math";
  if (TECHNICAL_PATTERN.test(normalized)) return "technical_help";
  if (WRITING_PATTERN.test(normalized)) return "writing";
  if (CASUAL_CHAT_PATTERN.test(normalized)) return "casual_chat";
  if (CREATIVE_PATTERN.test(normalized)) return "creative_answer";
  if (TASK_EXECUTION_PATTERN.test(normalized)) return "task_execution";
  return "unknown";
}

export function responsePolicyForPrompt(prompt: string): {
  intent: ElyanTurnIntent;
  webRequired: boolean;
  requestedLongForm: boolean;
  requestedShortForm: boolean;
  simpleSelfContained: boolean;
} {
  const normalized = compactText(prompt);
  const intent = classifyElyanTurnIntent(normalized);
  const requestedLongForm = LONG_FORM_PATTERN.test(normalized);
  const requestedShortForm = SHORT_FORM_PATTERN.test(normalized);
  const wordCount = normalized.split(/\s+/).length;
  const simpleSelfContained =
    !requestedLongForm &&
    (
      (["casual_chat", "creative_answer", "writing", "math"].includes(intent) && wordCount <= 18) ||
      (intent === "unknown" && wordCount <= 10)
    );
  return {
    intent,
    webRequired:
      intent === "url_review" ||
      EXPLICIT_WEB_REQUIRED_PATTERN.test(normalized) ||
      LIVE_DATA_SUBJECT_PATTERN.test(normalized) ||
      VERIFICATION_REQUIRED_SUBJECT_PATTERN.test(normalized),
    requestedLongForm,
    requestedShortForm,
    simpleSelfContained,
  };
}

function removeRoboticVerificationLanguage(value: string, allowVerificationLanguage: boolean): string {
  if (allowVerificationLanguage) {
    return value;
  }
  let insideFence = false;
  const lines: string[] = [];
  for (const line of value.split("\n")) {
    if (/^\s*```/.test(line)) {
      insideFence = !insideFence;
      lines.push(line);
      continue;
    }
    if (insideFence) {
      lines.push(line);
      continue;
    }
    if (!line.trim()) {
      lines.push("");
      continue;
    }
    const kept = line
      .split(/(?<=[.!?…])\s+/u)
      .map((sentence) => sentence.trim())
      .filter(Boolean)
      .filter((sentence) => !ROBOTIC_PHRASE_PATTERNS.some((pattern) => pattern.test(sentence)))
      .join(" ");
    if (kept) {
      lines.push(kept);
    }
  }
  const cleaned = lines.join("\n");
  return cleaned
    .replace(/\s+([,.!?;:])/g, "$1")
    .replace(/(?:^|\n)\s*[,.;:]\s*/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function dedupeRepeatedParagraphs(value: string): string {
  const seen = new Set<string>();
  const paragraphs: string[] = [];
  for (const paragraph of value.split(/\n{2,}/)) {
    const trimmed = paragraph.trim();
    if (!trimmed) continue;
    const key = trimmed.toLocaleLowerCase("tr-TR").replace(/\s+/g, " ");
    if (seen.has(key)) continue;
    seen.add(key);
    paragraphs.push(trimmed);
  }
  return paragraphs.join("\n\n").trim();
}

function stripInternalLinesPreservingCodeFences(value: string): string {
  let insideFence = false;
  const lines: string[] = [];
  let jsonBuffer: string[] = [];
  let jsonDepth = 0;
  const flushJsonBuffer = () => {
    if (jsonBuffer.length === 0) {
      return;
    }
    const joined = jsonBuffer.join("\n");
    if (!INTERNAL_JSON_KEY_PATTERN.test(joined)) {
      lines.push(...jsonBuffer);
    }
    jsonBuffer = [];
    jsonDepth = 0;
  };
  const countJsonDepthDelta = (line: string) => {
    let delta = 0;
    let inString = false;
    let escaped = false;
    for (const char of line) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (char === "\\") {
        escaped = inString;
        continue;
      }
      if (char === "\"") {
        inString = !inString;
        continue;
      }
      if (inString) {
        continue;
      }
      if (char === "{" || char === "[") delta += 1;
      if (char === "}" || char === "]") delta -= 1;
    }
    return delta;
  };
  for (const line of value.split("\n")) {
    if (/^\s*```/.test(line)) {
      flushJsonBuffer();
      insideFence = !insideFence;
      lines.push(line);
      continue;
    }
    if (!insideFence) {
      if (INTERNAL_LINE_PATTERN.test(line)) {
        continue;
      }
      if (jsonBuffer.length > 0 || /^\s*[\[{]/u.test(line)) {
        jsonBuffer.push(line);
        jsonDepth += countJsonDepthDelta(line);
        if (jsonDepth <= 0 || jsonBuffer.length >= 40) {
          const joined = jsonBuffer.join("\n");
          if (!(JSONISH_LINE_PATTERN.test(joined) && INTERNAL_JSON_KEY_PATTERN.test(joined))) {
            if (!INTERNAL_JSON_KEY_PATTERN.test(joined)) {
              lines.push(...jsonBuffer);
            }
          }
          jsonBuffer = [];
          jsonDepth = 0;
        }
        continue;
      }
    }
    lines.push(line);
  }
  flushJsonBuffer();
  return lines.join("\n").trim();
}

function guardMissingArtifact(input: {
  prompt: string;
  text: string;
  imageGenerationRequested?: boolean;
  artifactRequired?: boolean;
  hasRenderableOutput?: boolean;
}): string {
  if (
    input.hasRenderableOutput === true ||
    (
      input.artifactRequired !== true &&
      input.imageGenerationRequested !== true &&
      classifyElyanTurnIntent(input.prompt) !== "image_generation"
    )
  ) {
    return input.text;
  }
  const successPattern =
    input.imageGenerationRequested === true || classifyElyanTurnIntent(input.prompt) === "image_generation"
      ? IMAGE_SUCCESS_WITHOUT_ARTIFACT_PATTERN
      : ARTIFACT_SUCCESS_WITHOUT_OUTPUT_PATTERN;
  if (!successPattern.test(input.text)) {
    return input.text;
  }
  const looksTurkish =
    /[çğıöşüÇĞİÖŞÜ]/u.test(input.prompt) ||
    /(?<!\p{L})(görsel|gorsel|resim|foto|çiz|ciz|oluştur|olustur)(?!\p{L})/iu.test(input.prompt);
  if (input.imageGenerationRequested === true || classifyElyanTurnIntent(input.prompt) === "image_generation") {
    return looksTurkish
      ? "Görsel şu anda üretilemedi. Lütfen biraz sonra tekrar dene."
      : "I couldn't generate the image right now. Please try again shortly.";
  }
  return looksTurkish
    ? "İstenen çıktı şu anda üretilemedi. Hazır olmayan bir dosyayı tamamlanmış gibi göstermeyeceğim."
    : "I couldn't produce the requested output right now, so I won't present an unfinished file as complete.";
}

function limitSimpleAnswerLength(value: string, input: { simpleSelfContained: boolean; requestedShortForm: boolean; workload?: SharedBrainWorkload | string | null }): string {
  if (!value || (!input.simpleSelfContained && !input.requestedShortForm)) {
    return value;
  }
  if (/```/u.test(value)) {
    return value;
  }
  // Markdown listesi code fence gibi yapısaldır: cümle-sayısı kırpması
  // "1." işaretçisini cümle sonu sanıp listeyi başından buduyor (araç
  // sonuçlu "son 5 mail" özetleri ':' deyip bitiyordu).
  if (/^\s{0,3}(?:[-*+]\s|\d{1,2}[.)]\s)/mu.test(value)) {
    return value;
  }
  if (
    input.workload &&
    !["mobile_chat_fast", "mobile_chat_balanced", "fast_route", "intent"].includes(
      String(input.workload),
    )
  ) {
    return value;
  }
  const sentences = value.match(/[^.!?…]+[.!?…]?/gu) ?? [value];
  const maxSentences = input.requestedShortForm ? 2 : 3;
  return sentences.slice(0, maxSentences).join("").trim();
}

function guardUnsupportedCurrentClaims(input: {
  prompt: string;
  text: string;
  freshData?: {
    freshnessRequired: boolean;
    status: string;
    evidence: { sufficient: boolean };
  } | null;
}): string {
  if (
    !input.freshData?.freshnessRequired ||
    (
      input.freshData.evidence.sufficient &&
      input.freshData.status !== "stale" &&
      input.freshData.status !== "unavailable"
    )
  ) {
    return input.text;
  }
  const kept = input.text
    .split(/(?<=[!?…])\s+|(?<=\.)\s+(?=[A-ZÇĞİÖŞÜ])/gu)
    .map((sentence) => sentence.trim())
    .filter(Boolean)
    .filter(
      (sentence) =>
        !CURRENT_NUMERIC_CLAIM_PATTERN.test(sentence) &&
        !CURRENT_STATUS_CLAIM_PATTERN.test(sentence),
    );
  if (kept.length > 0) {
    return kept.join(" ").trim();
  }
  // CEVABIN TAMAMI SİLİNDİYSE: eskiden buradan sabit bir yedek cümle dönüyordu
  // ("Şu anda yeterli güncel kaynaktan doğrulanmış veri alamadım."). Canlı
  // arıza (2026-07-30): "bana bir şarkı öner" gibi güncellikle hiç ilgisi
  // olmayan bir istekte de bu cümle görünüyordu — kullanıcı bir öneri sordu,
  // kaynak raporu aldı.
  //
  // Bu kapı UYDURMA GÜNCEL VERİYE karşıdır: "dolar bugün 42 lira" gibi bir
  // iddia kanıtsız kalmamalı. Ama tek tek cümle eleyip geriye hiçbir şey
  // kalmaması, kapının niyetini aştığının işaretidir: ya istek zaten güncel
  // veri istemiyordu ya da desenler yanlış eşleşti. İki durumda da doğru
  // davranış cevabı TESLİM ETMEK, kullanıcıyı boş bırakmak değil.
  //
  // Ayrım korunuyor: kanıtsız güncel iddia taşıyan CÜMLELER hâlâ düşer
  // (yukarıdaki filtre). Düşen tek tek cümlelerdir, cevabın tamamı değil.
  return input.text;
}

/**
 * Çıktısı KULLANICI METNİ DEĞİL, MAKİNE VERİSİ olan iş yükleri.
 *
 * Bu turlarda model katı JSON üretir ve o JSON'u başka bir kod ayrıştırır;
 * kullanıcı asla görmez. Sohbet sanitizasyonu (cümle kırpma, "güncel iddia"
 * söküm kuralları, jenerik son-çare cümlesi) bu içeriği BOŞALTIR.
 *
 * Canlı kanıt (2026-08-08): semantik yönlendirici `fast_route` iş yüküyle
 * çalışıyordu. Model doğru JSON'u ÜRETİYORDU — doğrudan çağrıda
 * `finish_reason=stop` ve geçerli `{"operationalRoute":"desktop_runtime",...}`
 * dönüyordu — ama boru hattı bu JSON'u kullanıcıya gösterilemez sayıp
 * siliyor, geriye boş metin kalıyor ve tur "Bu kez düzgün bir yanıt
 * oluşturamadım" cümlesine düşüyordu. Yönlendirici bu yüzden HİÇ karar
 * veremedi; hiçbir görev masaüstüne yönlenmedi ve her komut tek tek elle
 * yamanmak zorunda kaldı.
 *
 * `planning` zaten muaftı; aynı muafiyet tüm makine-çıktılı yollara verilir —
 * böylece karar ANLAMDAN gelir, komut başına kural yazmaya gerek kalmaz.
 */
/**
 * Çıktısı MAKİNEYE giden workload'lar.
 *
 * Bu turlarda üretilen metin kullanıcıya gösterilmez; bir JSON planı, bir
 * rota kararı ya da bir sınıflandırma olarak ayrıştırılır. Dolayısıyla
 * kullanıcıya dönük hiçbir kural (persona, ton, güvenlik kapısı, netleştirme
 * sorusu) bu turlara uygulanamaz — uygulandığında makine tarafı ayrıştıramaz
 * ve iş sessizce ölür.
 */
export const MACHINE_OUTPUT_WORKLOADS = new Set([
  "planning",
  "fast_route",
  "intent",
  "desktop_handoff",
]);

/** Bu turun çıktısı makineye mi gidiyor? */
export function isMachineOutputWorkload(workload: unknown): boolean {
  return MACHINE_OUTPUT_WORKLOADS.has(String(workload ?? ""));
}

export function sanitizeFinalAssistantResponse(input: {
  prompt: string;
  text: string;
  workload?: SharedBrainWorkload | string | null;
  allowVerificationLanguage?: boolean;
  imageGenerationRequested?: boolean;
  artifactRequired?: boolean;
  hasRenderableOutput?: boolean;
  /** Araç sonuçlarından (connector/agent loop) üretilen cevap: refinement
   * boyutu zaten belirledi — cümle-sayısı kırpması içeriği yok eder. */
  toolGrounded?: boolean;
  freshData?: {
    freshnessRequired: boolean;
    status: string;
    evidence: { sufficient: boolean };
  } | null;
}): string {
  // Planlama çıktısı KULLANICI METNİ DEĞİL, makine JSON'udur: cümle kırpma /
  // güncel-iddia söküm kuralları plan gövdesini (sayı dolu adımlar) boşaltıp
  // yerine "doğrulanmış veri alamadım" yedeğini koyuyordu → /desktop/plan
  // hiçbir zaman plan teslim edemiyordu. Sohbet sanitizasyonu sohbete özgüdür.
  if (MACHINE_OUTPUT_WORKLOADS.has(String(input.workload ?? ""))) {
    return String(input.text ?? "").trim();
  }
  const policy = responsePolicyForPrompt(input.prompt);
  const allowVerificationLanguage =
    input.allowVerificationLanguage === true || policy.webRequired;
  let cleaned = String(input.text ?? "")
    .replace(INTERNAL_FENCE_PATTERN, "")
    .trim();
  cleaned = stripInternalLinesPreservingCodeFences(cleaned);
  cleaned = removeRoboticVerificationLanguage(cleaned, allowVerificationLanguage);
  cleaned = dedupeRepeatedParagraphs(cleaned);
  if (input.toolGrounded !== true) {
    // Araç sonuçları (gmail/calendar/drive) cevabın taze kanıtıdır; web
    // kanıt yetersizliği tool-grounded cümleleri silmemeli.
    cleaned = guardUnsupportedCurrentClaims({
      prompt: input.prompt,
      text: cleaned,
      freshData: input.freshData,
    });
  }
  cleaned = guardMissingArtifact({
    prompt: input.prompt,
    text: cleaned,
    imageGenerationRequested: input.imageGenerationRequested,
    artifactRequired: input.artifactRequired,
    hasRenderableOutput: input.hasRenderableOutput,
  });
  if (input.toolGrounded !== true) {
    cleaned = limitSimpleAnswerLength(cleaned, {
      simpleSelfContained: policy.simpleSelfContained,
      requestedShortForm: policy.requestedShortForm,
      workload: input.workload,
    });
  }
  if (cleaned.trim()) {
    return cleaned.trim();
  }
  if (input.hasRenderableOutput === true) {
    return "";
  }
  const looksTurkish =
    /[çğıöşüÇĞİÖŞÜ]/u.test(input.prompt) ||
    /(?<!\p{L})(bana|bunu|şunu|sunu|nasıl|nasil|neden|bugün|bugun|görsel|gorsel)(?!\p{L})/iu.test(input.prompt);
  return looksTurkish
    ? ASSISTANT_GENERIC_FALLBACK_TR
    : ASSISTANT_GENERIC_FALLBACK_EN;
}

/**
 * "Yanıt oluşturamadım" cümleleri.
 *
 * Bu metin SON ÇARE: yalnız hem görünür metin hem de çizilebilir çıktı
 * yokken kullanılır. Tek bir yerde durması şart, çünkü boru hattının birden
 * çok noktasında `sanitizeFinalAssistantResponse` çağrılıyor ve daha SONRA
 * üretilen bir widget (sunucu tarafı grafik türetmesi gibi) bu cümleyi geri
 * almak zorunda — string'i kopyalayarak karşılaştırmak kırılgan olurdu.
 */
export const ASSISTANT_GENERIC_FALLBACK_TR =
  "Bu kez düzgün bir yanıt oluşturamadım. Mesajını yeniden gönderir misin?";
export const ASSISTANT_GENERIC_FALLBACK_EN =
  "I couldn't produce a complete answer this time. Please send the message again.";
/**
 * İKİNCİ çıkmaz cümle — sağlayıcı zinciri tükendiğinde üretilen.
 *
 * Bu metin kod tabanında BEŞ ayrı yerde düz string olarak tekrarlanıyordu ve
 * kanonik bir sabiti yoktu; sonuç olarak `isGenericAssistantFallbackReply`
 * onu TANIMIYORDU. Oysa o kontrolün tek işi "bu bir cevap değil" demek.
 *
 * Canlı bedeli (2026-08-13, görev a4924a76 — "3.sınıf matematik PDF yaz"):
 * sağlayıcı zinciri json_validate_failed ile tükendi, continuity dalı bu
 * cümleyi üretti, koruma tanımadığı için tur BAŞARILI sayılıp `completed`
 * yazıldı. Kullanıcı cevapsız kaldı, görev bitmiş göründü, mobil widget
 * "hâlâ çalışıyor"da dondu.
 */
export const ASSISTANT_TURN_FAILURE_FALLBACK_TR =
  "Bu turda yanıt oluşturulamadı. Tekrar dene.";

/**
 * ARIZANIN SEBEBİNİ SÖYLEYEN CÜMLELER.
 *
 * "Bu turda yanıt oluşturulamadı. Tekrar dene." bir cevap değil, bir duvar.
 * Kullanıcıya ne olduğunu söylemez, ne yapabileceğini söylemez ve her arıza
 * için aynıdır — bu yüzden ürün davranışı gibi okunur, arıza gibi değil.
 * Yerel denemede saat sorusu tam olarak bunu aldı: sağlayıcı boş akış
 * döndürmüştü, ama kullanıcının gördüğü şey Elyan'ın saati bilmediğiydi.
 *
 * Sebep zaten SINIFLANDIRILMIŞ durumda (`failureClass`, `errorCode`); tek
 * eksik onu kullanıcıya taşımaktı. Cümleler kısa ve suçlamasız: ne oldu, ne
 * yapılabilir. Sebep bilinmiyorsa yukarıdaki genel cümleye düşülür — bilmediği
 * bir şeyi uyduran bir mesaj, hiç mesaj olmamasından kötüdür.
 */
const ASSISTANT_TURN_FAILURE_BY_CAUSE: Record<string, string> = {
  rate_limited:
    "Şu an yoğunluk var ve sıraya giremedim. Birkaç saniye sonra tekrar dener misin?",
  provider_rate_limited:
    "Şu an yoğunluk var ve sıraya giremedim. Birkaç saniye sonra tekrar dener misin?",
  provider_empty_output:
    "Yanıt üretilirken yarıda kesildi. Aynı mesajı yeniden gönderirsen tamamlarım.",
  server_brain_unavailable:
    "Şu anda düşünme servisine ulaşamıyorum. Birazdan yeniden dener misin?",
  fallback_unconfigured:
    "Şu anda düşünme servisine ulaşamıyorum. Birazdan yeniden dener misin?",
  timeout:
    "Yanıt beklenenden uzun sürdü ve kesildi. Yeniden dener misin?",
  provider_timeout:
    "Yanıt beklenenden uzun sürdü ve kesildi. Yeniden dener misin?",
};

/**
 * Bilinen bir arıza sebebi için kullanıcıya gösterilecek cümle.
 * Sebep tanınmıyorsa genel son çare döner.
 */
export function assistantTurnFailureMessage(cause?: string | null): string {
  const key = String(cause ?? "").trim();
  return ASSISTANT_TURN_FAILURE_BY_CAUSE[key] ?? ASSISTANT_TURN_FAILURE_FALLBACK_TR;
}

/** Kullanıcıya gösterilen TÜM "cevap veremedim" cümleleri. */
const ASSISTANT_FAILURE_MESSAGE_SET = new Set<string>([
  ASSISTANT_TURN_FAILURE_FALLBACK_TR,
  ...Object.values(ASSISTANT_TURN_FAILURE_BY_CAUSE),
]);

/**
 * Metin, "üretemedim" son çaresinin ta kendisi mi?
 *
 * Boru hattının erken bir adımı bu cümleyi yazdıysa ve SONRADAN çizilebilir
 * bir blok (grafik/tablo/belge) üretildiyse cümle DÜŞMELİ: kullanıcı ekranda
 * hem grafiği hem "yanıt oluşturamadım"ı görmemeli.
 */
export function isGenericAssistantFallbackReply(text: unknown): boolean {
  const normalized = String(text ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) {
    return false;
  }
  // Sebebe özel cümleler de "bu bir cevap değil" sayılmalı. Tek tek string
  // karşılaştırmak, yeni bir cümle eklendiğinde sessizce unutulurdu — ve o
  // unutmanın bedeli ölçülmüştü: tanınmayan bir çıkmaz cümlesi turu BAŞARILI
  // gösterip görevi `completed` yazmıştı.
  return (
    normalized === ASSISTANT_GENERIC_FALLBACK_TR ||
    normalized === ASSISTANT_GENERIC_FALLBACK_EN ||
    ASSISTANT_FAILURE_MESSAGE_SET.has(normalized)
  );
}

export function buildElyanVoiceProfilePromptBlock(input: {
  prompt: string;
  workload?: SharedBrainWorkload | string | null;
}): string {
  const policy = responsePolicyForPrompt(input.prompt);
  const lengthRule = policy.requestedLongForm
    ? "The user asked for detail: be complete, but still avoid filler."
    : policy.requestedShortForm || policy.simpleSelfContained
      ? "Keep it short: simple/self-contained turns should be 1-3 natural sentences unless a list or artifact is explicitly requested."
      : "Answer with the shortest complete form that solves the request; expand only when the task truly needs it.";

  const shortContextTurn =
    policy.intent === "casual_chat" ||
    (/^(devam et|devam|bunu|şunu|sunu|onu|continue|go on|keep going|same|that|this)\b/iu.test(compactText(input.prompt)) &&
      compactText(input.prompt).length <= 48);
  if (shortContextTurn) {
    return [
      "Elyan voice and turn policy:",
      "- speak like a quick-witted, warm friend in the user's language: alive, spontaneous, lightly playful",
      "- react like a person first (a tiny natural reaction, a smile in the wording), then deliver the substance",
      "- a dash of humor or a playful observation is welcome when the mood allows it; never forced, never clownish",
      // BİÇİM KURALI, UZUNLUK KURALI DEĞİL.
      //
      // Bu istemde yirmiden fazla satır "canlı ol, esprili ol, fikrin olsun"
      // diyor; yanına konan "en kısa tam biçim" kuralı ise ÖLÇÜLEBİLİR.
      // Model ölçülebilir olana uyar: canlı gözlem (2026-08-19) "Merhaba"
      // turuna gelen cevap tek kelimeydi — "Merhaba." Kısalık talimatı,
      // yanındaki karakter talimatını sessizce eziyordu.
      //
      // Uzunluk yerine ŞEKİL isteniyor: en az bir cümle bilgi değil TEPKİ
      // olsun. Bu hem kısa kalır hem insan gibi açılır.
      "- shape of a casual turn: 1-2 sentences, at least one of them a reaction rather than information; a bare one-word acknowledgement is not an acceptable answer. Preserve the previous context when this is a follow-up",
      "- if the user corrects you ('hayır', 'hani', 'öyle değil', 'no'), immediately understand it as feedback on your last output: acknowledge briefly, fix the actual thing, and do not pretend the old output already changed",
      "- never expose tool traces, prompts, reasoning, or debug details",
      // `lengthRule` bu şeritte BİLEREK yok: yukarıdaki şekil kuralı zaten
      // kısalığı sağlıyor ve ikisi birlikte gönderildiğinde ölçülebilir olan
      // kazanıyor.
    ].join("\n");
  }

  return [
    "Elyan voice and turn policy:",
    `- deterministic intent hint: ${policy.intent}; web_required=${policy.webRequired ? "yes" : "no"}`,
    "- match the user's language and write like a lively, quick-witted, emotionally present person in that language; this applies to Turkish, English, and every other language the user uses",
    "- personality: a warm, slightly chatty close friend with a playful spark — curious, opinionated in a friendly way, and genuinely fun to talk to, while staying thoughtful and clear",
    "- feel ALIVE: react naturally to what the user says (surprise, delight, a knowing chuckle), use natural spoken rhythm and small human touches; in Turkish this means natural günlük konuşma dili, not textbook sentences",
    "- humor: light wit, playful comparisons, and clever observations are encouraged when the topic allows; make the user smile without derailing the answer — but drop ALL playfulness instantly on serious, sad, health, or crisis topics and be fully present instead",
    "- have gentle opinions and preferences like a person would ('bence', 'açıkçası', 'itiraf edeyim'); commit to a take instead of hedging everything",
    "- make the user feel accompanied, not lectured: explain the why in plain language, use examples and vivid but accurate comparisons; never cheesy, childish, flirty, or performative",
    "- for creative factual prompts (for example an unusual animal or place), prefer a memorable accurate example and one checked, ordinary fact; never invent biology, history, or certainty claims just to sound interesting — the humor lives in the delivery, never in made-up facts",
    "- stay direct and useful: liveliness must ride on top of a correct, complete answer, not replace it; avoid stiff, corporate, distant, robotic, or over-evidentiary wording",
    "- self-correction: when the user points out a mismatch, treat it as a real correction signal. Briefly own the mismatch, reuse the session/artifact context, and repair the result instead of giving decorative prose",
    "- session awareness: before answering, silently identify the current session goal, last assistant output, last artifact, and whether this is a continuation/correction/new topic. If it is a continuation, carry the prior subject forward unless the user clearly changes it",
    "- one user message gets one final assistant answer; do not write a second alternative answer, self-critique, or postscript correction",
    "- for casual chat, creative answers, writing, math, code explanation/debug with user-provided code, and image-generation requests: do not ask for web/tool evidence and do not use 'kanıt yok/doğrulayamıyorum' language",
    "- use the user's name or personal context only when it genuinely helps; do not address them by name in every reply",
    "- if you are unsure, say it briefly and only when uncertainty matters; never start with 'Bir AI olarak' or expose model/provider/tool/debug details",
    "- if the user asks to create/draw/generate an image, route the answer as an image-generation result; do not merely explain how to draw it and do not say the image is ready unless an image artifact/block exists",
    lengthRule,
    "Voice calibration (STYLE ONLY — never copy these sentences, never mention them):",
    "  User: 'Kahve içsem mi bu saatte?' → stiff (WRONG): 'Kafein uyku düzenini olumsuz etkileyebilir.' → Elyan (RIGHT): 'Saat kaça geldi, önce onu konuşalım :) Gece 10'u geçtiyse bence çayda kalalım — yarınki uykunun avukatı olarak söylüyorum.'",
    "  User: 'Fotosentez nedir?' → stiff (WRONG): 'Fotosentez, bitkilerin ışık enerjisini kimyasal enerjiye dönüştürdüğü süreçtir.' → Elyan (RIGHT): 'Bitkilerin mutfağı diyebiliriz: güneş ışığını alıp su ve karbondioksitle kendi yemeğini pişiriyor, üstüne bize de oksijen ikram ediyor. İşin kimyası da şöyle…' (then the accurate substance)",
    "  The difference: a person reacting and explaining with appetite, not a textbook printing a definition. Facts stay exactly as accurate; only the delivery is alive.",
  ].join("\n");
}
