import type { ResolvedAttachmentContext, ResolvedAttachmentContextChunk } from "./attachment-context.js";
import {
  buildAssistantFileBlock,
  buildAssistantInfoCardBlock,
  buildAssistantTableBlock,
  type AssistantMessageBlock,
} from "../chat/message-blocks.js";

const MAX_TABLES = 2;
const MAX_TABLE_ROWS = 12;
const MAX_TABLE_COLUMNS = 8;
const MAX_CELL_CHARS = 120;
const MAX_VISUAL_NOTES = 4;
const MAX_DOCS = 3;

export type AttachmentTableInsight = {
  documentId: string;
  documentTitle: string;
  pageNumber: number | null;
  chunkHash: string;
  title: string;
  columns: string[];
  rows: string[][];
  confidence: number;
};

export type AttachmentVisualInsight = {
  documentId: string;
  documentTitle: string;
  mimeType: string | null;
  pageNumber: number | null;
  summary: string;
};

export type AttachmentInsightResult = {
  used: boolean;
  documentCount: number;
  chunkCount: number;
  tableCount: number;
  visualCount: number;
  tables: AttachmentTableInsight[];
  visuals: AttachmentVisualInsight[];
  promptBlock: string | null;
  renderBlocks: AssistantMessageBlock[];
  warnings: string[];
};

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(record: Record<string, unknown> | null, keys: string[]): string | null {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function scrubLabel(value: string, maxChars = 180): string {
  const withoutPath = value.replace(/^.*[\\/]/, "");
  const compact = withoutPath
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return compact.length <= maxChars ? compact : `${compact.slice(0, maxChars - 1).trimEnd()}…`;
}

function normalizeRichText(value: string): string {
  return value
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\r\n?/g, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>\s*<p>/gi, "\n")
    .replace(/<[^>]{1,40}>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function normalizeTableSourceText(value: string): string {
  return value
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\r\n?/g, "\n")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<\/p>\s*<p>/gi, "\n")
    .replace(/<[^>]{1,40}>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function normalizeCell(value: unknown): string {
  const normalized = normalizeRichText(String(value ?? ""))
    .replace(/\n+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return normalized.length <= MAX_CELL_CHARS
    ? normalized
    : `${normalized.slice(0, MAX_CELL_CHARS - 1).trimEnd()}…`;
}

function splitPipeRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((cell) => normalizeCell(cell))
    .filter((cell) => cell.length > 0);
}

function isMarkdownTableSeparator(line: string): boolean {
  return splitPipeRow(line).every((cell) => /^:?-{3,}:?$/.test(cell));
}

function normalizeRowsToColumnCount(rows: string[][], columnCount: number): string[][] {
  return rows
    .map((row) => {
      const bounded = row.slice(0, columnCount);
      while (bounded.length < columnCount) {
        bounded.push("");
      }
      return bounded;
    })
    .filter((row) => row.some((cell) => cell.trim()))
    .slice(0, MAX_TABLE_ROWS);
}

function parsePipeTable(lines: string[]): { columns: string[]; rows: string[][] } | null {
  const pipeLines = lines.filter((line) => line.includes("|"));
  if (pipeLines.length < 2) {
    return null;
  }

  const separatorIndex = pipeLines.findIndex(isMarkdownTableSeparator);
  const headerLine =
    separatorIndex > 0 ? pipeLines[separatorIndex - 1] : pipeLines[0];
  const rowLines =
    separatorIndex >= 0 ? pipeLines.slice(separatorIndex + 1) : pipeLines.slice(1);
  const columns = splitPipeRow(headerLine).slice(0, MAX_TABLE_COLUMNS);
  if (columns.length < 2) {
    return null;
  }

  const rows = normalizeRowsToColumnCount(
    rowLines.map(splitPipeRow).filter((row) => row.length >= 2),
    columns.length,
  );
  return rows.length > 0 ? { columns, rows } : null;
}

function parseDelimitedTable(lines: string[]): { columns: string[]; rows: string[][] } | null {
  if (lines.length < 2) {
    return null;
  }

  const delimiter = ["\t", ";", ","].find((candidate) => {
    const counts = lines.slice(0, 5).map((line) => line.split(candidate).length);
    return counts.filter((count) => count >= 2).length >= 2;
  });
  if (!delimiter) {
    return null;
  }

  const parsed = lines
    .map((line) => line.split(delimiter).map(normalizeCell))
    .filter((row) => row.length >= 2);
  const columns = (parsed[0] ?? []).slice(0, MAX_TABLE_COLUMNS);
  if (columns.length < 2) {
    return null;
  }
  const rows = normalizeRowsToColumnCount(parsed.slice(1), columns.length);
  return rows.length > 0 ? { columns, rows } : null;
}

function parseTableFromChunk(chunk: ResolvedAttachmentContextChunk): {
  columns: string[];
  rows: string[][];
} | null {
  const normalized = normalizeTableSourceText(chunk.content);
  const lines = normalized
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 80);

  return parsePipeTable(lines) ?? parseDelimitedTable(lines);
}

function metadataKind(chunk: ResolvedAttachmentContextChunk): string {
  const metadata = readRecord(chunk.metadata);
  const chunkMetadata = readRecord(metadata?.chunkMetadata);
  return (
    readString(metadata, ["chunkKind", "blockType", "type", "kind"]) ??
    readString(chunkMetadata, ["chunkKind", "blockType", "type", "kind"]) ??
    ""
  ).toLowerCase();
}

function isTableCandidate(chunk: ResolvedAttachmentContextChunk): boolean {
  const kind = metadataKind(chunk);
  if (/\b(table|table_data|csv|spreadsheet|sheet)\b/i.test(kind)) {
    return true;
  }
  const normalized = normalizeRichText(chunk.content);
  const pipeLineCount = normalized.split(/\n+/).filter((line) => line.includes("|")).length;
  return pipeLineCount >= 2 || /\b(csv|tablo|sütun|column|row)\b/i.test(normalized);
}

function isVisualCandidate(chunk: ResolvedAttachmentContextChunk): boolean {
  const kind = metadataKind(chunk);
  return (
    String(chunk.mimeType ?? "").toLowerCase().startsWith("image/") ||
    /\b(image|ocr|vision|visual|caption|screenshot|görsel|resim)\b/i.test(kind)
  );
}

function buildTables(context: ResolvedAttachmentContext): AttachmentTableInsight[] {
  const tables: AttachmentTableInsight[] = [];
  const seen = new Set<string>();

  for (const chunk of context.chunks) {
    if (tables.length >= MAX_TABLES || !isTableCandidate(chunk)) {
      continue;
    }

    const parsed = parseTableFromChunk(chunk);
    if (!parsed) {
      continue;
    }

    const key = JSON.stringify({
      documentId: chunk.documentId,
      columns: parsed.columns,
      rows: parsed.rows.slice(0, 3),
    }).toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    tables.push({
      documentId: chunk.documentId,
      documentTitle: scrubLabel(chunk.documentTitle),
      pageNumber: chunk.pageNumber,
      chunkHash: chunk.chunkHash,
      title: chunk.pageNumber
        ? `${scrubLabel(chunk.documentTitle, 96)} · Sayfa ${chunk.pageNumber}`
        : scrubLabel(chunk.documentTitle, 120),
      columns: parsed.columns,
      rows: parsed.rows,
      confidence: metadataKind(chunk).includes("table") ? 0.92 : 0.72,
    });
  }

  return tables;
}

function buildVisuals(context: ResolvedAttachmentContext): AttachmentVisualInsight[] {
  const visuals: AttachmentVisualInsight[] = [];
  const seen = new Set<string>();

  for (const chunk of context.chunks) {
    if (visuals.length >= MAX_VISUAL_NOTES || !isVisualCandidate(chunk)) {
      continue;
    }

    const summary = scrubLabel(chunk.content, 260);
    if (!summary) {
      continue;
    }
    const key = `${chunk.documentId}:${summary.toLowerCase()}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    visuals.push({
      documentId: chunk.documentId,
      documentTitle: scrubLabel(chunk.documentTitle),
      mimeType: chunk.mimeType,
      pageNumber: chunk.pageNumber,
      summary,
    });
  }

  return visuals;
}

function buildPromptBlock(input: {
  context: ResolvedAttachmentContext;
  tables: AttachmentTableInsight[];
  visuals: AttachmentVisualInsight[];
  warnings: string[];
}): string | null {
  if (!input.context.used) {
    return null;
  }

  const payload = {
    mode: "bounded_derived_attachment_insights",
    rawBinaryStored: false,
    documentCount: input.context.documents.length,
    chunkCount: input.context.chunks.length,
    tables: input.tables.map((table) => ({
      documentTitle: table.documentTitle,
      pageNumber: table.pageNumber,
      columns: table.columns,
      rows: table.rows,
      confidence: table.confidence,
    })),
    visuals: input.visuals.map((visual) => ({
      documentTitle: visual.documentTitle,
      mimeType: visual.mimeType,
      pageNumber: visual.pageNumber,
      summary: visual.summary,
    })),
    warnings: input.warnings,
  };

  return [
    "Attachment intelligence packet (bounded, derived, render-aware):",
    "Use this packet to preserve table rows, document evidence, and image/OCR details without requesting raw files.",
    "When presenting tables, use complete rows and cells. Do not emit HTML tags such as <br>; use plain text or Markdown line breaks.",
    "```json",
    JSON.stringify(payload, null, 2),
    "```",
  ].join("\n");
}

function buildRenderBlocks(input: {
  context: ResolvedAttachmentContext;
  tables: AttachmentTableInsight[];
  visuals: AttachmentVisualInsight[];
}): AssistantMessageBlock[] {
  const blocks: AssistantMessageBlock[] = [];
  const fileBlocks = input.context.documents
    .slice(0, MAX_DOCS)
    .map((document) =>
      buildAssistantFileBlock(
        {
          fileName: scrubLabel(document.title),
          mimeType: document.mimeType,
          documentId: document.documentId,
          preview: document.summary,
        },
        {
          priority: 2,
          renderHints: {
            source: "attachment_insights",
            derived: true,
          },
        },
      ),
    )
    .filter((block): block is AssistantMessageBlock => block != null);
  blocks.push(...fileBlocks);

  for (const table of input.tables) {
    const block = buildAssistantTableBlock(
      {
        title: table.title,
        columns: table.columns,
        rows: table.rows,
        caption: table.pageNumber ? `Kaynak: ${table.documentTitle}, sayfa ${table.pageNumber}` : `Kaynak: ${table.documentTitle}`,
      },
      {
        confidence: table.confidence,
        priority: 1,
        renderHints: {
          source: "attachment_insights",
          derived: true,
          sourceChunkHash: table.chunkHash,
        },
      },
    );
    if (block) {
      blocks.push(block);
    }
  }

  const infoItems = [
    { label: "Belge", value: `${input.context.documents.length}` },
    { label: "Parça", value: `${input.context.chunks.length}` },
    ...(input.tables.length > 0 ? [{ label: "Tablo", value: `${input.tables.length}` }] : []),
    ...(input.visuals.length > 0 ? [{ label: "Görsel/OCR", value: `${input.visuals.length}` }] : []),
  ];
  const infoBlock = buildAssistantInfoCardBlock(
    {
      type: "attachment_context",
      title: "Ek bağlamı",
      items: infoItems,
    },
    {
      priority: 3,
      renderHints: {
        source: "attachment_insights",
        derived: true,
      },
    },
  );
  if (infoBlock) {
    blocks.push(infoBlock);
  }

  return blocks.slice(0, 6);
}

export function buildAttachmentInsights(
  context: ResolvedAttachmentContext | null | undefined,
): AttachmentInsightResult {
  if (!context?.used) {
    return {
      used: false,
      documentCount: 0,
      chunkCount: 0,
      tableCount: 0,
      visualCount: 0,
      tables: [],
      visuals: [],
      promptBlock: null,
      renderBlocks: [],
      warnings: [],
    };
  }

  const tables = buildTables(context);
  const visuals = buildVisuals(context);
  const warnings = [
    ...(context.chunkCount > context.chunks.length
      ? ["attachment_context_was_budget_limited"]
      : []),
    ...(tables.length >= MAX_TABLES ? ["table_preview_limited"] : []),
  ];

  return {
    used: true,
    documentCount: context.documents.length,
    chunkCount: context.chunks.length,
    tableCount: tables.length,
    visualCount: visuals.length,
    tables,
    visuals,
    promptBlock: buildPromptBlock({ context, tables, visuals, warnings }),
    renderBlocks: buildRenderBlocks({ context, tables, visuals }),
    warnings,
  };
}

export function buildAttachmentInsightPromptBlock(
  context: ResolvedAttachmentContext | null | undefined,
): string | null {
  return buildAttachmentInsights(context).promptBlock;
}

export function buildAttachmentInsightBlocks(
  context: ResolvedAttachmentContext | null | undefined,
): AssistantMessageBlock[] {
  return buildAttachmentInsights(context).renderBlocks;
}

export function buildAttachmentInsightMetadata(
  context: ResolvedAttachmentContext | null | undefined,
) {
  const insights = buildAttachmentInsights(context);
  return {
    attachmentInsightUsed: insights.used,
    attachmentInsightDocumentCount: insights.documentCount,
    attachmentInsightChunkCount: insights.chunkCount,
    attachmentInsightTableCount: insights.tableCount,
    attachmentInsightVisualCount: insights.visualCount,
    attachmentInsightWarnings: insights.warnings,
  };
}
