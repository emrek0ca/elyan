import type { UnderstandingEnvelope } from "../../core/understanding/types.js";
import type {
  ElyanAssistantChartBlock,
  ElyanAssistantDocumentBlock,
  ElyanAssistantSvgBlock,
  ElyanAssistantTableBlock,
} from "../../contracts/domain.js";
import type { AssistantMessageBlock } from "../chat/message-blocks.js";
import type {
  ArtifactContentSource,
  AuthoritativeArtifactData,
  ArtifactProvenance,
  ArtifactIntent,
  ArtifactSourceAuthority,
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
  extractExplicitNumericSequence,
  extractRequestedTableColumns,
  extractFooterText,
  extractMoneyItems,
  formatMoney,
  normalizeKey,
  normalizeLocale,
  parseNumericValue,
  readRecord,
  readString,
  stableArtifactId,
} from "./utils.js";
import { validateChartSpec } from "./validators/chart.validator.js";

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
  authoritativeData?: AuthoritativeArtifactData;
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

function canonicalTableBlock(
  blocks: AssistantMessageBlock[] | undefined,
): ElyanAssistantTableBlock | null {
  if (!Array.isArray(blocks)) return null;
  return (
    blocks.find(
      (block): block is ElyanAssistantTableBlock =>
        block.type === "table" &&
        Array.isArray(block.columns) &&
        block.columns.length > 0 &&
        Array.isArray(block.rows) &&
        block.rows.length > 0,
    ) ?? null
  );
}

function canonicalChartBlock(
  blocks: AssistantMessageBlock[] | undefined,
): ElyanAssistantChartBlock | null {
  if (!Array.isArray(blocks)) return null;
  return (
    blocks.find(
      (block): block is ElyanAssistantChartBlock => block.type === "chart",
    ) ?? null
  );
}

function canonicalSvgBlock(
  blocks: AssistantMessageBlock[] | undefined,
): ElyanAssistantSvgBlock | null {
  if (!Array.isArray(blocks)) return null;
  return (
    blocks.find(
      (block): block is ElyanAssistantSvgBlock => block.type === "svg",
    ) ?? null
  );
}

function selectedAuthoritativeTypedBlock(
  input: BuildSpecInput,
): AssistantMessageBlock | null {
  if (input.intent.type === "table")
    return canonicalTableBlock(input.assistantBlocks);
  if (input.intent.type === "chart")
    return canonicalChartBlock(input.assistantBlocks);
  if (input.intent.type === "svg")
    return canonicalSvgBlock(input.assistantBlocks);
  if (input.intent.type === "document")
    return canonicalDocumentBlock(input.assistantBlocks);
  if (input.intent.type === "pdf") {
    return (
      canonicalDocumentBlock(input.assistantBlocks) ??
      canonicalTableBlock(input.assistantBlocks)
    );
  }
  return null;
}

function typedBlockSourceAuthority(
  block: AssistantMessageBlock,
  input: BuildSpecInput,
): ArtifactSourceAuthority {
  const record = block as AssistantMessageBlock & Record<string, unknown>;
  const renderHints = readRecord(record.renderHints);
  const contentOwner = readString(renderHints, "contentOwner")?.toLowerCase();
  const skillId = readString(renderHints, "skillId");
  const producerId = readString(renderHints, "producerId");
  const resultDigest = readString(renderHints, "resultDigest");
  if (
    contentOwner === "tool" &&
    producerId &&
    resultDigest &&
    input.authoritativeData?.source.authority === "tool_connector" &&
    input.authoritativeData.source.producerId === producerId &&
    input.authoritativeData.source.resultDigest === resultDigest
  ) {
    return "tool_connector";
  }
  if (
    contentOwner === "skill" &&
    skillId &&
    input.provenance?.skillUsed === true &&
    input.provenance.skillId === skillId
  ) {
    return "skill_structured_output";
  }
  return "model_typed_block";
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
  const typedBlock = selectedAuthoritativeTypedBlock(input);
  const hasTypedBlock = typedBlock != null;
  const responseText = compactText(input.responseText);
  const contentSource: ArtifactContentSource = input.authoritativeData
    ? "authoritative_structured_data"
    : hasTypedBlock
      ? "assistant_typed_block"
      : responseText
        ? "current_response_text"
        : "user_request";
  const sourceAuthority: ArtifactSourceAuthority =
    input.authoritativeData != null
      ? input.authoritativeData.source.authority
      : typedBlock != null
        ? typedBlockSourceAuthority(typedBlock, input)
        : responseText
          ? "response_text"
          : "deterministic_prompt";
  const provenance = input.provenance;
  return {
    ...(input.userId ? { userId: input.userId } : {}),
    ...(input.sessionId ? { sessionId: input.sessionId } : {}),
    ...(input.taskId ? { taskId: input.taskId } : {}),
    createdAt: new Date().toISOString(),
    ...(input.model ? { model: input.model } : {}),
    confidence: input.intent.confidence,
    contentSource,
    sourceAuthority,
    ...(input.authoritativeData
      ? {
          sourceProducerId: input.authoritativeData.source.producerId,
          sourceResultDigest: input.authoritativeData.source.resultDigest,
        }
      : {}),
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

function baseFor<TType extends ArtifactSpec["type"]>(
  input: BuildSpecInput,
  type: TType,
) {
  const sourceText = compactText(input.userRequest);
  const requiredExactTexts = (input.understandingEnvelope?.constraints ?? [])
    .filter(
      (constraint) =>
        (constraint.kind === "footer_text" ||
          constraint.kind === "signature_text") &&
        constraint.explicit === true &&
        typeof constraint.value === "string",
    )
    .map((constraint) => String(constraint.value).trim())
    .filter(Boolean);
  return {
    id: stableArtifactId({ type, text: sourceText, taskId: input.taskId }),
    type,
    intent: input.intent.intent,
    sourceText,
    locale: normalizeLocale(
      readString(readRecord(input.metadata), "locale") ??
        detectLanguage(sourceText),
    ),
    blocks: [],
    renderOptions: {
      requestedOutputKinds: input.intent.requestedOutputKinds,
      requestedExportFormats: input.intent.requestedFormats,
      desiredOutputs: input.intent.desiredOutputs,
      primaryArtifactType: input.intent.type,
      requestedColumns: extractRequestedTableColumns(input.userRequest),
      requiredExactTexts,
    },
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

function typedValue(value: string): string | number | boolean {
  const normalized = compactText(value);
  if (/^(?:true|evet)$/iu.test(normalized)) return true;
  if (/^(?:false|hayır|hayir)$/iu.test(normalized)) return false;
  const numeric =
    /^[-+]?(?:\d+(?:[.,]\d+)?|\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?)$/.test(
      normalized,
    )
      ? parseNumericValue(normalized)
      : null;
  if (numeric != null) return numeric;
  return normalized;
}

function uniqueColumnKeys(labels: string[]): string[] {
  const used = new Set<string>();
  return labels.map((label, index) => {
    const base = normalizeKey(label || `column_${index + 1}`);
    let key = base;
    let suffix = 2;
    while (used.has(key)) {
      key = `${base}_${suffix}`;
      suffix += 1;
    }
    used.add(key);
    return key;
  });
}

function tableSpecDataFromBlock(
  block: ElyanAssistantTableBlock,
): Pick<TableSpec, "title" | "columns" | "rows"> | null {
  const labels = block.columns
    .map((column) => compactText(column))
    .filter(Boolean);
  if (labels.length === 0 || block.rows.length === 0) return null;
  const keys = uniqueColumnKeys(labels);
  const matrix = block.rows
    .filter((row) => row.length === labels.length)
    .slice(0, 500);
  if (matrix.length === 0) return null;
  const typedMatrix = matrix.map((row) => row.map((cell) => typedValue(cell)));
  const columns: TableSpec["columns"] = labels.map((label, columnIndex) => {
    const values = typedMatrix.map((row) => row[columnIndex]);
    const dataType = values.every((value) => typeof value === "number")
      ? "number"
      : values.every((value) => typeof value === "boolean")
        ? "boolean"
        : "string";
    return {
      key: keys[columnIndex]!,
      label,
      dataType,
      align: dataType === "number" ? "right" : "left",
      required: true,
    };
  });
  const rows = typedMatrix.map((row) =>
    Object.fromEntries(keys.map((key, index) => [key, row[index] ?? ""])),
  );
  return {
    ...(block.title ? { title: block.title } : {}),
    columns,
    rows,
  };
}

function buildPdfSpec(input: BuildSpecInput): PdfSpec {
  const base = baseFor(input, "pdf");
  const sourceDocument = canonicalDocumentBlock(input.assistantBlocks);
  const sourceTable = canonicalTableBlock(input.assistantBlocks);
  const authoritativeTable =
    input.authoritativeData?.type === "table" ? input.authoritativeData : null;
  const moneyItems = extractMoneyItems(input.userRequest);
  const lineItems = moneyItems.filter((item) => !item.isTotal);
  const userTotal = moneyItems.find((item) => item.isTotal);
  const computedTotal = lineItems.reduce((sum, item) => sum + item.amount, 0);
  const currency =
    lineItems[0]?.currency !== "unknown"
      ? lineItems[0]?.currency
      : userTotal?.currency !== "unknown"
        ? userTotal?.currency
        : "TRY";
  const footerText = extractFooterText(input.userRequest);
  const blocks: PdfBlock[] = [];

  if (authoritativeTable) {
    blocks.push({
      type: "table",
      columns: authoritativeTable.columns,
      rows: authoritativeTable.rows,
      placement: "body",
      source: "normalized",
    });
  } else if (sourceDocument) {
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
  } else if (sourceTable) {
    const table = tableSpecDataFromBlock(sourceTable);
    if (table) {
      blocks.push({
        type: "table",
        columns: table.columns,
        rows: table.rows,
        placement: "body",
        source: "normalized",
      });
    }
  } else if (lineItems.length > 0) {
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
    ...(authoritativeTable?.title
      ? { title: authoritativeTable.title }
      : sourceDocument?.title
        ? { title: sourceDocument.title }
        : sourceTable?.title
          ? { title: sourceTable.title }
          : {}),
    blocks,
    page: {
      size: "A4",
      margin: 48,
      orientation: /\b(yatay|landscape)\b/i.test(input.userRequest)
        ? "landscape"
        : "portrait",
    },
    ...(footerText ? { footer: { text: footerText, align: "center" } } : {}),
  };
}

function buildTableSpec(input: BuildSpecInput): TableSpec | null {
  const base = baseFor(input, "table");
  if (input.authoritativeData?.type === "table") {
    return {
      ...base,
      ...(input.authoritativeData.title
        ? { title: input.authoritativeData.title }
        : {}),
      columns: input.authoritativeData.columns,
      rows: input.authoritativeData.rows,
    };
  }
  const sourceTable = canonicalTableBlock(input.assistantBlocks);
  if (sourceTable) {
    const source = tableSpecDataFromBlock(sourceTable);
    return source ? { ...base, ...source } : null;
  }
  const explicitSequence = extractExplicitNumericSequence(input.userRequest);
  const requestedColumns = extractRequestedTableColumns(input.userRequest);
  const squareRequested =
    /\b(?:kare(?:si|leri|lerini)?|square(?:s|d)?)\b/iu.test(input.userRequest);
  if (
    squareRequested &&
    explicitSequence.length > 0 &&
    requestedColumns.length === 2
  ) {
    const columnRoles = requestedColumns.map((label) => {
      const key = normalizeKey(label);
      if (/^(?:sayi|number|input|girdi)$/u.test(key)) return "input" as const;
      if (/^(?:kare|square|squared|sonuc|result)$/u.test(key))
        return "square" as const;
      return null;
    });
    if (columnRoles.includes("input") && columnRoles.includes("square")) {
      const displayColumns = requestedColumns.map((label) =>
        label.length > 0
          ? `${label[0]!.toLocaleUpperCase("tr-TR")}${label.slice(1)}`
          : label,
      );
      const keys = uniqueColumnKeys(displayColumns);
      return {
        ...base,
        metadata: {
          ...base.metadata,
          contentSource: "user_request",
          sourceAuthority: "deterministic_prompt",
        },
        columns: displayColumns.map((label, index) => ({
          key: keys[index]!,
          label,
          dataType: "number" as const,
          align: "right" as const,
          required: true,
        })),
        rows: explicitSequence.map((value) =>
          Object.fromEntries(
            keys.map((key, index) => [
              key,
              columnRoles[index] === "square" ? value * value : value,
            ]),
          ),
        ),
      };
    }
  }
  const points = extractDataPoints(input.userRequest);
  if (points.length === 0) return null;
  const hasCurrency = points.some((point) => point.currency !== "unknown");
  const rows = points.map((point) => ({
    label: point.label,
    value: point.value,
    ...(point.currency !== "unknown" ? { currency: point.currency } : {}),
  }));
  const total = rows.reduce(
    (sum, row) => sum + (typeof row.value === "number" ? row.value : 0),
    0,
  );

  return {
    ...base,
    title: /\b(gelir|revenue)\b/i.test(input.userRequest)
      ? "Gelir Tablosu"
      : "Tablo",
    columns: [
      {
        key: "label",
        label: "Dönem",
        dataType: "string",
        align: "left",
        required: true,
      },
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

function chartTypeForArtifact(
  type: ElyanAssistantChartBlock["chartType"],
): ChartSpec["chartType"] {
  if (
    type === "pie" ||
    type === "scatter" ||
    type === "bar" ||
    type === "line"
  ) {
    return type;
  }
  return type === "area" ? "line" : "bar";
}

function chartSpecDataFromBlock(block: ElyanAssistantChartBlock): Pick<
  ChartSpec,
  "data" | "xKey" | "yKey" | "series"
> | null {
  // `series`/`labels`/`values` EKRAN serisidir — 240 noktaya seyreltilir.
  // `data` tam çözünürlüğü taşır. Artefakt (XLSX/PDF/render) tam veriyi
  // almalı, önizleme serisini değil; bu yüzden `data` daha uzunsa o kazanır.
  const fullResolutionRecords = Array.isArray(block.data) ? block.data : [];
  const displayPointCount =
    block.series?.[0]?.labels?.length ?? block.labels?.length ?? 0;
  const preferFullResolution =
    fullResolutionRecords.length > displayPointCount &&
    fullResolutionRecords.length > 0;

  if (!preferFullResolution && block.series && block.series.length > 0) {
    const normalizedSeries = block.series.map((series, index) => {
      const labels = Array.isArray(series.labels) ? series.labels : [];
      const values = Array.isArray(series.values) ? series.values : [];
      if (labels.length === 0 || labels.length !== values.length) return null;
      return {
        key: `series_${index + 1}`,
        label: compactText(series.name) || `Seri ${index + 1}`,
        labels,
        values,
      };
    });
    if (normalizedSeries.some((series) => series == null)) return null;
    const completeSeries = normalizedSeries.filter(
      (series): series is NonNullable<typeof series> => series != null,
    );
    const labels = completeSeries[0]!.labels;
    if (
      completeSeries.some(
        (series) =>
          series.labels.length !== labels.length ||
          series.labels.some((label, index) => label !== labels[index]),
      )
    ) {
      return null;
    }
    return {
      xKey: "label",
      yKey: completeSeries[0]!.key,
      series: completeSeries.map((series) => ({
        key: series.key,
        label: series.label,
        valueType: "number" as const,
      })),
      data: labels.slice(0, 1_500).map((label, rowIndex) => ({
        label,
        ...Object.fromEntries(
          completeSeries.map((series) => [series.key, series.values[rowIndex]]),
        ),
      })),
    };
  }
  const directLabels = Array.isArray(block.labels) ? block.labels : [];
  const directValues = Array.isArray(block.values) ? block.values : [];
  if (
    !preferFullResolution &&
    directLabels.length > 0 &&
    directLabels.length === directValues.length
  ) {
    return {
      xKey: "label",
      yKey: "value",
      series: [
        { key: "value", label: block.yLabel ?? "Değer", valueType: "number" },
      ],
      data: directLabels.slice(0, 1_500).map((label, index) => ({
        label,
        value: directValues[index],
      })),
    };
  }
  const records = Array.isArray(block.data)
    ? block.data
    : Array.isArray(block.points)
      ? block.points
      : [];
  const data = records
    .filter(
      (entry): entry is Record<string, unknown> =>
        Boolean(entry) && typeof entry === "object" && !Array.isArray(entry),
    )
    .slice(0, 1_500);
  if (data.length === 0) return null;
  const keys = Object.keys(data[0] ?? {});
  const numericKeys = keys.filter((key) =>
    data.every(
      (row) => typeof row[key] === "number" && Number.isFinite(row[key]),
    ),
  );
  if (numericKeys.length === 0) return null;
  const xKey = keys.find((key) => !numericKeys.includes(key)) ?? "label";
  return {
    data,
    xKey,
    yKey: numericKeys[0]!,
    series: numericKeys.slice(0, 8).map((key) => ({
      key,
      label: key,
      valueType: "number" as const,
    })),
  };
}

function deterministicSquareChartSpec(input: BuildSpecInput): ChartSpec | null {
  const explicitSequence = extractExplicitNumericSequence(input.userRequest);
  if (explicitSequence.length === 0) return null;
  if (!/\b(?:kare(?:si|leri|lerini)?|square(?:s|d)?)\b/iu.test(input.userRequest)) {
    return null;
  }

  const base = baseFor(input, "chart");
  return {
    ...base,
    metadata: {
      ...base.metadata,
      contentSource: "user_request",
      sourceAuthority: "deterministic_prompt",
    },
    chartType: detectChartType(input.userRequest),
    title: "Kareler",
    xKey: "sayi",
    yKey: "kare",
    series: [{ key: "kare", label: "Kare", valueType: "number" }],
    data: explicitSequence.map((value) => ({
      sayi: value,
      kare: value * value,
    })),
  };
}

function buildChartSpec(input: BuildSpecInput): ChartSpec | null {
  const base = baseFor(input, "chart");
  if (input.authoritativeData?.type === "chart") {
    return {
      ...base,
      ...(input.authoritativeData.title
        ? { title: input.authoritativeData.title }
        : {}),
      ...(input.authoritativeData.description
        ? { description: input.authoritativeData.description }
        : {}),
      chartType: input.authoritativeData.chartType,
      xKey: input.authoritativeData.xKey,
      yKey: input.authoritativeData.yKey,
      series: input.authoritativeData.series,
      data: input.authoritativeData.data,
    };
  }
  const sourceChart = canonicalChartBlock(input.assistantBlocks);
  const deterministicSquare = deterministicSquareChartSpec(input);
  if (sourceChart) {
    const source = chartSpecDataFromBlock(sourceChart);
    if (!source) return deterministicSquare;
    const candidate: ChartSpec = {
      ...base,
      chartType: chartTypeForArtifact(sourceChart.chartType),
      ...(sourceChart.title ? { title: sourceChart.title } : {}),
      ...(sourceChart.caption ? { description: sourceChart.caption } : {}),
      ...source,
    };
    if (validateChartSpec(candidate).ok) {
      return candidate;
    }
    return deterministicSquare ?? candidate;
  }
  if (deterministicSquare) return deterministicSquare;
  const points = extractDataPoints(input.userRequest);
  if (points.length === 0) return null;
  const valueType = points.some((point) => point.currency !== "unknown")
    ? "currency"
    : "number";
  return {
    ...base,
    chartType: detectChartType(input.userRequest),
    title: /\b(gelir|revenue)\b/i.test(input.userRequest)
      ? "Gelir Grafiği"
      : "Grafik",
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
    height:
      Number.isFinite(height) && height > 0 ? Math.min(height, 10_000) : 1024,
  };
}

function extractCenteredSvgText(text: string): string {
  const match = /(?:ortada|merkezde|center(?:ed)?)\s+(.+?)\s+yazan/iu.exec(
    text,
  );
  const direct = compactText(match?.[1] ?? "");
  if (direct) return direct.slice(0, 80);
  const quoted = /["“']([^"”']{1,80})["”']/.exec(text);
  return compactText(quoted?.[1] ?? "Elyan") || "Elyan";
}

function buildSvgSpec(input: BuildSpecInput): SvgSpec {
  const base = baseFor(input, "svg");
  const sourceSvg = canonicalSvgBlock(input.assistantBlocks);
  if (sourceSvg?.svg || sourceSvg?.markup) {
    const markup = sourceSvg.svg ?? sourceSvg.markup!;
    const viewBox =
      /\bviewBox\s*=\s*["']([^"']+)["']/iu.exec(markup)?.[1] ??
      sourceSvg.viewBox;
    const dimensions = String(viewBox ?? "")
      .trim()
      .split(/\s+/)
      .map(Number);
    const width =
      dimensions.length === 4 &&
      Number.isFinite(dimensions[2]) &&
      dimensions[2]! > 0
        ? Math.min(10_000, Math.round(dimensions[2]!))
        : 1024;
    const height =
      dimensions.length === 4 &&
      Number.isFinite(dimensions[3]) &&
      dimensions[3]! > 0
        ? Math.min(10_000, Math.round(dimensions[3]!))
        : 1024;
    return {
      ...base,
      canvas: {
        width,
        height,
        viewBox: viewBox ?? `0 0 ${width} ${height}`,
      },
      elements: [],
      markup,
    };
  }
  const canvas = extractSvgCanvas(input.userRequest);
  const text = extractCenteredSvgText(input.userRequest);
  const fontSize = Math.max(
    24,
    Math.round(Math.min(canvas.width, canvas.height) / 8),
  );
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
    purpose: /\b(mail|email)\b/i.test(input.userRequest)
      ? "email"
      : "chat_message",
    tone,
    language,
    blocks: [{ type: "body", text: payload || input.userRequest }],
    renderOptions: {
      requestedTone: /\b(profesyonel)\b/i.test(input.userRequest)
        ? "professional"
        : tone,
    },
  };
}

function buildDocumentSpec(input: BuildSpecInput): DocumentSpec | null {
  const base = baseFor(input, "document");
  const sourceDocument = canonicalDocumentBlock(input.assistantBlocks);
  const explicitUserContent = input.userRequest.includes(":")
    ? extractTextPayload(input.userRequest)
    : "";
  const source = explicitUserContent || compactText(input.responseText);
  if (!sourceDocument && !source) {
    return null;
  }
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
  const requestedExportFormats = input.intent.requestedFormats.filter(
    (format): format is "pdf" | "docx" | "xlsx" =>
      format === "pdf" || format === "docx" || format === "xlsx",
  );
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
    language: detectLanguage(source || input.userRequest),
    sections: sourceDocument
      ? sourceDocument.sections.map((section) => ({
          ...(section.heading ? { heading: section.heading } : {}),
          content: section.content,
          ...(section.level ? { level: section.level } : {}),
        }))
      : [{ heading: undefined, content: compactText(source), level: 1 }],
    exportFormats:
      requestedExportFormats.length > 0
        ? requestedExportFormats
        : (sourceDocument?.exportFormats ?? ["pdf", "docx"]),
  };
}

function buildImagePromptSpec(input: BuildSpecInput): ImagePromptSpec {
  const base = baseFor(input, "image_prompt");
  const subject =
    compactText(
      extractTextPayload(input.userRequest)
        .replace(
          /\b(prompt|görsel|gorsel|image|video|oluştur|olustur|yaz)\b/gi,
          " ",
        )
        .trim(),
    ) || "Elyan görseli";
  const characterLock = /\b(elyan\s+robot|elyan robotu|robot)\b/i.test(
    input.userRequest,
  )
    ? { subject: "Elyan robot", preserveExistingDesign: true }
    : undefined;
  const constraints = [
    ...(characterLock ? ["Elyan robot görünümü değişmeyecek."] : []),
    ...(/\b(do not redesign|yeniden tasarlama|değişmesin|degismesin)\b/i.test(
      input.userRequest,
    )
      ? ["Mevcut tasarım kilitleri korunacak."]
      : []),
  ];
  return {
    ...base,
    subject,
    style: /\b(app store)\b/i.test(input.userRequest)
      ? "mobile app store preview"
      : undefined,
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

export function artifactSpecSummary(
  spec: ArtifactSpec,
): Record<string, unknown> {
  return {
    id: spec.id,
    type: spec.type,
    intent: spec.intent,
    blockCount: spec.blocks.length,
    contentSource: spec.metadata?.contentSource ?? null,
    sourceAuthority: spec.metadata?.sourceAuthority ?? null,
    desiredOutputs: spec.renderOptions?.desiredOutputs ?? [],
    webSourceCount: spec.metadata?.webSourceCount ?? 0,
    documentSourceCount: spec.metadata?.documentSourceCount ?? 0,
    retrievalResultCount: spec.metadata?.retrievalResultCount ?? 0,
    skillUsed: spec.metadata?.skillUsed ?? false,
    toolCallCount: spec.metadata?.toolCallCount ?? 0,
    ...(spec.type === "pdf"
      ? { documentType: spec.documentType, pdfBlockCount: spec.blocks.length }
      : {}),
    ...(spec.type === "table"
      ? { rowCount: spec.rows.length, columnCount: spec.columns.length }
      : {}),
    ...(spec.type === "chart"
      ? { chartType: spec.chartType, dataCount: spec.data.length }
      : {}),
    ...(spec.type === "svg"
      ? { elementCount: spec.elements.length, canvas: spec.canvas }
      : {}),
    ...(spec.type === "document"
      ? { sectionCount: spec.sections.length, documentType: spec.documentType }
      : {}),
  };
}
