import type { DocumentSpec, ValidationIssue, ValidationResult } from "../types.js";

function issue(code: string, message: string, path: string, severity: "error" | "warning" = "error"): ValidationIssue {
  return { code, message, path, severity };
}

export function validateDocumentSpec(spec: DocumentSpec): ValidationResult {
  const issues: ValidationIssue[] = [];
  spec.sections.forEach((section, index) => {
    if (!section.content.trim()) {
      issues.push(issue("empty_section", "Document section content is missing.", `sections.${index}.content`));
    }
  });
  if (spec.documentType === "contract_draft") {
    issues.push(issue("legal_review_required", "Contract drafts should be reviewed before use.", "documentType", "warning"));
  }
  return {
    ok: issues.every((entry) => entry.severity !== "error"),
    errors: issues,
    warnings: issues
      .filter((entry) => entry.severity === "warning")
      .map(({ code, message, path }) => ({ code, message, path })),
  };
}
