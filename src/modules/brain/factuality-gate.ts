import type { UserUnderstandingContext } from "../../core/understanding/types.js";

export type FactualityClaimKind = "number" | "date" | "name";
export type FactualityClaimSalience = "medium" | "high";

export type FactualityClaim = {
  kind: FactualityClaimKind;
  text: string;
  normalized: string;
  salience: FactualityClaimSalience;
  supported: boolean;
  evidenceRefs: string[];
};

export type FactualityGateDecision = {
  claimCount: number;
  unsupportedClaims: FactualityClaim[];
  shouldCritique: boolean;
  evidenceSourceCount: number;
  evidenceCharCount: number;
  evidencePreview: string;
};

export type FactualityGateInput = {
  prompt: string;
  answer: string;
  understandingContext?: UserUnderstandingContext | null;
  inferenceMetadata?: Record<string, unknown> | null;
};

type EvidenceSource = {
  ref: string;
  text: string;
};

const MAX_EVIDENCE_SOURCES = 32;
const MAX_EVIDENCE_CHARS = 24_000;
const MAX_PROMPT_ANSWER_CHARS = 8_000;
const COMMON_TITLECASE_STARTS = new Set([
  "Ama",
  "Ancak",
  "Aslinda",
  "Ayrica",
  "Ben",
  "Bir",
  "Bu",
  "Bunu",
  "Eger",
  "Kisa",
  "Kisaca",
  "Ozetle",
  "Sen",
  "Su",
  "Yani",
  "Yes",
  "No",
  "The",
  "This",
  "That",
]);

const TURKISH_MONTHS =
  "ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik|jan|january|feb|february|mar|march|apr|april|jun|june|jul|july|aug|august|sep|september|oct|october|nov|november|dec|december";

export function evaluatePrePublishFactuality(input: FactualityGateInput): FactualityGateDecision {
  const evidenceSources = collectEvidenceSources(input);
  const evidenceText = evidenceSources
    .map((source) => source.text)
    .join("\n")
    .slice(0, MAX_EVIDENCE_CHARS);
  const claims = extractFactualClaims(input.answer);
  const supportedClaims = claims.map((claim) => {
    const refs = evidenceSources
      .filter((source) => evidenceSupportsClaim(source.text, claim))
      .map((source) => source.ref)
      .slice(0, 4);
    return {
      ...claim,
      supported: refs.length > 0,
      evidenceRefs: refs,
    };
  });
  const unsupportedClaims = supportedClaims.filter((claim) => !claim.supported);
  const shouldCritique = unsupportedClaims.some(
    (claim) => claim.kind !== "number" || claim.salience === "high",
  );
  return {
    claimCount: supportedClaims.length,
    unsupportedClaims,
    shouldCritique,
    evidenceSourceCount: evidenceSources.length,
    evidenceCharCount: evidenceText.length,
    evidencePreview: evidenceText.slice(0, MAX_EVIDENCE_CHARS),
  };
}

export function buildFactualityCritiquePrompt(input: {
  userPrompt: string;
  draftAnswer: string;
  decision: FactualityGateDecision;
}): string {
  const unsupported = input.decision.unsupportedClaims
    .slice(0, 16)
    .map((claim) => `- ${claim.kind}: ${claim.text}`)
    .join("\n");
  return [
    "Cevap yayinlanmadan once kanit kapisi calisiyor.",
    "Taslakta sayi, tarih veya isim iceren iddialar var; asagidaki kanitlarda birebir ya da acikca desteklenmeyenleri yayina alma.",
    "",
    "Kurallar:",
    "- Kanitta olan iddialari koru.",
    "- Kanitta olmayan sayi/tarih/isim iddialarini ya cikar ya da emin olmadigini soyleyip kontrol etmeyi teklif et.",
    "- Kanitta olmayan yeni sayi, tarih, kisi, kurum veya kaynak adi ekleme.",
    "- Sadece kullaniciya gidecek nihai yaniti yaz; aciklama, meta-not veya kontrol listesi yazma.",
    "",
    "Kullanici sorusu:",
    input.userPrompt.slice(0, MAX_PROMPT_ANSWER_CHARS),
    "",
    "Mevcut kanitlar:",
    input.decision.evidencePreview || "(kanit yok)",
    "",
    "Desteksiz gorunen iddia isaretleri:",
    unsupported || "- (yok)",
    "",
    "Taslak yanit:",
    input.draftAnswer.slice(0, MAX_PROMPT_ANSWER_CHARS),
  ].join("\n");
}

export function buildFactualityGateMetadata(input: {
  decision: FactualityGateDecision;
  triggered: boolean;
  applied: boolean;
  fallbackApplied: boolean;
  unsupportedAfter?: number;
}): Record<string, unknown> {
  return {
    factualityGateChecked: true,
    factualityGateTriggered: input.triggered,
    factualityGateApplied: input.applied,
    factualityGateFallbackApplied: input.fallbackApplied,
    factualityGateClaimCount: input.decision.claimCount,
    factualityGateUnsupportedCount: input.decision.unsupportedClaims.length,
    factualityGateUnsupportedAfter:
      typeof input.unsupportedAfter === "number" ? input.unsupportedAfter : undefined,
    factualityGateEvidenceSourceCount: input.decision.evidenceSourceCount,
    factualityGateEvidenceCharCount: input.decision.evidenceCharCount,
    factualityGateUnsupportedClaims: input.decision.unsupportedClaims
      .slice(0, 12)
      .map((claim) => ({
        kind: claim.kind,
        text: claim.text,
        salience: claim.salience,
      })),
  };
}

export function applyDeterministicFactualityFallback(input: {
  answer: string;
  decision: FactualityGateDecision;
  prompt?: string;
}): string {
  if (input.decision.unsupportedClaims.length === 0) {
    return input.answer;
  }
  const fallback = fallbackSentence(input.prompt ?? input.answer);
  const sentences = splitSentences(input.answer);
  const unsupported = input.decision.unsupportedClaims;
  const kept: string[] = [];
  let replaced = false;
  for (const sentence of sentences) {
    const sentenceNorm = normalizeForMatch(sentence);
    const hasUnsupported = unsupported.some((claim) => sentenceNorm.includes(claim.normalized));
    if (!hasUnsupported) {
      kept.push(sentence);
      continue;
    }
    if (!replaced) {
      kept.push(fallback);
      replaced = true;
    }
  }
  const text = kept.join(" ").replace(/\s+/g, " ").trim();
  return text || fallback;
}

export function extractFactualClaims(answer: string): FactualityClaim[] {
  const claims: Array<Omit<FactualityClaim, "supported" | "evidenceRefs">> = [];
  const seen = new Set<string>();
  const add = (kind: FactualityClaimKind, text: string, salience: FactualityClaimSalience) => {
    const clean = text.replace(/\s+/g, " ").trim();
    if (clean.length < 2 || clean.length > 160) {
      return;
    }
    const normalized = normalizeClaim(clean);
    const key = `${kind}:${normalized}`;
    if (!normalized || seen.has(key)) {
      return;
    }
    seen.add(key);
    claims.push({ kind, text: clean, normalized, salience });
  };

  const isoDateRegex = /\b(?:19|20|21)\d{2}-\d{1,2}-\d{1,2}\b/g;
  for (const match of answer.matchAll(isoDateRegex)) {
    add("date", match[0], "high");
  }

  const numericDateRegex = /\b\d{1,2}[./-]\d{1,2}(?:[./-](?:\d{2}|\d{4}))?\b/g;
  for (const match of answer.matchAll(numericDateRegex)) {
    add("date", match[0], "high");
  }

  const monthDateRegex = new RegExp(
    `\\b\\d{1,2}\\s+(?:${TURKISH_MONTHS})(?:\\s+(?:19|20|21)\\d{2})?\\b`,
    "giu",
  );
  for (const match of answer.matchAll(monthDateRegex)) {
    add("date", match[0], "high");
  }

  const numberRegex =
    /(?:[$€£]|TL|TRY|USD|EUR|GBP|₺)?\s*\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\b\s*(?:%|percent|yuzde|yüzde|tl|try|usd|eur|gbp|dolar|euro|puan|kg|km|mb|gb|tb|ms|sn|saat|gun|gün|hafta|ay|yil|yıl|adim|adım)?/giu;
  for (const match of answer.matchAll(numberRegex)) {
    const raw = match[0].trim();
    if (!raw || raw.includes("-") || raw.includes("/")) {
      continue;
    }
    add("number", raw, isHighSalienceNumber(raw) ? "high" : "medium");
  }

  const nameRegex =
    /\b[\p{Lu}İĞÜŞÖÇ][\p{L}\p{M}'’.&-]{1,}(?:\s+(?:[\p{Lu}İĞÜŞÖÇ][\p{L}\p{M}'’.&-]{1,}|AI|API|GPT|LLM|CEO|CTO|Inc\.?|Ltd\.?)){1,5}\b/gu;
  for (const match of answer.matchAll(nameRegex)) {
    const raw = match[0].trim();
    const first = stripDiacritics(raw.split(/\s+/)[0] ?? "");
    if (COMMON_TITLECASE_STARTS.has(first)) {
      continue;
    }
    add("name", raw, "high");
  }

  const acronymRegex = /\b(?:[A-Z]{2,8}|OpenAI|ChatGPT|Elyan)\b/g;
  for (const match of answer.matchAll(acronymRegex)) {
    add("name", match[0], "high");
  }

  return claims.map((claim) => ({ ...claim, supported: false, evidenceRefs: [] }));
}

function collectEvidenceSources(input: FactualityGateInput): EvidenceSource[] {
  const sources: EvidenceSource[] = [];
  const add = (ref: string, value: unknown) => {
    for (const text of collectStrings(value)) {
      const clean = text.replace(/\s+/g, " ").trim();
      if (clean.length < 2) {
        continue;
      }
      sources.push({ ref, text: clean.slice(0, 2_000) });
      if (sources.length >= MAX_EVIDENCE_SOURCES) {
        return;
      }
    }
  };
  add("current_turn", input.prompt);
  const context = input.understandingContext ?? null;
  add("continuity", context?.continuitySummary);
  add("active_goal", context?.activeGoal);
  add("context_packet", context?.contextPackets);
  add("retrieved_memory", context?.retrievedMemory);
  add("memory_recall", context?.memoryRecall);
  add("cognitive_context", context?.cognitiveContext);
  const metadata = input.inferenceMetadata ?? {};
  add("web_grounding", metadata.webSources);
  add("web_grounding_blocks", collectGroundingBlocks(metadata.blocks));
  add("tool_results", metadata.toolResults);
  add("retrieval", {
    memoryResultCount: metadata.memoryResultCount,
    retrievalMode: metadata.retrievalMode,
    retrievalSufficiency: metadata.retrievalSufficiency,
    dataGroundingLevel: metadata.dataGroundingLevel,
  });
  return sources.slice(0, MAX_EVIDENCE_SOURCES);
}

function collectGroundingBlocks(value: unknown): unknown[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (item && typeof item === "object" ? (item as Record<string, unknown>) : null))
    .filter((item): item is Record<string, unknown> => item?.type === "web_search")
    .slice(0, 8);
}

function collectStrings(value: unknown, depth = 0): string[] {
  if (value == null || depth > 5) {
    return [];
  }
  if (typeof value === "string") {
    return [value];
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return [String(value)];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => collectStrings(item, depth + 1)).slice(0, 80);
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .flatMap(([key, item]) => {
        if (/token|secret|password|credential/i.test(key)) {
          return [];
        }
        return collectStrings(item, depth + 1);
      })
      .slice(0, 80);
  }
  return [];
}

function evidenceSupportsClaim(evidence: string, claim: Pick<FactualityClaim, "kind" | "text" | "normalized">): boolean {
  const normalizedEvidence = normalizeForMatch(evidence);
  if (normalizedEvidence.includes(claim.normalized)) {
    return true;
  }
  if (claim.kind === "number" || claim.kind === "date") {
    const digits = claim.text.replace(/\D/g, "");
    return digits.length >= 3 && normalizedEvidence.replace(/\D/g, "").includes(digits);
  }
  return false;
}

function isHighSalienceNumber(raw: string): boolean {
  const lower = normalizeForMatch(raw);
  if (/[₺$€£%]/.test(raw) || /\b(tl|try|usd|eur|gbp|percent|yuzde|yüzde|dolar|euro|puan|kg|km|mb|gb|tb|ms|sn|saat|gun|gün|hafta|ay|yil|yıl|adim|adım)\b/i.test(lower)) {
    return true;
  }
  const numeric = Number(raw.replace(/[^\d.,-]/g, "").replace(/\.(?=\d{3}\b)/g, "").replace(",", "."));
  if (!Number.isFinite(numeric)) {
    return false;
  }
  return numeric >= 1900 || raw.includes(".") || raw.includes(",");
}

function normalizeClaim(value: string): string {
  return normalizeForMatch(value).replace(/^[^\p{L}\d]+|[^\p{L}\d]+$/gu, "");
}

function normalizeForMatch(value: string): string {
  return stripDiacritics(value)
    .toLocaleLowerCase("tr-TR")
    .replace(/[’']/g, "")
    .replace(/[^\p{L}\d%₺$€£]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function stripDiacritics(value: string): string {
  return value
    .replace(/İ/g, "I")
    .replace(/ı/g, "i")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "");
}

function splitSentences(text: string): string[] {
  const matches = text.match(/[^.!?\n]+[.!?]?|\n+/g) ?? [text];
  return matches.map((item) => item.trim()).filter(Boolean);
}

function fallbackSentence(sample: string): string {
  // BİLİNEN KUSUR: bu cümle kullanıcının cevabına girer ve Türkçesi aksansız
  // ("iddiayi", "kanitlarla", "dogrulayamiyorum"). Makine metni gibi okunur.
  //
  // Aksanları düzeltmek DENENDİ ve geri alındı (2026-08-28): tek başına bu
  // dizgeyi düzeltmek `generateGovernedSharedBrainReply runs factuality gate`
  // testini düşürüyor — tur cümleyi üretiyor, `factualityGateFallbackApplied`
  // doğru işaretleniyor, ama nihai metin genel yedeğe dönüyor. Sebep
  // bulunamadı: taranan hiçbir kapı (`isPlaceholderRefusal`,
  // `classifyReasoningDump`, `sanitizeAssistantVisibleText`,
  // `polishAssistantVisibleText`, blok kurucular) iki yazım arasında farklı
  // davranmıyor.
  //
  // Anlaşılmayan bir etkiyle göndermektense kusuru GÖRÜNÜR bırakmak doğru:
  // burada bir yerde yazıma duyarlı gizli bir bağ var ve onu bulmak bu
  // düzeltmenin ön koşulu.
  const turkish = "Bu iddiayi elimdeki kanitlarla dogrulayamiyorum; istersen bakabilirim.";
  const english = "I cannot verify that from the available evidence; want me to check?";
  // Elyan Türkçe-öncelikli: örnek metin AÇIKÇA İngilizce değilse Türkçe fallback
  // kullan. Kısa Türkçe girdiler ("2+2 kac", "Selam") aksan içermeyince yanlışlıkla
  // İngilizce fallback alıyordu.
  const clearlyEnglish =
    !looksTurkish(sample) &&
    /\b(the|and|is|are|was|were|please|check|verify|help|what|how|when|why|which|available|evidence)\b/i.test(
      sample,
    );
  return clearlyEnglish ? english : turkish;
}

function looksTurkish(value: string): boolean {
  return /[çğıöşüÇĞİÖŞÜ]|\b(ve|bir|icin|için|degil|değil|emin|istersen|bakayim|bakayım)\b/i.test(value);
}
