import type { TableSpec, ValidationIssue, ValidationResult } from "../types.js";
import {
  extractExplicitNumericSequence,
  extractRequestedTableColumns,
  normalizeKey,
  parseNumericValue,
} from "../utils.js";

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

  const requestedColumns = Array.isArray(spec.renderOptions?.requestedColumns)
    ? spec.renderOptions.requestedColumns.filter(
        (value): value is string => typeof value === "string" && value.trim().length > 0,
      )
    : extractRequestedTableColumns(spec.sourceText ?? "");
  if (requestedColumns.length > 0) {
    const actualLabels = new Set(spec.columns.map((column) => normalizeKey(column.label)));
    for (const requested of requestedColumns) {
      if (!actualLabels.has(normalizeKey(requested))) {
        issues.push(
          issue(
            "requested_column_missing",
            `Requested table column is missing: ${requested}`,
            "columns",
          ),
        );
      }
    }
  }

  const explicitSequence = extractExplicitNumericSequence(spec.sourceText ?? "");
  if (explicitSequence.length > 0) {
    const inputColumn =
      spec.columns.find((column) => /^(?:sayi|number|input|girdi)$/u.test(normalizeKey(column.label))) ??
      spec.columns.find((column) => column.dataType === "number");
    if (!inputColumn || spec.rows.length !== explicitSequence.length) {
      issues.push(
        issue(
          "explicit_sequence_not_covered",
          "Table rows must cover every explicitly requested number exactly once.",
          "rows",
        ),
      );
    } else {
      const actualInputs = spec.rows.map((row) => parseNumericValue(row[inputColumn.key]));
      if (
        actualInputs.some((value) => value == null) ||
        actualInputs.some((value, index) => Math.abs((value ?? 0) - explicitSequence[index]!) > 1e-9)
      ) {
        issues.push(
          issue(
            "explicit_sequence_mismatch",
            "Table input values do not match the explicitly requested number sequence.",
            "rows",
          ),
        );
      }
    }

    if (/\b(?:kare(?:si|leri|lerini)?|square(?:s|d)?)\b/iu.test(spec.sourceText ?? "")) {
      const squareColumn = spec.columns.find((column) =>
        /^(?:kare|square|squared|sonuc|result)$/u.test(normalizeKey(column.label)),
      );
      if (!inputColumn || !squareColumn) {
        issues.push(
          issue(
            "square_columns_missing",
            "Square tables require both input and square-result columns.",
            "columns",
          ),
        );
      } else {
        spec.rows.forEach((row, rowIndex) => {
          const input = parseNumericValue(row[inputColumn.key]);
          const square = parseNumericValue(row[squareColumn.key]);
          if (input == null || square == null || Math.abs(input * input - square) > 1e-9) {
            issues.push(
              issue(
                "unsafe_math_mismatch",
                "Computed square does not match its input value.",
                `rows.${rowIndex}.${squareColumn.key}`,
              ),
            );
          }
        });
      }
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
