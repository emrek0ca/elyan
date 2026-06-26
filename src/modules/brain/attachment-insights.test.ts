import assert from "node:assert/strict";
import test from "node:test";
import { buildAttachmentInsights } from "./attachment-context.js";
import type { ResolvedAttachmentContext } from "./attachment-context.js";

function buildContext(): ResolvedAttachmentContext {
  return {
    used: true,
    source: "request_attachments",
    promptBlock: "Attachment context",
    documentIds: ["doc-1"],
    documents: [
      {
        documentId: "doc-1",
        title: "/Users/example/Desktop/ataturk.pdf",
        mimeType: "application/pdf",
        summary: "Atatürk inkılapları belgesi.",
        source: "request",
        chunkCount: 2,
        includedChunkCount: 2,
      },
    ],
    chunks: [
      {
        documentId: "doc-1",
        documentTitle: "/Users/example/Desktop/ataturk.pdf",
        mimeType: "application/pdf",
        chunkId: "chunk-1",
        chunkHash: "hash-1",
        pageNumber: 2,
        content:
          "| Kategori | Önemli İnkılaplar |\n|---|---|\n| Eğitim | 1924 Eğitim Kanunu<br>1928 Harf Devrimi |\n| Hukuk | 1926 Medeni Kanun |",
        metadata: {
          chunkKind: "table_data",
        },
      },
      {
        documentId: "doc-1",
        documentTitle: "screenshot.png",
        mimeType: "image/png",
        chunkId: "chunk-2",
        chunkHash: "hash-2",
        pageNumber: null,
        content: "OCR: ekranda görev listesi ve tarih alanı görünüyor.",
        metadata: {
          chunkKind: "ocr_text",
        },
      },
    ],
    totalChars: 240,
    chunkCount: 2,
    needsClarification: false,
  };
}

test("buildAttachmentInsights extracts bounded table, file, and visual blocks from derived chunks", () => {
  const insights = buildAttachmentInsights(buildContext());

  assert.equal(insights.used, true);
  assert.equal(insights.tableCount, 1);
  assert.equal(insights.visualCount, 1);
  assert.deepEqual(insights.tables[0]?.columns, ["Kategori", "Önemli İnkılaplar"]);
  assert.deepEqual(insights.tables[0]?.rows[0], [
    "Eğitim",
    "1924 Eğitim Kanunu 1928 Harf Devrimi",
  ]);
  assert.match(insights.promptBlock ?? "", /bounded_derived_attachment_insights/);
  assert.doesNotMatch(insights.promptBlock ?? "", /\/Users\/example/);
  assert.equal(insights.renderBlocks.some((block) => block.type === "file"), true);
  assert.equal(insights.renderBlocks.some((block) => block.type === "table"), true);
});
