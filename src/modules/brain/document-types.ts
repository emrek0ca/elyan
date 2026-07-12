/**
 * document-types.ts — İstemcinin (mobil/desktop) sunucuya gönderdiği
 * yapılandırılmış belge/görsel/tablo verileri.
 *
 * KURAL: Sunucuya asla ham dosya gitmez.
 * - PDF/DOCX → istemci sayfaları metin chunk'larına çevirir → ClientDocumentChunk[]
 * - Görsel   → istemci ≤512px thumbnail + OCR metin üretir → ClientImageAttachment
 * - Tablo    → istemci satır/sütun JSON'u çıkarır → ClientTableData
 *
 * Tüm alanlar JSON-serializable, binary yok.
 */

/* ── Document chunk ──────────────────────────────────────────────────── */

export type ClientDocumentChunk = {
  /** İstemcinin ürettiği kararlı ID (sha256 veya uuid) */
  chunkId: string;
  /** Kaynak belge kimliği */
  documentId: string;
  /** Belge başlığı / dosya adı */
  documentTitle: string;
  /** MIME tipi: application/pdf, application/vnd.openxmlformats-officedocument… */
  mimeType: string;
  /** İstemcide çıkarılan metin içeriği */
  text: string;
  /** Karakter sayısı (metin uzunluğu) */
  charCount: number;
  /** Sayfa numarası (0-indexed, null → bilinmiyor) */
  pageIndex: number | null;
  /** Toplam sayfa sayısı */
  totalPages: number | null;
  /** chunk'ın belgedeki yüzde konumu (0–1) */
  position: number | null;
  /** İstemci tarafı meta veri (extraction_method, confidence vs.) */
  metadata?: Record<string, unknown>;
};

/* ── Image attachment ────────────────────────────────────────────────── */

export type ClientImageAttachment = {
  /** İstemcinin ürettiği kararlı ID */
  imageId: string;
  /** MIME tipi: image/jpeg, image/png, image/heic */
  mimeType: string;
  /** Orijinal dosya adı */
  fileName: string;
  /** ≤512px, JPEG/PNG base64 thumbnail (ham görsel değil küçük temsil) */
  base64Thumbnail: string;
  /** Thumbnail genişliği (px) */
  thumbnailWidth: number;
  /** Thumbnail yüksekliği (px) */
  thumbnailHeight: number;
  /** İstemcide OCR ile çıkarılan metin (boş string → OCR yok) */
  ocrText: string;
  /** Orijinal görsel boyutu (byte) */
  originalSizeBytes: number | null;
  /** Görsel kategorisi: photo, screenshot, document, diagram */
  imageCategory?: "photo" | "screenshot" | "document" | "diagram";
};

/* ── Table data ──────────────────────────────────────────────────────── */

export type ClientTableData = {
  /** İstemcinin ürettiği kararlı ID */
  tableId: string;
  /** Kaynak belge (spreadsheet, PDF tablo vs.) */
  sourceDocumentId?: string;
  /** Tablo başlığı */
  caption?: string;
  /** Sütun başlıkları */
  headers: string[];
  /** Satırlar — her satır header listesiyle aynı uzunlukta */
  rows: string[][];
  /** Toplam satır sayısı (rows kırpılmış olabilir) */
  totalRowCount: number;
  /** Kırpma varsa true */
  truncated: boolean;
};

/* ── Union: tek attachment kaydı ─────────────────────────────────────── */

export type ClientAttachment =
  | ({ attachmentType: "document_chunk" } & ClientDocumentChunk)
  | ({ attachmentType: "image" } & ClientImageAttachment)
  | ({ attachmentType: "table" } & ClientTableData);

/* ── Validation helpers ──────────────────────────────────────────────── */

const MAX_CHUNK_CHARS = 12_000;
const MAX_THUMBNAIL_BASE64 = 180_000; /* ~135 KB decoded */
const MAX_THUMBNAIL_EDGE = 1024;
const ALLOWED_IMAGE_MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_TABLE_CELLS = 8 * 80; /* 8 sütun × 80 satır */

export function validateClientAttachment(value: unknown): ClientAttachment | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const r = value as Record<string, unknown>;
  const t = r.attachmentType;

  if (t === "document_chunk") {
    if (typeof r.chunkId !== "string" || !r.chunkId) return null;
    if (typeof r.text !== "string") return null;
    const text = r.text.slice(0, MAX_CHUNK_CHARS);
    return {
      attachmentType: "document_chunk",
      chunkId: r.chunkId,
      documentId: typeof r.documentId === "string" ? r.documentId : r.chunkId,
      documentTitle: typeof r.documentTitle === "string" ? r.documentTitle.slice(0, 200) : "Belge",
      mimeType: typeof r.mimeType === "string" ? r.mimeType : "application/octet-stream",
      text,
      charCount: text.length,
      pageIndex: typeof r.pageIndex === "number" ? r.pageIndex : null,
      totalPages: typeof r.totalPages === "number" ? r.totalPages : null,
      position: typeof r.position === "number" ? Math.max(0, Math.min(1, r.position)) : null,
      metadata: r.metadata && typeof r.metadata === "object" ? r.metadata as Record<string, unknown> : undefined,
    };
  }

  if (t === "image") {
    if (typeof r.imageId !== "string" || !r.imageId) return null;
    // Accept both new `base64Thumbnail` and legacy `visionImageJpeg` key
    const thumbnailData =
      typeof r.base64Thumbnail === "string"
        ? r.base64Thumbnail
        : typeof r.visionImageJpeg === "string"
          ? r.visionImageJpeg
          : null;
    if (!thumbnailData || thumbnailData.length > MAX_THUMBNAIL_BASE64) return null;
    if (!/^[A-Za-z0-9+/]*={0,2}$/.test(thumbnailData) || thumbnailData.length % 4 !== 0) return null;
    const rawMimeType = typeof r.mimeType === "string" ? r.mimeType.toLowerCase() : "image/jpeg";
    // HEIC/HEIF originals are represented by a client-generated JPEG thumbnail.
    const mimeType = rawMimeType === "image/heic" || rawMimeType === "image/heif"
      ? "image/jpeg"
      : rawMimeType;
    if (!ALLOWED_IMAGE_MIME_TYPES.has(mimeType)) return null;
    const width = typeof r.thumbnailWidth === "number" && Number.isFinite(r.thumbnailWidth)
      ? Math.max(0, Math.floor(r.thumbnailWidth))
      : 0;
    const height = typeof r.thumbnailHeight === "number" && Number.isFinite(r.thumbnailHeight)
      ? Math.max(0, Math.floor(r.thumbnailHeight))
      : 0;
    if (width > MAX_THUMBNAIL_EDGE || height > MAX_THUMBNAIL_EDGE) return null;
    return {
      attachmentType: "image",
      imageId: r.imageId,
      mimeType,
      fileName: typeof r.fileName === "string" ? r.fileName.slice(0, 200) : "image",
      base64Thumbnail: thumbnailData,
      thumbnailWidth: width,
      thumbnailHeight: height,
      ocrText: typeof r.ocrText === "string" ? r.ocrText.slice(0, 4_000) : "",
      originalSizeBytes: typeof r.originalSizeBytes === "number" ? r.originalSizeBytes : null,
      imageCategory: ["photo", "screenshot", "document", "diagram"].includes(r.imageCategory as string)
        ? (r.imageCategory as ClientImageAttachment["imageCategory"])
        : undefined,
    };
  }

  if (t === "table") {
    if (typeof r.tableId !== "string" || !r.tableId) return null;
    if (!Array.isArray(r.headers) || r.headers.length === 0) return null;
    if (!Array.isArray(r.rows)) return null;
    const headers = (r.headers as unknown[])
      .slice(0, 12)
      .map((h) => String(h ?? "").slice(0, 120));
    const rows = (r.rows as unknown[])
      .slice(0, MAX_TABLE_CELLS / headers.length)
      .map((row) =>
        Array.isArray(row)
          ? (row as unknown[]).slice(0, headers.length).map((c) => String(c ?? "").slice(0, 240))
          : [],
      )
      .filter((row) => row.length > 0);
    return {
      attachmentType: "table",
      tableId: r.tableId,
      sourceDocumentId: typeof r.sourceDocumentId === "string" ? r.sourceDocumentId : undefined,
      caption: typeof r.caption === "string" ? r.caption.slice(0, 240) : undefined,
      headers,
      rows,
      totalRowCount: typeof r.totalRowCount === "number" ? r.totalRowCount : rows.length,
      truncated: typeof r.truncated === "boolean" ? r.truncated : false,
    };
  }

  return null;
}

export function extractClientAttachments(metadata: Record<string, unknown>): ClientAttachment[] {
  // New format: clientAttachments[] with attachmentType discriminator
  const raw = metadata.clientAttachments ?? metadata.client_attachments;
  if (Array.isArray(raw) && raw.length > 0) {
    return raw
      .map(validateClientAttachment)
      .filter((a): a is ClientAttachment => a !== null)
      .slice(0, 10);
  }

  // Legacy fallback: convert old buildCompactTaskChatAttachmentPayload format
  const legacyAttachments = metadata.attachments;
  if (!Array.isArray(legacyAttachments) || legacyAttachments.length === 0) return [];

  const converted: ClientAttachment[] = [];
  for (const att of legacyAttachments.slice(0, 10)) {
    if (!att || typeof att !== "object") continue;
    const a = att as Record<string, unknown>;
    const docId = (a.documentId ?? a.fileName ?? "doc") as string;
    const fileName = (a.fileName ?? a.name ?? "Belge") as string;

    // Extract text chunks from fastPreview / deepContext
    const deep = a.deepContext as Record<string, unknown> | undefined;
    const fast = a.fastPreview as Record<string, unknown> | undefined;
    const chunks: unknown[] =
      (deep?.chunks as unknown[]) ??
      (fast?.chunks as unknown[]) ??
      [];

    if (chunks.length > 0) {
      for (let i = 0; i < Math.min(chunks.length, 20); i++) {
        const ch = chunks[i] as Record<string, unknown>;
        const text = (ch.text ?? ch.content ?? "") as string;
        if (!text) continue;
        converted.push({
          attachmentType: "document_chunk",
          chunkId: `${docId}-chunk-${i}`,
          documentId: docId,
          documentTitle: fileName,
          mimeType: (a.mimeType as string) ?? "application/octet-stream",
          text: text.slice(0, MAX_CHUNK_CHARS),
          charCount: Math.min(text.length, MAX_CHUNK_CHARS),
          pageIndex: typeof ch.pageNumber === "number" ? ch.pageNumber : i,
          totalPages: typeof a.pageCount === "number" ? a.pageCount : null,
          position: chunks.length > 1 ? i / (chunks.length - 1) : 0,
        });
      }
    } else {
      // Use textPreview / contentPreview as single chunk
      const text = ((a.textPreview ?? a.contentPreview ?? deep?.extractedText ?? fast?.textPreview) as string | undefined) ?? "";
      if (text.trim()) {
        converted.push({
          attachmentType: "document_chunk",
          chunkId: `${docId}-chunk-0`,
          documentId: docId,
          documentTitle: fileName,
          mimeType: (a.mimeType as string) ?? "application/octet-stream",
          text: text.slice(0, MAX_CHUNK_CHARS),
          charCount: Math.min(text.length, MAX_CHUNK_CHARS),
          pageIndex: 0,
          totalPages: null,
          position: 0,
        });
      }
    }

    // Legacy vision image: visionImageJpeg at top level of attachment
    const visionJpeg = a.visionImageJpeg as string | undefined;
    if (typeof visionJpeg === "string" && visionJpeg.length > 0 && visionJpeg.length <= MAX_THUMBNAIL_BASE64) {
      converted.push({
        attachmentType: "image",
        imageId: `${docId}-vision`,
        mimeType: "image/jpeg",
        fileName,
        base64Thumbnail: visionJpeg,
        thumbnailWidth: 512,
        thumbnailHeight: 512,
        ocrText: "",
        originalSizeBytes: null,
        imageCategory: "document",
      });
    }
  }

  return converted.slice(0, 10);
}
