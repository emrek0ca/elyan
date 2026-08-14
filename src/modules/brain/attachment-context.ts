import { createHash } from "node:crypto";
import type { KnowledgeSourceType } from "../../contracts/domain.js";
import { normalizeLocalDerivedMetadata } from "../../lib/derived-data.js";
import type { ReliabilityStore } from "../../lib/reliability/redis.js";
import { prepareKnowledgeDocument } from "./service.js";
import {
  embedQueryForStorage,
  embedTextsForStorage,
  isStorageEmbedderDisabled,
} from "./semantic-embedder.js";
import {
  buildAssistantFileBlock,
  buildAssistantInfoCardBlock,
  buildAssistantTableBlock,
  type AssistantMessageBlock,
} from "../chat/message-blocks.js";
import {
  formatVisionEvidenceV3Prompt,
  normalizeVisionEvidence,
  parseVisionEvidence,
  type VisionEvidence,
  type VisionEvidenceV3,
} from "./vision-evidence-v3.js";
import { buildVisionTaskPromptBlock, classifyVisionTask } from "./vision-task-policy.js";
import { assessVisionEvidence, buildVisionEvidenceGatePrompt } from "./vision-evidence-gate.js";
import { extractClientAttachments } from "./document-types.js";
import { isSessionVisionMemoryFresh } from "./vision-memory-policy.js";

const DEFAULT_MAX_ATTACHMENTS = 3;
const DEFAULT_MAX_CHUNKS = 20;
const DEFAULT_MAX_CHARS = 24_000;
const MAX_EXCERPT_CHARS = 1_200;
const PREPARED_ATTACHMENT_CACHE_TTL_MS = 3_600_000;

export type AttachmentContextCandidate = {
  messageId?: string;
  createdAt?: string;
  prompt?: string;
  metadata: Record<string, unknown>;
};

export type AttachmentContextSource = "request_attachments" | "session_recovery";

export type ResolvedAttachmentContextDocument = {
  documentId: string;
  title: string;
  mimeType: string | null;
  summary: string;
  source: "request" | "session";
  chunkCount: number;
  includedChunkCount: number;
};

export type ResolvedAttachmentContextChunk = {
  documentId: string;
  documentTitle: string;
  mimeType: string | null;
  chunkId: string;
  chunkHash: string;
  content: string;
  pageNumber: number | null;
  metadata: Record<string, unknown>;
};

export type ResolvedAttachmentContextVisionImage = {
  documentId: string;
  mimeType: string;
  base64: string;
  label: string;
  width?: number;
  height?: number;
  category?: "photo" | "screenshot" | "document" | "diagram";
  transport?: "request_ephemeral";
  detail?: "low" | "high" | "auto";
};

export type ResolvedAttachmentContext = {
  used: boolean;
  source: AttachmentContextSource;
  promptBlock: string;
  documentIds: string[];
  documents: ResolvedAttachmentContextDocument[];
  chunks: ResolvedAttachmentContextChunk[];
  totalChars: number;
  chunkCount: number;
  needsClarification: boolean;
  clarificationMessage?: string;
  cacheHit?: boolean;
  visionImages?: ResolvedAttachmentContextVisionImage[];
  visionBlocks?: VisionEvidence[];
};

type CachedPreparedAttachmentCandidate = {
  documentId: string;
  title: string;
  mimeType: string | null;
  summary: string;
  documentMetadata: Record<string, unknown>;
  prepared: ReturnType<typeof prepareKnowledgeDocument>;
};

type CachedPreparedAttachmentRecord = {
  prepared: ReturnType<typeof prepareKnowledgeDocument>;
};

type PreparedAttachmentCandidate = CachedPreparedAttachmentCandidate & {
  key: string;
  source: "request" | "session";
  cacheHit: boolean;
};

type AttachmentContextStore = Pick<ReliabilityStore, "get" | "set">;

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readArray(record: Record<string, unknown> | null, key: string): unknown[] {
  const value = record?.[key];
  return Array.isArray(value) ? value : [];
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readNumber(record: Record<string, unknown> | null, key: string): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function compactText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function normalizeToken(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function boundedText(value: string, maxChars = MAX_EXCERPT_CHARS): string {
  const compact = compactText(value);
  if (compact.length <= maxChars) {
    return compact;
  }
  return `${compact.slice(0, maxChars - 1).trimEnd()}…`;
}

function normalizeExcerptText(value: unknown): string {
  return String(value ?? "")
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\r\n?/g, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function boundedExcerptText(value: string, maxChars = MAX_EXCERPT_CHARS): string {
  const normalized = normalizeExcerptText(value);
  if (!normalized) {
    return "";
  }
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, maxChars - 1).trimEnd()}…`;
}

function stableChunkHash(input: {
  documentId: string;
  chunkId: string;
  content: string;
  pageNumber: number | null;
}): string {
  return createHash("sha256")
    .update(
      JSON.stringify({
        documentId: input.documentId,
        chunkId: input.chunkId,
        pageNumber: input.pageNumber,
        content: input.content,
      }),
    )
    .digest("hex")
    .slice(0, 24);
}

function isAllowedKnowledgeSourceType(value: string | null): value is KnowledgeSourceType {
  return (
    value === "manual" ||
    value === "task_artifact" ||
    value === "external_url" ||
    value === "dataset" ||
    value === "feedback"
  );
}

function normalizeSourceType(value: string | null): KnowledgeSourceType {
  return isAllowedKnowledgeSourceType(value) ? value : "manual";
}

function hasAttachmentShape(record: Record<string, unknown> | null): boolean {
  if (!record) {
    return false;
  }

  return (
    Array.isArray(record.attachments) ||
    record.fastPreview != null ||
    record.deepContext != null ||
    record.document_analysis != null ||
    record.documentAnalysis != null ||
    record.compactDocument != null ||
    record.documentEnvelope != null ||
    record.envelope != null ||
    record.visionBlock != null
  );
}

export function extractAttachmentMetadataCarrier(
  metadata: Record<string, unknown> | undefined,
): Record<string, unknown> | null {
  const record = readRecord(metadata);
  if (!record) {
    return null;
  }

  const carrier: Record<string, unknown> = {};
  const attachments = readArray(record, "attachments")
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null);
  if (attachments.length > 0) {
    carrier.attachments = attachments;
    carrier.attachmentCount = attachments.length;
  }

  for (const key of [
    "document_analysis",
    "documentAnalysis",
    "compactDocument",
    "documentEnvelope",
    "envelope",
    "fastPreview",
    "deepContext",
    "processingState",
    "derivedContent",
    "sourceType",
    "raw_file_uploaded",
    "data_origin",
    "privacy_level",
    "attachmentCount",
    "visionBlock",
  ]) {
    if (record[key] !== undefined) {
      carrier[key] = record[key];
    }
  }

  if (!hasAttachmentShape(carrier)) {
    return null;
  }

  return normalizeLocalDerivedMetadata(carrier);
}

function extractAttachmentRecords(carrier: Record<string, unknown>): Record<string, unknown>[] {
  const attachments = readArray(carrier, "attachments")
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null);

  // Only synthesize a record from top-level legacy fields when there is no
  // explicit attachments[] array.  Synthesizing when attachments[] is already
  // present causes the same physical document to appear as two candidates and
  // triggers the "birden fazla belge görüyorum" clarification erroneously.
  const synthesized: Record<string, unknown>[] = [];
  if (
    attachments.length === 0 &&
    (readRecord(carrier.document_analysis) ||
      readRecord(carrier.documentAnalysis) ||
      readRecord(carrier.compactDocument) ||
      readRecord(carrier.documentEnvelope) ||
      readRecord(carrier.envelope))
  ) {
    synthesized.push({
      ...carrier,
      ...(readRecord(carrier.documentAnalysis) && carrier.document_analysis == null
        ? { document_analysis: carrier.documentAnalysis }
        : {}),
      ...(readRecord(carrier.envelope) && carrier.documentEnvelope == null
        ? { documentEnvelope: carrier.envelope }
        : {}),
    });
  }

  const seen = new Set<string>();
  const combined = [...attachments, ...synthesized].filter((item) => {
    const key = attachmentDedupKey(item);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });

  return combined;
}

function attachmentDedupKey(record: Record<string, unknown>): string {
  const documentAnalysis = readRecord(record.document_analysis) ?? readRecord(record.documentAnalysis);
  const compactDocument = readRecord(record.compactDocument);
  const documentEnvelope = readRecord(record.documentEnvelope) ?? readRecord(record.envelope);
  return [
    readString(record, "documentId"),
    readString(documentAnalysis, "documentId"),
    readString(compactDocument, "documentId"),
    readString(documentEnvelope, "id"),
    readString(compactDocument, "sha256"),
    readString(compactDocument, "content_hash"),
    readString(record, "sha256"),
    readString(record, "content_hash"),
    readString(record, "fileName"),
    readString(record, "name"),
  ]
    .filter(Boolean)
    .join("|")
    .toLowerCase() || JSON.stringify(record).slice(0, 120);
}

function blockToChunk(block: Record<string, unknown>) {
  const text = readString(block, "text") ?? readString(block, "content") ?? "";
  if (!text) {
    return null;
  }

  const metadata = readRecord(block.metadata) ?? {};
  return {
    text,
    pageNumber:
      typeof block.page === "number"
        ? block.page
        : typeof block.pageNumber === "number"
          ? block.pageNumber
          : 0,
    metadata: {
      ...metadata,
      ...(readString(block, "type") ? { kind: readString(block, "type") } : {}),
    },
  };
}

function describeMimeType(mimeType: string | null): string | null {
  const normalized = String(mimeType ?? "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (normalized === "application/pdf") {
    return "PDF";
  }
  if (normalized.includes("wordprocessingml") || normalized.includes("msword")) {
    return "Word";
  }
  if (normalized.includes("spreadsheetml") || normalized.includes("excel")) {
    return "Excel";
  }
  if (normalized.includes("presentationml") || normalized.includes("powerpoint")) {
    return "Sunum";
  }
  if (normalized.startsWith("image/")) {
    return "Görsel";
  }
  if (normalized === "text/markdown") {
    return "Markdown";
  }
  if (normalized.startsWith("text/")) {
    return "Metin";
  }
  return mimeType;
}

function readPositivePageNumber(record: Record<string, unknown> | null, key: string): number | null {
  const value = readNumber(record, key);
  return value !== null && Number.isInteger(value) && value > 0 ? value : null;
}

function inferPageCount(candidate: CachedPreparedAttachmentCandidate): number | null {
  const explicit =
    readPositivePageNumber(candidate.documentMetadata, "pageCount") ??
    readPositivePageNumber(candidate.documentMetadata, "page_count");
  if (explicit) {
    return explicit;
  }

  let maxPage = 0;
  for (const chunk of candidate.prepared.chunks) {
    const metadata = readRecord(chunk.metadata);
    const pageEnd =
      readPositivePageNumber(metadata, "pageEnd") ??
      readPositivePageNumber(metadata, "page_end") ??
      readPositivePageNumber(metadata, "pageNumber") ??
      readPositivePageNumber(metadata, "page");
    if (pageEnd && pageEnd > maxPage) {
      maxPage = pageEnd;
    }
  }

  return maxPage > 0 ? maxPage : null;
}

function inferExtractionMethod(candidate: CachedPreparedAttachmentCandidate): string | null {
  const explicit =
    readString(candidate.documentMetadata, "extractionMethod") ??
    readString(candidate.documentMetadata, "extraction_method") ??
    readString(candidate.documentMetadata, "analysisMode");
  if (explicit) {
    return explicit;
  }

  for (const chunk of candidate.prepared.chunks) {
    const metadata = readRecord(chunk.metadata);
    const value =
      readString(metadata, "extractionMethod") ??
      readString(metadata, "extraction_method") ??
      readString(metadata, "analysisMode");
    if (value) {
      return value;
    }
  }

  return null;
}

function inferConfidence(candidate: CachedPreparedAttachmentCandidate): number | null {
  const explicit = readNumber(candidate.documentMetadata, "confidence");
  if (explicit !== null) {
    return Math.max(0, Math.min(1, explicit));
  }

  let sum = 0;
  let count = 0;
  for (const chunk of candidate.prepared.chunks) {
    const value = readNumber(readRecord(chunk.metadata), "confidence");
    if (value === null) {
      continue;
    }
    sum += Math.max(0, Math.min(1, value));
    count += 1;
  }

  return count > 0 ? sum / count : null;
}

function formatConfidence(confidence: number | null): string | null {
  if (confidence === null) {
    return null;
  }
  return Math.max(0, Math.min(1, confidence)).toFixed(2);
}

function readChunkMetadataRecord(metadata: Record<string, unknown>): Record<string, unknown> | null {
  return readRecord(metadata.chunkMetadata);
}

function readChunkMetadataString(metadata: Record<string, unknown>, key: string): string | null {
  return readString(metadata, key) ?? readString(readChunkMetadataRecord(metadata), key);
}

function readChunkMetadataPageNumber(metadata: Record<string, unknown>, key: string): number | null {
  return (
    readPositivePageNumber(metadata, key) ??
    readPositivePageNumber(readChunkMetadataRecord(metadata), key)
  );
}

function resolveChunkPageRange(metadata: Record<string, unknown>, pageNumber: number | null) {
  const pageStart =
    readChunkMetadataPageNumber(metadata, "pageStart") ??
    readChunkMetadataPageNumber(metadata, "page_start") ??
    pageNumber;
  const pageEnd =
    readChunkMetadataPageNumber(metadata, "pageEnd") ??
    readChunkMetadataPageNumber(metadata, "page_end") ??
    pageStart;
  if (!pageStart || !pageEnd) {
    return null;
  }
  return {
    pageStart,
    pageEnd: pageEnd >= pageStart ? pageEnd : pageStart,
  };
}

function formatChunkPageLabel(metadata: Record<string, unknown>, pageNumber: number | null): string | null {
  const range = resolveChunkPageRange(metadata, pageNumber);
  if (!range) {
    return null;
  }
  return range.pageStart === range.pageEnd
    ? `Sayfa ${range.pageStart}`
    : `Sayfa ${range.pageStart}-${range.pageEnd}`;
}

function formatBlockKind(metadata: Record<string, unknown>): string | null {
  const normalized = (
    readString(metadata, "chunkKind") ??
    readChunkMetadataString(metadata, "blockType") ??
    readChunkMetadataString(metadata, "type") ??
    readChunkMetadataString(metadata, "kind") ??
    readString(metadata, "type") ??
    readString(metadata, "kind")
  )
    ?.trim()
    .toLowerCase();
  if (!normalized) {
    return null;
  }
  if (normalized === "table_data" || normalized === "table") {
    return "[tablo]";
  }
  if (normalized === "header") {
    return "[başlık]";
  }
  return null;
}

function resolveAttachmentCacheHash(record: Record<string, unknown>): string | null {
  const preferredRecord = selectPreferredAttachmentRecord(record);
  const documentAnalysis =
    readRecord(preferredRecord.document_analysis) ??
    readRecord(preferredRecord.documentAnalysis);
  const compactDocument = readRecord(preferredRecord.compactDocument);
  const documentEnvelope =
    readRecord(preferredRecord.documentEnvelope) ??
    readRecord(preferredRecord.envelope);
  const attachmentMetadata = readRecord(preferredRecord.metadata);

  return (
    readString(preferredRecord, "content_hash") ??
    readString(compactDocument, "content_hash") ??
    readString(attachmentMetadata, "content_hash") ??
    readString(documentAnalysis, "content_hash") ??
    readString(documentEnvelope, "content_hash") ??
    readString(preferredRecord, "sha256") ??
    readString(compactDocument, "sha256") ??
    readString(attachmentMetadata, "sha256") ??
    readString(documentAnalysis, "sha256") ??
    readString(documentEnvelope, "sha256")
  );
}

function buildEnvelopeFromPreview(record: Record<string, unknown>): Record<string, unknown> | null {
  const fastPreview = readRecord(record.fastPreview);
  if (!fastPreview) {
    return null;
  }

  const chunks = readArray(fastPreview, "chunks")
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null);
  if (!chunks.length) {
    return null;
  }

  const sourceHash =
    readString(record, "sha256") ??
    readString(record, "content_hash") ??
    readString(readRecord(record.compactDocument), "sha256") ??
    "local-derived";
  const mimeType = readString(record, "mimeType") ?? "application/octet-stream";
  return {
    id: readString(record, "documentId") ?? undefined,
    sourceHash,
    mimeType,
    blocks: chunks.map((chunk, index) => ({
      id:
        readString(chunk, "id") ??
        `${readString(record, "documentId") ?? "attachment"}-preview-${index + 1}`,
      type: "text",
      text: readString(chunk, "text") ?? "",
      page:
        typeof chunk.pageNumber === "number"
          ? chunk.pageNumber
          : typeof chunk.page === "number"
            ? chunk.page
            : index + 1,
      metadata: readRecord(chunk.metadata) ?? {},
      sourceHash,
      mimeType,
    })),
  };
}

function buildDocumentAnalysisFromPreview(record: Record<string, unknown>): Record<string, unknown> | null {
  const fastPreview = readRecord(record.fastPreview);
  if (!fastPreview) {
    return null;
  }

  const metadata = readRecord(fastPreview.metadata) ?? {};
  const textPreview =
    readString(fastPreview, "textPreview") ??
    readString(fastPreview, "summary") ??
    readString(record, "summary") ??
    "";
  const chunks = readArray(fastPreview, "chunks");

  return {
    documentId: readString(record, "documentId") ?? undefined,
    sourceType: readString(record, "sourceType") ?? "manual",
    fileName: readString(record, "fileName") ?? readString(record, "name") ?? "Ek",
    mimeType: readString(record, "mimeType") ?? "application/octet-stream",
    sizeBytes: record.sizeBytes,
    sha256: readString(record, "sha256") ?? undefined,
    extractedText: textPreview,
    textPreview,
    textTruncated: fastPreview.textTruncated === true,
    chunks,
    metadata: {
      ...metadata,
      ...(readString(record, "processingState")
        ? { processingState: readString(record, "processingState") }
        : {}),
    },
    summary: readString(fastPreview, "summary") ?? undefined,
    raw_file_uploaded: false,
    data_origin: "local_derived",
    privacy_level: "local_derived",
  };
}

function selectPreferredAttachmentRecord(record: Record<string, unknown>): Record<string, unknown> {
  const deepContext = readRecord(record.deepContext);
  if (deepContext) {
    return {
      ...record,
      ...deepContext,
      ...(readRecord(deepContext.documentAnalysis) && deepContext.document_analysis == null
        ? { document_analysis: deepContext.documentAnalysis }
        : {}),
      ...(readRecord(deepContext.envelope) && deepContext.documentEnvelope == null
        ? { documentEnvelope: deepContext.envelope }
        : {}),
    };
  }

  const fastPreview = readRecord(record.fastPreview);
  if (!fastPreview) {
    return record;
  }

  const synthesizedAnalysis = buildDocumentAnalysisFromPreview(record);
  const synthesizedEnvelope = buildEnvelopeFromPreview(record);
  return {
    ...record,
    ...(synthesizedAnalysis ? { document_analysis: synthesizedAnalysis } : {}),
    ...(synthesizedEnvelope ? { documentEnvelope: synthesizedEnvelope } : {}),
  };
}

function buildPreparedAttachmentCandidateFromPrepared(
  record: Record<string, unknown>,
  prepared: ReturnType<typeof prepareKnowledgeDocument>,
): CachedPreparedAttachmentCandidate | null {
  if (readString(record, "processingState")?.toLowerCase() === "failed") {
    return null;
  }
  const preferredRecord = selectPreferredAttachmentRecord(record);
  const documentAnalysis =
    readRecord(preferredRecord.document_analysis) ??
    readRecord(preferredRecord.documentAnalysis);
  const compactDocument = readRecord(preferredRecord.compactDocument);
  const documentEnvelope =
    readRecord(preferredRecord.documentEnvelope) ??
    readRecord(preferredRecord.envelope);
  const envelopeMetadata = readRecord(documentEnvelope?.metadata);
  const analysisMetadata = readRecord(documentAnalysis?.metadata);
  const attachmentMetadata = readRecord(preferredRecord.metadata);
  const sourceType = normalizeSourceType(
    readString(preferredRecord, "sourceType") ??
      readString(compactDocument, "sourceType") ??
      readString(attachmentMetadata, "sourceType"),
  );
  const mergedMetadata = normalizeLocalDerivedMetadata({
    ...(attachmentMetadata ?? {}),
    ...(analysisMetadata ?? {}),
    ...(envelopeMetadata ?? {}),
    ...(compactDocument ?? {}),
    sourceType,
    processingState: readString(preferredRecord, "processingState") ?? undefined,
    document_analysis: documentAnalysis ?? undefined,
    compactDocument: compactDocument ?? undefined,
    documentEnvelope: documentEnvelope ?? undefined,
    mimeType:
      readString(preferredRecord, "mimeType") ??
      readString(compactDocument, "mimeType") ??
      readString(attachmentMetadata, "mimeType") ??
      undefined,
    originalName:
      readString(preferredRecord, "fileName") ??
      readString(preferredRecord, "name") ??
      readString(compactDocument, "fileName") ??
      readString(attachmentMetadata, "originalName") ??
      undefined,
  });

  const documentId =
    readString(preferredRecord, "documentId") ??
    readString(documentAnalysis, "documentId") ??
    readString(compactDocument, "documentId") ??
    readString(documentEnvelope, "id") ??
    readString(preferredRecord, "sha256") ??
    readString(preferredRecord, "content_hash") ??
    readString(compactDocument, "sha256") ??
    readString(compactDocument, "content_hash") ??
    `attachment-${prepared.contentHash.slice(0, 12)}`;
  const title =
    readString(preferredRecord, "fileName") ??
    readString(preferredRecord, "name") ??
    readString(compactDocument, "fileName") ??
    readString(attachmentMetadata, "originalName") ??
    readString(preferredRecord, "title") ??
    "Ek";
  const mimeType =
    readString(preferredRecord, "mimeType") ??
    readString(compactDocument, "mimeType") ??
    readString(attachmentMetadata, "mimeType");
  const summary =
    readString(preferredRecord, "summary") ??
    readString(documentAnalysis, "summary") ??
    prepared.summary;

  return {
    documentId,
    title,
    mimeType,
    summary,
    documentMetadata: mergedMetadata,
    prepared,
  };
}

function buildPreparedAttachmentCandidatePayload(
  record: Record<string, unknown>,
): CachedPreparedAttachmentCandidate | null {
  if (readString(record, "processingState")?.toLowerCase() === "failed") {
    return null;
  }
  const preferredRecord = selectPreferredAttachmentRecord(record);
  const documentAnalysis =
    readRecord(preferredRecord.document_analysis) ??
    readRecord(preferredRecord.documentAnalysis);
  const compactDocument = readRecord(preferredRecord.compactDocument);
  const documentEnvelope =
    readRecord(preferredRecord.documentEnvelope) ??
    readRecord(preferredRecord.envelope);
  const envelopeMetadata = readRecord(documentEnvelope?.metadata);
  const analysisMetadata = readRecord(documentAnalysis?.metadata);
  const attachmentMetadata = readRecord(preferredRecord.metadata);
  const sourceType = normalizeSourceType(
    readString(preferredRecord, "sourceType") ??
      readString(compactDocument, "sourceType") ??
      readString(attachmentMetadata, "sourceType"),
  );
  const mergedMetadata = normalizeLocalDerivedMetadata({
    ...(attachmentMetadata ?? {}),
    ...(analysisMetadata ?? {}),
    ...(envelopeMetadata ?? {}),
    ...(compactDocument ?? {}),
    sourceType,
    processingState: readString(preferredRecord, "processingState") ?? undefined,
    document_analysis: documentAnalysis ?? undefined,
    compactDocument: compactDocument ?? undefined,
    documentEnvelope: documentEnvelope ?? undefined,
    mimeType:
      readString(preferredRecord, "mimeType") ??
      readString(compactDocument, "mimeType") ??
      readString(attachmentMetadata, "mimeType") ??
      undefined,
    originalName:
      readString(preferredRecord, "fileName") ??
      readString(preferredRecord, "name") ??
      readString(compactDocument, "fileName") ??
      readString(attachmentMetadata, "originalName") ??
      undefined,
  });
  const explicitChunks = readArray(preferredRecord, "chunks") as Array<string | Record<string, unknown>>;
  const analysisChunks = readArray(documentAnalysis, "chunks") as Array<string | Record<string, unknown>>;
  const envelopeBlocks = readArray(documentEnvelope, "blocks")
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null)
    .map(blockToChunk)
    .filter((item): item is { text: string; pageNumber: number; metadata: Record<string, unknown> } => item != null);
  const prepared = (() => {
    try {
      return prepareKnowledgeDocument({
        text:
          readString(preferredRecord, "extractedText") ??
          readString(preferredRecord, "textPreview") ??
          readString(preferredRecord, "content") ??
          readString(preferredRecord, "text") ??
          readString(documentAnalysis, "extractedText") ??
          readString(documentAnalysis, "textPreview") ??
          readString(preferredRecord, "summary") ??
          readString(documentAnalysis, "summary") ??
          undefined,
        chunks:
          explicitChunks.length > 0
            ? explicitChunks
            : analysisChunks.length > 0
              ? analysisChunks
              : envelopeBlocks.length > 0
                ? envelopeBlocks
                : undefined,
        metadata: mergedMetadata,
        sourceType,
      });
    } catch {
      return null;
    }
  })();

  if (!prepared) {
    return null;
  }

  return buildPreparedAttachmentCandidateFromPrepared(record, prepared);
}

function buildPreparedAttachmentCandidate(
  record: Record<string, unknown>,
  source: "request" | "session",
): PreparedAttachmentCandidate | null {
  const payload = buildPreparedAttachmentCandidatePayload(record);
  if (!payload) {
    return null;
  }

  return {
    ...payload,
    key: attachmentDedupKey(record),
    source,
    cacheHit: false,
  };
}

function parseCachedPreparedAttachmentCandidate(
  value: string,
): CachedPreparedAttachmentRecord | null {
  try {
    const parsed = JSON.parse(value) as CachedPreparedAttachmentRecord | null;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    if (
      !parsed.prepared ||
      typeof parsed.prepared !== "object" ||
      !Array.isArray(parsed.prepared.chunks)
    ) {
      return null;
    }
    return {
      prepared: parsed.prepared,
    };
  } catch {
    return null;
  }
}

async function buildPreparedAttachmentCandidateWithCache(
  store: AttachmentContextStore,
  record: Record<string, unknown>,
  source: "request" | "session",
): Promise<PreparedAttachmentCandidate | null> {
  const cacheHash = resolveAttachmentCacheHash(record);
  if (!cacheHash) {
    return buildPreparedAttachmentCandidate(record, source);
  }

  const cacheKey = `attachment_context:prepared:${cacheHash}`;
  const cachedValue = await store.get(cacheKey);
  if (cachedValue) {
    const cachedCandidate = parseCachedPreparedAttachmentCandidate(cachedValue);
    if (cachedCandidate) {
      const payload = buildPreparedAttachmentCandidateFromPrepared(
        record,
        cachedCandidate.prepared,
      );
      if (!payload) {
        return null;
      }
      return {
        ...payload,
        key: attachmentDedupKey(record),
        source,
        cacheHit: true,
      };
    }
  }

  const payload = buildPreparedAttachmentCandidatePayload(record);
  if (!payload) {
    return null;
  }

  await store
    .set(
      cacheKey,
      JSON.stringify({
        prepared: payload.prepared,
      } satisfies CachedPreparedAttachmentRecord),
      PREPARED_ATTACHMENT_CACHE_TTL_MS,
    )
    .catch(() => undefined);

  return {
    ...payload,
    key: attachmentDedupKey(record),
    source,
    cacheHit: false,
  };
}

function buildPreparedCandidates(
  metadata: Record<string, unknown> | undefined,
  source: "request" | "session",
): PreparedAttachmentCandidate[] {
  const carrier = extractAttachmentMetadataCarrier(metadata);
  if (!carrier) {
    return [];
  }

  return extractAttachmentRecords(carrier)
    .map((record) => buildPreparedAttachmentCandidate(record, source))
    .filter((item): item is PreparedAttachmentCandidate => item != null);
}

async function buildPreparedCandidatesWithCache(
  store: AttachmentContextStore,
  metadata: Record<string, unknown> | undefined,
  source: "request" | "session",
): Promise<PreparedAttachmentCandidate[]> {
  const carrier = extractAttachmentMetadataCarrier(metadata);
  if (!carrier) {
    return [];
  }

  const prepared = await Promise.all(
    extractAttachmentRecords(carrier).map((record) =>
      buildPreparedAttachmentCandidateWithCache(store, record, source),
    ),
  );

  return prepared.filter((item): item is PreparedAttachmentCandidate => item != null);
}

function isReferentialAttachmentPrompt(prompt: string): boolean {
  const normalized = normalizeToken(prompt);
  if (!normalized) {
    return false;
  }

  return /\b(bu|bunu|buna|bundan|şu|sunu|same document|aynı belge|aynı dosya|bu belge|bu dosya|bu görsel|bu resim|bu pdf|sayfa|tablo)\b/u.test(
    normalized,
  );
}

export function promptReferencesSessionVisual(prompt: string): boolean {
  const normalized = normalizeToken(prompt);
  if (!normalized) return false;
  return /\b(görsel|gorsel|resim|fotoğraf|fotograf|ekran|screenshot|image|picture|photo|soldaki|sağdaki|sagdaki|üstteki|ustteki|alttaki|önceki ekran|onceki ekran|bu uyarı|bu uyari|bu nesne|bu yazı|bu yazi|bu tablo|bu grafik|what is on the left|in the image|in the picture)\b/u.test(normalized);
}

function candidateAliases(candidate: PreparedAttachmentCandidate): string[] {
  const aliases = new Set<string>();
  const rawTitle = compactText(candidate.title);
  if (rawTitle) {
    aliases.add(normalizeToken(rawTitle));
    aliases.add(normalizeToken(rawTitle.replace(/\.[a-z0-9]{2,5}$/i, "")));
  }
  aliases.add(normalizeToken(candidate.documentId));
  return [...aliases].filter((value) => value.length >= 3);
}

function matchCandidatesByPrompt(
  candidates: PreparedAttachmentCandidate[],
  prompt: string,
): PreparedAttachmentCandidate[] {
  const normalizedPrompt = normalizeToken(prompt);
  if (!normalizedPrompt) {
    return [];
  }

  return candidates.filter((candidate) =>
    candidateAliases(candidate).some(
      (alias) => alias && normalizedPrompt.includes(alias),
    ),
  );
}

function buildClarificationMessage(candidates: PreparedAttachmentCandidate[]): string {
  const labels = candidates
    .slice(0, DEFAULT_MAX_ATTACHMENTS)
    .map((candidate) => candidate.title)
    .filter(Boolean)
    .join(", ");
  return labels
    ? `Birden fazla belge veya görsel görüyorum. Hangisini kullanmamı istediğini belirt: ${labels}.`
    : "Birden fazla belge veya görsel görüyorum. Hangisini kullanmamı istediğini belirtir misin?";
}

/* ════════════════════════════════════════════════════════════════════════
 * Question-relevant chunk selection
 *
 * Long documents used to be blindly truncated: chunks were consumed in file
 * order until the char/chunk budget ran out, so a question about page 40 got
 * pages 1-3 as context. When a document does not fit the budget we now rank
 * its chunks against the user's question — semantically via the e5-small
 * storage embedder when available, lexically otherwise — keep the top-K, and
 * re-sort the survivors back into document order so the excerpt still reads
 * coherently. Documents that fit the budget are left untouched.
 * ════════════════════════════════════════════════════════════════════════ */

const CHUNK_RELEVANCE_STOPWORDS = new Set([
  "acaba", "ama", "ancak", "bana", "belge", "ben", "bir", "biz", "bunu", "bunun",
  "daha", "dosya", "gibi", "hangi", "için", "icin", "ile", "kadar", "nasıl",
  "nasil", "nedir", "olan", "olarak", "sen", "şey", "sey", "var", "veya",
  "the", "and", "for", "with", "what", "this", "that", "from", "about",
]);

const SEMANTIC_CHUNK_SCORE_TIMEOUT_MS = 2_500;
const MAX_CHUNKS_TO_EMBED = 80;

type RankableChunk = ReturnType<typeof prepareKnowledgeDocument>["chunks"][number];

function buildPromptTokenSet(prompt: string): Set<string> {
  const tokens = normalizeToken(prompt).split(" ");
  const set = new Set<string>();
  for (const token of tokens) {
    if (token.length >= 3 && !CHUNK_RELEVANCE_STOPWORDS.has(token)) {
      set.add(token);
    }
  }
  return set;
}

function lexicalChunkScore(promptTokens: Set<string>, content: string): number {
  if (promptTokens.size === 0) {
    return 0;
  }
  const chunkTokens = new Set(normalizeToken(content).split(" ").filter(Boolean));
  if (chunkTokens.size === 0) {
    return 0;
  }
  let hits = 0;
  for (const token of promptTokens) {
    if (chunkTokens.has(token)) {
      hits += 1;
      continue;
    }
    // Turkish suffixation: "faturalar", "faturanın" should still match "fatura".
    for (const chunkToken of chunkTokens) {
      if (chunkToken.length >= 4 && (chunkToken.startsWith(token) || token.startsWith(chunkToken))) {
        hits += 0.7;
        break;
      }
    }
  }
  return hits / promptTokens.size;
}

function candidateNeedsChunkRanking(
  candidate: PreparedAttachmentCandidate,
  maxChunks: number,
  maxChars: number,
): boolean {
  const chunks = candidate.prepared.chunks;
  if (chunks.length > maxChunks) {
    return true;
  }
  let totalChars = 0;
  for (const chunk of chunks) {
    totalChars += Math.min(compactText(chunk.content).length, MAX_EXCERPT_CHARS);
  }
  return totalChars > maxChars;
}

/**
 * Picks the most question-relevant chunk indices (in original document order).
 * `semanticScores` — when provided (one per chunk, higher is better) — is the
 * primary signal, with lexical overlap as tiebreak; otherwise lexical only.
 * Exported for tests.
 */
export function selectPromptRelevantChunkIndices(input: {
  prompt: string;
  contents: string[];
  maxChunks: number;
  semanticScores?: number[] | null;
}): number[] {
  const promptTokens = buildPromptTokenSet(input.prompt);
  const scored = input.contents.map((content, index) => {
    const lexical = lexicalChunkScore(promptTokens, content);
    const semantic =
      input.semanticScores && Number.isFinite(input.semanticScores[index])
        ? Number(input.semanticScores[index])
        : null;
    return {
      index,
      score: semantic !== null ? semantic + lexical * 0.1 : lexical,
    };
  });

  const hasSignal = scored.some((item) => item.score > 0);
  if (!hasSignal) {
    // No relevance signal at all — keep the document head (original behavior).
    return scored.slice(0, input.maxChunks).map((item) => item.index);
  }

  return scored
    .slice()
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .slice(0, Math.max(1, input.maxChunks))
    .map((item) => item.index)
    .sort((left, right) => left - right);
}

function reorderCandidateChunksForPrompt(
  prompt: string,
  candidate: PreparedAttachmentCandidate,
  maxChunks: number,
  maxChars: number,
  semanticScores: number[] | null,
): PreparedAttachmentCandidate {
  if (!candidateNeedsChunkRanking(candidate, maxChunks, maxChars)) {
    return candidate;
  }
  const chunks = candidate.prepared.chunks as RankableChunk[];
  const selected = selectPromptRelevantChunkIndices({
    prompt,
    contents: chunks.map((chunk) => String(chunk.content ?? "")),
    maxChunks,
    semanticScores,
  });
  if (selected.length === chunks.length) {
    return candidate;
  }
  return {
    ...candidate,
    prepared: {
      ...candidate.prepared,
      chunks: selected.map((index) => chunks[index]),
    },
  };
}

function cosineDot(a: Float32Array | number[] | ReadonlyArray<number>, b: Float32Array | number[] | ReadonlyArray<number>): number {
  let dot = 0;
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i += 1) {
    dot += a[i] * b[i];
  }
  return dot;
}

/**
 * Race a promise against a shared deadline. When the deadline has already
 * elapsed, resolves to null without even awaiting the underlying work. Used
 * so the semantic-ranking budget is spent per REQUEST, not per candidate: 3
 * attachments never blow past a single 2.5s budget.
 */
function raceDeadline<T>(work: Promise<T>, remainingMs: number): Promise<T | null> {
  if (remainingMs <= 0) {
    return Promise.resolve(null);
  }
  return new Promise<T | null>((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve(null);
    }, remainingMs);
    timer.unref?.();
    work.then(
      (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      },
      () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(null);
      },
    );
  });
}

function rankCandidatesForPrompt(
  prompt: string,
  candidates: PreparedAttachmentCandidate[],
  maxChunks: number,
  maxChars: number,
): PreparedAttachmentCandidate[] {
  return candidates.map((candidate) =>
    reorderCandidateChunksForPrompt(prompt, candidate, maxChunks, maxChars, null),
  );
}

/**
 * Rank candidates with e5-small storage embeddings. Optimized vs the earlier
 * per-candidate-sequential path:
 *   1. Query embedding is computed ONCE per request (not per candidate).
 *   2. Chunk-vector calls for every candidate that needs ranking are launched
 *      in parallel — the total wall-clock is dominated by the slowest
 *      candidate, not the sum.
 *   3. The 2.5s timeout is a SHARED per-request budget, not per-candidate:
 *      three attachments can never spend 7.5s of caller time waiting.
 * When the embedder is disabled, times out, or throws, every candidate falls
 * back to the lexical ranker — same behavior as before, just cheaper.
 */
async function rankCandidatesForPromptWithEmbeddings(
  prompt: string,
  candidates: PreparedAttachmentCandidate[],
  maxChunks: number,
  maxChars: number,
): Promise<PreparedAttachmentCandidate[]> {
  if (candidates.length === 0) {
    return candidates;
  }
  const rankable = candidates.map((candidate) =>
    candidateNeedsChunkRanking(candidate, maxChunks, maxChars),
  );
  if (!rankable.some(Boolean) || isStorageEmbedderDisabled()) {
    return candidates.map((candidate, index) =>
      rankable[index]
        ? reorderCandidateChunksForPrompt(prompt, candidate, maxChunks, maxChars, null)
        : candidate,
    );
  }

  const deadlineAt = Date.now() + SEMANTIC_CHUNK_SCORE_TIMEOUT_MS;
  const remaining = () => deadlineAt - Date.now();

  // Query embedding is a single call; every candidate reuses this vector.
  const queryVector = await raceDeadline(embedQueryForStorage(prompt), remaining()).catch(
    () => null,
  );

  // Kick off chunk-vector requests for all rankable candidates in parallel.
  const chunkContents = candidates.map((candidate, index) =>
    rankable[index]
      ? (candidate.prepared.chunks as RankableChunk[])
          .map((chunk) => String(chunk.content ?? ""))
          .slice(0, MAX_CHUNKS_TO_EMBED)
      : null,
  );
  const vectorPromises = chunkContents.map((contents) =>
    contents && queryVector
      ? embedTextsForStorage(contents).catch(() => null)
      : Promise.resolve(null),
  );
  const chunkVectorsByCandidate = await Promise.all(
    vectorPromises.map((promise) => raceDeadline(promise, remaining())),
  );

  return candidates.map((candidate, index) => {
    if (!rankable[index]) {
      return candidate;
    }
    const contents = chunkContents[index]!;
    const totalChunks = (candidate.prepared.chunks as RankableChunk[]).length;
    const chunkVectors = chunkVectorsByCandidate[index];
    let semanticScores: number[] | null = null;
    if (queryVector && chunkVectors) {
      const raw = chunkVectors.map((vector) => cosineDot(queryVector, vector));
      // Pad the truncated tail (chunks past MAX_CHUNKS_TO_EMBED) with -1 so
      // unembedded chunks rank below embedded ones while lexical scoring can
      // still surface them via the tiebreak.
      semanticScores = Array.from({ length: totalChunks }, (_, i) =>
        i < raw.length ? raw[i] : -1,
      );
      void contents;
    }
    return reorderCandidateChunksForPrompt(
      prompt,
      candidate,
      maxChunks,
      maxChars,
      semanticScores,
    );
  });
}

function buildPromptBlock(input: {
  candidates: PreparedAttachmentCandidate[];
  source: AttachmentContextSource;
  maxChunks: number;
  maxChars: number;
}) {
  const lines = [
    "Attachment context (mobile-derived, readable, session-scoped):",
    "Use only this attachment context for the attached-file question. If it is insufficient, say so plainly.",
  ];
  const documents: ResolvedAttachmentContextDocument[] = [];
  const chunks: ResolvedAttachmentContextChunk[] = [];
  const documentIds: string[] = [];
  let totalChars = 0;
  let chunkCount = 0;

  for (const [index, candidate] of input.candidates.entries()) {
    if (chunkCount >= input.maxChunks || totalChars >= input.maxChars) {
      break;
    }

    const docLines: string[] = [];
    const summary = boundedText(candidate.summary, 240);
    const pageCount = inferPageCount(candidate);
    const confidence = formatConfidence(inferConfidence(candidate));
    const extractionMethod = inferExtractionMethod(candidate);
    const headerSegments = [
      `BELGE ${index + 1}: ${candidate.title}`,
      describeMimeType(candidate.mimeType),
      pageCount ? `${pageCount} sayfa` : null,
      confidence ? `güven: ${confidence}` : null,
      extractionMethod ? `yöntem: ${extractionMethod}` : null,
    ].filter((value): value is string => Boolean(value));
    const header = `[${headerSegments.join(" | ")}]`;
    docLines.push(header);
    if (summary) {
      docLines.push(`Özet: ${summary}`);
      totalChars += summary.length;
    }

    let includedChunkCount = 0;
    for (const [chunkIndex, chunk] of candidate.prepared.chunks.entries()) {
      if (chunkCount >= input.maxChunks || totalChars >= input.maxChars) {
        break;
      }

      const excerpt = boundedExcerptText(chunk.content);
      if (!excerpt) {
        continue;
      }

      const nextChars = totalChars + excerpt.length;
      if (includedChunkCount > 0 && nextChars > input.maxChars) {
        break;
      }

      const pageNumber =
        readChunkMetadataPageNumber(chunk.metadata, "pageNumber") ??
        readChunkMetadataPageNumber(chunk.metadata, "page") ??
        null;
      const pageLabel = formatChunkPageLabel(chunk.metadata, pageNumber);
      const blockKind = formatBlockKind(chunk.metadata);
      docLines.push(
        `${pageLabel ?? "İçerik"}: ${blockKind ? `${blockKind} ` : ""}${excerpt}`,
      );
      const chunkId =
        typeof chunk.metadata.id === "string" && chunk.metadata.id.trim()
          ? chunk.metadata.id.trim()
          : `${candidate.documentId}:chunk:${chunkIndex + 1}`;
      chunks.push({
        documentId: candidate.documentId,
        documentTitle: candidate.title,
        mimeType: candidate.mimeType,
        chunkId,
        chunkHash: stableChunkHash({
          documentId: candidate.documentId,
          chunkId,
          pageNumber,
          content: excerpt,
        }),
        content: excerpt,
        pageNumber,
        metadata: chunk.metadata,
      });
      includedChunkCount += 1;
      chunkCount += 1;
      totalChars += excerpt.length;
    }

    lines.push(...docLines);
    lines.push("");
    documentIds.push(candidate.documentId);
    documents.push({
      documentId: candidate.documentId,
      title: candidate.title,
      mimeType: candidate.mimeType,
      summary,
      source: candidate.source,
      chunkCount: candidate.prepared.chunks.length,
      includedChunkCount,
    });
  }

  return {
    promptBlock: lines.join("\n").trim(),
    documents,
    chunks,
    documentIds,
    totalChars,
    chunkCount,
  };
}

function extractSessionCandidates(
  sessionAttachmentCandidates: AttachmentContextCandidate[] | undefined,
): PreparedAttachmentCandidate[] {
  if (!sessionAttachmentCandidates?.length) {
    return [];
  }

  const prepared: PreparedAttachmentCandidate[] = [];
  const seen = new Set<string>();
  for (const candidate of sessionAttachmentCandidates) {
    for (const preparedCandidate of buildPreparedCandidates(candidate.metadata, "session")) {
      if (seen.has(preparedCandidate.key)) {
        continue;
      }
      seen.add(preparedCandidate.key);
      prepared.push(preparedCandidate);
    }
  }
  return prepared;
}

async function extractSessionCandidatesWithCache(
  store: AttachmentContextStore,
  sessionAttachmentCandidates: AttachmentContextCandidate[] | undefined,
): Promise<PreparedAttachmentCandidate[]> {
  if (!sessionAttachmentCandidates?.length) {
    return [];
  }

  const prepared: PreparedAttachmentCandidate[] = [];
  const seen = new Set<string>();
  for (const candidate of sessionAttachmentCandidates) {
    for (const preparedCandidate of await buildPreparedCandidatesWithCache(
      store,
      candidate.metadata,
      "session",
    )) {
      if (seen.has(preparedCandidate.key)) {
        continue;
      }
      seen.add(preparedCandidate.key);
      prepared.push(preparedCandidate);
    }
  }
  return prepared;
}

const MAX_VISION_BLOCKS_PER_TURN = 4;

function readVisionBlockFromRecord(
  record: Record<string, unknown> | null,
): VisionEvidence | null {
  return parseVisionEvidence(readRecord(record?.visionBlock));
}

function collectVisionBlocksFromCarrier(
  carrier: Record<string, unknown> | null,
): VisionEvidence[] {
  if (!carrier) {
    return [];
  }
  const blocks: VisionEvidence[] = [];
  const topLevel = readVisionBlockFromRecord(carrier);
  if (topLevel) {
    blocks.push(topLevel);
  }
  const attachmentRecords = readArray(carrier, "attachments")
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null);
  for (const record of attachmentRecords) {
    if (blocks.length >= MAX_VISION_BLOCKS_PER_TURN) {
      break;
    }
    const block = readVisionBlockFromRecord(record);
    if (block) {
      blocks.push(block);
    }
    for (const item of readArray(record, "clientAttachments")) {
      if (blocks.length >= MAX_VISION_BLOCKS_PER_TURN) {
        break;
      }
      const nested = readVisionBlockFromRecord(readRecord(item));
      if (nested) {
        blocks.push(nested);
      }
    }
  }
  return blocks;
}

function collectSessionVisionBlocks(
  candidates: AttachmentContextCandidate[] | undefined,
): VisionEvidence[] {
  if (!candidates?.length) return [];
  const blocks: VisionEvidence[] = [];
  const seen = new Set<string>();
  const ordered = [...candidates].sort((a, b) =>
    String(b.createdAt ?? "").localeCompare(String(a.createdAt ?? "")),
  );
  for (const candidate of ordered) {
    if (!isSessionVisionMemoryFresh(candidate.createdAt)) {
      continue;
    }
    for (const block of collectVisionBlocksFromCarrier(
      extractAttachmentMetadataCarrier(candidate.metadata),
    )) {
      if (seen.has(block.id)) continue;
      seen.add(block.id);
      blocks.push(block);
      if (blocks.length >= MAX_VISION_BLOCKS_PER_TURN) return blocks;
    }
  }
  return blocks;
}

function buildNormalizedVisionPromptBlock(
  prompt: string,
  blocks: VisionEvidence[],
): string | null {
  const normalized = blocks
    .map((block) => normalizeVisionEvidence(block))
    .filter((block): block is VisionEvidenceV3 => block != null);
  if (normalized.length === 0) return null;
  const task = classifyVisionTask({
    prompt,
    evidence: normalized[0],
    imageCount: normalized.length,
  });
  const evidenceGate = assessVisionEvidence(normalized, task);
  return [
    buildVisionTaskPromptBlock(task),
    buildVisionEvidenceGatePrompt(evidenceGate),
    formatVisionEvidenceV3Prompt(normalized),
  ].filter((value): value is string => Boolean(value)).join("\n\n");
}

function resolveAttachmentContextFromCandidates(input: {
  prompt: string;
  requestCarrier: Record<string, unknown> | null;
  requestCandidates: PreparedAttachmentCandidate[];
  sessionCandidates: PreparedAttachmentCandidate[];
  maxAttachments: number;
  maxChunks: number;
  maxChars: number;
  recoveredVisionBlocks?: VisionEvidence[];
  hasEphemeralVision?: boolean;
}): ResolvedAttachmentContext | null {
  const source: AttachmentContextSource =
    input.requestCandidates.length > 0 ? "request_attachments" : "session_recovery";
  const baseCandidates =
    input.requestCandidates.length > 0 ? input.requestCandidates : input.sessionCandidates;
  const requestVisionBlocks = collectVisionBlocksFromCarrier(input.requestCarrier);
  const visionBlocks = requestVisionBlocks.length > 0
    ? requestVisionBlocks
    : (input.recoveredVisionBlocks ?? []);

  if (baseCandidates.length === 0) {
    if (visionBlocks.length > 0) {
      const visionPromptBlock = buildNormalizedVisionPromptBlock(input.prompt, visionBlocks) ?? "";
      return {
        used: true,
        source: "request_attachments",
        promptBlock: visionPromptBlock,
        documentIds: visionBlocks.map((block) => block.id),
        documents: [],
        chunks: [],
        totalChars: visionPromptBlock.length,
        chunkCount: 0,
        needsClarification: false,
        visionBlocks,
      };
    }
    if (input.requestCarrier) {
      // Görsel baytları request-scoped ephemeralVision taşıyıcısında geliyor;
      // metin/OCR türevi olmaması netleştirme gerektirmez — vision modeli
      // görseli doğrudan görecek.
      if (input.hasEphemeralVision === true) {
        return null;
      }
      return {
        used: false,
        source: "request_attachments",
        promptBlock: "",
        documentIds: [],
        documents: [],
        chunks: [],
        totalChars: 0,
        chunkCount: 0,
        needsClarification: true,
        clarificationMessage:
          "Eklenen belge veya görselden yeterli okunabilir veri çıkarılamadı. Lütfen dosyayı yeniden ekle veya işlenecek sayfayı belirt.",
      };
    }
    return null;
  }

  let selectedCandidates = baseCandidates.slice(0, input.maxAttachments);
  if (selectedCandidates.length > 1) {
    const namedMatches = matchCandidatesByPrompt(selectedCandidates, input.prompt);
    if (namedMatches.length === 1) {
      selectedCandidates = [namedMatches[0]];
    } else if (namedMatches.length > 1 || isReferentialAttachmentPrompt(input.prompt)) {
      return {
        used: false,
        source,
        promptBlock: "",
        documentIds: selectedCandidates.map((candidate) => candidate.documentId),
        documents: selectedCandidates.map((candidate) => ({
          documentId: candidate.documentId,
          title: candidate.title,
          mimeType: candidate.mimeType,
          summary: boundedText(candidate.summary, 180),
          source: candidate.source,
          chunkCount: candidate.prepared.chunks.length,
          includedChunkCount: 0,
        })),
        chunks: [],
        totalChars: 0,
        chunkCount: 0,
        needsClarification: true,
        clarificationMessage: buildClarificationMessage(selectedCandidates),
        cacheHit: selectedCandidates.some((candidate) => candidate.cacheHit),
      };
    }
  }

  const promptBlock = buildPromptBlock({
    candidates: selectedCandidates,
    source,
    maxChunks: input.maxChunks,
    maxChars: input.maxChars,
  });
  const visionPromptBlock = buildNormalizedVisionPromptBlock(input.prompt, visionBlocks);
  const combinedPromptBlock = [promptBlock.promptBlock, visionPromptBlock]
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .join("\n\n");
  return {
    used: promptBlock.documents.length > 0 || visionBlocks.length > 0,
    source,
    promptBlock: combinedPromptBlock,
    documentIds: promptBlock.documentIds,
    documents: promptBlock.documents,
    chunks: promptBlock.chunks,
    totalChars: promptBlock.totalChars,
    chunkCount: promptBlock.chunkCount,
    needsClarification: false,
    cacheHit: selectedCandidates.some((candidate) => candidate.cacheHit),
    visionBlocks,
  };
}

export function extractAttachmentCandidatesFromBrainContext(
  value: unknown,
): AttachmentContextCandidate[] {
  const brainContext = readRecord(value);
  const candidates = readArray(brainContext, "attachmentCandidates");
  const resolved: AttachmentContextCandidate[] = [];

  for (const rawCandidate of candidates) {
    const candidate = readRecord(rawCandidate);
    if (!candidate) {
      continue;
    }

    const metadata = extractAttachmentMetadataCarrier(
      readRecord(candidate.metadata) ?? undefined,
    );
    if (!metadata) {
      continue;
    }

    resolved.push({
      messageId: readString(candidate, "messageId") ?? undefined,
      createdAt: readString(candidate, "createdAt") ?? undefined,
      prompt: readString(candidate, "prompt") ?? undefined,
      metadata,
    });
  }

  return resolved;
}

export function resolveAttachmentContext(input: {
  prompt: string;
  metadata?: Record<string, unknown>;
  sessionAttachmentCandidates?: AttachmentContextCandidate[];
  maxAttachments?: number;
  maxChunks?: number;
  maxChars?: number;
  hasEphemeralVision?: boolean;
}): ResolvedAttachmentContext | null {
  const maxAttachments = input.maxAttachments ?? DEFAULT_MAX_ATTACHMENTS;
  const maxChunks = input.maxChunks ?? DEFAULT_MAX_CHUNKS;
  const maxChars = input.maxChars ?? DEFAULT_MAX_CHARS;
  const requestCarrier = extractAttachmentMetadataCarrier(input.metadata);
  const requestCandidates = rankCandidatesForPrompt(
    input.prompt,
    buildPreparedCandidates(input.metadata, "request"),
    maxChunks,
    maxChars,
  );
  const sessionCandidates = !requestCarrier
    ? rankCandidatesForPrompt(
        input.prompt,
        extractSessionCandidates(input.sessionAttachmentCandidates),
        maxChunks,
        maxChars,
      )
    : [];
  const context = resolveAttachmentContextFromCandidates({
    prompt: input.prompt,
    requestCarrier,
    requestCandidates,
    sessionCandidates,
    maxAttachments,
    maxChunks,
    maxChars,
    recoveredVisionBlocks: !requestCarrier && promptReferencesSessionVisual(input.prompt)
      ? collectSessionVisionBlocks(input.sessionAttachmentCandidates)
      : [],
    hasEphemeralVision: input.hasEphemeralVision,
  });
  return context;
}

export async function resolveAttachmentContextWithCache(
  store: AttachmentContextStore,
  input: {
    prompt: string;
    metadata?: Record<string, unknown>;
    sessionAttachmentCandidates?: AttachmentContextCandidate[];
    maxAttachments?: number;
    maxChunks?: number;
    maxChars?: number;
    hasEphemeralVision?: boolean;
  },
): Promise<ResolvedAttachmentContext | null> {
  const maxAttachments = input.maxAttachments ?? DEFAULT_MAX_ATTACHMENTS;
  const maxChunks = input.maxChunks ?? DEFAULT_MAX_CHUNKS;
  const maxChars = input.maxChars ?? DEFAULT_MAX_CHARS;
  const requestCarrier = extractAttachmentMetadataCarrier(input.metadata);
  const requestCandidates = await rankCandidatesForPromptWithEmbeddings(
    input.prompt,
    await buildPreparedCandidatesWithCache(store, input.metadata, "request"),
    maxChunks,
    maxChars,
  );
  const sessionCandidates = !requestCarrier
    ? await rankCandidatesForPromptWithEmbeddings(
        input.prompt,
        await extractSessionCandidatesWithCache(store, input.sessionAttachmentCandidates),
        maxChunks,
        maxChars,
      )
    : [];

  const context = resolveAttachmentContextFromCandidates({
    prompt: input.prompt,
    requestCarrier,
    requestCandidates,
    sessionCandidates,
    maxAttachments,
    maxChunks,
    maxChars,
    recoveredVisionBlocks: !requestCarrier && promptReferencesSessionVisual(input.prompt)
      ? collectSessionVisionBlocks(input.sessionAttachmentCandidates)
      : [],
    hasEphemeralVision: input.hasEphemeralVision,
  });
  return context;
}
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

function readStringMulti(record: Record<string, unknown> | null, keys: string[]): string | null {
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
    readStringMulti(metadata, ["chunkKind", "blockType", "type", "kind"]) ??
    readStringMulti(chunkMetadata, ["chunkKind", "blockType", "type", "kind"]) ??
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

function buildInsightPromptBlock(input: {
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
    promptBlock: buildInsightPromptBlock({ context, tables, visuals, warnings }),
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
