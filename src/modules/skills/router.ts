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

function hasAnyPhrase(prompt: string, phrases: string[]): boolean {
  const normalizedPrompt = normalize(prompt);
  return phrases.some((phrase) => {
    const normalizedPhrase = normalize(phrase);
    return normalizedPhrase && normalizedPrompt.includes(normalizedPhrase);
  });
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

function isQuestionPrompt(prompt: string): boolean {
  const normalized = normalize(prompt);
  return (
    normalized.includes("?") ||
    /\b(ne|nedir|hangi|kim|kaç|kac|nasıl|nasil|neden|niye|mi|mı|mu|mü|does|what|which|how|why|where|when)\b/u.test(
      normalized,
    ) ||
    /\b(burada ne|bunda ne|ne diyor|ne yazıyor|ne yaziyor|ne var|ne anlatıyor|ne anlatiyor)\b/u.test(normalized) ||
    /\b(anlat|açıkla|acikla|explain|describe|tell me)\b/u.test(normalized) ||
    /\b(göster|goster|listele|çıkar|cikar|bul|say|hesapla|çevir|cevir|getir|ver)\b/u.test(normalized)
  );
}

function isImageTextQuestion(prompt: string): boolean {
  const normalized = normalize(prompt);
  return /\b(ne yazıyor|ne yaziyor|ne diyor|metin|yazı|yazi|ocr|text|okunuyor|oku)\b/u.test(normalized);
}

function deterministicSkillId(prompt: string): { skillId: string; confidence: number; reason: string } | null {
  const normalized = normalize(prompt);

  if (
    /\b(önemli noktalar|onemli noktalar|ana noktalar|aksiyon|action item|key points|maddeler|kararlar|kararları|tarihler|son tarih|deadline|yükümlülük|yukumluluk|sorumluluk|görev listesi|gorev listesi|başlıklar|basliklar|obligations|decisions|sorumlular|sorumlu kişi|sorumlu kisi|görevler|gorevler|başlık|baslik|madde|tarih)\b/u.test(
      normalized,
    )
  ) {
    return {
      skillId: "document_key_points",
      confidence: 0.9,
      reason: "User asked for key points, action items, decisions, dates, or obligations from the attachment.",
    };
  }

  if (
    /\b(özetle|ozetle|özet|özeti|ozeti|summary|summarize|kısaca anlat|kisaca anlat|genel bakış|genel bakis|özetini çıkar|özetini cikar|kısalt|kisalt|özetini ver|ozetini ver|kısaca|kisaca|genel bilgi|ne hakkında|ne hakkinda|hakkında ne|hakkinda ne)\b/u.test(
      normalized,
    )
  ) {
    return {
      skillId: "document_summary",
      confidence: 0.9,
      reason: "User asked to summarize extracted document content.",
    };
  }

  if (
    /\b(burada ne|bunda ne|ne diyor|ne yazıyor|ne yaziyor|ne var|ne anlatıyor|ne anlatiyor)\b/u.test(normalized)
  ) {
    return {
      skillId: "document_qa",
      confidence: 0.88,
      reason: "User asked a direct content question about the attachment.",
    };
  }

  if (isQuestionPrompt(prompt)) {
    return {
      skillId: "document_qa",
      confidence: 0.82,
      reason: "User asked a question grounded in the attachment.",
    };
  }

  return null;
}

function isResearchDocumentPrompt(prompt: string): boolean {
  const normalized = normalize(prompt);
  if (!normalized) return false;

  const asksForArtifact =
    /\b(pdf|rapor|report|belge|doküman|dokuman|document|docx)\b/u.test(
      normalized,
    );
  const explicitlyRequestsPublicResearch =
    /(?<!\p{L})(araştır\p{L}*|arastir\p{L}*|research\p{L}*|kaynaklı|kaynakli|source backed|internetten|internet|webden|web|online)(?!\p{L})/u.test(
      normalized,
    );
  const explicitlyRequestsWeb =
    /\b(internetten|internet|webden|web|online|public web|açık web|acik web)\b/u.test(
      normalized,
    );
  const targetsInlineOrPrivateText =
    /\b(aşağıdaki|asagidaki|şu metni|su metni|bu metni|verdiğim metni|verdigim metni|sözleşmeyi|sozlesmeyi|sözleşme metnini|sozlesme metnini|içeriği incele|icerigi incele)\b/u.test(
      normalized,
    );
  const rejectsResearch =
    /\b(araştırmadan|arastirmadan|araştırma yapma|arastirma yapma|do not research|without researching)\b/u.test(
      normalized,
    );
  return (
    asksForArtifact &&
    explicitlyRequestsPublicResearch &&
    !rejectsResearch &&
    (!targetsInlineOrPrivateText || explicitlyRequestsWeb)
  );
}

export async function routeSkill(input: {
  prompt: string;
  attachmentContext?: ResolvedAttachmentContext | null;
  skills: SkillSummary[];
  skillHint?: string | null;
  desiredOutputKinds?: readonly string[];
  classify?: (input: {
    prompt: string;
    attachmentContext: ResolvedAttachmentContext;
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

  if (
    (!context?.used || context.chunks.length === 0) &&
    activeSkillIds.has("research_document") &&
    input.skills.some(
      (skill) =>
        skill.id === "research_document" &&
        canProduceRequestedOutput(skill, input.desiredOutputKinds),
    ) &&
    isResearchDocumentPrompt(input.prompt)
  ) {
    return {
      needsSkill: true,
      skillId: "research_document",
      confidence: 0.94,
      reason:
        "User requested a source-grounded research artifact that does not require an attachment.",
      source: "deterministic",
    };
  }

  if (!context?.used || context.chunks.length === 0) {
    return {
      needsSkill: false,
      skillId: null,
      confidence: 0,
      reason: "No usable attachment context is available.",
      source: "fallback",
    };
  }

  const attachmentCompatibleSkills = input.skills.filter((skill) =>
    canRouteSkillWithAttachment(context, skill) &&
    canProduceRequestedOutput(skill, input.desiredOutputKinds),
  );
  if (attachmentCompatibleSkills.length === 0) {
    return {
      needsSkill: false,
      skillId: null,
      confidence: 0.9,
      reason: "No active skill produces every explicitly requested output.",
      source: "fallback",
    };
  }
  const attachmentCompatibleSkillIds = new Set(
    attachmentCompatibleSkills.map((skill) => skill.id),
  );

  const imageDoc = context.documents.find((d) => /^image\//i.test(d.mimeType ?? ""));
  const deterministic = deterministicSkillId(input.prompt);
  if (
    deterministic &&
    attachmentCompatibleSkillIds.has(deterministic.skillId) &&
    (!imageDoc || deterministic.skillId !== "document_qa" || isImageTextQuestion(input.prompt))
  ) {
    return {
      needsSkill: true,
      skillId: deterministic.skillId,
      confidence: deterministic.confidence,
      reason: deterministic.reason,
      source: "deterministic",
    };
  }

  // Image attachment → vision_analysis (keyword or short prompt)
  if (imageDoc && activeSkillIds.has("vision_analysis")) {
    const hasVisionKeyword = hasAnyPhrase(input.prompt, [
      "görüş", "gorus", "görsel", "gorsel", "resme bak", "fotografa bak", "fotoğrafa bak",
      "ne görüyorsun", "ne goruyorsun", "analiz et", "incele", "oku", "tarat",
    ]);
    if (hasVisionKeyword || normalize(input.prompt).split(" ").length <= 6) {
      return {
        needsSkill: true,
        skillId: "vision_analysis",
        confidence: 0.85,
        reason: "Image attachment detected with short or vision-oriented prompt.",
        source: "payload_type",
      };
    }
  }

  for (const skill of attachmentCompatibleSkills) {
    if (hasAnyPhrase(input.prompt, skill.triggers.phrases)) {
      return {
        needsSkill: true,
        skillId: skill.id,
        confidence: 0.8,
        reason: `Prompt matched trigger phrase for ${skill.id}.`,
        source: "trigger_phrase",
      };
    }
  }

  const classified = input.classify
    ? await input.classify({
        prompt: input.prompt,
        attachmentContext: context,
        skills: attachmentCompatibleSkills,
      })
    : null;
  // Lower threshold when attachment is present — less risk of wrong skill, high risk of missing.
  const threshold = context.documents.length > 0 ? 0.62 : ROUTE_CONFIDENCE_THRESHOLD;
  if (
    classified?.needsSkill &&
    classified.skillId &&
    attachmentCompatibleSkillIds.has(classified.skillId) &&
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

  const payloadMatch = attachmentCompatibleSkills.find((skill) =>
    hasPayloadType(context, skill),
  );
  if (payloadMatch && isQuestionPrompt(input.prompt)) {
    return {
      needsSkill: true,
      skillId: "document_qa",
      confidence: 0.74,
      reason: "Attachment payload type matched document Q&A and prompt is question-like.",
      source: "payload_type",
    };
  }

  // Short/vague prompt with document attachment → document_qa fallback
  const docMimeTypes = [
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ];
  const docAttachment = context.documents.find((d) => docMimeTypes.includes(d.mimeType ?? ""));
  if (docAttachment && activeSkillIds.has("document_qa") && normalize(input.prompt).split(" ").length <= 4) {
    return {
      needsSkill: true,
      skillId: "document_qa",
      confidence: 0.70,
      reason: "Short vague prompt with document attachment — defaulting to Q&A.",
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
