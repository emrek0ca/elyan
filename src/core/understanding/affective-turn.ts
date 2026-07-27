import { nlpDaemon } from "../../lib/nlp-daemon.js";

export type AffectiveTurnMood =
  | "positive"
  | "frustrated"
  | "anxious"
  | "sad"
  | "tired"
  | "curious"
  | "negative"
  | "neutral";

export type AffectiveTurnSignal = {
  mood: AffectiveTurnMood;
  energy: "low" | "mid" | "high";
  confidence: number;
  source: "nlp_daemon" | "typed_fallback";
  responseDirective: string;
};

const typedMoodPatterns: Array<[AffectiveTurnMood, RegExp]> = [
  ["frustrated", /(?<!\p{L})(sinir\p{L}*|kızg\p{L}*|kizg\p{L}*|bık\p{L}*|bik\p{L}*|olmadı|olmadi|çalışmıyor|calismiyor|frustrated|angry|annoyed|broken)(?!\p{L})/iu],
  ["anxious", /(?<!\p{L})(kayg\p{L}*|endiş\p{L}*|endis\p{L}*|stres\p{L}*|gergin\p{L}*|panik\p{L}*|anxious|worried|nervous|overwhelmed)(?!\p{L})/iu],
  ["sad", /(?<!\p{L})(üzg\p{L}*|uzg\p{L}*|mutsuz\p{L}*|kötü hissed\p{L}*|kotu hissed\p{L}*|sad|unhappy|lonely|down)(?!\p{L})/iu],
  ["tired", /(?<!\p{L})(yorgun\p{L}*|bitkin\p{L}*|tüken\p{L}*|tuken\p{L}*|tired|exhausted|drained|burnout)(?!\p{L})/iu],
  ["curious", /(?<!\p{L})(merak\p{L}*|öğrenmek ist\p{L}*|ogrenmek ist\p{L}*|curious|intrigued)(?!\p{L})/iu],
  ["positive", /(?<!\p{L})(mutlu\p{L}*|heyecan\p{L}*|harika|mükemmel|mukemmel|süper|super|happy|excited|great|excellent)(?!\p{L})/iu],
];

function directiveFor(mood: AffectiveTurnMood, energy: AffectiveTurnSignal["energy"]): string {
  switch (mood) {
    case "frustrated":
      return "Be calm, concrete, and solution-first; avoid humor and unnecessary preamble.";
    case "anxious":
      return "Use a steady, warm tone, reduce uncertainty with concrete next steps, and do not diagnose.";
    case "sad":
      return "Respond with restrained warmth and care; do not become theatrical or make clinical claims.";
    case "tired":
      return "Keep cognitive load low: short sentences, clear ordering, and only the next useful details.";
    case "curious":
      return "Match the user's curiosity with an engaged, explanatory tone and concrete examples.";
    case "positive":
      return energy === "high"
        ? "Use a lively but natural tone; keep claims precise and avoid exaggerated praise."
        : "Use a warm, natural tone while staying direct.";
    case "negative":
      return "Use a calm, precise tone and focus on resolving the concrete issue.";
    default:
      return "Use a natural tone that matches the user's language and request.";
  }
}

function typedMood(message: string): AffectiveTurnMood {
  for (const [mood, pattern] of typedMoodPatterns) {
    if (pattern.test(message)) return mood;
  }
  return "neutral";
}

export async function detectAffectiveTurn(
  message: string,
): Promise<AffectiveTurnSignal> {
  const compact = message.replace(/\s+/g, " ").trim().slice(0, 2_000);
  const explicitMood = typedMood(compact);
  const sentiment = nlpDaemon.isAvailable()
    ? await nlpDaemon.scoreSentiment(compact).catch(() => null)
    : null;
  const mood =
    explicitMood !== "neutral"
      ? explicitMood
      : sentiment?.label === "positive"
        ? "positive"
        : sentiment?.label === "negative"
          ? "negative"
          : "neutral";
  const energy: AffectiveTurnSignal["energy"] =
    mood === "tired" || mood === "sad"
      ? "low"
      : mood === "positive" && /!{2,}/u.test(compact)
        ? "high"
        : "mid";
  const confidence =
    explicitMood !== "neutral"
      ? 0.82
      : sentiment
        ? Math.max(0.55, Math.min(0.78, sentiment.score))
        : 0.45;

  return {
    mood,
    energy,
    confidence,
    source: sentiment ? "nlp_daemon" : "typed_fallback",
    responseDirective: directiveFor(mood, energy),
  };
}
