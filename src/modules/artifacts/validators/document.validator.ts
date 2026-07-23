import type { DocumentSpec, ValidationIssue, ValidationResult } from "../types.js";

function issue(code: string, message: string, path: string, severity: "error" | "warning" = "error"): ValidationIssue {
  return { code, message, path, severity };
}

export function validateDocumentSpec(spec: DocumentSpec): ValidationResult {
  const issues: ValidationIssue[] = [];
  const content = spec.sections
    .map((section) => `${section.heading ?? ""}\n${section.content}`)
    .join("\n")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("tr-TR");
  spec.sections.forEach((section, index) => {
    if (!section.content.trim()) {
      issues.push(issue("empty_section", "Document section content is missing.", `sections.${index}.content`));
    }
  });
  if (spec.documentType === "contract_draft") {
    issues.push(issue("legal_review_required", "Contract drafts should be reviewed before use.", "documentType", "warning"));
  }
  const requiredExactTexts = Array.isArray(spec.renderOptions?.requiredExactTexts)
    ? spec.renderOptions.requiredExactTexts.filter(
        (value): value is string => typeof value === "string" && value.trim().length > 0,
      )
    : [];
  for (const required of requiredExactTexts) {
    const normalized = required
      .normalize("NFKC")
      .replace(/\s+/g, " ")
      .trim()
      .toLocaleLowerCase("tr-TR");
    if (normalized && !content.includes(normalized)) {
      issues.push(
        issue(
          "required_exact_text_missing",
          "Document does not preserve an explicitly required footer or signature.",
          "sections",
        ),
      );
    }
  }
  return {
    ok: issues.every((entry) => entry.severity !== "error"),
    errors: issues,
    warnings: issues
      .filter((entry) => entry.severity === "warning")
      .map(({ code, message, path }) => ({ code, message, path })),
  };
}
