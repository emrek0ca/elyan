import { createHash } from "node:crypto";
import {
  elyanAssistantBlockSourceValues,
  elyanSourceWidgetBlockTypeValues,
} from "../../contracts/assistant-block-schemas.js";
import { isDispatchWidgetType } from "../../contracts/assistant-block-schemas.js";

export const ELYAN_ASSISTANT_BLOCK_VERSION = 1 as const;

export const sourceWidgetBlockTypeValues = elyanSourceWidgetBlockTypeValues;

export type SourceWidgetBlockType =
  (typeof sourceWidgetBlockTypeValues)[number];

const sourceWidgetBlockTypes = new Set<string>(sourceWidgetBlockTypeValues);
const assistantBlockSources = new Set<string>(elyanAssistantBlockSourceValues);

const sourceAliases: Record<string, string> = {
  connector: "mcp",
  email: "gmail",
  google_calendar: "calendar",
  google_drive: "drive",
  linear: "mcp",
  mail: "gmail",
};

const envelopeKeys = new Set([
  "type",
  "version",
  "blockId",
  "stableBlockId",
  "source",
  "visibility",
  "confidence",
  "priority",
  "cacheDigest",
  "isRenderable",
  "renderHints",
  "data",
]);

export type CanonicalAssistantBlockEnvelope = Record<string, unknown> & {
  type: string;
  version: typeof ELYAN_ASSISTANT_BLOCK_VERSION;
  blockId: string;
  stableBlockId: string;
  source: string;
  visibility: "user_visible" | "assistant_internal_by_default";
  renderHints: Record<string, unknown>;
  data: Record<string, unknown>;
  cacheDigest: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stableJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stableJsonValue);
  }
  if (!isRecord(value)) {
    return value;
  }
  return Object.keys(value)
    .sort()
    .reduce<Record<string, unknown>>((output, key) => {
      output[key] = stableJsonValue(value[key]);
      return output;
    }, {});
}

export function assistantBlockDigest(input: {
  type: string;
  source: string;
  data: Record<string, unknown>;
  renderHints?: Record<string, unknown>;
  visibility?: unknown;
  priority?: unknown;
  confidence?: unknown;
}): string {
  return createHash("sha256")
    .update(JSON.stringify(stableJsonValue(input)))
    .digest("hex")
    .slice(0, 16);
}

function normalizeIdentifier(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value
    .trim()
    .replace(/[^a-zA-Z0-9:._-]+/g, "_")
    .slice(0, 160);
  return normalized.length >= 3 ? normalized : null;
}

function normalizeSource(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "_")
    .slice(0, 80);
  if (!normalized) return null;
  const canonical = sourceAliases[normalized] ?? normalized;
  return assistantBlockSources.has(canonical) ? canonical : "mcp";
}

function inferSource(
  type: string,
  block: Record<string, unknown>,
  renderHints: Record<string, unknown>,
): string {
  const explicit =
    normalizeSource(block.source) ??
    normalizeSource(block.provider) ??
    normalizeSource(renderHints.source);
  if (explicit) return explicit;
  if (type === "mail_list" || type === "mail_detail") return "gmail";
  if (type === "calendar_agenda") return "calendar";
  if (type === "drive_files") return "drive";
  if (type === "notion_page") return "notion";
  if (type === "github_activity") return "github";
  if (type === "slack_messages") return "slack";
  if (type === "web_search") return "web";
  if (
    type === "attachment_ack" ||
    type === "attachment_context" ||
    type === "image_analysis"
  ) {
    return "user_attachment";
  }
  if (
    type === "document_block" ||
    type === "document_block_skeleton" ||
    type === "file" ||
    type === "pdf_generate" ||
    type === "pdf_viewer"
  ) {
    return "document";
  }
  if (
    type === "automation" ||
    type === "capability_unavailable" ||
    type === "desktop_suggestion" ||
    type === "status" ||
    isDispatchWidgetType(type) ||
    type === "terminal"
  ) {
    return "runtime";
  }
  if (type === "connector_result") return "legacy";
  return "elyan";
}

function extractData(block: Record<string, unknown>): Record<string, unknown> {
  const isCanonicalEnvelope =
    block.version === ELYAN_ASSISTANT_BLOCK_VERSION ||
    typeof block.blockId === "string" ||
    isSourceWidgetBlockType(block.type);
  if (isCanonicalEnvelope && isRecord(block.data)) {
    return { ...block.data };
  }
  const data: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(block)) {
    // Legacy chart blocks already use a top-level `data` payload. Preserve it
    // inside the new envelope instead of mistaking it for the envelope itself.
    if (key === "data") {
      data.data = value;
      continue;
    }
    if (!envelopeKeys.has(key)) {
      data[key] = value;
    }
  }
  return data;
}

function blockSlotIdentity(
  type: string,
  source: string,
  data: Record<string, unknown>,
  renderHints: Record<string, unknown>,
  digest: string,
): string {
  const explicitDataIdentity =
    normalizeIdentifier(data.threadId) ??
    normalizeIdentifier(data.messageId) ??
    normalizeIdentifier(data.pageId) ??
    normalizeIdentifier(data.queryId) ??
    normalizeIdentifier(data.id);
  if (explicitDataIdentity) {
    return `${source}:${type}:${explicitDataIdentity}`;
  }
  const slot =
    normalizeIdentifier(renderHints.slot) ??
    normalizeIdentifier(renderHints.sectionRole);
  if (slot && !["table", "chart", "file", "artifact"].includes(type)) {
    return `${source}:${type}:${slot}`;
  }
  return `${source}:${type}:${digest}`;
}

/**
 * Adds the canonical additive envelope without removing legacy top-level data.
 * Old clients keep reading the flat fields; new clients read `data`.
 */
export function withCanonicalAssistantBlockEnvelope(
  value: Record<string, unknown>,
): CanonicalAssistantBlockEnvelope {
  const type = String(value.type ?? "").trim().toLowerCase() || "unknown";
  const renderHints: Record<string, unknown> = isRecord(value.renderHints)
    ? { ...value.renderHints }
    : { sectionRole: type };
  const source = inferSource(type, value, renderHints);
  const data = extractData(value);
  const visibility =
    value.visibility === "assistant_internal_by_default"
      ? "assistant_internal_by_default"
      : "user_visible";
  const computedDigest = assistantBlockDigest({
    type,
    source,
    data,
    renderHints,
    visibility,
    priority: value.priority,
    confidence: value.confidence,
  });
  // Digest is always recomputed from canonical data. Trusting a legacy digest
  // would preserve the historical connector bug where payload changes were not
  // represented in the cache key.
  const cacheDigest = computedDigest;
  const explicitId =
    normalizeIdentifier(value.blockId) ?? normalizeIdentifier(value.stableBlockId);
  const blockId =
    explicitId ?? blockSlotIdentity(type, source, data, renderHints, computedDigest);
  return {
    ...value,
    version: ELYAN_ASSISTANT_BLOCK_VERSION,
    blockId,
    // Preserve the legacy identity alias until all stored histories migrate.
    stableBlockId: normalizeIdentifier(value.stableBlockId) ?? blockId,
    source,
    visibility,
    renderHints,
    // Additive contract: legacy chart blocks carry their point ARRAY at the
    // top-level `data` key. Overwriting it with the canonical payload record
    // buried the sampled points under `data.data` and broke every flat reader
    // (mobile chart preview showed no data). Digest/blockId are still computed
    // from the canonical payload; the flat array stays readable in place.
    data: Array.isArray(value.data) ? value.data : data,
    cacheDigest,
  } as CanonicalAssistantBlockEnvelope;
}

/**
 * Makes an enveloped block readable by the existing flat-field parsers.
 * Envelope metadata wins over any same-named key inside `data`.
 */
export function hydrateLegacyAssistantBlockInput(
  value: Record<string, unknown>,
): Record<string, unknown> {
  if (!isRecord(value.data)) return value;
  const { data, ...envelope } = value;
  return {
    ...data,
    ...envelope,
    // `chart` historically named its own payload field `data`; keep that
    // field visible to the legacy parser after unwrapping the envelope.
    ...(Object.prototype.hasOwnProperty.call(data, "data")
      ? { data: data.data }
      : {}),
    type: String(value.type ?? data.type ?? "").trim().toLowerCase(),
  };
}

export function isSourceWidgetBlockType(
  value: unknown,
): value is SourceWidgetBlockType {
  return typeof value === "string" && sourceWidgetBlockTypes.has(value);
}
