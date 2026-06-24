import assert from "node:assert/strict";
import test from "node:test";
import {
  resolveAttachmentContext,
  resolveAttachmentContextWithCache,
  type AttachmentContextCandidate,
} from "./attachment-context.js";

function buildAttachmentMetadata(input: {
  documentId: string;
  fileName: string;
  text: string;
  summary?: string;
  mimeType?: string;
}) {
  return {
    attachments: [
      {
        documentId: input.documentId,
        fileName: input.fileName,
        mimeType: input.mimeType ?? "application/pdf",
        compactDocument: {
          documentId: input.documentId,
          fileName: input.fileName,
          mimeType: input.mimeType ?? "application/pdf",
        },
        document_analysis: {
          documentId: input.documentId,
          summary: input.summary ?? input.text,
          extractedText: input.text,
        },
      },
    ],
  } satisfies Record<string, unknown>;
}

function buildSessionCandidate(input: {
  documentId: string;
  fileName: string;
  text: string;
  summary?: string;
}): AttachmentContextCandidate {
  return {
    messageId: `message-${input.documentId}`,
    createdAt: "2030-01-01T00:00:00.000Z",
    prompt: `Belge ${input.fileName}`,
    metadata: buildAttachmentMetadata(input),
  };
}

class FakeStore {
  private readonly memory = new Map<string, string>();

  async get(key: string) {
    return this.memory.get(key) ?? null;
  }

  async set(key: string, value: string) {
    this.memory.set(key, value);
  }
}

test("resolveAttachmentContext uses current request attachments before session recovery", () => {
  const context = resolveAttachmentContext({
    prompt: "Bu PDF'i özetle",
    metadata: buildAttachmentMetadata({
      documentId: "doc-current",
      fileName: "ozet.pdf",
      text: "Alpha raporu ilk bölüm. Beta raporu ikinci bölüm.",
      summary: "Alpha ve Beta raporu özeti",
    }),
  });

  assert.ok(context);
  assert.equal(context?.used, true);
  assert.equal(context?.source, "request_attachments");
  assert.deepEqual(context?.documentIds, ["doc-current"]);
  assert.match(context?.promptBlock ?? "", /Alpha raporu/i);
});

test("resolveAttachmentContext recovers the last single attachment from the same session", () => {
  const context = resolveAttachmentContext({
    prompt: "Bunu yeniden düzenle",
    sessionAttachmentCandidates: [
      buildSessionCandidate({
        documentId: "doc-session",
        fileName: "notlar.docx",
        text: "Toplantı notları. İlk karar bütçe onayı.",
        summary: "Toplantı notları özeti",
      }),
    ],
  });

  assert.ok(context);
  assert.equal(context?.used, true);
  assert.equal(context?.source, "session_recovery");
  assert.deepEqual(context?.documentIds, ["doc-session"]);
  assert.match(context?.promptBlock ?? "", /Toplantı notları/i);
});

test("resolveAttachmentContext asks for clarification instead of guessing across multiple session attachments", () => {
  const context = resolveAttachmentContext({
    prompt: "bunu düzenle",
    sessionAttachmentCandidates: [
      buildSessionCandidate({
        documentId: "doc-a",
        fileName: "teklif-a.pdf",
        text: "Teklif A içeriği",
      }),
      buildSessionCandidate({
        documentId: "doc-b",
        fileName: "teklif-b.pdf",
        text: "Teklif B içeriği",
      }),
    ],
  });

  assert.ok(context);
  assert.equal(context?.used, false);
  assert.equal(context?.needsClarification, true);
  assert.equal(context?.source, "session_recovery");
  assert.match(context?.clarificationMessage ?? "", /hangi/i);
  assert.deepEqual(context?.documentIds, ["doc-a", "doc-b"]);
});

test("resolveAttachmentContext fails closed for a failed current attachment instead of using stale session context", () => {
  const context = resolveAttachmentContext({
    prompt: "Bunda ne yazıyor?",
    metadata: {
      attachments: [
        {
          documentId: "doc-failed",
          fileName: "bozuk.pdf",
          mimeType: "application/pdf",
          processingState: "failed",
        },
      ],
    },
    sessionAttachmentCandidates: [
      buildSessionCandidate({
        documentId: "doc-old",
        fileName: "eski.pdf",
        text: "Eski belgenin içeriği",
      }),
    ],
  });

  assert.ok(context);
  assert.equal(context?.used, false);
  assert.equal(context?.source, "request_attachments");
  assert.equal(context?.needsClarification, true);
  assert.deepEqual(context?.documentIds, []);
  assert.match(context?.clarificationMessage ?? "", /yeniden ekle/i);
});

test("resolveAttachmentContext does not produce multiple candidates when attachments[] and legacy fields coexist", () => {
  // Reproduces the "birden fazla belge görüyorum" false-positive clarification:
  // mobile sends attachments[0] that already contains nested document_analysis and
  // compactDocument; old code also synthesized a second record from carrier-level
  // legacy fields, causing two candidates for a single physical document.
  const context = resolveAttachmentContext({
    prompt: "Bu belgeyi özetle",
    metadata: {
      attachments: [
        {
          documentId: "doc-single",
          fileName: "rapor.pdf",
          mimeType: "application/pdf",
          compactDocument: {
            documentId: "doc-single",
            fileName: "rapor.pdf",
            mimeType: "application/pdf",
          },
          document_analysis: {
            documentId: "doc-single",
            summary: "Rapor içeriği",
            extractedText: "Rapor içeriği satırı",
          },
        },
      ],
      // carrier-level legacy field that old code would synthesize a second record from
      documentEnvelope: {
        id: "doc-single",
        sourceHash: "abc123",
        mimeType: "application/pdf",
        blocks: [{ id: "b1", type: "text", text: "Rapor içeriği satırı", page: 1, metadata: {}, sourceHash: "abc123", mimeType: "application/pdf" }],
      },
    },
  });

  assert.ok(context);
  assert.equal(context?.needsClarification, false, "single attachment must not trigger clarification");
  assert.equal(context?.documentIds.length, 1, "only one document id expected");
  assert.equal(context?.used, true);
});

test("resolveAttachmentContext treats image attachment with OCR text as usable context", () => {
  const context = resolveAttachmentContext({
    prompt: "Bu görselde ne yazıyor?",
    metadata: {
      attachments: [
        {
          documentId: "img-1",
          fileName: "screenshot.png",
          mimeType: "image/png",
          document_analysis: {
            documentId: "img-1",
            mimeType: "image/png",
            fileName: "screenshot.png",
            summary: "Toplantı notu görseli",
            extractedText: "Toplantı: 15 Haziran, Katılımcılar: Ali, Veli",
          },
        },
      ],
    },
  });

  assert.ok(context);
  assert.equal(context?.needsClarification, false);
  assert.equal(context?.used, true);
  assert.equal(context?.documentIds.length, 1);
  assert.match(context?.promptBlock ?? "", /screenshot\.png/i);
});

test("resolveAttachmentContext formats document headers, page labels, and table chunks with larger excerpts", () => {
  const context = resolveAttachmentContext({
    prompt: "Bu faturayı açıkla",
    metadata: {
      attachments: [
        {
          documentId: "doc-rich",
          fileName: "fatura.pdf",
          mimeType: "application/pdf",
          sha256: "sha-rich-1",
          metadata: {
            pageCount: 8,
            extractionMethod: "pdf_text_layer",
            confidence: 0.97,
          },
          compactDocument: {
            documentId: "doc-rich",
            fileName: "fatura.pdf",
            mimeType: "application/pdf",
            sha256: "sha-rich-1",
          },
          document_analysis: {
            documentId: "doc-rich",
            summary: "Mayıs 2026 elektrik faturası.",
            extractedText: "Özet metin",
            chunks: [
              {
                text: "A".repeat(1_500),
                pageNumber: 1,
                metadata: {
                  pageNumber: 1,
                  pageStart: 1,
                  pageEnd: 1,
                  extractionMethod: "pdf_text_layer",
                  confidence: 0.97,
                  blockType: "table_data",
                  type: "table",
                },
              },
              {
                text: "İkinci ve üçüncü sayfa özeti",
                metadata: {
                  pageStart: 2,
                  pageEnd: 3,
                },
              },
              {
                text: "Sayfa bilgisi olmayan not",
                metadata: {},
              },
            ],
          },
        },
      ],
    },
  });

  assert.ok(context);
  assert.match(
    context?.promptBlock ?? "",
    /\[BELGE 1: fatura\.pdf \| PDF \| 8 sayfa \| güven: 0\.97 \| yöntem: pdf_text_layer\]/i,
  );
  assert.match(context?.promptBlock ?? "", /Özet: Mayıs 2026 elektrik faturası\./i);
  assert.match(context?.promptBlock ?? "", /Sayfa 1: \[tablo\]/i);
  assert.match(context?.promptBlock ?? "", /Sayfa 2-3: İkinci ve üçüncü sayfa özeti/i);
  assert.match(context?.promptBlock ?? "", /İçerik: Sayfa bilgisi olmayan not/i);
  assert.ok((context?.chunks[0]?.content.length ?? 0) > 700);
});

test("resolveAttachmentContext enforces the expanded chunk and character budgets", () => {
  const chunks = Array.from({ length: 30 }, (_, index) => ({
    text: `Bölüm ${index + 1} ` + "x".repeat(2_000),
    pageNumber: index + 1,
    metadata: {
      pageNumber: index + 1,
      extractionMethod: "pdf_text_layer",
      confidence: 0.94,
    },
  }));
  const context = resolveAttachmentContext({
    prompt: "Bu belgeyi incele",
    metadata: {
      attachments: [
        {
          documentId: "doc-budget",
          fileName: "uzun-rapor.pdf",
          mimeType: "application/pdf",
          compactDocument: {
            documentId: "doc-budget",
            fileName: "uzun-rapor.pdf",
            mimeType: "application/pdf",
          },
          document_analysis: {
            documentId: "doc-budget",
            summary: "Uzun rapor özeti",
            chunks,
          },
        },
      ],
    },
  });

  assert.ok(context);
  assert.ok((context?.chunkCount ?? 0) <= 20);
  assert.ok((context?.totalChars ?? 0) <= 24_000);
});

test("resolveAttachmentContextWithCache reuses prepared attachment payloads without changing the resolved context", async () => {
  const metadata = {
    attachments: [
      {
        documentId: "doc-cache",
        fileName: "cache.pdf",
        mimeType: "application/pdf",
        sha256: "cache-hash-1",
        compactDocument: {
          documentId: "doc-cache",
          fileName: "cache.pdf",
          mimeType: "application/pdf",
          sha256: "cache-hash-1",
        },
        document_analysis: {
          documentId: "doc-cache",
          summary: "Cache denemesi",
          extractedText: "Cache denemesi gövde metni",
        },
      },
    ],
  } satisfies Record<string, unknown>;
  const prompt = "Bu belgeyi özetle";
  const store = new FakeStore();

  const uncached = resolveAttachmentContext({ prompt, metadata });
  const first = await resolveAttachmentContextWithCache(store, { prompt, metadata });
  const second = await resolveAttachmentContextWithCache(store, { prompt, metadata });

  assert.equal(first?.cacheHit, false);
  assert.equal(second?.cacheHit, true);
  assert.deepEqual(
    JSON.parse(JSON.stringify({
      promptBlock: second?.promptBlock,
      documentIds: second?.documentIds,
      documents: second?.documents,
      chunks: second?.chunks,
      totalChars: second?.totalChars,
      chunkCount: second?.chunkCount,
      used: second?.used,
      source: second?.source,
      needsClarification: second?.needsClarification,
    })),
    JSON.parse(JSON.stringify({
      promptBlock: uncached?.promptBlock,
      documentIds: uncached?.documentIds,
      documents: uncached?.documents,
      chunks: uncached?.chunks,
      totalChars: uncached?.totalChars,
      chunkCount: uncached?.chunkCount,
      used: uncached?.used,
      source: uncached?.source,
      needsClarification: uncached?.needsClarification,
    })),
  );
});
