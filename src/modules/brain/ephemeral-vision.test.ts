import assert from "node:assert/strict";
import test from "node:test";
import {
  clearEphemeralVisionCarrier,
  buildEphemeralVisionPromptBlock,
  countDistinctEphemeralImages,
  ephemeralVisionCarrierSchema,
  selectEphemeralVisionVariants,
} from "./ephemeral-vision.js";

const encoded = Buffer.from("image-bytes").toString("base64");

test("ephemeral vision requires crop coordinates for crop variants", () => {
  const parsed = ephemeralVisionCarrierSchema.safeParse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "none" },
    images: [{ imageId: "img", kind: "text_crop", mimeType: "image/jpeg", base64Data: encoded, width: 800, height: 400 }],
  });
  assert.equal(parsed.success, false);
});

test("ephemeral vision counts physical images instead of crop variants", () => {
  const carrier = ephemeralVisionCarrierSchema.parse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "none" },
    images: [
      { imageId: "a", kind: "full_frame", mimeType: "image/jpeg", base64Data: encoded, width: 800, height: 600 },
      { imageId: "a", kind: "text_crop", mimeType: "image/jpeg", base64Data: encoded, width: 600, height: 300, box: { x: 0, y: 0, w: 1, h: 0.5 } },
    ],
  });
  assert.equal(countDistinctEphemeralImages(carrier), 1);
});

test("comparison preserves one context frame per physical image", () => {
  const carrier = ephemeralVisionCarrierSchema.parse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "none" },
    images: [
      { imageId: "a", kind: "text_crop", mimeType: "image/jpeg", base64Data: encoded, width: 600, height: 300, box: { x: 0, y: 0, w: 1, h: 0.5 } },
      { imageId: "a", kind: "full_frame", mimeType: "image/jpeg", base64Data: encoded, width: 800, height: 600 },
      { imageId: "b", kind: "detail_crop", mimeType: "image/jpeg", base64Data: encoded, width: 300, height: 300, box: { x: 0.2, y: 0.2, w: 0.5, h: 0.5 } },
      { imageId: "b", kind: "full_frame", mimeType: "image/jpeg", base64Data: encoded, width: 800, height: 600 },
    ],
  });
  const selected = selectEphemeralVisionVariants(carrier, {
    cropStrategy: "text_regions",
    maxImages: 2,
    preserveImageCoverage: true,
  });
  assert.deepEqual(selected.map((image) => [image.imageId, image.kind]), [["a", "full_frame"], ["b", "full_frame"]]);
  const prompt = buildEphemeralVisionPromptBlock(selected) ?? "";
  assert.match(prompt, /visual_1\/full_frame/);
  assert.match(prompt, /visual_2\/full_frame/);
  assert.doesNotMatch(prompt, /imageId|imageId=a|imageId=b/);
});

test("speech-boundary frames produce a bounded temporal comparison contract", () => {
  const carrier = ephemeralVisionCarrierSchema.parse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "personal" },
    images: [
      {
        imageId: "start",
        kind: "full_frame",
        mimeType: "image/jpeg",
        base64Data: encoded,
        width: 800,
        height: 600,
        mediaIntent: "live_camera",
        temporalRole: "speech_start",
        temporalSequence: 0,
      },
      {
        imageId: "sample",
        kind: "full_frame",
        mimeType: "image/jpeg",
        base64Data: encoded,
        width: 800,
        height: 600,
        mediaIntent: "live_camera",
        temporalRole: "speech_sample",
        temporalSequence: 1,
      },
      {
        imageId: "end",
        kind: "full_frame",
        mimeType: "image/jpeg",
        base64Data: encoded,
        width: 800,
        height: 600,
        mediaIntent: "live_camera",
        temporalRole: "speech_end",
        temporalSequence: 2,
      },
    ],
  });
  const prompt = buildEphemeralVisionPromptBlock(carrier.images) ?? "";
  assert.match(prompt, /speech_start is the earlier snapshot/);
  assert.match(prompt, /latest bounded intermediate observation/);
  assert.match(prompt, /do not imply continuous video or unseen events/);
});

test("one speech-boundary frame forbids before-after claims", () => {
  const carrier = ephemeralVisionCarrierSchema.parse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "personal" },
    images: [{
      imageId: "end",
      kind: "full_frame",
      mimeType: "image/jpeg",
      base64Data: encoded,
      width: 800,
      height: 600,
      mediaIntent: "screen_context",
      temporalRole: "speech_end",
      temporalSequence: 2,
    }],
  });
  const prompt = buildEphemeralVisionPromptBlock(carrier.images) ?? "";
  assert.match(prompt, /Only one verified speech-boundary snapshot/);
  assert.match(prompt, /do not claim before\/after change/);
});

test("temporal role and sequence must agree", () => {
  const parsed = ephemeralVisionCarrierSchema.safeParse({
    version: 2,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "personal" },
    inputRefs: [{
      inputRef: "r".repeat(32),
      name: "frame.jpg",
      contentType: "image/jpeg",
      byteLength: 120,
      expiresAt: new Date(Date.now() + 60_000).toISOString(),
      mediaIntent: "live_camera",
      temporalRole: "speech_start",
      temporalSequence: 1,
    }],
  });
  assert.equal(parsed.success, false);
});

test("ephemeral vision prioritizes task-specific crops", () => {
  const carrier = ephemeralVisionCarrierSchema.parse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "none" },
    images: [
      { imageId: "img", kind: "full_frame", mimeType: "image/jpeg", base64Data: encoded, width: 1200, height: 900 },
      { imageId: "img", kind: "text_crop", mimeType: "image/jpeg", base64Data: encoded, width: 1000, height: 500, box: { x: 0, y: 0, w: 1, h: 0.5 } },
    ],
  });
  assert.equal(selectEphemeralVisionVariants(carrier, { cropStrategy: "text_regions", maxImages: 1 })[0]?.kind, "text_crop");
  clearEphemeralVisionCarrier(carrier);
  assert.equal(carrier.images.length, 0);
});

test("fine-text budget keeps both crop detail and full-frame context", () => {
  const carrier = ephemeralVisionCarrierSchema.parse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "personal" },
    images: [
      { imageId: "doc", kind: "full_frame", mimeType: "image/jpeg", base64Data: encoded, width: 1200, height: 900 },
      { imageId: "doc", kind: "text_crop", mimeType: "image/jpeg", base64Data: encoded, width: 1000, height: 500, box: { x: 0, y: 0, w: 1, h: 0.5 } },
    ],
  });
  const selected = selectEphemeralVisionVariants(carrier, {
    cropStrategy: "text_regions",
    maxImages: 2,
  });
  assert.deepEqual(selected.map((image) => image.kind), ["text_crop", "full_frame"]);
});

test("two-image fine-text comparison keeps context and detail for both sources", () => {
  const carrier = ephemeralVisionCarrierSchema.parse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "personal" },
    images: [
      { imageId: "a", kind: "full_frame", mimeType: "image/jpeg", base64Data: encoded, width: 1200, height: 900 },
      { imageId: "a", kind: "text_crop", mimeType: "image/jpeg", base64Data: encoded, width: 1000, height: 500, box: { x: 0, y: 0, w: 1, h: 0.5 } },
      { imageId: "b", kind: "full_frame", mimeType: "image/jpeg", base64Data: encoded, width: 1200, height: 900 },
      { imageId: "b", kind: "text_crop", mimeType: "image/jpeg", base64Data: encoded, width: 1000, height: 500, box: { x: 0, y: 0, w: 1, h: 0.5 } },
    ],
  });
  const selected = selectEphemeralVisionVariants(carrier, {
    cropStrategy: "text_regions",
    maxImages: 4,
    preserveImageCoverage: true,
  });
  assert.equal(new Set(selected.map((image) => image.imageId)).size, 2);
  assert.equal(selected.filter((image) => image.kind === "full_frame").length, 2);
  assert.equal(selected.filter((image) => image.kind === "text_crop").length, 2);
});

test("ephemeral vision rejects crop boxes outside the source frame", () => {
  const parsed = ephemeralVisionCarrierSchema.safeParse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "none" },
    images: [{
      imageId: "img",
      kind: "detail_crop",
      mimeType: "image/jpeg",
      base64Data: encoded,
      width: 600,
      height: 400,
      box: { x: 0.8, y: 0.2, w: 0.4, h: 0.5 },
    }],
  });
  assert.equal(parsed.success, false);
});

test("ephemeral vision cleanup is deterministic and idempotent", () => {
  const carrier = ephemeralVisionCarrierSchema.parse({
    version: 1,
    retention: "request_ephemeral",
    privacy: { metadataStripped: true, userAuthorizedCloud: true, localSensitivity: "none" },
    images: [{ imageId: "private-image", kind: "full_frame", mimeType: "image/jpeg", base64Data: encoded, width: 800, height: 600 }],
  });
  const image = carrier.images[0];
  clearEphemeralVisionCarrier(carrier);
  assert.equal(image?.base64Data, "");
  assert.equal(carrier.images.length, 0);
  assert.doesNotThrow(() => clearEphemeralVisionCarrier(carrier));
});
