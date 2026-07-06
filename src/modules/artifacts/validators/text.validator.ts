import type { TextSpec, ValidationIssue, ValidationResult } from "../types.js";

function issue(code: string, message: string, path: string, severity: "error" | "warning" = "error"): ValidationIssue {
  return { code, message, path, severity };
}

export function validateTextSpec(spec: TextSpec): ValidationResult {
  const issues: ValidationIssue[] = [];
  const text = spec.blocks.map((block) => block.text).join("\n\n").trim();
  if (!text) {
    issues.push(issue("empty_text", "Text artifact cannot be empty.", "blocks"));
  }
  if (spec.tone === "short" && text.length > 500) {
    issues.push(issue("too_long_for_short_tone", "Short text is too long.", "blocks", "warning"));
  }
  if (spec.language === "tr" && /\b(the|and|with|please)\b/i.test(text)) {
    issues.push(issue("language_mismatch", "Text language appears inconsistent.", "language", "warning"));
  }
  if (spec.renderOptions?.["only_text"] === true && /\b(açıklama|not:|şunu yaptım)\b/i.test(text)) {
    issues.push(issue("extra_explanation", "Only-text request should not include extra explanation.", "blocks"));
  }
  return {
    ok: issues.every((entry) => entry.severity !== "error"),
    errors: issues,
    warnings: issues
      .filter((entry) => entry.severity === "warning")
      .map(({ code, message, path }) => ({ code, message, path })),
  };
}
