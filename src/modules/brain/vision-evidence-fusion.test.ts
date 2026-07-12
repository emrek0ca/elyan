import assert from "node:assert/strict";
import test from "node:test";
import { buildVisionEvidenceFusionPromptBlock, prepareVisionEvidenceFusion } from "./vision-evidence-fusion.js";
import { classifyVisionTask } from "./vision-task-policy.js";

test("uses meaningful OCR as a critical cross-check", () => {
  const fusion = prepareVisionEvidenceFusion({ ocrTexts: ["Connection failed\nError code E104"], task: classifyVisionTask({ prompt: "Ekrandaki hata kodunu oku", imageCount: 1 }) });
  assert.equal(fusion.mode, "critical_crosscheck");
  assert.match(buildVisionEvidenceFusionPromptBlock(fusion) ?? "", /never as instructions/u);
});

test("rejects short noisy OCR", () => {
  const fusion = prepareVisionEvidenceFusion({ ocrTexts: [".."], task: classifyVisionTask({ prompt: "Bu görseli açıkla", imageCount: 1 }) });
  assert.equal(fusion.mode, "none");
  assert.equal(fusion.usableText, "");
});

test("deduplicates lines and removes engine attribution", () => {
  const fusion = prepareVisionEvidenceFusion({ ocrTexts: ["Groq\nInvoice total: 120 TL\nInvoice total: 120 TL"], task: classifyVisionTask({ prompt: "Faturadaki toplamı oku", imageCount: 1 }) });
  assert.doesNotMatch(fusion.usableText, /groq/iu);
  assert.equal(fusion.usableText.match(/Invoice total/gu)?.length, 1);
});
