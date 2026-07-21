import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";
import type { ElyanAssistantDocumentBlock } from "../../contracts/domain.js";
import {
  buildAssistantChartBlock,
  buildAssistantCodeBlock,
  buildAssistantDocumentBlock,
  buildAssistantSvgBlock,
  buildAssistantTableBlock,
  type AssistantMessageBlock,
} from "../chat/message-blocks.js";
import { parseArtifactIntent } from "./parser.js";
import { buildArtifactSpec, artifactSpecSummary } from "./spec-builder.js";
import type {
  ArtifactIntent,
  ArtifactOutput,
  ArtifactProvenance,
  ArtifactSpec,
} from "./types.js";
import { normalizeArtifactSpec } from "./normalizer.js";
import { rendererForSpec } from "./renderers/index.js";
import { compactText, formatMoney, safeFileSlug } from "./utils.js";
import type { UnderstandingEnvelope } from "../../core/understanding/types.js";

const RESEARCH_ARTIFACT_ACTION_PATTERN =
  /(?<!\p{L})((?:araştır|arastir)\p{L}*|research\p{L}*|investigate\p{L}*)(?!\p{L})/iu;
const SOURCE_BACKED_ARTIFACT_PATTERN =
  /(?<!\p{L})(?:kaynaklı|kaynakli|source(?:[-\s]+)backed)\s+(?:(?:araştırma|arastirma|inceleme|research)\s+)?(?:rapor\p{L}*|belge\p{L}*|doküman\p{L}*|dokuman\p{L}*|paper\p{L}*|report\p{L}*|document\p{L}*)(?!\p{L})/iu;
const RESEARCH_NEGATION_PATTERN =
  /(?<!\p{L})(araştırmadan|arastirmadan|araştırma yapma|arastirma yapma|(?:internet(?:i)?|web(?:i)?)\s+kullanmadan|do not research|don't research|without researching|without using (?:the )?(?:web|internet))(?!\p{L})/iu;
const EXPLICIT_PUBLIC_WEB_ARTIFACT_PATTERN =
  /(?<!\p{L})(internetten|internetteki|internette ara|internet kaynak\p{L}*|webden|web'den|webdeki|web'deki|web üzerinde|web uzerinde|online araştır|online arastir|search the web|browse the web|browse online)(?!\p{L})/iu;
const INLINE_OR_PRIVATE_ARTIFACT_PATTERN =
  /(?<!\p{L})(aşağıdaki|asagidaki|şu metni|su metni|bu metni|verdiğim metni|verdigim metni|sözleşmeyi|sozlesmeyi|sözleşme metnini|sozlesme metnini|içeriği incele|icerigi incele)(?!\p{L})/iu;

function readMetadataString(
  metadata: Record<string, unknown> | undefined,
  key: string,
): string {
  const value = metadata?.[key];
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

export type ArtifactPipelineResult =
  | {
      kind: "none";
      intent: ArtifactIntent;
      latencyMs: number;
    }
  | {
      kind: "desktop_required";
      intent: ArtifactIntent;
      latencyMs: number;
    }
  | {
      kind: "evidence_required";
      intent: ArtifactIntent;
      reason:
        | "grounding_evidence_unavailable"
        | "artifact_content_insufficient";
      latencyMs: number;
    }
  | {
      kind: "rendered";
      intent: ArtifactIntent;
      spec: ArtifactSpec;
      output: ArtifactOutput;
      assistantBlocks: AssistantMessageBlock[];
      visibleText: string;
      rendererUsed: string;
      latencyMs: number;
    };

export async function buildArtifactPipeline(input: {
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
}): Promise<ArtifactPipelineResult> {
  const startedAt = Date.now();
  const intent = parseArtifactIntent({
    userRequest: input.userRequest,
    metadata: input.metadata,
    understandingEnvelope: input.understandingEnvelope,
  });
  if (!intent.type) {
    return { kind: "none", intent, latencyMs: Date.now() - startedAt };
  }
  if (intent.requiresDesktopRuntime) {
    return { kind: "desktop_required", intent, latencyMs: Date.now() - startedAt };
  }
  const researchPolicyRequired =
    input.metadata?.researchRequired === true ||
    readMetadataString(input.metadata, "evidencePolicy") ===
      "ground_before_render" ||
    readMetadataString(input.metadata, "documentExportIntent") ===
      "research_then_export" ||
    input.understandingEnvelope?.intent.name === "research";
  const explicitPublicWebRequested =
    EXPLICIT_PUBLIC_WEB_ARTIFACT_PATTERN.test(input.userRequest);
  const targetsInlineOrPrivateContent =
    INLINE_OR_PRIVATE_ARTIFACT_PATTERN.test(input.userRequest);
  const researchIntentAllowed =
    !targetsInlineOrPrivateContent || explicitPublicWebRequested;
  const researchArtifactRequested =
    (intent.type === "pdf" || intent.type === "document") &&
    researchIntentAllowed &&
    (researchPolicyRequired ||
      ((RESEARCH_ARTIFACT_ACTION_PATTERN.test(input.userRequest) ||
        SOURCE_BACKED_ARTIFACT_PATTERN.test(input.userRequest)) &&
        !RESEARCH_NEGATION_PATTERN.test(input.userRequest)));
  if (researchArtifactRequested) {
    const webEvidenceCount =
      input.provenance?.webGroundingUsed === true
        ? (input.provenance.webSourceCount ?? 0)
        : 0;
    const evidenceCount =
      webEvidenceCount +
      (input.provenance?.documentSourceCount ?? 0) +
      (input.provenance?.retrievalResultCount ?? 0);
    if (
      (explicitPublicWebRequested && webEvidenceCount <= 0) ||
      (!explicitPublicWebRequested && evidenceCount <= 0)
    ) {
      return {
        kind: "evidence_required",
        intent,
        reason: "grounding_evidence_unavailable",
        latencyMs: Date.now() - startedAt,
      };
    }
    if (artifactSourceText(input).length < 120) {
      return {
        kind: "evidence_required",
        intent,
        reason: "artifact_content_insufficient",
        latencyMs: Date.now() - startedAt,
      };
    }
  }
  const rawSpec = buildArtifactSpec({ ...input, intent });
  if (!rawSpec) {
    return { kind: "none", intent, latencyMs: Date.now() - startedAt };
  }
  const spec = normalizeArtifactSpec(rawSpec);
  const renderer = rendererForSpec(spec);
  const output = await renderer.render(spec);
  const assistantBlocks = artifactOutputToAssistantBlocks(
    output,
    input.assistantBlocks,
  );
  return {
    kind: "rendered",
    intent,
    spec,
    output,
    assistantBlocks,
    visibleText: visibleTextForArtifact(output),
    rendererUsed: renderer.constructor.name,
    latencyMs: Date.now() - startedAt,
  };
}

function sourceDocumentBlock(
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

function artifactSourceText(input: {
  assistantBlocks?: AssistantMessageBlock[];
  responseText?: string | null;
}): string {
  const document = sourceDocumentBlock(input.assistantBlocks);
  return compactText(
    document
      ? document.sections.map((section) => section.content).join(" ")
      : input.responseText,
  );
}

function pdfDocumentSections(spec: Extract<ArtifactSpec, { type: "pdf" }>): Array<{ heading?: string; content: string; level?: number }> {
  const lineItems = spec.blocks.filter((block) => block.type === "line_item");
  const totals = spec.blocks.filter((block) => block.type === "total");
  const sections: Array<{ heading?: string; content: string; level?: number }> = [];
  if (lineItems.length > 0) {
    sections.push({
      heading: "Kalemler",
      level: 1,
      content: lineItems
        .map((block) => `${block.label ?? "Kalem"}: ${formatMoney(block.amount ?? 0, block.currency ?? "TRY")}`)
        .join("\n"),
    });
  }
  if (totals.length > 0) {
    sections.push({
      heading: "Toplam",
      level: 1,
      content: totals
        .map((block) => `${block.label ?? "Genel toplam"}: ${formatMoney(block.amount ?? 0, block.currency ?? "TRY")}`)
        .join("\n"),
    });
  }
  if (spec.footer?.text) {
    sections.push({ heading: "Alt Bilgi", level: 1, content: spec.footer.text });
  }
  if (sections.length === 0) {
    const body = spec.blocks
      .map((block) => compactText(block.text ?? block.label ?? ""))
      .filter(Boolean)
      .join("\n\n");
    sections.push({ content: body || "Belge içeriği hazır.", level: 1 });
  }
  return sections;
}

function artifactOutputToAssistantBlocks(
  output: ArtifactOutput,
  sourceBlocks?: AssistantMessageBlock[],
): AssistantMessageBlock[] {
  const spec = output.spec;
  const requestedExportFormats = Array.isArray(
    spec.renderOptions?.requestedExportFormats,
  )
    ? spec.renderOptions.requestedExportFormats
        .filter(
          (format): format is "pdf" | "docx" | "xlsx" =>
            format === "pdf" || format === "docx" || format === "xlsx",
        )
        .slice(0, 3)
    : [];
  if (spec.type === "pdf") {
    const sourceDocument = sourceDocumentBlock(sourceBlocks);
    const block = buildAssistantDocumentBlock({
      title:
        sourceDocument?.title ??
        spec.title ??
        (spec.documentType === "receipt" ? "Makbuz" : "PDF Belgesi"),
      sections: sourceDocument?.sections ?? pdfDocumentSections(spec),
      format:
        sourceDocument?.format ??
        (spec.documentType === "letter" ? "letter" : "report"),
      wordCount: sourceDocument?.wordCount,
      summary: sourceDocument?.summary,
      exportFormats:
        requestedExportFormats.length > 0
          ? requestedExportFormats
          : (sourceDocument?.exportFormats ?? ["pdf"]),
      design:
        sourceDocument?.design ??
        {
          theme: "report",
          density: "comfortable",
          pageSize: "A4",
          footerText: spec.footer?.text ?? null,
        },
    }, {
      renderHints: {
        artifactId: output.artifactId,
        artifactType: "pdf",
        validationOk: output.validation.ok,
        fileName: `${safeFileSlug(spec.title ?? spec.documentType)}.pdf`,
        footer: spec.footer ?? null,
        contentSource: spec.metadata?.contentSource ?? "current_response_text",
        webSourceCount: spec.metadata?.webSourceCount ?? 0,
        documentSourceCount: spec.metadata?.documentSourceCount ?? 0,
        retrievalResultCount: spec.metadata?.retrievalResultCount ?? 0,
        skillUsed: spec.metadata?.skillUsed ?? false,
      },
    });
    return block ? [block] : [];
  }

  if (spec.type === "table") {
    const rows = spec.rows.map((row) => spec.columns.map((column) => String(row[column.key] ?? "")));
    const block = buildAssistantTableBlock({
      title: spec.title,
      columns: spec.columns.map((column) => column.label),
      rows,
      summary: spec.summary ? `${spec.summary.label}: ${JSON.stringify(spec.summary.values)}` : undefined,
    }, {
      renderHints: {
        artifactId: output.artifactId,
        artifactType: "table",
        validationOk: output.validation.ok,
        typedColumns: spec.columns,
        exportFormats: requestedExportFormats.filter(
          (format) => format === "xlsx",
        ),
        ...(requestedExportFormats.includes("xlsx")
          ? { fileName: `${safeFileSlug(spec.title ?? "elyan-tablosu")}.xlsx` }
          : {}),
      },
    });
    return block ? [block] : [];
  }

  if (spec.type === "chart") {
    const labels = spec.data.map((row) => String(row[spec.xKey ?? "label"] ?? ""));
    const values = spec.data
      .map((row) => row[spec.yKey ?? "value"])
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
    const block = buildAssistantChartBlock({
      chartType: spec.chartType,
      labels,
      values,
      data: spec.data,
      series: spec.series?.map((series) => ({
        name: series.label,
        labels,
        values,
      })),
      xLabel: spec.xKey ?? "label",
      yLabel: spec.yKey ?? "value",
      title: spec.title,
      caption: spec.description,
    }, {
      renderHints: {
        artifactId: output.artifactId,
        artifactType: "chart",
        validationOk: output.validation.ok,
      },
    });
    return block ? [block] : [];
  }

  if (spec.type === "svg" && output.output.kind === "svg") {
    const block = buildAssistantSvgBlock({
      svg: output.output.content,
      title: "SVG",
    }, {
      renderHints: {
        artifactId: output.artifactId,
        artifactType: "svg",
        validationOk: output.validation.ok,
        canvas: spec.canvas,
      },
    });
    return block ? [block] : [];
  }

  if (spec.type === "document") {
    const block = buildAssistantDocumentBlock({
      title: spec.title,
      sections: spec.sections,
      format: spec.documentType === "letter" ? "letter" : "report",
      exportFormats: spec.exportFormats ?? ["pdf", "docx"],
    }, {
      renderHints: {
        artifactId: output.artifactId,
        artifactType: "document",
        validationOk: output.validation.ok,
      },
    });
    return block ? [block] : [];
  }

  if (spec.type === "image_prompt" && output.output.kind === "text") {
    const block = buildAssistantCodeBlock({
      code: output.output.content,
      language: "text",
      title: "Görsel Promptu",
    }, {
      renderHints: {
        artifactId: output.artifactId,
        artifactType: "image_prompt",
        validationOk: output.validation.ok,
      },
    });
    return block ? [block] : [];
  }

  return [];
}

function visibleTextForArtifact(output: ArtifactOutput): string {
  if (output.type === "text" && output.output.kind === "text") {
    return output.output.content;
  }
  if (output.type === "pdf") {
    return output.validation.ok
      ? "PDF taslağı hazır. Belge bloğunu kontrol edip dışa aktarabilirsin."
      : "PDF taslağını hazırladım ama doğrulamada kontrol edilmesi gereken alanlar var.";
  }
  if (output.type === "table") {
    return output.validation.ok ? "Tablo hazır." : "Tablo taslağı hazır; doğrulama uyarılarını kontrol et.";
  }
  if (output.type === "chart") {
    return output.validation.ok ? "Grafik verisi hazır." : "Grafik taslağı hazır; veri doğrulamasını kontrol et.";
  }
  if (output.type === "svg") {
    return output.validation.ok ? "SVG taslağı hazır." : "SVG taslağı hazır; doğrulama uyarılarını kontrol et.";
  }
  if (output.type === "document") {
    return output.validation.ok ? "Belge taslağı hazır." : "Belge taslağı hazır; doğrulama uyarılarını kontrol et.";
  }
  if (output.type === "image_prompt") {
    return "Görsel promptu hazır.";
  }
  return "Artifact hazır.";
}

export function safeArtifactTelemetry(output: ArtifactOutput, extra?: { rendererUsed?: string; latencyMs?: number; repairAttempted?: boolean }) {
  return {
    artifact_type: output.type,
    intent: output.spec.intent,
    validation_ok: output.validation.ok,
    error_codes: output.validation.errors.map((error) => error.code).slice(0, 16),
    renderer_used: extra?.rendererUsed ?? null,
    latency_ms: extra?.latencyMs ?? null,
    model_used: output.spec.metadata?.model ?? null,
    repair_attempted: extra?.repairAttempted ?? false,
    content_source: output.spec.metadata?.contentSource ?? null,
    web_source_count: output.spec.metadata?.webSourceCount ?? 0,
    document_source_count: output.spec.metadata?.documentSourceCount ?? 0,
    retrieval_result_count: output.spec.metadata?.retrievalResultCount ?? 0,
    skill_used: output.spec.metadata?.skillUsed ?? false,
    skill_id: output.spec.metadata?.skillId ?? null,
    tool_call_count: output.spec.metadata?.toolCallCount ?? 0,
    user_corrected_after_output: false,
  };
}

export async function recordArtifactLearningEvent(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId?: string | null;
    output: ArtifactOutput;
    rendererUsed?: string;
    latencyMs?: number;
  },
) {
  const telemetry = safeArtifactTelemetry(input.output, {
    rendererUsed: input.rendererUsed,
    latencyMs: input.latencyMs,
  });
  await app.db.insert(learningEvents).values({
    userId: input.userId,
    accountId: input.userId,
    taskId: input.taskId ?? null,
    type: "artifact_generation",
    key: input.output.type,
    value: JSON.stringify({
      artifact_type: telemetry.artifact_type,
      validation_ok: telemetry.validation_ok,
      error_codes: telemetry.error_codes,
    }),
    confidence: input.output.validation.ok ? 86 : 55,
    scope: "user",
    source: "system",
    privacyLevel: "safe",
    metadata: telemetry,
  });
}

export function artifactResultForTask(output: ArtifactOutput, rendererUsed: string, latencyMs: number): Record<string, unknown> {
  return {
    artifactId: output.artifactId,
    type: output.type,
    spec: output.spec,
    output: output.output,
    validation: output.validation,
    telemetry: safeArtifactTelemetry(output, { rendererUsed, latencyMs }),
    specSummary: artifactSpecSummary(output.spec),
  };
}
