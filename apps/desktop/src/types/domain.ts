export type ThemeMode = "light" | "dark" | "system";
export type HealthState = "connected" | "degraded" | "offline" | "pending";
export type ProductResponseMode = "adaptive" | "concise" | "detailed";
export type ProductProviderStrategy = "local_first" | "balanced" | "verified";
export type ProductPrivacyMode = "balanced" | "maximum";
export type ProductAutomationLevel = "manual" | "assisted" | "operator";
export type ProductTone = "natural" | "warm" | "formal";
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

export interface WorkspaceSeatSummary {
  seatLimit: number;
  seatsUsed: number;
  seatsAvailable: number;
}

export interface WorkspacePermissionSummary {
  viewWorkspace: boolean;
  viewFinancials: boolean;
  manageMembers: boolean;
  manageRoles: boolean;
  manageSeats: boolean;
}

export interface WorkspaceAdminSummary {
  workspaceId: string;
  displayName: string;
  status: string;
  role: string;
  seats: WorkspaceSeatSummary;
  permissions: WorkspacePermissionSummary;
  billing?: {
    planId: string;
    status: string;
    creditsTotal: number;
  };
}

export interface WorkspaceMemberSummary {
  actorId: string;
  workspaceId: string;
  role: string;
  status: string;
  seatAssigned: boolean;
  user?: {
    userId: string;
    email: string;
    displayName: string;
    status: string;
  };
  seatAssignment?: {
    assignmentId: string;
    status: string;
    actorId: string;
    assignedBy: string;
    updatedAt?: number;
  };
}

export interface WorkspaceInviteSummary {
  inviteId: string;
  workspaceId: string;
  email: string;
  role: string;
  status: string;
  expiresAt?: number;
}

export interface BillingPlanSummary {
  id: string;
  label: string;
  status: string;
  monthlyCredits: number;
  seats: number;
  maxConnectors: number;
}

export interface TokenPackSummary {
  id: string;
  label: string;
  credits: number;
  price: number;
  currency: string;
}

export interface CreditLedgerEntrySummary {
  entryId: string;
  workspaceId: string;
  bucket: string;
  entryType: string;
  deltaCredits: number;
  balanceAfter: number;
  referenceId: string;
  createdAt: string;
  rawTimestamp?: number;
  metadata?: Record<string, unknown>;
}

export interface BillingEventSummary {
  eventId: string;
  workspaceId: string;
  provider: string;
  eventType: string;
  status: string;
  referenceId: string;
  createdAt: string;
  rawTimestamp?: number;
  payload?: Record<string, unknown>;
}

export interface BillingProfileSummary {
  workspaceId: string;
  profile: {
    fullName: string;
    email: string;
    phone: string;
    identityNumber: string;
    addressLine1: string;
    city: string;
    zipCode: string;
    country: string;
  };
  isComplete: boolean;
  missingFields: string[];
  updatedAt?: number;
}

export interface BillingCheckoutSessionSummary {
  referenceId: string;
  workspaceId: string;
  mode: "subscription" | "token_pack";
  catalogId: string;
  provider: string;
  status: string;
  providerStatus: string;
  launchUrl: string;
  paymentPageUrl: string;
  callbackUrl?: string;
  providerPaymentId?: string;
  subscriptionReferenceCode?: string;
  createdAt?: number;
  updatedAt?: number;
  completedAt?: number;
}

export interface BillingCheckoutLaunchSummary {
  launchUrl: string;
  referenceId: string;
  status: string;
  mode: "subscription" | "token_pack";
}

export interface InboxTaskExtraction {
  title: string;
  summary: string;
  taskType: CoworkMode;
  urgency: "low" | "medium" | "high";
  approvalRequired: boolean;
  actionItems: string[];
  recommendedPrompt: string;
  confidence: number;
  sourceType: string;
}

export interface InboxEventSummary {
  eventId: string;
  workspaceId: string;
  sourceType: string;
  sourceId: string;
  title: string;
  content: string;
  contentPreview: string;
  status: string;
  summary?: InboxTaskExtraction;
  metadata?: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  rawTimestamp?: number;
}

export interface WorkspaceAdminDetail {
  workspace: WorkspaceSummary;
  seats: WorkspaceSeatSummary;
  permissions: WorkspacePermissionSummary;
  currentRole: string;
  billing?: WorkspaceBillingSummary;
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

export interface ProductSettings {
  responseMode: ProductResponseMode;
  providerStrategy: ProductProviderStrategy;
  privacyMode: ProductPrivacyMode;
  automationLevel: ProductAutomationLevel;
  tone: ProductTone;
}

export interface SystemReadiness {
  status: "booting" | "ready" | "needs_attention";
  bootStage: "starting_services" | "loading_local_models" | "checking_providers" | "ready" | "needs_attention";
  runtimeReady: boolean;
  setupComplete: boolean;
  ollamaReady: boolean;
  channelConnected: boolean;
  hasRoutine: boolean;
  hasDailySummaryRun: boolean;
  connectedProvider?: string;
  connectedModel?: string;
  productivityAppsReady: boolean;
  bluebubblesReady: boolean;
  whatsappMode: "bridge" | "cloud" | "unavailable";
  applePermissions: {
    automation: boolean;
    screenCapture: boolean;
  };
  providerSummary: {
    available: number;
    authRequired: number;
    degraded: number;
  };
  platforms?: {
    activeSurfaces: number;
    configuredChannels: number;
    connectedChannels: number;
    connectedLabels: string[];
  };
  blockingIssue?: string;
}

export interface ModelDescriptor {
  modelId: string;
  displayName: string;
  providerId: string;
  installed: boolean;
  downloadable: boolean;
  size?: string;
  lastUsedAt?: string;
  capabilities: string[];
  digest?: string;
  modified?: string;
  roleAssignments?: string[];
}

export interface ExecutionLaneStatus {
  lane: "chat" | "reasoning" | "vision" | "research" | "fallback";
  activeProvider: string;
  model: string;
  fallbackActive: boolean;
  verificationState: "standard" | "verified";
  latencyBucket: "fast" | "balanced" | "slow";
}

export interface ProviderDescriptor {
  providerId: string;
  label: string;
  kind: "local" | "cloud";
  enabled: boolean;
  authState: "ready" | "auth_required" | "not_required";
  healthState: "available" | "degraded" | "rate_limited" | "unreachable";
  supportedRoles: string[];
  models: ModelDescriptor[];
  lanes: ExecutionLaneStatus[];
  endpoint?: string;
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
  collaborationTrace?: Array<{
    id: string;
    provider: string;
    model: string;
    lens: string;
    status: string;
    strategy?: string;
    source?: string;
    order?: number;
    error?: string;
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
    metadata?: Record<string, unknown>;
  }>;
  laneSummary?: {
    mode: string;
    runState?: string;
    missionState?: string;
    collaborationStrategy?: string;
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
    paymentProvider?: string;
    providerCustomerId?: string;
    providerSubscriptionId?: string;
    currentPeriodEnd?: number;
  };
  entitlements: EntitlementSnapshot;
  usage: {
    totals: Record<string, number>;
    budget: number;
    items: UsageLedgerEntry[];
  };
  creditBalance?: {
    included: number;
    purchased: number;
    total: number;
  };
  billingProfile?: BillingProfileSummary;
  activeCheckout?: BillingCheckoutSessionSummary;
  checkoutUrl?: string;
  portalUrl?: string;
  seats: number;
}

export interface CoworkHomeSnapshot {
  workspace: WorkspaceSummary;
  recentThreads: CoworkThreadSummary[];
  lastThread?: CoworkThreadSummary;
  pendingApprovals: CoworkApproval[];
  backgroundTasks: Array<{
    taskId: string;
    objective: string;
    summary: string;
    state: string;
    mode: string;
    capabilityDomain: string;
    updatedAt: string;
    rawTimestamp?: number;
  }>;
  autopilot?: {
    enabled: boolean;
    running: boolean;
    lastTickAt?: string;
    rawLastTickAt?: number;
    lastTickReason?: string;
    briefing?: string;
    suggestions: Array<{
      userId: string;
      task: string;
      description: string;
      priority: string;
      reason: string;
      confidence: number;
    }>;
    staleTasks: Array<{
      taskId: string;
      objective: string;
      state: string;
      action: string;
      ageMinutes: number;
    }>;
    interventions: Array<{
      id: string;
      prompt: string;
      ageMinutes: number;
    }>;
  };
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
  blockingIssue?: string;
  executionMode?: string;
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
  blockingIssue?: string;
  executionMode?: string;
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

export interface ConnectorExecutionResult {
  connector: string;
  action: string;
  blockingIssue?: string;
  result: Record<string, unknown>;
}

export interface ChannelField {
  name: string;
  label: string;
  required: boolean;
  secret: boolean;
}

export type ChannelSetupMode =
  | "token"
  | "bridge_qr"
  | "bridge_credentials"
  | "api_credentials"
  | "cloud_webhook"
  | "manual";

export interface ChannelCatalogEntry {
  type: string;
  label: string;
  fields: ChannelField[];
  setupMode?: ChannelSetupMode;
  supportsPairing?: boolean;
  minimalFields?: string[];
  automationHint?: string;
  notes?: string;
}

export interface ChannelSummary {
  id: string;
  type: string;
  enabled: boolean;
  mode?: string;
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

export interface ChannelPairingStatus {
  channel: string;
  mode: ChannelSetupMode;
  status: "not_configured" | "starting" | "waiting_for_scan" | "configured" | "needs_credentials" | "needs_attention" | "ready" | "unsupported";
  pending: boolean;
  ready: boolean;
  detail: string;
  instructions: string[];
  qrText?: string;
  phone?: string;
  blockingIssue?: string;
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
  backgroundTasks?: CoworkHomeSnapshot["backgroundTasks"];
  autopilot?: CoworkHomeSnapshot["autopilot"];
  billing?: WorkspaceBillingSummary;
  setupChecklist?: Array<{
    key: string;
    label: string;
    ready: boolean;
    detail?: string;
  }>;
  learningQueue?: {
    preferences: number;
    skills: number;
    routines: number;
    total: number;
    items: Array<{
      id: string;
      type: "skill" | "routine";
      title: string;
      detail: string;
      status: string;
      confidence?: number;
      deliveryChannel?: string;
      scheduleExpression?: string;
    }>;
  };
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
  presence?: {
    headline: string;
    status: string;
    liveNote: string;
    nextMove: string;
    quickReplies: string[];
    operatorNotes: Array<{
      id: string;
      title: string;
      body: string;
      tone: "info" | "success" | "warning";
    }>;
  };
  orchestration?: {
    requestText: string;
    requestClass: string;
    domain: string;
    objective: string;
    preview: string;
    primaryAction: string;
    orchestrationMode: string;
    fastPath: boolean;
    realTimeRequired: boolean;
    modelSelection: {
      provider: string;
      model: string;
      role: string;
      fallback: boolean;
    };
    collaboration: {
      enabled: boolean;
      strategy: string;
      maxModels: number;
      synthesisRole: string;
      executionStyle: string;
      lenses: Array<{
        name: string;
        instruction: string;
      }>;
    };
    integration: {
      provider: string;
      connectorName: string;
      integrationType: string;
      authStrategy: string;
      fallbackPolicy: string;
    };
    autonomy: {
      mode: string;
      shouldAsk: boolean;
      shouldResume: boolean;
    };
    taskPlan: {
      name: string;
      goal: string;
      constraints: string[];
      approvals: string[];
      evidence: string[];
      steps: Array<{
        name: string;
        kind: string;
        tool: string;
      }>;
    };
    goalGraph?: {
      workflowChain: string[];
      primaryDeliveryDomain: string;
      stageCount: number;
      complexityScore: number;
      constraints: {
        preferredOutput: string;
        urgency: string;
        qualityMode: string;
        deliverables: string[];
        requiresEvidence: boolean;
        autonomyPreference: string;
        proofFormats: string[];
        hasSchedule: boolean;
        scheduleExpression: string;
      };
      automationCandidate?: {
        type: string;
        cron: string;
        task: string;
      };
      nodes: Array<{
        id: string;
        text: string;
        domain: string;
        objective: string;
      }>;
    };
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
