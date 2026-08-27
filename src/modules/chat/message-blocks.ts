import { createHash } from "node:crypto";
import {
  isSampleableExpression,
  sampleFunctionChart,
  sampleSurfaceGrid,
} from "../brain/function-sampler.js";
import {
  defaultChartInteractions,
  downsampleSeries,
  normalizeChartData,
  normalizeSurfacePoints,
  type NormalizedChartSeries,
} from "./chart-data.js";
import {
  elyanAssistantArtifactBlockSchema,
  elyanAssistantBlockSchema,
  elyanAssistantConnectorResultBlockSchema,
  elyanAssistantGoalProgressBlockSchema,
  elyanAssistantPassthroughBlockSchema,
  elyanTaskTraceBlockSchema,
} from "../../contracts/domain.js";
import {
  hydrateLegacyAssistantBlockInput,
  isSourceWidgetBlockType,
  withCanonicalAssistantBlockEnvelope,
} from "./block-envelope.js";
import { containsProtectedElyanDisclosure } from "../../lib/elyan-public-identity.js";
import type {
  ElyanAssistantActionableBlock,
  ElyanAssistantAttachmentAckBlock,
  ElyanAssistantBlock,
  ElyanAssistantChartBlock,
  ElyanAssistantCodeBlock,
  ElyanAssistantConnectorResultBlock,
  ElyanAssistantDocumentBlock,
  ElyanAssistantFileBlock,
  ElyanAssistantBlockGroupBlock,
  ElyanAssistantImageAnalysisBlock,
  ElyanAssistantInfoCardBlock,
  ElyanAssistantMathBlock,
  ElyanAssistantMathSurface3DBlock,
  ElyanAssistantNextStepsBlock,
  ElyanAssistantSecurityDecisionBlock,
  ElyanAssistantStatusBlock,
  ElyanAssistantSvgBlock,
  ElyanAssistantSummaryBlock,
  ElyanAssistantTableBlock,
  ElyanAssistantTextBlock,
  ElyanAssistantWebSearchBlock,
  ElyanTaskTraceBlock,
} from "../../contracts/domain.js";
import { isDispatchWidgetType } from "../../contracts/assistant-block-schemas.js";

export type AssistantTextMessageBlock = ElyanAssistantTextBlock;
export type AssistantMessageBlock = ElyanAssistantBlock;

type BuildAssistantBlocksOptions = {
  streaming?: boolean;
};

type AssistantBlockVisibility = "user_visible" | "assistant_internal_by_default";
type AssistantRenderContract = {
  version: "elyan_blocks.v2";
  mode: "block_first";
  canonicalSurface: "blocks";
  legacyContent: "none";
  hasVisibleBlocks: boolean;
  visibleBlockTypes: string[];
  textIsBlockWrapped: boolean;
};

export type AssistantBlockContractValidationMode = "compose" | "normalize";

export type AssistantBlockContractValidationResult = {
  version: "elyan_blocks.v2";
  blocks: AssistantMessageBlock[];
  renderContract: AssistantRenderContract;
  blockQuality: AssistantBlockQualityReport;
  modelFeedbackSignals: string[];
};

export type AssistantBlockQualityIssue =
  | "duplicate_block"
  | "schema_invalid_block"
  | "malformed_structured_json"
  | "raw_json_leak_prevented"
  | "fallback_to_text"
  | "unrequested_table_block"
  | "content_block_overlap"
  | "document_preflight_enriched"
  | "semantic_validation_failed";

export type AssistantBlockQualityReport = {
  version: "elyan_block_quality.v1";
  score: number;
  issues: AssistantBlockQualityIssue[];
  feedbackSignals: string[];
  blockTypes: string[];
  sourceAuthority?:
    | "tool_connector"
    | "skill_structured_output"
    | "model_typed_block"
    | "deterministic_prompt"
    | "response_text";
  semanticValidation?: {
    ok: boolean;
    errorCodes: string[];
  };
  metrics: {
    inputBlockCount: number;
    normalizedBlockCount: number;
    duplicateBlockCount: number;
    duplicateTableBlockCount: number;
    schemaInvalidBlockCount: number;
    malformedStructuredJsonCount: number;
    rawJsonLeakPreventedCount: number;
    fallbackToTextCount: number;
    unrequestedTableBlockCount: number;
    contentBlockOverlapCount: number;
    documentPreflightEnrichedCount: number;
  };
};

export function applyAssistantBlockSemanticQuality(
  report: AssistantBlockQualityReport,
  input: {
    sourceAuthority?: AssistantBlockQualityReport["sourceAuthority"];
    validationOk: boolean;
    errorCodes?: string[];
  },
): AssistantBlockQualityReport {
  const errorCodes = [...new Set(input.errorCodes ?? [])].slice(0, 16);
  const failed = !input.validationOk;
  return {
    ...report,
    score: failed ? Math.min(report.score, 25) : report.score,
    issues: failed
      ? [...new Set([...report.issues, "semantic_validation_failed" as const])]
      : report.issues,
    feedbackSignals: failed
      ? [...new Set([...report.feedbackSignals, "semantic_validation_failed"])]
      : report.feedbackSignals,
    ...(input.sourceAuthority
      ? { sourceAuthority: input.sourceAuthority }
      : {}),
    semanticValidation: {
      ok: input.validationOk,
      errorCodes,
    },
  };
}

type AssistantBlockCommon = {
  stableBlockId?: string;
  visibility?: AssistantBlockVisibility;
  confidence?: number;
  priority?: number;
  cacheDigest?: string;
  renderHints?: Record<string, unknown>;
};

const fencePattern = /^\s*(```|~~~)/;
const bulletPrefixPattern = /^\s*(?:[-*•]|\d+\.)\s+/;
const hiddenAssistantTagPattern = /<\/?(?:think|analysis)>/i;
const internalAssistantPattern =
  /^(?:analyze user input|analyze constraints|check attachment context|system prompt|developer message|looking at the system prompt|we need to|user says|the user says|the user is|the user wants|the user's prompt|request:|language:|given the attachment context|attachment context(?: shows| provided)?|ocr\/summary text|page \d+ content|summary\/content|detected text|extracted text|visible text|the ocr output|context:|i am elyan|i started answering|prompt continuation|analysis:|reasoning:|plan:|thinking:|intent:|constraint check|check constraints|systeminstructions|system instructions|output format:|data source:|user-? ?language|however,\s*i have access to\b|i have access to\b.*\btools?\b|i should use\b|i will search\b|the tool\b.*\bavailable\b|<think>|<\/think>|<analysis>|<\/analysis>)/i;
// Reasoning-dump preambles that some models write INTO the content channel
// (e.g. "Here's a thinking process:" repeated through the reply). Matched as a
// substring because streaming concat can glue them mid-line
// ("…User- LanguageHere's a thinking process:").
const reasoningDumpPattern =
  /\b(?:here'?s (?:a|the|my)?\s*(?:thinking|thought|analysis|reasoning)(?:\s+process)?|here is (?:a|the|my)?\s*(?:thinking|thought|analysis|reasoning)(?:\s+process)?|thinking process\s*:|thought process\s*:|analyze constraints\s*&\s*system\s*instructions|analyze constraints\s*&\s*systeminstructions|check constraints\s*&\s*policies|düşünme süreci\s*:|let me think through this|step-by-step reasoning\s*:|internal reasoning\s*:|reasoning trace\s*:|akıl yürütme süreci\s*:|akil yurutme sureci\s*:|iç değerlendirme\s*:|ic degerlendirme\s*:)/i;
const finalAnswerPrefixPattern =
  /^(?:final answer|answer|cevap|son cevap)\s*:\s*/i;
const internalConfigurationDisclosurePattern =
  /\b(system prompt|developer message|sistem promptu|geliştirici mesajı|hidden instruction|gizli talimat|internal routing|backend policy|routeDecision|selectedWorkload|token budget)\b/i;
const visibleInternalConfigurationTerms = [
  [/\bsystem prompt\b/gi, "iç talimat"],
  [/\bdeveloper message\b/gi, "geliştirici talimatı"],
  [/\bsistem promptu\b/gi, "iç talimat"],
  [/\bgeliştirici mesajı\b/gi, "geliştirici talimatı"],
  [/\bhidden instruction\b/gi, "gizli olmayan çalışma talimatı"],
  [/\bgizli talimat\b/gi, "çalışma talimatı"],
  [/\binternal routing\b/gi, "yönlendirme"],
  [/\bbackend policy\b/gi, "çalışma politikası"],
  [/\bStructured operating data\b/gi, "çalışma verisi"],
  [/\bData understanding and quality protocol\b/gi, "veri kalite protokolü"],
  [/\bconstitution\.rules\b/gi, "güvenlik kuralları"],
] as const;

type VisibleTextSanitizerOptions = {
  fallback?: string | null | undefined;
  allowPublicProviderReferences?: boolean;
};
const analysisValueLabelPatterns = [
  /^ocr\/summary text\s*:/i,
  /^page \d+ content\s*:/i,
  /^summary\/content\s*:/i,
  /^detected text\s*:/i,
  /^extracted text\s*:/i,
  /^visible text\s*:/i,
] as const;
const genericLabeledLinePattern =
  /^[A-Za-zÇĞİÖŞÜçğıöşü][A-Za-zÇĞİÖŞÜçğıöşü0-9 /_()-]{0,40}:\s*/;

function normalizeTextValue(value: unknown, maxLength = 400): string | null {
  const normalized = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) {
    return null;
  }
  return normalized.length <= maxLength
    ? normalized
    : `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function normalizeStringList(
  value: unknown,
  options: { min?: number; max?: number; itemMaxLength?: number } = {},
): string[] {
  const min = options.min ?? 0;
  const max = options.max ?? 8;
  const itemMaxLength = options.itemMaxLength ?? 240;
  const items = Array.isArray(value)
    ? value
        .map((item) => normalizeTextValue(item, itemMaxLength))
        .filter((item): item is string => Boolean(item))
        .slice(0, max)
    : [];
  return items.length >= min ? items : [];
}

function normalizeVisibility(value: unknown): AssistantBlockVisibility | undefined {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (
    normalized === "user_visible" ||
    normalized === "assistant_internal_by_default"
  ) {
    return normalized;
  }
  return undefined;
}

function normalizeConfidence(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1
    ? value
    : undefined;
}

function normalizePriority(value: unknown): number | undefined {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 3
    ? value
    : undefined;
}

const internalRenderHintKeyPattern =
  /(?:^|[_-])(?:analysis|reasoning|debug|trace|tool|metadata|prompt|system|developer|secret|token|password|credential|raw|internal)(?:$|[_-])/i;

function normalizeBlockStableId(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const normalized = value.trim().replace(/[^\w:.-]+/g, "_").slice(0, 96);
  return normalized.length >= 3 ? normalized : undefined;
}

function normalizeBlockCacheDigest(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  return /^[a-f0-9]{8,64}$/.test(normalized) ? normalized : undefined;
}

function normalizeRenderHintValue(value: unknown, depth: number): unknown {
  if (value === null || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : undefined;
  }
  if (typeof value === "string") {
    const normalized = normalizeTextValue(value, 160);
    return normalized ?? undefined;
  }
  if (Array.isArray(value)) {
    if (depth >= 2) {
      return undefined;
    }
    const items = value
      .slice(0, 8)
      .map((item) => normalizeRenderHintValue(item, depth + 1))
      .filter((item) => item !== undefined);
    return items.length > 0 ? items : undefined;
  }
  if (!value || typeof value !== "object" || depth >= 2) {
    return undefined;
  }
  const output: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>).slice(0, 16)) {
    const normalizedKey = key.trim().replace(/[^\w.-]+/g, "_").slice(0, 48);
    const policyKey = normalizedKey.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase();
    if (!normalizedKey || internalRenderHintKeyPattern.test(policyKey)) {
      continue;
    }
    const normalizedValue = normalizeRenderHintValue(raw, depth + 1);
    if (normalizedValue !== undefined) {
      output[normalizedKey] = normalizedValue;
    }
  }
  return Object.keys(output).length > 0 ? output : undefined;
}

function normalizeRenderHints(value: unknown): Record<string, unknown> | undefined {
  const normalized = normalizeRenderHintValue(value, 0);
  return normalized && typeof normalized === "object" && !Array.isArray(normalized)
    ? normalized as Record<string, unknown>
    : undefined;
}

function mergeRenderHints(
  base: Record<string, unknown>,
  next: unknown,
): Record<string, unknown> {
  return {
    ...base,
    ...(normalizeRenderHints(next) ?? {}),
  };
}

function normalizeStringArray(
  value: unknown,
  allowed: readonly string[],
  max: number,
): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set<string>();
  const output: string[] = [];
  for (const item of value) {
    const normalized = typeof item === "string" ? item.trim().toLowerCase() : "";
    if (!normalized || !allowed.includes(normalized) || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    output.push(normalized);
    if (output.length >= max) {
      break;
    }
  }
  return output;
}

function normalizeDigestPayload(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(normalizeDigestPayload);
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  const record = value as Record<string, unknown>;
  return Object.keys(record)
    .sort()
    .reduce<Record<string, unknown>>((accumulator, key) => {
      accumulator[key] = normalizeDigestPayload(record[key]);
      return accumulator;
    }, {});
}

function buildCacheDigest(block: Record<string, unknown>) {
  return createHash("sha256")
    .update(JSON.stringify(normalizeDigestPayload(block)))
    .digest("hex")
    .slice(0, 16);
}

function withAssistantBlockDefaults<T extends Record<string, unknown>>(
  type: string,
  payload: T,
  options: AssistantBlockCommon = {},
): T & Required<Pick<AssistantBlockCommon, "stableBlockId" | "visibility" | "cacheDigest">> & AssistantBlockCommon {
  const visibility = options.visibility ?? "user_visible";
  const renderHints = normalizeRenderHints(options.renderHints) ?? { sectionRole: type };
  const withMeta = {
    ...payload,
    renderHints,
    ...(options.confidence != null ? { confidence: options.confidence } : {}),
    ...(options.priority != null ? { priority: options.priority } : {}),
    visibility,
  };
  const cacheDigest = normalizeBlockCacheDigest(options.cacheDigest) ?? buildCacheDigest({ type, ...withMeta });
  const sectionRole = normalizeBlockStableId(renderHints.sectionRole);
  const singletonSlot =
    sectionRole &&
    !["artifact", "block_group", "chart", "file", "table"].includes(type)
      ? `elyan:${type}:${sectionRole}`
      : null;
  const stableBlockId =
    normalizeBlockStableId(options.stableBlockId) ??
    singletonSlot ??
    `${type}_${cacheDigest}`;
  return {
    ...withMeta,
    stableBlockId,
    cacheDigest,
  };
}

function shouldRedactProtectedElyanDisclosure(
  value: string,
  _options: Pick<VisibleTextSanitizerOptions, "allowPublicProviderReferences"> = {},
) {
  if (!containsProtectedElyanDisclosure(value)) {
    return false;
  }
  return internalConfigurationDisclosurePattern.test(value);
}

function redactVisibleInternalConfigurationTerms(value: string): string {
  return visibleInternalConfigurationTerms.reduce(
    (current, [pattern, replacement]) => current.replace(pattern, replacement),
    value,
  );
}

function sanitizeVisibleCandidate(
  value: string,
  _options: Pick<VisibleTextSanitizerOptions, "allowPublicProviderReferences"> = {},
): string {
  const redactedTerms = redactVisibleInternalConfigurationTerms(value).trim();
  return redactedTerms;
}

function normalizeMarkdown(value: string | null | undefined) {
  return String(value ?? "")
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\r\n?/g, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .trim();
}

function stripFenceWrapper(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.startsWith("```") || !trimmed.endsWith("```")) {
    return trimmed;
  }

  const lines = trimmed.split("\n");
  if (lines.length < 3) {
    return trimmed;
  }
  return lines.slice(1, -1).join("\n").trim();
}

function tryParseJsonRecord(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return parsed as Record<string, unknown>;
  } catch {
    return null;
  }
}

function isInternalToolOrDebugRecord(record: Record<string, unknown>): boolean {
  const lowerKeys = new Set(Object.keys(record).map((key) => key.toLowerCase()));
  if (
    typeof record.tool === "string" &&
    (lowerKeys.has("arguments") || lowerKeys.has("args")) &&
    /^(?:gmail|calendar|drive|memory|web|goals|connector|mcp)\./i.test(record.tool)
  ) {
    return true;
  }
  return (
    Array.isArray(record.tool_requests) ||
    Array.isArray(record.toolRequests) ||
    lowerKeys.has("reasoning") ||
    lowerKeys.has("analysis") ||
    lowerKeys.has("tool_trace") ||
    lowerKeys.has("tooltrace") ||
    lowerKeys.has("route_decision") ||
    lowerKeys.has("routedecision") ||
    lowerKeys.has("system_prompt") ||
    lowerKeys.has("systemprompt")
  );
}

function isInternalToolOrDebugFence(value: string): boolean {
  const trimmed = value.trim();
  if (!/^(```|~~~)/.test(trimmed)) {
    return false;
  }
  const inner = stripFenceWrapper(trimmed);
  if (!inner.startsWith("{")) {
    return false;
  }
  const parsed = tryParseJsonRecord(inner);
  return parsed ? isInternalToolOrDebugRecord(parsed) : false;
}

function readStructuredVisibleText(record: Record<string, unknown>): string | null {
  const textCandidateKeys = ["final", "finalAnswer", "final_answer", "answer", "content", "message", "text"];
  for (const key of textCandidateKeys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  const rawBlocks = Array.isArray(record.blocks) ? record.blocks : [];
  const textBlocks = rawBlocks
    .map((block) => {
      if (!block || typeof block !== "object" || Array.isArray(block)) {
        return null;
      }
      const entry = block as Record<string, unknown>;
      const type = String(entry.type ?? "").trim().toLowerCase();
      if (type && type !== "text") {
        return null;
      }
      const value =
        typeof entry.markdown === "string"
          ? entry.markdown
          : typeof entry.text === "string"
            ? entry.text
            : typeof entry.content === "string"
              ? entry.content
              : typeof entry.body === "string"
                ? entry.body
                : typeof entry.message === "string"
                  ? entry.message
                  : "";
      return value.trim() ? value.trim() : null;
    })
    .filter((value): value is string => Boolean(value));
  if (textBlocks.length > 0) {
    return textBlocks.join("\n\n");
  }

  return null;
}

function tryParseStructuredVisibleText(value: string): string | null {
  const candidate = stripFenceWrapper(value);
  if (!candidate.startsWith("{")) {
    return null;
  }

  if (candidate.endsWith("}")) {
    try {
      const parsed = JSON.parse(candidate) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        return null;
      }
      return readStructuredVisibleText(parsed as Record<string, unknown>);
    } catch {
      // Fall through to tolerant envelope recovery below.
    }
  }

  return recoverTextFromStructuredEnvelope(candidate);
}

function recoverTextFromStructuredEnvelope(candidate: string): string | null {
  const compact = candidate.replace(/\s+/g, "");
  if (!candidate.trimStart().startsWith("{") || !compact.includes('"type":"text"')) {
    return null;
  }
  const keyMatch = /"(?:markdown|text|content|body|message)"\s*:\s*"/i.exec(candidate);
  if (!keyMatch) {
    return null;
  }
  let cursor = keyMatch.index + keyMatch[0].length;
  let escaped = false;
  let value = "";
  for (; cursor < candidate.length; cursor += 1) {
    const char = candidate[cursor] ?? "";
    if (escaped) {
      value += `\\${char}`;
      escaped = false;
      continue;
    }
    if (char === "\\") {
      escaped = true;
      continue;
    }
    if (char === '"') {
      break;
    }
    value += char;
  }
  const repaired = value
    .replace(/\\n/g, "\n")
    .replace(/\\r/g, "\r")
    .replace(/\\t/g, "\t")
    .replace(/\\"/g, '"')
    .replace(/\\\\/g, "\\");
  return normalizeMarkdown(repaired);
}

function stripBulletPrefix(value: string) {
  return value.replace(bulletPrefixPattern, "");
}

function cleanInlineLabelValue(value: string) {
  return normalizeMarkdown(value)
    .replace(/^["'“”‘’]+/, "")
    .replace(/["'“”‘’]+$/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function isAnalysisValueLabel(value: string) {
  return analysisValueLabelPatterns.some((pattern) => pattern.test(value));
}

function stripInlineMarkers(value: string) {
  // "2. **Check Constraints & Policies:**" → "check constraints & policies:"
  return value.replace(/^[#>*_`~\s]+/, "").replace(/\*\*|__|`/g, "");
}

function looksLikeInternalAssistantLine(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }
  if (reasoningDumpPattern.test(trimmed)) {
    return true;
  }
  const lowered = stripInlineMarkers(
    stripBulletPrefix(trimmed),
  ).toLowerCase();
  return (
    internalAssistantPattern.test(lowered) ||
    lowered.includes("system prompt") ||
    lowered.includes("developer message") ||
    lowered.includes("looking at the system prompt") ||
    lowered.includes("analyze user input") ||
    lowered.includes("user says") ||
    lowered.includes("the user says") ||
    lowered.includes("given the attachment context") ||
    lowered.includes("prompt continuation") ||
    lowered.includes("i started answering")
  );
}

function stripInlineInternalAssistantTail(value: string): string {
  const markerIndex = value.search(reasoningDumpPattern);
  if (markerIndex <= 0) {
    return value;
  }
  return value.slice(0, markerIndex).replace(/[-–—:;,\s]+$/u, "").trimEnd();
}

function containsInternalAssistantSignals(value: string) {
  return value
    .split("\n")
    .some((line) => looksLikeInternalAssistantLine(line));
}

function collapseDuplicatedConversationalRestart(value: string): string {
  const normalized = normalizeMarkdown(value);
  if (!normalized) {
    return "";
  }
  const openingMatch = normalized.match(/^\s*(Merhaba|Selam|Hey|Hello|Hi)\b/iu);
  if (!openingMatch) {
    return normalized;
  }
  const duplicateOpening = /([.!?…])\s*(Merhaba|Selam|Hey|Hello|Hi)\b/giu;
  const first = duplicateOpening.exec(normalized);
  if (!first || typeof first.index !== "number") {
    return normalized;
  }
  const duplicateIndex = first.index + first[1]!.length;
  const head = normalized.slice(0, duplicateIndex).trim();
  return head || normalized;
}

/**
 * When the model wraps its entire answer inside a hidden `<think>` /
 * `<analysis>` section (or never closes one), the paragraph loop strips
 * everything and the sanitizer would otherwise fall through to the terminal
 * "Yanıtı temiz biçimde oluşturamadım" fallback.
 *
 * This recovers the section body, drops the lines that read as reasoning meta
 * (`internalAssistantPattern`, `analysis-value labels`, nested hidden tags),
 * and returns whatever is left. In practice that IS the answer the model
 * intended to give — just misfiled inside a reasoning wrapper.
 */
function extractHiddenSectionAnswerFallback(source: string): string | null {
  const captures: string[] = [];

  const openPattern = /<\s*(think|analysis)\s*>/gi;
  let match: RegExpExecArray | null;
  while ((match = openPattern.exec(source))) {
    const start = match.index + match[0].length;
    const closePattern = new RegExp(`<\\s*/\\s*${match[1]}\\s*>`, "i");
    closePattern.lastIndex = start;
    const closeInRest = source.slice(start).search(closePattern);
    const end = closeInRest === -1 ? source.length : start + closeInRest;
    const body = source.slice(start, end).trim();
    if (body) {
      captures.push(body);
    }
  }

  if (captures.length === 0) {
    return null;
  }

  const cleanedParagraphs: string[] = [];
  for (const body of captures) {
    for (const paragraph of body.split(/\n{2,}/)) {
      const trimmedParagraph = paragraph.trim();
      if (!trimmedParagraph) {
        continue;
      }
      const cleanedLines: string[] = [];
      for (const rawLine of trimmedParagraph.split("\n")) {
        const line = rawLine.trim();
        if (!line) {
          if (
            cleanedLines.length > 0 &&
            cleanedLines[cleanedLines.length - 1] !== ""
          ) {
            cleanedLines.push("");
          }
          continue;
        }
        if (hiddenAssistantTagPattern.test(line)) {
          continue;
        }
        if (looksLikeInternalAssistantLine(line)) {
          continue;
        }
        if (isAnalysisValueLabel(line)) {
          continue;
        }
        cleanedLines.push(
          line.replace(finalAnswerPrefixPattern, "").trimStart(),
        );
      }
      const cleaned = cleanedLines.join("\n").trim();
      if (cleaned) {
        cleanedParagraphs.push(cleaned);
      }
    }
  }

  const joined = cleanedParagraphs.join("\n\n").trim();
  return joined || null;
}

function extractAnalysisValueFallback(source: string): string | null {
  const lines = source.split("\n");
  for (let index = 0; index < lines.length; index += 1) {
    const current = stripBulletPrefix(lines[index]!.trim());
    if (!current || !isAnalysisValueLabel(current)) {
      continue;
    }

    const parts: string[] = [];
    const inlineValue = cleanInlineLabelValue(current.replace(/^[^:]+:\s*/, ""));
    if (inlineValue) {
      parts.push(inlineValue);
    }

    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const next = stripBulletPrefix(lines[cursor]!.trim());
      if (!next) {
        if (parts.length > 0) {
          break;
        }
        continue;
      }
      if (
        looksLikeInternalAssistantLine(next) ||
        isAnalysisValueLabel(next) ||
        hiddenAssistantTagPattern.test(next) ||
        genericLabeledLinePattern.test(next)
      ) {
        break;
      }
      parts.push(next);
    }

    const cleaned = cleanInlineLabelValue(parts.join(" "));
    if (cleaned) {
      return cleaned;
    }
  }

  return null;
}

export function sanitizeAssistantVisibleText(
  value: string | null | undefined,
  options: VisibleTextSanitizerOptions = {},
) {
  const normalized = normalizeMarkdown(value);
  if (!normalized) {
    return normalizeMarkdown(options.fallback);
  }

  const structured = tryParseStructuredVisibleText(normalized);
  const source = normalizeMarkdown(structured ?? normalized);
  const retainedParagraphs: string[] = [];
  let insideHiddenAssistantSection = false;

  for (const paragraph of source.split(/\n{2,}/)) {
    const trimmed = paragraph.trim();
    if (!trimmed) {
      continue;
    }
    if (isInternalToolOrDebugFence(trimmed)) {
      continue;
    }
    if (fencePattern.test(trimmed)) {
      retainedParagraphs.push(trimmed);
      continue;
    }

    const cleanedLines: string[] = [];
    for (const rawLine of trimmed.split("\n")) {
      const line = rawLine.trimEnd();
      const lineTrimmed = line.trim();
      const loweredLine = lineTrimmed.toLowerCase();
      if (loweredLine.includes("<think>") || loweredLine.includes("<analysis>")) {
        insideHiddenAssistantSection = true;
        continue;
      }
      if (insideHiddenAssistantSection) {
        if (loweredLine.includes("</think>") || loweredLine.includes("</analysis>")) {
          insideHiddenAssistantSection = false;
        }
        continue;
      }
      if (loweredLine.includes("</think>") || loweredLine.includes("</analysis>")) {
        insideHiddenAssistantSection = false;
        continue;
      }
      if (!line.trim()) {
        if (cleanedLines.length > 0 && cleanedLines[cleanedLines.length - 1] !== "") {
          cleanedLines.push("");
        }
        continue;
      }
      const visibleLine = stripInlineInternalAssistantTail(line);
      if (!visibleLine.trim()) {
        continue;
      }
      if (/^\s*(?:[-*•]|\d+[.)-])\s*[*_`#\s]*$/u.test(visibleLine)) {
        continue;
      }
      if (looksLikeInternalAssistantLine(visibleLine)) {
        continue;
      }
      cleanedLines.push(visibleLine.replace(finalAnswerPrefixPattern, "").trimStart());
    }

    const cleaned = cleanedLines.join("\n").trim();
    if (cleaned) {
      retainedParagraphs.push(cleaned);
    }
  }

  const sanitized = retainedParagraphs.join("\n\n").trim();
  if (sanitized) {
    return sanitizeVisibleCandidate(sanitized, options);
  }

  // Recovery pass: if the paragraph loop stripped everything because the model
  // stuffed the answer inside `<think>` / `<analysis>` (or left the tag
  // unclosed), pull the section body back out and treat what survives after
  // reasoning-meta removal as the real answer. Without this, honest answers
  // wrapped in a reasoning frame collapse to the "Yanıtı temiz biçimde
  // oluşturamadım" fallback and the user sees a stub instead of the response.
  const hiddenSectionAnswer = extractHiddenSectionAnswerFallback(source);
  if (hiddenSectionAnswer) {
    return sanitizeVisibleCandidate(hiddenSectionAnswer, options);
  }

  const analysisFallback = extractAnalysisValueFallback(source);
  if (analysisFallback) {
    return sanitizeVisibleCandidate(analysisFallback, options);
  }

  const normalizedFallback = normalizeMarkdown(options.fallback);
  if (normalizedFallback) {
    return sanitizeVisibleCandidate(normalizedFallback, options);
  }

  if (shouldRedactProtectedElyanDisclosure(source, options)) {
    return redactVisibleInternalConfigurationTerms(source).trim();
  }
  if (containsInternalAssistantSignals(source)) {
    return "";
  }
  return redactVisibleInternalConfigurationTerms(source).trim();
}

export function polishAssistantVisibleText(
  value: string | null | undefined,
  options: Pick<VisibleTextSanitizerOptions, "allowPublicProviderReferences"> = {},
): string {
  const normalized = normalizeMarkdown(value);
  if (!normalized) {
    return "";
  }

  let polished = normalized
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/(?:\n|\A)([-*]|\d+\.)\s*$/gm, "")
    .replace(/(?:^|\n)(Sonuç|Detay|Not):\s*$/gim, "")
    .replace(/[ \t]+$/gm, "")
    .trim();

  const paragraphs = polished
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean);

  if (paragraphs.length > 1) {
    const tail = paragraphs[paragraphs.length - 1] ?? "";
    if (
      tail.length <= 18 &&
      !/[.!?…]$/.test(tail) &&
      !/^[A-Z0-9ÇĞİÖŞÜ][^a-zçğıöşü]*$/u.test(tail) &&
      /\p{L}/u.test(tail)
    ) {
      paragraphs.pop();
      polished = paragraphs.join("\n\n").trim();
    }
  }

  polished = collapseDuplicatedConversationalRestart(polished);

  return sanitizeVisibleCandidate(polished, options);
}

export function buildAssistantSummaryBlock(
  summary: string | null | undefined,
  options: AssistantBlockCommon & { title?: string } = {},
): ElyanAssistantSummaryBlock | null {
  const normalized = normalizeTextValue(summary, 400);
  if (!normalized) {
    return null;
  }
  return {
    type: "summary",
    summary: normalized,
    ...(normalizeTextValue(options.title, 120) ? { title: normalizeTextValue(options.title, 120)! } : {}),
    ...withAssistantBlockDefaults("summary", {}, {
      priority: options.priority ?? 0,
      renderHints: {
        sectionRole: "summary",
        density: "compact",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantStatusBlock(
  input: {
    status: ElyanAssistantStatusBlock["status"];
    title: string;
    detail?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantStatusBlock {
  return {
    type: "status",
    status: input.status,
    title: normalizeTextValue(input.title, 120) ?? "Durum",
    ...(normalizeTextValue(input.detail, 240)
      ? { detail: normalizeTextValue(input.detail, 240)! }
      : {}),
    ...withAssistantBlockDefaults("status", {}, {
      priority: options.priority ?? 0,
      renderHints: {
        sectionRole: "status",
        tone: input.status === "failed" ? "caution" : "neutral",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantNextStepsBlock(
  items: readonly string[],
  options: AssistantBlockCommon & { title?: string } = {},
): ElyanAssistantNextStepsBlock | null {
  const normalizedItems = normalizeStringList(items, {
    min: 1,
    max: 6,
    itemMaxLength: 240,
  });
  if (normalizedItems.length === 0) {
    return null;
  }
  return {
    type: "next_steps",
    items: normalizedItems,
    ...(normalizeTextValue(options.title, 120) ? { title: normalizeTextValue(options.title, 120)! } : {}),
    ...withAssistantBlockDefaults("next_steps", {}, {
      priority: options.priority ?? 2,
      renderHints: {
        sectionRole: "next_steps",
        density: "compact",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantActionableBlock(
  input: {
    kind: ElyanAssistantActionableBlock["kind"];
    title: string;
    detail?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantActionableBlock {
  return {
    type: "actionable",
    kind: input.kind,
    title: normalizeTextValue(input.title, 120) ?? "Aksiyon",
    ...(normalizeTextValue(input.detail, 240)
      ? { detail: normalizeTextValue(input.detail, 240)! }
      : {}),
    ...withAssistantBlockDefaults("actionable", {}, {
      priority: options.priority ?? 2,
      renderHints: {
        sectionRole: "actionable",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantInfoCardBlock(
  input: {
    type: ElyanAssistantInfoCardBlock["type"];
    title: string;
    items: Array<{ label: string; value: string; confidence?: number }>;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantInfoCardBlock | null {
  const items = input.items
    .map((item) => {
      const label = normalizeTextValue(item.label, 120);
      const value = normalizeTextValue(item.value, 240);
      if (!label || !value) {
        return null;
      }
      return {
        label,
        value,
        ...(normalizeConfidence(item.confidence) != null
          ? { confidence: normalizeConfidence(item.confidence) }
          : {}),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item != null)
    .slice(0, 8);
  if (items.length === 0) {
    return null;
  }
  return {
    type: input.type,
    title: normalizeTextValue(input.title, 120) ?? "Bağlam",
    items,
    ...withAssistantBlockDefaults(input.type, {}, {
      priority: options.priority ?? 2,
      renderHints: {
        sectionRole: "context",
        density: "compact",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

function normalizeTableColumns(value: unknown): string[] {
  return Array.isArray(value)
    ? value
        .map((item) => normalizeTextValue(item, 120))
        .filter((item): item is string => Boolean(item))
        .slice(0, 12)
    : [];
}

function normalizeTableRows(value: unknown, columnCount: number): string[][] {
  if (!Array.isArray(value) || columnCount <= 0) {
    return [];
  }

  const rows = value
    .map((row) => {
      const cells = Array.isArray(row)
        ? row
        : row && typeof row === "object" && !Array.isArray(row)
          ? Object.values(row as Record<string, unknown>)
          : [];
      const normalizedCells = cells
        .slice(0, columnCount)
        .map((cell) => normalizeMarkdown(String(cell ?? "")).replace(/\s+/g, " ").trim().slice(0, 240));
      while (normalizedCells.length < columnCount) {
        normalizedCells.push("");
      }
      return normalizedCells;
    })
    .filter((row) => row.some((cell) => cell.trim()))
    .slice(0, 80);

  return rejectBledTableRows(rows, columnCount);
}

/**
 * Drops rows whose cell content clearly bled in from an adjoining paragraph.
 *
 * Real prod incident: model wrote `| 6 | 200İleri Analiz Dersi Örnek Soru |`
 * because the next-paragraph heading had no line break before it. The mobile
 * mirrors this heuristic client-side; enforcing it at the server means broken
 * rows never even leave the backend.
 *
 * Signal: a cell is 3× the column median AND contains 3+ Title Case tokens.
 * If both trigger, the row is discarded before it can reach the widget.
 */
function rejectBledTableRows(rows: string[][], columnCount: number): string[][] {
  if (rows.length < 2 || columnCount <= 0) {
    return rows;
  }
  const medians: number[] = [];
  for (let col = 0; col < columnCount; col += 1) {
    const lengths: number[] = [];
    for (const row of rows) {
      if (col >= row.length) continue;
      const len = row[col].trim().length;
      if (len > 0) lengths.push(len);
    }
    if (lengths.length === 0) {
      medians.push(0);
      continue;
    }
    lengths.sort((a, b) => a - b);
    medians.push(lengths[Math.floor(lengths.length / 2)]);
  }
  const titleTokenPattern = /^[A-ZÇĞİÖŞÜ][a-zçğıöşü]+/;
  return rows.filter((row) => {
    for (let col = 0; col < row.length && col < columnCount; col += 1) {
      const cell = row[col].trim();
      if (cell.length < 20) continue;
      const median = medians[col];
      if (median <= 0) continue;
      if (cell.length < median * 3) continue;
      const tokens = cell.split(/\s+/).filter(Boolean);
      const titleTokens = tokens.filter((t) => titleTokenPattern.test(t)).length;
      if (titleTokens >= 3) {
        return false;
      }
    }
    return true;
  });
}

export function buildAssistantCodeBlock(
  input: {
    code: string;
    language?: string | null;
    filename?: string | null;
    title?: string | null;
    collapsed?: boolean;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantCodeBlock | null {
  const code = normalizeMarkdown(input.code).slice(0, 24_000);
  if (!code) {
    return null;
  }
  return {
    type: "code",
    code: code,
    ...(normalizeTextValue(input.language, 40) ? { language: normalizeTextValue(input.language, 40)! } : {}),
    ...(normalizeTextValue(input.filename, 180) ? { filename: normalizeTextValue(input.filename, 180)! } : {}),
    ...(normalizeTextValue(input.title, 120) ? { title: normalizeTextValue(input.title, 120)! } : {}),
    ...(typeof input.collapsed === "boolean" ? { collapsed: input.collapsed } : {}),
    ...withAssistantBlockDefaults("code", {}, {
      priority: options.priority ?? 1,
      renderHints: {
        sectionRole: "code",
        density: "regular",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantTableBlock(
  input: {
    columns: unknown;
    rows: unknown;
    title?: string | null;
    caption?: string | null;
    summary?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantTableBlock | null {
  const columns = normalizeTableColumns(input.columns);
  const rows = normalizeTableRows(input.rows, columns.length);
  if (columns.length === 0 || rows.length === 0) {
    return null;
  }
  const title = normalizeTextValue(input.title, 120);
  const caption = normalizeTextValue(input.caption, 240);
  const summary = normalizeTextValue(input.summary, 240);
  // Pass the *content* payload to withAssistantBlockDefaults so the
  // cache-digest actually reflects the columns/rows/title. Passing `{}`
  // (as this used to) meant two tables with different rows but the same
  // renderHints hashed to the same digest and one was silently dropped by
  // exact-key dedup — before subset-aware dedup could ever run.
  return {
    type: "table",
    ...withAssistantBlockDefaults(
      "table",
      {
        columns,
        rows,
        ...(title ? { title } : {}),
        ...(summary ? { summary } : {}),
        ...(caption ? { caption } : {}),
        previewRows: rows.slice(0, 20),
        totalRowCount: rows.length,
        density: (rows.length > 12 ? "compact" : "comfortable") as
          | "compact"
          | "comfortable",
        interactions: ["sort", "copy", "share"] as Array<
          "sort" | "copy" | "share"
        >,
      },
      {
        ...options,
        priority: options.priority ?? 1,
        renderHints: mergeRenderHints({
          sectionRole: "data_table",
          renderer: "native_table",
          exportFamily: "spreadsheet",
          exportFormats: ["xlsx", "csv"],
          density: rows.length > 12 ? "compact" : "regular",
          preflightRequired: true,
        }, options.renderHints),
      },
    ),
  };
}

export function buildAssistantChartBlock(
  input: {
    chartType: ElyanAssistantChartBlock["chartType"];
    labels: unknown;
    values: unknown;
    points?: unknown;
    data?: unknown;
    series?: unknown;
    expression?: string | null;
    variables?: unknown;
    range?: unknown;
    fixed?: unknown;
    xLabel?: string | null;
    yLabel?: string | null;
    unit?: string | null;
    theme?: string | null;
    interactions?: unknown;
    renderer?: string | null;
    seriesName?: string | null;
    title?: string | null;
    caption?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantChartBlock | null {
  const chartType = normalizeChartType(input.chartType);
  if (!chartType) {
    return null;
  }
  const expression = normalizeTextValue(input.expression, 2_000);
  const isSurface = chartType === "surface3d" || chartType === "mesh";

  // 1) HER giriş biçimi (labels+values · points · data · series) tek sayısal
  //    gösterime iner. Formül string'i, "yaklaşık 2450" gibi metin ya da
  //    aritmetik ifade y değeri OLAMAZ — o nokta burada düşer.
  let series: NormalizedChartSeries[] | null = normalizeChartData({
    labels: input.labels,
    values: input.values,
    points: input.points,
    data: input.data,
    series: input.series,
    seriesName: input.seriesName,
  });

  // 2) Yüzey: `points:[{x,y,z}]` zaten örneklenmiş olabilir; değilse ifadeyi
  //    sunucuda ızgara üzerinde örnekliyoruz. İstemcinin ifade
  //    değerlendirmesi gerekmesin.
  let surfacePoints = isSurface
    ? (normalizeSurfacePoints(input.points) ?? normalizeSurfacePoints(input.data))
    : null;
  if (isSurface && !surfacePoints && expression) {
    const sampled = sampleSurfaceGrid(expression, input.range);
    if (sampled) {
      surfacePoints = sampled.points;
    }
  }

  // 3) Fonksiyon grafiği: model yalnız `expression` (+ `range`) gönderdiyse
  //    sayısal veri yoktur; sunucuda örnekleyerek gerçek (labels, values) üret
  //    ki grafik her istemcide çizilebilsin ve "veri taşımayan grafik"
  //    düşülmesin.
  if (!series && !isSurface && expression) {
    const sampled = sampleFunctionChart(expression, input.range);
    if (sampled) {
      series = [
        {
          name: normalizeTextValue(input.seriesName, 80) ?? "f(x)",
          labels: sampled.labels,
          values: sampled.values,
        },
      ];
    }
  }

  // Sayısal veriye indirgenemeyen chart bloğu ÇİZİLEMEZ; yayınlanmaz.
  if (!series && !surfacePoints) {
    return null;
  }

  const fullSeries = (series ?? [])
    .filter((entry) => entry.values.length > 0)
    .slice(0, 8);
  // Ekranda çizilen seri 240 noktaya seyreltilir (telefon ekranında zaten
  // piksel başına birden çok nokta düşer, şema sınırı da 240). Tam çözünürlük
  // `data` içinde kalır: artefakt/dışa aktarma boru hattı XLSX/PDF üretirken
  // veriyi kaybetmemeli.
  const boundedSeries = fullSeries.map((entry) => downsampleSeries(entry));
  const primary = boundedSeries[0];
  const fullPrimary = fullSeries[0];
  const fullResolutionData =
    fullPrimary && primary && fullPrimary.values.length > primary.values.length
      ? fullPrimary.labels.map((label, index) => ({
          label,
          value: fullPrimary.values[index],
        }))
      : undefined;
  const variables = normalizeStringList(input.variables, {
    max: 12,
    itemMaxLength: 24,
  });
  const themeRaw = normalizeTextValue(input.theme, 40)?.toLowerCase();
  const theme = (["system", "presentation", "report", "minimal"] as const).includes(
    themeRaw as "system",
  )
    ? (themeRaw as "system" | "presentation" | "report" | "minimal")
    : "minimal";
  // Etkileşim listesi sözleşmenin görünür yüzeyi: istemci bunu okuyup
  // tooltip/zoom/tür-değişimi yüzeylerini açıyor. Model bildirmediyse tür
  // için anlamlı varsayılan HER ZAMAN taşınır (eskiden hiç gönderilmiyordu ve
  // mobil etkileşimleri hiç açmıyordu).
  const declaredInteractions = Array.isArray(input.interactions)
    ? (input.interactions
        .map((value) => String(value ?? "").trim().toLowerCase())
        .filter((value) =>
          [
            "tooltip",
            "trackball",
            "zoom",
            "pan",
            "type_switch",
            "fullscreen",
            "share",
          ].includes(value),
        ) as ElyanAssistantChartBlock["interactions"])
    : undefined;
  const interactions =
    declaredInteractions && declaredInteractions.length > 0
      ? declaredInteractions
      : (defaultChartInteractions(chartType) as NonNullable<
          ElyanAssistantChartBlock["interactions"]
        >);

  return {
    type: "chart",
    chartType,
    ...(primary && primary.labels.length > 0 ? { labels: primary.labels } : {}),
    ...(primary && primary.values.length > 0 ? { values: primary.values } : {}),
    ...(surfacePoints ? { points: surfacePoints } : {}),
    ...(fullResolutionData ? { data: fullResolutionData } : {}),
    ...(boundedSeries.length > 0 ? { series: boundedSeries } : {}),
    ...(expression ? { expression } : {}),
    ...(variables.length > 0 ? { variables } : {}),
    ...(input.range && typeof input.range === "object" && !Array.isArray(input.range) ? { range: input.range as Record<string, unknown> } : {}),
    ...(input.fixed && typeof input.fixed === "object" && !Array.isArray(input.fixed) ? { fixed: input.fixed as Record<string, number> } : {}),
    ...(normalizeTextValue(input.xLabel, 120) ? { xLabel: normalizeTextValue(input.xLabel, 120)! } : {}),
    ...(normalizeTextValue(input.yLabel, 120) ? { yLabel: normalizeTextValue(input.yLabel, 120)! } : {}),
    ...(normalizeTextValue(input.unit, 40) ? { unit: normalizeTextValue(input.unit, 40)! } : {}),
    ...(normalizeTextValue(input.renderer, 40) ? { renderer: normalizeTextValue(input.renderer, 40)! } : {}),
    ...(normalizeTextValue(input.title, 120) ? { title: normalizeTextValue(input.title, 120)! } : {}),
    ...(normalizeTextValue(input.caption, 240) ? { caption: normalizeTextValue(input.caption, 240)! } : {}),
    interactions,
    theme,
    ...withAssistantBlockDefaults("chart", {}, {
      priority: options.priority ?? 2,
      renderHints: {
        sectionRole: "chart",
        density: "regular",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

function normalizeChartType(value: unknown): ElyanAssistantChartBlock["chartType"] | null {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized || normalized === "chart" || normalized === "data_chart") {
    return "bar";
  }
  if (["bar", "column", "bar_chart", "column_chart"].includes(normalized)) return "bar";
  if (["line", "line2d", "line_chart", "spline"].includes(normalized)) return "line";
  if (["pie", "donut", "doughnut"].includes(normalized)) return "pie";
  if (["area", "area_chart"].includes(normalized)) return "area";
  if (["scatter", "scatterplot", "scatter_plot"].includes(normalized)) return "scatter";
  if (["geometry", "plot", "geometric", "geometry_plot"].includes(normalized)) return "geometry";
  if (["function", "function_plot", "curve", "math_function"].includes(normalized)) return "function";
  if (["surface", "surface3d", "3d", "3d_plot", "math_surface_3d", "surface_plot"].includes(normalized)) {
    return "surface3d";
  }
  if (["mesh", "mesh3d", "wireframe"].includes(normalized)) return "mesh";
  if (["heatmap", "heat_map", "matrix", "density"].includes(normalized)) return "heatmap";
  return null;
}

export function buildAssistantMathBlock(
  input: {
    content?: string | null;
    latex?: string | null;
    displayMode?: boolean | null;
    format?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantMathBlock | null {
  const content = normalizeTextValue(input.content ?? input.latex, 8_000);
  if (!content) {
    return null;
  }
  const format = String(input.format ?? "latex").trim().toLowerCase();
  return {
    type: "math",
    content,
    ...(input.latex ? { latex: input.latex } : {}),
    ...(typeof input.displayMode === "boolean" ? { displayMode: input.displayMode } : {}),
    format: format === "tex" || format === "plain" ? format : "latex",
    ...withAssistantBlockDefaults("math", {}, {
      priority: options.priority ?? 2,
      renderHints: {
        sectionRole: "math",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantMathSurface3DBlock(
  input: {
    expression?: string | null;
    title?: string | null;
    variables?: unknown;
    range?: unknown;
    resolution?: unknown;
    zLabel?: string | null;
    colorBy?: string | null;
    mode?: string | null;
    interactive?: unknown;
    renderer?: string | null;
    cacheKey?: string | null;
    caption?: string | null;
    error?: unknown;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantMathSurface3DBlock | null {
  const expression = normalizeTextValue(input.expression, 2_000);
  if (!expression) {
    return null;
  }
  const variables = normalizeStringList(input.variables, {
    min: 2,
    max: 4,
    itemMaxLength: 24,
  }).slice(0, 2);
  const normalizedVariables =
    variables.length === 2 &&
    variables[0]?.toLowerCase() === "x" &&
    variables[1]?.toLowerCase() === "y"
      ? ["x", "y"] as ["x", "y"]
      : undefined;
  const rawRange =
    input.range && typeof input.range === "object" && !Array.isArray(input.range)
      ? (input.range as Record<string, unknown>)
      : null;
  const normalizeAxis = (value: unknown): [number, number] | null => {
    if (!Array.isArray(value) || value.length < 2) return null;
    const [start, end] = value;
    if (
      typeof start !== "number" ||
      !Number.isFinite(start) ||
      typeof end !== "number" ||
      !Number.isFinite(end)
    ) {
      return null;
    }
    return [start, end];
  };
  // Aralık İSTEMCİ tarafında örneklemenin ön koşulu. Model göndermediğinde
  // eskiden alan hiç taşınmıyordu ve istemcinin örnekleyecek bir aralığı
  // olmadığı için yüzey sessizce boş kalıyordu; makul bir varsayılan taşınır.
  const xRange = normalizeAxis(rawRange?.x) ?? ([-5, 5] as [number, number]);
  const yRange = normalizeAxis(rawRange?.y) ?? ([-5, 5] as [number, number]);
  const resolution =
    typeof input.resolution === "number" &&
    Number.isInteger(input.resolution) &&
    input.resolution >= 10 &&
    input.resolution <= 120
      ? input.resolution
      : undefined;
  const colorByRaw = normalizeTextValue(input.colorBy, 40);
  const colorBy =
    colorByRaw === "z" || colorByRaw === "gradientMagnitude" ? colorByRaw : undefined;
  const modeRaw = normalizeTextValue(input.mode, 40);
  const mode = modeRaw === "surface" ? modeRaw : undefined;
  const rendererRaw = normalizeTextValue(input.renderer, 80);
  const renderer = rendererRaw === "plotly_local_webview" ? rendererRaw : undefined;
  const cacheKey = normalizeTextValue(input.cacheKey, 128);
  const rawError =
    input.error && typeof input.error === "object" && !Array.isArray(input.error)
      ? (input.error as Record<string, unknown>)
      : null;
  const declaredError =
    rawError &&
    typeof rawError.code === "string" &&
    typeof rawError.message === "string"
      ? {
          code: rawError.code,
          message: rawError.message,
        }
      : undefined;
  // İstemci yüzeyi z=f(x,y) ifadesini kendi örnekliyor. İfade güvenli
  // değerlendiriciyle derlenmiyorsa istemcide BOŞ bir yüzey çıkardı; bunun
  // yerine nedeni bloğa yazıyoruz ki kullanıcı sessiz bir boşluk görmesin.
  const error =
    declaredError ??
    (isSampleableExpression(expression, ["x", "y"])
      ? undefined
      : {
          code: "expression_not_sampleable",
          message: "Bu ifade yüzey olarak örneklenemedi.",
        });
  return {
    type: "math_surface_3d",
    expression,
    ...(normalizeTextValue(input.title, 120) ? { title: normalizeTextValue(input.title, 120)! } : {}),
    variables: normalizedVariables ?? (["x", "y"] as ["x", "y"]),
    ...(xRange && yRange ? { range: { x: xRange, y: yRange } } : {}),
    ...(resolution ? { resolution } : {}),
    ...(normalizeTextValue(input.zLabel, 120) ? { zLabel: normalizeTextValue(input.zLabel, 120)! } : {}),
    ...(colorBy ? { colorBy } : {}),
    ...(mode ? { mode } : {}),
    ...(typeof input.interactive === "boolean" ? { interactive: input.interactive } : {}),
    ...(renderer ? { renderer } : {}),
    ...(cacheKey ? { cacheKey } : {}),
    ...(normalizeTextValue(input.caption, 240) ? { caption: normalizeTextValue(input.caption, 240)! } : {}),
    ...(error ? { error } : {}),
    ...withAssistantBlockDefaults("math_surface_3d", {}, {
      priority: options.priority ?? 2,
      renderHints: {
        sectionRole: "math_surface_3d",
        interactiveSurface: true,
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantSvgBlock(
  input: {
    svg?: string | null;
    markup?: string | null;
    url?: string | null;
    title?: string | null;
    caption?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantSvgBlock | null {
  const svg = normalizeTextValue(input.svg ?? input.markup, 80_000);
  const url = normalizeTextValue(input.url, 2_000);
  if (!svg && !url) {
    return null;
  }
  return {
    type: "svg",
    ...(svg ? { svg } : {}),
    ...(url ? { url } : {}),
    ...(normalizeTextValue(input.title, 120) ? { title: normalizeTextValue(input.title, 120)! } : {}),
    ...(normalizeTextValue(input.caption, 240) ? { caption: normalizeTextValue(input.caption, 240)! } : {}),
    exportFormats: ["svg", "png", "pdf"],
    ...withAssistantBlockDefaults("svg", {}, {
      ...options,
      priority: options.priority ?? 2,
      renderHints: mergeRenderHints({
        sectionRole: "svg",
        renderer: "mobile_local",
        exportFamily: "image",
        vectorSafe: true,
        preflightRequired: true,
      }, options.renderHints),
    }),
  };
}

export function buildAssistantFileBlock(
  input: {
    fileName: string;
    mimeType?: string | null;
    sizeBytes?: number | null;
    documentId?: string | null;
    preview?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantFileBlock | null {
  const fileName = normalizeTextValue(String(input.fileName ?? "").replace(/^.*[\\/]/, ""), 180);
  if (!fileName) {
    return null;
  }
  return {
    type: "file",
    fileName,
    ...(normalizeTextValue(input.mimeType, 120) ? { mimeType: normalizeTextValue(input.mimeType, 120)! } : {}),
    ...(typeof input.sizeBytes === "number" && Number.isInteger(input.sizeBytes) && input.sizeBytes >= 0
      ? { sizeBytes: input.sizeBytes }
      : {}),
    ...(normalizeTextValue(input.documentId, 255) ? { documentId: normalizeTextValue(input.documentId, 255)! } : {}),
    ...(normalizeTextValue(input.preview, 400) ? { preview: normalizeTextValue(input.preview, 400)! } : {}),
    ...withAssistantBlockDefaults("file", {}, {
      priority: options.priority ?? 2,
      renderHints: {
        sectionRole: "attachment_file",
        density: "compact",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantDocumentBlock(
  input: {
    title?: string | null;
    sections: Array<{ heading?: string | null; content: string; level?: number | null }>;
    format?: string | null;
    wordCount?: number | null;
    summary?: string | null;
    exportFormats?: unknown;
    design?: unknown;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantDocumentBlock | null {
  const sections = (input.sections ?? [])
    .map((s) => ({
      ...(s.heading ? { heading: String(s.heading).slice(0, 200) } : {}),
      content: String(s.content ?? "").trim().slice(0, 8_000),
      ...(typeof s.level === "number" && s.level >= 1 && s.level <= 3 ? { level: s.level } : {}),
    }))
    .filter((s) => s.content.length > 0)
    .slice(0, 40);
  if (sections.length === 0) return null;
  const validFormats = ["report", "letter", "outline", "notes"] as const;
  const format = validFormats.find((f) => f === input.format) ?? undefined;
  const exportFormats = normalizeStringArray(
    input.exportFormats,
    ["pdf", "docx", "xlsx"],
    3,
  );
  const designRecord =
    input.design && typeof input.design === "object" && !Array.isArray(input.design)
      ? (input.design as Record<string, unknown>)
      : {};
  const theme = ["system", "report", "editorial", "minimal"].includes(String(designRecord.theme))
    ? String(designRecord.theme)
    : "report";
  const density = ["compact", "comfortable", "spacious"].includes(String(designRecord.density))
    ? String(designRecord.density)
    : "comfortable";
  const pageSize = String(designRecord.pageSize).toLowerCase() === "letter" ? "Letter" : "A4";
  return {
    type: "document_block",
    sections,
    ...(normalizeTextValue(input.title, 200) ? { title: normalizeTextValue(input.title, 200)! } : {}),
    ...(format ? { format } : {}),
    ...(normalizeTextValue(input.summary, 300) ? { summary: normalizeTextValue(input.summary, 300)! } : {}),
    exportFormats: exportFormats.length > 0 ? exportFormats as ["pdf" | "docx" | "xlsx", ...("pdf" | "docx" | "xlsx")[]] : ["pdf", "docx"],
    design: {
      theme: theme as "system" | "report" | "editorial" | "minimal",
      density: density as "compact" | "comfortable" | "spacious",
      pageSize: pageSize as "A4" | "Letter",
    },
    ...(typeof input.wordCount === "number" && input.wordCount >= 0 ? { wordCount: input.wordCount } : {}),
    ...withAssistantBlockDefaults("document_block", {}, {
      ...options,
      priority: options.priority ?? 2,
      renderHints: mergeRenderHints({
        sectionRole: "document",
        renderer: "mobile_local",
        exportFamily: "document",
        density: "full",
        preflightRequired: true,
      }, options.renderHints),
    }),
  };
}

export function buildAssistantAttachmentAckBlock(
  input: {
    summary: string;
    attachmentCount: number;
    pageCount?: number | null;
    chunkCount?: number | null;
    hasTable?: boolean;
    hasImage?: boolean;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantAttachmentAckBlock | null {
  const summary = normalizeTextValue(input.summary, 400);
  if (!summary) return null;
  return {
    type: "attachment_ack",
    summary,
    attachmentCount: Math.max(0, Math.floor(input.attachmentCount ?? 0)),
    ...(typeof input.pageCount === "number" ? { pageCount: input.pageCount } : {}),
    ...(typeof input.chunkCount === "number" ? { chunkCount: input.chunkCount } : {}),
    ...(typeof input.hasTable === "boolean" ? { hasTable: input.hasTable } : {}),
    ...(typeof input.hasImage === "boolean" ? { hasImage: input.hasImage } : {}),
    ...withAssistantBlockDefaults("attachment_ack", {}, {
      priority: options.priority ?? 3,
      visibility: options.visibility ?? "user_visible",
      renderHints: { sectionRole: "status", density: "compact", ...(options.renderHints ?? {}) },
      ...options,
    }),
  };
}

export function buildAssistantImageAnalysisBlock(
  input: {
    description: string;
    detectedText?: string | null;
    tags?: string[] | null;
    confidence?: number | null;
    language?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantImageAnalysisBlock | null {
  const description = normalizeTextValue(input.description, 2_000);
  if (!description) return null;
  const tags = normalizeStringList(input.tags, { max: 12, itemMaxLength: 60 });
  return {
    type: "image_analysis",
    description,
    ...(normalizeTextValue(input.detectedText, 2_000)
      ? { detectedText: normalizeTextValue(input.detectedText, 2_000)! }
      : {}),
    ...(tags.length > 0 ? { tags } : {}),
    ...(typeof input.confidence === "number" && input.confidence >= 0 && input.confidence <= 1
      ? { confidence: input.confidence }
      : {}),
    ...(normalizeTextValue(input.language, 20) ? { language: normalizeTextValue(input.language, 20)! } : {}),
    ...withAssistantBlockDefaults("image_analysis", {}, {
      priority: options.priority ?? 2,
      renderHints: { sectionRole: "image_result", density: "full", ...(options.renderHints ?? {}) },
      ...options,
    }),
  };
}

export function buildAssistantBlockGroup(
  children: AssistantMessageBlock[],
  options: AssistantBlockCommon & { title?: string } = {},
): ElyanAssistantBlockGroupBlock | null {
  const visibleChildren = children.filter(Boolean).slice(0, 12);
  if (visibleChildren.length === 0) {
    return null;
  }
  return {
    type: "block_group",
    children: visibleChildren,
    ...(normalizeTextValue(options.title, 120) ? { title: normalizeTextValue(options.title, 120)! } : {}),
    ...withAssistantBlockDefaults("block_group", {}, {
      priority: options.priority ?? 1,
      renderHints: {
        sectionRole: "detail",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantWebSearchBlock(
  input: {
    query: string;
    queries: string[];
    confidence: "high" | "medium" | "low";
    retrievedAt?: string;
    results: Array<{
      title: string;
      url: string;
      snippet?: string;
      sourceHost?: string;
      verificationState: "verified" | "partial" | "unverified";
    }>;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantWebSearchBlock | null {
  const query = normalizeTextValue(input.query, 320);
  if (!query || input.results.length === 0) {
    return null;
  }
  const results = input.results
    .map((result) => {
      const title = normalizeTextValue(result.title, 240);
      const url = normalizeTextValue(result.url, 512);
      if (!title || !url) {
        return null;
      }
      return {
        title,
        url,
        ...(result.snippet ? { snippet: normalizeTextValue(result.snippet, 400) ?? undefined } : {}),
        ...(result.sourceHost ? { sourceHost: normalizeTextValue(result.sourceHost, 120) ?? undefined } : {}),
        verificationState: result.verificationState,
      };
    })
    .filter((r): r is NonNullable<typeof r> => r != null)
    .slice(0, 8);
  if (results.length === 0) {
    return null;
  }
  const queries = (input.queries ?? [])
    .map((q) => normalizeTextValue(q, 320))
    .filter((q): q is string => Boolean(q))
    .slice(0, 4);
  const defaults = withAssistantBlockDefaults("web_search", {}, {
    priority: options.priority ?? 1,
    renderHints: {
      tone: "research",
      density: "compact",
      ...(options.renderHints ?? {}),
    },
    ...options,
  });
  return {
    type: "web_search",
    query,
    queries: queries.length > 0 ? queries : [query],
    confidence: input.confidence,
    ...(input.retrievedAt ? { retrievedAt: input.retrievedAt } : {}),
    results,
    ...defaults,
  } as ElyanAssistantWebSearchBlock;
}

export function buildAssistantConnectorResultBlock(
  input: {
    provider: ElyanAssistantConnectorResultBlock["provider"];
    tool: string;
    title: string;
    kind?: string | null;
    summary?: string | null;
    items: Array<{
      title: string;
      subtitle?: string | null;
      detail?: string | null;
      timestamp?: string | null;
      url?: string | null;
      kind?: string | null;
      status?: string | null;
      metadata?: Record<string, unknown> | null;
    }>;
    columns?: unknown;
    rows?: unknown;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantConnectorResultBlock | null {
  const title = normalizeTextValue(input.title, 160);
  const tool = normalizeTextValue(input.tool, 160);
  if (!title || !tool) return null;
  const items = input.items
    .map((item) => {
      const itemTitle = normalizeTextValue(item.title, 240);
      if (!itemTitle) return null;
      const metadata =
        item.metadata && typeof item.metadata === "object" && !Array.isArray(item.metadata)
          ? (normalizeRenderHintValue(item.metadata, 0) as Record<string, unknown> | undefined)
          : undefined;
      return {
        title: itemTitle,
        ...(normalizeTextValue(item.subtitle, 240) ? { subtitle: normalizeTextValue(item.subtitle, 240)! } : {}),
        ...(normalizeTextValue(item.detail, 400) ? { detail: normalizeTextValue(item.detail, 400)! } : {}),
        ...(normalizeTextValue(item.timestamp, 120) ? { timestamp: normalizeTextValue(item.timestamp, 120)! } : {}),
        ...(normalizeTextValue(item.url, 2_000) ? { url: normalizeTextValue(item.url, 2_000)! } : {}),
        ...(normalizeTextValue(item.kind, 80) ? { kind: normalizeTextValue(item.kind, 80)! } : {}),
        ...(normalizeTextValue(item.status, 80) ? { status: normalizeTextValue(item.status, 80)! } : {}),
        ...(metadata ? { metadata } : {}),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item != null)
    .slice(0, 80);
  if (items.length === 0) return null;
  const columns = normalizeTableColumns(input.columns);
  const rows = normalizeTableRows(input.rows, columns.length);
  return {
    type: "connector_result",
    provider: input.provider,
    tool,
    title,
    ...(normalizeTextValue(input.kind, 80) ? { kind: normalizeTextValue(input.kind, 80)! } : {}),
    ...(normalizeTextValue(input.summary, 240) ? { summary: normalizeTextValue(input.summary, 240)! } : {}),
    items,
    ...(columns.length > 0 && rows.length > 0 ? { columns, rows } : {}),
    ...withAssistantBlockDefaults("connector_result", {}, {
      priority: options.priority ?? 1,
      renderHints: mergeRenderHints({
        sectionRole: "connector_result",
        renderer: "native_connector_result",
        density: "regular",
      }, options.renderHints),
      ...options,
    }),
  };
}

function isTaskTraceBlock(block: AssistantMessageBlock): block is ElyanTaskTraceBlock {
  return isDispatchWidgetType(block.type);
}

function parseTaskTraceBlock(value: Record<string, unknown>): ElyanTaskTraceBlock | null {
  const taskId = String(value.taskId ?? "").trim();
  const status = String(value.status ?? "").trim().toLowerCase();
  const title = String(value.title ?? "").trim();
  const routeReasonCandidate = normalizeTextValue(value.routeReason, 240);
  const routeReason =
    routeReasonCandidate &&
    !shouldRedactProtectedElyanDisclosure(routeReasonCandidate)
      ? redactVisibleInternalConfigurationTerms(routeReasonCandidate)
      : null;
  const rawSteps = Array.isArray(value.steps) ? value.steps : [];
  const steps = rawSteps
    .map((step) => {
      if (!step || typeof step !== "object" || Array.isArray(step)) {
        return null;
      }
      const record = step as Record<string, unknown>;
      const id = String(record.id ?? "").trim().toLowerCase();
      const label = String(record.label ?? "").trim();
      const stepStatus = String(record.status ?? "").trim().toLowerCase();
      if (
        !taskId ||
        !title ||
        !id ||
        !label ||
        !["running", "completed", "failed", "waiting_approval"].includes(status) ||
        !["pending", "running", "waiting_approval", "completed", "failed", "skipped"].includes(stepStatus)
      ) {
        return null;
      }

      return {
        id: id as ElyanTaskTraceBlock["steps"][number]["id"],
        label,
        status: stepStatus as ElyanTaskTraceBlock["steps"][number]["status"],
        ...(typeof record.detail === "string" && record.detail.trim()
          ? { detail: record.detail.trim() }
          : {}),
        ...(typeof record.tool === "string" && record.tool.trim() ? { tool: record.tool.trim() } : {}),
        ...(typeof record.resultSummary === "string" && record.resultSummary.trim()
          ? { resultSummary: record.resultSummary.trim() }
          : {}),
        ...(typeof record.capability === "string" && record.capability.trim()
          ? { capability: record.capability.trim().slice(0, 120) }
          : {}),
        ...(record.approval && typeof record.approval === "object" && !Array.isArray(record.approval)
          ? { approval: record.approval as ElyanTaskTraceBlock["steps"][number]["approval"] }
          : {}),
        ...(["pending", "passed", "repaired", "failed"].includes(
          String(record.verificationStatus ?? "").trim().toLowerCase(),
        )
          ? {
              verificationStatus: String(record.verificationStatus)
                .trim()
                .toLowerCase() as ElyanTaskTraceBlock["steps"][number]["verificationStatus"],
            }
          : {}),
        ...(typeof record.attemptCount === "number" &&
        Number.isInteger(record.attemptCount) &&
        record.attemptCount >= 1 &&
        record.attemptCount <= 32
          ? { attemptCount: record.attemptCount }
          : {}),
        ...(typeof record.startedAt === "string" && record.startedAt.trim()
          ? { startedAt: record.startedAt.trim() }
          : {}),
        ...(typeof record.completedAt === "string" && record.completedAt.trim()
          ? { completedAt: record.completedAt.trim() }
          : {}),
        ...(typeof record.durationMs === "number" && Number.isFinite(record.durationMs) && record.durationMs >= 0
          ? { durationMs: record.durationMs }
          : {}),
      };
    })
    .filter((step): step is ElyanTaskTraceBlock["steps"][number] => step != null);

  if (!taskId || !title || steps.length === 0) {
    return null;
  }

  if (!["running", "completed", "failed", "waiting_approval"].includes(status)) {
    return null;
  }

  const activeStepIdCandidate = String(value.activeStepId ?? "")
    .trim()
    .toLowerCase();
  const activeStepId =
    /^[a-zA-Z0-9_-]{1,80}$/.test(activeStepIdCandidate) &&
    steps.some((step) => step.id === activeStepIdCandidate)
      ? activeStepIdCandidate
      : null;
  const verificationRecord =
    value.verification &&
    typeof value.verification === "object" &&
    !Array.isArray(value.verification)
      ? (value.verification as Record<string, unknown>)
      : null;
  const verificationStatus = String(verificationRecord?.status ?? "")
    .trim()
    .toLowerCase();
  const interactionRecord =
    value.interaction && typeof value.interaction === "object" && !Array.isArray(value.interaction)
      ? (value.interaction as Record<string, unknown>)
      : null;
  const interactionKind = String(interactionRecord?.kind ?? "").trim().toLowerCase();
  const normalizedInteraction = ["permission", "clarification", "approval"].includes(
    interactionKind,
  )
    ? {
        contract: "elyan.interaction.v1" as const,
        id:
          normalizeTextValue(interactionRecord?.id, 255) ??
          `${taskId}:interaction:${
            typeof interactionRecord?.revision === "number" &&
            Number.isInteger(interactionRecord.revision) &&
            interactionRecord.revision > 0
              ? interactionRecord.revision
              : 1
          }`,
        taskId,
        taskRunId:
          normalizeTextValue(interactionRecord?.taskRunId, 255) ?? taskId,
        kind: interactionKind as "permission" | "clarification" | "approval",
        revision:
          typeof interactionRecord?.revision === "number" &&
          Number.isInteger(interactionRecord.revision) &&
          interactionRecord.revision > 0
            ? interactionRecord.revision
            : 1,
        // Kind determines the action surface. Ignore stale or incompatible
        // actions from legacy/persisted blocks while rebuilding the envelope.
        availableActions:
          interactionKind === "clarification"
            ? ["answer"]
            : ["approve", "reject"],
        ...(normalizeTextValue(interactionRecord?.question, 1_000)
          ? { question: normalizeTextValue(interactionRecord?.question, 1_000)! }
          : {}),
        ...(normalizeTextValue(interactionRecord?.summary, 1_000)
          ? { summary: normalizeTextValue(interactionRecord?.summary, 1_000)! }
          : {}),
        expiresAt:
          typeof interactionRecord?.expiresAt === "string" &&
          !Number.isNaN(Date.parse(interactionRecord.expiresAt))
            ? new Date(interactionRecord.expiresAt).toISOString()
            : new Date(Date.now() + 60_000).toISOString(),
        resolution:
          interactionRecord?.resolution &&
          typeof interactionRecord.resolution === "object" &&
          !Array.isArray(interactionRecord.resolution)
            ? (interactionRecord.resolution as Record<string, unknown>)
            : null,
      }
    : null;
  const rawArtifacts = Array.isArray(value.artifacts) ? value.artifacts : [];
  const artifacts = rawArtifacts.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const artifact = item as Record<string, unknown>;
    const artifactTitle = normalizeTextValue(
      artifact.title ?? artifact.name ?? artifact.fileName,
      180,
    );
    if (!artifactTitle) return [];
    return [{
      ...(normalizeTextValue(artifact.id, 255) ? { id: normalizeTextValue(artifact.id, 255)! } : {}),
      title: artifactTitle,
      ...(normalizeTextValue(artifact.kind, 80) ? { kind: normalizeTextValue(artifact.kind, 80)! } : {}),
      ...(normalizeTextValue(artifact.path, 1_000) ? { path: normalizeTextValue(artifact.path, 1_000)! } : {}),
      ...(normalizeTextValue(artifact.url, 2_000) ? { url: normalizeTextValue(artifact.url, 2_000)! } : {}),
    }];
  }).slice(0, 12);
  const errorRecord =
    value.error && typeof value.error === "object" && !Array.isArray(value.error)
      ? (value.error as Record<string, unknown>)
      : null;
  const errorMessage = normalizeTextValue(errorRecord?.message, 500);
  const availableActions = Array.isArray(value.availableActions)
    ? value.availableActions.filter(
        (action): action is "approve" | "reject" | "answer" | "retry" =>
          typeof action === "string" && ["approve", "reject", "answer", "retry"].includes(action),
      ).slice(0, 4)
    : [];

  const candidate = {
    type: "dispatch_widget",
    taskId,
    status: status as ElyanTaskTraceBlock["status"],
    title,
    ...(normalizeTextValue(value.phase, 80)
      ? { phase: normalizeTextValue(value.phase, 80)! }
      : {}),
    ...(normalizeTextValue(value.summary, 180)
      ? { summary: normalizeTextValue(value.summary, 180)! }
      : {}),
    ...(normalizeTextValue(value.progressLabel, 80)
      ? { progressLabel: normalizeTextValue(value.progressLabel, 80)! }
      : {}),
    ...(routeReason ? { routeReason } : {}),
    ...(activeStepId ? { activeStepId } : {}),
    ...(typeof value.needsApproval === "boolean"
      ? { needsApproval: value.needsApproval }
      : {}),
    ...(["pending", "passed", "repaired", "failed"].includes(verificationStatus)
      ? {
          verification: {
            status: verificationStatus as NonNullable<
              ElyanTaskTraceBlock["verification"]
            >["status"],
            ...(normalizeTextValue(verificationRecord?.summary, 240)
              ? { summary: normalizeTextValue(verificationRecord?.summary, 240)! }
              : {}),
          },
        }
      : {}),
    ...(normalizedInteraction
      ? {
          interaction: normalizedInteraction,
        }
      : {}),
    ...(artifacts.length > 0 ? { artifacts } : {}),
    ...(errorRecord && errorMessage
      ? {
          error: {
            code: normalizeTextValue(errorRecord.code, 120) ?? "TASK_EXECUTION_FAILED",
            message: errorMessage,
            retryable: errorRecord.retryable === true,
          },
        }
      : {}),
    ...(availableActions.length > 0 ? { availableActions } : {}),
    ...(typeof value.updatedAt === "string" && !Number.isNaN(Date.parse(value.updatedAt))
      ? { updatedAt: new Date(value.updatedAt).toISOString() }
      : {}),
    ...(typeof value.repairAttempts === "number" &&
    Number.isInteger(value.repairAttempts) &&
    value.repairAttempts >= 0 &&
    value.repairAttempts <= 32
      ? { repairAttempts: value.repairAttempts }
      : {}),
    ...(normalizeTextValue(value.stopReason, 160)
      ? { stopReason: normalizeTextValue(value.stopReason, 160)! }
      : {}),
    steps,
    ...withAssistantBlockDefaults("dispatch_widget", {}, {
      stableBlockId:
        normalizeBlockStableId(value.blockId) ??
        normalizeBlockStableId(value.stableBlockId),
      visibility: normalizeVisibility(value.visibility),
      confidence: normalizeConfidence(value.confidence),
      priority: normalizePriority(value.priority),
      cacheDigest: normalizeBlockCacheDigest(value.cacheDigest),
      renderHints: normalizeRenderHints(value.renderHints),
    }),
  };
  const parsed = elyanTaskTraceBlockSchema.safeParse(candidate);
  return parsed.success ? parsed.data : null;
}

function parseCommonMetadata(value: Record<string, unknown>): AssistantBlockCommon {
  return {
    stableBlockId:
      normalizeBlockStableId(value.blockId) ??
      normalizeBlockStableId(value.stableBlockId),
    visibility: normalizeVisibility(value.visibility),
    confidence: normalizeConfidence(value.confidence),
    priority: normalizePriority(value.priority),
    cacheDigest: normalizeBlockCacheDigest(value.cacheDigest),
    renderHints: normalizeRenderHints(value.renderHints),
  };
}

function parseInfoItems(value: unknown): ElyanAssistantInfoCardBlock["items"] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return null;
      }
      const record = item as Record<string, unknown>;
      const label = normalizeTextValue(record.label, 120);
      const itemValue = normalizeTextValue(record.value, 240);
      if (!label || !itemValue) {
        return null;
      }
      return {
        label,
        value: itemValue,
        ...(normalizeConfidence(record.confidence) != null
          ? { confidence: normalizeConfidence(record.confidence) }
          : {}),
      };
    })
    .filter((item): item is ElyanAssistantInfoCardBlock["items"][number] => item != null)
    .slice(0, 8);
}

function stableBlockDedupeKey(block: AssistantMessageBlock): string {
  const record = block as Record<string, unknown>;
  const blockId = normalizeBlockStableId(record.blockId) ?? "";
  if (blockId) {
    return `${block.type}:id:${blockId}`;
  }
  const stableBlockId = normalizeBlockStableId(record.stableBlockId) ?? "";
  if (stableBlockId) {
    return `${block.type}:id:${stableBlockId}`;
  }
  const contentKey = assistantBlockContentDedupeKey(block);
  if (contentKey) {
    return contentKey;
  }
  const cacheDigest = normalizeBlockCacheDigest(record.cacheDigest) ?? "";
  if (cacheDigest) {
    return `${block.type}:cache:${cacheDigest}`;
  }
  return `${block.type}:body:${JSON.stringify(block)}`;
}

function assistantBlockSchemaValid(block: AssistantMessageBlock): boolean {
  return elyanAssistantBlockSchema.safeParse(block).success;
}

function assistantBlockContentDedupeKey(block: AssistantMessageBlock): string | null {
  if (block.type === "text") {
    const markdown = normalizeMarkdown((block as ElyanAssistantTextBlock).markdown)
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
    return markdown ? `text:content:${markdown}` : null;
  }
  if (block.type === "table") {
    const table = block as ElyanAssistantTableBlock;
    const columns = table.columns
      .map((column) => column.trim().replace(/\s+/g, " ").toLowerCase())
      .join("\u001F");
    const rows = table.rows
      .map((row) =>
        row
          .map((cell) => cell.trim().replace(/\s+/g, " ").toLowerCase())
          .join("\u001F"),
      )
      .filter((row) => row.replace(/\u001F/g, "").length > 0)
      .join("\u001E");
    return columns && rows ? `table:content:${columns}\u001D${rows}` : null;
  }
  return null;
}

function countDuplicateAssistantBlocks(blocks: AssistantMessageBlock[]): number {
  const seen = new Set<string>();
  let duplicateCount = 0;
  for (const block of blocks) {
    const key = stableBlockDedupeKey(block);
    if (seen.has(key)) {
      duplicateCount += 1;
      continue;
    }
    seen.add(key);
  }
  return duplicateCount;
}

function countDuplicateAssistantBlocksOfType(
  blocks: AssistantMessageBlock[],
  type: AssistantMessageBlock["type"],
): number {
  return countDuplicateAssistantBlocks(blocks.filter((block) => block.type === type));
}

function dedupeAssistantBlocks(blocks: AssistantMessageBlock[]): AssistantMessageBlock[] {
  const seen = new Set<string>();
  const result: AssistantMessageBlock[] = [];
  for (const block of blocks) {
    const key = stableBlockDedupeKey(block);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(block);
  }
  return dedupeSubsetTables(result);
}

/**
 * Subset-aware dedup for `table` blocks.
 *
 * The model sometimes emits the same data twice — once as a full canonical
 * table and once as a truncated/streaming-artifact fragment (fewer rows,
 * occasionally corrupted). Exact-key dedup misses these because their row
 * signatures differ. Here two tables with matching columns collapse when
 * one row set is a subset of the other: the smaller one is dropped, the
 * larger is kept in its earlier position.
 */
function dedupeSubsetTables(blocks: AssistantMessageBlock[]): AssistantMessageBlock[] {
  const output = [...blocks];
  const tableIndices: number[] = [];
  for (let i = 0; i < output.length; i += 1) {
    if (output[i].type === "table") {
      tableIndices.push(i);
    }
  }
  if (tableIndices.length < 2) {
    return output;
  }
  const removals = new Set<number>();
  for (let a = 0; a < tableIndices.length; a += 1) {
    const idxA = tableIndices[a];
    if (removals.has(idxA)) continue;
    const tableA = output[idxA] as ElyanAssistantTableBlock;
    for (let b = a + 1; b < tableIndices.length; b += 1) {
      const idxB = tableIndices[b];
      if (removals.has(idxB)) continue;
      const tableB = output[idxB] as ElyanAssistantTableBlock;
      if (!tableColumnsEqual(tableA.columns, tableB.columns)) continue;
      const rowsA = tableRowSignatureSet(tableA.rows);
      const rowsB = tableRowSignatureSet(tableB.rows);
      if (rowsA.size === 0 || rowsB.size === 0) continue;
      if (isSubset(rowsB, rowsA)) {
        removals.add(idxB);
        continue;
      }
      if (isSubset(rowsA, rowsB)) {
        // Replace the earlier table with the later, more complete one, then
        // drop the later slot so surrounding order is preserved.
        output[idxA] = tableB;
        removals.add(idxB);
      }
    }
  }
  return output.filter((_, i) => !removals.has(i));
}

function tableColumnsEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].trim().toLowerCase() !== b[i].trim().toLowerCase()) return false;
  }
  return true;
}

function tableRowSignatureSet(rows: string[][]): Set<string> {
  const set = new Set<string>();
  for (const row of rows) {
    const signature = row.map((cell) => cell.trim()).join("|");
    if (signature.replace(/\|/g, "").length === 0) continue;
    set.add(signature);
  }
  return set;
}

function isSubset(candidate: Set<string>, container: Set<string>): boolean {
  if (candidate.size > container.size) return false;
  for (const value of candidate) {
    if (!container.has(value)) return false;
  }
  return true;
}

function parseAssistantBlock(value: unknown): AssistantMessageBlock | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const rawRecord = value as Record<string, unknown>;
  const type = String(rawRecord.type ?? "").trim().toLowerCase();
  if (isSourceWidgetBlockType(type)) {
    // Source widgets have no legacy top-level representation. Do not repair a
    // partially streamed/model-authored object into a canonical envelope: all
    // required envelope fields must already be present and schema-valid.
    if (!elyanAssistantBlockSchema.safeParse(rawRecord).success) {
      return null;
    }
    const enveloped = withCanonicalAssistantBlockEnvelope(rawRecord);
    return enveloped as AssistantMessageBlock;
  }
  const record = hydrateLegacyAssistantBlockInput(rawRecord);
  if (isDispatchWidgetType(type)) {
    return parseTaskTraceBlock(record);
  }
  if (type === "summary") {
    const summaryValue =
      typeof record.summary === "string"
        ? record.summary
        : typeof record.markdown === "string"
          ? record.markdown
          : "";
    return buildAssistantSummaryBlock(
      summaryValue,
      {
        title: typeof record.title === "string" ? record.title : undefined,
        ...parseCommonMetadata(record),
      },
    );
  }
  if (type === "next_steps") {
    const stepItems = Array.isArray(record.items)
      ? record.items.map((item) => String(item))
      : [];
    return buildAssistantNextStepsBlock(stepItems, {
      title: typeof record.title === "string" ? record.title : undefined,
      ...parseCommonMetadata(record),
    });
  }
  if (type === "status") {
    const status = String(record.status ?? "").trim().toLowerCase();
    if (
      ![
        "running",
        "waiting_approval",
        "needs_desktop",
        "completed",
        "failed",
        "retrying",
        "degraded",
      ].includes(status)
    ) {
      return null;
    }
    return buildAssistantStatusBlock(
      {
        status: status as ElyanAssistantStatusBlock["status"],
        title:
          typeof record.title === "string" ? record.title : "Durum",
        detail:
          typeof record.detail === "string" ? record.detail : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "security_decision") {
    const requestType = String(record.request_type ?? "").trim();
    const risk = String(record.risk ?? "").trim();
    if (
      ![
        "secret_extraction_attempt",
        "system_prompt_extraction_attempt",
        "internal_endpoint_request",
        "database_credential_request",
        "payment_action_request",
        "destructive_action_request",
        "external_send_request",
      ].includes(requestType) ||
      !["low", "medium", "high", "critical"].includes(risk)
    ) {
      return null;
    }
    return {
      type: "security_decision",
      request_type: requestType as ElyanAssistantSecurityDecisionBlock["request_type"],
      is_sensitive: record.is_sensitive === true,
      should_refuse: record.should_refuse === true,
      blocked_fields: Array.isArray(record.blocked_fields)
        ? record.blocked_fields.map((item) => String(item)).filter(Boolean).slice(0, 16)
        : [],
      reason: typeof record.reason === "string" ? record.reason : "Security-sensitive request was blocked.",
      safe_alternative:
        typeof record.safe_alternative === "string"
          ? record.safe_alternative
          : "I can help with a safe alternative.",
      leaked_secret: false,
      invented_internal_info: false,
      requires_verified_admin_channel:
        record.requires_verified_admin_channel === true,
      risk: risk as ElyanAssistantSecurityDecisionBlock["risk"],
      ...withAssistantBlockDefaults("security_decision", {}, {
        visibility: normalizeVisibility(record.visibility) ?? "assistant_internal_by_default",
        confidence: normalizeConfidence(record.confidence),
        priority: normalizePriority(record.priority),
        stableBlockId:
          normalizeBlockStableId(record.blockId) ??
          normalizeBlockStableId(record.stableBlockId),
        cacheDigest: normalizeBlockCacheDigest(record.cacheDigest),
        renderHints: normalizeRenderHints(record.renderHints) ?? {},
      }),
    };
  }
  if (type === "artifact") {
    const parsed = elyanAssistantArtifactBlockSchema.safeParse(record);
    return parsed.success ? parsed.data : null;
  }
  if (type === "web_search") {
    const rawResults = Array.isArray(record.results) ? record.results : [];
    const results = rawResults
      .filter((r) => r && typeof r === "object" && !Array.isArray(r))
      .map((r) => {
        const entry = r as Record<string, unknown>;
        return {
          title: String(entry.title ?? "").trim(),
          url: String(entry.url ?? "").trim(),
          snippet: typeof entry.snippet === "string" ? entry.snippet : undefined,
          sourceHost: typeof entry.sourceHost === "string" ? entry.sourceHost : undefined,
          verificationState: (["verified", "partial", "unverified"] as const).includes(
            String(entry.verificationState ?? "") as "verified" | "partial" | "unverified",
          )
            ? (String(entry.verificationState) as "verified" | "partial" | "unverified")
            : "unverified",
        };
      });
    const confidence = (["high", "medium", "low"] as const).includes(
      String(record.confidence ?? "") as "high" | "medium" | "low",
    )
      ? (String(record.confidence) as "high" | "medium" | "low")
      : "medium";
    return buildAssistantWebSearchBlock(
      {
        query: typeof record.query === "string" ? record.query : "",
        queries: Array.isArray(record.queries)
          ? record.queries.map((q) => String(q)).filter(Boolean)
          : [],
        confidence,
        retrievedAt: typeof record.retrievedAt === "string" ? record.retrievedAt : undefined,
        results,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "attachment_context" || type === "context_signal") {
    return buildAssistantInfoCardBlock(
      {
        type,
        title:
          typeof record.title === "string" ? record.title : "Bağlam",
        items: parseInfoItems(record.items),
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "code") {
    return buildAssistantCodeBlock(
      {
        code:
          typeof record.code === "string"
            ? record.code
            : typeof record.content === "string"
              ? record.content
              : typeof record.text === "string"
                ? record.text
                : "",
        language: typeof record.language === "string" ? record.language : undefined,
        filename: typeof record.filename === "string" ? record.filename : undefined,
        title: typeof record.title === "string" ? record.title : undefined,
        collapsed: typeof record.collapsed === "boolean" ? record.collapsed : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "table") {
    return buildAssistantTableBlock(
      {
        columns: record.columns,
        rows: record.rows,
        title: typeof record.title === "string" ? record.title : undefined,
        summary: typeof record.summary === "string" ? record.summary : undefined,
        caption: typeof record.caption === "string" ? record.caption : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "chart") {
    return buildAssistantChartBlock(
      {
        chartType: String(record.chartType ?? record.chart_type ?? record.kind ?? "bar") as ElyanAssistantChartBlock["chartType"],
        labels: record.labels ?? record.categories ?? record.x,
        values: record.values ?? record.y,
        points: record.points,
        data: record.data,
        series: record.series ?? record.datasets,
        expression: typeof record.expression === "string"
          ? record.expression
          : typeof record.expr === "string"
            ? record.expr
            : typeof record.formula === "string"
              ? record.formula
              : typeof record.function === "string"
                ? record.function
                : undefined,
        variables: record.variables,
        range: record.range,
        fixed: record.fixed,
        xLabel: typeof record.xLabel === "string"
          ? record.xLabel
          : typeof record.x_label === "string"
            ? record.x_label
            : undefined,
        yLabel: typeof record.yLabel === "string"
          ? record.yLabel
          : typeof record.y_label === "string"
            ? record.y_label
            : undefined,
        unit: typeof record.unit === "string" ? record.unit : undefined,
        theme: typeof record.theme === "string" ? record.theme : undefined,
        interactions: record.interactions,
        renderer: typeof record.renderer === "string" ? record.renderer : undefined,
        title: typeof record.title === "string" ? record.title : undefined,
        caption: typeof record.caption === "string" ? record.caption : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "math" || type === "latex" || type === "formula" || type === "equation") {
    return buildAssistantMathBlock(
      {
        content:
          typeof record.content === "string"
            ? record.content
            : typeof record.latex === "string"
              ? record.latex
              : typeof record.tex === "string"
                ? record.tex
                : typeof record.equation === "string"
                  ? record.equation
                  : typeof record.expression === "string"
                    ? record.expression
                    : undefined,
        latex: typeof record.latex === "string" ? record.latex : undefined,
        displayMode:
          typeof record.displayMode === "boolean"
            ? record.displayMode
            : typeof record.display_mode === "boolean"
              ? record.display_mode
              : undefined,
        format: typeof record.format === "string" ? record.format : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "math_surface_3d") {
    return buildAssistantMathSurface3DBlock(
      {
        expression: typeof record.expression === "string"
          ? record.expression
          : typeof record.formula === "string"
            ? record.formula
            : typeof record.content === "string"
              ? record.content
              : undefined,
        title: typeof record.title === "string" ? record.title : undefined,
        variables: record.variables,
        range: record.range,
        resolution: record.resolution,
        zLabel: typeof record.zLabel === "string"
          ? record.zLabel
          : typeof record.z_label === "string"
            ? record.z_label
            : undefined,
        colorBy: typeof record.colorBy === "string"
          ? record.colorBy
          : typeof record.color_by === "string"
            ? record.color_by
            : undefined,
        mode: typeof record.mode === "string" ? record.mode : undefined,
        interactive: record.interactive,
        renderer: typeof record.renderer === "string" ? record.renderer : undefined,
        cacheKey: typeof record.cacheKey === "string"
          ? record.cacheKey
          : typeof record.cache_key === "string"
            ? record.cache_key
            : undefined,
        caption: typeof record.caption === "string" ? record.caption : undefined,
        error: record.error,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "svg" || type === "vector" || type === "diagram") {
    return buildAssistantSvgBlock(
      {
        svg:
          typeof record.svg === "string"
            ? record.svg
            : typeof record.markup === "string"
              ? record.markup
              : typeof record.source === "string"
                ? record.source
                : typeof record.content === "string"
                  ? record.content
                  : undefined,
        url: typeof record.url === "string" ? record.url : undefined,
        title: typeof record.title === "string" ? record.title : undefined,
        caption: typeof record.caption === "string" ? record.caption : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "file") {
    return buildAssistantFileBlock(
      {
        fileName:
          typeof record.fileName === "string"
            ? record.fileName
            : typeof record.name === "string"
              ? record.name
              : "",
        mimeType: typeof record.mimeType === "string" ? record.mimeType : undefined,
        sizeBytes: typeof record.sizeBytes === "number" ? record.sizeBytes : undefined,
        documentId: typeof record.documentId === "string" ? record.documentId : undefined,
        preview: typeof record.preview === "string" ? record.preview : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "actionable") {
    const kind = String(record.kind ?? "").trim().toLowerCase();
    if (
      ![
        "approval_needed",
        "choose_device",
        "retry_option",
        "open_history",
        "restore_context",
      ].includes(kind)
    ) {
      return null;
    }
    return buildAssistantActionableBlock(
      {
        kind: kind as ElyanAssistantActionableBlock["kind"],
        title:
          typeof record.title === "string" ? record.title : "Aksiyon",
        detail:
          typeof record.detail === "string" ? record.detail : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "block_group") {
    const children = Array.isArray(record.children)
      ? record.children
          .map(parseAssistantBlock)
          .filter((item): item is AssistantMessageBlock => item != null)
      : [];
    return buildAssistantBlockGroup(children, {
      title: typeof record.title === "string" ? record.title : undefined,
      ...parseCommonMetadata(record),
    });
  }
  if (type === "document_block") {
    const rawSections = Array.isArray(record.sections) ? record.sections : [];
    const sections = rawSections
      .filter((s): s is Record<string, unknown> => s != null && typeof s === "object")
      .map((s) => ({
        heading: typeof s.heading === "string" ? s.heading : undefined,
        content: typeof s.content === "string" ? s.content : String(s.text ?? s.body ?? ""),
        level: typeof s.level === "number" ? s.level : undefined,
      }));
    return buildAssistantDocumentBlock(
      {
        title: typeof record.title === "string" ? record.title : undefined,
        sections,
        format: typeof record.format === "string" ? record.format : undefined,
        wordCount: typeof record.wordCount === "number" ? record.wordCount : undefined,
        summary: typeof record.summary === "string" ? record.summary : undefined,
        exportFormats: record.exportFormats ?? record.export_formats,
        design: record.design,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "attachment_ack") {
    return buildAssistantAttachmentAckBlock(
      {
        summary: typeof record.summary === "string" ? record.summary : "Alındı.",
        attachmentCount: typeof record.attachmentCount === "number" ? record.attachmentCount : 0,
        pageCount: typeof record.pageCount === "number" ? record.pageCount : undefined,
        chunkCount: typeof record.chunkCount === "number" ? record.chunkCount : undefined,
        hasTable: typeof record.hasTable === "boolean" ? record.hasTable : undefined,
        hasImage: typeof record.hasImage === "boolean" ? record.hasImage : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "image_analysis") {
    return buildAssistantImageAnalysisBlock(
      {
        description: typeof record.description === "string" ? record.description : "",
        detectedText: typeof record.detectedText === "string" ? record.detectedText : undefined,
        tags: Array.isArray(record.tags) ? record.tags : undefined,
        confidence: typeof record.confidence === "number" ? record.confidence : undefined,
        language: typeof record.language === "string" ? record.language : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  // Sözleşmede tanımlı ama burada özel parse case'i olmayan tipler: şemadan
  // geçiyorsa OLDUĞU GİBİ geçir. Eskiden bu tipler (connector_result,
  // reasoning_trace, clarification, goal_progress, terminal…) sessizce null'a
  // düşüyordu — inference doğru bloğu üretse bile compose zinciri onu yutuyor,
  // mobil widget hiç açılmıyordu. Ampirik kanıt: block-parity probe'unda
  // resmi buildAssistantConnectorResultBlock çıktısı bile compose'dan boş
  // dönüyordu. Şema doğrulaması korunur; geçersiz blok yine düşer.
  if (type === "connector_result") {
    const parsed = elyanAssistantConnectorResultBlockSchema.safeParse(record);
    if (!parsed.success) return null;
    return {
      ...parsed.data,
      ...withAssistantBlockDefaults("connector_result", {}, {
        visibility: normalizeVisibility(record.visibility),
        confidence: normalizeConfidence(record.confidence),
        priority: normalizePriority(record.priority),
        stableBlockId:
          normalizeBlockStableId(record.blockId) ??
          normalizeBlockStableId(record.stableBlockId),
        cacheDigest: normalizeBlockCacheDigest(record.cacheDigest),
        renderHints: normalizeRenderHints(record.renderHints) ?? {
          sectionRole: "connector_result",
          renderer: "native_connector_result",
        },
      }),
    } as AssistantMessageBlock;
  }
  if (type === "goal_progress") {
    const parsed = elyanAssistantGoalProgressBlockSchema.safeParse(record);
    if (!parsed.success) return null;
    return {
      ...parsed.data,
      ...withAssistantBlockDefaults("goal_progress", {}, {
        visibility: normalizeVisibility(record.visibility),
        confidence: normalizeConfidence(record.confidence),
        priority: normalizePriority(record.priority),
        stableBlockId:
          normalizeBlockStableId(record.blockId) ??
          normalizeBlockStableId(record.stableBlockId),
        cacheDigest: normalizeBlockCacheDigest(record.cacheDigest),
        renderHints: normalizeRenderHints(record.renderHints) ?? {
          sectionRole: "goal_progress",
        },
      }),
    } as AssistantMessageBlock;
  }
  {
    const passthrough = elyanAssistantPassthroughBlockSchema.safeParse(record);
    if (passthrough.success) {
      return {
        ...passthrough.data,
        ...withAssistantBlockDefaults(type, {}, {
          visibility: normalizeVisibility(record.visibility),
          confidence: normalizeConfidence(record.confidence),
          priority: normalizePriority(record.priority),
          stableBlockId:
            normalizeBlockStableId(record.blockId) ??
            normalizeBlockStableId(record.stableBlockId),
          cacheDigest: normalizeBlockCacheDigest(record.cacheDigest),
          renderHints: normalizeRenderHints(record.renderHints) ?? {
            sectionRole: type,
          },
        }),
      } as AssistantMessageBlock;
    }
  }
  const markdown = normalizeMarkdown(
    typeof record.markdown === "string"
      ? record.markdown
      : typeof record.text === "string"
        ? record.text
        : typeof record.content === "string"
          ? record.content
          : typeof record.body === "string"
            ? record.body
            : "",
  );
  const sanitizedMarkdown = type === "text" ? sanitizeAssistantVisibleText(markdown) : markdown;
  if (type !== "text" || !sanitizedMarkdown) {
    return null;
  }
  return {
    type: "text",
    markdown: sanitizedMarkdown,
    ...withAssistantBlockDefaults("text", {}, {
      visibility: normalizeVisibility(record.visibility),
      confidence: normalizeConfidence(record.confidence),
      priority: normalizePriority(record.priority),
      stableBlockId:
        normalizeBlockStableId(record.blockId) ??
        normalizeBlockStableId(record.stableBlockId),
      cacheDigest: normalizeBlockCacheDigest(record.cacheDigest),
      renderHints: {
        sectionRole: "detail",
        ...(normalizeRenderHints(record.renderHints) ?? {}),
      },
    }),
  };
}

/* ── Şema doğrulama + onarım katmanı ─────────────────────────────────────
 * parseAssistantBlock eksik zorunlu alanlı blokları null'a düşürür; eskiden bu
 * bloklar SESSİZCE kayboluyordu (mobilde "cevap geldi ama içerik yok" ya da
 * model metni fence içinde bıraktıysa boş gri kutu). Onarım kuralı:
 *   eksik zorunlu alan → bloğu düşür, okunabilir metin alanlarını tek bir
 *   text bloğuna çevir. Ham JSON asla kullanıcıya sızmaz; kurtarılacak metin
 *   yoksa blok tamamen atılır (boş kutu render edilmez).                     */

const SALVAGEABLE_BLOCK_TYPES = new Set([
  "chart",
  "table",
  "math",
  "latex",
  "formula",
  "equation",
  "math_surface_3d",
  "svg",
  "vector",
  "diagram",
  "document_block",
  "code",
  "image_analysis",
  "file",
  "text",
  "summary",
  "next_steps",
]);

function looksLikeRawStructuredPayload(value: string): boolean {
  const trimmed = value.trim();
  return (
    trimmed.startsWith("{") ||
    trimmed.startsWith("[") ||
    /"type"\s*:/.test(trimmed) ||
    /```(?:json)?/.test(trimmed)
  );
}

function looksLikeMarkdownTable(value: string): boolean {
  const lines = value.split("\n").map((line) => line.trim()).filter(Boolean);
  for (let i = 0; i < lines.length - 1; i += 1) {
    if (
      lines[i].startsWith("|") &&
      lines[i].endsWith("|") &&
      /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(lines[i + 1] ?? "")
    ) {
      return true;
    }
  }
  return false;
}

function countPreflightEnrichedBlocks(blocks: AssistantMessageBlock[]): number {
  return blocks.filter((block) => {
    const hints = (block as { renderHints?: unknown }).renderHints;
    if (!hints || typeof hints !== "object" || Array.isArray(hints)) {
      return false;
    }
    const record = hints as Record<string, unknown>;
    return (
      record.preflightRequired === true &&
      ["document_block", "table", "svg", "file"].includes(block.type)
    );
  }).length;
}

function salvageInvalidBlockToText(value: unknown): AssistantTextMessageBlock | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const type = String(record.type ?? "").trim().toLowerCase();
  // Meta/iç blok tipleri (status, security_decision, task_trace…) kullanıcıya
  // metin olarak da gösterilmez — sessizce düşmeleri doğru davranış.
  if (!SALVAGEABLE_BLOCK_TYPES.has(type)) {
    return null;
  }

  const parts: string[] = [];
  const seen = new Set<string>();
  for (const key of ["title", "summary", "caption", "description", "detail", "content", "markdown", "text"]) {
    const raw = record[key];
    if (typeof raw !== "string") {
      continue;
    }
    const compact = raw.replace(/\s+/g, " ").trim();
    if (!compact || compact.length > 2_400 || looksLikeRawStructuredPayload(compact)) {
      continue;
    }
    const dedupe = compact.toLowerCase();
    if (seen.has(dedupe)) {
      continue;
    }
    seen.add(dedupe);
    parts.push(compact);
  }

  const markdown = sanitizeAssistantVisibleText(parts.join("\n\n"), { fallback: "" });
  if (!markdown.trim()) {
    return null;
  }

  return {
    type: "text",
    markdown,
    ...withAssistantBlockDefaults("text", {}, {
      renderHints: {
        sectionRole: "detail",
        salvagedFromBlockType: type,
      },
    }),
  };
}

export function evaluateAssistantBlockQuality(input: {
  blocks?: unknown;
  content?: string | null | undefined;
  normalizedBlocks?: AssistantMessageBlock[];
  tablePolicy?: "forbidden" | "explicit_only";
}): AssistantBlockQualityReport {
  const rawBlocks = Array.isArray(input.blocks) ? input.blocks : [];
  const parsedOrSalvaged: AssistantMessageBlock[] = [];
  let schemaInvalidBlockCount = 0;
  let malformedStructuredJsonCount = 0;
  let rawJsonLeakPreventedCount = 0;
  let fallbackToTextCount = 0;

  for (const raw of rawBlocks) {
    const parsed = parseAssistantBlock(raw);
    if (parsed) {
      parsedOrSalvaged.push(parsed);
      if (!assistantBlockSchemaValid(parsed)) {
        schemaInvalidBlockCount += 1;
      }
      continue;
    }

    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      schemaInvalidBlockCount += 1;
      const record = raw as Record<string, unknown>;
      if (typeof record.type === "string" && record.type.trim()) {
        malformedStructuredJsonCount += 1;
      }
      if (
        Object.values(record).some(
          (value) => typeof value === "string" && looksLikeRawStructuredPayload(value),
        )
      ) {
        rawJsonLeakPreventedCount += 1;
      }
    }

    const salvaged = salvageInvalidBlockToText(raw);
    if (salvaged) {
      fallbackToTextCount += 1;
      parsedOrSalvaged.push(salvaged);
    }
  }

  const normalizedBlocks =
    input.normalizedBlocks ??
    composeAssistantMessageBlocks({
      blocks: input.blocks,
      content: input.content,
  });
  const duplicateBlockCount = countDuplicateAssistantBlocks(parsedOrSalvaged);
  const duplicateTableBlockCount = countDuplicateAssistantBlocksOfType(
    parsedOrSalvaged,
    "table",
  );
  const normalizedSchemaInvalidCount = normalizedBlocks.filter(
    (block) => !assistantBlockSchemaValid(block),
  ).length;
  schemaInvalidBlockCount += normalizedSchemaInvalidCount;

  const unrequestedTableBlockCount =
    input.tablePolicy === "forbidden"
      ? normalizedBlocks.filter((block) => block.type === "table").length
      : 0;
  const contentBlockOverlapCount =
    normalizedBlocks.some((block) => block.type === "table") &&
    looksLikeMarkdownTable(input.content ?? "")
      ? 1
      : 0;
  const documentPreflightEnrichedCount = countPreflightEnrichedBlocks(normalizedBlocks);

  const issueSet = new Set<AssistantBlockQualityIssue>();
  if (duplicateBlockCount > 0) issueSet.add("duplicate_block");
  if (schemaInvalidBlockCount > 0) issueSet.add("schema_invalid_block");
  if (malformedStructuredJsonCount > 0) issueSet.add("malformed_structured_json");
  if (rawJsonLeakPreventedCount > 0) issueSet.add("raw_json_leak_prevented");
  if (fallbackToTextCount > 0) issueSet.add("fallback_to_text");
  if (unrequestedTableBlockCount > 0) issueSet.add("unrequested_table_block");
  if (contentBlockOverlapCount > 0) issueSet.add("content_block_overlap");
  if (documentPreflightEnrichedCount > 0) issueSet.add("document_preflight_enriched");

  const feedbackSignals: string[] = [...issueSet].filter((issue) =>
    [
      "unrequested_table_block",
      "malformed_structured_json",
      "raw_json_leak_prevented",
      "fallback_to_text",
    ].includes(issue),
  );
  if (duplicateTableBlockCount > 0) {
    feedbackSignals.unshift("duplicate_table_block");
  } else if (duplicateBlockCount > 0) {
    feedbackSignals.unshift("duplicate_block");
  }
  const penalty =
    duplicateBlockCount * 8 +
    schemaInvalidBlockCount * 12 +
    malformedStructuredJsonCount * 10 +
    rawJsonLeakPreventedCount * 8 +
    fallbackToTextCount * 6 +
    unrequestedTableBlockCount * 14 +
    contentBlockOverlapCount * 10;

  return {
    version: "elyan_block_quality.v1",
    score: Math.max(0, Math.min(100, 100 - penalty)),
    issues: [...issueSet],
    feedbackSignals,
    blockTypes: normalizedBlocks.map((block) => block.type),
    metrics: {
      inputBlockCount: rawBlocks.length,
      normalizedBlockCount: normalizedBlocks.length,
      duplicateBlockCount,
      duplicateTableBlockCount,
      schemaInvalidBlockCount,
      malformedStructuredJsonCount,
      rawJsonLeakPreventedCount,
      fallbackToTextCount,
      unrequestedTableBlockCount,
      contentBlockOverlapCount,
      documentPreflightEnrichedCount,
    },
  };
}

function parseAssistantBlocksWithSalvage(blocks: unknown): AssistantMessageBlock[] {
  if (!Array.isArray(blocks)) {
    return [];
  }
  const output: AssistantMessageBlock[] = [];
  for (const raw of blocks) {
    const parsed = parseAssistantBlock(raw);
    if (parsed) {
      output.push(
        withCanonicalAssistantBlockEnvelope(
          parsed as Record<string, unknown>,
        ) as AssistantMessageBlock,
      );
      continue;
    }
    const salvaged = salvageInvalidBlockToText(raw);
    if (salvaged) {
      output.push(
        withCanonicalAssistantBlockEnvelope(
          salvaged as Record<string, unknown>,
        ) as AssistantMessageBlock,
      );
    }
  }
  return output;
}

function isInternalOnlyPublicBlock(block: AssistantMessageBlock): boolean {
  return ["security_decision", "reasoning_trace", "tool_trace"].includes(block.type);
}

function mergeAssistantBlocks(blocks: AssistantMessageBlock[]): AssistantMessageBlock[] {
  if (blocks.length === 0) {
    return [];
  }

  const merged: AssistantMessageBlock[] = [];
  let pendingText: string[] = [];

  const flushPendingText = () => {
    const markdown = normalizeMarkdown(pendingText.join("\n\n"));
    pendingText = [];
    if (!markdown) {
      return;
    }
    merged.push({
      type: "text",
      markdown,
      ...withAssistantBlockDefaults("text", {}, {
        renderHints: {
          sectionRole: "detail",
        },
      }),
    });
  };

  for (const block of blocks) {
    if (block.type === "text") {
      pendingText.push(block.markdown);
      continue;
    }

    flushPendingText();
    merged.push(block);
  }

  flushPendingText();
  return merged;
}

export function buildAssistantMessageBlocks(
  content: string | null | undefined,
  options: BuildAssistantBlocksOptions = {},
): AssistantTextMessageBlock[] {
  const normalized = normalizeMarkdown(content);
  if (!normalized) {
    return [];
  }
  const visibleText = sanitizeAssistantVisibleText(normalized);
  if (!visibleText) {
    return [];
  }

  if (options.streaming) {
    return [
      withCanonicalAssistantBlockEnvelope({
        type: "text" as const,
        markdown: visibleText,
        ...withAssistantBlockDefaults("text", {}, {
          renderHints: {
            tone: "streaming",
            density: "compact",
            expandable: false,
            sectionRole: "detail",
          },
        }),
      }) as unknown as AssistantTextMessageBlock,
    ];
  }

  return [
    withCanonicalAssistantBlockEnvelope({
      type: "text",
      markdown: visibleText,
      ...withAssistantBlockDefaults("text", {}, {
        renderHints: {
          tone: "neutral",
          density: visibleText.length > 260 ? "regular" : "compact",
          expandable: visibleText.length > 480,
          sectionRole: "detail",
        },
      }),
    }) as unknown as AssistantTextMessageBlock,
  ];
}

function canonicalizeAssistantBlocks(
  blocks: AssistantMessageBlock[],
): AssistantMessageBlock[] {
  return blocks.map(
    (block) =>
      withCanonicalAssistantBlockEnvelope(
        block as Record<string, unknown>,
      ) as AssistantMessageBlock,
  );
}

export function composeAssistantMessageBlocks(input: {
  blocks?: unknown;
  content?: string | null | undefined;
  streaming?: boolean;
}): AssistantMessageBlock[] {
  const normalizedBlocks = parseAssistantBlocksWithSalvage(input.blocks);
  const textBlocks = buildAssistantMessageBlocks(input.content, {
    streaming: input.streaming,
  });
  if (normalizedBlocks.length === 0) {
    return textBlocks;
  }
  const existingTypedBlocks = normalizedBlocks.filter((block) => block.type !== "text");
  const existingTextBlocks = normalizedBlocks.filter(
    (block): block is AssistantTextMessageBlock => block.type === "text",
  );
  return canonicalizeAssistantBlocks(
    dedupeAssistantBlocks(
      mergeAssistantBlocks([
        ...existingTypedBlocks,
        ...(textBlocks.length > 0 ? textBlocks : existingTextBlocks),
      ]),
    ),
  );
}

export function normalizeAssistantMessageBlocks(input: {
  blocks?: unknown;
  content?: string | null | undefined;
  streaming?: boolean;
}): AssistantMessageBlock[] {
  const normalizedBlocks = parseAssistantBlocksWithSalvage(input.blocks);
  if (normalizedBlocks.length > 0) {
    if (normalizedBlocks.length === 1 && normalizedBlocks[0]?.type === "text") {
      return canonicalizeAssistantBlocks(normalizedBlocks);
    }
    return canonicalizeAssistantBlocks(
      dedupeAssistantBlocks(mergeAssistantBlocks(normalizedBlocks)),
    );
  }
  return buildAssistantMessageBlocks(input.content, {
    streaming: input.streaming,
  });
}

function buildAssistantRenderContract(blocks: AssistantMessageBlock[]): AssistantRenderContract {
  const visibleBlockTypes = blocks
    .filter(
      (block) =>
        (block as { visibility?: unknown }).visibility !==
        "assistant_internal_by_default",
    )
    .map((block) => block.type);

  return {
    version: "elyan_blocks.v2",
    mode: "block_first",
    canonicalSurface: "blocks",
    legacyContent: "none",
    hasVisibleBlocks: visibleBlockTypes.length > 0,
    visibleBlockTypes,
    textIsBlockWrapped: blocks.some((block) => block.type === "text"),
  };
}

export function validateAssistantBlockContract(input: {
  blocks?: unknown;
  content?: string | null | undefined;
  streaming?: boolean;
  mode?: AssistantBlockContractValidationMode;
  tablePolicy?: "forbidden" | "explicit_only";
  qualityBlocks?: unknown;
}): AssistantBlockContractValidationResult {
  const blocks =
    input.mode === "normalize"
      ? normalizeAssistantMessageBlocks(input)
      : composeAssistantMessageBlocks(input);
  const blockQuality = evaluateAssistantBlockQuality({
    blocks: input.qualityBlocks ?? input.blocks,
    content: input.content,
    normalizedBlocks: blocks,
    tablePolicy: input.tablePolicy,
  });

  return {
    version: "elyan_blocks.v2",
    blocks,
    renderContract: buildAssistantRenderContract(blocks),
    blockQuality,
    modelFeedbackSignals: blockQuality.feedbackSignals,
  };
}

export function withAssistantBlocksMetadata(
  metadata: Record<string, unknown> | undefined,
  input: {
    content?: string | null | undefined;
    blocks?: unknown;
    streaming?: boolean;
    tablePolicy?: "forbidden" | "explicit_only";
  },
) {
  const next = {
    ...(metadata && typeof metadata === "object" && !Array.isArray(metadata)
      ? metadata
      : {}),
  } as Record<string, unknown>;
  const validation = validateAssistantBlockContract(input);
  const blocks = validation.blocks;
  if (blocks.length > 0) {
    next.blocks = blocks;
  } else {
    delete next.blocks;
  }
  next.renderContract = validation.renderContract;
  next.blockQuality = validation.blockQuality;
  next.blockSchemaValid = validation.blockQuality.metrics.schemaInvalidBlockCount === 0;
  next.blockFallbackUsed = validation.blockQuality.metrics.fallbackToTextCount > 0;
  if (validation.modelFeedbackSignals.length > 0) {
    next.modelFeedbackSignals = validation.modelFeedbackSignals;
  } else {
    delete next.modelFeedbackSignals;
  }
  return next;
}

export function shapeAssistantMessagePayload<
  T extends {
    role?: unknown;
    content?: unknown;
    metadata?: unknown;
  },
>(message: T) {
  const isAssistant = String(message.role ?? "").trim().toLowerCase() === "assistant";
  if (!isAssistant) {
    return message;
  }

  const metadata =
    message.metadata && typeof message.metadata === "object" && !Array.isArray(message.metadata)
      ? (message.metadata as Record<string, unknown>)
      : undefined;
  // Çağıranlar tipli blokları (document_block, table, chart, code…) TOP-LEVEL
  // `blocks` alanında geçiyor (service.ts message.completed). Eskiden yalnız
  // metadata.blocks okunuyordu → metadata yoksa TÜM tipli bloklar düşüp content
  // tek bir `text` bloğuna indirgeniyordu. Mobilde "widget hiç açılmıyor"
  // semptomunun kök sebebi buydu. Önce top-level blocks, yoksa metadata.blocks.
  const topLevelBlocks = (message as Record<string, unknown>).blocks;
  const sourceBlocks = Array.isArray(topLevelBlocks) ? topLevelBlocks : metadata?.blocks;
  const blocks = composeAssistantMessageBlocks({
    blocks: sourceBlocks,
    content: typeof message.content === "string" ? message.content : "",
    streaming: String((message as Record<string, unknown>).status ?? "").trim().toLowerCase() === "running",
  });
  const publicBlocks = blocks.filter((block) => !isInternalOnlyPublicBlock(block));
  const payload = { ...(message as Record<string, unknown>) };
  delete payload.content;
  if (publicBlocks.length > 0) {
    payload.blocks = publicBlocks;
  } else {
    delete payload.blocks;
  }
  return payload as Omit<T, "content"> & { blocks?: AssistantMessageBlock[] };
}
