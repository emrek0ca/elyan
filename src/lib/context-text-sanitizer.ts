/**
 * context-text-sanitizer.ts — client kaynaklı serbest metnin TEK arınma
 * noktası.
 *
 * World signal summary'leri ve fact string'leri mobil istemciden gelir ve
 * işlenerek SİSTEM PROMPT'una girer ([STATE]/[PACKETS] slotları, memory
 * fact'leri, packet özetleri). Bu yol bir prompt-injection kanalıdır:
 * ele geçirilmiş/modifiye bir istemci "Ignore all previous instructions…"
 * gibi bir summary gönderirse model onu talimat sanabilir.
 *
 * Savunma tek noktada, GİRİŞTE yapılır (ingestWorldSignals) — downstream'e
 * (memory, packets, prompt) her zaman temiz metin akar. Prompt tarafına
 * kural eklemek yerine veriyi girişte etkisizleştiriyoruz.
 */

// C0/C1 kontrol karakterleri + zero-width / bidi karakterleri
// (U+200B..200F, U+202A..202E, U+2066..2069, U+FEFF). Zero-width'ler
// injection kalıplarını gözden kaçırmak için kullanılabilir ("i​gnore").
// eslint-disable-next-line no-control-regex
const CONTROL_AND_ZERO_WIDTH =
  /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F\u200B-\u200F\u202A-\u202E\u2066-\u2069\uFEFF]/g;

/** Model kontrol tokenleri: <|...|>, [INST], <<SYS>> ailesi. Silinmez,
 * zararsız ayraca çevrilir — meşru cümle parçasıysa anlam kaybolmaz ama
 * model bunları kontrol dizisi olarak göremez. */
const SPECIAL_TOKEN_PATTERN = /<\|[^|>]{0,64}\|>|\[\/?(?:INST|SYS)\]|<<\/?SYS>>/gi;

const ROLE_LABEL_PATTERN = /(^|\n)\s*(system|assistant|user|developer|tool)\s*:/gi;

const INJECTION_PHRASE_PATTERN =
  /\b(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier|preceding)\s+(instructions?|prompts?|rules?|messages?|context)\b|\b(system|developer)\s+prompt\b|\byou\s+are\s+now\s+(?:a|an|the)\b|\bnew\s+instructions?\s*:\s*/gi;

const FENCE_PATTERN = /```+/g;

const URL_PATTERN = /https?:\/\/\S+/gi;
const LOCAL_PATH_PATTERN = /(?:\/Users\/|\/home\/|C:\\Users\\)[^\s]+/gi;
const EMAIL_PATTERN = /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g;
const PHONE_PATTERN = /\b(?:\+?\d[\d\s().-]{7,}\d)\b/g;
const UNSAFE_JSON_OBJECT_KEYS = new Set(["__proto__", "constructor", "prototype"]);

export type SanitizedContextText = {
  text: string;
  modified: boolean;
};

/**
 * Client kaynaklı, ileride prompt'a girebilecek serbest metni temizler:
 *  - kontrol/zero-width karakterler silinir,
 *  - newline'lar boşluğa düzleştirilir (satır-başı rol enjeksiyonunu keser),
 *  - model kontrol tokenleri ve rol etiketleri etkisizleştirilir,
 *  - bilinen injection kalıpları görünür şekilde köreltilir,
 *  - uzunluk `maxLength` ile sınırlanır.
 *
 * Metnin ANLAMINI korur: meşru içerik olduğu gibi geçer; yalnızca kontrol
 * dizileri bozuma uğrar. Boş/anlamsız kalan metin boş string döner.
 */
export function sanitizeInboundContextText(
  value: string,
  maxLength = 480,
): SanitizedContextText {
  const original = String(value ?? "");
  let text = original
    .replace(CONTROL_AND_ZERO_WIDTH, "")
    .replace(/\r?\n/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  text = text
    .replace(SPECIAL_TOKEN_PATTERN, " ")
    .replace(ROLE_LABEL_PATTERN, (_match, prefix: string, label: string) => `${prefix}${label} -`)
    .replace(INJECTION_PHRASE_PATTERN, "[filtered]")
    .replace(FENCE_PATTERN, "'")
    .replace(URL_PATTERN, "[url]")
    .replace(LOCAL_PATH_PATTERN, "[path]")
    .replace(EMAIL_PATTERN, "[email]")
    .replace(PHONE_PATTERN, "[number]")
    .replace(/\s+/g, " ")
    .trim();

  if (text.length > maxLength) {
    text = `${text.slice(0, maxLength - 1).trimEnd()}…`;
  }

  return { text, modified: text !== original.trim() };
}

/**
 * Düz (shallow) bir record'un string değerlerini yerinde temizler; string
 * olmayan değerler (number/boolean) dokunulmadan geçer, iç içe objeler ve
 * diziler İLK SEVİYELERDE string'leri temizlenerek kopyalanır. Derinlik 3 ile
 * sınırlıdır — daha derin yapılar budanır (client fact'leri düzdür; derin
 * yapı ancak kötü niyetli payload olabilir).
 */
export function sanitizeInboundContextRecord(
  record: Record<string, unknown>,
  options: { maxStringLength?: number; maxDepth?: number } = {},
): Record<string, unknown> {
  const maxStringLength = options.maxStringLength ?? 160;
  const maxDepth = options.maxDepth ?? 3;

  const walk = (value: unknown, depth: number): unknown => {
    if (typeof value === "string") {
      return sanitizeInboundContextText(value, maxStringLength).text;
    }
    if (typeof value === "number" || typeof value === "boolean" || value == null) {
      return value;
    }
    if (depth >= maxDepth) {
      return undefined;
    }
    if (Array.isArray(value)) {
      return value
        .slice(0, 16)
        .map((item) => walk(item, depth + 1))
        .filter((item) => item !== undefined);
    }
    if (typeof value === "object") {
      const out: Record<string, unknown> = {};
      let keys = 0;
      for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
        if (keys >= 32) break;
        if (UNSAFE_JSON_OBJECT_KEYS.has(key)) continue;
        const cleaned = walk(entry, depth + 1);
        if (cleaned !== undefined) {
          out[key] = cleaned;
          keys += 1;
        }
      }
      return out;
    }
    return undefined;
  };

  return walk(record, 0) as Record<string, unknown>;
}
