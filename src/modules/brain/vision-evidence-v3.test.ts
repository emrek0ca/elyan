import assert from "node:assert/strict";
import test from "node:test";
import {
  buildSessionVisionEvidenceV3,
  formatVisionEvidenceV3Prompt,
  normalizeVisionEvidence,
  visionEvidenceV3Schema,
} from "./vision-evidence-v3.js";

function v2Block() {
  return {
    id: "vision-1",
    type: "vision",
    version: 2,
    render: { status: "ready" },
    source: {
      kind: "image",
      privacy: "local_extracted_only",
      image_sent_to_server: false,
      platform: "ios",
      engine: "apple_vision",
    },
    input_kind: { value: "document", confidence: 0.9 },
    quality: {
      resolution: { width: 1200, height: 1600 },
      rotation: 0,
      is_readable: true,
      warnings: [],
    },
    text: {
      full_text: "Fatura toplam 1.250 TL",
      blocks: [{
        text: "Fatura toplam 1.250 TL",
        confidence: 0.93,
        box: { x: 0.1, y: 0.1, w: 0.8, h: 0.1 },
        role: "body",
      }],
    },
    scene: { labels: [], objects: [] },
    documents: { detected: true, pages: [] },
    barcodes: [],
    task_hints: ["document_ocr"],
    summary_for_llm: "Bir fatura görünüyor.",
    confidence: { overall: 0.88, ocr: 0.93, scene: 0.5, document: 0.9 },
  };
}

test("VisionBlock v2 upgrades into v3 evidence", () => {
  const normalized = normalizeVisionEvidence(v2Block());
  assert.ok(normalized);
  assert.equal(normalized.version, 3);
  assert.equal(normalized.source.mode, "local_only");
  assert.equal(normalized.task.primary, "document_ocr");
  assert.equal(normalized.text.spans[0]?.text, "Fatura toplam 1.250 TL");
});

test("v3 schema allows provider names as engine identifiers", () => {
  const normalized = normalizeVisionEvidence(v2Block());
  assert.ok(normalized);
  const invalid = {
    ...normalized,
    source: { ...normalized.source, engines: ["gemini"] },
  };
  assert.equal(visionEvidenceV3Schema.safeParse(invalid).success, true);
});

test("v3 prompt exposes evidence but not raw device engine internals", () => {
  const normalized = normalizeVisionEvidence(v2Block());
  assert.ok(normalized);
  const prompt = formatVisionEvidenceV3Prompt([normalized]) ?? "";
  assert.match(prompt, /Observed text/u);
  assert.doesNotMatch(prompt, /apple_vision|gemini|groq/iu);
});

test("session-derived vision evidence stores no image bytes and only an optional one-way hash", () => {
  const evidence = buildSessionVisionEvidenceV3({
    task: "screen_debugging",
    summary: "Ekranda E104 bağlantı zaman aşımı uyarısı görünüyor.",
    width: 1200,
    height: 800,
    sensitivity: "personal",
    cloudUsed: true,
    confidence: 0.78,
    contentHash: "sha256-normalized-image-123",
  });
  assert.equal(evidence.source.retention, "session_derived");
  assert.equal(evidence.image.content_hash, "sha256-normalized-image-123");
  assert.equal(evidence.image.metadata_stripped, true);
  assert.doesNotMatch(JSON.stringify(evidence), /base64/iu);
});
