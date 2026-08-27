import {
  isLikelyPureDocumentExportPrompt,
  isMobileLocalExportMode,
} from "./mobile-local-export.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

type AttachmentIntentInput = {
  prompt: string;
  requestMetadata?: Record<string, unknown>;
  attachmentContext?: { used?: boolean } | null;
};

function readMetadataRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readMetadataBoolean(
  record: Record<string, unknown> | null,
  key: string,
): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function readMetadataString(
  record: Record<string, unknown> | null,
  key: string,
): string {
  const value = record?.[key];
  return typeof value === "string" ? compactText(value).toLowerCase() : "";
}

export type AttachmentIntentMode =
  | "answer"
  | "analyze"
  | "semantic_edit"
  | "export";

export type AttachmentIntentSpec = {
  mode: AttachmentIntentMode;
  outputFormat:
    | "pdf"
    | "docx"
    | "xlsx"
    | "svg"
    | "png"
    | "jpg"
    | "webp"
    | "unknown";
  preserveNumbers: boolean;
  preserveUserPhrases: boolean;
  requiresStructuredDocument: boolean;
};

export function buildResolvedAttachmentIntentPromptBlock(
  input: AttachmentIntentInput,
): string | null {
  if (
    !input.attachmentContext?.used &&
    !isMobileLocalExportMode(input.requestMetadata)
  ) {
    return null;
  }

  const spec = resolveAttachmentIntentSpec(input);
  const metadata = readMetadataRecord(input.requestMetadata);
  const contentSource = readMetadataString(metadata, "artifactContentSource");
  const exportIntent = readMetadataString(metadata, "documentExportIntent");
  const sourceDirective = input.attachmentContext?.used
    ? "- content_authority: use the current attachment context as the only primary document source; never substitute a previous assistant reply, greeting, loading message, rolling summary, or memory for attachment content"
    : contentSource === "previous_assistant" ||
        exportIntent === "existing_content_export"
      ? "- content_authority: export the most recent completed assistant answer only; ignore pending/loading acknowledgements"
      : "- content_authority: generate the requested content in this turn before exporting; never reuse an unrelated previous assistant answer";
  return [
    "Resolved attachment/document intent:",
    `- mode: ${spec.mode}`,
    `- output_format: ${spec.outputFormat}`,
    `- preserve_numbers: ${spec.preserveNumbers}`,
    `- preserve_user_phrases: ${spec.preserveUserPhrases}`,
    `- requires_structured_document: ${spec.requiresStructuredDocument}`,
    sourceDirective,
    "- completion_contract: emit the complete requested typed document content; never emit preparation/status prose as document content",
    "Follow this resolved intent unless the user clearly changes the goal.",
  ].join("\n");
}

export function resolveAttachmentIntentMode(
  input: AttachmentIntentInput,
): AttachmentIntentMode {
  const metadata = readMetadataRecord(input.requestMetadata);
  const normalizedPrompt = compactText(input.prompt).toLowerCase();

  if (
    isMobileLocalExportMode(input.requestMetadata) ||
    isLikelyPureDocumentExportPrompt(normalizedPrompt)
  ) {
    return "export";
  }

  if (
    readMetadataBoolean(metadata, "documentEditRequested") === true ||
    /\b(düzenle|duzenle|değiştir|degistir|güncelle|guncelle|revize|rewrite|edit|replace|çıkar|cikar|remove)\b/i.test(
      normalizedPrompt,
    )
  ) {
    return "semantic_edit";
  }

  if (
    /\b(özetle|ozetle|analiz et|incele|yorumla|karşılaştır|karsilastir|çıkar|cikar|çevir|cevir|translate|summarize|analyze|analyse)\b/i.test(
      normalizedPrompt,
    )
  ) {
    return "analyze";
  }

  return "answer";
}

export function resolveAttachmentIntentSpec(
  input: AttachmentIntentInput,
): AttachmentIntentSpec {
  const normalizedPrompt = compactText(input.prompt).toLowerCase();
  const mode = resolveAttachmentIntentMode(input);
  const outputFormat = resolveRequestedOutputFormat(input);
  const preserveNumbers =
    /\b(toplam|tutar|fiyat|ücret|ucret|tl|try|₺|usd|\$|eur|€|excel|xlsx|tablo|spreadsheet|csv)\b/i.test(
      normalizedPrompt,
    );
  const preserveUserPhrases =
    /(["“”].+?["“”]|\b(en\s+alt|altına|altina|footer|dipnot|imza|imzası|imzasi|yazsın|yazsin)\b)/i.test(
      input.prompt,
    );

  return {
    mode,
    outputFormat,
    preserveNumbers,
    preserveUserPhrases,
    requiresStructuredDocument:
      mode === "export" ||
      outputFormat === "pdf" ||
      outputFormat === "docx" ||
      outputFormat === "xlsx",
  };
}

function resolveRequestedOutputFormat(
  input: AttachmentIntentInput,
): AttachmentIntentSpec["outputFormat"] {
  const metadata = readMetadataRecord(input.requestMetadata);
  const explicit = compactText(
    metadata?.exportFormat ??
      metadata?.outputFormat ??
      metadata?.renderFormat ??
      metadata?.format,
  ).toLowerCase();
  const normalizedPrompt = compactText(input.prompt).toLowerCase();
  const source = `${explicit} ${normalizedPrompt}`;

  if (/\b(xlsx|excel|spreadsheet|csv)\b/i.test(source)) {
    return "xlsx";
  }
  if (/\b(docx|word|doc)\b/i.test(source)) {
    return "docx";
  }
  if (/\b(svg)\b/i.test(source)) {
    return "svg";
  }
  if (/\b(webp)\b/i.test(source)) {
    return "webp";
  }
  if (/\b(jpe?g|jpg)\b/i.test(source)) {
    return "jpg";
  }
  if (/\b(png|image|görsel|gorsel|resim)\b/i.test(source)) {
    return "png";
  }
  if (/\b(pdf|belge|doküman|dokuman|rapor)\b/i.test(source)) {
    return "pdf";
  }
  return "unknown";
}
