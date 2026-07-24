export type ComposerAttachment = {
  id: string;
  fileName: string;
  mimeType: string;
  sizeBytes: number;
  sha256: string;
  kind: 'text' | 'image' | 'binary';
  textPreview?: string;
  textTruncated?: boolean;
  warning?: string;
};

export type ComposerAttachmentPayload = {
  attachments: Array<Record<string, unknown>>;
  promptSuffix: string;
};

const MAX_FILES = 8;
const MAX_TEXT_PREVIEW_CHARS = 12_000;
const MAX_CHUNK_CHARS = 1_200;
const MAX_CHUNKS = 8;
const TEXT_MIME_PATTERN = /^(text\/|application\/(json|xml|csv|yaml|x-yaml|toml|javascript|typescript))/i;
const TEXT_EXTENSION_PATTERN = /\.(txt|md|markdown|json|csv|tsv|xml|yaml|yml|toml|js|jsx|ts|tsx|css|html|svg|py|rb|go|rs|java|kt|swift|dart|sql|log)$/i;

function bytesToHex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function stableFallbackHash(parts: string[]): string {
  let hash = 0x811c9dc5;
  for (const part of parts.join('\0')) {
    hash ^= part.charCodeAt(0);
    hash = Math.imul(hash, 0x01000193);
  }
  return `web-fnv-${(hash >>> 0).toString(16).padStart(8, '0')}`;
}

async function sha256(file: File): Promise<string> {
  if (!globalThis.crypto?.subtle) return stableFallbackHash([file.name, String(file.size), String(file.lastModified)]);
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return bytesToHex(digest);
}

function normalizeMime(file: File): string {
  return file.type || (TEXT_EXTENSION_PATTERN.test(file.name) ? 'text/plain' : 'application/octet-stream');
}

function attachmentKind(file: File, mimeType: string): ComposerAttachment['kind'] {
  if (mimeType.startsWith('image/')) return 'image';
  if (TEXT_MIME_PATTERN.test(mimeType) || TEXT_EXTENSION_PATTERN.test(file.name)) return 'text';
  return 'binary';
}

function boundedText(value: string, limit = MAX_TEXT_PREVIEW_CHARS): { text: string; truncated: boolean } {
  const normalized = value.replace(/\u0000/g, '').trim();
  if (normalized.length <= limit) return { text: normalized, truncated: false };
  return { text: normalized.slice(0, limit).trimEnd(), truncated: true };
}

function chunksFor(text: string, documentId: string, mimeType: string, sha: string): Array<Record<string, unknown>> {
  const chunks: Array<Record<string, unknown>> = [];
  for (let index = 0; index < MAX_CHUNKS && index * MAX_CHUNK_CHARS < text.length; index += 1) {
    const chunkText = text.slice(index * MAX_CHUNK_CHARS, (index + 1) * MAX_CHUNK_CHARS).trim();
    if (!chunkText) continue;
    chunks.push({
      text: chunkText,
      pageNumber: 1,
      index,
      chunkId: `${documentId}-chunk-${index}`,
      documentId,
      position: index,
      extractionMethod: 'web_file_api_text',
      sourceHash: sha,
      mimeType,
    });
  }
  return chunks;
}

async function fileTextPreview(file: File, kind: ComposerAttachment['kind']): Promise<{ text?: string; truncated?: boolean; warning?: string }> {
  if (kind !== 'text') {
    return { warning: kind === 'image' ? 'Image metadata is attached; raw image bytes are not uploaded from web.' : 'Binary metadata is attached; raw file bytes are not uploaded.' };
  }
  try {
    const slice = file.slice(0, Math.min(file.size, 256_000));
    const { text, truncated } = boundedText(await slice.text());
    return { text, truncated: truncated || file.size > 256_000 };
  } catch {
    return { warning: 'File text could not be read in the browser.' };
  }
}

export async function buildComposerAttachments(files: FileList | File[]): Promise<ComposerAttachment[]> {
  const selected = Array.from(files).slice(0, MAX_FILES);
  const attachments: ComposerAttachment[] = [];
  for (const file of selected) {
    const mimeType = normalizeMime(file);
    const kind = attachmentKind(file, mimeType);
    const [hash, preview] = await Promise.all([sha256(file), fileTextPreview(file, kind)]);
    attachments.push({
      id: `web_att_${hash.slice(0, 24)}`,
      fileName: file.name || 'attachment',
      mimeType,
      sizeBytes: file.size,
      sha256: hash,
      kind,
      textPreview: preview.text,
      textTruncated: preview.truncated,
      warning: preview.warning,
    });
  }
  return attachments;
}

export function attachmentPromptLabel(attachments: ComposerAttachment[]): string {
  if (!attachments.length) return '';
  return attachments.map((attachment) => `- ${attachment.fileName} (${attachment.mimeType}, ${attachment.sizeBytes} bytes)`).join('\n');
}

export function buildAttachmentPayload(attachments: ComposerAttachment[]): ComposerAttachmentPayload {
  const manifests = attachments.map((attachment) => {
    const base = {
      documentId: attachment.id,
      sourceType: 'web_file',
      fileName: attachment.fileName,
      name: attachment.fileName,
      mimeType: attachment.mimeType,
      sizeBytes: attachment.sizeBytes,
      sha256: attachment.sha256,
      processingState: attachment.textPreview ? 'deep_ready' : 'fast_ready',
      raw_file_uploaded: false,
      data_origin: 'local_derived',
      privacy_level: 'local_derived',
      attachmentContractVersion: 'web.attachments.v1',
      summary: attachment.warning || (attachment.textPreview ? `Browser-derived text preview for ${attachment.fileName}` : undefined),
      intentHints: {
        documentKind: attachment.kind,
        extractionMethod: attachment.textPreview ? 'web_file_api_text' : 'metadata_only',
        semanticEditReady: attachment.kind === 'text',
      },
      renderHints: {
        preferredFormat: attachment.kind === 'image' ? 'image' : 'document',
        supportsMobileLocal: false,
        exactLayoutPreserved: false,
      },
    };
    if (!attachment.textPreview) {
      return {
        ...base,
        hasReadableText: false,
        clientAttachments: attachment.kind === 'image'
          ? [{ attachmentType: 'image', imageId: attachment.id, mimeType: attachment.mimeType, fileName: attachment.fileName }]
          : undefined,
      };
    }
    const chunks = chunksFor(attachment.textPreview, attachment.id, attachment.mimeType, attachment.sha256);
    const compactDocument = {
      documentId: attachment.id,
      sourceType: 'web_file',
      fileName: attachment.fileName,
      mimeType: attachment.mimeType,
      sizeBytes: attachment.sizeBytes,
      sha256: attachment.sha256,
      pageCount: 1,
      confidence: 0.8,
      extractionMethod: 'web_file_api_text',
      chunkCount: chunks.length,
      raw_file_uploaded: false,
      data_origin: 'local_derived',
      privacy_level: 'local_derived',
    };
    const documentEnvelope = {
      id: attachment.id,
      sourceHash: attachment.sha256,
      mimeType: attachment.mimeType,
      page: 1,
      confidence: 0.8,
      blocks: chunks.map((chunk, index) => ({
        id: `${attachment.id}-block-${index}`,
        type: 'text',
        sourceHash: attachment.sha256,
        mimeType: attachment.mimeType,
        text: String(chunk.text || ''),
        page: 1,
        confidence: 0.8,
      })),
      metadata: compactDocument,
    };
    const documentAnalysis = {
      documentId: attachment.id,
      sourceType: 'web_file',
      fileName: attachment.fileName,
      mimeType: attachment.mimeType,
      sizeBytes: attachment.sizeBytes,
      sha256: attachment.sha256,
      extractedText: attachment.textPreview,
      textPreview: attachment.textPreview,
      textTruncated: attachment.textTruncated === true,
      chunks,
      metadata: {
        ...compactDocument,
        textLength: attachment.textPreview.length,
        textTruncated: attachment.textTruncated === true,
      },
      raw_file_uploaded: false,
      data_origin: 'local_derived',
      privacy_level: 'local_derived',
    };
    return {
      ...base,
      fastPreview: {
        textPreview: attachment.textPreview.slice(0, 4_000),
        textTruncated: attachment.textPreview.length > 4_000 || attachment.textTruncated === true,
        chunks: chunks.slice(0, 4),
        chunkCount: chunks.length,
        includedChunkCount: Math.min(chunks.length, 4),
      },
      deepContext: {
        document_analysis: documentAnalysis,
        compactDocument,
        documentEnvelope,
      },
      document_analysis: documentAnalysis,
      compactDocument,
      documentEnvelope,
      hasReadableText: true,
      textPreview: attachment.textPreview.slice(0, 4_000),
      contentPreview: attachment.textPreview.slice(0, 4_000),
    };
  });
  const readable = attachments.filter((attachment) => attachment.textPreview);
  const promptSuffix = attachments.length
    ? [
        '\n\nAttached files:',
        attachmentPromptLabel(attachments),
        ...readable.map((attachment) => `\nReadable preview from ${attachment.fileName}:\n${attachment.textPreview}`),
      ].join('\n')
    : '';
  return { attachments: manifests, promptSuffix };
}
