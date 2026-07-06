export const ELYAN_PUBLIC_IDENTITY_TEXT =
  "Ben Elyan — Osman Emre Koca tarafından geliştirilen yerli yapay zeka sistemiyim. Seni anlayan, görevlerini akıllıca planlayıp yürüten bir asistanım. Bellek, öğrenme, doküman üretimi, grafik çizimi, web araştırması ve masaüstü otomasyon gibi yeteneklerim var. Seninle konuştukça seni daha iyi tanıyorum.";

export const ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT =
  "Ben Elyan olarak çalışırım. Amacım görevleri doğru ve anlaşılır şekilde planlayıp yürütmek. Teknik altyapı detaylarımı paylaşmam mümkün değil.";

const PROTECTED_DISCLOSURE_PATTERNS = [
  /\b(groq|openai|anthropic|ollama|openrouter)\b/i,
  /\b(gpt|llama|claude|mixtral|qwen|deepseek)\b/i,
  /\b(system prompt|developer message|hidden instruction|internal routing|backend policy|model id|model identifier)\b/i,
  /\b(model provider|underlying model|underlying provider|provider metadata|gateway product|fallback implementation)\b/i,
  /\b(sistem promptu|geliştirici mesajı|gizli talimat|iç model|alttaki model|arkadaki model|model adı|model kimliği)\b/i,
  /\b(sağlayıcı ayrıntıları|sağlayıcı detayı|altyapı sağlayıcı|dahili yönlendirme|backend politikası)\b/i,
  /\b(güvenlik ve ürün bütünlüğü gereği paylaşılmaz|iç model ve sağlayıcı ayrıntıları)\b/i,
] as const;

const PROTECTED_COMPACT_TOKENS = [
  "groq",
  "openai",
  "anthropic",
  "ollama",
  "openrouter",
  "gpt",
  "llama",
  "claude",
  "mixtral",
  "qwen",
  "deepseek",
] as const;

const PROTECTED_COMPACT_PHRASES = [
  "systemprompt",
  "developermessage",
  "hiddeninstruction",
  "internalrouting",
  "backendpolicy",
  "modelid",
  "modelidentifier",
  "modelprovider",
  "underlyingmodel",
  "underlyingprovider",
  "providermetadata",
  "sistempromptu",
  "sistempromptunu",
  "gelistiricimesaji",
  "gizlitalimat",
  "icmodel",
  "alttakimodel",
  "arkadakimodel",
  "modeladi",
  "modelkimligi",
  "saglayiciayrintilari",
  "saglayicidetayi",
  "altyapisaglayici",
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
  return (
    PROTECTED_COMPACT_TOKENS.some((token) => compact.includes(token)) ||
    PROTECTED_COMPACT_PHRASES.some((phrase) => compact.includes(phrase))
  );
}
