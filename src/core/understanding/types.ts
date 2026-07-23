import { z } from "zod";

export const intentValues = [
  "coding",
  "debugging",
  "research",
  "writing",
  "math",
  "document",
  "image",
  "automation",
  "browser",
  "computer",
  "planning",
  "chat",
  "unknown",
] as const;

export type UnderstandingIntent = (typeof intentValues)[number];
export type PrivacyRisk = "low" | "medium" | "high";
export type LearningSignalType =
  | "preference"
  | "identity"
  | "project_context"
  | "workflow"
  | "correction"
  | "style"
  | "technical_stack"
  | "routing"
  | "bridge"
  | "episodic";
export type ContextPacketKind =
  | "health_context"
  | "calendar_context"
  | "device_context"
  | "notification_context"
  | "time_context"
  | "world_context"
  | "conversation_context";
export type ContextPacketFreshness = "fresh" | "recent" | "stale" | "unknown";
export type ContextPacketMentionPolicy = "silent" | "implicit" | "explicit_when_relevant";
export type ContextPacket = {
  kind: ContextPacketKind;
  source: "world_signal" | "conversation";
  title: string;
  summary: string;
  confidence: number;
  freshness: ContextPacketFreshness;
  privacyClass: "safe_derived" | "ephemeral" | "health_ephemeral";
  evidenceCount: number;
  createdAt: string | null;
  expiresAt: string | null;
  renderHint: "context_signal";
  signalKinds: string[];
  mentionPolicy?: ContextPacketMentionPolicy;
  relevanceReason?: string;
  allowedUse?: string[];
};
export type ContextFreshnessSummary = {
  newestContextAt: string | null;
  oldestContextAt: string | null;
  maxAgeHours: number | null;
  stalePacketCount: number;
};
export type LearningSignalScope = "user" | "account" | "project";
export type FeedbackType =
  | "thumbs_up"
  | "thumbs_down"
  | "user_correction"
  | "regenerate"
  | "task_failed"
  | "task_completed"
  | "preferred_answer";

export type FeedbackReasonTag =
  | "too_general"
  | "too_long"
  | "misunderstood"
  | "not_warm_enough"
  | "too_playful";

export type RoutingHints = {
  mode: "fast" | "research" | "task" | "local_private";
  preferredCapabilities: string[];
  avoidCloud: boolean;
  requiresLocalRuntime: boolean;
};

export const understandingEnvelopeSourceValues = [
  "typed_extractor",
  "model_fallback",
  "legacy_fallback",
] as const;

export const understandingDesiredOutputKindValues = [
  "chat_reply",
  "pdf",
  "docx",
  "xlsx",
  "table",
  "chart",
  "image",
  "svg",
  "task_result",
  "artifact",
  "action",
] as const;

export const understandingConstraintKindValues = [
  "output_format",
  "document_style",
  "document_kind",
  "layout_template",
  "footer_text",
  "signature_text",
  "sheet_name",
  "columns",
  "include_totals",
  "preserve_numbers",
  "exact_text_required",
  "language",
  "deadline",
  "approval_required",
  "execution_surface",
] as const;

export const understandingCapabilityKindValues = [
  "chat.reply",
  "document.read",
  "document.write",
  "document.export",
  "spreadsheet.write",
  "table.generate",
  "chart.generate",
  "image.read",
  "image.generate",
  "svg.generate",
  "browser.read",
  "desktop.file_access",
  "desktop.runtime",
  "automation.schedule",
  "memory.write",
  "goal.update",
] as const;

export const understandingMemoryCandidateKindValues = [
  "fact",
  "preference",
  "episode",
  "self_model",
] as const;

export const understandingRiskLevelValues = ["low", "medium", "high"] as const;

export const understandingIntentSchema = z.object({
  name: z.enum(intentValues),
  action: z.string().min(1).max(64),
  topic: z.string().max(160).optional(),
  confidence: z.number().min(0).max(1),
  source: z.enum(["typed_extractor", "semantic_classifier", "policy_rules", "legacy_fallback"]),
});

export const understandingEntitySchema = z.object({
  type: z.string().min(1).max(48),
  value: z.string().min(1).max(240),
  normalized: z.string().min(1).max(240).optional(),
  confidence: z.number().min(0).max(1),
  source: z.enum(["typed_extractor", "metadata", "attachment"]),
});

export const understandingConstraintSchema = z.object({
  kind: z.enum(understandingConstraintKindValues),
  value: z.union([
    z.string().max(500),
    z.number(),
    z.boolean(),
    z.array(z.string().max(120)).max(24),
    z.record(z.unknown()),
  ]),
  confidence: z.number().min(0).max(1),
  source: z.enum(["typed_extractor", "metadata", "attachment", "policy_rule"]),
  explicit: z.boolean(),
});

export const understandingDesiredOutputSchema = z.object({
  kind: z.enum(understandingDesiredOutputKindValues),
  format: z.string().max(32).nullable().optional(),
  target: z.enum(["chat", "artifact", "widget", "desktop"]).default("chat"),
  confidence: z.number().min(0).max(1),
  constraints: z.array(z.string().max(80)).max(24).default([]),
});

export const understandingSuccessCriterionSchema = z.object({
  kind: z.string().min(1).max(64),
  description: z.string().min(1).max(240),
  evidenceRequired: z.enum(["none", "typed_output", "artifact", "state_readback", "tool_result"]),
  confidence: z.number().min(0).max(1),
});

export const understandingAmbiguitySchema = z.object({
  kind: z.enum(["conflicting_outputs", "missing_target", "missing_format", "unclear_scope", "risk_conflict"]),
  description: z.string().min(1).max(240),
  options: z.array(z.string().min(1).max(120)).max(8).default([]),
  severity: z.enum(["low", "medium", "high"]),
});

export const understandingRiskSchema = z.object({
  privacy: z.enum(understandingRiskLevelValues),
  safety: z.enum(understandingRiskLevelValues),
  cost: z.enum(understandingRiskLevelValues),
  latency: z.enum(understandingRiskLevelValues),
  local_private: z.boolean(),
  side_effect: z.boolean(),
  prompt_injection: z.boolean(),
  reasons: z.array(z.string().min(1).max(120)).max(12).default([]),
});

export const understandingRequiredCapabilitySchema = z.object({
  name: z.enum(understandingCapabilityKindValues),
  executionSurface: z.enum(["server", "desktop", "mobile_local"]),
  permission: z.enum(["none", "read", "write", "side_effect"]),
  reason: z.string().max(180).optional(),
  confidence: z.number().min(0).max(1),
});

export const understandingMemoryCandidateSchema = z.object({
  op: z.enum(["write", "update", "forget", "none"]),
  kind: z.enum(understandingMemoryCandidateKindValues),
  key: z.string().min(1).max(80),
  value: z.string().min(1).max(500),
  confidence: z.number().min(0).max(1),
  explicit: z.boolean(),
  source: z.enum(["user_statement", "correction", "preference_request"]),
  ttlDays: z.number().int().positive().max(3650).nullable().optional(),
});

export const understandingIntentGraphSchema = z.object({
  nodes: z.array(z.object({
    id: z.string().min(1).max(80),
    kind: z.enum(["gather", "read", "analyze", "decide", "act", "write", "export", "verify", "respond"]),
    label: z.string().min(1).max(180),
    surface: z.enum(["server", "desktop", "mobile", "external", "unknown"]).default("unknown"),
    confidence: z.number().min(0).max(1),
  })).max(16).default([]),
  edges: z.array(z.object({
    from: z.string().min(1).max(80),
    to: z.string().min(1).max(80),
    reason: z.string().max(160).default(""),
  })).max(24).default([]),
}).default({ nodes: [], edges: [] });

export const understandingConversationStateSchema = z.object({
  turnKind: z.enum(["new_request", "follow_up", "correction", "continuation"]).default("new_request"),
  currentGoal: z.string().max(500).nullable().default(null),
  lastAssistantSummary: z.string().max(800).nullable().default(null),
  lastArtifactSummary: z.string().max(500).nullable().default(null),
  lastImagePrompt: z.string().max(800).nullable().default(null),
  userCorrection: z.string().max(500).nullable().default(null),
  carryForward: z.boolean().default(false),
}).default({});

export const understandingToolSkillDecisionSchema = z.object({
  selected: z.string().min(1).max(120),
  surface: z.enum(["chat", "document", "spreadsheet", "chart", "image", "desktop"]),
  workload: z.string().max(80).nullable().default(null),
  confidence: z.number().min(0).max(1),
  reasons: z.array(z.string().max(160)).max(12).default([]),
  candidates: z.array(z.object({
    id: z.string().min(1).max(120),
    surface: z.enum(["chat", "document", "spreadsheet", "chart", "image", "desktop"]),
    score: z.number().min(0).max(1),
    reasons: z.array(z.string().max(120)).max(8).default([]),
  })).max(10).default([]),
}).nullable().default(null);

export const understandingOutputContractSchema = z.object({
  operation: z.string().max(80),
  sourceReference: z.enum(["none", "current_prompt", "previous_answer", "latest_artifact", "attachment"]),
  outputKind: z.string().max(80),
  outputFormat: z.string().max(40).nullable().default(null),
  pageCount: z.number().int().positive().max(80).nullable().default(null),
  requiresArtifact: z.boolean(),
  confidence: z.number().min(0).max(1),
  reasons: z.array(z.string().max(160)).max(16).default([]),
}).nullable().default(null);

export const understandingPrivacyRoutingSchema = z.object({
  mode: z.enum(["server", "desktop_private", "hybrid", "mobile_local"]).default("server"),
  mayUseHostedModels: z.boolean().default(true),
  maySendPrivateContextToServer: z.boolean().default(false),
  visibleProviderNamesAllowed: z.boolean().default(true),
  internalProviderDisclosure: z.literal("forbidden").default("forbidden"),
  reasons: z.array(z.string().max(160)).max(12).default([]),
}).default({});

export const understandingAmbiguityPolicySchema = z.object({
  action: z.enum(["proceed_with_best_reference", "ask_clarifying_question", "fail_safe"]).default("proceed_with_best_reference"),
  reason: z.string().max(240).default(""),
  assumedReference: z.enum(["current_prompt", "previous_answer", "latest_artifact", "attachment", "none"]).default("current_prompt"),
}).default({});

export const understandingEnvelopeSchema = z.object({
  schema_version: z.literal("2026-07-understanding-envelope-v2"),
  intent: understandingIntentSchema,
  intent_graph: understandingIntentGraphSchema,
  source_reference: z.enum(["none", "current_prompt", "previous_answer", "latest_artifact", "attachment"]).default("current_prompt"),
  latest_artifact_ref: z.object({
    id: z.string().max(160).nullable().default(null),
    kind: z.string().max(80).nullable().default(null),
    summary: z.string().max(500).nullable().default(null),
  }).nullable().default(null),
  conversation_state: understandingConversationStateSchema,
  entities: z.array(understandingEntitySchema).max(32),
  constraints: z.array(understandingConstraintSchema).max(48),
  desired_outputs: z.array(understandingDesiredOutputSchema).max(12),
  success_criteria: z.array(understandingSuccessCriterionSchema).max(16),
  ambiguities: z.array(understandingAmbiguitySchema).max(12),
  ambiguity_policy: understandingAmbiguityPolicySchema,
  risk: understandingRiskSchema,
  privacy_routing: understandingPrivacyRoutingSchema,
  required_capabilities: z.array(understandingRequiredCapabilitySchema).max(24),
  tool_skill_decision: understandingToolSkillDecisionSchema,
  output_contract: understandingOutputContractSchema,
  memory_candidates: z.array(understandingMemoryCandidateSchema).max(12),
  confidence: z.number().min(0).max(1),
  source: z.enum(understandingEnvelopeSourceValues),
});

export type UnderstandingEnvelopeSource =
  (typeof understandingEnvelopeSourceValues)[number];
export type UnderstandingDesiredOutputKind =
  (typeof understandingDesiredOutputKindValues)[number];
export type UnderstandingConstraintKind =
  (typeof understandingConstraintKindValues)[number];
export type UnderstandingRequiredCapabilityName =
  (typeof understandingCapabilityKindValues)[number];
export type UnderstandingIntentEnvelope = z.infer<typeof understandingIntentSchema>;
export type UnderstandingEntity = z.infer<typeof understandingEntitySchema>;
export type UnderstandingConstraint = z.infer<typeof understandingConstraintSchema>;
export type UnderstandingDesiredOutput = z.infer<typeof understandingDesiredOutputSchema>;
export type UnderstandingSuccessCriterion = z.infer<typeof understandingSuccessCriterionSchema>;
export type UnderstandingAmbiguity = z.infer<typeof understandingAmbiguitySchema>;
export type UnderstandingRisk = z.infer<typeof understandingRiskSchema>;
export type UnderstandingRequiredCapability = z.infer<typeof understandingRequiredCapabilitySchema>;
export type UnderstandingMemoryCandidate = z.infer<typeof understandingMemoryCandidateSchema>;
export type UnderstandingEnvelope = z.infer<typeof understandingEnvelopeSchema>;

export type ReasoningMode = "fast" | "balanced" | "deep";

export type TaskFrame = {
  goal: string;
  likelyAnswerShape: string;
  reasoningMode: ReasoningMode;
  shouldClarify: boolean;
};

export type ContinuityBoundary = {
  mode: "same_topic" | "possible_shift" | "new_topic";
  reason: string;
  carryContinuity: boolean;
};

export type ClarificationDiagnostics = {
  shouldClarify: boolean;
  ambiguityKind:
    | "none"
    | "ambiguous_followup"
    | "missing_target"
    | "conflicting_constraints"
    | "insufficient_evidence";
  reason: string;
};

export type IntentClassification = {
  primaryIntent: UnderstandingIntent;
  secondaryIntents: UnderstandingIntent[];
  requiresLocalRuntime: boolean;
  requiresRetrieval: boolean;
  requiresToolUse: boolean;
  requiresCitation: boolean;
  requiresLongRunningTask: boolean;
  privacyRisk: PrivacyRisk;
  confidence: number;
  reason: string;
  taskFrame: TaskFrame;
  ecosystemHints: string[];
  routingHints: RoutingHints;
};

export type LearningSignal = {
  type: LearningSignalType;
  key: string;
  value: string;
  confidence: number;
  scope: LearningSignalScope;
  source: "interaction" | "feedback" | "runtime" | "system";
  ttlDays: number | null;
  metadata?: Record<string, unknown>;
};

export type RetrievedMemory = {
  id: string;
  type: LearningSignalType | string;
  key: string;
  value: string;
  confidence: number;
  scope: LearningSignalScope | string;
  source: string;
  createdAt: Date;
  staleness?: "fresh" | "stale" | "contested";
  conflictStatus?: "active" | "contested" | "superseded";
  lastVerifiedAt?: Date | null;
  importanceScore?: number;
  isPinned?: boolean;
  metadata?: Record<string, unknown>;
};

export type MemoryProfileFact = {
  key: string;
  label: string;
  value: string;
  confidence: number;
  source: string;
  staleness: "fresh" | "stale" | "contested" | "unknown";
  updatedAt: string;
};

export type MemoryProfileSnapshot = {
  summary: string | null;
  identityFacts: MemoryProfileFact[];
  preferenceFacts: MemoryProfileFact[];
  projectFacts: MemoryProfileFact[];
  derivedFacts: MemoryProfileFact[];
  recentEpisodes: MemoryProfileFact[];
  safetyNotes: string[];
  memoryCount: number;
  compactedCount: number;
  lastUpdatedAt: string | null;
};

export type UserProfileSnapshot = {
  displayName: string | null;
  preferredName: string | null;
  planCode: string | null;
  subscriptionStatus: string | null;
  preferredLanguage: string | null;
};

export type DialogueUserMemorySnapshot = {
  name: string | null;
  preferredName: string | null;
  preferredLanguage: string | null;
  preferredTone: string | null;
  responseStyle: string | null;
  timezone: string | null;
  updatedAt: string | null;
};

export type UserModelEvidence = {
  key: string;
  value: string;
  source: "explicit_user" | "verified_memory" | "inferred";
  confidence: number;
  updatedAt: string;
};

export type CanonicalUserModel = {
  revision: 1;
  identity: {
    displayName: string | null;
    preferredName: string | null;
  };
  communication: {
    preferredLanguage: string | null;
    preferredTone: string | null;
    responseStyle: string | null;
  };
  locale: { timezone: string | null };
  evidence: UserModelEvidence[];
};

export type MemoryRecallPackage = {
  facts: Array<{ key: string; value: string; confidence: number; ageDays: number }>;
  episodes: Array<{ topic: string; when: string; summary: string }>;
  style: {
    preferredName: string | null;
    preferredLanguage: string | null;
    preferredTone: string | null;
    responseStyle: string | null;
  };
};

export type ActiveGoalContext = {
  id: string;
  title: string;
  description: string;
  status: "draft" | "active" | "paused" | "done" | "canceled";
  currentStep: number;
  maxSteps: number;
  progress: {
    completedSteps?: string[];
    nextAction?: string | null;
    blockers?: string[];
  };
  scheduleHint: "on_next_message" | "daily_08_00" | "every_15m" | null;
  dueAt: Date | null;
};

export type UserUnderstandingContext = {
  userId: string;
  accountId: string;
  intent: UnderstandingIntent;
  taskFrame: TaskFrame;
  ecosystemHints: string[];
  personalizationHints: string[];
  projectHints: string[];
  styleHints: string[];
  speakingStyleDirectives?: string[];
  reasoningDirectives?: string[];
  technicalHints: string[];
  safetyHints: string[];
  situationalHints: string[];
  behavioralHints: string[];
  environmentHints: string[];
  continuitySummary: {
    userGoal: string | null;
    assistantState: string | null;
    openLoops: string[];
  };
  activeGoal: ActiveGoalContext | null;
  continuityBoundary?: ContinuityBoundary;
  relationshipContextDigest: string[];
  clarificationDiagnostics: ClarificationDiagnostics;
  memoryEnabled: boolean;
  personalizationPrompt: string | null;
  memoryRelevanceSummary: string[];
  contextPackets: ContextPacket[];
  healthContextUsed: boolean;
  packetKinds: ContextPacketKind[];
  freshness: ContextFreshnessSummary;
  retrievedMemory: RetrievedMemory[];
  memorySnapshot?: MemoryProfileSnapshot;
  userProfile?: UserProfileSnapshot;
  dialogueUserMemory?: DialogueUserMemorySnapshot;
  userModel?: CanonicalUserModel;
  memoryRecall?: MemoryRecallPackage;
  cognitiveContext?: import("../../modules/brain/cognitive-context.js").CognitiveContextPacket;
  cognitiveShadow?: {
    legacyFactCount: number;
    cognitiveFactCount: number;
    keyMismatchCount: number;
    cognitiveRevision: number;
  };
  cognitiveReadMs?: number;
  /**
   * The typed interpretation produced for this turn. Keeping it on the
   * request-scoped understanding context makes the same semantic truth
   * available to routing, inference and tool policy instead of making each
   * layer reinterpret the raw user sentence.
   */
  understandingEnvelope?: UnderstandingEnvelope;
  tokenBudget: {
    maxHints: number;
    maxChars: number;
  };
};

export type UserUnderstandingResult = {
  intent: IntentClassification;
  context: UserUnderstandingContext;
  routingHints: RoutingHints;
  envelope?: UnderstandingEnvelope;
  envelopeSource?: UnderstandingEnvelopeSource;
  envelopeConfidence?: number;
};

export type TaskUnderstandingInput = {
  userId: string;
  accountId?: string;
  taskId?: string;
  title?: string;
  message: string;
  routeContext?: string;
  source?: string;
  deviceId?: string;
  metadata?: Record<string, unknown>;
};
