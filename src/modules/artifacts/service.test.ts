import test from "node:test";
import assert from "node:assert/strict";
import type { ElyanAssistantDocumentBlock } from "../../contracts/domain.js";
import {
  buildTypedUnderstandingEnvelope,
} from "../../core/understanding/understanding-envelope.js";
import type { IntentClassification } from "../../core/understanding/types.js";
import { buildArtifactPipeline } from "./service.js";

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
  assert.equal(result.spec.blocks.filter((block) => block.type === "line_item").length, 2);
  assert.equal(result.spec.blocks.find((block) => block.type === "total")?.amount, 21_000);
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
  assert.deepEqual(result.spec.columns.map((column) => column.key), ["label", "value"]);
  assert.equal(result.spec.rows.length, 3);
  assert.equal(result.spec.rows[1]?.value, 18_000);
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

test("artifact pipeline builds chart data without fake rows", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Ocak 12000, Şubat 18000, Mart 15000 verisiyle gelir grafiği çiz.",
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

test("artifact pipeline builds bounded SVG with text element", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "1024x1024 SVG içinde ortada Elyan yazan sade logo taslağı oluştur.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "svg");
  assert.equal(result.spec.type, "svg");
  if (result.spec.type !== "svg") return;
  assert.equal(result.spec.canvas.width, 1024);
  assert.equal(result.spec.canvas.height, 1024);
  assert.equal(result.spec.canvas.viewBox, "0 0 1024 1024");
  assert.equal(result.spec.elements.some((element) => element.type === "text"), true);
  assert.equal(result.output.output.kind, "svg");
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
  assert.equal(result.output.output.content, "Merhaba, işi yarın tamamlayacağım.");
});

test("artifact pipeline detects wrong PDF total", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Kapı tamiri 18000 TL, menteşe 3000 TL, genel toplam 22000 TL.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "pdf");
  assert.equal(result.output.validation.ok, false);
  assert.equal(result.output.validation.errors.some((error) => error.code === "total_mismatch"), true);
  assert.equal(result.spec.type, "pdf");
  if (result.spec.type !== "pdf") return;
  const computed = result.spec.blocks
    .filter((block) => block.type === "line_item")
    .reduce((sum, block) => sum + (block.amount ?? 0), 0);
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
    userRequest: "Bilgisayarımdaki son PDF’i özetle ve PDF olarak geri hazırla.",
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
