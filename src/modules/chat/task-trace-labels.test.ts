import assert from "node:assert/strict";
import test from "node:test";
import { withCapabilityStepLabels } from "./task-trace.js";
import type { ElyanTaskTraceBlock } from "../../contracts/domain.js";

// ---------------------------------------------------------------------------
// Canlı ekran (2026-08-22): telefonda adım satırı "document_write — ." göründü.
// Başlık ham yetenek kimliğiydi; mobil, etiket yoksa `capability` alanına
// düşüyor. Manifest `displayName` taşıyor ("Belge yazma") ama kullanan yoktu.
// ---------------------------------------------------------------------------

function block(steps: unknown[]): ElyanTaskTraceBlock {
  return {
    type: "task_trace",
    status: "waiting_approval",
    steps,
  } as unknown as ElyanTaskTraceBlock;
}

test("yetenek kimliği insan okunur etikete çevrilir", () => {
  const result = withCapabilityStepLabels(
    block([{ id: "tool", capability: "document_write", status: "waiting_approval" }]),
  );
  const label = (result.steps?.[0] as { label?: string })?.label ?? "";
  assert.notEqual(label, "document_write", "etiket hâlâ ham kimlik");
  assert.ok(label.length > 0);
});

test("etiket yetenek kimliğinin aynısıysa düzeltilir", () => {
  const result = withCapabilityStepLabels(
    block([{ id: "tool", capability: "open_app", label: "open_app" }]),
  );
  assert.notEqual((result.steps?.[0] as { label?: string })?.label, "open_app");
});

test("gerçek etiket KORUNUR", () => {
  // Trace yolunun Türkçe etiketleri (STEP_LABELS) ezilmemeli.
  const result = withCapabilityStepLabels(
    block([{ id: "tool", capability: "document_write", label: "Araç akışı" }]),
  );
  assert.equal((result.steps?.[0] as { label?: string })?.label, "Araç akışı");
});

test("yeteneksiz adıma dokunulmaz", () => {
  const input = block([{ id: "intent", label: "İstek analizi" }]);
  assert.equal(withCapabilityStepLabels(input), input);
});
