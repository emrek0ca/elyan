import { createHash } from "node:crypto";
import {
  containsProtectedElyanDisclosure,
  ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT,
} from "../../lib/elyan-public-identity.js";
import type {
  ElyanAssistantActionableBlock,
  ElyanAssistantBlock,
  ElyanAssistantChartBlock,
  ElyanAssistantCodeBlock,
  ElyanAssistantFileBlock,
  ElyanAssistantBlockGroupBlock,
  ElyanAssistantInfoCardBlock,
  ElyanAssistantNextStepsBlock,
  ElyanAssistantStatusBlock,
  ElyanAssistantSummaryBlock,
  ElyanAssistantTableBlock,
  ElyanAssistantTextBlock,
  ElyanAssistantWebSearchBlock,
  ElyanTaskTraceBlock,
} from "../../contracts/domain.js";

export type AssistantTextMessageBlock = ElyanAssistantTextBlock;
export type AssistantMessageBlock = ElyanAssistantBlock;

type BuildAssistantBlocksOptions = {
  streaming?: boolean;
};

type AssistantBlockVisibility = "user_visible" | "assistant_internal_by_default";

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
  /^(?:analyze user input|check attachment context|system prompt|developer message|looking at the system prompt|we need to|user says|the user says|the user is|the user wants|language:|given the attachment context|attachment context(?: shows| provided)?|ocr\/summary text|page \d+ content|summary\/content|detected text|extracted text|visible text|the ocr output|context:|i started answering|prompt continuation|analysis:|reasoning:|plan:|thinking:|<think>|<\/think>|<analysis>|<\/analysis>)/i;
const finalAnswerPrefixPattern =
  /^(?:final answer|answer|cevap|son cevap)\s*:\s*/i;
const publicProviderTopicPattern =
  /\b(openai|anthropic|groq|ollama|openrouter|gpt|llama|claude|qwen|deepseek)\b/i;
const selfImplementationDisclosurePattern =
  /\b(ben|elyan|sistemim|altyapım|altyapim|arkamda|bende)\b.{0,90}\b(openai|anthropic|groq|ollama|openrouter|gpt|llama|claude|qwen|deepseek)\b/i;
const reverseSelfImplementationDisclosurePattern =
  /\b(openai|anthropic|groq|ollama|openrouter|gpt|llama|claude|qwen|deepseek)\b.{0,90}\b(kullanıyorum|kullaniyorum|çalışıyorum|calisiyorum|tabanlıyım|tabanliyim|altyapım|altyapim|modelim|sağlayıcım|saglayicim)\b/i;
const englishSelfImplementationDisclosurePattern =
  /\b(i use|i run on|i am powered by|my provider|my underlying model|elyan runs on)\b.{0,90}\b(openai|anthropic|groq|ollama|openrouter|gpt|llama|claude|qwen|deepseek)\b/i;
const internalConfigurationDisclosurePattern =
  /\b(system prompt|developer message|sistem promptu|geliştirici mesajı|hidden instruction|gizli talimat|iç model|ic model|underlying model|provider metadata|routeDecision|selectedWorkload|token budget)\b/i;

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

function normalizeRenderHints(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? { ...(value as Record<string, unknown>) }
    : undefined;
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
  const withMeta = {
    ...payload,
    ...(options.renderHints ? { renderHints: options.renderHints } : {}),
    ...(options.confidence != null ? { confidence: options.confidence } : {}),
    ...(options.priority != null ? { priority: options.priority } : {}),
    visibility,
  };
  const cacheDigest = options.cacheDigest ?? buildCacheDigest({ type, ...withMeta });
  const stableBlockId =
    options.stableBlockId ?? `${type}_${cacheDigest}`;
  return {
    ...withMeta,
    stableBlockId,
    cacheDigest,
  };
}

function shouldRedactProtectedElyanDisclosure(
  value: string,
  options: Pick<VisibleTextSanitizerOptions, "allowPublicProviderReferences"> = {},
) {
  if (!containsProtectedElyanDisclosure(value)) {
    return false;
  }
  if (!options.allowPublicProviderReferences || !publicProviderTopicPattern.test(value)) {
    return true;
  }
  return (
    selfImplementationDisclosurePattern.test(value) ||
    reverseSelfImplementationDisclosurePattern.test(value) ||
    englishSelfImplementationDisclosurePattern.test(value) ||
    internalConfigurationDisclosurePattern.test(value)
  );
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
  if (!candidate.startsWith("{") || !candidate.endsWith("}")) {
    return null;
  }

  try {
    const parsed = JSON.parse(candidate) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return readStructuredVisibleText(parsed as Record<string, unknown>);
  } catch {
    return null;
  }
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

function looksLikeInternalAssistantLine(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return false;
  }
  const lowered = stripBulletPrefix(trimmed).toLowerCase();
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

function containsInternalAssistantSignals(value: string) {
  return value
    .split("\n")
    .some((line) => looksLikeInternalAssistantLine(line));
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
      if (looksLikeInternalAssistantLine(line)) {
        continue;
      }
      cleanedLines.push(line.replace(finalAnswerPrefixPattern, "").trimStart());
    }

    const cleaned = cleanedLines.join("\n").trim();
    if (cleaned) {
      retainedParagraphs.push(cleaned);
    }
  }

  const sanitized = retainedParagraphs.join("\n\n").trim();
  if (sanitized) {
    return shouldRedactProtectedElyanDisclosure(sanitized, options)
      ? ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT
      : sanitized;
  }

  const analysisFallback = extractAnalysisValueFallback(source);
  if (analysisFallback) {
    return shouldRedactProtectedElyanDisclosure(analysisFallback, options)
      ? ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT
      : analysisFallback;
  }

  const normalizedFallback = normalizeMarkdown(options.fallback);
  if (normalizedFallback) {
    return shouldRedactProtectedElyanDisclosure(normalizedFallback, options)
      ? ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT
      : normalizedFallback;
  }

  if (shouldRedactProtectedElyanDisclosure(source, options)) {
    return ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT;
  }
  if (containsInternalAssistantSignals(source)) {
    return "";
  }
  return source;
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

  return shouldRedactProtectedElyanDisclosure(polished, options)
    ? ELYAN_PUBLIC_MODEL_ABSTRACTION_TEXT
    : polished;
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

  return value
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
    code,
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
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantTableBlock | null {
  const columns = normalizeTableColumns(input.columns);
  const rows = normalizeTableRows(input.rows, columns.length);
  if (columns.length === 0 || rows.length === 0) {
    return null;
  }
  return {
    type: "table",
    columns,
    rows,
    ...(normalizeTextValue(input.title, 120) ? { title: normalizeTextValue(input.title, 120)! } : {}),
    ...(normalizeTextValue(input.caption, 240) ? { caption: normalizeTextValue(input.caption, 240)! } : {}),
    ...withAssistantBlockDefaults("table", {}, {
      priority: options.priority ?? 1,
      renderHints: {
        sectionRole: "data_table",
        density: "regular",
        ...(options.renderHints ?? {}),
      },
      ...options,
    }),
  };
}

export function buildAssistantChartBlock(
  input: {
    chartType: ElyanAssistantChartBlock["chartType"];
    labels: unknown;
    values: unknown;
    title?: string | null;
    caption?: string | null;
  },
  options: AssistantBlockCommon = {},
): ElyanAssistantChartBlock | null {
  const labels = normalizeStringList(input.labels, {
    min: 1,
    max: 24,
    itemMaxLength: 120,
  });
  const values = Array.isArray(input.values)
    ? input.values
        .map((value) => (typeof value === "number" && Number.isFinite(value) ? value : null))
        .filter((value): value is number => value != null)
        .slice(0, labels.length)
    : [];
  if (
    !["bar", "line", "pie"].includes(input.chartType) ||
    labels.length === 0 ||
    values.length === 0
  ) {
    return null;
  }
  return {
    type: "chart",
    chartType: input.chartType,
    labels: labels.slice(0, values.length),
    values,
    ...(normalizeTextValue(input.title, 120) ? { title: normalizeTextValue(input.title, 120)! } : {}),
    ...(normalizeTextValue(input.caption, 240) ? { caption: normalizeTextValue(input.caption, 240)! } : {}),
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

function isTaskTraceBlock(block: AssistantMessageBlock): block is ElyanTaskTraceBlock {
  return block.type === "task_trace";
}

function parseTaskTraceBlock(value: Record<string, unknown>): ElyanTaskTraceBlock | null {
  const taskId = String(value.taskId ?? "").trim();
  const status = String(value.status ?? "").trim().toLowerCase();
  const title = String(value.title ?? "").trim();
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
        !["pending", "running", "completed", "failed", "skipped"].includes(stepStatus)
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
        ...(typeof record.startedAt === "string" && record.startedAt.trim()
          ? { startedAt: record.startedAt.trim() }
          : {}),
        ...(typeof record.completedAt === "string" && record.completedAt.trim()
          ? { completedAt: record.completedAt.trim() }
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

  return {
    type: "task_trace",
    taskId,
    status: status as ElyanTaskTraceBlock["status"],
    title,
    steps,
    ...withAssistantBlockDefaults("task_trace", {}, {
      stableBlockId:
        typeof value.stableBlockId === "string" && value.stableBlockId.trim()
          ? value.stableBlockId.trim()
          : undefined,
      visibility: normalizeVisibility(value.visibility),
      confidence: normalizeConfidence(value.confidence),
      priority: normalizePriority(value.priority),
      cacheDigest:
        typeof value.cacheDigest === "string" && value.cacheDigest.trim()
          ? value.cacheDigest.trim()
          : undefined,
      renderHints: normalizeRenderHints(value.renderHints),
    }),
  };
}

function parseCommonMetadata(value: Record<string, unknown>): AssistantBlockCommon {
  return {
    stableBlockId:
      typeof value.stableBlockId === "string" && value.stableBlockId.trim()
        ? value.stableBlockId.trim()
        : undefined,
    visibility: normalizeVisibility(value.visibility),
    confidence: normalizeConfidence(value.confidence),
    priority: normalizePriority(value.priority),
    cacheDigest:
      typeof value.cacheDigest === "string" && value.cacheDigest.trim()
        ? value.cacheDigest.trim()
        : undefined,
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

function parseAssistantBlock(value: unknown): AssistantMessageBlock | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const record = value as Record<string, unknown>;
  const type = String(record.type ?? "").trim().toLowerCase();
  if (type === "task_trace") {
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
        caption: typeof record.caption === "string" ? record.caption : undefined,
      },
      parseCommonMetadata(record),
    );
  }
  if (type === "chart") {
    const chartType = String(record.chartType ?? record.kind ?? "").trim().toLowerCase();
    if (!["bar", "line", "pie"].includes(chartType)) {
      return null;
    }
    return buildAssistantChartBlock(
      {
        chartType: chartType as ElyanAssistantChartBlock["chartType"],
        labels: record.labels,
        values: record.values,
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
        typeof record.stableBlockId === "string" && record.stableBlockId.trim()
          ? record.stableBlockId.trim()
          : undefined,
      cacheDigest:
        typeof record.cacheDigest === "string" && record.cacheDigest.trim()
          ? record.cacheDigest.trim()
          : undefined,
      renderHints: {
        sectionRole: "detail",
        ...(normalizeRenderHints(record.renderHints) ?? {}),
      },
    }),
  };
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
      {
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
      },
    ];
  }

  return [
    {
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
    },
  ];
}

export function composeAssistantMessageBlocks(input: {
  blocks?: unknown;
  content?: string | null | undefined;
  streaming?: boolean;
}): AssistantMessageBlock[] {
  const normalizedBlocks = Array.isArray(input.blocks)
    ? input.blocks
        .map(parseAssistantBlock)
        .filter((value): value is AssistantMessageBlock => value != null)
    : [];
  const textBlocks = buildAssistantMessageBlocks(input.content, {
    streaming: input.streaming,
  });
  if (normalizedBlocks.length === 0) {
    return textBlocks;
  }
  const existingVisibleBlocks = normalizedBlocks.filter((block) => block.type !== "text");
  return mergeAssistantBlocks([
    ...existingVisibleBlocks,
    ...(textBlocks.length > 0
      ? textBlocks
      : normalizedBlocks.filter(
          (block): block is AssistantTextMessageBlock => block.type === "text",
        )),
  ]);
}

export function normalizeAssistantMessageBlocks(input: {
  blocks?: unknown;
  content?: string | null | undefined;
  streaming?: boolean;
}): AssistantMessageBlock[] {
  const normalizedBlocks = Array.isArray(input.blocks)
    ? input.blocks
        .map(parseAssistantBlock)
        .filter((value): value is AssistantMessageBlock => value != null)
    : [];
  if (normalizedBlocks.length > 0) {
    return mergeAssistantBlocks(normalizedBlocks);
  }
  return buildAssistantMessageBlocks(input.content, {
    streaming: input.streaming,
  });
}

export function withAssistantBlocksMetadata(
  metadata: Record<string, unknown> | undefined,
  input: {
    content?: string | null | undefined;
    blocks?: unknown;
    streaming?: boolean;
  },
) {
  const next = {
    ...(metadata && typeof metadata === "object" && !Array.isArray(metadata)
      ? metadata
      : {}),
  } as Record<string, unknown>;
  const blocks = composeAssistantMessageBlocks(input);
  if (blocks.length > 0) {
    next.blocks = blocks;
  } else {
    delete next.blocks;
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
  const blocks = composeAssistantMessageBlocks({
    blocks: metadata?.blocks,
    content: typeof message.content === "string" ? message.content : "",
    streaming: String((message as Record<string, unknown>).status ?? "").trim().toLowerCase() === "running",
  });
  const visibleText = blocks
    .filter((block): block is AssistantTextMessageBlock => block.type === "text")
    .map((block) => block.markdown.trim())
    .filter(Boolean)
    .join("\n\n")
    .trim();

  return {
    ...message,
    ...(visibleText ? { content: visibleText } : {}),
    ...(blocks.length > 0 ? { blocks } : {}),
  };
}
