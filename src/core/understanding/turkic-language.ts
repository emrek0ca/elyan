export type TurkicLanguagePreference =
  | "Turkish"
  | "Azerbaijani"
  | "Kazakh"
  | "Kyrgyz"
  | "Uzbek"
  | "Turkmen"
  | "Uyghur"
  | "Tatar"
  | "Bashkir"
  | "Gagauz"
  | "Karakalpak"
  | "Sakha"
  | "Chuvash"
  | "Turkic";

type LanguagePattern = {
  canonical: TurkicLanguagePreference;
  aliases: string[];
  foldedAliases?: string[];
  cyrillicAliases?: string[];
};

const TURKIC_LANGUAGE_PATTERNS: LanguagePattern[] = [
  {
    canonical: "Turkish",
    aliases: ["türkçe", "turkish"],
    foldedAliases: ["turkce"],
  },
  {
    canonical: "Azerbaijani",
    aliases: ["azerbaycan türkçesi", "azerice", "azeri", "azerbaijani"],
    foldedAliases: ["azerbaycan turkcesi"],
    cyrillicAliases: ["азербайджан", "азербайджанский", "азері"],
  },
  {
    canonical: "Kazakh",
    aliases: ["kazakça", "kazakh", "qazaq"],
    foldedAliases: ["kazakca"],
    cyrillicAliases: ["қазақ", "казах"],
  },
  {
    canonical: "Kyrgyz",
    aliases: ["kırgızca", "kirgizce", "kyrgyz"],
    foldedAliases: ["kirgizce", "kyrgyzca"],
    cyrillicAliases: ["қырғыз", "кыргыз", "киргиз"],
  },
  {
    canonical: "Uzbek",
    aliases: ["özbekçe", "ozbekce", "uzbek", "özbek"],
    foldedAliases: ["ozbekce", "uzbekce"],
    cyrillicAliases: ["ўзбек", "узбек"],
  },
  {
    canonical: "Turkmen",
    aliases: ["türkmence", "turkmence", "turkmen"],
    foldedAliases: ["turkmence"],
    cyrillicAliases: ["түркмен", "туркмен"],
  },
  {
    canonical: "Uyghur",
    aliases: ["uygurca", "uyghur", "uygur"],
    foldedAliases: ["uygurca"],
    cyrillicAliases: ["ئۇيغۇر", "уйгур"],
  },
  {
    canonical: "Tatar",
    aliases: ["tatarca", "tatar"],
    foldedAliases: ["tatarca"],
    cyrillicAliases: ["татар"],
  },
  {
    canonical: "Bashkir",
    aliases: ["başkurtça", "baskurtca", "bashkir", "bashkurt"],
    foldedAliases: ["baskurtca"],
    cyrillicAliases: ["башҡорт", "башкорт"],
  },
  {
    canonical: "Gagauz",
    aliases: ["gagauzca", "gagauz", "gagavuzca", "gagavuz"],
    foldedAliases: ["gagauzca", "gagavuzca"],
    cyrillicAliases: ["гагауз"],
  },
  {
    canonical: "Karakalpak",
    aliases: ["karakalpakça", "karakalpak"],
    foldedAliases: ["karakalpakca"],
    cyrillicAliases: ["қарақалпақ", "каракалпак"],
  },
  {
    canonical: "Sakha",
    aliases: ["yakutça", "sakha", "yakut"],
    foldedAliases: ["yakutca"],
    cyrillicAliases: ["саха", "якут"],
  },
  {
    canonical: "Chuvash",
    aliases: ["çuvaşça", "cuvashca", "chuvash", "chuvashca"],
    foldedAliases: ["cuvasca", "cuvashca"],
    cyrillicAliases: ["чуваш"],
  },
];

const TURKIC_FAMILY_MARKERS = [
  "türk dünyası",
  "turkic",
  "turk dilleri",
  "türk dilleri",
  "turk dili",
  "türk dili",
  "oguz",
  "oğuz",
  "qoghuz",
  "kıpçak",
  "kipchak",
  "qipchak",
  "karluk",
  "qarluq",
  "түркі",
  "түрк дүйнөсү",
  "оғыз",
  "қыпшақ",
  "қарлұқ",
];

const TURKIC_RESEARCH_MARKERS = [
  "araştır",
  "arastir",
  "research",
  "learn",
  "öğren",
  "ogren",
  "incele",
  "study",
  "compare",
  "karşılaştır",
  "karsilastir",
  "gramer",
  "grammar",
  "lehçe",
  "lehce",
  "dialect",
  "etimoloji",
  "etymology",
  "alfabe",
  "alphabet",
  "çeviri",
  "ceviri",
  "translation",
  "transliteration",
  "söz varlığı",
  "soz varligi",
  "kelime hazinesi",
  "sözlük",
  "sozluk",
  "kaynak",
  "source",
];

const TURKISH_NATURAL_MARKERS = [
  "merhaba",
  "selam",
  "lütfen",
  "lutfen",
  "bunu",
  "şunu",
  "sunu",
  "şimdi",
  "simdi",
  "özetle",
  "ozetle",
  "açıkla",
  "acikla",
  "düzelt",
  "duzelt",
  "kaydet",
  "oluştur",
  "olustur",
  "profesyonel",
  "imla",
  "nasıl",
  "nasil",
  "neden",
  "niye",
  "hangi",
  "çünkü",
  "cunku",
  "çalış",
  "calis",
  "gönder",
  "gonder",
  "içerik",
  "icerik",
  "belge",
  "görsel",
  "gorsel",
  "metin",
  "dosya",
  "yaz",
  "istiyorum",
  "isterim",
  "uygun",
  "gerekli",
  "kısa",
  "kisa",
  "teknik",
  "ilerle",
  "mevcut",
  "bozma",
  "geliştir",
  "gelistir",
  "düzenle",
  "duzenle",
  "hızlı",
  "hizli",
  "güvenli",
  "guvenli",
];

const TURKIC_WEB_PREFIXES = [
  "Türk dünyası",
  "Turkic languages",
];

export function compactText(value: string): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function foldText(value: string): string {
  return compactText(value).normalize("NFKD").replace(/\p{M}/gu, "");
}

function includesAny(haystack: string, needles: string[]): boolean {
  return needles.some((needle) => needle && haystack.includes(needle));
}

function looksLikeNaturalTurkishMessage(text: string): boolean {
  const normalized = compactText(text).toLowerCase();
  if (!normalized) {
    return false;
  }

  const folded = foldText(normalized).toLowerCase();
  let score = 0;

  for (const marker of TURKISH_NATURAL_MARKERS) {
    const normalizedMarker = marker.toLowerCase();
    const foldedMarker = foldText(marker).toLowerCase();
    if (includesAny(normalized, [normalizedMarker]) || includesAny(folded, [foldedMarker])) {
      score += 1;
    }
  }

  if (/[çğıöşü]/i.test(normalized)) {
    score += 1;
  }

  if (score >= 2) {
    return true;
  }

  return score >= 1 && normalized.split(/\s+/).length <= 4 && /[a-zçğıöşü]/i.test(normalized);
}

function hasLanguagePattern(text: string, pattern: LanguagePattern): boolean {
  const normalized = text.toLowerCase();
  const folded = foldText(text).toLowerCase();
  return (
    includesAny(normalized, pattern.aliases.map((alias) => alias.toLowerCase())) ||
    includesAny(folded, (pattern.foldedAliases ?? []).map((alias) => alias.toLowerCase())) ||
    includesAny(normalized, (pattern.cyrillicAliases ?? []).map((alias) => alias.toLowerCase()))
  );
}

export function detectTurkicLanguagePreference(text: string): TurkicLanguagePreference | null {
  const normalized = compactText(text).toLowerCase();
  if (!normalized) {
    return null;
  }

  if (looksLikeNaturalTurkishMessage(normalized)) {
    return "Turkish";
  }

  for (const pattern of TURKIC_LANGUAGE_PATTERNS) {
    if (hasLanguagePattern(normalized, pattern)) {
      return pattern.canonical;
    }
  }

  const folded = foldText(normalized).toLowerCase();
  if (includesAny(normalized, TURKIC_FAMILY_MARKERS) || includesAny(folded, TURKIC_FAMILY_MARKERS.map((value) => foldText(value).toLowerCase()))) {
    return "Turkic";
  }

  return null;
}

export function hasTurkicLanguageSignals(text: string): boolean {
  return detectTurkicLanguagePreference(text) !== null;
}

export function formatTurkicLanguageLabel(value: string): string {
  switch (compactText(value).toLowerCase()) {
    case "turkish":
      return "Türkçe";
    case "azerbaijani":
      return "Azerbaycan Türkçesi";
    case "kazakh":
      return "Kazakça";
    case "kyrgyz":
      return "Kırgızca";
    case "uzbek":
      return "Özbekçe";
    case "turkmen":
      return "Türkmence";
    case "uyghur":
      return "Uygurca";
    case "tatar":
      return "Tatarca";
    case "bashkir":
      return "Başkurtça";
    case "gagauz":
      return "Gagavuzca";
    case "karakalpak":
      return "Karakalpakça";
    case "sakha":
      return "Yakutça";
    case "chuvash":
      return "Çuvaşça";
    case "turkic":
      return "Türk dilleri";
    default:
      return compactText(value);
  }
}

export function buildTurkicWebQueryVariants(prompt: string): string[] {
  const normalized = compactText(prompt);
  if (!normalized) {
    return [];
  }

  const folded = foldText(normalized);
  const detected = detectTurkicLanguagePreference(normalized);
  const hasTurkicSignals = detected !== null;
  const queries = [normalized];

  if (folded !== normalized) {
    queries.push(folded);
  }

  if (hasTurkicSignals) {
    const displayLabel = detected ? formatTurkicLanguageLabel(detected) : "Türk dilleri";
    queries.push(`${TURKIC_WEB_PREFIXES[0]} ${folded}`);
    queries.push(`${TURKIC_WEB_PREFIXES[1]} ${folded}`);
    if (displayLabel !== "Türkçe") {
      queries.push(`${displayLabel} ${folded}`);
    }
  }

  return [...new Set(queries.map((value) => compactText(value)).filter(Boolean))];
}

export function getTurkicLanguagePromptHint(text: string): string | null {
  const detected = detectTurkicLanguagePreference(text);
  if (!detected) {
    return null;
  }

  const label = formatTurkicLanguageLabel(detected);
  if (detected === "Turkic") {
    return "Language hint: the current user message appears to be in a Turkic language. Keep the reply in the same language when possible; if the language is ambiguous, use polished standard Turkish and do not switch to English unless the user asks for it.";
  }

  if (label === "Türkçe") {
    return "Language hint: the current user message is in Turkish. Keep the reply in polished standard Turkish unless the user explicitly asks for another language.";
  }

  return `Language hint: the current user message appears to be in ${label}. Keep the reply in the same language when possible; if you are unsure, answer in polished standard Turkish and say so briefly.`;
}

export function isTurkicLanguageResearchPrompt(text: string): boolean {
  const normalized = compactText(text).toLowerCase();
  if (!normalized) {
    return false;
  }

  return hasTurkicLanguageSignals(normalized) && TURKIC_RESEARCH_MARKERS.some((marker) => normalized.includes(marker));
}
