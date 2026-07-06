import type { ChartSpec, ValidationIssue, ValidationResult } from "../types.js";
import { parseNumericValue } from "../utils.js";

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

  return {
    ok: issues.every((entry) => entry.severity !== "error"),
    errors: issues,
    warnings: issues
      .filter((entry) => entry.severity === "warning")
      .map(({ code, message, path }) => ({ code, message, path })),
  };
}
