import { formatMemoryProfilePromptBlock } from "../../core/understanding/memory-profile.js";
import type { UserUnderstandingContext } from "../../core/understanding/types.js";
import { formatTurkicLanguageLabel } from "../../core/understanding/turkic-language.js";

function compactText(value: unknown): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function sentenceCase(value: string): string {
  const compact = compactText(value);
  if (!compact) {
    return compact;
  }
  return compact.charAt(0).toUpperCase() + compact.slice(1);
}

export function formatPreferencePromptValue(key: string, value: string): string {
  const normalizedKey = compactText(key).toLowerCase();
  const normalizedValue = compactText(value).toLowerCase();
  if (normalizedKey === "preferred_language" || normalizedKey === "language") {
    return sentenceCase(formatTurkicLanguageLabel(value));
  }
  const translations: Record<string, Record<string, string>> = {
    response_style_preference: {
      formal: "resmi",
      balanced: "dengeli",
      warm: "sıcak",
    },
    preferred_tone: {
      warm_professional: "sıcak ve profesyonel",
      warm: "sıcak",
      formal: "resmi",
      balanced: "dengeli",
    },
    answer_length: {
      concise: "kısa ve öz",
      detailed: "detaylı",
      "detailed when needed": "gerektiğinde detaylı",
    },
    brevity_preference: {
      short: "kısa",
      concise: "kısa ve öz",
      balanced: "dengeli",
    },
    humor_level: {
      restrained: "kısıtlı",
      light: "hafif",
      off: "kapalı",
    },
  };

  const mapped = translations[normalizedKey]?.[normalizedValue] ?? value;
  return sentenceCase(mapped);
}

export function buildPreferencePromptBlock(
  context: UserUnderstandingContext | undefined,
): string | null {
  if (!context) {
    return null;
  }

  const hints: string[] = [];
  const seen = new Set<string>();
  const pushHint = (value: string) => {
    const compact = compactText(value);
    if (!compact) {
      return;
    }
    const key = compact.toLowerCase();
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    hints.push(compact);
  };

  const preferenceFacts = context.memorySnapshot?.preferenceFacts ?? [];
  if (context.personalizationPrompt) {
    pushHint(
      `Explicit personalization directive from user settings: ${context.personalizationPrompt}. Apply this to tone, pacing, formatting, and interaction style when relevant, but never let it override safety, privacy, honesty, routing truth, or factual accuracy.`,
    );
  }
  pushHint(
    context.memoryEnabled
      ? "Memory is enabled for this user: use only the relevant current-user memory shortlist, prefer verified/stable facts, and ignore stale or unrelated memories."
      : "Memory is disabled for this request: do not use saved personal memories or imply cross-chat recall; rely only on the current message and explicitly provided context.",
  );
  pushHint(
    "Advice stance: when the user asks what to choose, recommend one path instead of staying neutral. Tie the reason to the relevant preference, style hint, relationship digest, goal, or current request evidence; never invent a personal reason that is not present here.",
  );
  pushHint(
    "Advice few-shot shape: 'Iki yol var; senin durumunda A'yi secerdim, cunku [relevant memory/digest/current-request reason]. B ancak [clear tradeoff] icin mantikli.' Use this shape naturally in the user's language.",
  );
  pushHint(
    "Personalization dosage: adapt wording and examples silently first. Use the user's name only for a meaningful greeting, emotional support, or an important transition; never repeat it across ordinary replies and never mention memory mechanics.",
  );
  const dialogueUserMemory = context.dialogueUserMemory;
  if (dialogueUserMemory?.preferredName) {
    pushHint(
      `Current dialogue state preferred name: ${dialogueUserMemory.preferredName}. This is available when direct address genuinely improves the moment; it is not a requirement to address the user.`,
    );
  }
  if (dialogueUserMemory?.preferredLanguage) {
    pushHint(
      `Current dialogue state preferred language: ${formatPreferencePromptValue("preferred_language", dialogueUserMemory.preferredLanguage)}.`,
    );
  }
  if (dialogueUserMemory?.preferredTone || dialogueUserMemory?.responseStyle) {
    pushHint(
      `Current dialogue state style: ${[
        dialogueUserMemory.preferredTone
          ? `tone=${formatPreferencePromptValue("preferred_tone", dialogueUserMemory.preferredTone)}`
          : null,
        dialogueUserMemory.responseStyle
          ? `response_style=${formatPreferencePromptValue("response_style_preference", dialogueUserMemory.responseStyle)}`
          : null,
      ].filter(Boolean).join(", ")}.`,
    );
  }
  const preferredLanguageFact = preferenceFacts.find(
    (item) => item.key === "preferred_language" || item.key === "language",
  );
  if (preferredLanguageFact) {
    const languageValue = formatPreferencePromptValue(
      preferredLanguageFact.key,
      preferredLanguageFact.value,
    );
    pushHint(
      `Preferred language: ${languageValue}. When the user writes in a Turkic language, answer in the same language when possible; otherwise use polished standard Turkish by default and do not mirror typos or broken punctuation.`,
    );
  }

  const responseStyleFact = preferenceFacts.find(
    (item) =>
      item.key === "response_style_preference" || item.key === "preferred_tone",
  );
  if (responseStyleFact) {
    pushHint(
      `Response style preference: ${formatPreferencePromptValue(responseStyleFact.key, responseStyleFact.value)}.`,
    );
  }

  const answerLengthFact = preferenceFacts.find(
    (item) => item.key === "answer_length" || item.key === "brevity_preference",
  );
  if (answerLengthFact) {
    pushHint(
      `Answer length preference: ${formatPreferencePromptValue(answerLengthFact.key, answerLengthFact.value)}.`,
    );
  }

  for (const hint of [
    ...(context.personalizationHints ?? []).slice(0, 2),
    ...(context.styleHints ?? []).slice(0, 3),
    ...(context.safetyHints ?? []).slice(0, 2),
  ]) {
    pushHint(hint);
  }
  for (const hint of (context.relationshipContextDigest ?? []).slice(0, 2)) {
    pushHint(hint);
  }
  for (const hint of (context.speakingStyleDirectives ?? []).slice(0, 3)) {
    pushHint(hint);
  }
  for (const hint of [
    ...(context.behavioralHints ?? []).slice(0, 2),
    ...(context.environmentHints ?? []).slice(0, 2),
  ]) {
    pushHint(hint);
  }

  if (!hints.length) {
    return null;
  }

  return ["User preference hints:", ...hints.map((item) => `- ${item}`)].join(
    "\n",
  );
}

export function buildMemoryProfilePromptBlock(
  context: UserUnderstandingContext | undefined,
): string | null {
  return formatMemoryProfilePromptBlock(context?.memorySnapshot);
}
