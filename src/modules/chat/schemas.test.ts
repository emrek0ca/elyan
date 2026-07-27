import assert from "node:assert/strict";
import test from "node:test";
import { createChatMessageBodySchema } from "./schemas.js";

const sessionId = "11111111-1111-4111-8111-111111111111";
const otherSessionId = "22222222-2222-4222-8222-222222222222";

test("createChatMessageBodySchema accepts email and WhatsApp channel sources", () => {
  for (const source of ["email", "whatsapp"] as const) {
    const parsed = createChatMessageBodySchema.parse({
      source,
      content: "Merhaba",
    });
    assert.equal(parsed.source, source);
  }
});

test("createChatMessageBodySchema accepts chatSessionId as a sessionId alias", () => {
  const parsed = createChatMessageBodySchema.parse({
    chatSessionId: sessionId,
    content: "Bunda ne yazıyor?",
    metadata: {
      attachments: [
        {
          documentId: "doc-1",
          fileName: "belge.pdf",
          mimeType: "application/pdf",
          deepContext: {
            compactDocument: {
              chunks: [{ id: "chunk-1", text: "Test belge içeriği." }],
            },
          },
        },
      ],
    },
  });

  assert.equal(parsed.sessionId, sessionId);
  assert.equal("chatSessionId" in parsed, false);
});

test("createChatMessageBodySchema derives content from Elyan text blocks", () => {
  const parsed = createChatMessageBodySchema.parse({
    sessionId,
    blocks: [
      {
        type: "text",
        markdown: "Bunda ne yazıyor?",
        visibility: "user_visible",
      },
    ],
    source: "mobile",
  });

  assert.equal(parsed.content, "Bunda ne yazıyor?");
  assert.equal(parsed.blocks?.[0]?.type, "text");
});

test("createChatMessageBodySchema rejects conflicting session id aliases", () => {
  const result = createChatMessageBodySchema.safeParse({
    sessionId,
    chatSessionId: otherSessionId,
    content: "Bunda ne yazıyor?",
  });

  assert.equal(result.success, false);
});

test("createChatMessageBodySchema rejects raw or storage-backed attachment payloads", () => {
  const result = createChatMessageBodySchema.safeParse({
    chatSessionId: sessionId,
    content: "Bunda ne yazıyor?",
    metadata: {
      attachments: [
        {
          documentId: "doc-raw",
          fileName: "belge.pdf",
          mimeType: "application/pdf",
          filePath: "/private/var/mobile/belge.pdf",
          presignedUrl: "https://storage.example.test/private/belge.pdf",
          fastPreview: {
            textPreview: "Güvenli türetilmiş metin",
          },
        },
      ],
    },
  });

  assert.equal(result.success, false);
  if (!result.success) {
    assert.match(result.error.message, /raw binary upload payload is not accepted/);
  }
});

test("createChatMessageBodySchema rejects legacy vision image base64 payloads", () => {
  const result = createChatMessageBodySchema.safeParse({
    chatSessionId: sessionId,
    content: "Bu gorselde ne var?",
    metadata: {
      attachments: [
        {
          documentId: "img-raw",
          fileName: "screen.png",
          mimeType: "image/png",
          visionImageJpeg: "abc123",
          clientAttachments: [
            {
              attachmentType: "image",
              base64Thumbnail: "abc123",
              mimeType: "image/jpeg",
            },
          ],
        },
      ],
    },
  });

  assert.equal(result.success, false);
  if (!result.success) {
    assert.match(result.error.message, /raw binary upload payload is not accepted/);
  }
});

test("createChatMessageBodySchema accepts bounded request-ephemeral vision outside metadata", () => {
  const result = createChatMessageBodySchema.safeParse({
    chatSessionId: sessionId,
    content: "Bu ekrandaki küçük hata kodunu oku.",
    metadata: { cloudVisionOptIn: true },
    ephemeralVision: {
      version: 1,
      retention: "request_ephemeral",
      privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "personal" },
      images: [{
        imageId: "screen-1",
        kind: "text_crop",
        mimeType: "image/jpeg",
        base64Data: Buffer.from("small-image").toString("base64"),
        width: 1200,
        height: 600,
        box: { x: 0, y: 0, w: 1, h: 0.5 },
      }],
    },
  });
  assert.equal(result.success, true);
  if (result.success) {
    assert.equal(result.data.ephemeralVision?.retention, "request_ephemeral");
  }
});

test("createChatMessageBodySchema migrates authorized legacy mobile vision out of metadata", () => {
  const result = createChatMessageBodySchema.safeParse({
    chatSessionId: sessionId,
    content: "Bu gorselde ne var?",
    metadata: {
      cloudVisionOptIn: true,
      attachments: [{
        documentId: "img-legacy",
        clientAttachments: [{
          attachmentType: "image",
          imageId: "image-1",
          base64Thumbnail: Buffer.from("small-image").toString("base64"),
          mimeType: "image/jpeg",
          thumbnailWidth: 512,
          thumbnailHeight: 384,
        }],
      }],
    },
  });
  assert.equal(result.success, true);
  if (result.success) {
    assert.equal(result.data.ephemeralVision?.images.length, 1);
    assert.equal(JSON.stringify(result.data.metadata).includes("base64Thumbnail"), false);
  }
});
