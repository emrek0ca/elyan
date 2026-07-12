import assert from "node:assert/strict";
import test from "node:test";
import { shouldPersistSessionVisionEvidence } from "./vision-memory-policy.js";
import { classifyVisionTask } from "./vision-task-policy.js";

test("verified visual answer is eligible for session-derived memory", () => {
  const task = classifyVisionTask({ prompt: "Bu fotoğrafta ne oluyor?", imageCount: 1 });
  const decision = shouldPersistSessionVisionEvidence({
    task,
    answerAccepted: true,
    answerFlags: [],
    expectedPhysicalImageCount: 1,
    verifiedPhysicalImageCount: 1,
    qualityScore: 0.75,
    summary: "Fotoğrafta yağmur altında yürüyen iki kişi var.",
  });
  assert.equal(decision.persist, true);
});

test("busy or conflicting visual turn never becomes session memory", () => {
  const task = classifyVisionTask({ prompt: "Ekrandaki hata kodunu oku", imageCount: 1 });
  for (const flag of ["visual_processing_busy", "critical_visual_conflict"]) {
    const decision = shouldPersistSessionVisionEvidence({
      task,
      answerAccepted: false,
      answerFlags: [flag],
      expectedPhysicalImageCount: 1,
      verifiedPhysicalImageCount: 1,
      qualityScore: 0.8,
      summary: "Görseli yeniden gönder.",
    });
    assert.equal(decision.persist, false);
    assert.ok(decision.reasons.includes("non_evidentiary_answer"));
  }
});

test("fine-text memory requires stronger image quality and full coverage", () => {
  const task = classifyVisionTask({ prompt: "Bu iki belgedeki kodları oku", imageCount: 2 });
  const decision = shouldPersistSessionVisionEvidence({
    task,
    answerAccepted: true,
    answerFlags: [],
    expectedPhysicalImageCount: 2,
    verifiedPhysicalImageCount: 1,
    qualityScore: 0.4,
    summary: "İlk belgede E104 yazıyor.",
  });
  assert.equal(decision.persist, false);
  assert.ok(decision.reasons.includes("incomplete_image_coverage"));
  assert.ok(decision.reasons.includes("quality_below_memory_threshold"));
});
