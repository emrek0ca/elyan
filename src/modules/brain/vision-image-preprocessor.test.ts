import assert from "node:assert/strict";
import test from "node:test";
import sharp from "sharp";
import {
  calculateVisionVariantEncodedBudget,
  preprocessVisionVariants,
  shouldApplyFineTextEnhancement,
  shouldDeriveFineTextCrop,
} from "./vision-image-preprocessor.js";
import { classifyVisionTask } from "./vision-task-policy.js";
import { decideVisionMediaPolicy } from "./vision-media-policy.js";

async function patternedPng(): Promise<Buffer> {
  const svg = Buffer.from(`<svg width="900" height="600" xmlns="http://www.w3.org/2000/svg"><rect width="900" height="600" fill="white"/><g fill="black" font-size="44"><text x="40" y="100">E104 CONNECTION TIMEOUT</text><text x="40" y="180">Retry the operation</text></g><path d="M0 300 L900 500 M0 500 L900 300" stroke="red" stroke-width="18"/></svg>`);
  return sharp(svg).withMetadata({ orientation: 6 }).png().toBuffer();
}

test("preprocessor verifies dimensions, strips metadata, and removes duplicate pixels", async () => {
  const source = await patternedPng();
  const task = classifyVisionTask({ prompt: "Ekrandaki hata kodunu oku", imageCount: 2 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Ekrandaki hata kodunu oku", explicitCloudConsent: true, imageCount: 2 });
  const base64Data = source.toString("base64");
  const result = await preprocessVisionVariants({
    media,
    variants: [
      { imageId: "screen", kind: "text_crop", mimeType: "image/png", base64Data, width: 100, height: 100, box: { x: 0, y: 0, w: 1, h: 1 } },
      { imageId: "screen", kind: "text_crop", mimeType: "image/png", base64Data, width: 900, height: 600, box: { x: 0, y: 0, w: 1, h: 1 } },
    ],
  });
  assert.equal(result.variants.length, 1);
  assert.ok(result.warnings.includes("declared_dimension_mismatch"));
  assert.ok(result.warnings.includes("duplicate_pixels"));
  assert.equal(result.enhancedCount, 1);
  assert.equal(result.variants[0]?.enhancedForFineText, true);
  const outputMetadata = await sharp(Buffer.from(result.variants[0]!.base64Data, "base64")).metadata();
  assert.equal(outputMetadata.exif, undefined);
  assert.equal(outputMetadata.width, 600);
  assert.equal(outputMetadata.height, 900);
});

test("fine-text enhancement is task-aware and never enlarges tiny inputs", () => {
  const detailTask = classifyVisionTask({ prompt: "Belgedeki küçük yazıyı oku", imageCount: 1 });
  const detailMedia = decideVisionMediaPolicy({ task: detailTask, images: [], prompt: "Belgedeki küçük yazıyı oku", explicitCloudConsent: true, imageCount: 1 });
  const sceneTask = classifyVisionTask({ prompt: "Bu fotoğrafta ne oluyor?", imageCount: 1 });
  const sceneMedia = decideVisionMediaPolicy({ task: sceneTask, images: [], prompt: "Bu fotoğrafta ne oluyor?", explicitCloudConsent: true, imageCount: 1 });

  assert.equal(shouldApplyFineTextEnhancement({ media: detailMedia, kind: "text_crop", width: 1200, height: 700 }), true);
  assert.equal(shouldApplyFineTextEnhancement({ media: detailMedia, kind: "text_crop", width: 320, height: 180 }), false);
  assert.equal(shouldApplyFineTextEnhancement({ media: detailMedia, kind: "detail_crop", width: 1200, height: 700 }), false);
  assert.equal(shouldApplyFineTextEnhancement({ media: sceneMedia, kind: "full_frame", width: 1600, height: 900 }), false);
});

test("encoded budget reserves capacity for remaining physical images", () => {
  assert.equal(calculateVisionVariantEncodedBudget({ totalEncodedChars: 0, remainingPhysicalImages: 2 }), 480_000);
  assert.equal(calculateVisionVariantEncodedBudget({ totalEncodedChars: 300_000, remainingPhysicalImages: 1 }), 280_000);
  assert.equal(calculateVisionVariantEncodedBudget({ totalEncodedChars: 650_000, remainingPhysicalImages: 1 }), 0);
});

test("preprocessor derives one bounded text crop when only a full frame exists", async () => {
  const source = await patternedPng();
  const task = classifyVisionTask({ prompt: "Belgedeki küçük yazıyı oku", imageCount: 1 });
  const media = decideVisionMediaPolicy({ task, images: [], prompt: "Belgedeki küçük yazıyı oku", explicitCloudConsent: true, imageCount: 1 });
  const result = await preprocessVisionVariants({
    media,
    variants: [{
      imageId: "document",
      kind: "full_frame",
      mimeType: "image/png",
      base64Data: source.toString("base64"),
      width: 900,
      height: 600,
    }],
  });
  assert.equal(result.derivedCropCount, 1);
  assert.equal(result.variants.length, 2);
  assert.equal(result.variants.some((variant) => variant.kind === "full_frame"), true);
  assert.equal(result.variants.some((variant) => variant.kind === "text_crop"), true);
});

test("auto-crop policy skips existing crops, small images, and scene profiles", () => {
  const detailTask = classifyVisionTask({ prompt: "Belgedeki küçük yazıyı oku", imageCount: 1 });
  const detailMedia = decideVisionMediaPolicy({ task: detailTask, images: [], prompt: "Belgedeki küçük yazıyı oku", explicitCloudConsent: true, imageCount: 1 });
  const sceneTask = classifyVisionTask({ prompt: "Bu fotoğrafta ne oluyor?", imageCount: 1 });
  const sceneMedia = decideVisionMediaPolicy({ task: sceneTask, images: [], prompt: "Bu fotoğrafta ne oluyor?", explicitCloudConsent: true, imageCount: 1 });
  assert.equal(shouldDeriveFineTextCrop({ media: detailMedia, kind: "full_frame", width: 1200, height: 800, hasExistingCrop: false, currentVariantCount: 1 }), true);
  assert.equal(shouldDeriveFineTextCrop({ media: detailMedia, kind: "full_frame", width: 1200, height: 800, hasExistingCrop: true, currentVariantCount: 1 }), false);
  assert.equal(shouldDeriveFineTextCrop({ media: detailMedia, kind: "full_frame", width: 600, height: 300, hasExistingCrop: false, currentVariantCount: 1 }), false);
  assert.equal(shouldDeriveFineTextCrop({ media: sceneMedia, kind: "full_frame", width: 1200, height: 800, hasExistingCrop: false, currentVariantCount: 1 }), false);
});
