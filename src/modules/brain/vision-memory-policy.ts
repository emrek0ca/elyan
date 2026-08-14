import type { VisionTaskDecision } from "./vision-task-policy.js";

/**
 * Session-derived visual evidence is a short-lived working-memory aid, not a
 * permanent visual archive. The chat row remains durable, but stale evidence
 * must not silently become the answer to a later visual follow-up.
 */
export const SESSION_VISION_MEMORY_TTL_MS = 2 * 60 * 60 * 1000;

export function isSessionVisionMemoryFresh(
  createdAt: Date | string | null | undefined,
  now = new Date(),
): boolean {
  if (createdAt == null || createdAt === "") {
    // Older rows may not carry a timestamp. Preserve their existing contract
    // while new rows are bounded by the explicit TTL.
    return true;
  }
  const parsed = createdAt instanceof Date ? createdAt : new Date(createdAt);
  if (!Number.isFinite(parsed.getTime())) {
    return false;
  }
  // Future timestamps are accepted to tolerate small clock skews and legacy
  // fixtures; only evidence older than the TTL is expired.
  return now.getTime() - parsed.getTime() <= SESSION_VISION_MEMORY_TTL_MS;
}

export function shouldPersistSessionVisionEvidence(input: {
  task: VisionTaskDecision;
  answerAccepted: boolean;
  answerFlags: string[];
  expectedPhysicalImageCount: number;
  verifiedPhysicalImageCount: number;
  qualityScore: number;
  summary: string;
  sensitivity?: "none" | "personal" | "sensitive" | "restricted";
}): { persist: boolean; reasons: string[] } {
  const reasons: string[] = [];
  if (input.sensitivity === "restricted") reasons.push("restricted_visual_memory");
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
