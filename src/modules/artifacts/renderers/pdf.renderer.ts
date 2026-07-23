import type { ArtifactOutput, ArtifactRenderer, PdfSpec, ValidationResult } from "../types.js";
import {
  escapeMarkdownTableCell,
  formatMoney,
  safeFileSlug,
} from "../utils.js";
import { validatePdfSpec } from "../validators/pdf.validator.js";

function linesForPdf(spec: PdfSpec): string[] {
  const lines: string[] = [];
  const title = spec.title ?? (
    spec.documentType === "receipt"
      ? "Makbuz"
      : spec.documentType === "invoice"
        ? "Fatura"
        : spec.documentType === "quote"
          ? "Teklif"
          : "Belge"
  );
  lines.push(`# ${title}`);
  for (const block of spec.blocks) {
    if (block.type === "line_item") {
      lines.push(`- ${block.label ?? "Kalem"}: ${formatMoney(block.amount ?? 0, block.currency ?? "TRY")}`);
    } else if (block.type === "total") {
      lines.push(`**${block.label ?? "Genel toplam"}: ${formatMoney(block.amount ?? 0, block.currency ?? "TRY")}**`);
    } else if (block.type === "paragraph" && block.text) {
      lines.push(block.text);
    } else if (block.type === "table") {
      const columns = block.columns ?? [];
      const rows = block.rows ?? [];
      if (columns.length > 0 && rows.length > 0) {
        lines.push(
          `| ${columns.map((column) => escapeMarkdownTableCell(column.label)).join(" | ")} |`,
        );
        lines.push(`| ${columns.map(() => "---").join(" | ")} |`);
        for (const row of rows) {
          lines.push(
            `| ${columns.map((column) => escapeMarkdownTableCell(row[column.key])).join(" | ")} |`,
          );
        }
      }
    }
  }
  if (spec.footer?.text) {
    lines.push("---");
    lines.push(spec.footer.text);
  }
  return lines;
}

export class PdfRenderer implements ArtifactRenderer<PdfSpec> {
  supports(type: string): boolean {
    return type === "pdf";
  }

  async validate(spec: PdfSpec): Promise<ValidationResult> {
    return validatePdfSpec(spec);
  }

  async render(spec: PdfSpec): Promise<ArtifactOutput> {
    const validation = await this.validate(spec);
    return {
      artifactId: spec.id,
      type: "pdf",
      spec,
      output: {
        kind: "json",
        content: {
          renderer: "mobile_local_pdf_recipe",
          fileName: `${safeFileSlug(spec.title ?? spec.documentType)}.pdf`,
          mimeType: "application/pdf",
          markdown: linesForPdf(spec).join("\n\n"),
          page: spec.page,
          footer: spec.footer ?? null,
        },
      },
      validation,
    };
  }
}
