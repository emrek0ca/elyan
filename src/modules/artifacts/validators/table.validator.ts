import type { TableSpec, ValidationIssue, ValidationResult } from "../types.js";
import { parseNumericValue } from "../utils.js";

function issue(code: string, message: string, path: string, severity: "error" | "warning" = "error"): ValidationIssue {
  return { code, message, path, severity };
}

export function validateTableSpec(spec: TableSpec): ValidationResult {
  const issues: ValidationIssue[] = [];
  const seenKeys = new Set<string>();
  for (const [index, column] of spec.columns.entries()) {
    if (seenKeys.has(column.key)) {
      issues.push(issue("duplicate_column_key", "Column keys must be stable and unique.", `columns.${index}.key`));
    }
    seenKeys.add(column.key);
  }

  spec.rows.forEach((row, rowIndex) => {
    for (const column of spec.columns) {
      const value = row[column.key];
      if (column.required !== false && (value == null || String(value).trim() === "")) {
        issues.push(issue("missing_required_cell", "Row is missing a required column.", `rows.${rowIndex}.${column.key}`));
      }
      if (
        (column.dataType === "number" || column.dataType === "currency") &&
        value != null &&
        typeof value !== "number" &&
        parseNumericValue(value) == null
      ) {
        issues.push(issue("invalid_numeric_cell", "Numeric/currency cells must be parseable.", `rows.${rowIndex}.${column.key}`));
      }
    }
  });

  if (spec.summary) {
    for (const [key, value] of Object.entries(spec.summary.values)) {
      const column = spec.columns.find((entry) => entry.key === key);
      if (!column || (column.dataType !== "number" && column.dataType !== "currency")) {
        continue;
      }
      const expected = spec.rows.reduce((sum, row) => {
        const parsed = typeof row[key] === "number" ? row[key] as number : parseNumericValue(row[key]) ?? 0;
        return sum + parsed;
      }, 0);
      const actual = typeof value === "number" ? value : parseNumericValue(value);
      if (actual == null || Math.abs(expected - actual) > 0.01) {
        issues.push(issue("summary_mismatch", "Summary value does not match row values.", `summary.values.${key}`));
      }
    }
  }

  const normalizedLabels = spec.columns.map((column) => column.label.trim().toLocaleLowerCase("tr-TR"));
  if (new Set(normalizedLabels).size !== normalizedLabels.length) {
    issues.push(issue("duplicate_column_label", "Same information appears in multiple columns.", "columns", "warning"));
  }

  if (spec.sort && !spec.columns.some((column) => column.key === spec.sort?.key)) {
    issues.push(issue("sort_key_missing", "Requested sort key is not present in columns.", "sort.key"));
  }

  return {
    ok: issues.every((entry) => entry.severity !== "error"),
    errors: issues,
    warnings: issues
      .filter((entry) => entry.severity === "warning")
      .map(({ code, message, path }) => ({ code, message, path })),
  };
}
