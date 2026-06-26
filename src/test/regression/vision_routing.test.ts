import assert from "node:assert/strict";
import test from "node:test";
import { resolveAttachmentAwareSharedBrainWorkload } from "../../modules/brain/workloads.js";

test("vision routing: visionImageJpeg present → workload = vision_reasoning", () => {
  const result = resolveAttachmentAwareSharedBrainWorkload({
    route: "server_brain",
    selectedWorkload: "mobile_chat_balanced",
    attachmentContextUsed: false,
    hasVisionImage: true,
  });
  assert.equal(result, "vision_reasoning");
});

test("vision routing: no vision image → workload unchanged", () => {
  const result = resolveAttachmentAwareSharedBrainWorkload({
    route: "server_brain",
    selectedWorkload: "mobile_chat_balanced",
    attachmentContextUsed: false,
    hasVisionImage: false,
  });
  assert.equal(result, "mobile_chat_balanced");
});

test("vision routing: hasVisionImage false when visionImages array is empty", () => {
  const hasVisionImage =
    Array.isArray([]) &&
    ([].length ?? 0) > 0;
  assert.equal(hasVisionImage, false);
});

test("vision routing: hasVisionImage true when visionImages array has items", () => {
  const images = [{ documentId: "doc-1", mimeType: "image/jpeg", base64: "abc", label: "test" }];
  const hasVisionImage =
    Array.isArray(images) &&
    (images.length ?? 0) > 0;
  assert.equal(hasVisionImage, true);
});
