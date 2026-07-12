import type { VisionMediaDecision } from "./vision-media-policy.js";
import type { VisionTaskDecision } from "./vision-task-policy.js";
import { buildVisionRecoveryMessage } from "./vision-user-messages.js";
import { stripVisionProviderAttribution, VISION_PROVIDER_NAME_PATTERN } from "./vision-provider-privacy.js";

const INTERNAL_VISION_PATTERN = /(?:vision[_ -]?(?:task|media|evidence)|cloudVisionOptIn|request_ephemeral|provider-neutral|image_url|base64)/giu;
const STRONG_CERTAINTY_PATTERN = /(?<!\p{L})(kesinlikle|kesin olarak|şüphesiz|şuphesiz|definitely|certainly|without doubt)(?!\p{L})/iu;

export type VisionAnswerGateResult = {
  text: string;
  accepted: boolean;
  flags: string[];
};

export function gateVisionAnswer(input: {
  text: string;
  prompt?: string;
  task: VisionTaskDecision;
  media: VisionMediaDecision;
  imageCount: number;
  expectedPhysicalImageCount?: number;
  verifiedPhysicalImageCount?: number;
  inputQualityScore?: number | null;
  preprocessingWarnings?: string[];
  criticalConflict?: boolean;
}): VisionAnswerGateResult {
  const flags: string[] = [];
  let text = String(input.text ?? "");
  if (text.search(VISION_PROVIDER_NAME_PATTERN) >= 0) {
    flags.push("provider_name_removed");
    text = stripVisionProviderAttribution(text);
  }
  if (text.search(INTERNAL_VISION_PATTERN) >= 0) {
    flags.push("internal_vision_metadata_removed");
    text = text.replace(INTERNAL_VISION_PATTERN, "");
  }
  text = text.replace(/[ \t]{2,}/g, " ").replace(/\n{3,}/g, "\n\n").trim();

  const prompt = String(input.prompt ?? "");
  if (input.imageCount === 0) {
    flags.push("missing_visual_input");
    const alreadyAcknowledgesMissingInput = /(?<!\p{L})(görseli göremiyorum|gorseli goremiyorum|görsel ulaşmadı|gorsel ulasmadi|görsel okunamadı|gorsel okunamadi|can't see the image|cannot see the image|image was not available|image could not be read)(?!\p{L})/iu.test(text);
    if (!alreadyAcknowledgesMissingInput) {
      text = buildVisionRecoveryMessage({ prompt, reason: "missing", task: input.task });
    }
  }
  const preprocessingBusy = (input.preprocessingWarnings ?? []).some((warning) =>
    ["preprocessing_capacity", "preprocessing_timeout"].includes(warning));
  if (preprocessingBusy) {
    flags.push("visual_processing_busy");
    text = buildVisionRecoveryMessage({ prompt, reason: "busy", task: input.task });
  }
  if (input.criticalConflict) {
    flags.push("critical_visual_conflict");
    text = buildVisionRecoveryMessage({ prompt, reason: "conflict", task: input.task });
  }
  const missingComparisonImage =
    !preprocessingBusy && !input.criticalConflict &&
    input.task.primary === "visual_comparison" &&
    (input.expectedPhysicalImageCount ?? 0) > (input.verifiedPhysicalImageCount ?? input.imageCount);
  if (missingComparisonImage) {
    flags.push("incomplete_visual_comparison");
    text = buildVisionRecoveryMessage({ prompt, reason: "comparison", task: input.task });
  }
  const severeFineDetailQuality =
    !preprocessingBusy && !input.criticalConflict &&
    input.imageCount > 0 &&
    input.task.requiresFineText &&
    ((input.inputQualityScore != null && input.inputQualityScore < 0.32) ||
      (input.preprocessingWarnings ?? []).some((warning) =>
        ["near_blank_image", "insufficient_resolution"].includes(warning)));
  if (severeFineDetailQuality) {
    flags.push("unreadable_fine_detail");
    text = buildVisionRecoveryMessage({ prompt, reason: "fine_detail", task: input.task });
  }
  const insufficientFineDetail =
    input.task.requiresFineText &&
    (input.media.profile !== "detail" || input.media.preferredMaxEdge < 1280 ||
      (input.inputQualityScore != null && input.inputQualityScore < 0.5));
  if (insufficientFineDetail && STRONG_CERTAINTY_PATTERN.test(text)) {
    flags.push("unsupported_visual_certainty");
    text = text.replace(STRONG_CERTAINTY_PATTERN, "görülebildiği kadarıyla");
  }
  return {
    text,
    accepted: !flags.some((flag) => ["missing_visual_input", "visual_processing_busy", "critical_visual_conflict", "incomplete_visual_comparison", "unreadable_fine_detail"].includes(flag)),
    flags,
  };
}
