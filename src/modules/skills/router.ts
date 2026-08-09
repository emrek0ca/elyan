import type { ResolvedAttachmentContext } from "../brain/attachment-context.js";
import type { SkillRouteDecision, SkillSummary } from "./types.js";

const ROUTE_CONFIDENCE_THRESHOLD = 0.72;
const NON_SKILL_OUTPUT_KINDS = new Set(["chat_reply", "task_result", "action"]);

function normalize(value: unknown): string {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function hasPayloadType(context: ResolvedAttachmentContext, skill: SkillSummary): boolean {
  const payloadTypes = new Set(skill.triggers.payloadTypes.map((item) => normalize(item)));
  return context.documents.some((document) => {
    const mimeType = normalize(document.mimeType ?? "");
    return mimeType && payloadTypes.has(mimeType);
  });
}

function canRouteSkillWithAttachment(
  context: ResolvedAttachmentContext | null | undefined,
  skill: SkillSummary,
): boolean {
  if (!context?.used || context.documents.length === 0) {
    return !skill.requiresAttachment;
  }
  return hasPayloadType(context, skill);
}

function canProduceRequestedOutput(
  skill: SkillSummary,
  desiredOutputKinds: readonly string[] | undefined,
): boolean {
  const richOutputs = (desiredOutputKinds ?? []).filter(
    (kind) => !NON_SKILL_OUTPUT_KINDS.has(kind),
  );
  if (richOutputs.length === 0) return true;
  const produced = new Set<string>(skill.produces.desiredOutputKinds);
  return richOutputs.every((kind) => produced.has(kind));
}

export async function routeSkill(input: {
  prompt: string;
  attachmentContext?: ResolvedAttachmentContext | null;
  skills: SkillSummary[];
  skillHint?: string | null;
  desiredOutputKinds?: readonly string[];
  classify?: (input: {
    prompt: string;
    attachmentContext?: ResolvedAttachmentContext | null;
    skills: SkillSummary[];
  }) => Promise<SkillRouteDecision | null>;
}): Promise<SkillRouteDecision> {
  const context = input.attachmentContext;
  const activeSkillIds = new Set(input.skills.map((skill) => skill.id));
  const hintedSkillId = typeof input.skillHint === "string" ? input.skillHint.trim() : "";
  const hintedSkill = hintedSkillId
    ? input.skills.find((skill) => skill.id === hintedSkillId && skill.manualSelectable)
    : null;
  if (
    hintedSkill &&
    activeSkillIds.has(hintedSkill.id) &&
    canRouteSkillWithAttachment(context, hintedSkill) &&
    canProduceRequestedOutput(hintedSkill, input.desiredOutputKinds)
  ) {
    return {
      needsSkill: true,
      skillId: hintedSkill.id,
      confidence: 0.95,
      reason: `User selected ${hintedSkill.id} via composer skill hint.`,
      source: "manual_hint",
    };
  }

  const routeCompatibleSkills = input.skills.filter((skill) =>
    canRouteSkillWithAttachment(context, skill) &&
    canProduceRequestedOutput(skill, input.desiredOutputKinds),
  );
  if (routeCompatibleSkills.length === 0) {
    return {
      needsSkill: false,
      skillId: null,
      confidence: 0.9,
      reason: "No active skill produces every explicitly requested output.",
      source: "fallback",
    };
  }
  const routeCompatibleSkillIds = new Set(
    routeCompatibleSkills.map((skill) => skill.id),
  );

  const classified = input.classify
    ? await input.classify({
        prompt: input.prompt,
        attachmentContext: context,
        skills: routeCompatibleSkills,
      })
    : null;
  // Lower threshold when attachment is present — less risk of wrong skill, high risk of missing.
  const threshold = context?.documents.length ? 0.62 : ROUTE_CONFIDENCE_THRESHOLD;
  if (
    classified?.needsSkill &&
    classified.skillId &&
    routeCompatibleSkillIds.has(classified.skillId) &&
    classified.confidence >= threshold
  ) {
    return classified;
  }
  if (classified) {
    return {
      needsSkill: false,
      skillId: null,
      confidence: classified.confidence,
      reason: classified.reason || "Skill routing confidence was below threshold.",
      source: classified.source,
    };
  }

  if (!context?.used || context.documents.length === 0) {
    return {
      needsSkill: false,
      skillId: null,
      confidence: 0,
      reason: "Semantic skill routing did not select a no-attachment skill.",
      source: "fallback",
    };
  }

  const payloadMatch = routeCompatibleSkills.find((skill) =>
    hasPayloadType(context, skill),
  );
  if (payloadMatch && routeCompatibleSkills.length === 1) {
    return {
      needsSkill: true,
      skillId: payloadMatch.id,
      confidence: 0.74,
      reason: "Attachment payload type matched a single compatible skill.",
      source: "payload_type",
    };
  }

  return {
    needsSkill: false,
    skillId: null,
    confidence: 0.45,
    reason: "Skill routing confidence was below threshold.",
    source: "fallback",
  };
}
