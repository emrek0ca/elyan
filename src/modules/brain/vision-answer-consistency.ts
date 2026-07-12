import type { VisionTaskDecision } from "./vision-task-policy.js";

const CODE_PATTERN = /(?<![\p{L}\p{N}])(?=[A-Z0-9._-]{3,24}(?![\p{L}\p{N}]))(?=[A-Z0-9._-]*\d)[A-Z][A-Z0-9._-]*/giu;
const CURRENCY_AMOUNT_PATTERN = /(?:[$€£₺]\s*\d{1,9}(?:[.,]\d{1,2})?|\d{1,9}(?:[.,]\d{1,2})?\s*(?:tl|try|usd|eur|gbp|₺|\$|€|£))/giu;
const LABELED_TOTAL_PATTERN = /(?:toplam|total|grand total|gesamt|totale|итого|المجموع)\s*[:=-]?\s*([$€£₺]?\s*\d{1,9}(?:[.,]\d{1,2})?\s*(?:tl|try|usd|eur|gbp|₺|\$|€|£)?)/giu;

function normalizeToken(value: string): string {
  const compact = value.toLocaleUpperCase("en-US").replace(/\s+/g, "");
  const currency = /(?:₺|TRY|TL)/u.test(compact)
    ? "TRY"
    : /(?:\$|USD)/u.test(compact)
      ? "USD"
      : /(?:€|EUR)/u.test(compact)
        ? "EUR"
        : /(?:£|GBP)/u.test(compact)
          ? "GBP"
          : null;
  if (currency) {
    const rawNumeric = compact.replace(/[^\d,.-]/g, "");
    const lastComma = rawNumeric.lastIndexOf(",");
    const lastDot = rawNumeric.lastIndexOf(".");
    const decimalSeparator = Math.max(lastComma, lastDot);
    const fractionalDigits = decimalSeparator >= 0 ? rawNumeric.length - decimalSeparator - 1 : 0;
    const numeric = fractionalDigits > 0 && fractionalDigits <= 2
      ? `${rawNumeric.slice(0, decimalSeparator).replace(/[.,]/g, "")}.${rawNumeric.slice(decimalSeparator + 1)}`
      : rawNumeric.replace(/[.,]/g, "");
    return `${currency}:${numeric}`;
  }
  return compact.replace(/^[._-]+|[._-]+$/g, "");
}

function collect(pattern: RegExp, text: string, captureGroup?: number): Set<string> {
  const tokens = new Set<string>();
  for (const match of text.matchAll(pattern)) {
    const value = match[captureGroup ?? 0];
    if (value) tokens.add(normalizeToken(value));
  }
  return tokens;
}

function extractCriticalTokens(text: string, task: VisionTaskDecision): Set<string> {
  if (["code_screenshot", "screen_debugging", "document_ocr"].includes(task.primary)) {
    return collect(CODE_PATTERN, text);
  }
  if (task.primary === "receipt_or_invoice") {
    const totals = collect(LABELED_TOTAL_PATTERN, text, 1);
    return totals.size > 0 ? totals : collect(CURRENCY_AMOUNT_PATTERN, text);
  }
  return new Set();
}

export function assessVisionAnswerConsistency(input: {
  primary: string;
  secondary: string;
  task: VisionTaskDecision;
  comparisonMode?: "exact" | "overlap";
}): { conflictDetected: boolean; reason: "critical_values_disagree" | "not_comparable" | "consistent" } {
  const primary = extractCriticalTokens(input.primary, input.task);
  const secondary = extractCriticalTokens(input.secondary, input.task);
  if (primary.size === 0 || secondary.size === 0) {
    return { conflictDetected: false, reason: "not_comparable" };
  }
  const same = input.comparisonMode === "overlap"
    ? [...primary].some((token) => secondary.has(token))
    : primary.size === secondary.size && [...primary].every((token) => secondary.has(token));
  return same
    ? { conflictDetected: false, reason: "consistent" }
    : { conflictDetected: true, reason: "critical_values_disagree" };
}
