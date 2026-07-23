import type { PdfSpec, TableSpec, ValidationIssue, ValidationResult } from "../types.js";
import { validateTableSpec } from "./table.validator.js";

function issue(code: string, message: string, path: string, severity: "error" | "warning" = "error"): ValidationIssue {
  return { code, message, path, severity };
}

export function validatePdfSpec(spec: PdfSpec): ValidationResult {
  const issues: ValidationIssue[] = [];
  const lineItems = spec.blocks.filter((block) => block.type === "line_item");
  const totals = spec.blocks.filter((block) => block.type === "total");
  const footers = spec.blocks.filter((block) => block.type === "footer");

  spec.blocks.forEach((block, index) => {
    if (
      ["title", "subtitle", "paragraph", "signature", "footer"].includes(block.type) &&
      !String(block.text ?? block.label ?? "").trim()
    ) {
      issues.push(issue("missing_text", "PDF block text is missing.", `blocks.${index}.text`));
    }
    if (
      (block.type === "line_item" || block.type === "total") &&
      (typeof block.amount !== "number" || !Number.isFinite(block.amount))
    ) {
      issues.push(issue("invalid_money_amount", "Money block amount must be numeric.", `blocks.${index}.amount`));
    }
    if (block.type === "table") {
      const columns = block.columns ?? [];
      const rows = block.rows ?? [];
      if (columns.length === 0 || rows.length === 0) {
        issues.push(issue("pdf_table_empty", "PDF table requires columns and rows.", `blocks.${index}`));
      } else {
        for (const [rowIndex, row] of rows.entries()) {
          for (const column of columns) {
            if (!(column.key in row)) {
              issues.push(
                issue(
                  "pdf_table_cell_missing",
                  "PDF table row is missing a declared column.",
                  `blocks.${index}.rows.${rowIndex}.${column.key}`,
                ),
              );
            }
          }
        }
        const tableValidation = validateTableSpec({
          id: `${spec.id}:table:${index}`,
          type: "table",
          intent: spec.intent,
          sourceText: spec.sourceText,
          locale: spec.locale,
          blocks: [],
          renderOptions: spec.renderOptions,
          validationRules: spec.validationRules,
          metadata: spec.metadata,
          columns,
          rows,
        } satisfies TableSpec);
        issues.push(
          ...tableValidation.errors.map((entry) => ({
            ...entry,
            path: `blocks.${index}.${entry.path ?? "table"}`,
          })),
        );
      }
    }
  });

  if (lineItems.length > 0 && totals.length > 0) {
    const computed = lineItems.reduce((sum, block) => sum + (typeof block.amount === "number" ? block.amount : 0), 0);
    const userTotal = totals.find((block) => block.source === "user") ?? totals[0];
    const declared = typeof userTotal?.amount === "number" ? userTotal.amount : null;
    if (declared != null && Math.abs(computed - declared) > 0.01) {
      issues.push(issue(
        "total_mismatch",
        `Line items total ${computed} but declared total is ${declared}.`,
        "blocks.total.amount",
      ));
    }
  }

  if (footers.length > 0 && !spec.footer?.text) {
    issues.push(issue("footer_not_in_footer_slot", "Footer block must be mirrored into spec.footer.", "footer"));
  }
  footers.forEach((block, index) => {
    if (block.placement !== "footer") {
      issues.push(issue("footer_wrong_placement", "Footer text must be placed in the footer area.", `blocks.${index}.placement`));
    }
  });
  if (spec.footer?.text && !footers.some((block) => block.text === spec.footer?.text)) {
    issues.push(issue("footer_block_missing", "Explicit footer text must also exist as a footer block.", "blocks"));
  }
  if (spec.blocks.length > 34) {
    issues.push(issue("page_overflow_risk", "PDF has enough blocks to risk page overflow.", "blocks", "warning"));
  }
  if (lineItems.length > 0 && lineItems.some((block) => !block.label?.trim())) {
    issues.push(issue("line_item_label_missing", "Every line item needs a label.", "blocks.line_item.label"));
  }
  const requiredExactTexts = Array.isArray(spec.renderOptions?.requiredExactTexts)
    ? spec.renderOptions.requiredExactTexts.filter(
        (value): value is string => typeof value === "string" && value.trim().length > 0,
      )
    : [];
  const preservedText = [
    ...spec.blocks.flatMap((block) => [block.text, block.label]),
    spec.footer?.text,
  ]
    .filter((value): value is string => typeof value === "string")
    .join(" ")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .toLocaleLowerCase("tr-TR");
  for (const required of requiredExactTexts) {
    const normalized = required
      .normalize("NFKC")
      .replace(/\s+/g, " ")
      .trim()
      .toLocaleLowerCase("tr-TR");
    if (normalized && !preservedText.includes(normalized)) {
      issues.push(
        issue(
          "required_exact_text_missing",
          "PDF does not preserve an explicitly required footer or signature.",
          "blocks",
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
