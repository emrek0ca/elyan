import type { ImagePromptSpec, ValidationIssue, ValidationResult } from "../types.js";

function issue(code: string, message: string, path: string, severity: "error" | "warning" = "error"): ValidationIssue {
  return { code, message, path, severity };
}

export function validateImagePromptSpec(spec: ImagePromptSpec): ValidationResult {
  const issues: ValidationIssue[] = [];
  if (!spec.subject.trim()) {
    issues.push(issue("missing_subject", "Image prompt subject is required.", "subject"));
  }
  if (!spec.prompt.trim()) {
    issues.push(issue("missing_prompt", "Image prompt text is required.", "prompt"));
  }
  if (spec.character_lock && !spec.constraints.some((constraint) => /değişmeyecek|degismeyecek|preserve|lock/i.test(constraint))) {
    issues.push(issue("character_lock_without_constraint", "Character lock must be represented as an explicit constraint.", "constraints"));
  }
  return {
    ok: issues.every((entry) => entry.severity !== "error"),
    errors: issues,
    warnings: issues
      .filter((entry) => entry.severity === "warning")
      .map(({ code, message, path }) => ({ code, message, path })),
  };
}
