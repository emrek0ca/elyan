import {
  isLikelyPureDocumentExportPrompt,
  isMobileLocalExportMode,
} from "./mobile-local-export.js";

type AttachmentIntentInput = {
  prompt: string;
  requestMetadata?: Record<string, unknown>;
  attachmentContext?: { used?: boolean } | null;
};

function compactText(value: unknown): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

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
  return [
    "Resolved attachment/document intent:",
    `- mode: ${spec.mode}`,
    `- output_format: ${spec.outputFormat}`,
    `- preserve_numbers: ${spec.preserveNumbers}`,
    `- preserve_user_phrases: ${spec.preserveUserPhrases}`,
    `- requires_structured_document: ${spec.requiresStructuredDocument}`,
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
