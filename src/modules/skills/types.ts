import type { SharedBrainWorkload } from "../brain/workloads.js";
import type { ResolvedAttachmentContext, ResolvedAttachmentContextChunk } from "../brain/attachment-context.js";

export const skillModelProfileValues = [
  "cheap_classification",
  "fast_reasoning",
  "vision_reasoning",
  "document_reasoning",
  "long_context",
  "code_reasoning",
  "local_only",
] as const;

export type SkillModelProfile = (typeof skillModelProfileValues)[number];

export const skillAllowedToolValues = [
  "retrieval.search",
  "memory.query",
  "web.search",
  "web.fetch_url",
] as const;

export type SkillAllowedTool = (typeof skillAllowedToolValues)[number];

export type SkillProduces = {
  desiredOutputKinds: Array<
    | "chat_reply"
    | "pdf"
    | "docx"
    | "xlsx"
    | "table"
    | "chart"
    | "image"
    | "svg"
    | "task_result"
    | "artifact"
    | "action"
  >;
  artifactTypes: Array<
    "text" | "table" | "chart" | "svg" | "pdf" | "document" | "image_prompt"
  >;
  blockTypes: string[];
};

export type SkillDefinition = {
  id: string;
  version: string;
  active: boolean;
  name: string;
  displayName: string;
  displayDescription: string;
  slashCommand: string;
  uiCategory: "document" | "image" | "reasoning" | "local";
  requiresAttachment: boolean;
  supportedMimeTypes: string[];
  manualSelectable: boolean;
  purpose: string;
  summary: string;
  instructions: string;
  triggers: {
    phrases: string[];
    intents: string[];
    payloadTypes: string[];
  };
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
  produces: SkillProduces;
  allowedTools: SkillAllowedTool[];
  modelProfile: SkillModelProfile;
  maxInputTokens: number;
  maxOutputTokens: number;
  timeoutMs: number;
  cachePolicy: {
    enabled: boolean;
    ttlMs: number;
  };
  validation: {
    requireJson: boolean;
    repairAttempts: number;
    rejectEmptyOutput: boolean;
    minConfidence: number;
  };
};

export type SkillSummary = Pick<
  SkillDefinition,
  | "id"
  | "version"
  | "active"
  | "name"
  | "displayName"
  | "displayDescription"
  | "slashCommand"
  | "uiCategory"
  | "requiresAttachment"
  | "supportedMimeTypes"
  | "manualSelectable"
  | "purpose"
  | "summary"
  | "triggers"
  | "produces"
  | "modelProfile"
>;

export type SkillRouteDecision = {
  needsSkill: boolean;
  skillId: string | null;
  confidence: number;
  reason: string;
  source: "manual_hint" | "deterministic" | "trigger_phrase" | "payload_type" | "session_context" | "classifier" | "fallback";
};

export type SkillInput = {
  prompt: string;
  attachmentContext?: ResolvedAttachmentContext | null;
  requestMetadata?: Record<string, unknown>;
};

export type PublicSkillCatalogItem = {
  id: string;
  version: string;
  skillHint: string;
  displayName: string;
  displayDescription: string;
  slashCommand: string;
  uiCategory: SkillDefinition["uiCategory"];
  requiresAttachment: boolean;
  supportedMimeTypes: string[];
  manualSelectable: boolean;
};

export type PublicSkillCatalog = {
  enabled: boolean;
  catalogVersion: "2026-06-skill-catalog-v1";
  items: PublicSkillCatalogItem[];
};

export type SelectedSkillChunk = ResolvedAttachmentContextChunk & {
  score: number;
};

export type SkillModelCallInput = {
  prompt: string;
  /** Original user intent used by authorized knowledge adapters. */
  knowledgeQuery: string;
  /** Capability allowlist enforced before any adapter is invoked. */
  toolAllowlist: SkillAllowedTool[];
  /** Skill contract requires public-web evidence unless user/privacy policy denies it. */
  webGroundingRequired: boolean;
  workload: SharedBrainWorkload;
  outputSchema: Record<string, unknown>;
  maxOutputTokens: number;
  timeoutMs: number;
  metadata: Record<string, unknown>;
};

export type SkillModelCallResult = {
  text: string;
  provider: string;
  model: string;
  latencyMs: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  metadata: Record<string, unknown>;
};

export type SkillToolResultSummary = {
  tool: string;
  ok: boolean;
  durationMs: number | null;
  resultCount: number | null;
  errorCode: string | null;
};

export type SkillWebSourceSummary = {
  title: string;
  url: string;
  sourceHost: string | null;
  publishedAt: string | null;
};

export type SkillExecutionResult = {
  text: string;
  structuredOutput: Record<string, unknown> | null;
  provider: string;
  model: string;
  latencyMs: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  metadata: {
    skillUsed: true;
    skillId: string;
    skillVersion: string;
    skillConfidence: number;
    skillRouteSource: SkillRouteDecision["source"];
    selectedChunkHashes: string[];
    modelProfile: SkillModelProfile;
    workload: SharedBrainWorkload;
    validationStatus: "valid" | "repaired" | "failed";
    /** Set only when a provider was called but its skill output was rejected. */
    failureCode: string | null;
    cacheHit: boolean;
    toolCalls: string[];
    toolResults: SkillToolResultSummary[];
    groundingUsed: boolean;
    documentSourceCount: number;
    webGroundingUsed: boolean;
    webEvidenceSufficient: boolean;
    webSourceCount: number;
    webSources: SkillWebSourceSummary[];
    retrievalResultCount: number;
    manualHintUsed: boolean;
    skillDisplay: {
      label: string;
      source: SkillRouteDecision["source"];
      status: "used" | "failed";
    };
  };
};

export type SkillExecutionLogInput = {
  userId: string;
  taskId?: string;
  routeDecision: SkillRouteDecision;
  skill: SkillDefinition;
  inputHash: string;
  selectedChunkHashes: string[];
  provider: string | null;
  model: string | null;
  latencyMs: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cacheHit: boolean;
  validationStatus: SkillExecutionResult["metadata"]["validationStatus"];
  toolCalls: string[];
  finalStatus: "success" | "fallback" | "error";
  errorCode?: string;
  manualHintUsed?: boolean;
};

export function mapSkillModelProfileToWorkload(profile: SkillModelProfile): SharedBrainWorkload | null {
  switch (profile) {
    case "cheap_classification":
      return "intent";
    case "fast_reasoning":
      return "mobile_chat_fast";
    case "vision_reasoning":
      return "image_analyze";
    case "document_reasoning":
      return "document_analysis";
    case "long_context":
      return "mobile_chat_balanced";
    case "code_reasoning":
      return "planning";
    case "local_only":
      return null;
  }
}
