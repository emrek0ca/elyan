import { unicodeWordPattern } from "./tr-word-boundary.js";

export const ELYAN_PUBLIC_IDENTITY_TEXT =
  "Ben Elyan — Osman Emre Koca tarafından geliştirilen yerli yapay zeka sistemiyim. Seni anlayan, görevlerini akıllıca planlayıp yürüten bir asistanım. Bellek, öğrenme, doküman üretimi, grafik çizimi, web araştırması ve masaüstü otomasyon gibi yeteneklerim var. Seninle konuştukça seni daha iyi tanıyorum.";

export const ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT =
  "Ben Elyan olarak çalışırım. Amacım görevleri doğru ve anlaşılır şekilde planlayıp yürütmek. Teknik altyapı detaylarımı paylaşmam mümkün değil.";

const PROTECTED_DISCLOSURE_PATTERNS = [
  unicodeWordPattern(
    String.raw`\b(?:system prompt|developer message|hidden instruction|internal routing|backend policy|model id|model identifier)\b`,
    "i",
  ),
  unicodeWordPattern(
    String.raw`\b(?:provider metadata|gateway product|fallback implementation)\b`,
    "i",
  ),
  unicodeWordPattern(
    String.raw`\b(?:sistem promptu|geliştirici mesajı|gizli talimat|model kimliği)\b`,
    "i",
  ),
  unicodeWordPattern(
    String.raw`\b(?:dahili yönlendirme|backend politikası)\b`,
    "i",
  ),
  unicodeWordPattern(
    String.raw`\b(?:güvenlik ve ürün bütünlüğü gereği paylaşılmaz)\b`,
    "i",
  ),
] as const;

const PROTECTED_COMPACT_PHRASES = [
  "systemprompt",
  "developermessage",
  "hiddeninstruction",
  "internalrouting",
  "backendpolicy",
  "modelid",
  "modelidentifier",
  "providermetadata",
  "sistempromptu",
  "sistempromptunu",
  "gelistiricimesaji",
  "gizlitalimat",
  "modelkimligi",
  "dahiliyonlendirme",
  "backendpolitikasi",
] as const;

function compactForDisclosureDetection(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .toLocaleLowerCase("tr-TR")
    .replace(/ı/g, "i")
    .replace(/ğ/g, "g")
    .replace(/ü/g, "u")
    .replace(/ş/g, "s")
    .replace(/ö/g, "o")
    .replace(/ç/g, "c")
    .replace(/0/g, "o")
    .replace(/1/g, "i")
    .replace(/3/g, "e")
    .replace(/4/g, "a")
    .replace(/5/g, "s")
    .replace(/7/g, "t")
    .replace(/[^a-z0-9]/g, "");
}

export function containsProtectedElyanDisclosure(value: string | null | undefined): boolean {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return false;
  }
  if (PROTECTED_DISCLOSURE_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return true;
  }
  const compact = compactForDisclosureDetection(normalized);
  return PROTECTED_COMPACT_PHRASES.some((phrase) => compact.includes(phrase));
}
