import type { UserUnderstandingContext } from "../../core/understanding/types.js";

export type PromptLanguage = "tr" | "en" | "turkic" | "mixed" | "unknown";
export type DataGroundingLevel =
  | "attachment_grounded"
  | "memory_augmented"
  | "request_only";

type DataGroundingInput = {
  attachmentContext?: { used?: boolean } | null;
  understandingContext?: Pick<
    UserUnderstandingContext,
    "contextPackets" | "retrievedMemory"
  >;
};

function compactText(value: unknown): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

export function detectPromptLanguage(prompt: string): PromptLanguage {
  const compact = compactText(prompt);
  if (!compact) {
    return "unknown";
  }

  const lowered = compact.toLocaleLowerCase("tr-TR");
  const hasTurkishChars = /[çğıöşü]/i.test(compact);
  const turkishSignals =
    /\b(selam|merhaba|ve|ile|için|bunu|şunu|burada|nedir|nasıl|özetle|düzelt|belge|görsel)\b/i.test(
      lowered,
    );
  const englishSignals =
    /\b(the|and|for|what|how|summarize|analyze|fix|document|image)\b/i.test(
      lowered,
    );
  const turkicSignals =
    /\b(oğuz|kıpçak|karluk|özbek|kazak|kırgız|türkmen|uygur|azerbaycan)\b/i.test(
      lowered,
    );

  if ((hasTurkishChars || turkishSignals) && englishSignals) {
    return "mixed";
  }
  if (turkicSignals && !turkishSignals && !hasTurkishChars) {
    return "turkic";
  }
  if (hasTurkishChars || turkishSignals) {
    return "tr";
  }
  if (englishSignals) {
    return "en";
  }
  return "unknown";
}

export function inferDataGroundingLevel(
  input: DataGroundingInput,
): DataGroundingLevel {
  if (input.attachmentContext?.used) {
    return "attachment_grounded";
  }
  if ((input.understandingContext?.contextPackets?.length ?? 0) > 0) {
    return "memory_augmented";
  }
  if ((input.understandingContext?.retrievedMemory?.length ?? 0) > 0) {
    return "memory_augmented";
  }
  return "request_only";
}
