import {
  polishAssistantVisibleText,
  sanitizeAssistantVisibleText,
} from "../chat/message-blocks.js";
import {
  classifyReasoningDump,
  extractFinalAnswerFromReasoningDump,
} from "./reasoning-guard.js";
import { computeStreamVisibleText } from "./typed-json-blocks.js";

/**
 * A reply whose entire content is an internal-reasoning dump is worse than an
 * empty stream: the sanitizer strips all of it and the user gets a stub.
 * Typed blocks count as real content because the visible-text gate removes
 * them first.
 */
export function isReasoningOnlyReply(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  const prose = computeStreamVisibleText(trimmed);
  if (!prose.trim()) {
    return false;
  }
  const visible = sanitizeAssistantVisibleText(prose, { fallback: "" });
  if (!visible.trim()) {
    return true;
  }
  return classifyReasoningDump(visible).isDump;
}

type VisibleAnswerSanitizerOptions = Parameters<
  typeof sanitizeAssistantVisibleText
>[1];

function rescueVisibleAnswerFromRawText(
  raw: string,
  options: VisibleAnswerSanitizerOptions = {},
): string | null {
  const visible = computeStreamVisibleText(String(raw ?? ""));
  const extracted = extractFinalAnswerFromReasoningDump(visible || String(raw ?? ""));
  if (!extracted) {
    return null;
  }
  const sanitized = sanitizeAssistantVisibleText(extracted, {
    ...options,
    fallback: extracted,
  });
  return sanitized.trim() ? sanitized : extracted;
}

export function resolveCleanVisibleAnswer(input: {
  candidates: Array<string | null | undefined>;
  raw: string;
  options?: VisibleAnswerSanitizerOptions;
}): string {
  const options = input.options ?? {};
  for (const candidate of input.candidates) {
    if (!candidate?.trim()) {
      continue;
    }
    const sanitized = polishAssistantVisibleText(
      sanitizeAssistantVisibleText(candidate, { ...options, fallback: "" }),
      options,
    );
    if (!sanitized.trim()) {
      continue;
    }
    if (classifyReasoningDump(sanitized).isDump) {
      const rescuedFromCandidate = rescueVisibleAnswerFromRawText(
        candidate,
        options,
      );
      if (rescuedFromCandidate) {
        return rescuedFromCandidate;
      }
      continue;
    }
    return sanitized;
  }

  const rescued = rescueVisibleAnswerFromRawText(input.raw, options);
  if (rescued) {
    return rescued;
  }

  const rawVisible = computeStreamVisibleText(String(input.raw ?? "")).trim();
  if (rawVisible && !classifyReasoningDump(rawVisible).isDump) {
    const polished = polishAssistantVisibleText(rawVisible, options);
    return polished.trim() || rawVisible;
  }

  return "";
}
