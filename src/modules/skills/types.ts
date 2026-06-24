import type { SharedBrainWorkload } from "../brain/workloads.js";
import type { ResolvedAttachmentContext, ResolvedAttachmentContextChunk } from "../brain/attachment-context.js";

export const skillModelProfileValues = [
  "cheap_classification",
  "fast_reasoning",
  "long_context",
  "code_reasoning",
  "local_only",
] as const;

export type SkillModelProfile = (typeof skillModelProfileValues)[number];

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
  allowedTools: string[];
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
  attachmentContext: ResolvedAttachmentContext;
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
  workload: SharedBrainWorkload;
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
    cacheHit: boolean;
    toolCalls: string[];
    manualHintUsed: boolean;
    skillDisplay: {
      label: string;
      source: SkillRouteDecision["source"];
      status: "used";
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
    case "long_context":
      return "mobile_chat_balanced";
    case "code_reasoning":
      return "planning";
    case "local_only":
      return null;
  }
}
