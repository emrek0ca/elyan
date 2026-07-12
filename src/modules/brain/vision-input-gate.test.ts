import assert from "node:assert/strict";
import test from "node:test";
import { evaluateVisionInputGate } from "./vision-input-gate.js";
import { decideVisionMediaPolicy } from "./vision-media-policy.js";
import { classifyVisionTask } from "./vision-task-policy.js";

function media(prompt: string) {
  const task = classifyVisionTask({ prompt, imageCount: 1 });
  return decideVisionMediaPolicy({ task, images: [], prompt, explicitCloudConsent: true, imageCount: 1 });
}

test("verified visual input proceeds to the provider", () => {
  assert.deepEqual(evaluateVisionInputGate({
    cloudVisionActive: true,
    physicalImageCount: 1,
    verifiedImageCount: 1,
    media: media("Bu görseli açıkla"),
    preprocessingWarnings: [],
  }), { shortCircuit: false, reason: "pass" });
});

test("invalid visual input short-circuits before provider invocation", () => {
  assert.deepEqual(evaluateVisionInputGate({
    cloudVisionActive: true,
    physicalImageCount: 1,
    verifiedImageCount: 0,
    media: media("Bu görseli açıkla"),
    preprocessingWarnings: ["decode_or_processing_failed"],
  }), { shortCircuit: true, reason: "missing" });
});

test("capacity and restricted content receive distinct zero-call reasons", () => {
  const ordinary = media("Bu görseli açıkla");
  const restricted = media("Bu pasaporttaki numarayı oku");
  assert.deepEqual(evaluateVisionInputGate({
    cloudVisionActive: true,
    physicalImageCount: 1,
    verifiedImageCount: 0,
    media: ordinary,
    preprocessingWarnings: ["preprocessing_capacity"],
  }), { shortCircuit: true, reason: "busy" });
  assert.deepEqual(evaluateVisionInputGate({
    cloudVisionActive: true,
    physicalImageCount: 1,
    verifiedImageCount: 0,
    media: restricted,
    preprocessingWarnings: [],
  }), { shortCircuit: true, reason: "privacy" });
});
