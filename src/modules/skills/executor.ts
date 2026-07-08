import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";
import { estimateTextTokens } from "../billing/token-metering.js";
import {
  mapSkillModelProfileToWorkload,
  type SelectedSkillChunk,
  type SkillDefinition,
  type SkillExecutionLogInput,
  type SkillExecutionResult,
  type SkillInput,
  type SkillModelCallInput,
  type SkillModelCallResult,
  type SkillRouteDecision,
} from "./types.js";
import {
  parseStrictJsonObject,
  validateSkillInput,
  validateSkillOutput,
} from "./validator.js";

type CacheEntry = {
  result: SkillExecutionResult;
  expiresAt: number;
};

const skillExecutionCache = new Map<string, CacheEntry>();
const APPROX_CHARS_PER_TOKEN = 4;
const MAX_SELECTED_CHUNKS = 8;
const RELEVANCE_STOPWORDS = new Set([
  "bir",
  "bu",
  "bunu",
  "şu",
  "sunu",
  "şunu",
  "ve",
  "ile",
  "için",
  "icin",
  "var",
  "mi",
  "ne",
  "nedir",
  "nasıl",
  "nasil",
  "the",
  "and",
  "for",
  "what",
  "how",
  "this",
  "that",
  "document",
  "file",
]);

function compactText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function normalize(value: unknown): string {
  return compactText(value).toLowerCase();
}

function tokenizeForRelevance(value: unknown): Set<string> {
  return new Set(
    normalize(value)
      .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
      .split(/\s+/)
      .map((token) => token.trim())
      .filter((token) => token.length >= 3 && !RELEVANCE_STOPWORDS.has(token)),
  );
}

function extractPageReferences(prompt: string): Set<number> {
  const refs = new Set<number>();
  for (const match of normalize(prompt).matchAll(/\b(?:sayfa|page|s\.?|p\.?)\s*(\d{1,4})\b/g)) {
    const page = Number(match[1]);
    if (Number.isInteger(page) && page > 0) {
      refs.add(page);
    }
  }
  return refs;
}

function sha256(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function scoreChunk(
  prompt: string,
  chunk: SkillInput["attachmentContext"]["chunks"][number],
  documentSummaryMap: Map<string, string>,
): number {
  const promptTokens = tokenizeForRelevance(prompt);
  const chunkTokens = tokenizeForRelevance([
    chunk.documentTitle,
    chunk.mimeType,
    chunk.pageNumber ? `page ${chunk.pageNumber}` : "",
    chunk.content,
  ].join(" "));
  const normalizedPrompt = normalize(prompt);
  const normalizedContent = normalize(chunk.content);

  let score = 0;

  // Prompt token overlap in content/title/page.
  for (const token of promptTokens) {
    if (chunkTokens.has(token)) {
      score += 4;
    } else if (normalizedContent.includes(token)) {
      score += 1;
    }
  }

  // Heading/title chunk boost — surface important structural chunks early
  const kind = String(chunk.metadata?.kind ?? chunk.metadata?.type ?? "").toLowerCase();
  if (kind === "heading" || kind === "title" || kind === "header") {
    score += 8;
  }

  // Document title token overlap (additional boost beyond haystack match)
  const titleTokens = tokenizeForRelevance(chunk.documentTitle ?? "");
  for (const token of promptTokens) {
    if (titleTokens.has(token)) {
      score += 2;
    }
  }

  // Document summary relevance boost
  const docSummaryTokens = tokenizeForRelevance(documentSummaryMap.get(chunk.documentId) ?? "");
  if (docSummaryTokens.size > 0) {
    for (const token of promptTokens) {
      if (docSummaryTokens.has(token)) {
        score += 1;
      }
    }
  }

  const pageReferences = extractPageReferences(prompt);
  if (chunk.pageNumber && pageReferences.has(chunk.pageNumber)) {
    score += 12;
  }

  const mimeType = String(chunk.mimeType ?? "");
  if (/\b(görsel|gorsel|resim|fotoğraf|fotograf|image|photo)\b/i.test(normalizedPrompt) && mimeType.startsWith("image/")) {
    score += 8;
  }
  if (/\b(pdf|belge|doküman|dokuman|document)\b/i.test(normalizedPrompt) && mimeType === "application/pdf") {
    score += 4;
  }

  // First-page bias only as tie-breaker (max +1)
  if (chunk.pageNumber === 1) {
    score += 0.5;
  }

  return score;
}

function buildDocumentSummaryMap(input: SkillInput): Map<string, string> {
  const map = new Map<string, string>();
  for (const doc of input.attachmentContext.documents) {
    if (doc.summary) {
      map.set(doc.documentId, doc.summary);
    }
  }
  return map;
}

function truncateContentToTokenBudget(content: string, maxTokens: number): {
  content: string;
  truncated: boolean;
} {
  const compact = compactText(content);
  if (maxTokens <= 0) {
    return { content: "", truncated: compact.length > 0 };
  }
  if (estimateTextTokens(compact) <= maxTokens) {
    return { content: compact, truncated: false };
  }

  const maxChars = Math.max(120, maxTokens * APPROX_CHARS_PER_TOKEN);
  return {
    content: compact.slice(0, maxChars).trimEnd(),
    truncated: true,
  };
}

function selectChunks(input: SkillInput, skill: SkillDefinition): SelectedSkillChunk[] {
  const selected: SelectedSkillChunk[] = [];
  let usedTokens = Math.max(0, estimateTextTokens(input.prompt));
  const summaryMap = buildDocumentSummaryMap(input);
  const sorted = [...input.attachmentContext.chunks]
    .map((chunk) => ({
      ...chunk,
      score: scoreChunk(input.prompt, chunk, summaryMap),
    }))
    .sort((a, b) => b.score - a.score || (a.pageNumber ?? 9999) - (b.pageNumber ?? 9999));

  for (const chunk of sorted) {
    const remainingTokens = skill.maxInputTokens - usedTokens;
    if (remainingTokens <= 0 && selected.length > 0) {
      continue;
    }

    const bounded = truncateContentToTokenBudget(
      chunk.content,
      selected.length === 0 ? Math.max(1, remainingTokens) : remainingTokens,
    );
    if (!bounded.content) {
      continue;
    }

    const boundedChunk: SelectedSkillChunk = {
      ...chunk,
      content: bounded.content,
      metadata: {
        ...chunk.metadata,
        ...(bounded.truncated ? { skillContextTruncated: true } : {}),
      },
    };

    const chunkTokens = estimateTextTokens(boundedChunk.content);
    selected.push(boundedChunk);
    usedTokens += chunkTokens;
    if (usedTokens >= skill.maxInputTokens || selected.length >= MAX_SELECTED_CHUNKS) {
      break;
    }
  }

  if (selected.length > 0) {
    return selected;
  }

  const fallback = sorted[0];
  if (!fallback) {
    return [];
  }
  const bounded = truncateContentToTokenBudget(fallback.content, Math.max(1, skill.maxInputTokens));
  return bounded.content
    ? [
        {
          ...fallback,
          content: bounded.content,
          metadata: {
            ...fallback.metadata,
            ...(bounded.truncated ? { skillContextTruncated: true } : {}),
          },
        },
      ]
    : [];
}

function buildSkillInputPayload(input: SkillInput, selectedChunks: SelectedSkillChunk[]) {
  return {
    prompt: input.prompt,
    documents: input.attachmentContext.documents.map((document) => ({
      documentId: document.documentId,
      title: document.title,
      mimeType: document.mimeType,
      summary: document.summary,
      source: document.source,
    })),
    chunks: selectedChunks.map((chunk) => ({
      documentId: chunk.documentId,
      documentTitle: chunk.documentTitle,
      mimeType: chunk.mimeType,
      chunkHash: chunk.chunkHash,
      pageNumber: chunk.pageNumber,
      relevanceScore: Number(chunk.score.toFixed(2)),
      text: chunk.content,
      truncated: chunk.metadata?.skillContextTruncated === true,
    })),
  };
}

function detectUnauthorizedToolCalls(output: Record<string, unknown>, skill: SkillDefinition): string[] {
  const allowed = new Set(skill.allowedTools);
  const rawToolCalls = output.toolCalls ?? output.tool_calls ?? output.tools;
  const toolCalls = Array.isArray(rawToolCalls)
    ? rawToolCalls
        .map((item) =>
          typeof item === "string"
            ? item
            : item && typeof item === "object" && !Array.isArray(item)
              ? String((item as Record<string, unknown>).name ?? "")
              : "",
        )
        .map((item) => item.trim())
        .filter(Boolean)
    : [];

  return toolCalls.filter((tool) => !allowed.has(tool));
}

function buildModelPrompt(skill: SkillDefinition, payload: ReturnType<typeof buildSkillInputPayload>): string {
  return [
    `Selected skill: ${skill.id}@${skill.version}`,
    `Purpose: ${skill.purpose}`,
    "Skill instructions:",
    skill.instructions,
    "Output contract: return strict JSON only. Do not include markdown fences or commentary.",
    `Output schema: ${JSON.stringify(skill.outputSchema)}`,
    "Input:",
    JSON.stringify(payload),
  ].join("\n\n");
}

function formatSkillText(skill: SkillDefinition, output: Record<string, unknown>): string {
  if (skill.id === "document_summary") {
    const summary = compactText(output.summary);
    const keyPoints = Array.isArray(output.keyPoints)
      ? output.keyPoints.map(compactText).filter(Boolean)
      : [];
    return [summary, keyPoints.length ? `Öne çıkanlar:\n${keyPoints.map((item) => `- ${item}`).join("\n")}` : ""]
      .filter(Boolean)
      .join("\n\n");
  }

  if (skill.id === "document_key_points") {
    const title = compactText(output.title);
    const keyPoints = Array.isArray(output.keyPoints)
      ? output.keyPoints.map(compactText).filter(Boolean)
      : [];
    const actionItems = Array.isArray(output.actionItems)
      ? output.actionItems.map(compactText).filter(Boolean)
      : [];
    return [
      title,
      keyPoints.length ? `Önemli noktalar:\n${keyPoints.map((item) => `- ${item}`).join("\n")}` : "",
      actionItems.length ? `Aksiyonlar:\n${actionItems.map((item) => `- ${item}`).join("\n")}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  }

  if (skill.id === "vision_analysis") {
    const description = compactText(output.visualDescription);
    const detectedText = compactText(output.detectedText);
    // Model labels arrive as raw classifier slugs ("drinking_glass") — the
    // user-facing list must read as natural language.
    const keyElements = Array.isArray(output.keyElements)
      ? output.keyElements
          .map((item) => compactText(item).replace(/_/g, " "))
          .filter(Boolean)
      : [];
    return [
      description,
      detectedText ? `Tespit edilen metin:\n${detectedText}` : "",
      keyElements.length ? `Öne çıkan öğeler:\n${keyElements.map((item) => `- ${item}`).join("\n")}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  }

  const answer = compactText(output.answer);
  return answer || "Ekten anlamlı bir yanıt üretmek için yeterli veri bulunamadı.";
}

function createCacheKey(input: {
  skill: SkillDefinition;
  inputHash: string;
  selectedChunkHashes: string[];
}) {
  return JSON.stringify({
    skillId: input.skill.id,
    skillVersion: input.skill.version,
    inputHash: input.inputHash,
    selectedChunkHashes: input.selectedChunkHashes,
    modelProfile: input.skill.modelProfile,
  });
}

function validateSkillOutputPolicy(skill: SkillDefinition, output: Record<string, unknown>, formattedText: string): {
  ok: boolean;
  error?: string;
} {
  if (skill.validation.rejectEmptyOutput && !compactText(formattedText)) {
    return { ok: false, error: "empty_skill_output" };
  }

  const confidence = output.confidence;
  if (
    typeof confidence === "number" &&
    Number.isFinite(confidence) &&
    confidence < skill.validation.minConfidence
  ) {
    return { ok: false, error: "low_skill_confidence" };
  }

  return { ok: true };
}

async function recordSkillExecution(app: FastifyInstance, input: SkillExecutionLogInput) {
  await app.db.insert(learningEvents).values({
    userId: input.userId,
    accountId: input.userId,
    taskId: input.taskId ?? null,
    type: "skill_execution",
    key: `${input.skill.id}:${input.finalStatus}`,
    value: JSON.stringify({
      skillId: input.skill.id,
      skillVersion: input.skill.version,
      finalStatus: input.finalStatus,
      validationStatus: input.validationStatus,
      cacheHit: input.cacheHit,
    }),
    confidence: Math.round(input.routeDecision.confidence * 100),
    scope: "user",
    source: "brain_skill",
    privacyLevel: "safe",
    metadata: {
      skillId: input.skill.id,
      skillVersion: input.skill.version,
      inputHash: input.inputHash,
      selectedChunkHashes: input.selectedChunkHashes,
      modelProfile: input.skill.modelProfile,
      provider: input.provider,
      model: input.model,
      latencyMs: input.latencyMs,
      promptTokens: input.promptTokens,
      completionTokens: input.completionTokens,
      totalTokens: input.totalTokens,
      cacheHit: input.cacheHit,
      validationStatus: input.validationStatus,
      toolCalls: input.toolCalls,
      finalStatus: input.finalStatus,
      routeDecision: input.routeDecision,
      errorCode: input.errorCode ?? null,
      manualHintUsed: input.manualHintUsed === true,
    },
  });
}

export async function executeSkill(input: {
  app: FastifyInstance;
  userId: string;
  taskId?: string;
  skill: SkillDefinition;
  skillInput: SkillInput;
  routeDecision: SkillRouteDecision;
  modelCall: (input: SkillModelCallInput) => Promise<SkillModelCallResult>;
}): Promise<SkillExecutionResult | null> {
  const workload = mapSkillModelProfileToWorkload(input.skill.modelProfile);
  if (!workload) {
    return null;
  }

  const selectedChunks = selectChunks(input.skillInput, input.skill);
  const payload = buildSkillInputPayload(input.skillInput, selectedChunks);
  const selectedChunkHashes = selectedChunks.map((chunk) => chunk.chunkHash);
  const inputHash = sha256({
    prompt: input.skillInput.prompt,
    documents: payload.documents.map((document) => ({
      documentId: document.documentId,
      title: document.title,
      mimeType: document.mimeType,
    })),
    selectedChunkHashes,
  });

  const inputValidation = validateSkillInput(input.skill, payload);
  if (!inputValidation.ok) {
    await recordSkillExecution(input.app, {
      userId: input.userId,
      taskId: input.taskId,
      routeDecision: input.routeDecision,
      skill: input.skill,
      inputHash,
      selectedChunkHashes,
      provider: null,
      model: null,
      latencyMs: 0,
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
      cacheHit: false,
      validationStatus: "failed",
      toolCalls: [],
      finalStatus: "fallback",
      errorCode: "invalid_skill_input",
      manualHintUsed: input.routeDecision.source === "manual_hint",
    });
    return null;
  }

  const cacheKey = createCacheKey({
    skill: input.skill,
    inputHash,
    selectedChunkHashes,
  });
  const cached = input.skill.cachePolicy.enabled ? skillExecutionCache.get(cacheKey) : null;
  if (cached && cached.expiresAt > Date.now()) {
    await recordSkillExecution(input.app, {
      userId: input.userId,
      taskId: input.taskId,
      routeDecision: input.routeDecision,
      skill: input.skill,
      inputHash,
      selectedChunkHashes,
      provider: cached.result.provider,
      model: cached.result.model,
      latencyMs: 0,
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
      cacheHit: true,
      validationStatus: cached.result.metadata.validationStatus,
      toolCalls: cached.result.metadata.toolCalls,
      finalStatus: "success",
      manualHintUsed: input.routeDecision.source === "manual_hint",
    });
    return {
      ...cached.result,
      metadata: {
        ...cached.result.metadata,
        cacheHit: true,
        manualHintUsed: input.routeDecision.source === "manual_hint",
        skillRouteSource: input.routeDecision.source,
        skillDisplay: {
          ...cached.result.metadata.skillDisplay,
          source: input.routeDecision.source,
        },
      },
    };
  }

  const startedAt = Date.now();
  let modelResult = await input.modelCall({
    prompt: buildModelPrompt(input.skill, payload),
    workload,
    maxOutputTokens: input.skill.maxOutputTokens,
    timeoutMs: input.skill.timeoutMs,
    metadata: {
      skillExecution: {
        skillId: input.skill.id,
        skillVersion: input.skill.version,
        inputHash,
        selectedChunkHashes,
        modelProfile: input.skill.modelProfile,
        cacheHit: false,
        manualHintUsed: input.routeDecision.source === "manual_hint",
      },
    },
  });

  let parsed = input.skill.validation.requireJson
    ? parseStrictJsonObject(modelResult.text)
    : parseStrictJsonObject(modelResult.text);
  let validationStatus: SkillExecutionResult["metadata"]["validationStatus"] = "valid";
  let outputValidation = parsed ? validateSkillOutput(input.skill, parsed) : { ok: false, error: "invalid_json" };

  if (parsed) {
    const unauthorizedToolCalls = detectUnauthorizedToolCalls(parsed, input.skill);
    if (unauthorizedToolCalls.length > 0) {
      await recordSkillExecution(input.app, {
        userId: input.userId,
        taskId: input.taskId,
        routeDecision: input.routeDecision,
        skill: input.skill,
        inputHash,
        selectedChunkHashes,
        provider: modelResult.provider,
        model: modelResult.model,
        latencyMs: Date.now() - startedAt,
        promptTokens: modelResult.promptTokens,
        completionTokens: modelResult.completionTokens,
        totalTokens: modelResult.totalTokens,
        cacheHit: false,
        validationStatus: "failed",
        toolCalls: unauthorizedToolCalls,
        finalStatus: "error",
        errorCode: "unauthorized_tool_call",
        manualHintUsed: input.routeDecision.source === "manual_hint",
      });
      return null;
    }
  }

  if ((!parsed || !outputValidation.ok) && input.skill.validation.repairAttempts > 0) {
    validationStatus = "repaired";
    modelResult = await input.modelCall({
      prompt: [
        "Repair this model output into strict JSON that matches the schema.",
        "Do not add commentary. Return only JSON.",
        `Schema: ${JSON.stringify(input.skill.outputSchema)}`,
        `Invalid output: ${modelResult.text.slice(0, 4000)}`,
      ].join("\n\n"),
      workload,
      maxOutputTokens: input.skill.maxOutputTokens,
      timeoutMs: input.skill.timeoutMs,
      metadata: {
        skillExecution: {
          skillId: input.skill.id,
          skillVersion: input.skill.version,
          inputHash,
          selectedChunkHashes,
          modelProfile: input.skill.modelProfile,
          repairAttempt: true,
          cacheHit: false,
          manualHintUsed: input.routeDecision.source === "manual_hint",
        },
      },
    });
    parsed = input.skill.validation.requireJson
      ? parseStrictJsonObject(modelResult.text)
      : parseStrictJsonObject(modelResult.text);
    outputValidation = parsed ? validateSkillOutput(input.skill, parsed) : { ok: false, error: "invalid_json" };
  }

  if (!parsed || !outputValidation.ok) {
    await recordSkillExecution(input.app, {
      userId: input.userId,
      taskId: input.taskId,
      routeDecision: input.routeDecision,
      skill: input.skill,
      inputHash,
      selectedChunkHashes,
      provider: modelResult.provider,
      model: modelResult.model,
      latencyMs: Date.now() - startedAt,
      promptTokens: modelResult.promptTokens,
      completionTokens: modelResult.completionTokens,
      totalTokens: modelResult.totalTokens,
      cacheHit: false,
      validationStatus: "failed",
      toolCalls: [],
      finalStatus: "fallback",
      errorCode: outputValidation.error ?? "invalid_skill_output",
      manualHintUsed: input.routeDecision.source === "manual_hint",
    });
    return null;
  }

  const unauthorizedToolCalls = detectUnauthorizedToolCalls(parsed, input.skill);
  if (unauthorizedToolCalls.length > 0) {
    await recordSkillExecution(input.app, {
      userId: input.userId,
      taskId: input.taskId,
      routeDecision: input.routeDecision,
      skill: input.skill,
      inputHash,
      selectedChunkHashes,
      provider: modelResult.provider,
      model: modelResult.model,
      latencyMs: Date.now() - startedAt,
      promptTokens: modelResult.promptTokens,
      completionTokens: modelResult.completionTokens,
      totalTokens: modelResult.totalTokens,
      cacheHit: false,
      validationStatus: "failed",
      toolCalls: unauthorizedToolCalls,
      finalStatus: "error",
      errorCode: "unauthorized_tool_call",
      manualHintUsed: input.routeDecision.source === "manual_hint",
    });
    return null;
  }

  const formattedText = formatSkillText(input.skill, parsed);
  const outputPolicy = validateSkillOutputPolicy(input.skill, parsed, formattedText);
  if (!outputPolicy.ok) {
    await recordSkillExecution(input.app, {
      userId: input.userId,
      taskId: input.taskId,
      routeDecision: input.routeDecision,
      skill: input.skill,
      inputHash,
      selectedChunkHashes,
      provider: modelResult.provider,
      model: modelResult.model,
      latencyMs: Date.now() - startedAt,
      promptTokens: modelResult.promptTokens,
      completionTokens: modelResult.completionTokens,
      totalTokens: modelResult.totalTokens,
      cacheHit: false,
      validationStatus: "failed",
      toolCalls: [],
      finalStatus: "fallback",
      errorCode: outputPolicy.error,
      manualHintUsed: input.routeDecision.source === "manual_hint",
    });
    return null;
  }

  const result: SkillExecutionResult = {
    text: formattedText,
    structuredOutput: parsed,
    provider: modelResult.provider,
    model: modelResult.model,
    latencyMs: modelResult.latencyMs,
    promptTokens: modelResult.promptTokens,
    completionTokens: modelResult.completionTokens,
    totalTokens: modelResult.totalTokens,
    metadata: {
      skillUsed: true,
      skillId: input.skill.id,
      skillVersion: input.skill.version,
      skillConfidence: input.routeDecision.confidence,
      skillRouteSource: input.routeDecision.source,
      selectedChunkHashes,
      modelProfile: input.skill.modelProfile,
      workload,
      validationStatus,
      cacheHit: false,
      toolCalls: [],
      manualHintUsed: input.routeDecision.source === "manual_hint",
      skillDisplay: {
        label: input.skill.displayName,
        source: input.routeDecision.source,
        status: "used",
      },
    },
  };

  if (input.skill.cachePolicy.enabled && input.skill.cachePolicy.ttlMs > 0) {
    skillExecutionCache.set(cacheKey, {
      result,
      expiresAt: Date.now() + input.skill.cachePolicy.ttlMs,
    });
  }

  await recordSkillExecution(input.app, {
    userId: input.userId,
    taskId: input.taskId,
    routeDecision: input.routeDecision,
    skill: input.skill,
    inputHash,
    selectedChunkHashes,
    provider: modelResult.provider,
    model: modelResult.model,
    latencyMs: modelResult.latencyMs,
    promptTokens: modelResult.promptTokens,
    completionTokens: modelResult.completionTokens,
    totalTokens: modelResult.totalTokens,
    cacheHit: false,
    validationStatus,
    toolCalls: [],
    finalStatus: "success",
    manualHintUsed: input.routeDecision.source === "manual_hint",
  });

  return result;
}

export function resetSkillExecutionCacheForTests() {
  skillExecutionCache.clear();
}
