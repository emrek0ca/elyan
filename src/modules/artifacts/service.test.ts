import test from "node:test";
import assert from "node:assert/strict";
import type { ElyanAssistantDocumentBlock } from "../../contracts/domain.js";
import { buildTypedUnderstandingEnvelope } from "../../core/understanding/understanding-envelope.js";
import type { IntentClassification } from "../../core/understanding/types.js";
import { buildArtifactPipeline } from "./service.js";
import { artifactSpecToRenderRecipeBlocks } from "./render-recipe-adapter.js";
import {
  buildAssistantChartBlock,
  buildAssistantSvgBlock,
  buildAssistantTableBlock,
} from "../chat/message-blocks.js";

function documentIntent(): IntentClassification {
  return {
    primaryIntent: "document",
    secondaryIntents: [],
    requiresLocalRuntime: false,
    requiresRetrieval: false,
    requiresToolUse: false,
    requiresCitation: false,
    requiresLongRunningTask: false,
    privacyRisk: "low",
    confidence: 0.92,
    reason: "artifact_test",
    taskFrame: {
      goal: "create artifact",
      likelyAnswerShape: "typed artifact",
      reasoningMode: "balanced",
      shouldClarify: false,
    },
    ecosystemHints: [],
    routingHints: {
      mode: "task",
      preferredCapabilities: [],
      avoidCloud: false,
      requiresLocalRuntime: false,
    },
  };
}

test("artifact pipeline builds a validated PDF receipt with footer", async () => {
  const result = await buildArtifactPipeline({
    userRequest:
      "Toplam 18 kapı tamiri =18.000tl Gadet kapı menteşesi =3000tl Genel toplam = 21.000tl En alta Metin cam Metin Koca yazsın.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "pdf");
  assert.equal(result.spec.type, "pdf");
  if (result.spec.type !== "pdf") return;
  assert.equal(
    result.spec.blocks.filter((block) => block.type === "line_item").length,
    2,
  );
  assert.equal(
    result.spec.blocks.find((block) => block.type === "total")?.amount,
    21_000,
  );
  assert.equal(result.spec.footer?.text, "Metin cam Metin Koca");
  assert.equal(result.output.validation.ok, true);
});

test("artifact pipeline builds typed table rows and numeric values", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Şunları tablo yap: Ocak 12000, Şubat 18000, Mart 15000.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "table");
  assert.equal(result.spec.type, "table");
  if (result.spec.type !== "table") return;
  assert.deepEqual(
    result.spec.columns.map((column) => column.key),
    ["label", "value"],
  );
  assert.equal(result.spec.rows.length, 3);
  assert.equal(result.spec.rows[1]?.value, 18_000);
});

test("artifact pipeline preserves the authoritative typed table for the reported square-table regression", async () => {
  const table = buildAssistantTableBlock({
    title: "Sayıların Kareleri",
    columns: ["Sayı", "Kare"],
    rows: [
      ["1", "1"],
      ["2", "4"],
      ["3", "9"],
    ],
  });
  assert.ok(table);

  const result = await buildArtifactPipeline({
    userRequest:
      "1,2 ve 3 sayılarının karelerini sayı ve kare sütunlarıyla tablo halinde göster. JSON yazma",
    assistantBlocks: [table],
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "table");
  if (result.spec.type !== "table") return;
  assert.deepEqual(
    result.spec.columns.map((column) => column.label),
    ["Sayı", "Kare"],
  );
  assert.deepEqual(result.spec.rows, [
    { sayi: 1, kare: 1 },
    { sayi: 2, kare: 4 },
    { sayi: 3, kare: 9 },
  ]);
  const renderedTable = result.assistantBlocks.find(
    (block) => block.type === "table",
  );
  assert.equal(renderedTable?.type, "table");
  if (renderedTable?.type !== "table") return;
  assert.deepEqual(renderedTable.columns, ["Sayı", "Kare"]);
  assert.deepEqual(renderedTable.rows, [
    ["1", "1"],
    ["2", "4"],
    ["3", "9"],
  ]);
  assert.deepEqual(renderedTable.interactions, ["sort", "copy", "share"]);
  assert.ok(renderedTable.stableBlockId);
  assert.ok(renderedTable.cacheDigest);
  assert.equal(result.ownsVisibleContent, true);
  assert.equal(result.spec.metadata?.sourceAuthority, "model_typed_block");
  assert.equal(result.output.validation.ok, true);
});

test("artifact pipeline rejects a structurally valid table with incorrect square values", async () => {
  const table = buildAssistantTableBlock({
    columns: ["Sayı", "Kare"],
    rows: [
      ["1", "1"],
      ["2", "3"],
      ["3", "9"],
    ],
  });
  assert.ok(table);

  const result = await buildArtifactPipeline({
    userRequest:
      "1,2 ve 3 sayılarının karelerini sayı ve kare sütunlarıyla tablo halinde göster.",
    assistantBlocks: [table],
  });

  assert.equal(result.kind, "validation_failed");
  if (result.kind !== "validation_failed") return;
  assert.equal(result.reason, "semantic_validation_failed");
  assert.equal(
    result.validation.errors.some(
      (error) => error.code === "unsafe_math_mismatch",
    ),
    true,
  );
});

test("artifact pipeline marks typed tool data above model or prompt authority", async () => {
  const table = buildAssistantTableBlock(
    {
      columns: ["Ay", "Gelir"],
      rows: [
        ["Ocak", "12000"],
        ["Şubat", "18000"],
      ],
    },
    {
      renderHints: {
        contentOwner: "tool",
        producerId: "web.numeric_facts",
        resultDigest: "0123456789abcdef0123456789abcdef",
      },
    },
  );
  assert.ok(table);

  const result = await buildArtifactPipeline({
    userRequest: "Ocak ve Şubat gelirlerini tablo halinde göster.",
    assistantBlocks: [table],
    authoritativeData: {
      type: "table",
      columns: [
        { key: "ay", label: "Ay", dataType: "string", required: true },
        { key: "gelir", label: "Gelir", dataType: "number", required: true },
      ],
      rows: [
        { ay: "Ocak", gelir: 12000 },
        { ay: "Şubat", gelir: 18000 },
      ],
      source: {
        authority: "tool_connector",
        producerId: "web.numeric_facts",
        resultDigest: "0123456789abcdef0123456789abcdef",
      },
    },
    provenance: { toolCallCount: 1, skillUsed: true, skillId: "document_qa" },
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.metadata?.sourceAuthority, "tool_connector");
  assert.equal(
    result.spec.metadata?.contentSource,
    "authoritative_structured_data",
  );
});

test("request-wide tool counters cannot promote an unproven model block", async () => {
  const table = buildAssistantTableBlock({
    columns: ["Ay", "Gelir"],
    rows: [
      ["Ocak", "12000"],
      ["Şubat", "18000"],
    ],
  });
  assert.ok(table);
  const result = await buildArtifactPipeline({
    userRequest: "Ocak: 12000 ve Şubat: 18000 verisini tablo halinde göster.",
    assistantBlocks: [table],
    provenance: { toolCallCount: 1 },
  });
  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.metadata?.sourceAuthority, "model_typed_block");
});

test("screenshot regression deterministically produces Sayı/Kare when the model omits a block", async () => {
  const result = await buildArtifactPipeline({
    userRequest:
      "1,2 ve 3 sayılarının karelerini sayı ve kare sütunlarıyla tablo halinde göster. JSON yazma",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  const table = result.assistantBlocks.find((block) => block.type === "table");
  assert.equal(table?.type, "table");
  if (table?.type !== "table") return;
  assert.deepEqual(table.columns, ["Sayı", "Kare"]);
  assert.deepEqual(table.rows, [
    ["1", "1"],
    ["2", "4"],
    ["3", "9"],
  ]);
  assert.equal(result.spec.metadata?.sourceAuthority, "deterministic_prompt");
});

test("an incomplete natural-language number list still fails closed", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "1,2 ve 3 sayılarını tablo halinde göster.",
  });
  assert.equal(result.kind, "validation_failed");
  if (result.kind !== "validation_failed") return;
  assert.equal(result.reason, "authoritative_data_unavailable");
});

test("artifact pipeline maps explicit Word output to the existing document artifact", async () => {
  const userRequest =
    "Bu içeriği Word dosyası olarak oluştur: Proje durumu planlandığı gibi ilerliyor.";
  const understandingEnvelope = buildTypedUnderstandingEnvelope({
    userId: "user_1",
    message: userRequest,
    intent: documentIntent(),
  });
  const result = await buildArtifactPipeline({
    userRequest,
    understandingEnvelope,
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "document");
  if (result.spec.type !== "document") return;
  assert.deepEqual(result.intent.requestedFormats, ["docx"]);
  assert.deepEqual(result.spec.exportFormats, ["docx"]);
  const document = result.assistantBlocks.find(
    (block) => block.type === "document_block",
  ) as ElyanAssistantDocumentBlock | undefined;
  assert.deepEqual(document?.exportFormats, ["docx"]);
});

test("artifact pipeline preserves multiple requested document export formats", async () => {
  const userRequest =
    "Bu raporu önce Word sonra PDF olarak oluştur: Gelirler istikrarlı biçimde artıyor.";
  const understandingEnvelope = buildTypedUnderstandingEnvelope({
    userId: "user_1",
    message: userRequest,
    intent: documentIntent(),
  });
  const result = await buildArtifactPipeline({
    userRequest,
    understandingEnvelope,
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "document");
  if (result.spec.type !== "document") return;
  assert.deepEqual(result.intent.requestedOutputKinds, ["docx", "pdf"]);
  assert.deepEqual(result.spec.exportFormats, ["docx", "pdf"]);
  assert.deepEqual(
    result.intent.desiredOutputs.map((output) => ({
      kind: output.kind,
      format: output.format,
      confidence: output.confidence,
    })),
    [
      { kind: "docx", format: "docx", confidence: 0.92 },
      { kind: "pdf", format: "pdf", confidence: 0.94 },
    ],
  );
});

test("document artifact uses completed response content instead of the generation instruction", async () => {
  const userRequest = "Bu içeriği Word dosyası olarak oluştur";
  const result = await buildArtifactPipeline({
    userRequest,
    responseText:
      "Proje planlandığı gibi ilerliyor ve tüm kilometre taşları tamamlandı.",
    understandingEnvelope: buildTypedUnderstandingEnvelope({
      userId: "user_1",
      message: userRequest,
      intent: documentIntent(),
    }),
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "document");
  if (result.spec.type !== "document") return;
  assert.equal(
    result.spec.sections[0]?.content,
    "Proje planlandığı gibi ilerliyor ve tüm kilometre taşları tamamlandı.",
  );
  assert.doesNotMatch(
    result.spec.sections[0]?.content ?? "",
    /belgesi hazırla/i,
  );
});

test("document artifact fails closed when neither typed nor completed content exists", async () => {
  const userRequest = "Bu içeriği Word dosyası olarak oluştur";
  const result = await buildArtifactPipeline({
    userRequest,
    understandingEnvelope: buildTypedUnderstandingEnvelope({
      userId: "user_1",
      message: userRequest,
      intent: documentIntent(),
    }),
  });

  assert.equal(result.kind, "validation_failed");
  if (result.kind !== "validation_failed") return;
  assert.equal(result.reason, "authoritative_data_unavailable");
});

test("artifact pipeline never replaces authoritative source widgets with a generic table", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Gelen kutumdaki son mailleri tablo halinde göster",
    assistantBlocks: [{ type: "mail_list" } as never],
    provenance: { toolCallCount: 1 },
  });

  assert.equal(result.kind, "none");
});

test("artifact pipeline carries Excel export intent into the existing table block", async () => {
  const userRequest =
    "Ocak 12000, Şubat 18000, Mart 15000 verileriyle Excel tablo oluştur.";
  const understandingEnvelope = buildTypedUnderstandingEnvelope({
    userId: "user_1",
    message: userRequest,
    intent: documentIntent(),
  });
  const result = await buildArtifactPipeline({
    userRequest,
    understandingEnvelope,
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "table");
  const table = result.assistantBlocks.find(
    (block) => block.type === "table",
  ) as Record<string, unknown> | undefined;
  const renderHints = table?.renderHints as Record<string, unknown> | undefined;
  assert.deepEqual(renderHints?.exportFormats, ["xlsx"]);
  assert.match(String(renderHints?.fileName ?? ""), /\.xlsx$/);
});

test("authoritative table keeps 500 artifact rows while mobile receives 80 with a 20-row preview", async () => {
  const rows = Array.from({ length: 500 }, (_, index) => ({
    sayi: index + 1,
    kare: (index + 1) ** 2,
  }));
  const result = await buildArtifactPipeline({
    userRequest: "Sayı ve Kare sütunlarıyla Excel tablo oluştur.",
    authoritativeData: {
      type: "table",
      columns: [
        { key: "sayi", label: "Sayı", dataType: "number", required: true },
        { key: "kare", label: "Kare", dataType: "number", required: true },
      ],
      rows,
      source: {
        authority: "tool_connector",
        producerId: "web.numeric_facts",
        resultDigest: "abcdef0123456789abcdef0123456789",
      },
    },
  });
  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered" || result.spec.type !== "table") return;
  assert.equal(result.spec.rows.length, 500);
  const table = result.assistantBlocks.find((block) => block.type === "table");
  assert.equal(table?.type, "table");
  if (table?.type !== "table") return;
  assert.equal(table.rows.length, 80);
  assert.equal(table.previewRows?.length, 20);
  assert.equal(table.totalRowCount, 500);
  const recipeTable = artifactSpecToRenderRecipeBlocks(result.spec).find(
    (block) => block.type === "table",
  );
  assert.equal(recipeTable?.tableRows?.length, 500);
  assert.deepEqual(recipeTable?.tableRows?.at(-1), ["500", "250000"]);
});

test("artifact pipeline builds chart data without fake rows", async () => {
  const result = await buildArtifactPipeline({
    userRequest:
      "Ocak 12000, Şubat 18000, Mart 15000 verisiyle gelir grafiği çiz.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "chart");
  assert.equal(result.spec.type, "chart");
  if (result.spec.type !== "chart") return;
  assert.equal(result.spec.chartType, "bar");
  assert.equal(result.spec.xKey, "label");
  assert.equal(result.spec.yKey, "value");
  assert.equal(result.spec.data.length, 3);
});

test("artifact pipeline keeps full chart data in the spec and emits a bounded deterministic mobile preview", async () => {
  const data = Array.from({ length: 1_500 }, (_, index) => ({
    label: `N${index + 1}`,
    value: index + 1,
  }));
  const chart = buildAssistantChartBlock({
    chartType: "line",
    labels: [],
    values: [],
    data,
    title: "Büyük Seri",
  });
  assert.ok(chart);
  const result = await buildArtifactPipeline({
    userRequest: "Bu verileri çizgi grafik olarak göster",
    assistantBlocks: [chart],
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "chart");
  if (result.spec.type !== "chart") return;
  assert.equal(result.spec.data.length, 1_500);
  const rendered = result.assistantBlocks.find(
    (block) => block.type === "chart",
  );
  assert.equal(rendered?.type, "chart");
  if (rendered?.type !== "chart") return;
  assert.equal(rendered.data?.length, 240);
  assert.deepEqual(rendered.data?.[0], data[0]);
  assert.deepEqual(rendered.data?.at(-1), data.at(-1));
});

test("artifact pipeline builds bounded SVG with text element", async () => {
  const result = await buildArtifactPipeline({
    userRequest:
      "1024x1024 SVG içinde ortada Elyan yazan sade logo taslağı oluştur.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "svg");
  assert.equal(result.spec.type, "svg");
  if (result.spec.type !== "svg") return;
  assert.equal(result.spec.canvas.width, 1024);
  assert.equal(result.spec.canvas.height, 1024);
  assert.equal(result.spec.canvas.viewBox, "0 0 1024 1024");
  assert.equal(
    result.spec.elements.some((element) => element.type === "text"),
    true,
  );
  assert.equal(result.output.output.kind, "svg");
});

test("artifact pipeline preserves safe authoritative SVG markup exactly", async () => {
  const markup =
    '<svg viewBox="0 0 32 16" xmlns="http://www.w3.org/2000/svg"><rect width="32" height="16" fill="#123127"/></svg>';
  const svg = buildAssistantSvgBlock({ svg: markup, title: "Elyan İşareti" });
  assert.ok(svg);

  const result = await buildArtifactPipeline({
    userRequest: "Bu SVG görselini oluştur.",
    assistantBlocks: [svg],
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "svg");
  if (result.spec.type !== "svg") return;
  assert.equal(result.spec.markup, markup);
  assert.equal(result.output.output.kind, "svg");
  if (result.output.output.kind !== "svg") return;
  assert.equal(result.output.output.content, markup);
});

test("artifact pipeline fails closed on unsafe authoritative SVG markup", async () => {
  const svg = buildAssistantSvgBlock({
    svg: '<svg viewBox="0 0 32 16"><script>alert(1)</script></svg>',
  });
  assert.ok(svg);

  const result = await buildArtifactPipeline({
    userRequest: "Bu SVG görselini oluştur.",
    assistantBlocks: [svg],
  });

  assert.equal(result.kind, "validation_failed");
  if (result.kind !== "validation_failed") return;
  assert.equal(result.reason, "semantic_validation_failed");
  assert.equal(
    result.validation.errors.some(
      (error) => error.code === "unsafe_svg_markup",
    ),
    true,
  );
});

test("artifact pipeline rejects non-allowlisted static SVG tags", async () => {
  const svg = buildAssistantSvgBlock({
    svg: '<svg viewBox="0 0 32 16"><feImage href="https://evil.example/x"/></svg>',
  });
  assert.ok(svg);
  const result = await buildArtifactPipeline({
    userRequest: "Bu SVG görselini oluştur.",
    assistantBlocks: [svg],
  });
  assert.equal(result.kind, "validation_failed");
});

test("an independent typed document can export beside a source widget", async () => {
  const document: ElyanAssistantDocumentBlock = {
    type: "document_block",
    title: "Kaynaklı Rapor",
    sections: [{ heading: "Özet", content: "Doğrulanmış içerik", level: 1 }],
  } as ElyanAssistantDocumentBlock;
  const result = await buildArtifactPipeline({
    userRequest: "Bu raporu PDF olarak oluştur.",
    assistantBlocks: [{ type: "mail_list" } as never, document],
  });
  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "pdf");
});

test("PDF export from a typed table preserves the same visible table and full recipe data", async () => {
  const table = buildAssistantTableBlock({
    title: "Sayıların Kareleri",
    columns: ["Sayı", "Kare"],
    rows: [
      ["1", "1"],
      ["2", "4"],
      ["3", "9"],
    ],
  });
  assert.ok(table);

  const result = await buildArtifactPipeline({
    userRequest:
      "1,2 ve 3 sayılarının karelerini sayı ve kare sütunlarıyla PDF olarak oluştur.",
    assistantBlocks: [table],
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "pdf");
  if (result.spec.type !== "pdf") return;
  const pdfTable = result.spec.blocks.find((block) => block.type === "table");
  assert.equal(pdfTable?.type, "table");
  if (pdfTable?.type !== "table") return;
  assert.deepEqual(pdfTable.rows, [
    { sayi: 1, kare: 1 },
    { sayi: 2, kare: 4 },
    { sayi: 3, kare: 9 },
  ]);
  assert.equal(result.assistantBlocks.length, 1);
  assert.equal(result.assistantBlocks[0]?.type, "table");
  if (result.assistantBlocks[0]?.type !== "table") return;
  assert.deepEqual(result.assistantBlocks[0].columns, ["Sayı", "Kare"]);
  assert.deepEqual(result.assistantBlocks[0].rows, [
    ["1", "1"],
    ["2", "4"],
    ["3", "9"],
  ]);
  assert.deepEqual(
    (result.assistantBlocks[0].renderHints as Record<string, unknown>)
      .exportFormats,
    ["pdf"],
  );
  assert.equal(result.output.output.kind, "json");
  if (result.output.output.kind !== "json") return;
  assert.match(
    String((result.output.output.content as Record<string, unknown>).markdown),
    /\| 2 \| 4 \|/,
  );
});

test("artifact pipeline renders professional text without unrelated additions", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Bunu daha profesyonel mesaj yap: Abi işi yarın bitiririm.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "text");
  assert.equal(result.spec.type, "text");
  if (result.spec.type !== "text") return;
  assert.equal(result.spec.tone, "formal");
  assert.equal(result.output.output.kind, "text");
  if (result.output.output.kind !== "text") return;
  assert.equal(
    result.output.output.content,
    "Merhaba, işi yarın tamamlayacağım.",
  );
});

test("artifact pipeline detects wrong PDF total", async () => {
  const result = await buildArtifactPipeline({
    userRequest:
      "Kapı tamiri 18000 TL, menteşe 3000 TL, genel toplam 22000 TL.",
  });

  assert.equal(result.kind, "validation_failed");
  if (result.kind !== "validation_failed") return;
  assert.equal(result.reason, "semantic_validation_failed");
  assert.equal(
    result.validation.errors.some((error) => error.code === "total_mismatch"),
    true,
  );
  assert.ok(result.spec);
  if (!result.spec || result.spec.type !== "pdf") return;
  const computed = result.spec.blocks
    .filter((block) => block.type === "line_item")
    .reduce(
      (sum, block) => sum + ((block as { amount?: number }).amount ?? 0),
      0,
    );
  assert.equal(computed, 21_000);
});

test("artifact pipeline does not turn ordinary sum questions into PDF", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Bunların toplamı kaç eder?",
  });

  assert.equal(result.kind, "none");
});

test("artifact pipeline requires desktop runtime for private local PDF requests", async () => {
  const result = await buildArtifactPipeline({
    userRequest:
      "Bilgisayarımdaki son PDF’i özetle ve PDF olarak geri hazırla.",
  });

  assert.equal(result.kind, "desktop_required");
  assert.equal(result.intent.requiresDesktopRuntime, true);
  assert.equal(result.intent.type, "pdf");
});

test("research PDF uses the current typed document instead of the previous assistant text", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Kedilerin tarihini araştırıp PDF olarak ver",
    responseText: "Merhaba Osman Emre Koca, ben buradayım.",
    taskId: "task-cat-history",
    assistantBlocks: [
      {
        type: "document_block",
        title: "Kedilerin Tarihi",
        format: "report",
        exportFormats: ["pdf", "docx"],
        sections: [
          {
            heading: "Evcilleşmenin Başlangıcı",
            level: 1,
            content:
              "Arkeolojik ve genetik bulgular, evcil kedinin Yakın Doğu yaban kedisi soyundan geldiğini gösterir. Tarım topluluklarındaki tahıl depolarının kemirgenleri çekmesi, insanlarla kediler arasında karşılıklı faydaya dayalı uzun bir yakınlaşma başlatmıştır.",
          },
          {
            heading: "Antik Dünyadan Günümüze",
            level: 1,
            content:
              "Kediler Mısır'da güçlü bir kültürel konum kazanmış, ticaret ve deniz yollarıyla Akdeniz'e yayılmıştır. Sonraki yüzyıllarda limanlarda ve kentlerde kemirgen kontrolüne katkı sağlarken zamanla ev arkadaşı kimliği de güçlenmiştir.",
          },
        ],
      },
    ],
    provenance: {
      webGroundingUsed: true,
      webSourceCount: 4,
      retrievalResultCount: 3,
      skillUsed: true,
      skillId: "document_summary",
      toolCallCount: 1,
    },
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.spec.type, "pdf");
  if (result.spec.type !== "pdf") return;
  assert.equal(result.spec.title, "Kedilerin Tarihi");
  assert.equal(result.spec.metadata?.contentSource, "assistant_typed_block");
  assert.equal(result.spec.metadata?.webSourceCount, 4);
  assert.equal(result.spec.metadata?.retrievalResultCount, 3);
  assert.equal(result.spec.metadata?.skillId, "document_summary");
  assert.equal(result.spec.metadata?.toolCallCount, 1);
  const document = result.assistantBlocks.find(
    (block) => block.type === "document_block",
  ) as ElyanAssistantDocumentBlock | undefined;
  assert.equal(document?.type, "document_block");
  if (document?.type !== "document_block") return;
  assert.equal(document.title, "Kedilerin Tarihi");
  assert.deepEqual(document.exportFormats, ["pdf"]);
  assert.match(document.sections[0]?.content ?? "", /Yakın Doğu yaban kedisi/i);
  assert.doesNotMatch(
    document.sections.map((section) => section.content).join(" "),
    /Merhaba Osman Emre Koca/i,
  );
});

test("research PDF fails closed when grounding evidence is unavailable", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Kedilerin tarihini araştırıp PDF olarak ver",
    responseText: "Merhaba Osman Emre Koca, ben buradayım.",
  });

  assert.equal(result.kind, "evidence_required");
  if (result.kind !== "evidence_required") return;
  assert.equal(result.reason, "grounding_evidence_unavailable");
});

test("research PDF fails closed when grounded content is too short to render", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Kedilerin tarihini araştırıp PDF olarak ver",
    responseText: "Kısa ve eksik araştırma notu.",
    provenance: {
      webGroundingUsed: true,
      webSourceCount: 1,
    },
  });

  assert.equal(result.kind, "evidence_required");
  if (result.kind !== "evidence_required") return;
  assert.equal(result.reason, "artifact_content_insufficient");
});

test("long model prose cannot become a research PDF without web or RAG evidence", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Kedilerin tarihini araştırıp PDF olarak ver",
    responseText:
      "Kedilerin evcilleşmesi tarım toplumlarıyla başlayan uzun bir süreçtir. İnsan yerleşimlerindeki tahıl depoları kemirgenleri çekmiş, kediler de bu ortamda insanlarla karşılıklı faydaya dayalı bir yakınlık geliştirmiştir. Antik dönemlerden modern kent yaşamına kadar kedilerin kültürel rolü giderek çeşitlenmiştir.",
    assistantBlocks: [
      {
        type: "document_block",
        title: "Kedilerin Tarihi",
        sections: [
          {
            heading: "Tarihçe",
            content:
              "Kedilerin evcilleşmesi tarım toplumlarıyla başlayan uzun bir süreçtir. İnsan yerleşimlerindeki tahıl depoları kemirgenleri çekmiş, kediler de bu ortamda insanlarla karşılıklı faydaya dayalı bir yakınlık geliştirmiştir. Antik dönemlerden modern kent yaşamına kadar kedilerin kültürel rolü giderek çeşitlenmiştir.",
          },
        ],
      },
    ],
  });

  assert.equal(result.kind, "evidence_required");
  if (result.kind !== "evidence_required") return;
  assert.equal(result.reason, "grounding_evidence_unavailable");
});

test("word/docx istekleri belge artefaktı üretir (ekli isimlerle birlikte)", async () => {
  // PRODÜKSİYON VAKASI: "raporunu word belgesi olarak hazırla" hiçbir artefakt
  // üretmiyordu. İki kusur: (1) `word`/`docx` desende hiç yoktu, (2) `\brapor\b`
  // "raporunu" ile eşleşmiyor — ek gelince sağ sınır oluşmuyor. Anlama katmanı
  // aynı tur için `format=docx, requiresArtifact=true` diyordu; iki katman
  // çelişiyordu.
  const rapor = "# Tanıtım Raporu\n\n## Özet\nKısa bir özet.\n\n## Sonuç\nBitti.";
  for (const request of [
    "tanıtım raporunu word belgesi olarak hazırla",
    "bu raporu word belgesi yap",
    "bunu docx yap",
    "sözleşmeyi hazırla",
  ]) {
    const result = await buildArtifactPipeline({
      userRequest: request,
      responseText: rapor,
      metadata: {},
    });
    assert.notEqual(result.kind, "none", `artefakt üretilmeliydi: ${request}`);
    assert.equal(result.intent.type, "document", `belge olmalıydı: ${request}`);
  }
});

test("belgesel bir belge isteği değildir", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "bana güzel bir belgesel öner",
    responseText: "Şunları önerebilirim.",
    metadata: {},
  });
  assert.equal(result.intent.type, null);
});

test("PDF başlığı cevabın kendi başlığından türer", async () => {
  // Eskiden yetkili veri/kaynak belge başlık vermediğinde PDF jenerik
  // "Belge" başlığı ve `custom.pdf` adıyla üretiliyordu — metin
  // "# Elyan Tanıtım Raporu" ile başlasa bile. Kullanıcının gördüğü ilk şey.
  const result = await buildArtifactPipeline({
    userRequest: "şirket raporu hazırla pdf olarak",
    responseText: "# Elyan Tanıtım Raporu\n\n## Özet\nKısa özet.\n\n## Sonuç\nBitti.",
    metadata: {},
  });
  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  const rendered = result.output.output;
  assert.equal(rendered.kind, "json");
  if (rendered.kind !== "json") return;
  const content = rendered.content as Record<string, unknown>;
  assert.equal(content.fileName, "elyan_tanitim_raporu.pdf");
  assert.match(String(content.markdown), /^# Elyan Tanıtım Raporu/);
});

// ---------------------------------------------------------------------------
// CANLI ARIZA (görev 67649401, 2026-08-22 16:34).
//
// "masaüstüne zürafalar hakkında bir pdf hazırla ve kaydet" isteğinde model
// netleştirme sorusu döndürdü — "Netleştireyim: tam olarak neyi yapmamı
// istiyorsun?" — ve bu SORU PDF'in gövdesi olarak basıldı. Görev
// "PDF Belgesi hazır." diye BAŞARILI raporlandı. Kullanıcı masaüstünde içi
// tek soru cümlesi olan bir PDF buldu.
//
// Asgari içerik kapısı vardı ama yalnız araştırma artefaktlarında çalışıyordu.
// ---------------------------------------------------------------------------

test("netleştirme sorusu belge gövdesi olamaz", async () => {
  // İstek SUNUCU tarafında kalmalı: masaüstüne kaydetme isteyen bir cümle
  // hattın ilk kapısında `desktop_required` döner ve netleştirme kapısı hiç
  // çalışmazdı. Ölçmek istediğimiz değişmez şu: cevap metni bir SORU ise
  // belge gövdesi olamaz.
  const userRequest = "Zürafalar hakkında bir pdf hazırla";
  const result = await buildArtifactPipeline({
    userRequest,
    responseText: "Netleştireyim: tam olarak neyi yapmamı istiyorsun?",
    understandingEnvelope: buildTypedUnderstandingEnvelope({
      userId: "user_1",
      message: userRequest,
      intent: documentIntent(),
    }),
  });

  assert.equal(result.kind, "evidence_required");
  if (result.kind !== "evidence_required") return;
  assert.equal(result.reason, "artifact_content_is_clarification");
});

test("gerçek cevap metni belge gövdesi OLABİLİR", async () => {
  // Kapı yalnız soruyu eler; kısa ama geçerli dönüşümler etkilenmez.
  const userRequest = "Bu içeriği Word dosyası olarak oluştur";
  const result = await buildArtifactPipeline({
    userRequest,
    responseText:
      "Proje planlandığı gibi ilerliyor ve tüm kilometre taşları tamamlandı.",
    understandingEnvelope: buildTypedUnderstandingEnvelope({
      userId: "user_1",
      message: userRequest,
      intent: documentIntent(),
    }),
  });

  assert.equal(result.kind, "rendered");
});
