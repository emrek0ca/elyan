import assert from "node:assert/strict";
import test from "node:test";
import { buildAttachmentInsightPromptBlock } from "../../modules/brain/attachment-context.js";
import type { ResolvedAttachmentContext } from "../../modules/brain/attachment-context.js";

function buildContext(): ResolvedAttachmentContext {
  return {
    used: true,
    source: "request_attachments",
    promptBlock: "Attachment context",
    documentIds: ["doc-1"],
    documents: [
      {
        documentId: "doc-1",
        title: "Rapor.pdf",
        mimeType: "application/pdf",
        summary: "Çeyrek gelir raporu.",
        source: "request",
        chunkCount: 3,
        includedChunkCount: 3,
      },
    ],
    chunks: [
      {
        documentId: "doc-1",
        documentTitle: "Rapor.pdf",
        mimeType: "application/pdf",
        chunkId: "chunk-1",
        chunkHash: "abc123",
        content: "Gelir bu çeyrekte %12 arttı.",
        pageNumber: 1,
        metadata: {},
      },
    ],
    totalChars: 500,
    chunkCount: 3,
    needsClarification: false,
  };
}

test("document pipeline: attachment insight prompt block is generated", () => {
  const ctx = buildContext();
  const block = buildAttachmentInsightPromptBlock(ctx);
  assert.ok(block !== null, "Prompt block must be generated for used attachment context");
  assert.ok(block!.includes("bounded_derived_attachment_insights"), "Block must declare bounded mode");
  assert.ok(block!.includes("rawBinaryStored"), "Block must declare rawBinaryStored flag");
});

test("document pipeline: rawBinaryStored is always false in prompt block", () => {
  const ctx = buildContext();
  const block = buildAttachmentInsightPromptBlock(ctx);
  assert.ok(block !== null);
  // Extract JSON between the code fences
  const jsonMatch = block!.match(/```json\n([\s\S]+?)\n```/);
  assert.ok(jsonMatch, "Prompt block must contain a JSON code block");
  const parsed = JSON.parse(jsonMatch![1]);
  assert.equal(parsed.rawBinaryStored, false, "rawBinaryStored must be false");
});

test("document pipeline: returns null when attachment context not used", () => {
  const ctx: ResolvedAttachmentContext = {
    used: false,
    source: "request_attachments",
    promptBlock: "",
    documentIds: [],
    documents: [],
    chunks: [],
    totalChars: 0,
    chunkCount: 0,
    needsClarification: false,
  };
  const block = buildAttachmentInsightPromptBlock(ctx);
  assert.equal(block, null);
});
