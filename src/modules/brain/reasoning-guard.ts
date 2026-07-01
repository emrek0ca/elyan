/**
 * reasoning-guard.ts — Reasoning sızıntısına karşı TEK toplama noktası.
 *
 * Sorun: gpt-oss tarzı modeller reasoning_format=hidden'a rağmen bazen iç
 * düşünme sürecini CONTENT kanalına yazar ("The user's preferred language is
 * Turkish. I should provide... Let's say Kurt. Wait, ... Response: \"Kurt.\"").
 * Bu üç ayrı hataya dönüşüyordu:
 *   1. Dump streaming sırasında delta olarak CANLI kullanıcıya akıyordu
 *      (tespit ancak stream bitince çalışıyordu),
 *   2. Delta yayınlandığı için retry engelleniyor, dump final cevap kalıyordu,
 *   3. Sanitizer dump'ı kısmen/komple silince kullanıcı "Yanıtı temiz biçimde
 *      oluşturamadım" stub'ını görüyordu.
 *
 * Bu modül üç savunma sağlar:
 *   • looksLikeReasoningDumpOpening — streaming'de ilk pencerede (≥24 karakter)
 *     dump açılışını yakalar; delta yayını daha ilk chunk'ta bastırılır.
 *   • classifyReasoningDump — tamamlanan metin üzerinde satır-bazlı meta-oran
 *     skorlaması; sanitizer'ın satır satır kaçırdığı dump'ları bütüncül yakalar.
 *   • extractFinalAnswerFromReasoningDump — dump'ın içindeki gerçek cevabı
 *     (Response:/I'll reply:/son aday alıntı) çıkarır; retry israfı ve stub
 *     yerine kullanıcıya temiz cevap gider.
 */

export type ReasoningDumpClassification = {
  isDump: boolean;
  /** meta satır oranı 0..1 */
  score: number;
  metaLineCount: number;
  totalLineCount: number;
};

/* Dump AÇILIŞLARI — bir asistan cevabının kullanıcıya hitaben başlamayacağı,
 * kendi kendine konuşma kalıpları. Streaming gate'te ilk ~24-64 karakterde
 * test edilir; muhafazakâr tutulmalı (yanlış pozitif = o cevapta canlı akış
 * yerine tek seferde teslim — zararsız ama animasyonsuz). */
const REASONING_DUMP_OPENING_PATTERN =
  /^\s*(?:the user(?:'s)?\b|the request\b|user request\b|i (?:should|will|'ll|need to|am going to|want to|can (?:just|simply))\b|we (?:need|should|will|must)\b|let'?s (?:go with|say|think|see|stick|provide|start by)\b|okay,? (?:the user|so)\b|ok,? (?:the user|so)\b|hmm+[,.]|wait[,.]|alright[,.]|first,? i (?:should|will|need)\b|my (?:goal|task|job) (?:is|here)\b|analysis\s*:|reasoning\s*:|thinking process\b|thought process\b|kullanıcı(?:nın|nin)? (?:istediği|amacı|hedefi|dili|mesajı|isteği)\b|önce kullanıcı\b)/iu;

/* Satır-bazlı meta işaretleri: dump'ların gövdesindeki kendi kendine konuşma
 * kalıpları. Tek tek zararsız görünen satırlar toplamda dump'ı ele verir. */
const META_LINE_PATTERNS: RegExp[] = [
  /^(?:the user(?:'s)?|user request|the request)\b/i,
  /^i\s*(?:'ll|will|should|can|need to|am going to|want to|think)\b/i,
  /^we\s+(?:need|should|will|can|must)\b/i,
  /^(?:let'?s|let us)\b/i,
  /^(?:wait|actually|hmm+|okay|ok so|alright|anyway|so,)\b[,.]?\s/i,
  /^(?:wait|actually|hmm+|done|good|perfect|fine)[,.]?$/i,
  /^(?:response|reply|final answer|answer|draft|output)\s*:/i,
  /^(?:cevap|yanıt|son cevap|taslak)\s*:/i,
  /^check(?:ing)?\b.{0,40}\b(?:constraints|policies|persona|rules)/i,
  /^(?:keep it|make it)\s+(?:concise|short|simple|brief|warm)/i,
  /^or\s+(?:simply|just)?\s*["“']/i,
  /"[^"]*"\s+(?:is|seems|sounds)\s+(?:enough|good|fine|best|simple|friendly|better)/i,
  /\b(?:per the persona|the persona|the prompt says|the system prompt|as per the persona)\b/i,
  /\bmight be testing\b/i,
  /^kullanıcı(?:nın|nin)?\b/i,
  /(?:yapmalıyım|etmeliyim|söylemeliyim|listelemeliyim|vermeliyim|seçmeliyim|secmeliyim)[.\s]*$/iu,
];

function splitNonEmptyLines(text: string): string[] {
  return text
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function isMetaLine(line: string): boolean {
  return META_LINE_PATTERNS.some((pattern) => pattern.test(line));
}

/**
 * Streaming ilk-pencere kontrolü: görünür metnin AÇILIŞI dump kalıbına
 * benziyor mu? Publisher bunu ilk ~24-64 karakterde çağırır; true dönerse o
 * attempt'in delta yayını tamamen bastırılır (kullanıcı dump'ı asla görmez),
 * stream sonu kontrolü retry/kurtarma kararını verir.
 */
export function looksLikeReasoningDumpOpening(text: string): boolean {
  const compact = String(text ?? "").trimStart();
  if (!compact) {
    return false;
  }
  return REASONING_DUMP_OPENING_PATTERN.test(compact.slice(0, 200));
}

/**
 * Tamamlanmış (görünür) metin üzerinde bütüncül dump sınıflandırması.
 * isReasoningOnlyReply'dan farkı: sanitizer'ın SATIR SATIR silemediği
 * dump'ları da yakalar — tek tek zararsız görünen ama toplamda kendi kendine
 * konuşma olan metinler (prod ekran görüntüsündeki vaka).
 */
export function classifyReasoningDump(text: string): ReasoningDumpClassification {
  const lines = splitNonEmptyLines(String(text ?? ""));
  if (lines.length === 0) {
    return { isDump: false, score: 0, metaLineCount: 0, totalLineCount: 0 };
  }

  let metaLineCount = 0;
  for (const line of lines) {
    if (isMetaLine(line)) {
      metaLineCount += 1;
    }
  }
  const score = metaLineCount / lines.length;
  const opensAsDump = looksLikeReasoningDumpOpening(lines[0]);

  const isDump =
    // Çok satırlı ve satırların yarısı meta → kesin dump.
    (lines.length >= 3 && score >= 0.5) ||
    // Dump açılışı + kayda değer meta oranı.
    (opensAsDump && lines.length >= 2 && score >= 0.34) ||
    // Tek "satır"a sıkışmış uzun dump (newline'lar kaybolmuş olabilir).
    (opensAsDump && lines.length === 1 && lines[0].length > 160);

  return { isDump, score: Number(score.toFixed(3)), metaLineCount, totalLineCount: lines.length };
}

const LABELLED_ANSWER_PATTERN =
  /(?:^|\n)\s*(?:final answer|response|reply|answer|cevap|yanıt|son cevap)\s*:\s*["“']?([^\n"”']{2,300})/gi;
const SPEECH_ANSWER_PATTERN =
  /i'?ll\s+(?:reply|say|answer|respond with|go with)\s*:?\s*["“']([^"”'\n]{2,300})["”']/gi;
const QUOTED_CANDIDATE_PATTERN = /["“]([^"”\n]{2,300})["”]/g;

function lastMatch(text: string, pattern: RegExp): string | null {
  let result: string | null = null;
  for (const match of text.matchAll(pattern)) {
    const candidate = (match[1] ?? "").trim();
    if (candidate) {
      result = candidate;
    }
  }
  return result;
}

function cleanExtractedAnswer(candidate: string | null): string | null {
  if (!candidate) {
    return null;
  }
  const cleaned = candidate
    .replace(/^["“'\s]+|["”'\s]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (cleaned.length < 2 || !/\p{L}/u.test(cleaned)) {
    return null;
  }
  // Çıkarılan aday hâlâ meta konuşmaysa cevap değildir.
  if (isMetaLine(cleaned) || looksLikeReasoningDumpOpening(cleaned)) {
    return null;
  }
  return cleaned;
}

/**
 * Dump'ın içinden modelin ASLINDA vermek istediği cevabı çıkarır. Dump'lar
 * neredeyse her zaman nihai cevabı içerir; öncelik sırası:
 *   1. Etiketli cevap: `Response: "..."`, `Final answer: ...`, `Cevap: ...`
 *      (SON geçen kazanır — model karar değiştirdikçe sonuncusu nihaidir),
 *   2. Konuşma kalıbı: `I'll reply: "..."`, `I'll go with "..."`,
 *   3. Metnin son yarısındaki son tırnaklı aday.
 * Bulunamazsa null — çağıran retry/stub kararını verir.
 */
export function extractFinalAnswerFromReasoningDump(text: string): string | null {
  const source = String(text ?? "");
  if (!source.trim()) {
    return null;
  }

  const labelled = cleanExtractedAnswer(lastMatch(source, LABELLED_ANSWER_PATTERN));
  if (labelled) {
    return labelled;
  }

  const speech = cleanExtractedAnswer(lastMatch(source, SPEECH_ANSWER_PATTERN));
  if (speech) {
    return speech;
  }

  const tail = source.slice(Math.floor(source.length / 2));
  const quoted = cleanExtractedAnswer(lastMatch(tail, QUOTED_CANDIDATE_PATTERN));
  if (quoted) {
    return quoted;
  }

  return null;
}
