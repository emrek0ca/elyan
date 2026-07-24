import assert from "node:assert/strict";
import test from "node:test";
import { gateVisionAnswer } from "./vision-answer-gate.js";
import { classifyVisionTask } from "./vision-task-policy.js";
import { decideVisionMediaPolicy } from "./vision-media-policy.js";

test("provider names survive the vision answer gate while internal metadata is removed", () => {
  const task = classifyVisionTask({ prompt: "Görselde ne var?", imageCount: 1 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Görselde ne var?", explicitCloudConsent: true });
  const result = gateVisionAnswer({
    text: "Gemini vision_evidence ile bunu gördü.",
    task,
    media,
    imageCount: 1,
  });
  assert.match(result.text, /Gemini/iu);
  assert.doesNotMatch(result.text, /vision_evidence/iu);
  assert.doesNotMatch(result.text, /görsel analiz sistemi/iu);
  assert.ok(result.flags.includes("internal_vision_metadata_removed"));
});

test("provider attribution is preserved without robotic replacement", () => {
  const task = classifyVisionTask({ prompt: "Explain this image", imageCount: 1 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Explain this image", explicitCloudConsent: true });
  const result = gateVisionAnswer({
    text: "According to Gemini, the visible warning says connection timeout.",
    prompt: "Explain this image",
    task,
    media,
    imageCount: 1,
  });
  assert.equal(result.text, "According to Gemini, the visible warning says connection timeout.");
  assert.doesNotMatch(result.text, /system/iu);
});

test("missing verified image cannot produce a visual hallucination", () => {
  const task = classifyVisionTask({ prompt: "Bu görselde ne var?", imageCount: 1 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Bu görselde ne var?", explicitCloudConsent: true, imageCount: 1 });
  const result = gateVisionAnswer({
    text: "Görselde kırmızı bir araba var.",
    prompt: "Bu görselde ne var?",
    task,
    media,
    imageCount: 0,
  });
  assert.equal(result.accepted, false);
  assert.match(result.text, /Görsel doğrulanamadı/);
  assert.doesNotMatch(result.text, /kırmızı bir araba/);
});

test("fine text on a low-quality image asks for a focused crop", () => {
  const task = classifyVisionTask({ prompt: "Ekrandaki hata mesajını oku", imageCount: 1 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Ekrandaki hata mesajını oku", explicitCloudConsent: true, imageCount: 1 });
  const result = gateVisionAnswer({
    text: "Hata kesinlikle bağlantı sorunu.",
    prompt: "Ekrandaki hata mesajını oku",
    task,
    media,
    imageCount: 1,
    inputQualityScore: 0.2,
  });
  assert.equal(result.accepted, false);
  assert.ok(result.flags.includes("unreadable_fine_detail"));
  assert.match(result.text, /hata mesajının bulunduğu bölümü/i);
});

test("comparison cannot proceed with missing physical image coverage", () => {
  const task = classifyVisionTask({ prompt: "Bu iki görseli karşılaştır", imageCount: 2 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Bu iki görseli karşılaştır", explicitCloudConsent: true, imageCount: 2 });
  const result = gateVisionAnswer({
    text: "İlk görsel daha net.",
    prompt: "Bu iki görseli karşılaştır",
    task,
    media,
    imageCount: 1,
    expectedPhysicalImageCount: 2,
    verifiedPhysicalImageCount: 1,
    inputQualityScore: 0.8,
  });
  assert.equal(result.accepted, false);
  assert.ok(result.flags.includes("incomplete_visual_comparison"));
  assert.doesNotMatch(result.text, /İlk görsel daha net/);
});

test("preprocessing capacity is not misreported as a bad image", () => {
  const task = classifyVisionTask({ prompt: "Bu görseli açıkla", imageCount: 1 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Bu görseli açıkla", explicitCloudConsent: true, imageCount: 1 });
  const result = gateVisionAnswer({
    text: "Görsel okunamadı.",
    prompt: "Bu görseli açıkla",
    task,
    media,
    imageCount: 0,
    preprocessingWarnings: ["preprocessing_capacity"],
  });
  assert.equal(result.accepted, false);
  assert.ok(result.flags.includes("visual_processing_busy"));
  assert.match(result.text, /şu anda yoğun/i);
  assert.doesNotMatch(result.text, /daha net/i);
});

test("critical OCR disagreement never reaches the user as a guessed value", () => {
  const task = classifyVisionTask({ prompt: "Ekrandaki hata kodunu oku", imageCount: 1 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Ekrandaki hata kodunu oku", explicitCloudConsent: true, imageCount: 1 });
  const result = gateVisionAnswer({
    text: "Kod kesinlikle E104.",
    prompt: "Ekrandaki hata kodunu oku",
    task,
    media,
    imageCount: 1,
    inputQualityScore: 0.8,
    criticalConflict: true,
  });
  assert.equal(result.accepted, false);
  assert.ok(result.flags.includes("critical_visual_conflict"));
  assert.doesNotMatch(result.text, /E104/);
  assert.match(result.text, /Tahmin etmek istemiyorum/i);
});
