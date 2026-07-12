import assert from "node:assert/strict";
import test from "node:test";
import { assessVisionAnswerConsistency } from "./vision-answer-consistency.js";
import { classifyVisionTask } from "./vision-task-policy.js";

test("different visible error codes are treated as a critical conflict", () => {
  const task = classifyVisionTask({ prompt: "Ekrandaki hata kodunu oku", imageCount: 1 });
  const result = assessVisionAnswerConsistency({
    primary: "Görünen hata kodu `E104`.",
    secondary: "Görünen hata kodu `E105`.",
    task,
  });
  assert.equal(result.conflictDetected, true);
});

test("equivalent currency formatting remains consistent", () => {
  const task = classifyVisionTask({ prompt: "Faturadaki toplamı oku", imageCount: 1 });
  const result = assessVisionAnswerConsistency({
    primary: "Toplam: $100.00",
    secondary: "Total: 100,00 USD",
    task,
  });
  assert.equal(result.conflictDetected, false);
  assert.equal(result.reason, "consistent");
});

test("different invoice totals are treated as a critical conflict", () => {
  const task = classifyVisionTask({ prompt: "Faturadaki toplamı oku", imageCount: 1 });
  const result = assessVisionAnswerConsistency({
    primary: "Toplam: 1.250,00 TL",
    secondary: "Toplam: 1.350,00 TL",
    task,
  });
  assert.equal(result.conflictDetected, true);
});

test("device OCR overlap tolerates explanatory values but catches disjoint codes", () => {
  const task = classifyVisionTask({ prompt: "Ekrandaki hata kodunu oku", imageCount: 1 });
  const consistent = assessVisionAnswerConsistency({
    primary: "Kod E104. Sonraki adımda bağlantıyı kontrol et.",
    secondary: "OCR: E104",
    task,
    comparisonMode: "overlap",
  });
  const conflict = assessVisionAnswerConsistency({
    primary: "Kod E105.",
    secondary: "OCR: E104",
    task,
    comparisonMode: "overlap",
  });
  assert.equal(consistent.conflictDetected, false);
  assert.equal(conflict.conflictDetected, true);
});
