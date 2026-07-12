import assert from "node:assert/strict";
import test from "node:test";
import type { ClientImageAttachment } from "./document-types.js";
import { classifyVisionTask } from "./vision-task-policy.js";
import { calculateVisionVariantBudget, classifyVisionSensitivity, decideVisionMediaPolicy } from "./vision-media-policy.js";

const image = (ocrText = "", override: Partial<ClientImageAttachment> = {}): ClientImageAttachment => ({
  imageId: "img_1",
  mimeType: "image/jpeg",
  fileName: "screen.jpg",
  base64Thumbnail: "aGVsbG8=",
  thumbnailWidth: 512,
  thumbnailHeight: 512,
  ocrText,
  originalSizeBytes: 1000,
  imageCategory: "screenshot",
  ...override,
});

test("fine text tasks select detail media without exceeding bounded image count", () => {
  const task = classifyVisionTask({ prompt: "Bu ekran görüntüsündeki hata mesajını oku", imageCount: 1 });
  const decision = decideVisionMediaPolicy({
    task,
    images: [image()],
    prompt: "Bu ekran görüntüsündeki hata mesajını oku",
    explicitCloudConsent: true,
  });
  assert.equal(decision.profile, "detail");
  assert.equal(decision.resolution, "high");
  assert.equal(decision.maxImages, 2);
});

test("credential-like visual content fails closed even with cloud consent", () => {
  const task = classifyVisionTask({ prompt: "Bunu oku", imageCount: 1 });
  const decision = decideVisionMediaPolicy({
    task,
    images: [image("Password: secret")],
    prompt: "Bunu oku",
    explicitCloudConsent: true,
  });
  assert.equal(decision.allowCloud, false);
  assert.equal(decision.profile, "restricted");
});

test("visual comparison preserves coverage across physical images", () => {
  const task = classifyVisionTask({ prompt: "Bunların farkı ne?", imageCount: 2 });
  const decision = decideVisionMediaPolicy({
    task,
    images: [image()],
    prompt: "Bunların farkı ne?",
    explicitCloudConsent: true,
    imageCount: 2,
  });
  assert.equal(task.primary, "visual_comparison");
  assert.equal(decision.preserveImageCoverage, true);
  assert.equal(decision.maxImages, 2);
});

test("fine-text primary still preserves secondary comparison coverage", () => {
  const task = classifyVisionTask({ prompt: "Bu iki belgedeki hata kodlarını karşılaştır", imageCount: 2 });
  const decision = decideVisionMediaPolicy({
    task,
    images: [image()],
    prompt: "Bu iki belgedeki hata kodlarını karşılaştır",
    explicitCloudConsent: true,
    imageCount: 2,
  });
  assert.equal(task.requiresFineText, true);
  assert.ok(task.secondary.includes("visual_comparison"));
  assert.equal(decision.profile, "detail");
  assert.equal(decision.preserveImageCoverage, true);
  assert.equal(decision.maxImages, 4);
});

test("vision variant budget keeps context plus crop without exceeding four", () => {
  assert.equal(calculateVisionVariantBudget({ imageCount: 1, fineDetail: true }), 2);
  assert.equal(calculateVisionVariantBudget({ imageCount: 2, fineDetail: true }), 4);
  assert.equal(calculateVisionVariantBudget({ imageCount: 4, fineDetail: true }), 4);
  assert.equal(calculateVisionVariantBudget({ imageCount: 3, fineDetail: false }), 3);
  assert.equal(calculateVisionVariantBudget({ imageCount: 0, fineDetail: true }), 0);
});

test("documents and portraits are classified as personal by default", () => {
  assert.equal(classifyVisionSensitivity({
    prompt: "Bunu özetle",
    images: [image("", { imageCategory: "document", fileName: "report.jpg" })],
  }), "personal");
  assert.equal(classifyVisionSensitivity({
    prompt: "Describe this family photo",
    images: [image("", { imageCategory: "photo", fileName: "photo.jpg" })],
  }), "personal");
});

test("identity and credential content fails closed across languages", () => {
  assert.equal(classifyVisionSensitivity({
    prompt: "Lee este pasaporte",
    images: [image("", { imageCategory: "document", fileName: "scan.jpg" })],
  }), "restricted");
  assert.equal(classifyVisionSensitivity({
    prompt: "اقرأ رمز التحقق",
    images: [image("", { imageCategory: "screenshot", fileName: "screen.jpg" })],
  }), "restricted");
});

test("declared sensitivity can raise but never downgrade inferred sensitivity", () => {
  const task = classifyVisionTask({ prompt: "Bu sağlık raporunu açıkla", imageCount: 1 });
  const decision = decideVisionMediaPolicy({
    task,
    images: [image("teşhis sonucu", { imageCategory: "document" })],
    prompt: "Bu sağlık raporunu açıkla",
    explicitCloudConsent: true,
    declaredSensitivity: "none",
  });
  assert.equal(decision.sensitivity, "sensitive");
  assert.equal(decision.allowCloud, true);
});

test("an ephemeral image without attachment metadata is personal at minimum", () => {
  const task = classifyVisionTask({ prompt: "What is this?", imageCount: 1 });
  const decision = decideVisionMediaPolicy({
    task,
    images: [],
    prompt: "What is this?",
    explicitCloudConsent: true,
    declaredSensitivity: "none",
    imageCount: 1,
  });
  assert.equal(decision.sensitivity, "personal");
  assert.equal(decision.allowCloud, true);
});

test("ordinary technical use of minor does not become sensitive", () => {
  const task = classifyVisionTask({ prompt: "Explain this minor visual issue", imageCount: 1 });
  const decision = decideVisionMediaPolicy({
    task,
    images: [],
    prompt: "Explain this minor visual issue",
    explicitCloudConsent: true,
    imageCount: 1,
  });
  assert.equal(decision.sensitivity, "personal");
});
