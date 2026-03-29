export type ThemeMode = "light" | "dark" | "system";
export type HealthState = "connected" | "degraded" | "offline" | "pending";
export type WorkflowTaskType = "document" | "presentation" | "website";
export type CoworkMode = "cowork" | WorkflowTaskType;
export type WorkflowAudience = "executive" | "developer" | "client";
export type WorkflowLanguage = "tr" | "en";
export type WorkflowTone = "premium" | "technical" | "editorial";
export type WebsiteStack = "react" | "nextjs" | "vanilla";
export type DocumentOutputMode = "docx_pdf" | "pdf" | "docx";
export type PresentationOutputMode = "pptx_pdf" | "pptx";
export type WorkflowRoutingProfile = "balanced" | "local_first" | "quality_first";
export type WorkflowReviewStrictness = "balanced" | "strict";
export type WorkflowLifecycleState =
  | "received"
  | "classified"
  | "scoped"
  | "planned"
  | "gathering_context"
  | "executing"
  | "reviewing"
  | "revising"
  | "ready_for_approval"
  | "exporting"
  | "completed"
  | "failed";
export type RunStatus =
  | "queued"
  | "planning"
  | "approval"
  | "running"
  | "verifying"
  | "completed"
  | "partial"
  | "failed";

export type AppRoute =
  | "/onboarding"
  | "/home"
  | "/command-center"
  | "/providers"
  | "/integrations"
  | "/settings"
  | "/logs";

export interface WorkspaceSummary {
  id: string;
  name: string;
  status: HealthState;
  detail?: string;
}

export interface ProviderSummary {
  id: string;
  name: string;
  model: string;
  latencyMs: number;
  usageToday: number;
  status: HealthState;
  detail?: string;
}

export interface IntegrationSummary {
  id: string;
  kind: "device" | "channel" | "devtool" | "automation";
  name: string;
  status: HealthState;
  detail: string;
}

export interface ActivityItem {
  id: string;
  title: string;
  detail: string;
  source: string;
  level: "info" | "success" | "warning" | "error";
  createdAt: string;
}

export interface RunSummary {
  id: string;
  title: string;
  status: RunStatus;
  model?: string;
  toolCount: number;
  updatedAt: string;
  summary?: string;
}

export interface CoworkTurn {
  turnId: string;
  role: "user" | "operator";
  content: string;
  createdAt: string;
  rawTimestamp?: number;
  mode: CoworkMode;
  status: string;
  missionId?: string;
  runId?: string;
  metadata?: Record<string, unknown>;
}

export interface CoworkArtifact {
  artifactId: string;
  label: string;
  path: string;
  kind: string;
  createdAt: string;
  rawTimestamp?: number;
  runId?: string;
  missionId?: string;
}

export interface CoworkApproval {
  id: string;
  title: string;
  summary: string;
  riskLevel: string;
  status: string;
  createdAt: string;
  rawTimestamp?: number;
  missionId: string;
  nodeId?: string;
  note?: string;
}

export interface CoworkThreadSummary {
  threadId: string;
  workspaceId: string;
  sessionId: string;
  title: string;
  currentMode: CoworkMode;
  status: string;
  activeRunId?: string;
  activeMissionId?: string;
  pendingApprovals: number;
  artifactCount: number;
  reviewStatus?: string;
  lastUserTurn?: CoworkTurn;
  lastOperatorTurn?: CoworkTurn;
  updatedAt: string;
  rawTimestamp?: number;
}

export interface CoworkThreadDetail extends CoworkThreadSummary {
  goal?: string;
  currentStep?: string;
  riskLevel?: string;
  toolsInUse?: string[];
  filesTouched?: string[];
  lastSuccessfulCheckpoint?: {
    checkpointId: string;
    title: string;
    workflowState?: string;
    createdAt: string;
    rawTimestamp?: number;
    summary?: Record<string, unknown>;
  };
  controlActions?: Array<{
    id: string;
    label: string;
    tone: "primary" | "secondary" | "danger";
    enabled: boolean;
  }>;
  replay?: {
    checkpoints: Array<{
      checkpointId: string;
      title: string;
      workflowState?: string;
      createdAt: string;
      rawTimestamp?: number;
      summary?: Record<string, unknown>;
    }>;
    verificationResults: Array<{
      id: string;
      status: string;
      method: string;
      createdAt: string;
      rawTimestamp?: number;
      payload?: Record<string, unknown>;
    }>;
    recoveryActions: Array<{
      id: string;
      decision: string;
      createdAt: string;
      rawTimestamp?: number;
      payload?: Record<string, unknown>;
    }>;
  };
  artifactDiffs?: Array<{
    id: string;
    artifactId: string;
    beforeHash: string;
    afterHash: string;
    createdAt: string;
    rawTimestamp?: number;
    summary?: Record<string, unknown>;
  }>;
  turns: CoworkTurn[];
  approvals: CoworkApproval[];
  artifacts: CoworkArtifact[];
  timeline: Array<{
    id: string;
    title: string;
    status: string;
    source: "mission" | "run";
    createdAt: string;
    rawTimestamp?: number;
    error?: string;
  }>;
  laneSummary?: {
    mode: string;
    runState?: string;
    missionState?: string;
    assignedAgents?: string[];
    review?: ReviewReport;
  };
}

export interface CoworkDeltaEvent {
  type: string;
  threadId?: string;
  workspaceId?: string;
  runId?: string;
  missionId?: string;
  status?: string;
  payload?: Record<string, unknown>;
}

export interface WorkspaceBillingSummary {
  workspaceId: string;
  billingCustomer: string;
  plan: {
    id: string;
    label: string;
    status: string;
  };
  subscriptionState: {
    status: string;
    stripeCustomerId?: string;
    stripeSubscriptionId?: string;
    currentPeriodEnd?: number;
  };
  entitlements: EntitlementSnapshot;
  usage: {
    totals: Record<string, number>;
    budget: number;
    items: UsageLedgerEntry[];
  };
  checkoutUrl?: string;
  portalUrl?: string;
  seats: number;
}

export interface CoworkHomeSnapshot {
  workspace: WorkspaceSummary;
  recentThreads: CoworkThreadSummary[];
  lastThread?: CoworkThreadSummary;
  pendingApprovals: CoworkApproval[];
  security: SecuritySummary;
  billing?: WorkspaceBillingSummary;
  backends: BackendSummary[];
}

export interface EntitlementSnapshot {
  maxThreads: number;
  maxConnectors: number;
  artifactExports: number;
  premiumModels: boolean;
  teamSeats: number;
  monthlyUsageBudget: number;
}

export interface UsageLedgerEntry {
  usageId: string;
  workspaceId: string;
  metric: string;
  amount: number;
  createdAt: string;
  rawTimestamp?: number;
  metadata?: Record<string, unknown>;
}

export interface ConnectorDefinition {
  connector: string;
  provider: string;
  label: string;
  category: string;
  integrationType: string;
  capabilities: string[];
  scopes: string[];
  status: HealthState | "pending" | "offline";
  accountCount: number;
  traceCount: number;
}

export interface ConnectorAccount {
  accountId: string;
  provider: string;
  accountAlias: string;
  displayName: string;
  email: string;
  status: string;
  authUrl?: string;
  grantedScopes: string[];
  workspaceId: string;
  metadata?: Record<string, unknown>;
}

export interface ConnectorHealth {
  connector: string;
  provider: string;
  status: string;
  accountCount: number;
  traceCount: number;
}

export interface ConnectorActionTrace {
  traceId: string;
  provider: string;
  connectorName: string;
  operation: string;
  status: string;
  success: boolean;
  createdAt: string;
  rawTimestamp?: number;
  metadata?: Record<string, unknown>;
}

export interface ChannelField {
  name: string;
  label: string;
  required: boolean;
  secret: boolean;
}

export interface ChannelCatalogEntry {
  type: string;
  label: string;
  fields: ChannelField[];
  notes?: string;
}

export interface ChannelSummary {
  id: string;
  type: string;
  enabled: boolean;
  status: string;
  connected: boolean;
  lastActivity?: string;
  messageMetrics?: {
    received: number;
    sent: number;
    sendFailures: number;
    processingErrors: number;
  };
  health?: Record<string, unknown>;
}

export interface ChannelTestResult {
  channel: string;
  status: string;
  connected: boolean;
  message: string;
}

export interface BackendSummary {
  id: string;
  label: string;
  active: boolean;
  available: boolean;
  detail: string;
}

export interface MetricSummary {
  label: string;
  value: string;
  meta: string;
  tone: "neutral" | "success" | "warning" | "error";
}

export interface WorkflowLaunchCard {
  id: WorkflowTaskType;
  title: string;
  description: string;
  actionLabel: string;
  agentLane: string;
  status: "ready" | "active" | "degraded";
  meta: string;
}

export interface TrustStripItem {
  id: string;
  label: string;
  value: string;
  tone: "neutral" | "success" | "warning" | "error";
  detail?: string;
}

export interface RecentArtifactSummary {
  id: string;
  title: string;
  kind: WorkflowTaskType | "run";
  status: RunStatus;
  updatedAt: string;
  summary: string;
}

export interface SecuritySummary {
  posture: string;
  deploymentScope: string;
  dataLocality: string;
  cloudPromptRedaction: boolean;
  allowCloudFallback: boolean;
  pendingApprovals: number;
  activeSessions: number;
  sessionPersistence: boolean;
  handoffPending: number;
  semanticBackend: string;
}

export interface LearningSummary {
  userId: string;
  learningMode: string;
  retentionPolicy: string;
  paused: boolean;
  optOut: boolean;
  learningScore: number;
  successRate: number;
  dominantDomain: string;
  topTopics: string[];
  recentLessons: string[];
  nextActions: Array<{
    title: string;
    reason: string;
    priority: string;
  }>;
  promptHint: string;
  signalCount: number;
  actionCount: number;
  agentCount: number;
}

export interface PrivacySummary {
  workspaceId: string;
  userId: string;
  policy: {
    allowPersonalDataLearning: boolean;
    allowWorkspaceDataLearning: boolean;
    allowOperationalDataLearning: boolean;
    allowPublicDataLearning: boolean;
    allowSecretDataLearning: boolean;
    allowGlobalAggregation: boolean;
    redactPersonalData: boolean;
    redactSecretData: boolean;
    learningScope: string;
    retentionPolicy: Record<string, unknown>;
  };
  consent: {
    consentId: string;
    scope: string;
    granted: boolean;
    source: string;
    expiresAt: number;
  };
  classificationCounts: Record<string, number>;
  learningScopeCounts: Record<string, number>;
  whatIsLearned: string[];
  whatIsExcluded: string[];
  totalEntries: number;
  redactedEntries: number;
  sharedLearningEligible: number;
  recentEntries: Array<{
    entryId: string;
    sourceKind: string;
    classification: string;
    learningScope: string;
    redacted: boolean;
    text: string;
    createdAt: number;
  }>;
}

export interface PrivacyExportBundle {
  userId: string;
  workspaceId: string;
  audit: Record<string, unknown>;
  learningSummary: LearningSummary | null;
  privacy: PrivacySummary;
}

export interface WorkflowPreferences {
  language: WorkflowLanguage;
  audience: WorkflowAudience;
  tone: WorkflowTone;
  websiteStack: WebsiteStack;
  documentOutput: DocumentOutputMode;
  presentationOutput: PresentationOutputMode;
}

export interface ProjectTemplate {
  id: string;
  name: string;
  description: string;
  sessionId: string;
  preferredTaskType: WorkflowTaskType;
  routingProfile: WorkflowRoutingProfile;
  reviewStrictness: WorkflowReviewStrictness;
  preferences: Partial<WorkflowPreferences>;
}

export interface SidecarHealth {
  status: "offline" | "starting" | "healthy" | "degraded" | "stopped" | "error";
  managed: boolean;
  port: number;
  runtimeUrl: string;
  adminToken?: string | null;
  pid?: number | null;
  projectDir?: string | null;
  retries: number;
  lastError?: string | null;
  lastStartedAt?: string | null;
  lastReadyAt?: string | null;
  desktopVersion?: string;
  expectedProtocolVersion?: string;
  runtimeVersion?: string | null;
  runtimeProtocolVersion?: string | null;
  compatible?: boolean;
  compatibilityReason?: string | null;
  lastLogsExportPath?: string | null;
}

export type RuntimeConnectionState = "booting" | "connected" | "reconnecting" | "offline" | "error";

export interface WorkflowStateTransition {
  id: string;
  from: WorkflowLifecycleState;
  to: WorkflowLifecycleState;
  timestamp: string;
  traceId?: string;
}

export interface ReviewReport {
  status: "passed" | "needs_revision" | "failed";
  issues: Array<{
    severity: "low" | "medium" | "high";
    message: string;
  }>;
  recommendedAction?: string;
  score?: number;
  checklist?: Array<{
    label: string;
    status: "passed" | "warning" | "failed";
  }>;
}

export interface ArtifactManifest {
  id: string;
  taskType: WorkflowTaskType;
  primaryPath?: string;
  outputs: string[];
}

export interface ExportJob {
  id: string;
  taskType: WorkflowTaskType;
  format: string;
  status: "queued" | "running" | "completed" | "failed";
}

export interface PlatformCapabilities {
  os: "macos" | "windows" | "linux" | "unknown";
  revealInFolder: boolean;
  openArtifact: boolean;
}

export interface CommandHomeAction {
  id: string;
  label: string;
  route: AppRoute;
  tone: "primary" | "secondary";
}

export interface HomeSnapshot {
  workspace: WorkspaceSummary;
  providers: ProviderSummary[];
  integrations: IntegrationSummary[];
  recentRuns: RunSummary[];
  activity: ActivityItem[];
  metrics: {
    successRate: number;
    avgLatencyMs: number;
    activeAgents: number;
    totalActions: number;
  };
  metricCards: MetricSummary[];
  backends: BackendSummary[];
  workflowCards: WorkflowLaunchCard[];
  trustStrip: TrustStripItem[];
  recentArtifacts: RecentArtifactSummary[];
  recommendedFlow?: WorkflowTaskType;
  recentThreads?: CoworkThreadSummary[];
  lastThread?: CoworkThreadSummary;
  pendingApprovals?: CoworkApproval[];
  billing?: WorkspaceBillingSummary;
}

export type HomeSnapshotV2 = HomeSnapshot;

export interface CommandCenterSnapshot {
  threads?: CoworkThreadSummary[];
  selectedThread?: CoworkThreadDetail;
  runs: RunSummary[];
  approvals: Array<{
    id: string;
    action: string;
    priority: "critical" | "high" | "normal" | "low";
    confidence?: number;
  }>;
  outputBlocks: Array<{
    id: string;
    kind: "thinking" | "action" | "result" | "evidence" | "warning";
    title: string;
    body: string;
    meta?: string;
  }>;
  security: SecuritySummary;
  securityEvents: LogEvent[];
  controlActions?: Array<{
    id: string;
    label: string;
    tone: "primary" | "secondary" | "danger";
    enabled: boolean;
  }>;
  selectedRun?: {
    id: string;
    title: string;
    taskType?: WorkflowTaskType;
    workflowState?: WorkflowLifecycleState | string;
    artifactPath?: string;
    assignedAgents?: string[];
    launchProfile?: {
      audience?: string;
      language?: string;
      theme?: string;
      stack?: string;
      preferredFormats?: string[];
      objective?: string;
      projectTemplateId?: string;
      projectName?: string;
      routingProfile?: WorkflowRoutingProfile | string;
      reviewStrictness?: WorkflowReviewStrictness | string;
      candidateChain?: string[];
    };
    planSummary?: {
      artifactTargets: string[];
      owners: string[];
      stages: string[];
    };
    artifacts: Array<{
      path: string;
      label: string;
      kind: string;
      exists?: boolean;
    }>;
    review?: ReviewReport;
    timeline: Array<{
      id: string;
      title: string;
      status: string;
      startedAt?: number;
      duration?: number;
      error?: string;
    }>;
  };
}

export interface LogEvent {
  id: string;
  level: "info" | "success" | "warning" | "error";
  source: string;
  title: string;
  detail: string;
  timestamp: string;
  category?: "runtime" | "security";
  rawTimestamp?: number;
  payload?: Record<string, unknown>;
}
