import type { PdfSpec, ValidationIssue, ValidationResult } from "../types.js";

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

  return {
    ok: issues.every((entry) => entry.severity !== "error"),
    errors: issues,
    warnings: issues
      .filter((entry) => entry.severity === "warning")
      .map(({ code, message, path }) => ({ code, message, path })),
  };
}
