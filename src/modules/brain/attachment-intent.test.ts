import assert from "node:assert/strict";
import test from "node:test";
import {
  buildResolvedAttachmentIntentPromptBlock,
  resolveAttachmentIntentSpec,
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
    [
      "Resolved attachment/document intent:",
      "- mode: answer",
      "- output_format: unknown",
      "- preserve_numbers: false",
      "- preserve_user_phrases: false",
      "- requires_structured_document: false",
      "Follow this resolved intent unless the user clearly changes the goal.",
    ].join("\n"),
  );
});

test("resolveAttachmentIntentSpec captures spreadsheet export requirements", () => {
  assert.deepEqual(
    resolveAttachmentIntentSpec({
      prompt: "Toplamları koru ve bunu Excel tablo olarak oluştur",
      requestMetadata: { documentExportMode: "mobile_local" },
      attachmentContext: { used: true },
    }),
    {
      mode: "export",
      outputFormat: "xlsx",
      preserveNumbers: true,
      preserveUserPhrases: false,
      requiresStructuredDocument: true,
    },
  );
});
