import type { UnderstandingEnvelope } from "../../core/understanding/types.js";
import type { ElyanAssistantDocumentBlock } from "../../contracts/domain.js";
import type { AssistantMessageBlock } from "../chat/message-blocks.js";
import type {
  ArtifactContentSource,
  ArtifactProvenance,
  ArtifactIntent,
  ArtifactSpec,
  ChartSpec,
  DocumentSpec,
  ImagePromptSpec,
  PdfBlock,
  PdfSpec,
  SvgSpec,
  TableSpec,
  TextSpec,
} from "./types.js";
import {
  compactText,
  detectLanguage,
  extractDataPoints,
  extractFooterText,
  extractMoneyItems,
  formatMoney,
  normalizeKey,
  normalizeLocale,
  readRecord,
  readString,
  stableArtifactId,
} from "./utils.js";

type BuildSpecInput = {
  intent: ArtifactIntent;
  userRequest: string;
  responseText?: string | null;
  metadata?: Record<string, unknown>;
  understandingEnvelope?: UnderstandingEnvelope | null;
  userId?: string;
  sessionId?: string;
  taskId?: string;
  model?: string | null;
  assistantBlocks?: AssistantMessageBlock[];
  provenance?: ArtifactProvenance;
};

function canonicalDocumentBlock(
  blocks: AssistantMessageBlock[] | undefined,
): ElyanAssistantDocumentBlock | null {
  if (!Array.isArray(blocks)) {
    return null;
  }
  return (
    blocks.find(
      (block): block is ElyanAssistantDocumentBlock =>
        block.type === "document_block" &&
        Array.isArray((block as ElyanAssistantDocumentBlock).sections) &&
        (block as ElyanAssistantDocumentBlock).sections.length > 0,
    ) ?? null
  );
}

function boundedCount(value: number | undefined): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? Math.min(10_000, Math.floor(value))
    : undefined;
}

function safeSkillId(value: string | null | undefined): string | undefined {
  const normalized = value?.trim() ?? "";
  return /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$/.test(normalized)
    ? normalized
    : undefined;
}

function metadataFor(input: BuildSpecInput) {
  const sourceDocument = canonicalDocumentBlock(input.assistantBlocks);
  const responseText = compactText(input.responseText);
  const contentSource: ArtifactContentSource = sourceDocument
    ? "assistant_typed_block"
    : responseText
      ? "current_response_text"
      : "user_request";
  const provenance = input.provenance;
  return {
    ...(input.userId ? { userId: input.userId } : {}),
    ...(input.sessionId ? { sessionId: input.sessionId } : {}),
    ...(input.taskId ? { taskId: input.taskId } : {}),
    createdAt: new Date().toISOString(),
    ...(input.model ? { model: input.model } : {}),
    confidence: input.intent.confidence,
    contentSource,
    ...(provenance?.webGroundingUsed !== undefined
      ? { webGroundingUsed: provenance.webGroundingUsed }
      : {}),
    ...(boundedCount(provenance?.webSourceCount) !== undefined
      ? { webSourceCount: boundedCount(provenance?.webSourceCount) }
      : {}),
    ...(boundedCount(provenance?.documentSourceCount) !== undefined
      ? { documentSourceCount: boundedCount(provenance?.documentSourceCount) }
      : {}),
    ...(boundedCount(provenance?.retrievalResultCount) !== undefined
      ? { retrievalResultCount: boundedCount(provenance?.retrievalResultCount) }
      : {}),
    ...(provenance?.skillUsed !== undefined
      ? { skillUsed: provenance.skillUsed }
      : {}),
    ...(safeSkillId(provenance?.skillId)
      ? { skillId: safeSkillId(provenance?.skillId) }
      : {}),
    ...(boundedCount(provenance?.toolCallCount) !== undefined
      ? { toolCallCount: boundedCount(provenance?.toolCallCount) }
      : {}),
  };
}

function baseFor<TType extends ArtifactSpec["type"]>(input: BuildSpecInput, type: TType) {
  const sourceText = compactText(input.userRequest);
  return {
    id: stableArtifactId({ type, text: sourceText, taskId: input.taskId }),
    type,
    intent: input.intent.intent,
    sourceText,
    locale: normalizeLocale(readString(readRecord(input.metadata), "locale") ?? detectLanguage(sourceText)),
    blocks: [],
    renderOptions: {},
    validationRules: [],
    metadata: metadataFor(input),
  };
}

function detectPdfDocumentType(text: string): PdfSpec["documentType"] {
  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (/\b(fatura|invoice)\b/i.test(normalized)) return "invoice";
  if (/\b(teklif|quote|proforma)\b/i.test(normalized)) return "quote";
  if (/\b(rapor|report)\b/i.test(normalized)) return "report";
  if (/\b(mektup|dilekçe|dilekce|letter)\b/i.test(normalized)) return "letter";
  if (/\b(özet|ozet|summary)\b/i.test(normalized)) return "summary";
  if (/\b(makbuz|fiş|fis|receipt)\b/i.test(normalized)) return "receipt";
  return extractMoneyItems(text).length > 0 ? "receipt" : "custom";
}

function buildPdfSpec(input: BuildSpecInput): PdfSpec {
  const base = baseFor(input, "pdf");
  const sourceDocument = canonicalDocumentBlock(input.assistantBlocks);
  const moneyItems = extractMoneyItems(input.userRequest);
  const lineItems = moneyItems.filter((item) => !item.isTotal);
  const userTotal = moneyItems.find((item) => item.isTotal);
  const computedTotal = lineItems.reduce((sum, item) => sum + item.amount, 0);
  const currency = lineItems[0]?.currency !== "unknown"
    ? lineItems[0]?.currency
    : userTotal?.currency !== "unknown"
      ? userTotal?.currency
      : "TRY";
  const footerText = extractFooterText(input.userRequest);
  const blocks: PdfBlock[] = [];

  if (lineItems.length === 0) {
    if (sourceDocument) {
      for (const section of sourceDocument.sections) {
        const sectionText = [
          section.heading ? `## ${compactText(section.heading)}` : "",
          String(section.content ?? "").trim(),
        ]
          .filter(Boolean)
          .join("\n\n")
          .slice(0, 8_000)
          .trim();
        if (sectionText) {
          blocks.push({
            type: "paragraph",
            text: sectionText,
            placement: "body",
            source: "normalized",
          });
        }
      }
    } else {
      const text = compactText(input.responseText || input.userRequest);
      if (text) {
        blocks.push({
          type: "paragraph",
          text,
          placement: "body",
          source: input.responseText ? "normalized" : "user",
        });
      }
    }
  } else {
    for (const item of lineItems) {
      blocks.push({
        type: "line_item",
        label: item.label,
        amount: item.amount,
        rawAmount: item.rawAmount,
        currency: item.currency === "unknown" ? currency : item.currency,
        source: "user",
        placement: "body",
      });
    }
    blocks.push({
      type: "total",
      label: userTotal?.label ?? "Genel toplam",
      amount: userTotal?.amount ?? computedTotal,
      rawAmount: userTotal?.rawAmount ?? formatMoney(computedTotal, currency),
      currency,
      source: userTotal ? "user" : "computed",
      placement: "body",
    });
  }

  if (footerText) {
    blocks.push({
      type: "footer",
      text: footerText,
      placement: "footer",
      source: "user",
    });
  }

  return {
    ...base,
    documentType: detectPdfDocumentType(input.userRequest),
    ...(sourceDocument?.title ? { title: sourceDocument.title } : {}),
    blocks,
    page: {
      size: "A4",
      margin: 48,
      orientation: /\b(yatay|landscape)\b/i.test(input.userRequest) ? "landscape" : "portrait",
    },
    ...(footerText ? { footer: { text: footerText, align: "center" } } : {}),
  };
}

function buildTableSpec(input: BuildSpecInput): TableSpec {
  const base = baseFor(input, "table");
  const points = extractDataPoints(input.userRequest);
  const hasCurrency = points.some((point) => point.currency !== "unknown");
  const rows = points.map((point) => ({
    label: point.label,
    value: point.value,
    ...(point.currency !== "unknown" ? { currency: point.currency } : {}),
  }));
  const total = rows.reduce((sum, row) => sum + (typeof row.value === "number" ? row.value : 0), 0);

  return {
    ...base,
    title: /\b(gelir|revenue)\b/i.test(input.userRequest) ? "Gelir Tablosu" : "Tablo",
    columns: [
      { key: "label", label: "Dönem", dataType: "string", align: "left", required: true },
      {
        key: "value",
        label: hasCurrency ? "Tutar" : "Değer",
        dataType: hasCurrency ? "currency" : "number",
        align: "right",
        required: true,
      },
    ],
    rows,
    ...(rows.length > 1
      ? { summary: { label: "Toplam", values: { value: total } } }
      : {}),
  };
}

function detectChartType(text: string): ChartSpec["chartType"] {
  const normalized = compactText(text).toLocaleLowerCase("tr-TR");
  if (/\b(çizgi|cizgi|line)\b/i.test(normalized)) return "line";
  if (/\b(pasta|pie)\b/i.test(normalized)) return "pie";
  if (/\b(scatter|dağılım|dagilim)\b/i.test(normalized)) return "scatter";
  return "bar";
}

function buildChartSpec(input: BuildSpecInput): ChartSpec {
  const base = baseFor(input, "chart");
  const points = extractDataPoints(input.userRequest);
  const valueType = points.some((point) => point.currency !== "unknown") ? "currency" : "number";
  return {
    ...base,
    chartType: detectChartType(input.userRequest),
    title: /\b(gelir|revenue)\b/i.test(input.userRequest) ? "Gelir Grafiği" : "Grafik",
    xKey: "label",
    yKey: "value",
    series: [{ key: "value", label: "Değer", valueType }],
    data: points.map((point) => ({ label: point.label, value: point.value })),
  };
}

function extractSvgCanvas(text: string): { width: number; height: number } {
  const match = /(?<width>\d{2,5})\s*[x×]\s*(?<height>\d{2,5})/i.exec(text);
  const width = Number(match?.groups?.width ?? 1024);
  const height = Number(match?.groups?.height ?? width);
  return {
    width: Number.isFinite(width) && width > 0 ? Math.min(width, 10_000) : 1024,
    height: Number.isFinite(height) && height > 0 ? Math.min(height, 10_000) : 1024,
  };
}

function extractCenteredSvgText(text: string): string {
  const match = /(?:ortada|merkezde|center(?:ed)?)\s+(.+?)\s+yazan/iu.exec(text);
  const direct = compactText(match?.[1] ?? "");
  if (direct) return direct.slice(0, 80);
  const quoted = /["“']([^"”']{1,80})["”']/.exec(text);
  return compactText(quoted?.[1] ?? "Elyan") || "Elyan";
}

function buildSvgSpec(input: BuildSpecInput): SvgSpec {
  const base = baseFor(input, "svg");
  const canvas = extractSvgCanvas(input.userRequest);
  const text = extractCenteredSvgText(input.userRequest);
  const fontSize = Math.max(24, Math.round(Math.min(canvas.width, canvas.height) / 8));
  return {
    ...base,
    canvas: {
      width: canvas.width,
      height: canvas.height,
      viewBox: `0 0 ${canvas.width} ${canvas.height}`,
    },
    elements: [
      {
        type: "rect",
        x: 0,
        y: 0,
        width: canvas.width,
        height: canvas.height,
        fill: "transparent",
      },
      {
        type: "text",
        x: canvas.width / 2,
        y: canvas.height / 2,
        text,
        textAnchor: "middle",
        dominantBaseline: "middle",
        fontSize,
        fontFamily: "Inter, Arial, sans-serif",
        fill: "#123127",
      },
    ],
  };
}

function extractTextPayload(text: string): string {
  const colonIndex = text.indexOf(":");
  if (colonIndex >= 0 && colonIndex < text.length - 1) {
    return compactText(text.slice(colonIndex + 1));
  }
  return compactText(text);
}

function buildTextSpec(input: BuildSpecInput): TextSpec {
  const base = baseFor(input, "text");
  const payload = extractTextPayload(input.userRequest);
  const language = detectLanguage(payload || input.userRequest);
  const tone = /\b(kısa|kisa|short)\b/i.test(input.userRequest)
    ? "short"
    : /\b(teknik|technical)\b/i.test(input.userRequest)
      ? "technical"
      : /\b(ikna|satış|satis|persuasive)\b/i.test(input.userRequest)
        ? "persuasive"
        : /\b(profesyonel|resmi|formal)\b/i.test(input.userRequest)
          ? "formal"
          : "neutral";
  return {
    ...base,
    purpose: /\b(mail|email)\b/i.test(input.userRequest) ? "email" : "chat_message",
    tone,
    language,
    blocks: [{ type: "body", text: payload || input.userRequest }],
    renderOptions: {
      requestedTone: /\b(profesyonel)\b/i.test(input.userRequest) ? "professional" : tone,
    },
  };
}

function buildDocumentSpec(input: BuildSpecInput): DocumentSpec {
  const base = baseFor(input, "document");
  const sourceDocument = canonicalDocumentBlock(input.assistantBlocks);
  const source = extractTextPayload(input.userRequest) || input.responseText || input.userRequest;
  const normalized = compactText(input.userRequest).toLocaleLowerCase("tr-TR");
  const documentType = /\b(teklif)\b/i.test(normalized)
    ? "quote"
    : /\b(sözleşme|sozlesme)\b/i.test(normalized)
      ? "contract_draft"
      : /\b(özet|ozet)\b/i.test(normalized)
        ? "summary"
        : /\b(mektup|dilekçe|dilekce)\b/i.test(normalized)
          ? "letter"
          : /\b(rapor)\b/i.test(normalized)
            ? "report"
            : "custom";
  return {
    ...base,
    documentType,
    title:
      sourceDocument?.title ??
      (documentType === "quote"
        ? "Teklif"
        : documentType === "report"
          ? "Rapor"
          : undefined),
    language: detectLanguage(source),
    sections: sourceDocument
      ? sourceDocument.sections.map((section) => ({
          ...(section.heading ? { heading: section.heading } : {}),
          content: section.content,
          ...(section.level ? { level: section.level } : {}),
        }))
      : [{ heading: undefined, content: compactText(source), level: 1 }],
    exportFormats: sourceDocument?.exportFormats ?? ["pdf", "docx"],
  };
}

function buildImagePromptSpec(input: BuildSpecInput): ImagePromptSpec {
  const base = baseFor(input, "image_prompt");
  const subject = compactText(
    extractTextPayload(input.userRequest)
      .replace(/\b(prompt|görsel|gorsel|image|video|oluştur|olustur|yaz)\b/gi, " ")
      .trim(),
  ) || "Elyan görseli";
  const characterLock = /\b(elyan\s+robot|elyan robotu|robot)\b/i.test(input.userRequest)
    ? { subject: "Elyan robot", preserveExistingDesign: true }
    : undefined;
  const constraints = [
    ...(characterLock ? ["Elyan robot görünümü değişmeyecek."] : []),
    ...(/\b(do not redesign|yeniden tasarlama|değişmesin|degismesin)\b/i.test(input.userRequest)
      ? ["Mevcut tasarım kilitleri korunacak."]
      : []),
  ];
  return {
    ...base,
    subject,
    style: /\b(app store)\b/i.test(input.userRequest) ? "mobile app store preview" : undefined,
    aspectRatio: /\b(16:9|9:16|1:1|4:5)\b/i.exec(input.userRequest)?.[1],
    constraints,
    negativePrompt: ["brand drift", "unreadable text", "extra logos"],
    prompt: [subject, ...constraints].filter(Boolean).join(". "),
    ...(characterLock ? { character_lock: characterLock } : {}),
  };
}

export function buildArtifactSpec(input: BuildSpecInput): ArtifactSpec | null {
  if (!input.intent.type || input.intent.requiresDesktopRuntime) {
    return null;
  }
  switch (input.intent.type) {
    case "pdf":
      return buildPdfSpec(input);
    case "table":
      return buildTableSpec(input);
    case "chart":
      return buildChartSpec(input);
    case "svg":
      return buildSvgSpec(input);
    case "text":
      return buildTextSpec(input);
    case "document":
      return buildDocumentSpec(input);
    case "image_prompt":
      return buildImagePromptSpec(input);
  }
}

export function artifactSpecSummary(spec: ArtifactSpec): Record<string, unknown> {
  return {
    id: spec.id,
    type: spec.type,
    intent: spec.intent,
    blockCount: spec.blocks.length,
    contentSource: spec.metadata?.contentSource ?? null,
    webSourceCount: spec.metadata?.webSourceCount ?? 0,
    documentSourceCount: spec.metadata?.documentSourceCount ?? 0,
    retrievalResultCount: spec.metadata?.retrievalResultCount ?? 0,
    skillUsed: spec.metadata?.skillUsed ?? false,
    toolCallCount: spec.metadata?.toolCallCount ?? 0,
    ...(spec.type === "pdf" ? { documentType: spec.documentType, pdfBlockCount: spec.blocks.length } : {}),
    ...(spec.type === "table" ? { rowCount: spec.rows.length, columnCount: spec.columns.length } : {}),
    ...(spec.type === "chart" ? { chartType: spec.chartType, dataCount: spec.data.length } : {}),
    ...(spec.type === "svg" ? { elementCount: spec.elements.length, canvas: spec.canvas } : {}),
    ...(spec.type === "document" ? { sectionCount: spec.sections.length, documentType: spec.documentType } : {}),
  };
}
