import type { RenderRecipeBlock } from "../../core/understanding/render-recipe.js";
import type { ArtifactSpec, PdfBlock } from "./types.js";
import { compactText, formatMoney } from "./utils.js";

function tableBlock(input: {
  title?: string;
  columns: Array<{ key: string; label: string }>;
  rows: Array<Record<string, unknown>>;
}): RenderRecipeBlock {
  return {
    type: "table",
    text: compactText(input.title),
    tableHeaders: input.columns.map((column) => column.label),
    tableRows: input.rows.map((row) =>
      input.columns.map((column) => String(row[column.key] ?? "")),
    ),
  };
}

function pdfText(block: PdfBlock): string {
  const text = compactText(block.text);
  if (text) return text;
  const label = compactText(block.label);
  if (typeof block.amount === "number") {
    return [
      label,
      compactText(block.rawAmount) ||
        formatMoney(block.amount, block.currency ?? "TRY"),
    ]
      .filter(Boolean)
      .join(": ");
  }
  return label;
}

/** Typed artifact -> mobile render-recipe boundary adapter. */
export function artifactSpecToRenderRecipeBlocks(
  spec: ArtifactSpec,
): RenderRecipeBlock[] {
  if (spec.type === "table") {
    return [tableBlock(spec)];
  }
  if (spec.type === "document") {
    const blocks: RenderRecipeBlock[] = [];
    if (spec.title) blocks.push({ type: "title", text: spec.title, level: 1 });
    for (const section of spec.sections) {
      if (section.heading) {
        blocks.push({
          type: "heading",
          text: section.heading,
          level: section.level ?? 1,
        });
      }
      blocks.push({ type: "paragraph", text: section.content });
    }
    return blocks;
  }
  if (spec.type === "pdf") {
    const blocks: RenderRecipeBlock[] = [];
    if (spec.title) blocks.push({ type: "title", text: spec.title, level: 1 });
    for (const block of spec.blocks) {
      if (
        block.type === "table" &&
        Array.isArray(block.columns) &&
        Array.isArray(block.rows)
      ) {
        blocks.push(tableBlock({ columns: block.columns, rows: block.rows }));
        continue;
      }
      const text = pdfText(block);
      if (!text) continue;
      blocks.push({
        type:
          block.type === "title"
            ? "title"
            : block.type === "subtitle"
              ? "heading"
              : "paragraph",
        text,
        ...(block.type === "subtitle" ? { level: 2 } : {}),
      });
    }
    return blocks;
  }
  return [];
}
