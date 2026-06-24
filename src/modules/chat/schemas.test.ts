import assert from "node:assert/strict";
import test from "node:test";
import { createChatMessageBodySchema } from "./schemas.js";

const sessionId = "11111111-1111-4111-8111-111111111111";
const otherSessionId = "22222222-2222-4222-8222-222222222222";

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
