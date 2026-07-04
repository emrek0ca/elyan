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

export function buildResolvedAttachmentIntentPromptBlock(
  input: AttachmentIntentInput,
): string | null {
  if (
    !input.attachmentContext?.used &&
    !isMobileLocalExportMode(input.requestMetadata)
  ) {
    return null;
  }

  return `Resolved intent: ${resolveAttachmentIntentMode(input)}. Follow that mode unless the user clearly changes the goal.`;
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
