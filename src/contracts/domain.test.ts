import assert from "node:assert/strict";
import test from "node:test";
import {
  brainResultSchema,
  documentEnvelopeSchema,
  elyanAssistantBlockSchema,
} from "./domain.js";

test("documentEnvelopeSchema accepts normalized mobile document envelopes", () => {
  const envelope = {
    id: "envelope-1",
    sourceHash: "sha256:abc123",
    mimeType: "application/pdf",
    language: "tr",
    confidence: 0.94,
    redactionState: "unredacted",
    lineage: ["mobile_local", "server_brain"],
    metadata: {
      source: "mobile",
      privacyLevel: "local_derived",
    },
    blocks: [
      {
        id: "block-1",
        type: "heading",
        text: "Rapor özeti",
        page: 1,
        bbox: [0, 0, 612, 72],
        confidence: 0.98,
        sourceHash: "sha256:abc123",
        mimeType: "application/pdf",
        language: "tr",
        redactionState: "unredacted",
        lineage: ["capture", "ocr", "chunk"],
      },
      {
        id: "block-2",
        type: "text",
        text: "Maliyetler sabit, teslimat iki hafta gecikebilir.",
        page: 1,
        confidence: 0.92,
        sourceHash: "sha256:abc123",
        lineage: ["capture", "chunk"],
      },
    ],
  };

  assert.deepEqual(documentEnvelopeSchema.parse(envelope), envelope);
});

test("brainResultSchema accepts structured answer payloads for mobile rendering", () => {
  const result = {
    answer: "Özet hazır.",
    highlights: ["Teslimat gecikebilir.", "Maliyetler sabit."],
    citations: [
      {
        blockId: "block-2",
        page: 1,
        text: "Maliyetler sabit, teslimat iki hafta gecikebilir.",
        sourceHash: "sha256:abc123",
      },
    ],
    extractedTables: [
      {
        headers: ["Kalem", "Tutar"],
        rows: [["Maliyet", "Sabit"]],
      },
    ],
    actions: ["create_summary_doc", "export_pdf"],
  };

  assert.deepEqual(brainResultSchema.parse(result), result);
});

test("elyanAssistantBlockSchema accepts phased v1.1 summary and group blocks", () => {
  const block = {
    type: "block_group",
    stableBlockId: "group_1",
    visibility: "user_visible",
    children: [
      {
        type: "summary",
        stableBlockId: "summary_1",
        visibility: "user_visible",
        summary: "Kısa sonuç hazır.",
      },
      {
        type: "next_steps",
        stableBlockId: "next_1",
        visibility: "user_visible",
        items: ["Raporu paylaş", "Cihaz seç"],
      },
    ],
  };

  assert.deepEqual(elyanAssistantBlockSchema.parse(block), block);
});

test("elyanAssistantBlockSchema accepts smart task trace presentation fields", () => {
  const block = {
    type: "task_trace",
    stableBlockId: "trace_1",
    visibility: "user_visible",
    taskId: "task-1",
    status: "completed",
    title: "Görev tamamlandı",
    phase: "verify",
    summary: "Bağlam işlendi ve yanıt kontrol edildi.",
    progressLabel: "Son kontrol tamamlandı",
    routeReason:
      "Elyan bunu sohbet olarak işledi çünkü istek özel yerel veri veya bilgisayar erişimi gerektirmiyor.",
    activeStepId: "verify",
    steps: [
      {
        id: "intent",
        label: "Niyet anlaşıldı",
        status: "completed",
      },
      {
        id: "verify",
        label: "Sonuç doğrulandı",
        status: "completed",
      },
    ],
  };

  assert.deepEqual(elyanAssistantBlockSchema.parse(block), block);
});
