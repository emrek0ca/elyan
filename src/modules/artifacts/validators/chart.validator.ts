import type { ChartSpec, ValidationIssue, ValidationResult } from "../types.js";
import {
  extractExplicitNumericSequence,
  normalizeKey,
  parseNumericValue,
} from "../utils.js";

function issue(code: string, message: string, path: string, severity: "error" | "warning" = "error"): ValidationIssue {
  return { code, message, path, severity };
}

export function validateChartSpec(spec: ChartSpec): ValidationResult {
  const issues: ValidationIssue[] = [];
  if (spec.data.length === 0) {
    issues.push(issue("empty_chart_data", "Chart data cannot be empty.", "data"));
  }
  if (spec.xKey && spec.data.some((row) => !(spec.xKey! in row))) {
    issues.push(issue("x_key_missing", "xKey must exist in every data row.", "xKey"));
  }
  if (spec.yKey && spec.data.some((row) => !(spec.yKey! in row))) {
    issues.push(issue("y_key_missing", "yKey must exist in every data row.", "yKey"));
  }
  if (spec.yKey) {
    spec.data.forEach((row, index) => {
      if (parseNumericValue(row[spec.yKey!]) == null) {
        issues.push(
          issue(
            "chart_value_non_numeric",
            "Chart values must be finite numbers.",
            `data.${index}.${spec.yKey}`,
          ),
        );
      }
    });
  }
  if (spec.xKey) {
    spec.data.forEach((row, index) => {
      if (String(row[spec.xKey!] ?? "").trim().length === 0) {
        issues.push(
          issue(
            "chart_label_missing",
            "Every chart value must have a matching label.",
            `data.${index}.${spec.xKey}`,
          ),
        );
      }
    });
  }
  if (spec.chartType === "pie") {
    const total = spec.data.reduce((sum, row) => sum + (parseNumericValue(row[spec.yKey ?? "value"]) ?? 0), 0);
    if (total <= 0) {
      issues.push(issue("pie_total_invalid", "Pie chart values must form a positive total.", "data"));
    }
  }
  if (spec.chartType === "line" && spec.xKey) {
    const values = spec.data.map((row) => row[spec.xKey!]);
    const sorted = [...values].sort((a, b) => String(a).localeCompare(String(b), "tr"));
    if (values.map(String).join("\u0000") !== sorted.map(String).join("\u0000")) {
      issues.push(issue("line_x_axis_unsorted", "Line chart x-axis is not sorted.", "data", "warning"));
    }
  }
  if (spec.chartType === "scatter") {
    for (const [index, row] of spec.data.entries()) {
      if (parseNumericValue(row[spec.xKey ?? "x"]) == null || parseNumericValue(row[spec.yKey ?? "y"]) == null) {
        issues.push(issue("scatter_non_numeric", "Scatter chart requires numeric x and y values.", `data.${index}`));
      }
    }
  }

  const explicitSequence = extractExplicitNumericSequence(spec.sourceText ?? "");
  if (explicitSequence.length > 0) {
    const xKey = spec.xKey;
    if (!xKey || spec.data.length !== explicitSequence.length) {
      issues.push(
        issue(
          "explicit_sequence_not_covered",
          "Chart data must cover every explicitly requested number exactly once.",
          "data",
        ),
      );
    } else {
      const actualInputs = spec.data.map((row) => parseNumericValue(row[xKey]));
      if (
        actualInputs.some((value) => value == null) ||
        actualInputs.some((value, index) => Math.abs((value ?? 0) - explicitSequence[index]!) > 1e-9)
      ) {
        issues.push(
          issue(
            "explicit_sequence_mismatch",
            "Chart x-axis values do not match the explicitly requested number sequence.",
            "data",
          ),
        );
      }
    }

    if (/\b(?:kare(?:si|leri|lerini)?|square(?:s|d)?)\b/iu.test(spec.sourceText ?? "")) {
      const squareSeries =
        spec.series?.find((series) =>
          /^(?:kare|square|squared|sonuc|result)$/u.test(normalizeKey(series.label)),
        ) ??
        spec.series?.find((series) =>
          /^(?:kare|square|squared|sonuc|result)$/u.test(normalizeKey(series.key)),
        );
      const resultKey = squareSeries?.key ?? spec.yKey;
      if (!xKey || !resultKey) {
        issues.push(
          issue(
            "square_axes_missing",
            "Square charts require both input and square-result axes.",
            "series",
          ),
        );
      } else {
        spec.data.forEach((row, rowIndex) => {
          const input = parseNumericValue(row[xKey]);
          const square = parseNumericValue(row[resultKey]);
          if (input == null || square == null || Math.abs(input * input - square) > 1e-9) {
            issues.push(
              issue(
                "unsafe_math_mismatch",
                "Computed chart square does not match its input value.",
                `data.${rowIndex}.${resultKey}`,
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
