/**
 * document-context.ts — İstemciden gelen yapılandırılmış ek dosya verilerini
 * AI prompt context bloğuna dönüştürür.
 *
 * - DocumentChunk[]  → sayfa metin bloğu, token bütçesi dahilinde seçim
 * - ImageAttachment  → thumbnail + OCR metin bloğu
 * - TableData        → markdown tablo + yapılandırılmış tablo bloğu
 */

import type { FastifyInstance } from "fastify";
import type {
  ClientAttachment,
  ClientDocumentChunk,
  ClientImageAttachment,
  ClientTableData,
} from "./document-types.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";

/* ── Sabitler ────────────────────────────────────────────────────────── */

const DEFAULT_CHAR_BUDGET = 20_000;
const MAX_IMAGES = 3;
const MAX_TABLES = 4;
const MAX_DOCUMENT_SOURCES = 6;

/* ── Chunk budget: token bütçesine göre hangi chunk'lar seçilir ──────── */

type ChunkWithMeta = ClientDocumentChunk & { budgetScore: number };

function scoreChunkForBudget(chunk: ClientDocumentChunk, totalPages: number): number {
  /* İlk ve son sayfalar + kısa chunk'lar daha önce alınır */
  const pos = chunk.position ?? (chunk.pageIndex != null && totalPages > 0 ? chunk.pageIndex / totalPages : 0.5);
  const isEdge = pos < 0.15 || pos > 0.85;
  return (isEdge ? 2.0 : 1.0) - pos * 0.1;
}

export async function selectChunksWithinBudget(
  chunks: ClientDocumentChunk[],
  charBudget = DEFAULT_CHAR_BUDGET,
): Promise<ClientDocumentChunk[]> {
  /* nlp-daemon chunk_budget varsa kullan, yoksa basit greedy */
  if (nlpDaemon.isAvailable()) {
    try {
      const result = await nlpDaemon.chunkBudget(
        chunks.map((c) => ({ id: c.chunkId, charCount: c.charCount })),
        charBudget,
      );
      if (result && result.length > 0) {
        const selectedSet = new Set(result);
        return chunks.filter((c) => selectedSet.has(c.chunkId));
      }
    } catch {
      /* fall through */
    }
  }

  /* Greedy fallback: skor sırası ile doldur */
  const totalPages = Math.max(...chunks.map((c) => c.totalPages ?? 0), 1);
  const scored: ChunkWithMeta[] = chunks.map((c) => ({
    ...c,
    budgetScore: scoreChunkForBudget(c, totalPages),
  }));
  scored.sort((a, b) => b.budgetScore - a.budgetScore);

  const selected: ClientDocumentChunk[] = [];
  let used = 0;
  for (const c of scored) {
    if (used + c.charCount > charBudget) continue;
    selected.push(c);
    used += c.charCount;
  }
  /* Sayfa sırasına geri döndür */
  selected.sort((a, b) => (a.pageIndex ?? 0) - (b.pageIndex ?? 0));
  return selected;
}

/* ── Tablo → markdown ────────────────────────────────────────────────── */

export function tableToMarkdown(table: ClientTableData, maxRows = 30): string {
  const headers = table.headers;
  const rows = table.rows.slice(0, maxRows);
  const sep = headers.map(() => "---").join(" | ");
  const lines = [
    headers.join(" | "),
    sep,
    ...rows.map((row) => row.join(" | ")),
  ];
  if (table.truncated || table.rows.length > maxRows) {
    lines.push(`_... ${table.totalRowCount} satırdan ${rows.length} tanesi gösteriliyor_`);
  }
  return lines.join("\n");
}

/* ── Belge chunk'ları → prompt bloğu ────────────────────────────────── */

function buildDocumentChunksBlock(chunks: ClientDocumentChunk[]): string {
  /* Belge başlıklarına göre grupla */
  const byDoc = new Map<string, ClientDocumentChunk[]>();
  for (const chunk of chunks) {
    const existing = byDoc.get(chunk.documentId) ?? [];
    existing.push(chunk);
    byDoc.set(chunk.documentId, existing);
  }

  const parts: string[] = ["ATTACHED DOCUMENT CONTENT"];
  parts.push("Extracted from client-side processing. No raw file was sent to the server.");

  let docIndex = 0;
  for (const [, docChunks] of byDoc) {
    if (docIndex >= MAX_DOCUMENT_SOURCES) break;
    const first = docChunks[0]!;
    parts.push(`\n## ${first.documentTitle} (${first.mimeType})`);
    if (first.totalPages) {
      const includedPages = docChunks
        .map((c) => c.pageIndex)
        .filter((p): p is number => p !== null)
        .map((p) => p + 1);
      parts.push(`Pages: ${first.totalPages} total, showing: ${includedPages.join(", ")}`);
    }
    for (const chunk of docChunks) {
      const pageLabel = chunk.pageIndex != null ? `[Page ${chunk.pageIndex + 1}]` : "";
      parts.push(`\n${pageLabel}\n${chunk.text}`);
    }
    docIndex++;
  }

  return parts.join("\n");
}

/* ── Görsel attachment → prompt bloğu ───────────────────────────────── */

function buildImageAttachmentsBlock(images: ClientImageAttachment[]): string {
  const parts: string[] = ["ATTACHED IMAGES"];
  parts.push("Thumbnails and OCR extracted client-side. Analyze based on this data.");

  for (const img of images.slice(0, MAX_IMAGES)) {
    parts.push(`\n### ${img.fileName} (${img.imageCategory ?? img.mimeType})`);
    if (img.ocrText) {
      parts.push(`Detected text (OCR):\n${img.ocrText}`);
    } else {
      parts.push("No text detected (OCR returned empty).");
    }
    if (img.thumbnailWidth && img.thumbnailHeight) {
      parts.push(`Thumbnail: ${img.thumbnailWidth}×${img.thumbnailHeight}px (thumbnail only, not full resolution)`);
    }
  }

  return parts.join("\n");
}

/* ── Tablo → prompt bloğu ────────────────────────────────────────────── */

function buildTableDataBlock(tables: ClientTableData[]): string {
  const parts: string[] = ["ATTACHED TABLES"];
  parts.push("Parsed client-side from source document.");

  for (const table of tables.slice(0, MAX_TABLES)) {
    if (table.caption) parts.push(`\n### ${table.caption}`);
    parts.push(tableToMarkdown(table));
  }

  return parts.join("\n");
}

/* ── Ana entry point ─────────────────────────────────────────────────── */

export type DocumentContextResult = {
  promptBlock: string | null;
  chunkCount: number;
  imageCount: number;
  tableCount: number;
  hasContent: boolean;
  visionImages: Array<{
    imageId: string;
    mimeType: string;
    base64: string;
    label: string;
    width: number;
    height: number;
    category?: ClientImageAttachment["imageCategory"];
    transport: "request_ephemeral";
  }>;
};

export async function buildDocumentContextBlock(
  _app: FastifyInstance,
  attachments: ClientAttachment[],
  options: { charBudget?: number } = {},
): Promise<DocumentContextResult> {
  const charBudget = options.charBudget ?? DEFAULT_CHAR_BUDGET;

  const docChunks: ClientDocumentChunk[] = [];
  const images: ClientImageAttachment[] = [];
  const tables: ClientTableData[] = [];

  for (const att of attachments) {
    if (att.attachmentType === "document_chunk") docChunks.push(att);
    else if (att.attachmentType === "image") images.push(att);
    else if (att.attachmentType === "table") tables.push(att);
  }

  /* Budget-aware chunk selection */
  const selectedChunks = docChunks.length > 0
    ? await selectChunksWithinBudget(docChunks, charBudget)
    : [];

  const parts: string[] = [];

  if (selectedChunks.length > 0) {
    parts.push(buildDocumentChunksBlock(selectedChunks));
  }
  if (tables.length > 0) {
    parts.push(buildTableDataBlock(tables));
  }
  if (images.length > 0) {
    parts.push(buildImageAttachmentsBlock(images));
  }

  const promptBlock = parts.length > 0 ? parts.join("\n\n---\n\n") : null;

  /* Vision images: thumbnail base64'leri vision modeline ilet */
  const visionImages = images.slice(0, 3).map((img) => ({
    imageId: img.imageId,
    mimeType: img.mimeType.startsWith("image/") ? img.mimeType : "image/jpeg",
    base64: img.base64Thumbnail,
    label: img.fileName,
    width: img.thumbnailWidth,
    height: img.thumbnailHeight,
    category: img.imageCategory,
    transport: "request_ephemeral" as const,
  }));

  return {
    promptBlock,
    chunkCount: selectedChunks.length,
    imageCount: images.length,
    tableCount: tables.length,
    hasContent: parts.length > 0,
    visionImages,
  };
}

/* ── Attachment ACK prompt (kullanıcıya gösterilecek) ─────────────────── */

export function buildAttachmentAckText(result: DocumentContextResult): string {
  const parts: string[] = [];
  if (result.chunkCount > 0) parts.push(`${result.chunkCount} metin bölümü`);
  if (result.tableCount > 0) parts.push(`${result.tableCount} tablo`);
  if (result.imageCount > 0) parts.push(`${result.imageCount} görsel`);
  if (parts.length === 0) return "Ek içerik alındı.";
  return `Alındı: ${parts.join(", ")}. İşleniyor...`;
}
