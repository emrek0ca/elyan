import type { VisionMediaDecision } from "./vision-media-policy.js";

export type VisionInputGateDecision = {
  shortCircuit: boolean;
  reason: "pass" | "missing" | "busy" | "privacy";
};

export function evaluateVisionInputGate(input: {
  cloudVisionActive: boolean;
  physicalImageCount: number;
  verifiedImageCount: number;
  media: VisionMediaDecision;
  preprocessingWarnings: string[];
}): VisionInputGateDecision {
  if (!input.cloudVisionActive || input.physicalImageCount <= 0 || input.verifiedImageCount > 0) {
    return { shortCircuit: false, reason: "pass" };
  }
  if (input.media.sensitivity === "restricted" || !input.media.allowCloud) {
    return { shortCircuit: true, reason: "privacy" };
  }
  if (input.preprocessingWarnings.some((warning) =>
    warning === "preprocessing_capacity" || warning === "preprocessing_timeout")) {
    return { shortCircuit: true, reason: "busy" };
  }
  return { shortCircuit: true, reason: "missing" };
}
