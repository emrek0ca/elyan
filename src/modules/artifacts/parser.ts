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
  const normalizeFormat = (value: string): string => {
    const format = value.toLowerCase();
    if (format === "word" || format === "doc") return "docx";
    if (format === "excel" || format === "spreadsheet" || format === "csv") {
      return "xlsx";
    }
    if (format === "table") return "table";
    return format;
  };
  return [
    ...new Set(
      (envelope?.desired_outputs ?? [])
        .filter((output) => artifactTypeForDesiredOutput(output) != null)
        .map((output) => normalizeFormat(output.format ?? output.kind))
        .filter(Boolean),
    ),
  ];
}

function requestedDesiredOutputs(
  envelope: UnderstandingEnvelope | null | undefined,
): ArtifactIntent["desiredOutputs"] {
  return (envelope?.desired_outputs ?? [])
    .filter((output) => artifactTypeForDesiredOutput(output) != null)
    .map((output) => ({
      kind: output.kind,
      format: output.format ?? null,
      target: output.target,
      confidence: output.confidence,
      constraints: [...output.constraints],
    }));
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
  // BELGE TESPİTİ — iki kusur düzeltildi (ölçüldü, canlı kod üzerinde):
  //
  // 1) `word` ve `docx` desende HİÇ YOKTU. Kullanıcının Word belgesi istemesinin
  //    en doğal yolu bu ("word belgesi yap", "bunu docx yap") ve hiçbir artefakt
  //    üretilmiyordu — üstelik anlama katmanı aynı tur için `format=docx,
  //    requiresArtifact=true, confidence=0.96` diyordu. İki katman çelişiyordu.
  //
  // 2) `\brapor\b` "raporunu" ile, `\bbelge\b` "belgesi" ile EŞLEŞMİYOR: ek
  //    geldiğinde sağ sınır oluşmuyor. Yani belge üretimi yalnız isim YALIN
  //    söylendiğinde çalışıyordu ("bir rapor hazırla" ✓ / "raporunu word
  //    belgesi yap" ✗) — doğal Türkçede kimse öyle konuşmuyor.
  //
  // Ek toleransı sınırlı (`\p{L}{0,6}`) ve "belgesel" bilinçli dışarıda:
  // belgesel bir film türü, belge isteği değil.
  if (
    /(?<!\p{L})(?:teklif\s+dosya\p{L}{0,6}|sözleşme\p{L}{0,6}|sozlesme\p{L}{0,6}|rapor\p{L}{0,6}|doküman\p{L}{0,6}|dokuman\p{L}{0,6}|belge(?!sel)\p{L}{0,6}|word|docx?)(?!\p{L})/iu.test(
      normalized,
    )
  ) {
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
    desiredOutputs:
      requestedDesiredOutputs(input.understandingEnvelope).length > 0
        ? requestedDesiredOutputs(input.understandingEnvelope)
        : type
          ? [
              {
                kind: type === "image_prompt" ? "image" : type,
                format: type === "image_prompt" ? "image" : type,
                target: type === "table" || type === "chart" ? "widget" : "artifact",
                confidence: source === "understanding_envelope" ? 0.9 : 0.82,
                constraints: [],
              },
            ]
          : [],
    requiresDesktopRuntime,
    ...(requiresDesktopRuntime
      ? { privateDataReason: "local_private_file_or_desktop_context_requested" }
      : {}),
  };
}
