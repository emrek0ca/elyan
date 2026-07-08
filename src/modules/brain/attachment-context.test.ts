import assert from "node:assert/strict";
import test from "node:test";
import {
  resolveAttachmentContext,
  resolveAttachmentContextWithCache,
  selectPromptRelevantChunkIndices,
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

function buildVisionBlock(overrides: Record<string, unknown> = {}) {
  return {
    id: "vision_img_1",
    type: "vision",
    version: 2,
    render: { widget: "vision_summary", title: "Gorsel analizi", status: "ready" },
    source: {
      kind: "gallery",
      privacy: "local_extracted_only",
      image_sent_to_server: false,
      platform: "ios",
      engine: "apple_vision",
    },
    input_kind: { value: "error_screen", confidence: 0.84 },
    quality: {
      blur: 0.12,
      brightness: 0.52,
      contrast: 0.44,
      resolution: { width: 1170, height: 2532 },
      rotation: 0,
      is_readable: true,
      warnings: [],
    },
    text: {
      full_text: "Unhandled Exception: SocketException failed host lookup",
      blocks: [
        {
          text: "Unhandled Exception: SocketException failed host lookup",
          confidence: 0.91,
          box: { x: 0.08, y: 0.12, w: 0.8, h: 0.08 },
          role: "error",
        },
      ],
      reading_order: "top_to_bottom",
    },
    scene: {
      labels: [{ name: "screenshot", confidence: 0.82, source: "apple_vision" }],
      objects: [],
    },
    documents: { detected: false, pages: [] },
    barcodes: [],
    task_hints: ["extract_error"],
    summary_for_llm: "Bu gorsel error_screen olarak siniflandirildi.",
    confidence: { overall: 0.78, ocr: 0.91, scene: 0.82, document: 0 },
    debug: { latency_ms: 120, engine_version: "apple_vision", warnings: [] },
    ...overrides,
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

test("resolveAttachmentContext uses VisionBlock v2 without raw image data", () => {
  const context = resolveAttachmentContext({
    prompt: "Bu ekrandaki hatayi acikla",
    metadata: {
      attachments: [
        {
          documentId: "img-vision",
          fileName: "error-screen.png",
          mimeType: "image/png",
          processingState: "fast_ready",
          visionBlock: buildVisionBlock(),
        },
      ],
    },
  });

  assert.ok(context);
  assert.equal(context?.used, true);
  assert.equal(context?.needsClarification, false);
  assert.equal(context?.visionBlocks?.length, 1);
  assert.match(context?.promptBlock ?? "", /server does NOT have the image/i);
  assert.match(context?.promptBlock ?? "", /SocketException failed host lookup/);
  assert.doesNotMatch(context?.promptBlock ?? "", /base64/i);
});

test("resolveAttachmentContext surfaces low-quality VisionBlock as qualified evidence", () => {
  const context = resolveAttachmentContext({
    prompt: "Bu gorselde ne yaziyor?",
    metadata: {
      attachments: [
        {
          documentId: "img-low",
          fileName: "blurred.png",
          mimeType: "image/png",
          processingState: "fast_ready",
          visionBlock: buildVisionBlock({
            render: { widget: "vision_summary", status: "unreadable" },
            quality: {
              blur: 0.88,
              brightness: 0.18,
              contrast: 0.12,
              resolution: { width: 480, height: 640 },
              rotation: 0,
              is_readable: false,
              warnings: ["possible_blur", "too_dark"],
            },
            confidence: { overall: 0.31, ocr: 0.28, scene: 0.4, document: 0 },
          }),
        },
      ],
    },
  });

  assert.ok(context);
  assert.equal(context?.used, true);
  assert.match(context?.promptBlock ?? "", /Quality warnings/i);
  assert.match(context?.promptBlock ?? "", /Overall vision confidence is low/i);
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

/* ── Question-relevant chunk selection ──────────────────────────────────── */

test("selectPromptRelevantChunkIndices favors question-relevant chunks in document order", () => {
  const contents = [
    "Giriş bölümü: şirket tarihçesi ve genel bilgiler.",
    "İkinci bölüm: organizasyon şeması ve roller.",
    "Üçüncü bölüm: 2024 bütçe tablosu ve fatura ödemeleri detayı.",
    "Dördüncü bölüm: gelecek planları ve vizyon.",
  ];
  const selected = selectPromptRelevantChunkIndices({
    prompt: "2024 bütçe ve fatura ödemeleri ne kadar?",
    contents,
    maxChunks: 2,
  });
  assert.ok(selected.includes(2), "budget/invoice chunk must be selected");
  assert.deepEqual(selected, [...selected].sort((a, b) => a - b), "selection stays in document order");
});

test("selectPromptRelevantChunkIndices keeps document head when there is no relevance signal", () => {
  const contents = ["Bölüm bir metni.", "Bölüm iki metni.", "Bölüm üç metni."];
  const selected = selectPromptRelevantChunkIndices({
    prompt: "xyzq qwerty",
    contents,
    maxChunks: 2,
  });
  assert.deepEqual(selected, [0, 1]);
});

test("selectPromptRelevantChunkIndices prefers semantic scores when provided", () => {
  const contents = ["alakasız metin bir", "alakasız metin iki", "alakasız metin üç"];
  const selected = selectPromptRelevantChunkIndices({
    prompt: "soru",
    contents,
    maxChunks: 1,
    semanticScores: [0.1, 0.9, 0.3],
  });
  assert.deepEqual(selected, [1]);
});

test("resolveAttachmentContext surfaces question-relevant chunks from deep in a long document", () => {
  const chunks = Array.from({ length: 12 }, (_, index) =>
    index === 10
      ? "Sayfa 11: KVKK uyumluluk maddesi ve veri ihlali ceza hükümleri bu bölümde açıklanır."
      : `Sayfa ${index + 1}: genel açıklama metni, tarihçe ve idari süreç anlatımı bölüm ${index + 1}.`,
  );
  const context = resolveAttachmentContext({
    prompt: "KVKK uyumluluk maddesi ne diyor?",
    metadata: {
      attachments: [
        {
          documentId: "doc-long",
          fileName: "sozlesme.pdf",
          mimeType: "application/pdf",
          document_analysis: {
            documentId: "doc-long",
            summary: "Uzun sözleşme dökümanı",
            chunks,
          },
        },
      ],
    },
    maxChunks: 3,
  });

  assert.ok(context);
  assert.equal(context?.used, true);
  assert.match(context?.promptBlock ?? "", /KVKK uyumluluk maddesi/);
});

test("resolveAttachmentContext keeps short documents untouched (no reranking)", () => {
  const context = resolveAttachmentContext({
    prompt: "KVKK maddesi ne diyor?",
    metadata: {
      attachments: [
        {
          documentId: "doc-short",
          fileName: "kisa.pdf",
          mimeType: "application/pdf",
          document_analysis: {
            documentId: "doc-short",
            summary: "Kısa belge",
            chunks: ["Birinci bölüm metni.", "İkinci bölüm KVKK metni."],
          },
        },
      ],
    },
  });

  assert.ok(context);
  assert.match(context?.promptBlock ?? "", /Birinci bölüm metni/);
  assert.match(context?.promptBlock ?? "", /KVKK metni/);
});

test("resolveAttachmentContext re-surfaces consented session vision images on follow-up turns", () => {
  const optedInCandidate: AttachmentContextCandidate = {
    messageId: "message-vision-1",
    createdAt: "2030-01-02T00:00:00.000Z",
    prompt: "Burada ne var",
    metadata: {
      ...buildAttachmentMetadata({
        documentId: "doc-vision-1",
        fileName: "masa.jpg",
        text: "Görsel cihazda analiz edildi. Sahne: genel.",
      }),
      cloudVisionOptIn: true,
      clientAttachments: [
        {
          attachmentType: "image",
          imageId: "img-vision-1",
          mimeType: "image/jpeg",
          fileName: "masa.jpg",
          base64Thumbnail: "aGVsbG8=",
          thumbnailWidth: 512,
          thumbnailHeight: 512,
          ocrText: "",
        },
      ],
    },
  };

  const context = resolveAttachmentContext({
    prompt: "soldaki nesne ne?",
    sessionAttachmentCandidates: [optedInCandidate],
  });

  assert.ok(context);
  assert.equal(context.visionImages?.length, 1);
  assert.equal(context.visionImages?.[0]?.documentId, "img-vision-1");
  assert.equal(context.visionImages?.[0]?.base64, "aGVsbG8=");
});

test("resolveAttachmentContext never re-surfaces session images without the opt-in marker", () => {
  const nonConsentedCandidate: AttachmentContextCandidate = {
    messageId: "message-vision-2",
    createdAt: "2030-01-02T00:00:00.000Z",
    prompt: "Burada ne var",
    metadata: {
      ...buildAttachmentMetadata({
        documentId: "doc-vision-2",
        fileName: "masa.jpg",
        text: "Görsel cihazda analiz edildi. Sahne: genel.",
      }),
      clientAttachments: [
        {
          attachmentType: "image",
          imageId: "img-vision-2",
          mimeType: "image/jpeg",
          fileName: "masa.jpg",
          base64Thumbnail: "aGVsbG8=",
          thumbnailWidth: 512,
          thumbnailHeight: 512,
          ocrText: "",
        },
      ],
    },
  };

  const context = resolveAttachmentContext({
    prompt: "soldaki nesne ne?",
    sessionAttachmentCandidates: [nonConsentedCandidate],
  });

  assert.ok(context);
  assert.equal((context.visionImages ?? []).length, 0);
});
