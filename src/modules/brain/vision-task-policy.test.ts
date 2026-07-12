import assert from "node:assert/strict";
import test from "node:test";
import { classifyVisionTask } from "./vision-task-policy.js";

const cases = [
  ["Bu faturadaki toplam tutarı bul", "receipt_or_invoice"],
  ["Ekran görüntüsündeki Flutter hatasını açıkla", "code_screenshot"],
  ["Bu tablodaki satırları çıkar", "table_extraction"],
  ["Grafikteki trendi yorumla", "chart_interpretation"],
  ["El yazısını oku", "handwriting"],
  ["Bu ürünün markası ne?", "product_identification"],
  ["Lee el mensaje de error en esta pantalla", "code_screenshot"],
  ["Vergleiche diese beiden Bilder", "visual_comparison"],
  ["Lis les montants de cette facture", "receipt_or_invoice"],
  ["Интерпретируй этот график", "chart_interpretation"],
  ["اقرأ النص في هذا المستند", "document_ocr"],
] as const;

for (const [prompt, expected] of cases) {
  test(`vision task classifies ${expected}`, () => {
    const decision = classifyVisionTask({ prompt, imageCount: 1 });
    assert.equal(decision.primary, expected);
  });
}

test("multiple images default to visual comparison", () => {
  const decision = classifyVisionTask({ prompt: "Bunların farkı ne?", imageCount: 2 });
  assert.equal(decision.primary, "visual_comparison");
  assert.equal(decision.requiresSpatialReasoning, true);
});

test("crop variants from one physical image do not imply comparison", () => {
  const decision = classifyVisionTask({ prompt: "Bu görseli açıkla", imageCount: 1 });
  assert.notEqual(decision.primary, "visual_comparison");
});

test("multi-image comparison preserves secondary fine-text requirements", () => {
  const decision = classifyVisionTask({ prompt: "Bu iki belgedeki hata kodlarını karşılaştır", imageCount: 2 });
  assert.equal(decision.primary, "code_screenshot");
  assert.ok(decision.secondary.includes("document_ocr") || decision.secondary.includes("visual_comparison"));
  assert.equal(decision.requiresFineText, true);
  assert.equal(decision.requiresSpatialReasoning, true);
});
