import type { FastifyInstance } from "fastify";
import { trStemPattern } from "../../lib/tr-word-boundary.js";
import { learningEvents } from "../../db/schema.js";
import type { ElyanAssistantDocumentBlock } from "../../contracts/domain.js";
import { withCanonicalAssistantBlockEnvelope } from "../chat/block-envelope.js";
import {
  buildAssistantChartBlock,
  buildAssistantCodeBlock,
  buildAssistantDocumentBlock,
  buildAssistantSvgBlock,
  buildAssistantTableBlock,
  type AssistantMessageBlock,
} from "../chat/message-blocks.js";
import { parseArtifactIntent } from "./parser.js";
import { asRecord, recordString } from "../../lib/record.js";
import { buildArtifactSpec, artifactSpecSummary } from "./spec-builder.js";
import type {
  ArtifactIntent,
  ArtifactOutput,
  ArtifactProvenance,
  ArtifactSpec,
  ValidationResult,
} from "./types.js";
import { authoritativeArtifactDataSchema } from "./types.js";
import { normalizeArtifactSpec } from "./normalizer.js";
import { rendererForSpec } from "./renderers/index.js";
import {
  compactText,
  escapeMarkdownTableCell,
  formatMoney,
  safeFileSlug,
} from "./utils.js";
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
        | "artifact_content_insufficient"
        // Netleştirme sorusu belge gövdesi olamaz — canlı arıza 67649401.
        | "artifact_content_is_clarification";
      latencyMs: number;
    }
  | {
      kind: "validation_failed";
      intent: ArtifactIntent;
      reason:
        | "authoritative_data_unavailable"
        | "semantic_validation_failed";
      validation: ValidationResult;
      spec?: ArtifactSpec;
      latencyMs: number;
    }
  | {
      kind: "rendered";
      intent: ArtifactIntent;
      spec: ArtifactSpec;
      output: ArtifactOutput;
      assistantBlocks: AssistantMessageBlock[];
      visibleText: string;
      ownsVisibleContent: boolean;
      rendererUsed: string;
      latencyMs: number;
    };

const SOURCE_WIDGET_BLOCK_TYPES = new Set([
  "mail_list",
  "mail_detail",
  "calendar_agenda",
  "drive_files",
  "notion_page",
  "github_activity",
  "slack_messages",
]);

function hasSourceWidget(blocks: AssistantMessageBlock[] | undefined): boolean {
  return Array.isArray(blocks) && blocks.some((block) => SOURCE_WIDGET_BLOCK_TYPES.has(block.type));
}

function urlOnlySvgBlock(
  blocks: AssistantMessageBlock[] | undefined,
): Extract<AssistantMessageBlock, { type: "svg" }> | null {
  if (!Array.isArray(blocks)) return null;
  return (
    blocks.find(
      (block): block is Extract<AssistantMessageBlock, { type: "svg" }> =>
        block.type === "svg" &&
        !String(block.svg ?? block.markup ?? "").trim() &&
        Boolean(String(block.url ?? "").trim()),
    ) ?? null
  );
}

function isSafeRemoteSvgUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && Boolean(url.hostname);
  } catch {
    return false;
  }
}

function validationFailure(code: string, message: string): ValidationResult {
  return {
    ok: false,
    errors: [{ code, message, path: "assistantBlocks", severity: "error" }],
  };
}

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
  authoritativeData?: unknown;
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
  // ÖNCEKİ TURUN ÇIKTI BİÇİMİ SONRAKİ TURA MİRAS KALMAZ.
  //
  // ÖLÇÜLEN ARIZA: bir tablo turunun ardından "Beni nasıl tanıyorsun?"
  // sorulduğunda cevap "İstenen görseli/tabloyu güvenilir veriye
  // dayandıramadığım için üretmedim." ile açılıyordu. Kullanıcı görsel de
  // tablo da istememişti — istemin KENDİSİNDE hiçbir artefakt sinyali yok
  // (`detectArtifactType` metin üzerinde `null` döner). Tip, önceki turdan
  // taşınan anlama zarfının `desired_outputs` alanından geldi.
  //
  // Kişisel durum turunun cevabı kullanıcı hakkında düzyazıdır; yetkili bir
  // VERİ KÜMESİ yoktur ve olamaz. Böyle bir turda artefakt boru hattı
  // yalnızca başarısız olabilir, ve başarısızlığı da kullanıcının hiç
  // sormadığı bir şeyin reddi olarak görünür.
  //
  // Kapı DAR: yalnız zarftan/metadata'dan MİRAS ALINAN tipi düşürür.
  // Kullanıcı o turda açıkça "bunu tablo yap" derse metin sinyali kendisi
  // oluşur ve boru hattı normal çalışır.
  const routedKnowledgeSource = recordString(
    asRecord(asRecord(input.metadata)?.knowledgeNeed),
    "source",
  );
  if (routedKnowledgeSource === "memory" || routedKnowledgeSource === "conversation") {
    const textOnlyIntent = parseArtifactIntent({ userRequest: input.userRequest });
    if (!textOnlyIntent.type) {
      return { kind: "none", intent: textOnlyIntent, latencyMs: Date.now() - startedAt };
    }
  }
  if (intent.requiresDesktopRuntime) {
    return { kind: "desktop_required", intent, latencyMs: Date.now() - startedAt };
  }
  const authoritativeDataResult =
    input.authoritativeData == null
      ? null
      : authoritativeArtifactDataSchema.safeParse(input.authoritativeData);
  if (authoritativeDataResult && !authoritativeDataResult.success) {
    return {
      kind: "validation_failed",
      intent,
      reason: "semantic_validation_failed",
      validation: validationFailure(
        "invalid_authoritative_artifact_data",
        "The authoritative artifact dataset did not match its internal contract.",
      ),
      latencyMs: Date.now() - startedAt,
    };
  }
  const authoritativeData = authoritativeDataResult?.data;
  if (
    authoritativeData &&
    intent.type !== authoritativeData.type &&
    !(intent.type === "pdf" && authoritativeData.type === "table")
  ) {
    return {
      kind: "validation_failed",
      intent,
      reason: "semantic_validation_failed",
      validation: validationFailure(
        "authoritative_artifact_type_mismatch",
        "The authoritative dataset does not match the requested artifact type.",
      ),
      latencyMs: Date.now() - startedAt,
    };
  }
  const sourceWidgetPresent = hasSourceWidget(input.assistantBlocks);
  const sourceDocumentPresent = sourceDocumentBlock(input.assistantBlocks) != null;
  const independentArtifactPresent =
    authoritativeData != null ||
    ((intent.type === "pdf" || intent.type === "document") &&
      sourceDocumentPresent) ||
    (intent.type === "svg" && urlOnlySvgBlock(input.assistantBlocks) == null &&
      input.assistantBlocks?.some((block) => block.type === "svg") === true);
  if (
    sourceWidgetPresent &&
    !independentArtifactPresent
  ) {
    return { kind: "none", intent, latencyMs: Date.now() - startedAt };
  }
  if (intent.type === "svg") {
    const remoteSvg = urlOnlySvgBlock(input.assistantBlocks);
    if (remoteSvg) {
      return isSafeRemoteSvgUrl(remoteSvg.url ?? "")
        ? { kind: "none", intent, latencyMs: Date.now() - startedAt }
        : {
            kind: "validation_failed",
            intent,
            reason: "semantic_validation_failed",
            validation: validationFailure(
              "unsafe_svg_url",
              "Remote SVG URLs must use a valid HTTPS origin.",
            ),
            latencyMs: Date.now() - startedAt,
          };
    }
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
  // BELGE, ELDEKİ HERHANGİ BİR METİN DEĞİLDİR.
  //
  // Canlı arıza (görev 67649401, 2026-08-22 16:34 — "masaüstüne zürafalar
  // hakkında bir pdf hazırla ve kaydet"): model netleştirme sorusu döndürdü
  // ("Netleştireyim: tam olarak neyi yapmamı istiyorsun?") ve bu SORU PDF'in
  // gövdesi olarak basıldı. Görev "PDF Belgesi hazır." diye BAŞARILI raporlandı.
  //
  // Asgari içerik kapısı zaten vardı ama YALNIZ araştırma artefaktlarında
  // çalışıyordu (`researchArtifactRequested`). Sıradan bir "pdf hazırla"
  // isteğinde 50 karakterlik bir soru belge oldu.
  //
  // İki kapı, ikisi de gövde metnine bakar:
  // ASGARİ UZUNLUK KAPISI DENENDİ VE GERİ ALINDI: "bu içeriği word yap" gibi
  // meşru kısa dönüşümler 70 karakterlik gövdeyle geliyor (mevcut testler bunu
  // koruyor). Ayırt edici olan uzunluk değil, metnin SORU olması.
  if (intent.type === "pdf" || intent.type === "document") {
    // Gövde metni BOŞSA burası karar vermez: içerik kullanıcı isteğinden
    // deterministik olarak da türetilebiliyor (fiş/irsaliye yolu, responseText
    // hiç yok). Bu kapı yalnız ELDE BİR CEVAP METNİ VARKEN konuşur.
    const bodyText = artifactSourceText(input);
    if (bodyText.length > 0 && isClarificationText(bodyText)) {
      return {
        kind: "evidence_required",
        intent,
        reason: "artifact_content_is_clarification",
        latencyMs: Date.now() - startedAt,
      };
    }
  }
  const rawSpec = buildArtifactSpec({
    ...input,
    intent,
    authoritativeData,
  });
  if (!rawSpec) {
    return {
      kind: "validation_failed",
      intent,
      reason: "authoritative_data_unavailable",
      validation: validationFailure(
        intent.type === "table"
          ? "authoritative_table_data_unavailable"
          : intent.type === "chart"
            ? "authoritative_chart_data_unavailable"
            : "authoritative_artifact_data_unavailable",
        "The requested artifact could not be built from complete authoritative data.",
      ),
      latencyMs: Date.now() - startedAt,
    };
  }
  const spec = normalizeArtifactSpec(rawSpec);
  const renderer = rendererForSpec(spec);
  const output = await renderer.render(spec);
  if (!output.validation.ok) {
    return {
      kind: "validation_failed",
      intent,
      reason: "semantic_validation_failed",
      spec,
      validation: output.validation,
      latencyMs: Date.now() - startedAt,
    };
  }
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
    ownsVisibleContent: assistantBlocks.some((block) => block.type !== "text"),
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

/**
 * Metin bir cevap mı, yoksa kullanıcıya sorulmuş bir soru mu?
 *
 * Soru gövde olamaz. Tek sinyal noktalama değil; "netleştireyim/hangisini
 * istersin" gibi açılışlar soru işareti olmadan da netleştirmedir.
 */
function isClarificationText(text: string): boolean {
  const normalized = text.trim();
  if (!normalized) return false;
  if (/\?\s*$/u.test(normalized)) return true;
  return trStemPattern([
    "netleştir",
    "netlestir",
    "hangisini",
    "hangi biçim",
    "hangi format",
    "tam olarak ne",
    "biraz daha detay",
    "clarify",
    "could you specify",
  ]).test(normalized);
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
  const tables = spec.blocks.filter((block) => block.type === "table");
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
  for (const table of tables) {
    const columns = table.columns ?? [];
    const rows = table.rows ?? [];
    if (columns.length === 0 || rows.length === 0) continue;
    sections.push({
      heading: spec.title ?? "Tablo",
      level: 1,
      content: [
        `| ${columns.map((column) => escapeMarkdownTableCell(column.label)).join(" | ")} |`,
        `| ${columns.map(() => "---").join(" | ")} |`,
        ...rows.map(
          (row) =>
            `| ${columns.map((column) => escapeMarkdownTableCell(row[column.key])).join(" | ")} |`,
        ),
      ].join("\n"),
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
    if (body) sections.push({ content: body, level: 1 });
  }
  return sections;
}

function deterministicPreview<T>(values: T[], limit = 240): T[] {
  if (values.length <= limit) return [...values];
  const indexes = Array.from({ length: limit }, (_, index) =>
    Math.round((index * (values.length - 1)) / (limit - 1)),
  );
  return indexes.map((index) => values[index]!);
}

function authoritativeSourceBlock(
  type: ArtifactOutput["type"],
  sourceBlocks: AssistantMessageBlock[] | undefined,
  renderHints: Record<string, unknown>,
): AssistantMessageBlock | null {
  if (!Array.isArray(sourceBlocks)) return null;
  const sourceType = type === "document" || type === "pdf" ? "document_block" : type;
  const source = sourceBlocks.find((block) => block.type === sourceType);
  if (!source) return null;
  const base = {
    ...source,
    renderHints: {
      ...((source as { renderHints?: Record<string, unknown> }).renderHints ?? {}),
      ...renderHints,
    },
  } as AssistantMessageBlock & Record<string, unknown>;
  const finalize = (
    block: AssistantMessageBlock & Record<string, unknown>,
  ): AssistantMessageBlock =>
    withCanonicalAssistantBlockEnvelope(block) as AssistantMessageBlock;
  if (source.type === "table") {
    return finalize({
      ...base,
      interactions: (source.interactions ?? []).filter(
        (interaction: string) => interaction !== "fullscreen",
      ),
    } as AssistantMessageBlock & Record<string, unknown>);
  }
  if (source.type === "chart") {
    const labels = Array.isArray(source.labels) ? source.labels : [];
    const values = Array.isArray(source.values) ? source.values : [];
    const aligned = labels.length > 0 && labels.length === values.length;
    const pairs: Array<{ label: string; value: number }> = aligned
      ? labels.map((label: string, index: number) => ({
          label,
          value: values[index]!,
        }))
      : [];
    const sampledPairs = deterministicPreview(pairs);
    return finalize({
      ...base,
      ...(sampledPairs.length > 0
        ? {
            labels: sampledPairs.map((item) => item.label),
            values: sampledPairs.map((item) => item.value),
          }
        : {}),
      ...(Array.isArray(source.data)
        ? { data: deterministicPreview(source.data) }
        : {}),
      ...(Array.isArray(source.points)
        ? { points: deterministicPreview(source.points) }
        : {}),
      interactions: (source.interactions ?? []).filter(
        (interaction: string) => interaction !== "fullscreen",
      ),
    } as AssistantMessageBlock & Record<string, unknown>);
  }
  return finalize(base);
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
    const sourceTable = !sourceDocument
      ? authoritativeSourceBlock("table", sourceBlocks, {
          artifactId: output.artifactId,
          artifactType: "pdf",
          validationOk: output.validation.ok,
          exportFormats:
            requestedExportFormats.length > 0
              ? requestedExportFormats
              : ["pdf"],
          fileName: `${safeFileSlug(spec.title ?? spec.documentType)}.pdf`,
        })
      : null;
    // A PDF generated from a typed table must keep that exact table as the
    // visible source widget. The PDF recipe below owns export/layout only; it
    // must not replace the table with guessed prose or a generic document.
    if (sourceTable) return [sourceTable];
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
    const authoritative =
      spec.metadata?.sourceAuthority === "tool_connector"
        ? null
        : authoritativeSourceBlock(
            "table",
            sourceBlocks,
            {
              artifactId: output.artifactId,
              artifactType: "table",
              validationOk: true,
              typedColumns: spec.columns,
              exportFormats: requestedExportFormats.filter(
                (format) => format === "xlsx",
              ),
            },
          );
    if (authoritative) return [authoritative];
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
        sourceRowCount: spec.rows.length,
        visibleRowCount: Math.min(spec.rows.length, 80),
        sourceAuthority: spec.metadata?.sourceAuthority ?? null,
        sourceProducerId: spec.metadata?.sourceProducerId ?? null,
        sourceResultDigest: spec.metadata?.sourceResultDigest ?? null,
        exportFormats: requestedExportFormats.filter(
          (format) => format === "xlsx",
        ),
        ...(requestedExportFormats.includes("xlsx")
          ? { fileName: `${safeFileSlug(spec.title ?? "elyan-tablosu")}.xlsx` }
          : {}),
      },
    });
    return block
      ? [{
          ...block,
          previewRows: rows.slice(0, 20),
          totalRowCount: spec.rows.length,
        }]
      : [];
  }

  if (spec.type === "chart") {
    const authoritative =
      spec.metadata?.sourceAuthority === "tool_connector"
        ? null
        : authoritativeSourceBlock(
            "chart",
            sourceBlocks,
            {
              artifactId: output.artifactId,
              artifactType: "chart",
              validationOk: true,
              sampled: spec.data.length > 240,
              sourcePointCount: spec.data.length,
              previewPointCount: Math.min(spec.data.length, 240),
            },
          );
    if (authoritative) return [authoritative];
    const previewData = deterministicPreview(spec.data);
    const labels = previewData.map((row) => String(row[spec.xKey ?? "label"] ?? ""));
    const values = previewData
      .map((row) => row[spec.yKey ?? "value"])
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
    const block = buildAssistantChartBlock({
      chartType: spec.chartType,
      labels,
      values,
      data: previewData,
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
        sampled: spec.data.length > previewData.length,
        sourcePointCount: spec.data.length,
        previewPointCount: previewData.length,
        sourceAuthority: spec.metadata?.sourceAuthority ?? null,
        sourceProducerId: spec.metadata?.sourceProducerId ?? null,
        sourceResultDigest: spec.metadata?.sourceResultDigest ?? null,
      },
    });
    return block ? [block] : [];
  }

  if (spec.type === "svg" && output.output.kind === "svg") {
    const authoritative = authoritativeSourceBlock(
      "svg",
      sourceBlocks,
      {
        artifactId: output.artifactId,
        artifactType: "svg",
        validationOk: true,
        canvas: spec.canvas,
      },
    );
    if (authoritative) return [authoritative];
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
    source_authority: output.spec.metadata?.sourceAuthority ?? null,
    semantic_validation_ok: output.validation.ok,
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
