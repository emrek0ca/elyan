import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeRuntimeCapabilities,
  summarizeRuntimeCapabilities,
} from "./capabilities.js";

test("runtime capability summary classifies professional desktop tools", () => {
  const normalized = normalizeRuntimeCapabilities([
    "document_read",
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "text_analyze",
    "web_research",
    "math_solve",
  ]);

  assert.deepEqual(normalized, [
    "document.read",
    "document.write",
    "spreadsheet.write",
    "presentation.write",
    "text.analyze",
    "web.research",
    "math.solve",
  ]);

  const summary = summarizeRuntimeCapabilities(normalized);
  assert.equal(summary.total, 7);
  assert.equal(summary.categories.document, 6);
  assert.equal(summary.categories.quantum, 1);
  assert.equal(summary.categories.other, 0);
});
