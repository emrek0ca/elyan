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
  tokenBudget: {
    maxHints: number;
    maxChars: number;
  };
};

export type UserUnderstandingResult = {
  intent: IntentClassification;
  context: UserUnderstandingContext;
  routingHints: RoutingHints;
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
