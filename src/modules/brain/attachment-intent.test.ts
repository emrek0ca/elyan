import assert from "node:assert/strict";
import test from "node:test";
import {
  buildResolvedAttachmentIntentPromptBlock,
  resolveAttachmentIntentMode,
} from "./attachment-intent.js";

test("resolveAttachmentIntentMode selects export for mobile-local export metadata", () => {
  assert.equal(
    resolveAttachmentIntentMode({
      prompt: "Bunu PDF olarak ver",
      requestMetadata: { documentExportMode: "mobile_local" },
    }),
    "export",
  );
});

test("resolveAttachmentIntentMode selects semantic_edit for edit requests", () => {
  assert.equal(
    resolveAttachmentIntentMode({
      prompt: "Bu belgeyi daha resmi olacak şekilde düzenle",
      requestMetadata: {},
    }),
    "semantic_edit",
  );
  assert.equal(
    resolveAttachmentIntentMode({
      prompt: "Bunu kontrol et",
      requestMetadata: { documentEditRequested: true },
    }),
    "semantic_edit",
  );
});

test("resolveAttachmentIntentMode selects analyze for summary and analysis prompts", () => {
  assert.equal(
    resolveAttachmentIntentMode({
      prompt: "Bu dokümanı analiz et",
      requestMetadata: {},
    }),
    "analyze",
  );
});

test("buildResolvedAttachmentIntentPromptBlock only emits when attachment/export context exists", () => {
  assert.equal(
    buildResolvedAttachmentIntentPromptBlock({
      prompt: "Bunu açıkla",
      requestMetadata: {},
      attachmentContext: null,
    }),
    null,
  );
  assert.equal(
    buildResolvedAttachmentIntentPromptBlock({
      prompt: "Bunu açıkla",
      requestMetadata: {},
      attachmentContext: { used: true },
    }),
    "Resolved intent: answer. Follow that mode unless the user clearly changes the goal.",
  );
});
