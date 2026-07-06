import type { UnderstandingEnvelope } from "./types.js";
import {
  findUnderstandingEnvelope,
  hasRenderableDesiredOutput,
  preferredFormatFromUnderstandingEnvelope,
} from "./understanding-envelope.js";

export type RenderRecipeFormat =
  "pdf" | "png" | "jpg" | "jpeg" | "webp" | "svg" | "docx" | "xlsx";
export type RenderRecipeTarget = "mobile" | "desktop";
export type RenderRecipeOutputType =
  "document_render_recipe" | "image_render_recipe";

export type RenderRecipeBlock = {
  type: "title" | "heading" | "paragraph" | "bullet" | "list" | "table";
  text: string;
  level?: number;
  order?: number;
  items?: string[];
  tableHeaders?: string[];
  tableRows?: string[][];
};

export type RenderRecipeLayout =
  | {
      kind: "document_page";
      pageSize: "A4" | "LETTER" | "DOCX";
      orientation: "portrait" | "landscape";
      marginsPt: {
        top: number;
        right: number;
        bottom: number;
        left: number;
      };
      columns: 1;
    }
  | {
      kind: "canvas";
      widthPx: number;
      heightPx: number;
      background: "paper" | "transparent";
      safeAreaPx: number;
    };

export type LocalRenderRecipe = {
  schema_version: "2026-06-mobile-render-recipe-v2";
  output_type: RenderRecipeOutputType;
  format: RenderRecipeFormat;
  mime_type: string;
  file_name: string;
  layout: RenderRecipeLayout;
  text_blocks: RenderRecipeBlock[];
  content_model: {
    title: string | null;
    language: "tr" | "en" | "mixed" | "unknown";
    plain_text: string;
    estimated_pages: number;
    block_count: number;
  };
  render_hints: {
    renderer: "mobile_local";
    priority: "interactive";
    paginate: boolean;
    allow_share: boolean;
    allow_print: boolean;
    vector_safe: boolean;
    fallback_format: "pdf" | "png";
  };
  assets_needed: string[];
  render_on: RenderRecipeTarget;
  metadata: Record<string, unknown>;
};

type DocumentIntentHints = {
  document_style: "formal" | "minimal" | "modern" | "standard";
  document_kind:
    "quote" | "invoice" | "receipt" | "report" | "letter" | "generic";
  footer_text?: string;
  signature_text?: string;
  layout_template: "business_document" | "plain_document" | "visual_canvas";
};

type ExtractedMoneyAmount = {
  raw: string;
  currency: "TRY" | "USD" | "EUR" | "unknown";
  label?: string;
};

type DocumentRequirementSpec = {
  output_format: RenderRecipeFormat;
  export_family: "document" | "spreadsheet" | "image";
  kind: DocumentIntentHints["document_kind"] | "spreadsheet";
  style: DocumentIntentHints["document_style"];
  layout_template:
    | DocumentIntentHints["layout_template"]
    | "spreadsheet_workbook";
  preserve_numbers: boolean;
  table_required: boolean;
  exact_text_required: boolean;
  must_include: string[];
  money_amounts: ExtractedMoneyAmount[];
  quality_checks: {
    preserve_numbers: boolean;
    preserve_user_phrases: boolean;
    no_assistant_chatter: boolean;
    preflight_required: boolean;
  };
  spreadsheet?: {
    sheet_name: string;
    suggested_columns: string[];
    include_totals: boolean;
  };
  footer_text?: string;
  signature_text?: string;
};

const IMAGE_EXPORT_PATTERNS = [
  /\b(görsel|gorsel|resim|image|png|jpg|jpeg|webp|svg|afiş|afis|poster|banner|kapak|thumbnail|screenshot)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b/i,
  /\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b.*\b(görsel|gorsel|resim|image|png|jpg|jpeg|webp|svg|afiş|afis|poster|banner|kapak|thumbnail|screenshot)\b/i,
];

const DOCUMENT_EXPORT_PATTERNS = [
  /\b(pdf|docx|word|belge|doküman|dokuman|rapor|sunum|xlsx|excel|spreadsheet|csv|tablo)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b/i,
  /\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b.*\b(pdf|docx|word|belge|doküman|dokuman|rapor|sunum|xlsx|excel|spreadsheet|csv|tablo)\b/i,
];

const DOCUMENT_WORD_EXPORT_PATTERNS = [
  /\b(word|docx|doc)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b/i,
  /\b(pdf)\b.*\b(ver|hazırla|hazirla|oluştur|olustur|dönüştür|donustur|çevir|cevir|kaydet|düzenle|duzenle|yap|üret|uret)\b/i,
  /\b(metni|yazıyı|yaziyi|içeriği|icerigi|notları|notlari|özeti|ozeti)\b.*\b(pdf|word|docx|doc|belge)\b/i,
  /\b(pdf|word|docx|doc|belge)\b.*\b(metni|yazıyı|yaziyi|içeriği|icerigi|notları|notlari|özeti|ozeti|taslağı|taslagi)\b/i,
];

function compactText(value: string): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function slugifyFileName(value: string): string {
  const slug = compactText(value)
    .toLocaleLowerCase("tr-TR")
    .replace(/[^a-z0-9çğıöşü_-]+/gi, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 72);
  return slug || "elyan-cikti";
}

function mimeTypeForFormat(format: RenderRecipeFormat): string {
  switch (format) {
    case "pdf":
      return "application/pdf";
    case "svg":
      return "image/svg+xml";
    case "png":
      return "image/png";
    case "jpg":
    case "jpeg":
      return "image/jpeg";
    case "webp":
      return "image/webp";
    case "docx":
      return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    case "xlsx":
      return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  }
}

function detectLanguage(
  value: string,
): LocalRenderRecipe["content_model"]["language"] {
  const compact = compactText(value);
  if (!compact) {
    return "unknown";
  }
  const lowered = compact.toLocaleLowerCase("tr-TR");
  const hasTurkish =
    /[çğıöşü]/i.test(compact) ||
    /\b(selam|merhaba|ve|ile|için|bunu|belge|görsel|özet)\b/i.test(lowered);
  const hasEnglish =
    /\b(the|and|for|with|document|image|summary|report)\b/i.test(lowered);
  if (hasTurkish && hasEnglish) {
    return "mixed";
  }
  if (hasTurkish) {
    return "tr";
  }
  if (hasEnglish) {
    return "en";
  }
  return "unknown";
}

function normalizeValue(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s.-]+/g, "_");
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(
  record: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readArray(
  record: Record<string, unknown> | null,
  key: string,
): unknown[] {
  const value = record?.[key];
  return Array.isArray(value) ? value : [];
}

function readBoolean(
  record: Record<string, unknown> | null,
  key: string,
): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function isRenderRecipeFormat(value: string | null): value is RenderRecipeFormat {
  return (
    value === "pdf" ||
    value === "png" ||
    value === "jpg" ||
    value === "jpeg" ||
    value === "webp" ||
    value === "svg" ||
    value === "docx" ||
    value === "xlsx"
  );
}

function readEnvelopeConstraint(
  envelope: UnderstandingEnvelope | null | undefined,
  kind: string,
): unknown {
  return envelope?.constraints.find((constraint) => constraint.kind === kind)?.value;
}

function mergeEnvelopeRenderMetadata(
  metadata: Record<string, unknown>,
  envelope: UnderstandingEnvelope | null,
): Record<string, unknown> {
  if (!envelope) {
    return metadata;
  }

  const footerText = readEnvelopeConstraint(envelope, "footer_text");
  const signatureText = readEnvelopeConstraint(envelope, "signature_text");
  const documentStyle = readEnvelopeConstraint(envelope, "document_style");
  const documentKind = readEnvelopeConstraint(envelope, "document_kind");
  const layoutTemplate = readEnvelopeConstraint(envelope, "layout_template");
  const sheetName = readEnvelopeConstraint(envelope, "sheet_name");
  const columns = readEnvelopeConstraint(envelope, "columns");
  const includeTotals = readEnvelopeConstraint(envelope, "include_totals");
  const envelopeFormat = preferredFormatFromUnderstandingEnvelope(envelope);

  const derived: Record<string, unknown> = {
    understanding_envelope_source: envelope.source,
    understanding_envelope_confidence: envelope.confidence,
    understanding_desired_outputs: envelope.desired_outputs.map((output) => output.kind),
    understanding_constraint_count: envelope.constraints.length,
    ...(envelopeFormat ? { outputFormat: envelopeFormat } : {}),
    ...(typeof footerText === "string" && footerText.trim()
      ? { footer_text: footerText }
      : {}),
    ...(typeof signatureText === "string" && signatureText.trim()
      ? { signature_text: signatureText }
      : {}),
    ...(typeof documentStyle === "string" && documentStyle.trim()
      ? { document_style: documentStyle }
      : {}),
    ...(typeof documentKind === "string" && documentKind.trim()
      ? { document_kind: documentKind }
      : {}),
    ...(typeof layoutTemplate === "string" && layoutTemplate.trim()
      ? { layout_template: layoutTemplate }
      : {}),
    ...(typeof sheetName === "string" && sheetName.trim()
      ? { title: sheetName, sheet_name: sheetName }
      : {}),
    ...(Array.isArray(columns) && columns.every((item) => typeof item === "string")
      ? { spreadsheet_columns: columns }
      : {}),
    ...(typeof includeTotals === "boolean"
      ? { includeTotals, include_totals: includeTotals }
      : {}),
  };

  return {
    ...derived,
    ...metadata,
  };
}

function detectFormat(
  prompt: string,
  metadata?: Record<string, unknown>,
): RenderRecipeFormat | null {
  const metadataRecord = readRecord(metadata);
  const explicitFormat = normalizeValue(
    readString(metadataRecord, "exportFormat") ??
      readString(metadataRecord, "outputFormat") ??
      readString(metadataRecord, "renderFormat") ??
      readString(metadataRecord, "format"),
  );

  if (explicitFormat === "png") {
    return "png";
  }
  if (explicitFormat === "jpg") {
    return "jpg";
  }
  if (explicitFormat === "jpeg") {
    return "jpeg";
  }
  if (explicitFormat === "webp") {
    return "webp";
  }
  if (explicitFormat === "svg") {
    return "svg";
  }
  if (
    explicitFormat === "docx" ||
    explicitFormat === "word" ||
    explicitFormat === "doc"
  ) {
    return "docx";
  }
  if (
    explicitFormat === "xlsx" ||
    explicitFormat === "excel" ||
    explicitFormat === "spreadsheet" ||
    explicitFormat === "csv"
  ) {
    return "xlsx";
  }
  if (explicitFormat === "pdf") {
    return "pdf";
  }

  const normalizedPrompt = compactText(prompt).toLowerCase();
  if (!normalizedPrompt) {
    return null;
  }

  if (/\b(svg)\b/i.test(normalizedPrompt)) {
    return "svg";
  }
  if (/\b(webp)\b/i.test(normalizedPrompt)) {
    return "webp";
  }
  if (/\b(jpe?g|jpg)\b/i.test(normalizedPrompt)) {
    return /\b(jpeg)\b/i.test(normalizedPrompt) ? "jpeg" : "jpg";
  }
  if (/\b(png)\b/i.test(normalizedPrompt)) {
    return "png";
  }
  if (/\b(xlsx|excel|spreadsheet|csv)\b/i.test(normalizedPrompt)) {
    return "xlsx";
  }

  if (IMAGE_EXPORT_PATTERNS.some((pattern) => pattern.test(normalizedPrompt))) {
    return "png";
  }

  if (
    DOCUMENT_WORD_EXPORT_PATTERNS.some((pattern) =>
      pattern.test(normalizedPrompt),
    )
  ) {
    if (/\b(word|docx|doc)\b/i.test(normalizedPrompt)) {
      return "docx";
    }
    if (/\b(xlsx|excel|spreadsheet|csv)\b/i.test(normalizedPrompt)) {
      return "xlsx";
    }
    return "pdf";
  }

  if (
    DOCUMENT_EXPORT_PATTERNS.some((pattern) => pattern.test(normalizedPrompt))
  ) {
    if (/\b(xlsx|excel|spreadsheet|csv)\b/i.test(normalizedPrompt)) {
      return "xlsx";
    }
    return "pdf";
  }

  return null;
}

function detectRenderTarget(
  metadata?: Record<string, unknown>,
): RenderRecipeTarget {
  const metadataRecord = readRecord(metadata);
  const renderTarget = normalizeValue(
    readString(metadataRecord, "renderOn") ??
      readString(metadataRecord, "renderTarget") ??
      readString(metadataRecord, "target") ??
      readString(metadataRecord, "device"),
  );

  return renderTarget === "desktop" ? "desktop" : "mobile";
}

function collectAssetsNeeded(metadata?: Record<string, unknown>): string[] {
  const metadataRecord = readRecord(metadata);
  const candidates = [
    ...readArray(metadataRecord, "assetsNeeded"),
    ...readArray(metadataRecord, "assets_needed"),
    ...readArray(metadataRecord, "attachments"),
    ...readArray(metadataRecord, "assetRefs"),
    ...readArray(metadataRecord, "asset_refs"),
  ];

  const collected = candidates
    .map((candidate) => {
      if (typeof candidate === "string") {
        return candidate.trim();
      }
      if (
        !candidate ||
        typeof candidate !== "object" ||
        Array.isArray(candidate)
      ) {
        return "";
      }
      const record = candidate as Record<string, unknown>;
      return (
        readString(record, "assetId") ??
        readString(record, "id") ??
        readString(record, "name") ??
        readString(record, "contentHash") ??
        readString(record, "storageKey") ??
        readString(record, "uri") ??
        ""
      );
    })
    .filter(Boolean);

  return [...new Set(collected)].slice(0, 12);
}

function cleanInlineIntentText(value: string): string {
  return cleanMarkdownText(value)
    .replace(/^["'“”‘’]+|["'“”‘’.,;:\s]+$/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 160);
}

function extractTrailingRequestedText(
  prompt: string,
  patterns: RegExp[],
): string | null {
  for (const pattern of patterns) {
    const match = pattern.exec(prompt);
    if (!match) {
      continue;
    }
    const candidate = cleanInlineIntentText(match[1] ?? "");
    if (candidate.length >= 2) {
      return candidate;
    }
  }
  return null;
}

function detectDocumentIntentHints(
  prompt: string,
  metadata: Record<string, unknown>,
  format: RenderRecipeFormat,
): DocumentIntentHints {
  const normalizedPrompt = compactText(prompt).toLocaleLowerCase("tr-TR");
  const explicitStyle = normalizeValue(
    readString(metadata, "document_style") ??
      readString(metadata, "documentStyle") ??
      readString(metadata, "style") ??
      readString(metadata, "tone"),
  );
  const explicitKind = normalizeValue(
    readString(metadata, "document_kind") ??
      readString(metadata, "documentKind") ??
      readString(metadata, "template") ??
      readString(metadata, "layout_template"),
  );

  const document_style: DocumentIntentHints["document_style"] =
    explicitStyle === "formal" ||
    explicitStyle === "resmi" ||
    /\b(resmi|kurumsal|profesyonel|teklif|fatura|makbuz)\b/i.test(
      normalizedPrompt,
    )
      ? "formal"
      : explicitStyle === "minimal" ||
          /\b(minimal|sade|temiz)\b/i.test(normalizedPrompt)
        ? "minimal"
        : explicitStyle === "modern" ||
            /\b(modern|şık|sik|tasarımlı|tasarimli)\b/i.test(normalizedPrompt)
          ? "modern"
          : "standard";

  const document_kind: DocumentIntentHints["document_kind"] =
    explicitKind === "quote" ||
    explicitKind === "teklif" ||
    /\b(teklif|proforma)\b/i.test(normalizedPrompt)
      ? "quote"
      : explicitKind === "invoice" ||
          explicitKind === "fatura" ||
          /\b(fatura)\b/i.test(normalizedPrompt)
        ? "invoice"
        : explicitKind === "receipt" ||
            explicitKind === "makbuz" ||
            /\b(makbuz|fiş|fis)\b/i.test(normalizedPrompt)
          ? "receipt"
          : explicitKind === "report" ||
              explicitKind === "rapor" ||
              /\b(rapor|analiz)\b/i.test(normalizedPrompt)
            ? "report"
            : explicitKind === "letter" ||
                explicitKind === "dilekce" ||
                /\b(dilekçe|dilekce|mektup)\b/i.test(normalizedPrompt)
              ? "letter"
              : "generic";

  const footer_text =
    readString(metadata, "footer_text") ??
    readString(metadata, "footerText") ??
    extractTrailingRequestedText(prompt, [
      /(?:en\s+alt(?:\s+kısmında|\s+kisminda)?|alt(?:ına|ina|ta|ta\s+kısmında|ta\s+kisminda))\s+(.+?)\s+(?:yazsın|yazsin|yaz|olsun|ekle)(?:\b|$)/i,
      /(?:footer|dipnot)\s+(?:olarak\s+)?(.+?)\s+(?:yazsın|yazsin|yaz|olsun|ekle)(?:\b|$)/i,
    ]) ??
    undefined;

  const signature_text =
    readString(metadata, "signature_text") ??
    readString(metadata, "signatureText") ??
    extractTrailingRequestedText(prompt, [
      /(?:imza|imzası|imzasi|signed\s+by)\s*(?:olarak\s+)?(.+?)(?:\s+(?:yazsın|yazsin|yaz|olsun|ekle))?(?:\b|$)/i,
    ]) ??
    undefined;

  return {
    document_style,
    document_kind,
    ...(footer_text ? { footer_text } : {}),
    ...(signature_text ? { signature_text } : {}),
    layout_template:
      format === "png" ||
      format === "jpg" ||
      format === "jpeg" ||
      format === "webp" ||
      format === "svg"
        ? "visual_canvas"
        : document_kind === "generic" && document_style === "standard"
          ? "plain_document"
          : "business_document",
  };
}

function exportFamilyForFormat(
  format: RenderRecipeFormat,
  outputType: RenderRecipeOutputType,
): DocumentRequirementSpec["export_family"] {
  if (format === "xlsx") {
    return "spreadsheet";
  }
  if (outputType === "image_render_recipe") {
    return "image";
  }
  return "document";
}

function mapCurrency(value: string | undefined): ExtractedMoneyAmount["currency"] {
  const normalized = normalizeValue(value ?? "");
  if (normalized === "tl" || normalized === "try" || normalized === "₺") {
    return "TRY";
  }
  if (normalized === "usd" || normalized === "$") {
    return "USD";
  }
  if (normalized === "eur" || normalized === "€") {
    return "EUR";
  }
  return "unknown";
}

function extractMoneyAmounts(text: string): ExtractedMoneyAmount[] {
  const normalized = String(text ?? "");
  const matches: ExtractedMoneyAmount[] = [];
  const pattern =
    /(?:(?<label>[\p{L}\p{N}\s%.,/()-]{2,48}?)[=:]\s*)?(?<raw>(?:₺|\$|€)?\s*\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?<currency>tl|try|₺|usd|\$|eur|€)\b/giu;

  for (const match of normalized.matchAll(pattern)) {
    const raw = compactText(match.groups?.raw ?? match[0] ?? "");
    const currencyRaw = match.groups?.currency ?? "";
    const label = cleanInlineIntentText(match.groups?.label ?? "");
    if (!raw) {
      continue;
    }
    matches.push({
      raw: compactText(`${raw}${currencyRaw ? ` ${currencyRaw}` : ""}`),
      currency: mapCurrency(currencyRaw),
      ...(label ? { label } : {}),
    });
    if (matches.length >= 12) {
      break;
    }
  }

  const seen = new Set<string>();
  return matches.filter((item) => {
    const key = `${item.raw}:${item.currency}:${item.label ?? ""}`.toLocaleLowerCase(
      "tr-TR",
    );
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function hasTableBlock(blocks: RenderRecipeBlock[]): boolean {
  return blocks.some((block) => block.type === "table");
}

function detectSpreadsheetColumns(blocks: RenderRecipeBlock[]): string[] {
  const table = blocks.find(
    (block) => block.type === "table" && (block.tableHeaders?.length ?? 0) > 0,
  );
  if (table?.tableHeaders?.length) {
    return table.tableHeaders.slice(0, 12);
  }
  return ["Kalem", "Açıklama", "Tutar"];
}

function buildRequiredMarkers(input: {
  title: string | null;
  plainTextSource: string;
  documentIntentHints: DocumentIntentHints;
  moneyAmounts: ExtractedMoneyAmount[];
}): string[] {
  const markers = [
    input.title,
    compactText(input.plainTextSource).slice(0, 240),
    input.documentIntentHints.footer_text ?? null,
    input.documentIntentHints.signature_text ?? null,
    ...input.moneyAmounts.map((amount) => amount.raw),
  ].filter(
    (value): value is string =>
      typeof value === "string" && compactText(value).length > 0,
  );

  const seen = new Set<string>();
  return markers
    .map((marker) => compactText(marker).slice(0, 240))
    .filter((marker) => {
      const key = marker.toLocaleLowerCase("tr-TR");
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    })
    .slice(0, 16);
}

function buildDocumentRequirementSpec(input: {
  format: RenderRecipeFormat;
  outputType: RenderRecipeOutputType;
  prompt: string;
  plainTextSource: string;
  title: string | null;
  textBlocks: RenderRecipeBlock[];
  documentIntentHints: DocumentIntentHints;
  metadata: Record<string, unknown>;
}): DocumentRequirementSpec {
  const promptAndBody = `${input.prompt}\n${input.plainTextSource}`;
  const normalizedPrompt = compactText(input.prompt).toLocaleLowerCase("tr-TR");
  const moneyAmounts = extractMoneyAmounts(promptAndBody);
  const tableRequired =
    input.format === "xlsx" ||
    hasTableBlock(input.textBlocks) ||
    /\b(tablo|excel|xlsx|spreadsheet|csv|satır|sutun|sütun)\b/i.test(
      normalizedPrompt,
    );
  const exportFamily = exportFamilyForFormat(input.format, input.outputType);
  const mustInclude = buildRequiredMarkers({
    title: input.title,
    plainTextSource: input.plainTextSource,
    documentIntentHints: input.documentIntentHints,
    moneyAmounts,
  });
  const kind =
    input.format === "xlsx"
      ? "spreadsheet"
      : input.documentIntentHints.document_kind;
  const layoutTemplate =
    input.format === "xlsx"
      ? "spreadsheet_workbook"
      : input.documentIntentHints.layout_template;
  const metadataColumns = readArray(input.metadata, "spreadsheet_columns")
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .map((value) => value.trim())
    .slice(0, 12);

  return {
    output_format: input.format,
    export_family: exportFamily,
    kind,
    style: input.documentIntentHints.document_style,
    layout_template: layoutTemplate,
    preserve_numbers: moneyAmounts.length > 0 || tableRequired,
    table_required: tableRequired,
    exact_text_required:
      Boolean(input.documentIntentHints.footer_text) ||
      Boolean(input.documentIntentHints.signature_text) ||
      mustInclude.length > 0,
    must_include: mustInclude,
    money_amounts: moneyAmounts,
    quality_checks: {
      preserve_numbers: moneyAmounts.length > 0 || tableRequired,
      preserve_user_phrases: mustInclude.length > 0,
      no_assistant_chatter: true,
      preflight_required: true,
    },
    ...(input.documentIntentHints.footer_text
      ? { footer_text: input.documentIntentHints.footer_text }
      : {}),
    ...(input.documentIntentHints.signature_text
      ? { signature_text: input.documentIntentHints.signature_text }
      : {}),
    ...(input.format === "xlsx"
      ? {
          spreadsheet: {
            sheet_name: input.title ?? "Elyan Çıktısı",
            suggested_columns:
              metadataColumns.length > 0
                ? metadataColumns
                : detectSpreadsheetColumns(input.textBlocks),
            include_totals:
              moneyAmounts.length > 0 ||
              readBoolean(input.metadata, "include_totals") === true ||
              /\b(toplam|genel\s+toplam|total|sum)\b/i.test(normalizedPrompt),
          },
        }
      : {}),
  };
}

function cleanMarkdownText(value: string): string {
  return String(value ?? "")
    .replace(/\r\n?/g, "\n")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[(.*?)\]\((.*?)\)/g, "$1")
    .replace(/^>\s?/gm, "")
    .trim();
}

function splitMarkdownTableRow(line: string): string[] {
  const normalized = line.trim().replace(/^\||\|$/g, "");
  if (!normalized) {
    return [];
  }
  return normalized.split("|").map((cell) => cleanMarkdownText(cell).trim());
}

function isMarkdownTableDivider(line: string): boolean {
  const normalized = line.trim();
  return /^\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?$/.test(normalized);
}

function parseMarkdownTable(
  lines: string[],
  startIndex: number,
): { headers: string[]; rows: string[][]; nextIndex: number } | null {
  const headerLine = lines[startIndex]?.trim() ?? "";
  const dividerLine = lines[startIndex + 1]?.trim() ?? "";
  if (!headerLine.includes("|") || !isMarkdownTableDivider(dividerLine)) {
    return null;
  }
  const headers = splitMarkdownTableRow(headerLine);
  if (headers.length === 0) {
    return null;
  }
  const rows: string[][] = [];
  let nextIndex = startIndex + 2;
  for (; nextIndex < lines.length; nextIndex += 1) {
    const rowLine = lines[nextIndex]?.trim() ?? "";
    if (!rowLine || !rowLine.includes("|")) {
      break;
    }
    if (isMarkdownTableDivider(rowLine)) {
      continue;
    }
    const row = splitMarkdownTableRow(rowLine);
    if (row.length !== headers.length) {
      break;
    }
    rows.push(row);
  }
  return rows.length > 0 ? { headers, rows, nextIndex } : null;
}

function pushParagraphBlock(
  blocks: RenderRecipeBlock[],
  text: string,
  type: RenderRecipeBlock["type"] = "paragraph",
  level?: number,
) {
  const normalized = cleanMarkdownText(text);
  if (!normalized) {
    return;
  }
  blocks.push({
    type,
    text: normalized,
    ...(typeof level === "number" ? { level } : {}),
    order: blocks.length,
  });
}

function pushListBlock(blocks: RenderRecipeBlock[], items: string[]) {
  const normalizedItems = items
    .map((item) => cleanMarkdownText(item).trim())
    .filter(Boolean);
  if (normalizedItems.length === 0) {
    return;
  }
  for (const item of normalizedItems) {
    blocks.push({
      type: "bullet",
      text: item,
      order: blocks.length,
    });
  }
}

function pushTableBlock(
  blocks: RenderRecipeBlock[],
  headers: string[],
  rows: string[][],
  title?: string | null,
) {
  if (headers.length === 0 || rows.length === 0) {
    return;
  }
  blocks.push({
    type: "table",
    text: cleanMarkdownText(title ?? ""),
    tableHeaders: headers.map((header) => cleanMarkdownText(header).trim()),
    tableRows: rows.map((row) =>
      row.map((cell) => cleanMarkdownText(cell).trim()),
    ),
    order: blocks.length,
  });
}

function buildTextBlocks(responseText: string): RenderRecipeBlock[] {
  const normalized = compactText(responseText);
  if (!normalized) {
    return [{ type: "paragraph", text: "", order: 0 }];
  }

  const rawSegments = String(responseText)
    .split(/\n{2,}/)
    .map((segment) => segment.trim())
    .filter((segment) => compactText(segment));

  if (!rawSegments.length) {
    return [{ type: "paragraph", text: normalized, order: 0 }];
  }

  const blocks: RenderRecipeBlock[] = [];
  for (const segment of rawSegments) {
    const lines = segment.split("\n");
    const table = lines.length >= 2 ? parseMarkdownTable(lines, 0) : null;
    if (table && table.nextIndex >= lines.length) {
      pushTableBlock(blocks, table.headers, table.rows);
      continue;
    }

    const bulletLines = lines
      .map((line) => compactText(line).replace(/^([-*•]|\d+\.)\s*/, ""))
      .filter(Boolean);
    if (
      lines.every((line) => /^\s*([-*•]|\d+\.)\s+/.test(line.trim())) &&
      bulletLines.length > 0
    ) {
      pushListBlock(blocks, bulletLines);
      continue;
    }

    const compactSegment = cleanMarkdownText(segment);
    const isHeading =
      blocks.length > 0 &&
      compactSegment.length <= 96 &&
      !/[.!?…]$/.test(compactSegment) &&
      /^[A-ZÇĞİÖŞÜ0-9][\wÇĞİÖŞÜçğıöşü\s:,-]+$/u.test(compactSegment);
    pushParagraphBlock(
      blocks,
      compactSegment,
      blocks.length === 0 ? "title" : isHeading ? "heading" : "paragraph",
      isHeading ? 2 : undefined,
    );
  }

  return blocks.slice(0, 18);
}

function readObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function buildTextBlocksFromAssistantBlocks(
  blocks: unknown[],
): RenderRecipeBlock[] {
  const textBlocks: RenderRecipeBlock[] = [];
  for (const rawBlock of blocks) {
    const block = readObject(rawBlock);
    if (!block) {
      continue;
    }
    const type = normalizeValue(block.type);
    if (type === "document_block") {
      const title = readString(block, "title");
      if (title) {
        pushParagraphBlock(textBlocks, title, "title", 1);
      }
      const sections = Array.isArray(block.sections) ? block.sections : [];
      for (const rawSection of sections) {
        const section = readObject(rawSection);
        if (!section) {
          continue;
        }
        const heading = readString(section, "heading");
        const levelValue = section.level;
        const level =
          typeof levelValue === "number" && Number.isFinite(levelValue)
            ? Math.max(1, Math.min(3, Math.trunc(levelValue)))
            : 2;
        if (heading) {
          pushParagraphBlock(textBlocks, heading, "heading", level);
        }
        const content = readString(section, "content") ?? "";
        if (content.trim()) {
          const nested = buildTextBlocks(content);
          for (const nestedBlock of nested) {
            textBlocks.push({ ...nestedBlock, order: textBlocks.length });
          }
        }
      }
      continue;
    }

    if (type === "table") {
      const headers = Array.isArray(block.columns)
        ? block.columns
            .map((value) => cleanMarkdownText(String(value ?? "")).trim())
            .filter(Boolean)
        : [];
      const rows = Array.isArray(block.rows)
        ? block.rows
            .map((row) =>
              Array.isArray(row)
                ? row.map((cell) =>
                    cleanMarkdownText(String(cell ?? "")).trim(),
                  )
                : [],
            )
            .filter((row) => row.length > 0)
        : [];
      pushTableBlock(textBlocks, headers, rows, readString(block, "title"));
      if (readString(block, "caption")) {
        pushParagraphBlock(textBlocks, readString(block, "caption") ?? "");
      }
      continue;
    }
  }

  return textBlocks.slice(0, 36);
}

function buildLayout(format: RenderRecipeFormat): RenderRecipeLayout {
  if (
    format === "png" ||
    format === "jpg" ||
    format === "jpeg" ||
    format === "webp" ||
    format === "svg"
  ) {
    return {
      kind: "canvas",
      widthPx: 1080,
      heightPx: 1440,
      background: "paper",
      safeAreaPx: 72,
    };
  }

  return {
    kind: "document_page",
    pageSize: format === "docx" || format === "xlsx" ? "DOCX" : "A4",
    orientation: "portrait",
    marginsPt: {
      top: 48,
      right: 48,
      bottom: 48,
      left: 48,
    },
    columns: 1,
  };
}

function hasRenderRequest(
  prompt: string,
  metadata?: Record<string, unknown>,
): boolean {
  const format = detectFormat(prompt, metadata);
  if (format) {
    return true;
  }

  const metadataRecord = readRecord(metadata);
  if (
    readBoolean(metadataRecord, "mobileDocumentExport") === true ||
    readBoolean(metadataRecord, "mobileLocalExport") === true ||
    readBoolean(metadataRecord, "documentExportReady") === true
  ) {
    return true;
  }

  const outputMode = normalizeValue(
    readString(metadataRecord, "documentExportMode") ??
      readString(metadataRecord, "outputMode") ??
      readString(metadataRecord, "localExportMode") ??
      readString(metadataRecord, "documentOutputMode"),
  );

  return (
    outputMode === "mobile_local" ||
    outputMode === "local" ||
    outputMode === "mobile_export" ||
    outputMode === "on_device" ||
    outputMode === "on_device_export"
  );
}

export function buildLocalRenderRecipe(input: {
  prompt: string;
  responseText: string;
  metadata?: Record<string, unknown>;
  renderOn?: RenderRecipeTarget;
  taskId?: string;
  sessionId?: string;
  assistantBlocks?: unknown[];
  understandingEnvelope?: UnderstandingEnvelope | null;
}): LocalRenderRecipe | null {
  const rawMetadata = readRecord(input.metadata) ?? {};
  const envelope =
    input.understandingEnvelope ?? findUnderstandingEnvelope(rawMetadata);
  if (
    !hasRenderRequest(input.prompt, input.metadata) &&
    !hasRenderableDesiredOutput(envelope)
  ) {
    return null;
  }

  const envelopeFormat = preferredFormatFromUnderstandingEnvelope(envelope);
  const format =
    (isRenderRecipeFormat(envelopeFormat) ? envelopeFormat : null) ??
    detectFormat(input.prompt, input.metadata) ??
    "pdf";
  const metadata = mergeEnvelopeRenderMetadata(rawMetadata, envelope);
  const renderOn = input.renderOn ?? detectRenderTarget(metadata);
  const documentIntentHints = detectDocumentIntentHints(
    input.prompt,
    metadata,
    format,
  );
  const structuredTextBlocks =
    Array.isArray(input.assistantBlocks) && input.assistantBlocks.length > 0
      ? buildTextBlocksFromAssistantBlocks(input.assistantBlocks)
      : [];
  const textBlocks =
    structuredTextBlocks.length > 0
      ? structuredTextBlocks
      : buildTextBlocks(input.responseText);
  const titleBlock = textBlocks.find(
    (block) => block.type === "title" && compactText(block.text),
  );
  const title = titleBlock ? compactText(titleBlock.text).slice(0, 120) : null;
  const mimeType = mimeTypeForFormat(format);
  const extension = format === "jpeg" ? "jpg" : format;
  const plainTextSource =
    structuredTextBlocks.length > 0
      ? textBlocks
          .flatMap((block) => {
            if (block.type === "table") {
              return [
                ...((block.tableHeaders ?? []).length > 0
                  ? [(block.tableHeaders ?? []).join(" | ")]
                  : []),
                ...(block.tableRows ?? []).map((row) => row.join(" | ")),
              ];
            }
            if (Array.isArray(block.items) && block.items.length > 0) {
              return block.items;
            }
            return [block.text];
          })
          .join("\n")
      : cleanMarkdownText(input.responseText);
  const fileName = `${slugifyFileName(
    readString(metadata, "title") ?? title ?? input.prompt,
  )}.${extension}`;
  const outputType =
    format === "png" ||
    format === "jpg" ||
    format === "jpeg" ||
    format === "webp" ||
    format === "svg"
      ? "image_render_recipe"
      : "document_render_recipe";
  const documentRequirements = buildDocumentRequirementSpec({
    format,
    outputType,
    prompt: input.prompt,
    plainTextSource,
    title,
    textBlocks,
    documentIntentHints,
    metadata,
  });
  const requiredMarkers = documentRequirements.must_include;
  const recipe: LocalRenderRecipe = {
    schema_version: "2026-06-mobile-render-recipe-v2",
    output_type: outputType,
    format,
    mime_type: mimeType,
    file_name: fileName,
    layout: buildLayout(format),
    text_blocks: textBlocks,
    content_model: {
      title,
      language: detectLanguage(`${input.prompt}\n${input.responseText}`),
      plain_text: compactText(plainTextSource),
      estimated_pages: Math.max(
        1,
        Math.ceil(
          compactText(plainTextSource).length /
            (format === "pdf" ? 2400 : format === "xlsx" ? 1600 : 900),
        ),
      ),
      block_count: textBlocks.length,
    },
    render_hints: {
      renderer: "mobile_local",
      priority: "interactive",
      paginate: format === "pdf" || format === "docx" || format === "xlsx",
      allow_share: true,
      allow_print: format === "pdf",
      vector_safe: format === "svg" || format === "pdf",
      fallback_format: format === "svg" ? "png" : "pdf",
    },
    assets_needed: collectAssetsNeeded(metadata),
    render_on: renderOn,
    metadata: {
      ...metadata,
      ...documentIntentHints,
      schema_version: "2026-06-mobile-render-recipe-v2",
      response_length: input.responseText.length,
      prompt_length: compactText(input.prompt).length,
      source: "server_brain",
      output_format: format,
      mime_type: mimeType,
      file_name: fileName,
      preflight_required: true,
      required_markers: requiredMarkers,
      document_requirements: documentRequirements,
      quality_checks: documentRequirements.quality_checks,
      structured_block_count: structuredTextBlocks.length,
      preferred_export_family:
        format === "xlsx"
          ? "spreadsheet"
          : format === "docx"
            ? "document"
            : outputType === "image_render_recipe"
              ? "image"
              : "document",
      render_intent:
        format === "pdf" || format === "docx" || format === "xlsx"
          ? "document_export"
          : format === "svg"
            ? "vector_image_export"
            : "raster_image_export",
      ...(input.taskId ? { task_id: input.taskId } : {}),
      ...(input.sessionId ? { session_id: input.sessionId } : {}),
    },
  };

  return recipe;
}
