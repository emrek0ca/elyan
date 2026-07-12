import type { VisionTaskDecision } from "./vision-task-policy.js";

export function shouldPersistSessionVisionEvidence(input: {
  task: VisionTaskDecision;
  answerAccepted: boolean;
  answerFlags: string[];
  expectedPhysicalImageCount: number;
  verifiedPhysicalImageCount: number;
  qualityScore: number;
  summary: string;
}): { persist: boolean; reasons: string[] } {
  const reasons: string[] = [];
  if (!input.answerAccepted) reasons.push("answer_rejected");
  if (input.expectedPhysicalImageCount <= 0) reasons.push("no_request_image");
  if (input.verifiedPhysicalImageCount < input.expectedPhysicalImageCount) reasons.push("incomplete_image_coverage");
  const minimumQuality = input.task.requiresFineText ? 0.48 : 0.35;
  if (input.qualityScore < minimumQuality) reasons.push("quality_below_memory_threshold");
  if (!input.summary.trim()) reasons.push("empty_summary");
  if (input.answerFlags.some((flag) => [
    "missing_visual_input",
    "visual_processing_busy",
    "critical_visual_conflict",
    "incomplete_visual_comparison",
    "unreadable_fine_detail",
  ].includes(flag))) reasons.push("non_evidentiary_answer");
  return { persist: reasons.length === 0, reasons };
}
