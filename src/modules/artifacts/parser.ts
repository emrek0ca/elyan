import type {
  UnderstandingDesiredOutput,
  UnderstandingEnvelope,
} from "../../core/understanding/types.js";
import type { ArtifactIntent, ArtifactType } from "./types.js";
import { compactText, hasLocalPrivateDataRequest, readRecord, readString } from "./utils.js";

function artifactTypeForDesiredOutput(
  output: UnderstandingDesiredOutput,
): ArtifactType | null {
  const format = output.format?.toLowerCase() ?? "";
  if (output.kind === "pdf" || format === "pdf") return "pdf";
  if (output.kind === "docx" || format === "docx" || format === "doc") {
    return "document";
  }
  if (
    output.kind === "xlsx" ||
    output.kind === "table" ||
    format === "xlsx" ||
    format === "csv"
  ) {
    return "table";
  }
  if (output.kind === "chart") return "chart";
  if (output.kind === "svg" || format === "svg") return "svg";
  if (output.kind === "image") return "image_prompt";
  if (output.kind === "artifact") return "document";
  return null;
}

function outputKindFromEnvelope(
  envelope: UnderstandingEnvelope | null | undefined,
): ArtifactType | null {
  for (const output of envelope?.desired_outputs ?? []) {
    const type = artifactTypeForDesiredOutput(output);
    if (type) return type;
  }
  return null;
}

function requestedOutputKinds(
  envelope: UnderstandingEnvelope | null | undefined,
): string[] {
  return [
    ...new Set(
      (envelope?.desired_outputs ?? [])
        .filter((output) => artifactTypeForDesiredOutput(output) != null)
        .map((output) => output.kind),
    ),
  ];
}

function requestedFormats(
  envelope: UnderstandingEnvelope | null | undefined,
): string[] {
  return [
    ...new Set(
      (envelope?.desired_outputs ?? [])
        .filter((output) => artifactTypeForDesiredOutput(output) != null)
        .map((output) => output.format ?? output.kind)
        .filter(Boolean),
    ),
  ];
}

function detectArtifactType(text: string, metadata?: Record<string, unknown>, envelope?: UnderstandingEnvelope | null): ArtifactType | null {
  const metadataRecord = readRecord(metadata);
  const explicitType = readString(metadataRecord, "artifactType") ?? readString(metadataRecord, "artifact_type");
  if (
    explicitType === "text" ||
    explicitType === "table" ||
    explicitType === "chart" ||
    explicitType === "svg" ||
    explicitType === "pdf" ||
    explicitType === "document" ||
    explicitType === "image_prompt"
  ) {
    return explicitType;
  }

  const envelopeType = outputKindFromEnvelope(envelope);
  if (envelopeType) {
    return envelopeType;
  }

  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (/\b(app store|instagram|x|twitter|görsel|gorsel|image|video)\b.*\bprompt\b/i.test(normalized)) {
    return "image_prompt";
  }
  if (/\b(pdf|pdf'e|pdfe)\b/i.test(normalized)) {
    return "pdf";
  }
  if (/\b(svg)\b/i.test(normalized)) {
    return "svg";
  }
  if (/\b(grafik|grafiği|grafigi|chart|çizelge|cizelge)\b/i.test(normalized)) {
    return "chart";
  }
  if (/\b(tablo|table|excel|xlsx)\b/i.test(normalized)) {
    return "table";
  }
  const hasMoneyValue =
    /(?:₺|\$|€)?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?\s*(?:tl|try|₺|usd|\$|eur|€)\b/i.test(normalized) ||
    /\b(?:tl|try|₺|usd|\$|eur|€)\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?/i.test(normalized);
  if (
    /\b(fatura|makbuz|fiş|fis|receipt|invoice)\b/i.test(normalized) ||
    (hasMoneyValue && /\b(genel\s+toplam|toplam|tl|try|₺|usd|\$|eur|€)\b/i.test(normalized))
  ) {
    return "pdf";
  }
  if (/\b(teklif\s+dosyası|teklif\s+dosyasi|sözleşme|sozlesme|rapor|doküman|dokuman|belge)\b/i.test(normalized)) {
    return "document";
  }
  if (/\b(profesyonel\s+(?:mesaj|metin)|metni\s+(?:daha\s+)?profesyonel|sadece\s+metin|mail\s+taslağı|email\s+draft)\b/i.test(normalized)) {
    return "text";
  }
  return null;
}

export function parseArtifactIntent(input: {
  userRequest: string;
  metadata?: Record<string, unknown>;
  understandingEnvelope?: UnderstandingEnvelope | null;
}): ArtifactIntent {
  const text = compactText(input.userRequest);
  const requiresDesktopRuntime =
    hasLocalPrivateDataRequest(text) ||
    input.understandingEnvelope?.risk.local_private === true ||
    input.understandingEnvelope?.required_capabilities.some(
      (capability) => capability.executionSurface === "desktop",
    ) === true;
  const type = detectArtifactType(text, input.metadata, input.understandingEnvelope);
  const envelopeType = outputKindFromEnvelope(input.understandingEnvelope);
  const source = envelopeType
    ? "understanding_envelope"
    : readString(readRecord(input.metadata), "artifactType") ||
        readString(readRecord(input.metadata), "artifact_type")
      ? "metadata"
      : "typed_extractor";

  return {
    type,
    confidence: type ? (source === "understanding_envelope" ? 0.9 : 0.82) : 0,
    intent: type ? `${type}.create` : "none",
    source,
    requestedOutputKinds:
      requestedOutputKinds(input.understandingEnvelope).length > 0
        ? requestedOutputKinds(input.understandingEnvelope)
        : type
          ? [type]
          : [],
    requestedFormats:
      requestedFormats(input.understandingEnvelope).length > 0
        ? requestedFormats(input.understandingEnvelope)
        : type
          ? [type === "image_prompt" ? "image" : type]
          : [],
    requiresDesktopRuntime,
    ...(requiresDesktopRuntime
      ? { privateDataReason: "local_private_file_or_desktop_context_requested" }
      : {}),
  };
}
