import { createHash } from "node:crypto";
import { and, desc, eq, ilike, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { franc } from "franc-min";
import type {
  BrainScope,
  DatasetFormat,
  DatasetSource,
  DatasetStatus,
  KnowledgeSourceType,
  ModelArtifactStatus,
  TrainingJobKind,
} from "../../contracts/domain.js";
import {
  datasetManifests,
  knowledgeChunks,
  knowledgeDocuments,
  learningEvents,
  devices,
  modelArtifacts,
  runtimeConnections,
  trainingJobs,
} from "../../db/schema.js";
import { badRequest, conflict, forbidden, notFound } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import { getSharedBrainTargetDevice, listUserDevices } from "../devices/service.js";
import { buildElyanModelLearningPolicy } from "./elyan-model-learning-policy.js";
import { buildElyanModelProviderPlan } from "./elyan-model-provider-plan.js";
import { probeSharedBrainInference } from "./inference.js";
import { getBrainLatencySummary, type BrainLatencySummary } from "./latency-summary.js";
import { resolveSharedBrainModel } from "./model-resolution.js";
import { buildGroqModelCatalog } from "./groq-models.js";
import { buildBrainProfileSections } from "./profile-sections.js";
import {
  assertAttachmentQuotaAllowedFromUsage,
  getTrialQuotaPolicy,
  getTrialQuotaUsage,
  resolveUsageIdentityContext,
} from "../quota/service.js";
import { SHARED_TRAINING_PLAN } from "./bootstrap.js";
import { getNeuralBrainReadiness } from "./neural-readiness.js";
import {
  BRAIN_QUALITY_GATE_THRESHOLDS,
  evaluateBrainPromotionEligibility,
  evaluateBrainQueueQualityGate,
} from "./quality-gate.js";
import {
  getRetrievalStatus,
  indexKnowledgeChunksForDocument,
  searchKnowledge as searchKnowledgeWithMode,
} from "./retrieval.js";
import {
  getBrainMemoryById,
  getBrainMemoryStatus,
  listBrainMemory,
  restoreBrainMemory,
  searchBrainMemory,
  setBrainMemoryContest,
  setBrainMemoryPinning,
  softDeleteBrainMemory,
  updateBrainMemory,
} from "./memory.js";
import { selectSharedBrainRuntime } from "./runtime.js";
import { isCompleteReadyBrainModelArtifact, type SharedBrainSelection } from "./selection.js";
import {
  ELYAN_CONSTITUTION_GATE_READY,
  ELYAN_CONSTITUTION_VERSION,
  ELYAN_PROMPT_PROFILE_VERSION,
  constitutionRuleCount,
  listGateEnforcedRuleIds,
} from "./constitution.js";
import { getApprovedCorrectionDatasetState, getLatestBrainBenchmarkSummary } from "./review.js";
import { getSharedBrainWorkloadProfile } from "./workloads.js";
import { getPublicSkillCatalog } from "../skills/registry.js";
import { getBrainCorpusReadinessSummary } from "./corpus.js";
import { encryptJson } from "../../lib/crypto-seal.js";
import { normalizeLocalDerivedMetadata } from "../../lib/derived-data.js";
import { buildMemoryProfileSnapshot } from "../../core/understanding/memory-profile.js";
import { recordUsageLedgerEntry } from "../billing/usage-ledger.js";
import {
  invalidateBrainProfileCache,
  readBrainProfileCache,
  writeBrainProfileCache,
} from "./profile-cache.js";

const KNOWLEDGE_SUMMARY_MAX_CHARS = 280;
const KNOWLEDGE_CHUNK_MAX_CHARS = 900;
const SHARED_TRAINING_BACKEND = "pytorch";
const SHARED_TRAINING_ADAPTER_STRATEGY = "lora";
const SHARED_TRAINING_ADAPTER_MODE = "qlora";

function compactText(value: string, maxLength?: number): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return maxLength ? compact.slice(0, maxLength) : compact;
}

function normalizeLanguageTag(value: string): string | null {
  const compact = compactText(value).toLowerCase();
  if (!compact) {
    return null;
  }

  const mapping: Record<string, string> = {
    tur: "tr",
    eng: "en",
    fra: "fr",
    deu: "de",
    spa: "es",
    ita: "it",
    por: "pt",
    rus: "ru",
    ara: "ar",
    nld: "nl",
    pol: "pl",
    hun: "hu",
    jpn: "ja",
    kor: "ko",
    cmn: "zh",
  };

  if (mapping[compact]) {
    return mapping[compact];
  }

  if (/^[a-z]{2,3}$/.test(compact)) {
    return compact;
  }

  return null;
}

function detectLanguageTags(text: string): string[] {
  const compact = compactText(text, 20_000);
  if (!compact) {
    return [];
  }

  const detected = normalizeLanguageTag(franc(compact));
  if (detected) {
    return [detected];
  }

  if (/[çğıöşüÇĞİÖŞÜ]/.test(compact) || /\b(ve|ile|ama|için|ben|sen|kullanıcı|öğret|geliştirici|dil|boy)\b/i.test(compact)) {
    return ["tr"];
  }

  return [];
}

function readNumberMetadata(metadata: unknown, key: string): number | null {
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return null;
  }

  const value = (metadata as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeLanguageTags(tags: string[] | undefined, text: string): string[] {
  const requested = (tags ?? [])
    .map((tag) => normalizeLanguageTag(tag))
    .filter((tag): tag is string => Boolean(tag));
  const detected = detectLanguageTags(text);
  return [...new Set([...requested, ...detected])].slice(0, 4);
}

const knowledgeSensitivePatterns = [
  /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/gi,
  /\b(password|passwd|secret|token|api[_ -]?key|bearer|credential|private[_ -]?key)\b[^\n]*/gi,
  /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/gi,
  /(?:\/Users\/|\/home\/|C:\\Users\\)[^\s]+/gi,
  /\b\d{3}-\d{2}-\d{4}\b/g,
  /\b\d{13,19}\b/g,
];

function isPrivateSourceUri(value: string): boolean {
  const normalized = value.trim();
  return (
    normalized.startsWith("file:") ||
    normalized.startsWith("content:") ||
    normalized.startsWith("smb:") ||
    normalized.startsWith("afp:") ||
    /(?:\/Users\/|\/home\/|C:\\Users\\)/i.test(normalized)
  );
}

function redactSensitiveKnowledgeText(value: string): string {
  let redacted = compactText(value, 200_000);
  for (const pattern of knowledgeSensitivePatterns) {
    redacted = redacted.replace(pattern, "[redacted]");
  }
  return compactText(redacted, 200_000);
}

function maybeSealPrivateKnowledgePayload(app: FastifyInstance, payload: Record<string, unknown>): Record<string, unknown> {
  const tokenKey = String(app.config.TOKEN_ENCRYPTION_KEY ?? "").trim();
  if (!tokenKey) {
    return {
      mode: "hashed",
      sha256: createHash("sha256").update(JSON.stringify(payload)).digest("hex"),
    };
  }

  try {
    return {
      mode: "sealed",
      encryptedPayload: encryptJson(app.config, payload),
    };
  } catch {
    return {
      mode: "hashed",
      sha256: createHash("sha256").update(JSON.stringify(payload)).digest("hex"),
    };
  }
}

function sanitizeKnowledgeMetadata(
  app: FastifyInstance,
  input: {
    metadata: Record<string, unknown>;
    sourceUri?: string;
    title: string;
    summary: string;
  },
): Record<string, unknown> {
  const metadata = { ...input.metadata };
  const rawText =
    typeof metadata.originalText === "string"
      ? metadata.originalText
      : typeof metadata.rawText === "string"
        ? metadata.rawText
        : typeof metadata.sourceText === "string"
          ? metadata.sourceText
          : null;

  delete metadata.originalText;
  delete metadata.rawText;
  delete metadata.sourceText;

  if (rawText) {
    metadata.privatePayload = maybeSealPrivateKnowledgePayload(app, {
      title: input.title,
      summary: input.summary,
      rawText,
    });
  }

  if (input.sourceUri) {
    if (isPrivateSourceUri(input.sourceUri)) {
      metadata.privateSourceUri = maybeSealPrivateKnowledgePayload(app, {
        sourceUri: input.sourceUri,
      });
    } else {
      metadata.sourceUri = input.sourceUri;
    }
  }

  return normalizeLocalDerivedMetadata({
    ...metadata,
    privacyBoundary: "redacted_or_sealed",
  });
}

function assertCreatableScope(scope: BrainScope): BrainScope {
  if (scope === "shared") {
    throw forbidden("Elyan brain resources can only be promoted by a controlled server-side workflow");
  }

  return scope;
}

function normalizeRequiredArtifactField(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();

  if (!normalized) {
    throw badRequest("Ready model artifacts require storageUri, checksum, baseModel, and adapterKind");
  }

  return normalized;
}

async function getActiveKnowledgeCorpusSummary(app: FastifyInstance) {
  if (typeof (app.db as { execute?: unknown }).execute !== "function") {
    return {
      mode: "shared_global",
      readyDocuments: 0,
      readyDatasets: 0,
      latestDocumentUpdatedAt: null,
      latestDatasetUpdatedAt: null,
    };
  }

  const [documentCounts, datasetCounts] = await Promise.all([
    app.db
      .select({
        readyDocuments: sql<number>`count(*) filter (where ${knowledgeDocuments.status} = 'ready' and ${knowledgeDocuments.scope} = 'shared')`,
        latestDocumentUpdatedAt: sql<Date | null>`max(${knowledgeDocuments.updatedAt}) filter (where ${knowledgeDocuments.status} = 'ready' and ${knowledgeDocuments.scope} = 'shared')`,
      })
      .from(knowledgeDocuments),
    app.db
      .select({
        readyDatasets: sql<number>`count(*) filter (
          where ${datasetManifests.status} = 'ready'
            and ${datasetManifests.scope} = 'shared'
            and ${datasetManifests.source} = 'document_import'
            and ${datasetManifests.format} = 'document_corpus'
        )`,
        latestDatasetUpdatedAt: sql<Date | null>`max(${datasetManifests.updatedAt}) filter (
          where ${datasetManifests.status} = 'ready'
            and ${datasetManifests.scope} = 'shared'
            and ${datasetManifests.source} = 'document_import'
            and ${datasetManifests.format} = 'document_corpus'
        )`,
      })
      .from(datasetManifests),
  ]);

  return {
    mode: "shared_global",
    readyDocuments: Number(documentCounts[0]?.readyDocuments ?? 0),
    readyDatasets: Number(datasetCounts[0]?.readyDatasets ?? 0),
    latestDocumentUpdatedAt: documentCounts[0]?.latestDocumentUpdatedAt?.toISOString() ?? null,
    latestDatasetUpdatedAt: datasetCounts[0]?.latestDatasetUpdatedAt?.toISOString() ?? null,
  };
}

function assertReadyModelArtifactIntegrity(input: {
  status: ModelArtifactStatus;
  storageUri?: string | null;
  checksum?: string | null;
  baseModel: string;
  adapterKind: string;
}) {
  if (input.status !== "ready") {
    return;
  }

  normalizeRequiredArtifactField(input.storageUri);
  normalizeRequiredArtifactField(input.checksum);
  normalizeRequiredArtifactField(input.baseModel);
  normalizeRequiredArtifactField(input.adapterKind);
}

function estimateTokenCount(text: string): number {
  const compact = compactText(text);
  return compact ? Math.max(1, Math.ceil(compact.length / 4)) : 0;
}

function tokenize(text: string): string[] {
  return compactText(text)
    .toLowerCase()
    .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
    .split(/\s+/)
    .filter((token) => token.length >= 2)
    .slice(0, 80);
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  if (!record) {
    return null;
  }

  const value = record[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function hasApprovedCorrectionDatasetLineage(metadata: unknown): boolean {
  const record = readRecord(metadata);
  return (
    readString(record, "datasetRole") === "sft_ready_corrections_jsonl" &&
    (record?.approvedCorrectionsOnly === true || readString(record, "sourceLineage") === "approved_corrections")
  );
}

function readBoolean(record: Record<string, unknown> | null, key: string): boolean | null {
  if (!record) {
    return null;
  }
  const value = record[key];
  return typeof value === "boolean" ? value : null;
}

function readStringArray(record: Record<string, unknown> | null, key: string): string[] {
  const value = record?.[key];
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "string" ? item.trim() : ""))
        .filter(Boolean)
    : [];
}

function resolveBrainServingMode(app: FastifyInstance): "groq_primary_direct" | "fast_first_hybrid" | "fast_first_local_only" {
  const groqKey = String(app.config.GROQ_API_KEY ?? "").trim();
  const anthropicKey = String(app.config.ANTHROPIC_API_KEY ?? "").trim();
  const openAiKey = String(app.config.OPENAI_API_KEY ?? "").trim();
  const geminiKey = String(app.config.GEMINI_API_KEY ?? "").trim();
  const openRouterKey = String(app.config.OPENROUTER_API_KEY ?? "").trim();

  if (groqKey) {
    return "groq_primary_direct";
  }
  if (anthropicKey || openAiKey || geminiKey || openRouterKey) {
    return "fast_first_hybrid";
  }
  return "fast_first_local_only";
}

function isSharedKnowledgeLearningRequested(input: {
  scope: BrainScope;
  learningMode: "retrieval_only" | "shared_corpus_train";
}): boolean {
  return input.scope === "shared" || input.learningMode === "shared_corpus_train";
}

function resolveKnowledgeDocumentScope(input: {
  scope: BrainScope;
  learningMode: "retrieval_only" | "shared_corpus_train";
  isAdmin: boolean;
}): BrainScope {
  const sharedLearningRequested = isSharedKnowledgeLearningRequested(input);
  if (!sharedLearningRequested) {
    return assertCreatableScope(input.scope);
  }
  if (!input.isAdmin) {
    throw forbidden("Shared Elyan knowledge learning requires admin access");
  }
  return "shared";
}

export function scoreKnowledgeMatch(
  query: string,
  input: {
    title: string;
    content: string;
    scope: BrainScope;
    ordinal: number;
  },
): number {
  const haystack = `${input.title} ${input.content}`.toLowerCase();
  const queryTokens = tokenize(query);
  const overlap = queryTokens.reduce((count, token) => count + (haystack.includes(token) ? 1 : 0), 0);
  const exactBonus = haystack.includes(query.trim().toLowerCase()) ? 4 : 0;
  const scopeBonus = input.scope === "user" ? 1 : 0;

  return exactBonus + overlap * 2 + scopeBonus - input.ordinal * 0.01;
}

type KnowledgeDocumentChunkInput = string | Record<string, unknown>;

type KnowledgeDocumentSourceChunk = {
  content: string;
  metadata: Record<string, unknown>;
};

type KnowledgeDocumentNormalization = {
  sourceChunkCount: number;
  normalizedChunkCount: number;
  duplicateChunkCount: number;
  truncatedChunkCount: number;
  inputCharacterCount: number;
  normalizedCharacterCount: number;
  compressionRatio: number;
  structuredChunkCount: number;
  metadataSegmentCount: number;
};

const KNOWLEDGE_DOCUMENT_MAX_CHUNKS = 256;
const KNOWLEDGE_METADATA_SEGMENT_MAX = 48;

function normalizeKnowledgeChunk(value: string): string {
  return compactText(redactSensitiveKnowledgeText(value), KNOWLEDGE_CHUNK_MAX_CHARS);
}

function readMetadataString(record: Record<string, unknown> | null, keys: string[]): string | null {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }

  return null;
}

function readMetadataNumber(record: Record<string, unknown> | null, keys: string[]): number | null {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === "string") {
      const parsed = Number(value.trim());
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
  }

  return null;
}

function splitLongSegment(segment: string, maxChars: number): string[] {
  const compact = compactText(segment);
  if (!compact) {
    return [];
  }
  if (compact.length <= maxChars) {
    return [compact];
  }

  const sentenceSegments = compact
    .split(/(?<=[.!?。！？])\s+/)
    .map((value) => compactText(value))
    .filter(Boolean);

  if (sentenceSegments.length > 1) {
    return sentenceSegments.flatMap((sentence) => splitLongSegment(sentence, maxChars));
  }

  const pieces: string[] = [];
  let remaining = compact;

  while (remaining.length > maxChars) {
    let cutIndex = remaining.lastIndexOf(" ", maxChars);
    if (cutIndex < Math.floor(maxChars * 0.5)) {
      cutIndex = maxChars;
    }
    pieces.push(remaining.slice(0, cutIndex).trim());
    remaining = remaining.slice(cutIndex).trim();
  }

  if (remaining) {
    pieces.push(remaining);
  }

  return pieces;
}

function splitTextIntoChunks(text: string, maxChars = KNOWLEDGE_CHUNK_MAX_CHARS): string[] {
  const paragraphs = text
    .split(/\n{2,}/)
    .map((paragraph) => compactText(paragraph))
    .filter(Boolean);

  if (!paragraphs.length) {
    return [];
  }

  const chunks: string[] = [];
  let buffer = "";

  const flushBuffer = () => {
    if (buffer) {
      chunks.push(buffer);
      buffer = "";
    }
  };

  for (const paragraph of paragraphs) {
    const segments = splitLongSegment(paragraph, maxChars);
    for (const segment of segments) {
      if (!buffer) {
        buffer = segment;
        continue;
      }

      if (`${buffer}\n\n${segment}`.length <= maxChars) {
        buffer = `${buffer}\n\n${segment}`;
        continue;
      }

      flushBuffer();
      buffer = segment;
    }
  }

  flushBuffer();
  return chunks;
}

function readChunkText(record: Record<string, unknown>): string | null {
  return readMetadataString(record, [
    "text",
    "content",
    "summary",
    "ocrText",
    "visualSummary",
    "caption",
    "heading",
    "label",
    "description",
    "note",
    "value",
  ]);
}

function stringifyStructuredRows(rows: unknown[]): string[] {
  return rows
    .map((row) => {
      if (typeof row === "string") {
        return compactText(row);
      }

      if (Array.isArray(row)) {
        return row
          .map((cell) => compactText(String(cell ?? "")))
          .filter(Boolean)
          .join(" | ");
      }

      const record = readRecord(row);
      if (!record) {
        return "";
      }

      const text = readChunkText(record);
      if (text) {
        return text;
      }

      const cells = Array.isArray(record.cells)
        ? record.cells
        : Array.isArray(record.values)
          ? record.values
          : [];
      if (cells.length) {
        return cells
          .map((cell) => compactText(String(cell ?? "")))
          .filter(Boolean)
          .join(" | ");
      }

      const rowLabel = readMetadataString(record, ["name", "label", "title"]);
      return rowLabel ?? "";
    })
    .map((line) => compactText(line))
    .filter(Boolean)
    .slice(0, 32);
}

function buildChunkMetadata(input: {
  metadata?: Record<string, unknown>;
  sourceType?: KnowledgeSourceType;
  chunkIndex: number;
  chunkSource: "explicit_input" | "text_split" | "metadata_segment";
  sourcePath?: string;
  chunkKind?: string | null;
  pageNumber?: number | null;
  blockIndex?: number | null;
  chunkMetadata?: Record<string, unknown> | null;
  languageTags: string[];
}): Record<string, unknown> {
  const metadataRecord = readRecord(input.metadata);
  return normalizeLocalDerivedMetadata({
    chunkSource: input.chunkSource,
    chunkIndex: input.chunkIndex,
    ...(input.sourceType ? { documentSourceType: input.sourceType } : {}),
    ...(input.sourcePath ? { sourcePath: input.sourcePath } : {}),
    ...(input.chunkKind ? { chunkKind: input.chunkKind } : {}),
    ...(input.pageNumber != null ? { pageNumber: input.pageNumber } : {}),
    ...(input.blockIndex != null ? { blockIndex: input.blockIndex } : {}),
    ...(input.chunkMetadata ? { chunkMetadata: input.chunkMetadata } : {}),
    source_device_id: readMetadataString(metadataRecord, ["source_device_id", "sourceDeviceId"]) ?? undefined,
    content_hash: readMetadataString(metadataRecord, ["content_hash", "contentHash"]) ?? undefined,
    clientArtifactId: readMetadataString(metadataRecord, ["clientArtifactId"]) ?? undefined,
    mimeType: readMetadataString(metadataRecord, ["mimeType"]) ?? undefined,
    originalName: readMetadataString(metadataRecord, ["originalName"]) ?? undefined,
    summarySource: readMetadataString(metadataRecord, ["summarySource"]) ?? undefined,
    analysisMode: readMetadataString(metadataRecord, ["analysisMode", "analysis_mode"]) ?? undefined,
    extractionMode: readMetadataString(metadataRecord, ["extractionMode", "extraction_mode"]) ?? undefined,
    user_intent: readMetadataString(metadataRecord, ["user_intent", "userIntent"]) ?? undefined,
    languageTags: input.languageTags,
  });
}

function normalizeChunkInput(
  chunk: KnowledgeDocumentChunkInput,
  input: {
    metadata?: Record<string, unknown>;
    sourceType?: KnowledgeSourceType;
    languageTags: string[];
    chunkSource: "explicit_input" | "text_split" | "metadata_segment";
    chunkIndex: number;
    sourcePath?: string;
    isStructured?: boolean;
  },
): KnowledgeDocumentSourceChunk | null {
  if (typeof chunk === "string") {
    const content = normalizeKnowledgeChunk(chunk);
    if (!content) {
      return null;
    }

    return {
      content,
      metadata: buildChunkMetadata({
        metadata: input.metadata,
        sourceType: input.sourceType,
        chunkIndex: input.chunkIndex,
        chunkSource: input.chunkSource,
        sourcePath: input.sourcePath,
        languageTags: input.languageTags,
      }),
    };
  }

  const record = readRecord(chunk);
  if (!record) {
    return null;
  }

  const content =
    normalizeKnowledgeChunk(readChunkText(record) ?? "") ||
    normalizeKnowledgeChunk(
      stringifyStructuredRows(
        Array.isArray(record.rows)
          ? record.rows
          : Array.isArray(record.cells)
            ? [record.cells]
            : Array.isArray(record.values)
              ? [record.values]
              : [],
      ).join("\n"),
    );

  if (!content) {
    return null;
  }

  const pageNumber = readMetadataNumber(record, ["pageNumber", "page_number", "pageIndex", "page_index"]);
  const blockIndex = readMetadataNumber(record, ["blockIndex", "block_index", "ordinal", "index"]);
  const chunkMetadata = readRecord(record.metadata);
  const chunkKind =
    readMetadataString(record, ["kind", "type", "analysisMode", "analysis_mode", "extractionMode", "extraction_mode"]) ??
    readMetadataString(chunkMetadata, ["kind", "type", "analysisMode", "analysis_mode", "extractionMode", "extraction_mode"]);

  return {
    content,
    metadata: buildChunkMetadata({
      metadata: input.metadata,
      sourceType: input.sourceType,
      chunkIndex: input.chunkIndex,
      chunkSource: input.chunkSource,
      sourcePath: input.sourcePath,
      chunkKind,
      pageNumber,
      blockIndex,
      chunkMetadata,
      languageTags: input.languageTags,
    }),
  };
}

function collectMetadataSegments(
  value: unknown,
  input: {
    metadata?: Record<string, unknown>;
    sourceType?: KnowledgeSourceType;
    languageTags: string[];
  },
  state: {
    segments: KnowledgeDocumentSourceChunk[];
    seen: Set<string>;
    nextIndex: number;
  },
  path: string[] = [],
  depth = 0,
): void {
  if (depth > 6 || state.segments.length >= KNOWLEDGE_METADATA_SEGMENT_MAX || !value) {
    return;
  }

  if (typeof value === "string") {
    const normalized = normalizeKnowledgeChunk(value);
    if (!normalized) {
      return;
    }

    const key = normalized.toLowerCase();
    if (state.seen.has(key)) {
      return;
    }

    state.seen.add(key);
    state.segments.push({
      content: normalized,
      metadata: buildChunkMetadata({
        metadata: input.metadata,
        sourceType: input.sourceType,
        chunkIndex: state.nextIndex++,
        chunkSource: "metadata_segment",
        sourcePath: path.length ? path.join(".") : "metadata",
        chunkKind: "metadata_text",
        languageTags: input.languageTags,
      }),
    });
    return;
  }

  if (Array.isArray(value)) {
    value.forEach((item, index) => collectMetadataSegments(item, input, state, [...path, String(index)], depth + 1));
    return;
  }

  if (typeof value !== "object") {
    return;
  }

  const record = value as Record<string, unknown>;
  const sourceKind =
    readMetadataString(record, ["kind", "type", "analysisMode", "analysis_mode", "extractionMode", "extraction_mode"]) ??
    null;
  const pageNumber = readMetadataNumber(record, ["pageNumber", "page_number", "pageIndex", "page_index"]);
  const blockIndex = readMetadataNumber(record, ["blockIndex", "block_index", "ordinal", "index"]);
  const contextPath = path.length ? path.join(".") : "metadata";

  for (const key of ["text", "content", "summary", "ocrText", "visualSummary", "caption", "heading", "label", "description", "note"]) {
    const text = readMetadataString(record, [key]);
    if (!text) {
      continue;
    }

    const normalized = normalizeKnowledgeChunk(text);
    if (!normalized) {
      continue;
    }

    const keyHash = `${contextPath}:${key}:${normalized.toLowerCase()}`;
    if (state.seen.has(keyHash)) {
      continue;
    }

    state.seen.add(keyHash);
    state.segments.push({
      content: normalized,
      metadata: buildChunkMetadata({
        metadata: input.metadata,
        sourceType: input.sourceType,
        chunkIndex: state.nextIndex++,
        chunkSource: "metadata_segment",
        sourcePath: `${contextPath}.${key}`,
        chunkKind: sourceKind ?? key,
        pageNumber,
        blockIndex,
        languageTags: input.languageTags,
      }),
    });
  }

  const rows = Array.isArray(record.rows) ? record.rows : [];
  for (const [rowIndex, row] of stringifyStructuredRows(rows).entries()) {
    const normalized = normalizeKnowledgeChunk(row);
    if (!normalized) {
      continue;
    }

    const keyHash = `${contextPath}:rows:${rowIndex}:${normalized.toLowerCase()}`;
    if (state.seen.has(keyHash)) {
      continue;
    }

    state.seen.add(keyHash);
    state.segments.push({
      content: normalized,
      metadata: buildChunkMetadata({
        metadata: input.metadata,
        sourceType: input.sourceType,
        chunkIndex: state.nextIndex++,
        chunkSource: "metadata_segment",
        sourcePath: `${contextPath}.rows[${rowIndex}]`,
        chunkKind: sourceKind ?? "table_row",
        pageNumber,
        blockIndex,
        languageTags: input.languageTags,
      }),
    });
  }

  for (const key of [
    "document_analysis",
    "documentAnalysis",
    "analysis",
    "structured_data",
    "structuredData",
    "blocks",
    "pages",
    "tables",
    "figures",
    "chunks",
    "sections",
    "paragraphs",
    "items",
    "entries",
    "lines",
    "labels",
    "objects",
    "detections",
    "annotations",
    "regions",
  ]) {
    if (!(key in record)) {
      continue;
    }
    collectMetadataSegments(record[key], input, state, [...path, key], depth + 1);
  }
}

function extractKnowledgeMetadataSegments(
  metadata: Record<string, unknown> | undefined,
  input: {
    sourceType?: KnowledgeSourceType;
    languageTags: string[];
  },
): KnowledgeDocumentSourceChunk[] {
  if (!metadata) {
    return [];
  }

  const state = {
    segments: [] as KnowledgeDocumentSourceChunk[],
    seen: new Set<string>(),
    nextIndex: 0,
  };

  collectMetadataSegments(metadata, { metadata, sourceType: input.sourceType, languageTags: input.languageTags }, state);
  return state.segments.slice(0, KNOWLEDGE_METADATA_SEGMENT_MAX);
}

function normalizeKnowledgeChunkSources(input: {
  text?: string;
  chunks?: Array<KnowledgeDocumentChunkInput>;
  metadata?: Record<string, unknown>;
  languageTags: string[];
  sourceType?: KnowledgeSourceType;
}): KnowledgeDocumentSourceChunk[] {
  const sourceChunks: KnowledgeDocumentSourceChunk[] = [];
  const hasExplicitChunks = (input.chunks?.length ?? 0) > 0;

  if (hasExplicitChunks) {
    for (const [index, chunk] of (input.chunks ?? []).entries()) {
      const normalized = normalizeChunkInput(chunk, {
        metadata: input.metadata,
        sourceType: input.sourceType,
        languageTags: input.languageTags,
        chunkSource: "explicit_input",
        chunkIndex: index,
        sourcePath: `chunks[${index}]`,
      });
      if (normalized) {
        sourceChunks.push(normalized);
      }
    }
  } else if (input.text) {
    const textChunks = splitTextIntoChunks(redactSensitiveKnowledgeText(compactText(input.text, 200_000)));
    for (const [index, chunk] of textChunks.entries()) {
      const normalized = normalizeChunkInput(chunk, {
        metadata: input.metadata,
        sourceType: input.sourceType,
        languageTags: input.languageTags,
        chunkSource: "text_split",
        chunkIndex: index,
        sourcePath: "text",
      });
      if (normalized) {
        sourceChunks.push(normalized);
      }
    }
  }

  const metadataSegments = extractKnowledgeMetadataSegments(input.metadata, {
    sourceType: input.sourceType,
    languageTags: input.languageTags,
  });
  sourceChunks.push(...metadataSegments);

  return sourceChunks;
}

function compactKnowledgeChunks(chunks: KnowledgeDocumentSourceChunk[]): {
  chunks: KnowledgeDocumentSourceChunk[];
  normalization: KnowledgeDocumentNormalization;
} {
  const normalizedChunks: KnowledgeDocumentSourceChunk[] = [];
  const seen = new Set<string>();
  let inputCharacterCount = 0;

  for (const chunk of chunks) {
    const normalizedChunk = normalizeKnowledgeChunk(chunk.content);
    if (!normalizedChunk) {
      continue;
    }

    inputCharacterCount += normalizedChunk.length;
    const key = normalizedChunk.toLowerCase();
    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    normalizedChunks.push({
      content: normalizedChunk,
      metadata: chunk.metadata,
    });
  }

  const boundedChunks = normalizedChunks.slice(0, KNOWLEDGE_DOCUMENT_MAX_CHUNKS);
  const normalizedCharacterCount = boundedChunks.reduce((total, chunk) => total + chunk.content.length, 0);
  const sourceChunkCount = chunks.length;
  const duplicateChunkCount = Math.max(0, sourceChunkCount - normalizedChunks.length);
  const truncatedChunkCount = Math.max(0, normalizedChunks.length - boundedChunks.length);
  const compressionRatio =
    inputCharacterCount > 0 ? Number((normalizedCharacterCount / inputCharacterCount).toFixed(4)) : 1;
  const structuredChunkCount = boundedChunks.filter((chunk) => chunk.metadata.chunkSource !== "text_split").length;
  const metadataSegmentCount = boundedChunks.filter((chunk) => chunk.metadata.chunkSource === "metadata_segment").length;

  return {
    chunks: boundedChunks,
    normalization: {
      sourceChunkCount,
      normalizedChunkCount: boundedChunks.length,
      duplicateChunkCount,
      truncatedChunkCount,
      inputCharacterCount,
      normalizedCharacterCount,
      compressionRatio,
      structuredChunkCount,
      metadataSegmentCount,
    },
  };
}

export function prepareKnowledgeDocument(input: {
  text?: string;
  chunks?: Array<KnowledgeDocumentChunkInput>;
  languageTags?: string[];
  metadata?: Record<string, unknown>;
  sourceType?: KnowledgeSourceType;
}) {
  const sourceChunks = normalizeKnowledgeChunkSources({
    text: input.text,
    chunks: input.chunks,
    metadata: input.metadata,
    languageTags: input.languageTags ?? [],
    sourceType: input.sourceType,
  });
  const compacted = compactKnowledgeChunks(sourceChunks);

  if (!compacted.chunks.length) {
    throw badRequest("Knowledge document requires non-empty text or chunks");
  }

  const joined = compacted.chunks.map((chunk) => chunk.content).join("\n\n");
  const contentHash = createHash("sha256").update(joined).digest("hex");
  const languageTags = normalizeLanguageTags(input.languageTags, joined);

  return {
    contentHash,
    summary: compactText(joined, KNOWLEDGE_SUMMARY_MAX_CHARS),
    chunks: compacted.chunks.map((chunk, index) => ({
      ordinal: index,
      content: chunk.content,
      tokenEstimate: estimateTokenCount(chunk.content),
      metadata: chunk.metadata,
    })),
    languageTags,
    normalization: compacted.normalization,
  };
}

async function assertDatasetAccessible(app: FastifyInstance, datasetId: string, userId: string) {
  const rows = await app.db
    .select({
      id: datasetManifests.id,
      scope: datasetManifests.scope,
      ownerUserId: datasetManifests.ownerUserId,
    })
    .from(datasetManifests)
    .where(
      and(
        eq(datasetManifests.id, datasetId),
        or(eq(datasetManifests.scope, "shared"), eq(datasetManifests.ownerUserId, userId)),
      ),
    )
    .limit(1);

  if (!rows[0]) {
    throw notFound("Dataset manifest not found");
  }

  return rows[0];
}

async function assertTrainingJobAccessible(app: FastifyInstance, trainingJobId: string, userId: string) {
  const rows = await app.db
    .select({
      id: trainingJobs.id,
      scope: trainingJobs.scope,
      ownerUserId: trainingJobs.ownerUserId,
      status: trainingJobs.status,
    })
    .from(trainingJobs)
    .where(
      and(
        eq(trainingJobs.id, trainingJobId),
        or(eq(trainingJobs.scope, "shared"), eq(trainingJobs.ownerUserId, userId)),
      ),
    )
    .limit(1);

  if (!rows[0]) {
    throw notFound("Training job not found");
  }

  return rows[0];
}

export async function getBrainProfile(app: FastifyInstance, userId: string): Promise<any> {
  const cached = readBrainProfileCache(app, userId);
  if (cached) {
    return cached as Awaited<ReturnType<typeof getBrainProfile>>;
  }

  const [
    models,
    docCounts,
    trainingCounts,
    datasetCounts,
    learningCounts,
    learningQualityCounts,
    connectivityCounts,
    activeSharedJobs,
  ] = await Promise.all([
    app.db
      .select({
        id: modelArtifacts.id,
        name: modelArtifacts.name,
        scope: modelArtifacts.scope,
        provider: modelArtifacts.provider,
        baseModel: modelArtifacts.baseModel,
        adapterKind: modelArtifacts.adapterKind,
        status: modelArtifacts.status,
        storageUri: modelArtifacts.storageUri,
        checksum: modelArtifacts.checksum,
        updatedAt: modelArtifacts.updatedAt,
        metadata: modelArtifacts.metadata,
      })
      .from(modelArtifacts)
      .where(
        and(
          eq(modelArtifacts.status, "ready"),
          or(eq(modelArtifacts.scope, "shared"), eq(modelArtifacts.ownerUserId, userId)),
        ),
      )
      .orderBy(desc(modelArtifacts.scope), desc(modelArtifacts.updatedAt))
      .limit(10),
    app.db
      .select({
        documents: sql<number>`count(distinct ${knowledgeDocuments.id})`,
        chunks: sql<number>`count(${knowledgeChunks.id})`,
      })
      .from(knowledgeDocuments)
      .leftJoin(knowledgeChunks, eq(knowledgeChunks.documentId, knowledgeDocuments.id))
      .where(
        and(
          eq(knowledgeDocuments.status, "ready"),
          or(eq(knowledgeDocuments.scope, "shared"), eq(knowledgeDocuments.ownerUserId, userId)),
        ),
      ),
    app.db
      .select({
        queued: sql<number>`count(*) filter (where ${trainingJobs.status} = 'queued')`,
        running: sql<number>`count(*) filter (where ${trainingJobs.status} = 'running')`,
      })
      .from(trainingJobs)
      .where(or(eq(trainingJobs.scope, "shared"), eq(trainingJobs.ownerUserId, userId))),
    app.db
      .select({
        ready: sql<number>`count(*) filter (where ${datasetManifests.status} = 'ready')`,
        total: sql<number>`count(*)`,
      })
      .from(datasetManifests)
      .where(or(eq(datasetManifests.scope, "shared"), eq(datasetManifests.ownerUserId, userId))),
    app.db
      .select({
        safeEvents: sql<number>`count(*) filter (where ${learningEvents.privacyLevel} = 'safe')`,
        interactionEvents: sql<number>`count(*) filter (where ${learningEvents.source} = 'interaction')`,
        feedbackEvents: sql<number>`count(*) filter (where ${learningEvents.source} = 'feedback')`,
        runtimeEvents: sql<number>`count(*) filter (where ${learningEvents.source} = 'runtime')`,
        systemEvents: sql<number>`count(*) filter (where ${learningEvents.source} = 'system')`,
        routingSignals: sql<number>`count(*) filter (where ${learningEvents.type} = 'routing')`,
        bridgeSignals: sql<number>`count(*) filter (where ${learningEvents.type} = 'bridge')`,
      })
      .from(learningEvents)
      .where(or(eq(learningEvents.scope, "shared"), eq(learningEvents.userId, userId))),
    app.db
      .select({
        thumbsUp: sql<number>`count(*) filter (where ${learningEvents.source} = 'feedback' and ${learningEvents.key} = 'positive_feedback' and ${learningEvents.value} = 'thumbs_up')`,
        thumbsDown: sql<number>`count(*) filter (where ${learningEvents.source} = 'feedback' and ${learningEvents.key} = 'negative_feedback' and ${learningEvents.value} = 'thumbs_down')`,
        regenerate: sql<number>`count(*) filter (where ${learningEvents.source} = 'feedback' and ${learningEvents.key} = 'negative_feedback' and ${learningEvents.value} = 'regenerate')`,
        toneSignals: sql<number>`count(*) filter (where ${learningEvents.key} in ('preferred_tone', 'response_style_preference'))`,
        humorSignals: sql<number>`count(*) filter (where ${learningEvents.key} in ('humor_level', 'humor_feedback'))`,
        brevitySignals: sql<number>`count(*) filter (where ${learningEvents.key} in ('brevity_preference', 'answer_length', 'feedback_style'))`,
        helpfulnessSignals: sql<number>`count(*) filter (where ${learningEvents.key} in ('positive_feedback', 'negative_feedback', 'helpfulness_signal', 'follow_up_quality'))`,
        taskRoutingSignals: sql<number>`count(*) filter (where ${learningEvents.key} in ('task_target', 'routing_mode', 'task_handoff_helpfulness'))`,
        warmStyleVotes: sql<number>`count(*) filter (where (${learningEvents.key} = 'response_style_preference' and ${learningEvents.value} = 'warm') or (${learningEvents.key} = 'preferred_tone' and ${learningEvents.value} = 'warm_professional'))`,
        formalStyleVotes: sql<number>`count(*) filter (where (${learningEvents.key} = 'response_style_preference' and ${learningEvents.value} = 'formal') or (${learningEvents.key} = 'humor_level' and ${learningEvents.value} = 'restrained'))`,
        balancedStyleVotes: sql<number>`count(*) filter (where ${learningEvents.key} = 'response_style_preference' and ${learningEvents.value} = 'balanced')`,
      })
      .from(learningEvents)
      .where(eq(learningEvents.userId, userId)),
    app.db
      .select({
        mobileDevices: sql<number>`count(distinct case when ${devices.type} = 'mobile' then ${devices.id} end)`,
        desktopDevices: sql<number>`count(distinct case when ${devices.type} = 'desktop' then ${devices.id} end)`,
        connectedDesktopDevices: sql<number>`count(distinct case when ${devices.type} = 'desktop' and ${runtimeConnections.id} is not null and ${runtimeConnections.disconnectedAt} is null and ${runtimeConnections.status} != 'offline' then ${devices.id} end)`,
      })
      .from(devices)
      .leftJoin(
        runtimeConnections,
        and(eq(runtimeConnections.deviceId, devices.id), eq(runtimeConnections.userId, userId)),
      )
      .where(eq(devices.userId, userId)),
    app.db
      .select({
        id: trainingJobs.id,
        baseModel: trainingJobs.baseModel,
        kind: trainingJobs.kind,
        status: trainingJobs.status,
        config: trainingJobs.config,
        updatedAt: trainingJobs.updatedAt,
      })
      .from(trainingJobs)
      .where(
        and(
          eq(trainingJobs.scope, "shared"),
          or(eq(trainingJobs.status, "queued"), eq(trainingJobs.status, "running")),
        ),
      )
      .orderBy(desc(trainingJobs.updatedAt))
      .limit(1),
  ]);
  const runtimeSnapshot = await selectSharedBrainRuntime(app);
  const [retrievalStatus, memoryStatus, memoryListing] = await Promise.all([
    getRetrievalStatus(app, userId),
    getBrainMemoryStatus(app, userId),
    listBrainMemory(app, {
      userId,
      limit: 24,
      includeSoftDeleted: false,
      surface: "all",
      lifecycle: [],
      isAdmin: false,
    }).catch(() => ({
      items: [],
      summary: {
        total: 0,
        active: 0,
        contested: 0,
        superseded: 0,
        softDeleted: 0,
        stale: 0,
        facts: 0,
        episodes: 0,
      },
    })),
  ]);
  const userMemoryProfile = buildMemoryProfileSnapshot(
    memoryListing.items.map((item) => ({
      id: item.id,
      type: item.memoryType,
      key: item.title,
      value: item.content,
      confidence: Math.max(0, Math.min(1, item.confidence / 100)),
      scope: item.scope,
      source: item.entityType === "episode" ? "episodic_memory" : item.memorySource,
      createdAt: new Date(item.updatedAt),
      staleness:
        item.lifecycleStatus === "contested"
          ? "contested"
          : item.staleAt
            ? "stale"
            : "fresh",
      conflictStatus: item.conflictStatus,
      lastVerifiedAt: item.lastVerifiedAt ? new Date(item.lastVerifiedAt) : null,
      importanceScore: item.importanceScore,
      isPinned: item.isPinned,
    })),
  );

  const routingSignals = Number(learningCounts[0]?.routingSignals ?? 0);
  const bridgeSignals = Number(learningCounts[0]?.bridgeSignals ?? 0);
  const recentFeedbackSummary = {
    thumbsUp: Number(learningQualityCounts[0]?.thumbsUp ?? 0),
    thumbsDown: Number(learningQualityCounts[0]?.thumbsDown ?? 0),
    regenerate: Number(learningQualityCounts[0]?.regenerate ?? 0),
  };
  const qualitySignals = {
    toneSignals: Number(learningQualityCounts[0]?.toneSignals ?? 0),
    humorSignals: Number(learningQualityCounts[0]?.humorSignals ?? 0),
    brevitySignals: Number(learningQualityCounts[0]?.brevitySignals ?? 0),
    helpfulnessSignals: Number(learningQualityCounts[0]?.helpfulnessSignals ?? 0),
    taskRoutingSignals: Number(learningQualityCounts[0]?.taskRoutingSignals ?? 0),
  };
  const warmStyleVotes = Number(learningQualityCounts[0]?.warmStyleVotes ?? 0);
  const formalStyleVotes = Number(learningQualityCounts[0]?.formalStyleVotes ?? 0);
  const balancedStyleVotes = Number(learningQualityCounts[0]?.balancedStyleVotes ?? 0);
  const safeLearningEvents = Number(learningCounts[0]?.safeEvents ?? 0);
  const responseStylePreference: {
    code: "formal" | "balanced" | "warm";
    label: string;
    source: "learned" | "default";
  } =
    warmStyleVotes > formalStyleVotes && warmStyleVotes >= balancedStyleVotes
      ? { code: "warm", label: "Daha sıcak", source: "learned" }
      : formalStyleVotes > warmStyleVotes && formalStyleVotes >= balancedStyleVotes
        ? { code: "formal", label: "Daha resmi", source: "learned" }
        : balancedStyleVotes > 0
          ? { code: "balanced", label: "Dengeli", source: "learned" }
          : { code: "balanced", label: "Dengeli", source: "default" };
  const connectedDesktopDevices = Number(connectivityCounts[0]?.connectedDesktopDevices ?? 0);
  const desktopDevices = Number(connectivityCounts[0]?.desktopDevices ?? 0);
  const mobileDevices = Number(connectivityCounts[0]?.mobileDevices ?? 0);
  const runtimeReady = runtimeSnapshot.ready;
  const bridgeReadiness = connectedDesktopDevices > 0;
  const totalRoutingSignals = routingSignals + bridgeSignals;
  const routingQualityScore = Number(Math.min(1, totalRoutingSignals / 20).toFixed(2));
  const routingQualityState =
    totalRoutingSignals === 0
      ? "cold_start"
      : runtimeReady && bridgeReadiness && routingQualityScore >= 0.72
        ? "healthy"
        : "building";

  const readyModels = models.filter(isCompleteReadyBrainModelArtifact);
  const activeSharedModel = readyModels.find((model) => model.scope === "shared") ?? null;
  const activeUserModel = readyModels.find((model) => model.scope === "user") ?? null;
  const warmupJob = activeSharedJobs[0] ?? null;
  const readyDatasets = Number(datasetCounts[0]?.ready ?? 0);
  const sharedReadyModels = readyModels.filter((model) => model.scope === "shared");
  const rollbackSharedModel = sharedReadyModels[1] ?? null;
  const warmupPlan = readRecord(warmupJob?.config);
  const activeModelMetadata = readRecord(activeSharedModel?.metadata);
  const qualityGate = evaluateBrainQueueQualityGate({
    safeLearningEvents,
    feedbackSummary: recentFeedbackSummary,
    qualitySignals,
    responseStylePreference,
    routingSignals,
    bridgeSignals,
  });
  const promotionEligibility = evaluateBrainPromotionEligibility({
    evaluationScore:
      readNumberMetadata(activeSharedModel?.metadata, "evaluationScore") ??
      (activeSharedModel?.status === "ready" ? 1 : 0),
    qualityGate,
    qualitySignals,
  });
  const trainingPlan = warmupPlan;
  const sharedBrainTargetDevice = await getSharedBrainTargetDevice(app);
  const userDevices = await listUserDevices(app, userId);
  const serverTargetDeviceId =
    sharedBrainTargetDevice?.id ??
    userDevices.find((device) => device.type === "desktop" && device.canReceiveTasks)?.id ??
    null;
  const sharedBrainCapabilitySummary = sharedBrainTargetDevice?.runtime.capabilitySummary ?? null;
  const activeAdapter =
    readString(activeModelMetadata, "adapterStrategy") ??
    activeSharedModel?.adapterKind?.trim() ??
    "base";
  const serverBrainName = "Elyan";
  const configuredBaseModel = app.config.ELYAN_SHARED_BRAIN_MODEL.trim() || "llama3.2";
  const selectionBaseModel =
    activeSharedModel?.baseModel?.trim() ||
    warmupJob?.baseModel?.trim() ||
    activeUserModel?.baseModel?.trim() ||
    configuredBaseModel;
  const selection = {
    readyModels,
    activeSharedModel,
    rollbackSharedModel,
    activeUserModel,
    warmupJob,
    baseModel: selectionBaseModel,
    activeAdapter,
    trainingPlan,
  } satisfies SharedBrainSelection;
  const modelResolution = await resolveSharedBrainModel(app, {
    userId,
    workload: "mobile_chat_fast",
    selection,
    runtime: runtimeSnapshot,
  });
  const inferenceProbe = await probeSharedBrainInference(app, {
    userId,
  });
  const neural = await getNeuralBrainReadiness(app).catch(() => ({
    neuralReady: false,
    trainingWorkerReady: false,
    embeddingReady: false,
    evaluationReady: false,
    quantumLearningReady: false,
    activeTrainingJobs: 0,
    latestEvaluationScore: null,
    latestQualityCompositeScore: null,
    latestQuantumBenchmarkScore: null,
    mlWorkerMode: null,
    mlWorkerLastJobAt: null,
    mlWorkerLastErrorCode: null,
    optionalLibraries: {},
    runnerBacklog: null,
    brainBlockingReasons: ["neural_readiness_unavailable"],
  }));
  const brainRuntimeReady = Boolean(runtimeSnapshot.ready && serverBrainName);
  const probeReady = Boolean(inferenceProbe.ready);
  const servingProvider = inferenceProbe.provider ?? runtimeSnapshot.provider;
  const baseModel = (modelResolution.resolvedBaseModel ?? modelResolution.configuredBaseModel) || "llama3.2";
  const modelMode = activeSharedModel != null ? "adapted" : "base";
  const trainingState =
    activeSharedModel != null
      ? "adapted"
      : warmupJob != null
        ? "training"
        : probeReady || brainRuntimeReady
          ? "base_serving"
          : "cold";
  const inferenceReady = Boolean((probeReady || brainRuntimeReady) && baseModel);
  const isChatUsable = Boolean(inferenceReady && serverBrainName);
  const memoryAwareChatReady = Boolean(
    isChatUsable && (memoryStatus.pipelineReady || retrievalStatus.hybridReady),
  );
  const continuousImprovement = {
    status: warmupJob
      ? "active"
      : qualityGate.status === "ready_for_queue"
        ? "queueable"
        : "collecting_signals",
    canQueue: !warmupJob && qualityGate.status === "ready_for_queue",
    activeSharedJobId: warmupJob?.id ?? null,
    activeSharedJobStatus: warmupJob?.status ?? null,
    activeSharedModelId: activeSharedModel?.id ?? null,
    activeUserModelId: activeUserModel?.id ?? null,
    readyDatasets,
    safeLearningEvents,
    nextAction: warmupJob
      ? "wait_for_active_job"
      : qualityGate.status === "ready_for_queue"
        ? "queue_shared_refresh"
        : "collect_quality_signals",
  };
  const lastSharedRefreshAt =
    warmupJob?.updatedAt?.toISOString() ??
    (activeSharedModel?.updatedAt ? activeSharedModel.updatedAt.toISOString() : null);
  const freshSignalRows = await app.db
    .select({
      freshSignals: sql<number>`count(*)`,
      reconnectRecoveries: sql<number>`count(*) filter (where ${learningEvents.key} = 'session_recovered')`,
      handoffQualitySignals: sql<number>`count(*) filter (where ${learningEvents.key} = 'task_handoff_helpfulness')`,
    })
    .from(learningEvents)
    .where(
      and(
        eq(learningEvents.userId, userId),
        lastSharedRefreshAt
          ? sql`${learningEvents.createdAt} > ${lastSharedRefreshAt}`
          : sql`true`,
      ),
    );
  const signalFreshness = {
    freshSignalsSinceLastSharedRefresh: Number(freshSignalRows[0]?.freshSignals ?? 0),
    reconnectRecoveriesSinceLastSharedRefresh: Number(freshSignalRows[0]?.reconnectRecoveries ?? 0),
    handoffQualitySignalsSinceLastSharedRefresh: Number(freshSignalRows[0]?.handoffQualitySignals ?? 0),
    lastSharedRefreshAt,
  };
  const activeModelPromotion = {
    readySharedModelCount: sharedReadyModels.length,
    activeSharedModelId: activeSharedModel?.id ?? null,
    activeSharedModelProvider: activeSharedModel?.provider ?? null,
    activeSharedModelAdapter:
      readString(activeModelMetadata, "adapterStrategy") ??
      activeSharedModel?.adapterKind?.trim() ??
      null,
    rollbackSharedModelId: rollbackSharedModel?.id ?? null,
    rollbackSharedModelUpdatedAt: rollbackSharedModel?.updatedAt ?? null,
    promotedAt: activeSharedModel?.updatedAt ?? null,
    evaluationState: readString(activeModelMetadata, "evaluationState") ?? "bounded_offline_eval",
  };
  const desktopAvailable = bridgeReadiness;
  const quantumDesktop = userDevices.find((device) => {
    const capabilities = Array.isArray(device.runtime.capabilities)
      ? device.runtime.capabilities.map((capability) => String(capability ?? "").trim().toLowerCase().replace(/[\s_]+/g, "."))
      : [];
    return (
      device.type === "desktop" &&
      device.canReceiveTasks &&
      ["quantum.model.problem", "quantum.run.experiment", "quantum.compare.classical", "quantum.generate.report"].every(
        (capability) => capabilities.includes(capability),
      )
    );
  });
  const quantumReady = Boolean(quantumDesktop);
  const quantum = {
    mode: "hybrid",
    ready: quantumReady,
    supportedProblemClasses: quantumReady ? ["qubo", "ising", "qaoa", "vqe"] : [],
    solver: quantumReady ? "qiskit_simulator" : null,
    problemClass: "optimization",
    benchmarkStatus: quantumReady ? "ready" : "waiting_desktop",
    fallbackReason: quantumReady ? null : "quantum_desktop_runtime_unavailable",
    lastBenchmarkScore: null,
  };
  const mobileAvailable = mobileDevices > 0;
  const sections = buildBrainProfileSections({
    serverTargetDeviceId,
    serverBrainName,
    runtimeProvider: servingProvider,
    runtimeReady,
    runtimeCapabilitySummary: sharedBrainCapabilitySummary,
    desktopAvailable,
    mobileAvailable,
    connectedDesktopDevices,
    inferenceReady,
    isChatUsable,
    modelMode,
    trainingState,
    warmupJobId: warmupJob?.id ?? null,
    activeSharedModelId: activeSharedModel?.id ?? null,
    activeUserModelId: activeUserModel?.id ?? null,
    activeSharedJobId: warmupJob?.id ?? null,
    activeSharedJobStatus: warmupJob?.status ?? null,
    safeLearningEvents,
    readyDatasets,
    queuedJobs: Number(trainingCounts[0]?.queued ?? 0),
    runningJobs: Number(trainingCounts[0]?.running ?? 0),
    routingSignals,
    bridgeSignals,
    totalRoutingSignals,
    routingQualityScore,
    routingQualityState,
    bridgeReadiness,
    readySharedModelCount: sharedReadyModels.length,
    configuredBaseModel: modelResolution.configuredBaseModel,
    resolvedBaseModel: modelResolution.resolvedBaseModel,
    resolvedBaseModelSource: modelResolution.resolvedBaseModelSource,
    availableModels: modelResolution.availableModels,
  });
  const brainLatency = await getBrainLatencySummary(app).catch(() => ({
    lastChatLatencyMs: null,
    lastStreamingFirstDeltaMs: null,
    recentBrainTimeoutCount: 0,
    lastBrainResponseAt: null,
    completionLatencyP50Ms: null,
    completionLatencyP95Ms: null,
    firstDeltaP50Ms: null,
    firstDeltaP95Ms: null,
    attachmentCacheHitRate: null,
    recentResponseBytesAverage: null,
    sessionPageLatencyP50Ms: null,
    sessionPageLatencyP95Ms: null,
    sessionPageBytesP50: null,
    sessionPageBytesP95: null,
  }));
  const benchmarkSummary = await getLatestBrainBenchmarkSummary(app).catch(() => ({
    latestRunAt: null,
    latestStatus: null,
    latestOverallScore: null,
    latestBoundaryScore: null,
    latestReasoningScore: null,
    latestClarificationScore: null,
    latestToolUseScore: null,
    latestLatencyScore: null,
    caseCount: 0,
    constitutionVersion: ELYAN_CONSTITUTION_VERSION,
  }));
  const approvedCorrectionDataset = await getApprovedCorrectionDatasetState(app).catch(() => ({
    ready: false,
    datasetId: null,
    datasetVersion: null,
    compactionMode: null,
    approvedCorrectionCount: null,
    compactedRecordCount: null,
    freshSignalCount: null,
    correctionDensity: null,
    freshSignalRatio: null,
    signalFreshnessScore: null,
    lineageScore: null,
    compactionQualityScore: null,
    compactDatasetEligible: null,
    sourceLineage: null,
    freshnessWindowDays: null,
    highSignalThreshold: null,
    latestApprovedAt: null,
    oldestApprovedAt: null,
  }));
  const servingMode = resolveBrainServingMode(app);
  const groqConfigured = String(app.config.GROQ_API_KEY ?? "").trim().length > 0;
  const groqModelCatalog = groqConfigured ? buildGroqModelCatalog(app.config) : null;
  const groqConfiguredModels = groqModelCatalog?.defaultModelByWorkload ?? null;
  const activeMobileDefaultProfile = {
    workload: "mobile_chat_fast",
    mode: servingMode,
    model: groqConfigured
      ? (groqModelCatalog?.defaultModelByWorkload.mobile_chat_fast ?? modelResolution.resolvedBaseModel ?? modelResolution.configuredBaseModel ?? null)
      : modelResolution.resolvedBaseModel ?? modelResolution.configuredBaseModel ?? null,
    timeoutMs: getSharedBrainWorkloadProfile("mobile_chat_fast").timeoutMs,
    maxTokens: getSharedBrainWorkloadProfile("mobile_chat_fast").maxTokens,
    fallbackActive: groqConfigured
      ? Boolean(groqModelCatalog?.fallbackModel)
      : modelResolution.resolvedBaseModelSource === "installed_fallback" || Boolean(modelResolution.resolvedFallbackModel),
    fallbackModel: groqConfigured ? groqModelCatalog?.fallbackModel ?? null : modelResolution.resolvedFallbackModel,
  };
  const latestLatencyWarning =
    brainLatency.recentBrainTimeoutCount > 0
      ? "recent_timeouts_detected"
      : (brainLatency.lastChatLatencyMs ?? 0) > getSharedBrainWorkloadProfile("mobile_chat_fast").timeoutMs
        ? "mobile_chat_latency_high"
        : null;
  const recentLatencyPressure =
    latestLatencyWarning === "mobile_chat_latency_high" ? "high" : (brainLatency.lastChatLatencyMs ?? 0) > 0 ? "normal" : "cold";
  const recentTimeoutPressure =
    brainLatency.recentBrainTimeoutCount >= 3
      ? "high"
      : brainLatency.recentBrainTimeoutCount > 0
        ? "elevated"
        : "normal";
  const activeArtifact = activeSharedModel ?? activeUserModel;
  const hostedConfigured = Boolean(
    app.config.ANTHROPIC_API_KEY ||
      app.config.OPENAI_API_KEY ||
      app.config.GROQ_API_KEY ||
      app.config.GEMINI_API_KEY ||
      app.config.OPENROUTER_API_KEY,
  );
  const activeKnowledgeCorpusSnapshot = await getActiveKnowledgeCorpusSummary(app).catch(() => ({
    mode: "shared_global",
    readyDocuments: 0,
    readyDatasets: 0,
    latestDocumentUpdatedAt: null,
    latestDatasetUpdatedAt: null,
  }));
  const systemCorpus = await getBrainCorpusReadinessSummary(app).catch(() => ({
    enabled: true,
    corpusVersion: "unknown",
    expectedDocuments: 0,
    readyDocuments: 0,
    readyChunks: 0,
    domains: [],
    categories: [],
  }));
  const activeKnowledgeCorpus = {
    ...activeKnowledgeCorpusSnapshot,
    readyDocuments: Math.max(
      activeKnowledgeCorpusSnapshot.readyDocuments,
      Number(docCounts[0]?.documents ?? 0),
    ),
    readyDatasets: Math.max(
      activeKnowledgeCorpusSnapshot.readyDatasets,
      Number(datasetCounts[0]?.ready ?? 0),
    ),
    systemCorpus,
  };
  const currentServingPolicy = {
    mode: servingMode,
    workloadDefaults: {
      mobileChatFast: groqConfigured
        ? "groq_primary_direct"
        : hostedConfigured
          ? "hybrid_hosted_primary_local_fallback"
          : "local_primary_fast_model",
      mobileChatBalanced: groqConfigured
        ? "groq_primary_direct"
        : hostedConfigured
          ? "hybrid_hosted_primary_local_fallback"
          : "local_primary_balanced_model",
      planning: groqConfigured
        ? "groq_primary_direct"
        : hostedConfigured
          ? "hybrid_hosted_primary_local_fallback"
          : "local_primary_planning_model",
    },
    primaryProviderByWorkload: {
      mobileChatFast: groqConfigured ? "groq" : "ollama",
      mobileChatBalanced: groqConfigured ? "groq" : "ollama",
      planning: groqConfigured ? "groq" : "ollama",
    },
    localFallbackLadder: {
      fastRoute: groqConfigured ? [] : ["qwen2.5-coder:3b", "qwen2.5:7b-instruct-q5_K_M", "llama3:8b"],
      mobileChatFast: groqConfigured ? [] : ["qwen2.5-coder:3b", "qwen2.5:7b-instruct-q5_K_M", "llama3:8b"],
      mobileChatBalanced: groqConfigured ? [] : ["qwen2.5:7b-instruct-q5_K_M", "deepseek-r1:8b", "llama3:8b"],
      planning: groqConfigured ? [] : ["qwen2.5:7b-instruct-q5_K_M", "deepseek-r1:8b", "llama3:8b"],
    },
    configuredModels: {
      fastRoute: groqConfigured
        ? groqConfiguredModels?.fast_route ?? (app.config.ELYAN_SHARED_BRAIN_FAST_MODEL || "qwen2.5-coder:3b")
        : app.config.ELYAN_SHARED_BRAIN_FAST_MODEL || "qwen2.5-coder:3b",
      mobileChatFast: groqConfigured
        ? groqConfiguredModels?.mobile_chat_fast ?? (app.config.ELYAN_SHARED_BRAIN_FAST_MODEL || "qwen2.5-coder:3b")
        : app.config.ELYAN_SHARED_BRAIN_FAST_MODEL || "qwen2.5-coder:3b",
      mobileChatBalanced: groqConfigured
        ? groqConfiguredModels?.mobile_chat_balanced ?? (app.config.ELYAN_SHARED_BRAIN_BALANCED_MODEL || "qwen2.5:7b-instruct-q5_K_M")
        : app.config.ELYAN_SHARED_BRAIN_BALANCED_MODEL || "qwen2.5:7b-instruct-q5_K_M",
      planning: groqConfigured
        ? groqConfiguredModels?.planning ?? (app.config.ELYAN_SHARED_BRAIN_PLANNING_MODEL || "qwen2.5:7b-instruct-q5_K_M")
        : app.config.ELYAN_SHARED_BRAIN_PLANNING_MODEL || "qwen2.5:7b-instruct-q5_K_M",
    },
    webGrounding: {
      enabled: app.config.ELYAN_WEB_GROUNDING_ENABLED,
      source: "duckduckgo_html",
      maxResults: app.config.ELYAN_WEB_GROUNDING_MAX_RESULTS,
      timeoutMs: app.config.ELYAN_WEB_GROUNDING_TIMEOUT_MS,
    },
    hostedConfigured,
  };
  const elyanModelLearningPolicy = buildElyanModelLearningPolicy({
    groqConfigured,
    costGuardEnabled: Boolean(app.config.ELYAN_COST_GUARD_ENABLED),
    activeSharedModelId: activeSharedModel?.id ?? null,
    activeUserModelId: activeUserModel?.id ?? null,
    warmupJobId: warmupJob?.id ?? null,
    warmupJobStatus: warmupJob?.status ?? null,
    qualityGateStatus: qualityGate.status,
    qualityGateReasons: qualityGate.reasons,
    promotionGateStatus: promotionEligibility.status,
    promotionGateReasons: promotionEligibility.reasons,
    approvedCorrectionDatasetReady: approvedCorrectionDataset.ready,
    compactDatasetEligible: approvedCorrectionDataset.compactDatasetEligible,
    evaluationScore: readNumberMetadata(activeSharedModel?.metadata, "evaluationScore"),
    benchmarkScore: benchmarkSummary.latestOverallScore,
    recentTimeoutCount: brainLatency.recentBrainTimeoutCount,
  });
  const elyanModelProviderPlan = buildElyanModelProviderPlan({
    policy: elyanModelLearningPolicy,
    artifact: activeArtifact,
    workload: "mobile_chat_fast",
    runtimeProvider: runtimeSnapshot.provider,
    runtimeReady: runtimeSnapshot.ready,
    canaryEnabled: Boolean(app.config.ELYAN_MODEL_CANARY_ENABLED),
    primaryEnabled: Boolean(app.config.ELYAN_MODEL_PRIMARY_ENABLED),
  });
  const skills = await getPublicSkillCatalog();

  const profile = {
    skills,
    constitution: {
      version: ELYAN_CONSTITUTION_VERSION,
      promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
      ruleCount: constitutionRuleCount(),
      gateReady: ELYAN_CONSTITUTION_GATE_READY,
    },
    benchmark: {
      latestRunAt: benchmarkSummary.latestRunAt,
      latestStatus: benchmarkSummary.latestStatus,
      latestOverallScore: benchmarkSummary.latestOverallScore,
      latestBoundaryScore: benchmarkSummary.latestBoundaryScore,
      latestReasoningScore: benchmarkSummary.latestReasoningScore,
      latestClarificationScore: benchmarkSummary.latestClarificationScore,
      latestToolUseScore: benchmarkSummary.latestToolUseScore,
      latestLatencyScore: benchmarkSummary.latestLatencyScore,
      caseCount: benchmarkSummary.caseCount,
    },
    quota: getTrialQuotaPolicy(),
    bridge: {
      mode: "desktop_first_then_server_brain",
      taskRouting: "desktop_first_when_available",
      chatRouting: "server_brain_first",
      desktopAvailable,
      mobileAvailable,
      connectedDesktopDevices,
      serverBrainReady: isChatUsable,
      fallbackRoute: "server_brain_unavailable",
      surfaces: {
        chatMessages: "/v1/chat/messages",
        tasks: "/v1/tasks",
        realtime: "/v1/realtime/stream",
      },
    },
    chat: {
      dispatchPath: "/v1/tasks",
      brainProfilePath: "/v1/brain/profile",
      realtimePath: "/v1/realtime/stream",
      sessionsPath: "/v1/chat/sessions",
      messagesPath: "/v1/chat/messages",
      homeSurface: "chat",
      mobileDocumentExportReady: true,
      responseProtocol: {
        blocksVersion: app.config.ELYAN_BLOCKS_V11_ENABLED ? "v1.1" : "v1",
        phasedRollout: true,
        summaryReady: app.config.ELYAN_BLOCKS_V11_ENABLED,
        statusReady: app.config.ELYAN_BLOCKS_V11_ENABLED,
        nextStepsReady: app.config.ELYAN_BLOCKS_V11_ENABLED,
        actionableReady: app.config.ELYAN_BLOCKS_V11_ENABLED,
        qualityRepairReady: true,
        mobileChatQualityEvalReady: true,
        trainingLoopReady: true,
      },
      serverTargetDeviceId,
      activeSharedModel,
      activeUserModel,
      inferenceReady,
      modelMode,
      trainingState,
      activeMobileDefaultProfile,
      workloadProfiles: {
        mobileChatFast: getSharedBrainWorkloadProfile("mobile_chat_fast"),
        mobileChatBalanced: getSharedBrainWorkloadProfile("mobile_chat_balanced"),
        mobileChatDeepRefine: getSharedBrainWorkloadProfile("mobile_chat_deep_refine"),
        planning: getSharedBrainWorkloadProfile("planning"),
        desktopHandoff: getSharedBrainWorkloadProfile("desktop_handoff"),
      },
      latencyBudgets: {
        mobileChatFastFirstDeltaMs: getSharedBrainWorkloadProfile("mobile_chat_fast").firstDeltaBudgetMs,
        mobileChatFastTimeoutMs: getSharedBrainWorkloadProfile("mobile_chat_fast").timeoutMs,
        planningFirstDeltaMs: getSharedBrainWorkloadProfile("planning").firstDeltaBudgetMs,
        planningTimeoutMs: getSharedBrainWorkloadProfile("planning").timeoutMs,
      },
      fallbackStatus: {
        active: groqConfigured ? false : activeMobileDefaultProfile.fallbackActive,
        fallbackModel: groqConfigured ? null : activeMobileDefaultProfile.fallbackModel,
        hostedConfigured: currentServingPolicy.hostedConfigured,
        mode: activeMobileDefaultProfile.mode,
      },
      latencySummary: {
        lastChatLatencyMs: brainLatency.lastChatLatencyMs,
        lastStreamingFirstDeltaMs: brainLatency.lastStreamingFirstDeltaMs,
        completionLatencyP50Ms: brainLatency.completionLatencyP50Ms,
        completionLatencyP95Ms: brainLatency.completionLatencyP95Ms,
        firstDeltaP50Ms: brainLatency.firstDeltaP50Ms,
        firstDeltaP95Ms: brainLatency.firstDeltaP95Ms,
        attachmentCacheHitRate: brainLatency.attachmentCacheHitRate,
        recentResponseBytesAverage: brainLatency.recentResponseBytesAverage,
        sessionPageLatencyP50Ms: brainLatency.sessionPageLatencyP50Ms,
        sessionPageLatencyP95Ms: brainLatency.sessionPageLatencyP95Ms,
        sessionPageBytesP50: brainLatency.sessionPageBytesP50,
        sessionPageBytesP95: brainLatency.sessionPageBytesP95,
        recentBrainTimeoutCount: brainLatency.recentBrainTimeoutCount,
        lastBrainResponseAt: brainLatency.lastBrainResponseAt,
      },
      currentServingPolicy,
      elyanProviderPlan: elyanModelProviderPlan,
      activeArtifact,
      activeKnowledgeCorpus,
      recentLatencyPressure,
      recentTimeoutPressure,
      latestLatencyWarning,
      configuredBaseModel: modelResolution.configuredBaseModel,
      resolvedBaseModel: modelResolution.resolvedBaseModel,
      resolvedBaseModelSource: modelResolution.resolvedBaseModelSource,
      availableModels: modelResolution.availableModels,
      warmupJobId: warmupJob?.id ?? null,
      serverBrainName,
      isChatUsable,
      connection: {
        mode: "desktop_first_then_server_brain",
        desktopAvailable,
        mobileAvailable,
        connectedDesktopDevices,
        inferenceReady,
        realtimeReady: true,
        replaySupported: true,
        resumeCursorTtlSeconds: app.config.REALTIME_EVENT_RETENTION_HOURS * 60 * 60,
        sessionHydrationMode: "realtime_then_authoritative_refresh",
        degradedReason: !isChatUsable
          ? "server_brain_unavailable"
          : retrievalStatus.mode === "lexical_fallback" && memoryStatus.memoryIndexCoverage <= 0
            ? "memory_index_cold"
            : null,
        serverBrainReady: isChatUsable,
        fallbackRoute: "server_brain_unavailable",
      },
      boundaryGate: {
        ready: ELYAN_CONSTITUTION_GATE_READY,
        enforcedRuleIds: listGateEnforcedRuleIds(),
      },
    },
    quantum,
    sections,
    learning: {
      userUnderstandingEnabled: app.config.ELYAN_USER_UNDERSTANDING_ENABLED,
      personalizationEnabled: app.config.ELYAN_PERSONALIZATION_ENABLED,
      extractionEnabled: app.config.ELYAN_LEARNING_EXTRACTION_ENABLED,
      privacyBoundary: "shared_brain_plus_user_scoped_learning",
      neuralReady: neural.neuralReady,
      trainingWorkerReady: neural.trainingWorkerReady,
      embeddingReady: neural.embeddingReady,
      evaluationReady: neural.evaluationReady,
      quantumLearningReady: neural.quantumLearningReady,
      activeTrainingJobs: neural.activeTrainingJobs,
      latestEvaluationScore: neural.latestEvaluationScore,
      latestQuantumBenchmarkScore: neural.latestQuantumBenchmarkScore,
      mlWorkerMode: neural.mlWorkerMode,
      mlWorkerLastJobAt: neural.mlWorkerLastJobAt,
      mlWorkerLastErrorCode: neural.mlWorkerLastErrorCode,
      optionalLibraries: neural.optionalLibraries,
      runnerBacklog: neural.runnerBacklog,
      brainBlockingReasons: neural.brainBlockingReasons,
      responseStylePreference,
      humorMode: "controlled_light",
      recentFeedbackSummary,
      qualitySignals,
      qualityGate,
      signalFreshness,
      correctionDatasetStatus: approvedCorrectionDataset,
      elyanModel: elyanModelLearningPolicy,
      elyanProviderPlan: elyanModelProviderPlan,
    },
    memory: {
      workingMemoryBudget: {
        maxConversationMessages: 6,
        maxPromptTokens: 900,
        maxMemoryHints: 8,
      },
      userMemoryProfile,
      compaction: {
        compactedCount: userMemoryProfile.compactedCount,
        activeSnapshotCount:
          userMemoryProfile.identityFacts.length +
          userMemoryProfile.preferenceFacts.length +
          userMemoryProfile.projectFacts.length +
          userMemoryProfile.recentEpisodes.length,
        staleCount: memoryStatus.staleMemoryCount,
        softDeletedCount: memoryStatus.softDeletedCount,
        contestedCount: memoryStatus.contestedMemoryCount,
        retentionWindows: {
          factsDays: 365,
          episodesDays: 120,
        },
        lastCompactedAt: memoryStatus.lastReconsolidatedAt ?? memoryStatus.lastConsolidatedAt,
      },
      recallReady: memoryStatus.pipelineReady && (memoryStatus.semanticMemoryCount > 0 || memoryStatus.episodicMemoryCount > 0),
      activeSemanticCount: memoryStatus.semanticMemoryCount,
      recentEpisodeCount: memoryStatus.episodicMemoryCount,
      episodicMemoryCount: memoryStatus.episodicMemoryCount,
      semanticMemoryCount: memoryStatus.semanticMemoryCount,
      selfModelMemoryCount: memoryStatus.selfModelMemoryCount,
      reflectiveMemoryCount: memoryStatus.reflectiveMemoryCount,
      pinnedMemoryCount: memoryStatus.pinnedMemoryCount,
      softDeletedCount: memoryStatus.softDeletedCount,
      staleMemoryCount: memoryStatus.staleMemoryCount,
      contestedMemoryCount: memoryStatus.contestedMemoryCount,
      recallPenaltySummary: {
        stalePenaltyActiveCount: memoryStatus.staleMemoryCount,
        contestedPenaltyActiveCount: memoryStatus.contestedMemoryCount,
        lastMemoryIndexAt: memoryStatus.lastIndexedAt,
      },
      lastConsolidatedAt: memoryStatus.lastConsolidatedAt,
      lastReconsolidatedAt: memoryStatus.lastReconsolidatedAt,
      lastSelfModelUpdatedAt: memoryStatus.lastSelfModelUpdatedAt,
    },
    metacognition: {
      selfModelReady: memoryStatus.selfModelMemoryCount > 0,
      memoryAwareChatReady,
      contradictionGuardReady: memoryStatus.pipelineReady,
      memoryConflictGuardReady: memoryStatus.pipelineReady,
      reflectiveMemoryReady: memoryStatus.reflectiveMemoryCount > 0,
      memoryControlReady: memoryStatus.pipelineReady,
      lastSelfCheckAt: brainLatency.lastBrainResponseAt,
    },
    retrieval: {
      readyDocuments: Number(docCounts[0]?.documents ?? 0),
      readyChunks: Number(docCounts[0]?.chunks ?? 0),
      mode: retrievalStatus.mode,
      embeddingCoverage: retrievalStatus.embeddingCoverage,
      pendingIndexJobs: retrievalStatus.pendingIndexJobs,
      lastIndexedAt: retrievalStatus.lastIndexedAt,
      memorySources: memoryStatus.memorySources,
      memoryIndexCoverage: memoryStatus.memoryIndexCoverage,
      memorySourceCoverage: memoryStatus.memorySources,
      memoryRecallMode:
        retrievalStatus.mode === "hybrid" && memoryStatus.memoryIndexCoverage > 0
          ? "hybrid_memory_plus_knowledge"
          : "lexical_memory_fallback",
    },
    training: {
      queuedJobs: Number(trainingCounts[0]?.queued ?? 0),
      runningJobs: Number(trainingCounts[0]?.running ?? 0),
      readyDatasets: Number(datasetCounts[0]?.ready ?? 0),
      totalDatasets: Number(datasetCounts[0]?.total ?? 0),
      safeLearningEvents: Number(learningCounts[0]?.safeEvents ?? 0),
      connectivity: {
        mobileDevices: Number(connectivityCounts[0]?.mobileDevices ?? 0),
        desktopDevices: Number(connectivityCounts[0]?.desktopDevices ?? 0),
        connectedDesktopDevices: Number(connectivityCounts[0]?.connectedDesktopDevices ?? 0),
        bridgeMode: "mobile_desktop_sync",
        bridgeTargets: ["task_handoff", "session_reconnect", "dispatch_resilience"],
      },
      signalSummary: {
        interactionEvents: Number(learningCounts[0]?.interactionEvents ?? 0),
        feedbackEvents: Number(learningCounts[0]?.feedbackEvents ?? 0),
        runtimeEvents: Number(learningCounts[0]?.runtimeEvents ?? 0),
        systemEvents: Number(learningCounts[0]?.systemEvents ?? 0),
        routingSignals,
        bridgeSignals,
      },
      qualitySignalSummary: qualitySignals,
      signalFreshness,
      approvedCorrectionDatasetReady: approvedCorrectionDataset.ready,
      lastApprovedCorrectionDatasetId: approvedCorrectionDataset.datasetId,
      queueEligibility: {
        status: qualityGate.status,
        reasons: qualityGate.reasons,
      },
      trainingEligibility: {
        approvedCorrectionDatasetReady: approvedCorrectionDataset.ready,
        compactDatasetEligible: approvedCorrectionDataset.compactDatasetEligible ?? approvedCorrectionDataset.ready,
        compactDatasetQualityScore: approvedCorrectionDataset.compactionQualityScore ?? null,
        benchmarkBaselineReady: Boolean(benchmarkSummary.latestRunAt),
        benchmarkScoreAttached: typeof benchmarkSummary.latestOverallScore === "number",
        rawSignalDatasetsRejected: true,
      },
      promotionEligibility: {
        status: promotionEligibility.status,
        reasons: promotionEligibility.reasons,
      },
      pipeline: {
        neural,
        activeJobId: warmupJob?.id ?? null,
        activeJobStatus: warmupJob?.status ?? null,
        activeJobKind: warmupJob?.kind ?? null,
        activeJobBaseModel: warmupJob?.baseModel ?? null,
        activeJobPlan: trainingPlan,
        activeModelId: activeSharedModel?.id ?? null,
        activeModelScope: activeSharedModel?.scope ?? null,
        activeModelAdapter: activeAdapter,
        bridgeReadiness,
        bridgeLearning: {
          routingSignals,
          bridgeSignals,
          mobileDevices,
          desktopDevices,
          connectedDesktopDevices,
        },
        continuousImprovement,
        personaTarget: "warm_professional_balanced",
        mobileChatFocus: true,
        queueGateStatus: qualityGate.status,
        promotionGateStatus: promotionEligibility.status,
        lastQualityGateEvaluatedAt: new Date().toISOString(),
        routingQuality: {
          score: routingQualityScore,
          state: routingQualityState,
          totalSignals: totalRoutingSignals,
          bridgeReadiness,
          runtimeReady,
          readyForPromotion: runtimeReady && bridgeReadiness && routingQualityScore >= 0.72,
        },
        promotion: activeModelPromotion,
        inferenceReady,
        runtimeReady,
      },
      elyanModel: elyanModelLearningPolicy,
      elyanProviderPlan: elyanModelProviderPlan,
      brainLatency,
    },
  };

  writeBrainProfileCache(app, userId, profile);
  return profile;
}

export async function maybeQueueAutomaticSharedBrainRefresh(
  app: FastifyInstance,
  input: {
    userId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
    source: string;
  },
) {
  const profile = await getBrainProfile(app, input.userId);
  const qualityGate = profile.learning.qualityGate;
  const freshness = profile.training.signalFreshness;

  const hasNoActiveSharedJob = !profile.training.pipeline.continuousImprovement.activeSharedJobId;
  const enoughFreshSignals = freshness.freshSignalsSinceLastSharedRefresh >= 6;
  const enoughReconnectSignals = freshness.reconnectRecoveriesSinceLastSharedRefresh >= 1;
  const enoughHandoffSignals = freshness.handoffQualitySignalsSinceLastSharedRefresh >= 1;
  const memoryReady =
    profile.memory.semanticMemoryCount > 0 ||
    profile.memory.episodicMemoryCount > 0 ||
    profile.memory.lastConsolidatedAt != null;
  const eligible =
    hasNoActiveSharedJob &&
    qualityGate.status === "ready_for_queue" &&
    profile.chat.inferenceReady &&
    profile.learning.trainingWorkerReady &&
    memoryReady &&
    enoughFreshSignals &&
    (enoughReconnectSignals || enoughHandoffSignals);

  if (!eligible) {
    return {
      queued: false,
      reason: "auto_queue_not_eligible" as const,
    };
  }

  const result = await queueContinuousBrainTrainingJob(app, input);
  return {
    queued: result.created,
    reason: result.reason,
  };
}

export function shapePublicBrainProfile(
  profile: Awaited<ReturnType<typeof getBrainProfile>>,
) {
  const activeSharedModel = profile.chat.activeSharedModel
    ? {
        id: profile.chat.activeSharedModel.id,
        label: "Elyan paylaşılan zeka",
        scope: profile.chat.activeSharedModel.scope,
      }
    : null;
  const activeUserModel = profile.chat.activeUserModel
    ? {
        id: profile.chat.activeUserModel.id,
        label: "Elyan kişisel zeka",
        scope: profile.chat.activeUserModel.scope,
      }
    : null;
  const {
    configuredBaseModel: _configuredBaseModel,
    resolvedBaseModel: _resolvedBaseModel,
    resolvedBaseModelSource: _resolvedBaseModelSource,
    availableModels: _availableModels,
    activeSharedModel: _ignoredActiveSharedModel,
    activeUserModel: _ignoredActiveUserModel,
    activeMobileDefaultProfile: _activeMobileDefaultProfile,
    fallbackStatus: _fallbackStatus,
    currentServingPolicy: _currentServingPolicy,
    activeArtifact: _activeArtifact,
    ...publicChat
  } = profile.chat;

  return sanitizePublicBrainValue({
    ...profile,
    chat: {
      ...publicChat,
      activeSharedModel,
      activeUserModel,
    },
  });
}

const PRIVATE_BRAIN_PROFILE_KEYS = new Set([
  "provider",
  "servingProvider",
  "runtimeProvider",
  "activeSharedModelProvider",
  "activeModelProvider",
  "model",
  "baseModel",
  "activeJobBaseModel",
  "configuredBaseModel",
  "resolvedBaseModel",
  "resolvedBaseModelSource",
  "availableModels",
  "fallbackModel",
  "fallbackFromModel",
  "attemptedModels",
  "attemptedProviders",
  "modelSource",
  "content",
  "prompt",
  "systemPrompt",
  "instructions",
  "storageUri",
  "checksum",
]);

export function sanitizePublicBrainValue<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizePublicBrainValue(item)) as T;
  }
  if (!value || typeof value !== "object") {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !PRIVATE_BRAIN_PROFILE_KEYS.has(key))
      .map(([key, nestedValue]) => [key, sanitizePublicBrainValue(nestedValue)]),
  ) as T;
}

export async function queueContinuousBrainTrainingJob(
  app: FastifyInstance,
  input: {
    userId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const profile = await getBrainProfile(app, input.userId);
  const activeSharedJob = profile.training.pipeline.continuousImprovement.activeSharedJobId;
  const elyanModelPolicy = profile.training.elyanModel ?? profile.learning.elyanModel ?? null;
  const elyanProviderPlan =
    profile.training.elyanProviderPlan ?? profile.learning.elyanProviderPlan ?? profile.chat.elyanProviderPlan ?? null;

  if (activeSharedJob) {
    const rows = await app.db
      .select()
      .from(trainingJobs)
      .where(eq(trainingJobs.id, activeSharedJob))
      .limit(1);

    return {
      job: rows[0] ?? null,
      created: false,
      reason: "active_shared_job_exists" as const,
      elyanModel: elyanModelPolicy,
      elyanProviderPlan,
    };
  }

  const sharedBrainDevice = profile.chat.serverTargetDeviceId;

  if (!sharedBrainDevice) {
    throw notFound("Shared brain device not found");
  }

  const queueQualityGate = profile.learning.qualityGate;
  if (queueQualityGate.status !== "ready_for_queue") {
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "brain.training_job.blocked_by_quality_gate",
      resourceType: "training_job",
      resourceId: null,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        status: queueQualityGate.status,
        reasons: queueQualityGate.reasons,
        qualityCompositeScore: queueQualityGate.qualityCompositeScore,
        thumbsDownRate: queueQualityGate.thumbsDownRate,
        regenerateRate: queueQualityGate.regenerateRate,
      },
    });

    return {
      job: null,
      created: false,
      reason:
        queueQualityGate.status === "blocked_quality_regression"
          ? ("quality_gate_regression" as const)
          : ("quality_gate_low_signal" as const),
      elyanModel: elyanModelPolicy,
      elyanProviderPlan,
    };
  }

  const approvedCorrectionDataset = profile.learning.correctionDatasetStatus;
  const benchmarkSummary = profile.benchmark;

  if (!approvedCorrectionDataset.ready || !approvedCorrectionDataset.datasetId) {
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "brain.training_job.blocked_by_quality_gate",
      resourceType: "training_job",
      resourceId: null,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        status: "blocked_missing_approved_correction_dataset",
        reasons: ["approved_correction_dataset_required"],
      },
    });
    return {
      job: null,
      created: false,
      reason: "approved_correction_dataset_required" as const,
      elyanModel: elyanModelPolicy,
      elyanProviderPlan,
    };
  }

  if (!benchmarkSummary.latestRunAt || typeof benchmarkSummary.latestOverallScore !== "number") {
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "brain.training_job.blocked_by_quality_gate",
      resourceType: "training_job",
      resourceId: null,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        status: "blocked_missing_benchmark_baseline",
        reasons: ["benchmark_baseline_required"],
      },
    });
    return {
      job: null,
      created: false,
      reason: "benchmark_baseline_required" as const,
      elyanModel: elyanModelPolicy,
      elyanProviderPlan,
    };
  }

  const approvedDatasetRows = await app.db
    .select()
    .from(datasetManifests)
    .where(eq(datasetManifests.id, approvedCorrectionDataset.datasetId))
    .limit(1);
  const approvedDataset = approvedDatasetRows[0] ?? null;
  const approvedDatasetMetadata = readRecord(approvedDataset?.metadata);
  const approvedDatasetVersion = readString(approvedDatasetMetadata, "datasetVersion");
  const approvedDatasetCompaction = {
    compactionMode: readString(approvedDatasetMetadata, "compactionMode"),
    approvedCorrectionCount: readNumberMetadata(approvedDatasetMetadata, "approvedCorrectionCount"),
    compactedRecordCount: readNumberMetadata(approvedDatasetMetadata, "compactedRecordCount"),
    freshSignalCount: readNumberMetadata(approvedDatasetMetadata, "freshSignalCount"),
    correctionDensity: readNumberMetadata(approvedDatasetMetadata, "correctionDensity"),
    freshSignalRatio: readNumberMetadata(approvedDatasetMetadata, "freshSignalRatio"),
    signalFreshnessScore: readNumberMetadata(approvedDatasetMetadata, "signalFreshnessScore"),
    lineageScore: readNumberMetadata(approvedDatasetMetadata, "lineageScore"),
    compactionQualityScore: readNumberMetadata(approvedDatasetMetadata, "compactionQualityScore"),
    compactDatasetEligible: readBoolean(approvedDatasetMetadata, "compactDatasetEligible"),
    sourceLineage: readString(approvedDatasetMetadata, "sourceLineage"),
    freshnessWindowDays: readNumberMetadata(approvedDatasetMetadata, "freshnessWindowDays"),
    highSignalThreshold: readNumberMetadata(approvedDatasetMetadata, "highSignalThreshold"),
    latestApprovedAt: readString(approvedDatasetMetadata, "latestApprovedAt"),
    oldestApprovedAt: readString(approvedDatasetMetadata, "oldestApprovedAt"),
  };

  if (!approvedDataset || !hasApprovedCorrectionDatasetLineage(approvedDataset.metadata)) {
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "brain.training_job.blocked_by_quality_gate",
      resourceType: "training_job",
      resourceId: null,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        status: "blocked_invalid_dataset_lineage",
        reasons: ["approved_correction_lineage_required"],
      },
    });
    return {
      job: null,
      created: false,
      reason: "approved_correction_lineage_required" as const,
      elyanModel: elyanModelPolicy,
      elyanProviderPlan,
    };
  }

  const rows = await app.db
    .insert(trainingJobs)
    .values({
      ownerUserId: null,
      scope: "shared",
      name: "Elyan continuous brain refresh",
      kind: "lora",
      status: "queued",
      baseModel: profile.chat.resolvedBaseModel || profile.chat.configuredBaseModel || app.config.ELYAN_SHARED_BRAIN_MODEL.trim() || "llama3.2",
      datasetManifestId: approvedDataset.id,
      config: {
        bootstrap: false,
        source: "continuous_refresh",
        trigger: "manual",
        trainingBackend: SHARED_TRAINING_BACKEND,
        adapterStrategy: SHARED_TRAINING_ADAPTER_STRATEGY,
        adapterMode: SHARED_TRAINING_ADAPTER_MODE,
        serverBrainName: profile.chat.serverBrainName,
        sharedBrainDeviceId: sharedBrainDevice,
        activeSharedModelId: profile.training.pipeline.promotion.activeSharedModelId,
        activeUserModelId: profile.chat.activeUserModel?.id ?? null,
        datasetManifestId: approvedDataset.id,
        datasetManifestStatus: approvedDataset.status,
        trainingPlan: SHARED_TRAINING_PLAN,
        learningSnapshot: {
          safeLearningEvents: profile.training.pipeline.continuousImprovement.safeLearningEvents,
          routingSignals: profile.training.signalSummary.routingSignals,
          bridgeSignals: profile.training.signalSummary.bridgeSignals,
          bridgeReadiness: profile.training.pipeline.bridgeReadiness,
          runtimeReady: profile.training.pipeline.runtimeReady,
          recentFeedbackSummary: profile.learning.recentFeedbackSummary,
          signalFreshness: profile.training.signalFreshness,
          qualityGate: queueQualityGate,
          correctionDataset: {
            datasetId: approvedDataset.id,
            datasetVersion: approvedDatasetVersion,
            ...approvedDatasetCompaction,
          },
          queueEligibility: {
            status: queueQualityGate.status,
            reasons: queueQualityGate.reasons,
          },
        },
        evalBaseline: {
          latestRunAt: benchmarkSummary.latestRunAt,
          latestStatus: benchmarkSummary.latestStatus,
          latestOverallScore: benchmarkSummary.latestOverallScore,
          latestBoundaryScore: benchmarkSummary.latestBoundaryScore,
          latestReasoningScore: benchmarkSummary.latestReasoningScore,
          latestClarificationScore: benchmarkSummary.latestClarificationScore,
          latestToolUseScore: benchmarkSummary.latestToolUseScore,
          latestLatencyScore: benchmarkSummary.latestLatencyScore,
          caseCount: benchmarkSummary.caseCount,
        },
        qualitySignalSummary: profile.training.qualitySignalSummary,
        personaTarget: profile.training.pipeline.personaTarget,
        mobileChatFocus: profile.training.pipeline.mobileChatFocus,
        elyanModel: elyanModelPolicy,
        elyanProviderPlan,
        signalFreshness: profile.training.signalFreshness,
        datasetSnapshot: {
          datasetManifestId: approvedDataset.id,
          datasetVersion: approvedDatasetVersion,
          datasetLineage: "approved_corrections",
          ...approvedDatasetCompaction,
        },
        providerStrategy: {
          primary: app.config.ELYAN_SHARED_BRAIN_PROVIDER,
          learningProvider: "elyan",
          servingStrategy: elyanModelPolicy?.servingStrategy ?? "groq_primary_elyan_learning",
          groqRole: elyanModelPolicy?.groqRole ?? "primary",
          elyanRole: elyanModelPolicy?.elyanRole ?? "learning",
          liveRoutingEnabled: elyanProviderPlan?.liveRoutingEnabled ?? false,
          routeReason: elyanProviderPlan?.routeReason ?? "no_ready_elyan_model",
          traffic: elyanProviderPlan?.traffic ?? {
            groqPercent: 100,
            elyanShadowPercent: 0,
            elyanCanaryPercent: 0,
            elyanPrimaryPercent: 0,
          },
          fallback: ["elyan_shadow_until_quality_gate"],
          retirementPolicy: "operator_approval_after_eval_benchmark_latency_gates",
        },
        constitutionVersion: ELYAN_CONSTITUTION_VERSION,
        promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
      },
      metadata: {
        constitutionVersion: ELYAN_CONSTITUTION_VERSION,
        promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
        evalBaselineVersion: benchmarkSummary.latestRunAt,
        latestBenchmarkScore: benchmarkSummary.latestOverallScore,
        latestBoundaryScore: benchmarkSummary.latestBoundaryScore,
        approvedCorrectionDatasetId: approvedDataset.id,
        approvedCorrectionDatasetVersion: approvedDatasetVersion,
        datasetLineage: approvedDatasetCompaction.sourceLineage ?? "approved_corrections",
        datasetCompaction: approvedDatasetCompaction,
        elyanModel: elyanModelPolicy,
        elyanProviderPlan,
      },
    })
    .returning();

  const job = rows[0] ?? null;

  if (job) {
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "brain.training_job.queued",
      resourceType: "training_job",
      resourceId: job.id,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        queueGateStatus: queueQualityGate.status,
        queueGateReasons: queueQualityGate.reasons,
        source: "continuous_refresh",
        baseModel: job.baseModel,
        datasetManifestId: job.datasetManifestId ?? null,
        trainingBackend: SHARED_TRAINING_BACKEND,
        adapterStrategy: SHARED_TRAINING_ADAPTER_STRATEGY,
        adapterMode: SHARED_TRAINING_ADAPTER_MODE,
        qualitySignalSummary: profile.training.qualitySignalSummary,
        personaTarget: profile.training.pipeline.personaTarget,
        mobileChatFocus: profile.training.pipeline.mobileChatFocus,
        approvedCorrectionDatasetId: approvedDataset.id,
        approvedCorrectionDatasetVersion: approvedDatasetVersion,
        latestBenchmarkScore: benchmarkSummary.latestOverallScore,
        elyanModel: elyanModelPolicy,
        elyanProviderPlan,
      },
    });
  }

  return {
    job,
    created: true,
    reason: "queued_shared_refresh" as const,
    elyanModel: elyanModelPolicy,
    elyanProviderPlan,
  };
}

export async function listDatasetManifests(app: FastifyInstance, userId: string) {
  return app.db
    .select()
    .from(datasetManifests)
    .where(or(eq(datasetManifests.scope, "shared"), eq(datasetManifests.ownerUserId, userId)))
    .orderBy(desc(datasetManifests.updatedAt));
}

export async function createDatasetManifest(
  app: FastifyInstance,
  input: {
    userId: string;
    name: string;
    source: DatasetSource;
    format: DatasetFormat;
    scope: BrainScope;
    description?: string;
    locator?: string;
    languageTags: string[];
    recordCount: number;
    tokenEstimate: number;
    metadata: Record<string, unknown>;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const scope = assertCreatableScope(input.scope);

  const rows = await app.db
    .insert(datasetManifests)
    .values({
      ownerUserId: input.userId,
      scope,
      name: input.name,
      source: input.source,
      format: input.format,
      status: input.recordCount > 0 ? "ready" : "draft",
      description: input.description,
      locator: input.locator,
      languageTags: input.languageTags,
      recordCount: input.recordCount,
      tokenEstimate: input.tokenEstimate,
      metadata: input.metadata,
    })
    .returning();

  const dataset = rows[0];

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "brain.dataset.create",
    resourceType: "dataset_manifest",
    resourceId: dataset?.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      source: input.source,
      format: input.format,
      scope,
    },
  });

  return dataset;
}

async function ensureSharedTrainingDatasetManifest(
  app: FastifyInstance,
  input: {
    userId: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
    safeLearningEvents: number;
    routingSignals: number;
    bridgeSignals: number;
    runtimeReady: boolean;
    bridgeReadiness: boolean;
    baseModel: string;
    serverBrainName: string;
    recentFeedbackSummary: {
      thumbsUp: number;
      thumbsDown: number;
      regenerate: number;
    };
    qualitySignalSummary: {
      toneSignals: number;
      humorSignals: number;
      brevitySignals: number;
      helpfulnessSignals: number;
      taskRoutingSignals: number;
    };
    qualityGate: {
      status: string;
      reasons: string[];
      thumbsDownRate: number;
      regenerateRate: number;
      qualityCompositeScore: number;
      thresholds: Record<string, number>;
    };
  },
) {
  const existingRows = await app.db
    .select()
    .from(datasetManifests)
    .where(and(eq(datasetManifests.scope, "shared"), eq(datasetManifests.status, "ready")))
    .orderBy(desc(datasetManifests.updatedAt))
    .limit(1);

  const existingDataset = existingRows[0] ?? null;
  if (existingDataset) {
    return {
      dataset: existingDataset,
      created: false,
      reused: true,
    };
  }

  if (input.safeLearningEvents < BRAIN_QUALITY_GATE_THRESHOLDS.minSafeLearningEvents) {
    return {
      dataset: null,
      created: false,
      reused: false,
    };
  }

  const recordCount = Math.max(1, input.safeLearningEvents);
  const tokenEstimate = Math.max(256, Math.round(recordCount * 64));
  const rows = await app.db
    .insert(datasetManifests)
    .values({
      ownerUserId: null,
      scope: "shared",
      name: "Elyan shared LoRA training set",
      source: "manual_curation",
      format: "chat_jsonl",
      status: "ready",
      description:
        "Auto-generated shared dataset for PyTorch LoRA/QLoRA refresh from safe learning, routing, and bridge signals.",
      locator: "brain://shared-training/shared-lora-dataset",
      languageTags: ["tr", "en"],
      recordCount,
      tokenEstimate,
      metadata: {
        generatedBy: "brain.queueContinuousBrainTrainingJob",
        generatedFrom: "shared_learning_snapshot",
        trainingBackend: SHARED_TRAINING_BACKEND,
        adapterStrategy: SHARED_TRAINING_ADAPTER_STRATEGY,
        adapterMode: SHARED_TRAINING_ADAPTER_MODE,
        serverBrainName: input.serverBrainName,
        baseModel: input.baseModel,
        signalSummary: {
          safeLearningEvents: input.safeLearningEvents,
          routingSignals: input.routingSignals,
          bridgeSignals: input.bridgeSignals,
        },
        qualitySignalSummary: input.qualitySignalSummary,
        qualityGate: input.qualityGate,
        recentFeedbackSummary: input.recentFeedbackSummary,
        personaTarget: "warm_professional_balanced",
        mobileChatFocus: true,
        pipelineReadiness: {
          runtimeReady: input.runtimeReady,
          bridgeReadiness: input.bridgeReadiness,
        },
      },
    })
    .returning();

  const dataset = rows[0] ?? null;

  if (dataset) {
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "system",
      actorId: "elyan-brain-orchestrator",
      action: "brain.dataset.auto_create",
      resourceType: "dataset_manifest",
      resourceId: dataset.id,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        scope: "shared",
        source: "manual_curation",
        format: "chat_jsonl",
        recordCount,
        tokenEstimate,
        trainingBackend: SHARED_TRAINING_BACKEND,
        adapterStrategy: SHARED_TRAINING_ADAPTER_STRATEGY,
        adapterMode: SHARED_TRAINING_ADAPTER_MODE,
        personaTarget: "warm_professional_balanced",
        mobileChatFocus: true,
      },
    });
  }

  return {
    dataset,
    created: true,
    reused: false,
  };
}

export async function updateDatasetManifest(
  app: FastifyInstance,
  input: {
    userId: string;
    datasetId: string;
    name?: string;
    description?: string | null;
    locator?: string | null;
    status?: DatasetStatus;
    languageTags?: string[];
    recordCount?: number;
    tokenEstimate?: number;
    metadata?: Record<string, unknown>;
  },
) {
  const rows = await app.db
    .update(datasetManifests)
    .set({
      name: input.name,
      description: input.description,
      locator: input.locator,
      status: input.status,
      languageTags: input.languageTags,
      recordCount: input.recordCount,
      tokenEstimate: input.tokenEstimate,
      metadata: input.metadata,
      updatedAt: new Date(),
    })
    .where(and(eq(datasetManifests.id, input.datasetId), eq(datasetManifests.ownerUserId, input.userId)))
    .returning();

  if (!rows[0]) {
    throw notFound("Dataset manifest not found");
  }

  return rows[0];
}

export async function listTrainingJobs(app: FastifyInstance, userId: string) {
  return app.db
    .select()
    .from(trainingJobs)
    .where(or(eq(trainingJobs.scope, "shared"), eq(trainingJobs.ownerUserId, userId)))
    .orderBy(desc(trainingJobs.updatedAt));
}

export async function createTrainingJob(
  app: FastifyInstance,
  input: {
    userId: string;
    name: string;
    kind: TrainingJobKind;
    scope: BrainScope;
    baseModel: string;
    datasetManifestId?: string;
    config: Record<string, unknown>;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const scope = assertCreatableScope(input.scope);

  if (input.datasetManifestId) {
    await assertDatasetAccessible(app, input.datasetManifestId, input.userId);
  }

  const rows = await app.db
    .insert(trainingJobs)
    .values({
      ownerUserId: input.userId,
      scope,
      name: input.name,
      kind: input.kind,
      status: "queued",
      baseModel: input.baseModel,
      datasetManifestId: input.datasetManifestId,
      config: input.config,
    })
    .returning();

  const job = rows[0];

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "brain.training_job.create",
    resourceType: "training_job",
    resourceId: job?.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      kind: input.kind,
      baseModel: input.baseModel,
      scope,
      datasetManifestId: input.datasetManifestId ?? null,
    },
  });

  return job;
}

export async function cancelTrainingJob(
  app: FastifyInstance,
  input: {
    userId: string;
    jobId: string;
  },
) {
  const current = await assertTrainingJobAccessible(app, input.jobId, input.userId);

  if (current.ownerUserId !== input.userId) {
    throw forbidden("Only the owner can cancel this training job");
  }

  if (["completed", "failed", "canceled"].includes(current.status)) {
    throw conflict("Training job is already terminal", {
      status: current.status,
    });
  }

  const rows = await app.db
    .update(trainingJobs)
    .set({
      status: "canceled",
      completedAt: new Date(),
      updatedAt: new Date(),
    })
    .where(and(eq(trainingJobs.id, input.jobId), eq(trainingJobs.ownerUserId, input.userId)))
    .returning();

  return rows[0];
}

export async function listModelArtifacts(app: FastifyInstance, userId: string) {
  const rows = await app.db
    .select()
    .from(modelArtifacts)
    .where(or(eq(modelArtifacts.scope, "shared"), eq(modelArtifacts.ownerUserId, userId)))
    .orderBy(desc(modelArtifacts.updatedAt));

  return rows.filter((row) => row.status !== "ready" || isCompleteReadyBrainModelArtifact(row));
}

export async function createModelArtifact(
  app: FastifyInstance,
  input: {
    userId: string;
    name: string;
    scope: BrainScope;
    trainingJobId?: string;
    provider: string;
    baseModel: string;
    adapterKind: string;
    status: ModelArtifactStatus;
    storageUri?: string;
    checksum?: string;
    metadata: Record<string, unknown>;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const scope = assertCreatableScope(input.scope);

  if (input.trainingJobId) {
    await assertTrainingJobAccessible(app, input.trainingJobId, input.userId);
  }

  assertReadyModelArtifactIntegrity({
    status: input.status,
    storageUri: input.storageUri,
    checksum: input.checksum,
    baseModel: input.baseModel,
    adapterKind: input.adapterKind,
  });

  const rows = await app.db
    .insert(modelArtifacts)
    .values({
      ownerUserId: input.userId,
      scope,
      trainingJobId: input.trainingJobId,
      name: input.name,
      provider: input.provider,
      baseModel: input.baseModel,
      adapterKind: input.adapterKind,
      status: input.status,
      storageUri: input.storageUri,
      checksum: input.checksum,
      metadata: input.metadata,
    })
    .returning();

  const artifact = rows[0];

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "brain.model_artifact.create",
    resourceType: "model_artifact",
    resourceId: artifact?.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      provider: input.provider,
      baseModel: input.baseModel,
      adapterKind: input.adapterKind,
      scope,
    },
  });

  return artifact;
}

export async function updateModelArtifact(
  app: FastifyInstance,
  input: {
    userId: string;
    artifactId: string;
    status?: ModelArtifactStatus;
    storageUri?: string | null;
    checksum?: string | null;
    metadata?: Record<string, unknown>;
  },
) {
  const existingRows = await app.db
    .select()
    .from(modelArtifacts)
    .where(and(eq(modelArtifacts.id, input.artifactId), eq(modelArtifacts.ownerUserId, input.userId)))
    .limit(1);

  const existing = existingRows[0];

  if (!existing) {
    throw notFound("Model artifact not found");
  }

  const nextStatus = input.status ?? existing.status;
  const nextStorageUri = input.storageUri === undefined ? existing.storageUri : input.storageUri;
  const nextChecksum = input.checksum === undefined ? existing.checksum : input.checksum;
  const nextMetadata = input.metadata ?? readRecord(existing.metadata) ?? {};

  assertReadyModelArtifactIntegrity({
    status: nextStatus,
    storageUri: nextStorageUri,
    checksum: nextChecksum,
    baseModel: existing.baseModel,
    adapterKind: existing.adapterKind,
  });

  const rows = await app.db
    .update(modelArtifacts)
    .set({
      status: nextStatus,
      storageUri: nextStorageUri,
      checksum: nextChecksum,
      metadata: nextMetadata,
      updatedAt: new Date(),
    })
    .where(and(eq(modelArtifacts.id, input.artifactId), eq(modelArtifacts.ownerUserId, input.userId)))
    .returning();

  return rows[0];
}

async function ensureKnowledgeDocumentDatasetManifest(
  app: FastifyInstance,
  input: {
    userId: string;
    scope: BrainScope;
    document: typeof knowledgeDocuments.$inferSelect;
    chunkCount: number;
    tokenEstimate: number;
    languageTags: string[];
    retrievalReady: boolean;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const existingRows = await app.db
    .select()
    .from(datasetManifests)
    .where(
      and(
        eq(datasetManifests.scope, input.scope),
        eq(datasetManifests.source, "document_import"),
        eq(datasetManifests.format, "document_corpus"),
        sql`${datasetManifests.metadata} ->> 'sourceDocumentId' = ${input.document.id}`,
      ),
    )
    .orderBy(desc(datasetManifests.updatedAt))
    .limit(1);

  const existingDataset = existingRows[0] ?? null;
  if (existingDataset) {
    return {
      dataset: existingDataset,
      reused: true,
    };
  }

  const rows = await app.db
    .insert(datasetManifests)
    .values({
      ownerUserId: input.scope === "shared" ? input.userId : input.userId,
      scope: input.scope,
      name: `Knowledge corpus · ${input.document.title}`,
      source: "document_import",
      format: "document_corpus",
      status: input.chunkCount > 0 ? "ready" : "draft",
      description: "Knowledge document corpus used for Elyan retrieval grounding and shared brain learning lineage.",
      locator: `brain://knowledge-documents/${input.document.id}`,
      languageTags: input.languageTags,
      recordCount: input.chunkCount,
      tokenEstimate: input.tokenEstimate,
      metadata: {
        datasetRole: "knowledge_document_corpus",
        sourceDocumentId: input.document.id,
        sourceType: input.document.sourceType,
        contentHash: input.document.contentHash,
        title: input.document.title,
        languageTags: input.languageTags,
        ingestMode: input.scope === "shared" ? "shared_global" : "user_private",
        trainingIntent: "knowledge_grounding",
        retrievalReady: input.retrievalReady,
      },
    })
    .returning();

  const dataset = rows[0] ?? null;

  if (dataset) {
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "brain.dataset.auto_create",
      resourceType: "dataset_manifest",
      resourceId: dataset.id,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        source: "document_import",
        format: "document_corpus",
        scope: input.scope,
        sourceDocumentId: input.document.id,
      },
    });
  }

  return {
    dataset,
    reused: false,
  };
}

async function ensureKnowledgeDocumentRetrievalJob(
  app: FastifyInstance,
  input: {
    userId: string;
    scope: BrainScope;
    document: typeof knowledgeDocuments.$inferSelect;
    sourceType: KnowledgeSourceType;
  },
) {
  const retrievalStatus = await getRetrievalStatus(app, input.userId);
  if (!retrievalStatus.hybridReady) {
    return {
      retrievalStatus,
      retrievalJob: null,
      reused: false,
    };
  }

  const existingIndexJobs = await app.db
    .select()
    .from(trainingJobs)
    .where(
      and(
        eq(trainingJobs.kind, "retrieval_index"),
        or(eq(trainingJobs.status, "queued"), eq(trainingJobs.status, "running")),
        sql`${trainingJobs.config} ->> 'sourceDocumentId' = ${input.document.id}`,
      ),
    )
    .limit(1);

  if (existingIndexJobs[0]) {
    return {
      retrievalStatus,
      retrievalJob: existingIndexJobs[0],
      reused: true,
    };
  }

  const rows = await app.db
    .insert(trainingJobs)
    .values({
      ownerUserId: input.userId,
      scope: input.scope,
      name: `Knowledge retrieval index refresh · ${input.document.title}`,
      kind: "retrieval_index",
      status: "queued",
      baseModel: "elyan_hash_v1",
      config: {
        sourceDocumentId: input.document.id,
        sourceType: input.sourceType,
        retrievalMode: "hybrid",
        embeddingModel: "elyan_hash_v1",
        requestedBy: "knowledge_document_ingest",
      },
      metadata: {
        datasetLineage: "document_corpus",
        trainingIntent: "knowledge_grounding",
        sourceDocumentId: input.document.id,
      },
    })
    .returning();

  return {
    retrievalStatus,
    retrievalJob: rows[0] ?? null,
    reused: false,
  };
}

export async function queueKnowledgeDocumentTrainingJob(
  app: FastifyInstance,
  input: {
    userId: string;
    documentId: string;
    isAdmin: boolean;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  if (!input.isAdmin) {
    throw forbidden("Shared Elyan knowledge learning requires admin access");
  }

  const documentRows = await app.db
    .select()
    .from(knowledgeDocuments)
    .where(eq(knowledgeDocuments.id, input.documentId))
    .limit(1);

  const document = documentRows[0] ?? null;
  if (!document) {
    throw notFound("Knowledge document not found");
  }
  if (document.scope !== "shared") {
    throw badRequest("Only shared knowledge documents can be queued for shared Elyan learning");
  }

  const datasetRows = await app.db
    .select()
    .from(datasetManifests)
    .where(
      and(
        eq(datasetManifests.scope, "shared"),
        eq(datasetManifests.source, "document_import"),
        eq(datasetManifests.format, "document_corpus"),
        sql`${datasetManifests.metadata} ->> 'sourceDocumentId' = ${document.id}`,
      ),
    )
    .orderBy(desc(datasetManifests.updatedAt))
    .limit(1);

  const dataset = datasetRows[0] ?? null;
  if (!dataset) {
    throw badRequest("Knowledge document corpus dataset is not ready yet");
  }

  const existingJobs = await app.db
    .select()
    .from(trainingJobs)
    .where(
      and(
        eq(trainingJobs.kind, "lora"),
        or(eq(trainingJobs.status, "queued"), eq(trainingJobs.status, "running")),
        sql`${trainingJobs.config} ->> 'sourceDocumentId' = ${document.id}`,
      ),
    )
    .orderBy(desc(trainingJobs.updatedAt))
    .limit(1);

  if (existingJobs[0]) {
    return {
      document,
      dataset,
      job: existingJobs[0],
      reused: true,
    };
  }

  const rows = await app.db
    .insert(trainingJobs)
    .values({
      ownerUserId: input.userId,
      scope: "shared",
      name: `Knowledge grounding refresh · ${document.title}`,
      kind: "lora",
      status: "queued",
      baseModel: app.config.ELYAN_SHARED_BRAIN_BALANCED_MODEL.trim() || app.config.ELYAN_SHARED_BRAIN_MODEL.trim() || "qwen2.5:7b-instruct-q5_K_M",
      datasetManifestId: dataset.id,
      config: {
        source: "knowledge_document_train",
        sourceDocumentId: document.id,
        sourceType: document.sourceType,
        datasetManifestId: dataset.id,
        trainingBackend: "pytorch_cpu_safe",
        adapterStrategy: "lora",
        adapterMode: "grounding_eval",
        providerStrategy: "groq_primary_direct",
        trainingIntent: "knowledge_grounding",
        autoPromote: false,
      },
      metadata: {
        datasetLineage: "document_corpus",
        datasetRole: "knowledge_document_corpus",
        sourceDocumentId: document.id,
        trainingIntent: "knowledge_grounding",
        providerStrategy: "groq_primary_direct",
        autoPromote: false,
      },
    })
    .returning();

  const job = rows[0] ?? null;

  if (job) {
    await createAuditLog(app, {
      userId: input.userId,
      actorType: "user",
      actorId: input.userId,
      action: "brain.training_job.queued",
      resourceType: "training_job",
      resourceId: job.id,
      status: "success",
      ipAddress: input.ipAddress,
      userAgent: input.userAgent,
      requestId: input.requestId,
      payload: {
        source: "knowledge_document_train",
        sourceDocumentId: document.id,
        datasetManifestId: dataset.id,
        datasetLineage: "document_corpus",
        trainingIntent: "knowledge_grounding",
        providerStrategy: "groq_primary_direct",
      },
    });
  }

  invalidateBrainProfileCache(app);
  return {
    document,
    dataset,
    job,
    reused: false,
  };
}

export async function createKnowledgeDocument(
  app: FastifyInstance,
  input: {
    userId: string;
    title: string;
    scope: BrainScope;
    sourceType: KnowledgeSourceType;
    sourceUri?: string;
    text?: string;
    chunks?: Array<KnowledgeDocumentChunkInput>;
    learningMode: "retrieval_only" | "shared_corpus_train";
    languageTags: string[];
    autoQueueTraining?: boolean;
    isAdmin: boolean;
    metadata: Record<string, unknown>;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const scope = resolveKnowledgeDocumentScope({
    scope: input.scope,
    learningMode: input.learningMode,
    isAdmin: input.isAdmin,
  });
  const shouldCreateSharedCorpus = isSharedKnowledgeLearningRequested({
    scope: input.scope,
    learningMode: input.learningMode,
  });
  const shouldAutoQueueTraining =
    input.autoQueueTraining ?? input.learningMode === "shared_corpus_train";
  const prepared = prepareKnowledgeDocument({
    text: input.text,
    chunks: input.chunks,
    languageTags: input.languageTags,
    metadata: input.metadata,
    sourceType: input.sourceType,
  });
  const languageTags = prepared.languageTags.length ? prepared.languageTags : normalizeLanguageTags(input.languageTags, prepared.summary);
  const sanitizedMetadata = sanitizeKnowledgeMetadata(app, {
    metadata: input.metadata,
    sourceUri: input.sourceUri,
    title: input.title,
    summary: prepared.summary,
  });

  const existingRows = await app.db
    .select()
    .from(knowledgeDocuments)
    .where(
      scope === "shared"
        ? and(
            eq(knowledgeDocuments.scope, scope),
            eq(knowledgeDocuments.contentHash, prepared.contentHash),
          )
        : and(
            eq(knowledgeDocuments.ownerUserId, input.userId),
            eq(knowledgeDocuments.scope, scope),
            eq(knowledgeDocuments.contentHash, prepared.contentHash),
          ),
    )
    .limit(1);

  const tokenEstimate = prepared.chunks.reduce((total, chunk) => total + chunk.tokenEstimate, 0);

  if (existingRows[0]) {
    const existingDocument = existingRows[0];
    const retrieval = await ensureKnowledgeDocumentRetrievalJob(app, {
      userId: input.userId,
      scope,
      document: existingDocument,
      sourceType: input.sourceType,
    });
    const datasetResult = shouldCreateSharedCorpus
      ? await ensureKnowledgeDocumentDatasetManifest(app, {
          userId: input.userId,
          scope,
          document: existingDocument,
          chunkCount: prepared.chunks.length,
          tokenEstimate,
          languageTags,
          retrievalReady: retrieval.retrievalStatus.hybridReady,
          requestId: input.requestId,
          ipAddress: input.ipAddress,
          userAgent: input.userAgent,
        })
      : {
          dataset: null,
          reused: false,
        };
    const trainingResult =
      shouldCreateSharedCorpus && shouldAutoQueueTraining
        ? await queueKnowledgeDocumentTrainingJob(app, {
            userId: input.userId,
            documentId: existingDocument.id,
            isAdmin: input.isAdmin,
            requestId: input.requestId,
            ipAddress: input.ipAddress,
            userAgent: input.userAgent,
          })
        : { job: null };

    invalidateBrainProfileCache(app, scope === "shared" ? null : input.userId);
    return {
      document: existingDocument,
      chunkCount: prepared.chunks.length,
      dataset: datasetResult.dataset,
      retrievalJob: retrieval.retrievalJob,
      trainingJob: trainingResult.job,
      reusedDataset: datasetResult.reused,
      reused: true,
    };
  }

  const quota = await getTrialQuotaUsage(app.db, input.userId);
  assertAttachmentQuotaAllowedFromUsage(quota, {
    requiredDocumentUploads: 1,
  });

  const insertedDocuments = await app.db
    .insert(knowledgeDocuments)
    .values({
      ownerUserId: input.userId,
      scope,
      title: input.title,
      sourceType: input.sourceType,
      status: "ready",
      sourceUri: input.sourceUri && !isPrivateSourceUri(input.sourceUri) ? input.sourceUri : null,
      contentHash: prepared.contentHash,
      summary: prepared.summary,
      metadata: {
        ...sanitizedMetadata,
        documentAnalysis: {
          sourceType: input.sourceType,
          sourceDeviceId:
            readMetadataString(readRecord(input.metadata), ["source_device_id", "sourceDeviceId"]) ?? null,
          contentHash:
            readMetadataString(readRecord(input.metadata), ["content_hash", "contentHash"]) ?? prepared.contentHash,
          chunkCount: prepared.normalization.normalizedChunkCount,
          sourceChunkCount: prepared.normalization.sourceChunkCount,
          structuredChunkCount: prepared.normalization.structuredChunkCount,
          metadataSegmentCount: prepared.normalization.metadataSegmentCount,
        },
        normalization: {
          sourceChunkCount: prepared.normalization.sourceChunkCount,
          normalizedChunkCount: prepared.normalization.normalizedChunkCount,
          duplicateChunkCount: prepared.normalization.duplicateChunkCount,
          truncatedChunkCount: prepared.normalization.truncatedChunkCount,
          inputCharacterCount: prepared.normalization.inputCharacterCount,
          normalizedCharacterCount: prepared.normalization.normalizedCharacterCount,
          compressionRatio: prepared.normalization.compressionRatio,
          structuredChunkCount: prepared.normalization.structuredChunkCount,
          metadataSegmentCount: prepared.normalization.metadataSegmentCount,
        },
        learningMode: input.learningMode,
        languageTags,
      },
    })
    .returning();

  const document = insertedDocuments[0];
  const usageIdentity = await resolveUsageIdentityContext(app.db, {
    userId: input.userId,
  });
  await recordUsageLedgerEntry(app.db, {
    userId: input.userId,
    identityId: usageIdentity.identityId,
    metric: "knowledge_document_upload",
    quantity: 1,
    documentUnits: 1,
    qualityProfile: usageIdentity.qualityProfile,
    planSnapshot: {
      planCode: usageIdentity.planCode,
      qualityProfile: usageIdentity.qualityProfile,
      scope,
      sourceType: input.sourceType,
      usageSurface: "knowledge_document",
    },
  });

  await app.db.insert(knowledgeChunks).values(
    prepared.chunks.map((chunk) => ({
      documentId: document.id,
      ownerUserId: input.userId,
      scope,
      ordinal: chunk.ordinal,
      content: chunk.content,
      tokenEstimate: chunk.tokenEstimate,
      metadata: normalizeLocalDerivedMetadata({
        ...chunk.metadata,
        sourceDocumentId: document.id,
      }),
    })),
  );

  const retrieval = await ensureKnowledgeDocumentRetrievalJob(app, {
    userId: input.userId,
    scope,
    document,
    sourceType: input.sourceType,
  });
  const datasetResult = shouldCreateSharedCorpus
    ? await ensureKnowledgeDocumentDatasetManifest(app, {
        userId: input.userId,
        scope,
        document,
        chunkCount: prepared.chunks.length,
        tokenEstimate,
        languageTags,
        retrievalReady: retrieval.retrievalStatus.hybridReady,
        requestId: input.requestId,
        ipAddress: input.ipAddress,
        userAgent: input.userAgent,
      })
    : {
        dataset: null,
        reused: false,
      };
  const trainingResult =
    shouldCreateSharedCorpus && shouldAutoQueueTraining
      ? await queueKnowledgeDocumentTrainingJob(app, {
          userId: input.userId,
          documentId: document.id,
          isAdmin: input.isAdmin,
          requestId: input.requestId,
          ipAddress: input.ipAddress,
          userAgent: input.userAgent,
        })
      : { job: null };

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "brain.knowledge_document.create",
    resourceType: "knowledge_document",
    resourceId: document.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      scope,
      sourceType: input.sourceType,
      chunkCount: prepared.chunks.length,
      learningMode: input.learningMode,
      autoQueueTraining: shouldAutoQueueTraining,
    },
  });

  invalidateBrainProfileCache(app, scope === "shared" ? null : input.userId);
  return {
    document,
    chunkCount: prepared.chunks.length,
    dataset: datasetResult.dataset,
    retrievalJob: retrieval.retrievalJob,
    trainingJob: trainingResult.job,
    reusedDataset: datasetResult.reused,
    reused: false,
  };
}

export async function searchKnowledge(
  app: FastifyInstance,
  input: {
    userId: string;
    query: string;
    limit: number;
  },
) {
  const [knowledge, memory] = await Promise.all([
    searchKnowledgeWithMode(app, input),
    searchBrainMemory(app, input),
  ]);
  const combined = [...memory.results, ...knowledge.results]
    .sort((left, right) => {
      const leftPriority =
        "memorySource" in left
          ? left.memorySource === "semantic_memory" && left.isPinned
            ? 6
            : left.memorySource === "episodic_memory" && left.staleness === "fresh"
              ? 4
              : left.memorySource === "self_model_memory" || left.memorySource === "reflective_memory"
                ? 3
                : left.memorySource === "semantic_memory"
                  ? 2
                  : 1
          : 5;
      const rightPriority =
        "memorySource" in right
          ? right.memorySource === "semantic_memory" && right.isPinned
            ? 6
            : right.memorySource === "episodic_memory" && right.staleness === "fresh"
              ? 4
              : right.memorySource === "self_model_memory" || right.memorySource === "reflective_memory"
                ? 3
                : right.memorySource === "semantic_memory"
                  ? 2
                  : 1
          : 5;
      return rightPriority - leftPriority || Number(right.score ?? 0) - Number(left.score ?? 0);
    })
    .slice(0, input.limit);
  const topResult = combined[0] ?? null;

  return {
    retrievalMode:
      memory.retrievalMode === "hybrid" || knowledge.retrievalMode === "hybrid"
        ? "hybrid"
        : "lexical_fallback",
    degradedReason: memory.degradedReason ?? knowledge.degradedReason ?? null,
    memoryRecallMode:
      topResult && "memorySource" in topResult
        ? "memory_first"
        : topResult
          ? "knowledge_first"
          : "lexical_fallback",
    results: combined,
    memoryResults: memory.results,
    knowledgeResults: knowledge.results,
  };
}

export async function listBrainMemoryRecords(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    targetUserId: string;
    isAdmin: boolean;
    includeSoftDeleted: boolean;
    limit: number;
    surface: "all" | "facts" | "episodes";
    lifecycle: Array<"active" | "contested" | "superseded" | "soft_deleted" | "stale">;
  },
) {
  return listBrainMemory(app, {
    userId: input.targetUserId,
    includeSoftDeleted: input.includeSoftDeleted,
    limit: input.limit,
    surface: input.surface,
    lifecycle: input.lifecycle,
    isAdmin: input.isAdmin,
  });
}

export async function getBrainMemoryRecord(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    targetUserId: string;
    isAdmin: boolean;
    memoryId: string;
  },
) {
  return getBrainMemoryById(app, {
    userId: input.targetUserId,
    memoryId: input.memoryId,
  });
}

export async function setBrainMemoryPinState(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    targetUserId: string;
    isAdmin: boolean;
    memoryId: string;
    pinned: boolean;
    reason: string | null;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  return setBrainMemoryPinning(app, {
    userId: input.targetUserId,
    memoryId: input.memoryId,
    pinned: input.pinned,
    reason: input.reason,
    actorUserId: input.actorUserId,
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
  });
}

export async function setBrainMemoryContestState(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    targetUserId: string;
    isAdmin: boolean;
    memoryId: string;
    supersedesMemoryId: string | null;
    reason: string | null;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  return setBrainMemoryContest(app, {
    userId: input.targetUserId,
    memoryId: input.memoryId,
    supersedesMemoryId: input.supersedesMemoryId,
    reason: input.reason,
    actorUserId: input.actorUserId,
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
  });
}

export async function softDeleteBrainMemoryRecord(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    targetUserId: string;
    isAdmin: boolean;
    memoryId: string;
    reason: string;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  return softDeleteBrainMemory(app, {
    userId: input.targetUserId,
    memoryId: input.memoryId,
    reason: input.reason,
    actorUserId: input.actorUserId,
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
  });
}

export async function updateBrainMemoryRecord(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    targetUserId: string;
    isAdmin: boolean;
    memoryId: string;
    title?: string | null;
    content: string;
    reason: string | null;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  return updateBrainMemory(app, {
    userId: input.targetUserId,
    memoryId: input.memoryId,
    title: input.title ?? null,
    content: input.content,
    reason: input.reason,
    actorUserId: input.actorUserId,
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
  });
}

export async function restoreBrainMemoryRecord(
  app: FastifyInstance,
  input: {
    actorUserId: string;
    targetUserId: string;
    isAdmin: boolean;
    memoryId: string;
    reason: string | null;
    requestId?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  return restoreBrainMemory(app, {
    userId: input.targetUserId,
    memoryId: input.memoryId,
    reason: input.reason,
    actorUserId: input.actorUserId,
    requestId: input.requestId,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
  });
}
