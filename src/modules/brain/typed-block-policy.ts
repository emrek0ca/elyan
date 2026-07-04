import {
  isExplicitChartRequest,
  isExplicitMathOrLatexRequest,
  isExplicitMathSurface3DRequest,
  isExplicitSvgRequest,
  isExplicitTableRequest,
} from "../../core/understanding/structured-output-policy.js";
import type { SharedBrainWorkload } from "./workloads.js";

export function compactInlineText(value: unknown, maxLength = 160): string {
  return String(value ?? "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, maxLength);
}

export function tableBlockToPlainFallback(block: Record<string, unknown>): string {
  const columns = Array.isArray(block.columns)
    ? block.columns.map((column) => compactInlineText(column, 80)).filter(Boolean)
    : [];
  const rows = Array.isArray(block.rows) ? block.rows.slice(0, 12) : [];
  if (columns.length === 0 || rows.length === 0) {
    return "";
  }
  const title = compactInlineText(block.title, 120);
  const lines = title ? [`${title}:`] : [];
  for (const rawRow of rows) {
    const row = Array.isArray(rawRow)
      ? rawRow
      : rawRow && typeof rawRow === "object" && !Array.isArray(rawRow)
        ? Object.values(rawRow as Record<string, unknown>)
        : [];
    const cells = row.map((cell) => compactInlineText(cell, 140));
    const head = cells[0];
    if (!head) continue;
    const details = cells
      .slice(1, columns.length)
      .map((cell, index) => {
        const label = columns[index + 1] ?? "";
        return cell ? `${label ? `${label}: ` : ""}${cell}` : "";
      })
      .filter(Boolean)
      .join("; ");
    lines.push(`- ${head}${details ? `: ${details}` : ""}`);
  }
  return lines.join("\n");
}

export function shouldAcceptExtractedTypedBlock(input: {
  block: unknown;
  prompt: string;
  selectedWorkload: SharedBrainWorkload;
}): boolean {
  if (!input.block || typeof input.block !== "object" || Array.isArray(input.block)) {
    return true;
  }
  const type = String((input.block as Record<string, unknown>).type ?? "")
    .trim()
    .toLowerCase();
  if (type === "table") {
    return input.selectedWorkload === "table_generate" || isExplicitTableRequest(input.prompt);
  }
  if (type === "chart") {
    return isExplicitChartRequest(input.prompt);
  }
  if (type === "svg") {
    return isExplicitSvgRequest(input.prompt);
  }
  if (type === "math" || type === "math_surface_3d") {
    return isExplicitMathOrLatexRequest(input.prompt) || isExplicitMathSurface3DRequest(input.prompt);
  }
  if (type === "document_block") {
    return input.selectedWorkload === "document_generate";
  }
  return true;
}
