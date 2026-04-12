import type {
  ActivityItem,
  BackendSummary,
  CommandCenterSnapshot,
  ChannelCatalogEntry,
  ChannelPairingStatus,
  ChannelSummary,
  ChannelTestResult,
  ConnectorAccount,
  ConnectorActionTrace,
  ConnectorExecutionResult,
  ConnectorDefinition,
  ConnectorHealth,
  CoworkApproval,
  CoworkArtifact,
  CoworkHomeSnapshot,
  CoworkThreadDetail,
  CoworkThreadSummary,
  CoworkTurn,
  HomeSnapshotV2,
  IntegrationSummary,
  LogEvent,
  LearningSummary,
  PrivacySummary,
  MetricSummary,
  ModelDescriptor,
  ExecutionLaneStatus,
  ProviderDescriptor,
  ProviderSummary,
  RecentArtifactSummary,
  ReviewReport,
  PrivacyExportBundle,
  RunSummary,
  SecuritySummary,
  SystemReadiness,
  TrustStripItem,
  UsageLedgerEntry,
  WorkflowTaskType,
  WorkflowLaunchCard,
  WorkspaceBillingSummary,
  WorkspaceAdminDetail,
  WorkspaceAdminSummary,
  BillingCheckoutLaunchSummary,
  BillingCheckoutSessionSummary,
  BillingProfileSummary,
  BillingPlanSummary,
  BillingEventSummary,
  CreditLedgerEntrySummary,
  InboxEventSummary,
  InboxTaskExtraction,
  TokenPackSummary,
  WorkspaceInviteSummary,
  WorkspaceMemberSummary,
} from "@/types/domain";
import { apiClient } from "@/services/api/client";
import { approvalSchema, backendSchema, runSchema } from "@/services/api/contracts";

type SuccessEnvelope<T> = { success: boolean } & T;

type SecurityEnvelope = SuccessEnvelope<{
  security: {
    posture?: string;
    deployment_scope?: string;
    data_locality?: string;
    cloud_prompt_redaction?: boolean;
    allow_cloud_fallback?: boolean;
    pending_approvals?: number;
    active_sessions?: number;
    session_persistence?: boolean;
    handoff_pending?: number;
    semantic_backend?: string;
  };
}>;

type LearningEnvelope = SuccessEnvelope<{
  summary: {
    user_id?: string;
    learning_mode?: string;
    retention_policy?: string;
    paused?: boolean;
    opt_out?: boolean;
    learning_score?: number;
    success_rate?: number;
    dominant_domain?: string;
    top_topics?: string[];
    recent_lessons?: string[];
    next_actions?: Array<{
      title?: string;
      reason?: string;
      priority?: string;
    }>;
    prompt_hint?: string;
    signal_count?: number;
    action_count?: number;
    agent_count?: number;
  };
}>;

type PrivacyEnvelope = SuccessEnvelope<{
  summary: Record<string, unknown>;
}>;

type PrivacyExportEnvelope = SuccessEnvelope<{
  export?: {
    audit?: Record<string, unknown>;
    privacy?: {
      user_id?: string;
      workspace_id?: string;
      learning_summary?: Record<string, unknown> | null;
      privacy?: Record<string, unknown>;
    };
  };
}> & {
  ok?: boolean;
};

function toRunStatus(status?: string): RunSummary["status"] {
  switch ((status || "").toLowerCase()) {
    case "received":
    case "classified":
    case "scoped":
    case "planned":
    case "gathering_context":
      return "planning";
    case "ready_for_approval":
      return "approval";
    case "reviewing":
    case "revising":
      return "verifying";
    case "exporting":
    case "executing":
      return "running";
    case "completed":
      return "completed";
    case "cancelled":
    case "failed":
    case "error":
      return "failed";
    case "pending":
    case "queued":
      return "queued";
    case "running":
      return "running";
    default:
      return "planning";
  }
}

function formatTime(value?: number): string {
  if (!value) {
    return "Now";
  }
  try {
    return new Date(value * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "Now";
  }
}

function formatDateTime(value?: number): string {
  if (!value) {
    return "Now";
  }
  try {
    return new Date(value * 1000).toLocaleString([], { hour: "2-digit", minute: "2-digit", month: "short", day: "numeric" });
  } catch {
    return "Now";
  }
}

async function safeRequest<T>(path: string): Promise<T | null> {
  try {
    return await apiClient.request<T>(path);
  } catch {
    return null;
  }
}

async function safePost<T>(path: string, body: Record<string, unknown>): Promise<T | null> {
  try {
    return await apiClient.request<T>(path, {
      method: "POST",
      body,
    });
  } catch {
    return null;
  }
}

const memoryCache = new Map<string, { expiresAt: number; value: unknown }>();
const inflightRequests = new Map<string, Promise<unknown>>();

function invalidateMemoryCache(prefixes: string[]) {
  for (const key of Array.from(memoryCache.keys())) {
    if (prefixes.some((prefix) => key.startsWith(prefix))) {
      memoryCache.delete(key);
    }
  }
}

async function withMemoryCache<T>(key: string, ttlMs: number, loader: () => Promise<T>): Promise<T> {
  const now = Date.now();
  const cached = memoryCache.get(key);
  if (cached && cached.expiresAt > now) {
    return cached.value as T;
  }
  const active = inflightRequests.get(key);
  if (active) {
    return (await active) as T;
  }
  const request = loader()
    .then((value) => {
      memoryCache.set(key, { expiresAt: Date.now() + ttlMs, value });
      inflightRequests.delete(key);
      return value;
    })
    .catch((error) => {
      inflightRequests.delete(key);
      throw error;
    });
  inflightRequests.set(key, request);
  return (await request) as T;
}

const DEFAULT_SECURITY_SUMMARY: SecuritySummary = {
  posture: "balanced",
  deploymentScope: "single_user_local_first",
  dataLocality: "local_only",
  cloudPromptRedaction: true,
  allowCloudFallback: true,
  pendingApprovals: 0,
  activeSessions: 1,
  sessionPersistence: true,
  handoffPending: 0,
  semanticBackend: "unknown",
};

const DEFAULT_INTEGRATIONS: IntegrationSummary[] = [
  { id: "desktop", kind: "device", name: "Desktop runtime", status: "connected", detail: "Canonical desktop shell" },
  { id: "gateway", kind: "automation", name: "Gateway", status: "connected", detail: "Local control plane" },
];

const DEFAULT_ACTIVITY: ActivityItem[] = [];
const DEFAULT_LOGS: LogEvent[] = [];

function formatTimestamp(value?: number): string {
  if (!value) {
    return "Now";
  }
  try {
    return new Date(value * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "Now";
  }
}

function normalizeTaskType(value: string): WorkflowTaskType {
  const text = String(value || "").toLowerCase();
  if (text === "presentation") {
    return "presentation";
  }
  if (text === "website") {
    return "website";
  }
  return "document";
}

function stepCount(row: { step_count?: number; steps?: Array<Record<string, unknown>> }) {
  return row.step_count ?? row.steps?.length ?? 0;
}

function toolCount(row: { tool_call_count?: number; tool_calls?: Array<Record<string, unknown>> }) {
  return row.tool_call_count ?? row.tool_calls?.length ?? 0;
}

function runState(row: { workflow_state?: string; status?: string }) {
  return row.workflow_state || row.status || "received";
}

function inferTaskTypeFromText(value: string): WorkflowTaskType {
  const text = String(value || "").toLowerCase();
  if (/(slide|deck|sunum|presentation|ppt)/.test(text)) {
    return "presentation";
  }
  if (/(site|landing|web|website|react|nextjs|scaffold)/.test(text)) {
    return "website";
  }
  return "document";
}

function mapOperatorPreview(
  preview: Record<string, unknown> | undefined,
  previewText: string,
): CommandCenterSnapshot["orchestration"] | undefined {
  if (!preview) {
    return undefined;
  }
  return {
    requestText: String(preview.request_text || previewText),
    requestClass: String(preview.request_class || ""),
    domain: String(preview.domain || ""),
    objective: String(preview.objective || ""),
    preview: String(preview.preview || ""),
    primaryAction: String(preview.primary_action || ""),
    orchestrationMode: String(preview.orchestration_mode || "single_agent"),
    fastPath: Boolean(preview.fast_path),
    realTimeRequired: Boolean(preview.real_time_required),
    modelSelection: {
      provider: String(((preview.model_selection as Record<string, unknown> | undefined) || {}).provider || ""),
      model: String(((preview.model_selection as Record<string, unknown> | undefined) || {}).model || ""),
      role: String(((preview.model_selection as Record<string, unknown> | undefined) || {}).role || ""),
      fallback: Boolean(((preview.model_selection as Record<string, unknown> | undefined) || {}).fallback),
    },
    collaboration: {
      enabled: Boolean(((preview.collaboration as Record<string, unknown> | undefined) || {}).enabled),
      strategy: String(((preview.collaboration as Record<string, unknown> | undefined) || {}).strategy || ""),
      maxModels: Number(((preview.collaboration as Record<string, unknown> | undefined) || {}).max_models || 1),
      synthesisRole: String(((preview.collaboration as Record<string, unknown> | undefined) || {}).synthesis_role || ""),
      executionStyle: String(((preview.collaboration as Record<string, unknown> | undefined) || {}).execution_style || ""),
      lenses: Array.isArray(((preview.collaboration as Record<string, unknown> | undefined) || {}).lenses)
        ? ((((preview.collaboration as Record<string, unknown> | undefined) || {}).lenses as Array<Record<string, unknown>>) || []).map((item) => ({
            name: String(item.name || ""),
            instruction: String(item.instruction || ""),
          }))
        : [],
    },
    integration: {
      provider: String(((preview.integration as Record<string, unknown> | undefined) || {}).provider || ""),
      connectorName: String(((preview.integration as Record<string, unknown> | undefined) || {}).connector_name || ""),
      integrationType: String(((preview.integration as Record<string, unknown> | undefined) || {}).integration_type || ""),
      authStrategy: String(((preview.integration as Record<string, unknown> | undefined) || {}).auth_strategy || ""),
      fallbackPolicy: String(((preview.integration as Record<string, unknown> | undefined) || {}).fallback_policy || ""),
    },
    autonomy: {
      mode: String(((preview.autonomy as Record<string, unknown> | undefined) || {}).mode || ""),
      shouldAsk: Boolean(((preview.autonomy as Record<string, unknown> | undefined) || {}).should_ask),
      shouldResume: Boolean(((preview.autonomy as Record<string, unknown> | undefined) || {}).should_resume),
    },
    taskPlan: {
      name: String(((preview.task_plan as Record<string, unknown> | undefined) || {}).name || ""),
      goal: String(((preview.task_plan as Record<string, unknown> | undefined) || {}).goal || ""),
      constraints: Array.isArray(((preview.task_plan as Record<string, unknown> | undefined) || {}).constraints)
        ? ((((preview.task_plan as Record<string, unknown> | undefined) || {}).constraints as unknown[]) || []).map((item) => String(item))
        : [],
      approvals: Array.isArray(((preview.task_plan as Record<string, unknown> | undefined) || {}).approvals)
        ? ((((preview.task_plan as Record<string, unknown> | undefined) || {}).approvals as unknown[]) || []).map((item) => String(item))
        : [],
      evidence: Array.isArray(((preview.task_plan as Record<string, unknown> | undefined) || {}).evidence)
        ? ((((preview.task_plan as Record<string, unknown> | undefined) || {}).evidence as unknown[]) || []).map((item) => String(item))
        : [],
      steps: Array.isArray(((preview.task_plan as Record<string, unknown> | undefined) || {}).steps)
        ? ((((preview.task_plan as Record<string, unknown> | undefined) || {}).steps as Array<Record<string, unknown>>) || []).map((item) => ({
            name: String(item.name || ""),
            kind: String(item.kind || ""),
            tool: String(item.tool || ""),
          }))
        : [],
    },
    goalGraph: (() => {
      const rawGoalGraph = (preview.goal_graph as Record<string, unknown> | undefined) || undefined;
      if (!rawGoalGraph) {
        return undefined;
      }
      const rawConstraints = (rawGoalGraph.constraints as Record<string, unknown> | undefined) || {};
      const rawAutomation = (rawGoalGraph.automation_candidate as Record<string, unknown> | undefined) || undefined;
      return {
        workflowChain: Array.isArray(rawGoalGraph.workflow_chain)
          ? (rawGoalGraph.workflow_chain as unknown[]).map((item) => String(item))
          : [],
        primaryDeliveryDomain: String(rawGoalGraph.primary_delivery_domain || ""),
        stageCount: Number(rawGoalGraph.stage_count || 0),
        complexityScore: Number(rawGoalGraph.complexity_score || 0),
        constraints: {
          preferredOutput: String(rawConstraints.preferred_output || ""),
          urgency: String(rawConstraints.urgency || ""),
          qualityMode: String(rawConstraints.quality_mode || ""),
          deliverables: Array.isArray(rawConstraints.deliverables)
            ? (rawConstraints.deliverables as unknown[]).map((item) => String(item))
            : [],
          requiresEvidence: Boolean(rawConstraints.requires_evidence),
          autonomyPreference: String(rawConstraints.autonomy_preference || ""),
          proofFormats: Array.isArray(rawConstraints.proof_formats)
            ? (rawConstraints.proof_formats as unknown[]).map((item) => String(item))
            : [],
          hasSchedule: Boolean(rawConstraints.has_schedule),
          scheduleExpression: String(rawConstraints.schedule_expression || ""),
        },
        automationCandidate: rawAutomation
          ? {
              type: String(rawAutomation.type || ""),
              cron: String(rawAutomation.cron || ""),
              task: String(rawAutomation.task || ""),
            }
          : undefined,
        nodes: Array.isArray(rawGoalGraph.nodes)
          ? (rawGoalGraph.nodes as Array<Record<string, unknown>>).map((item) => ({
              id: String(item.id || ""),
              text: String(item.text || ""),
              domain: String(item.domain || ""),
              objective: String(item.objective || ""),
            }))
          : [],
      };
    })(),
  };
}

export async function getOperatorPreview(
  text: string,
  sessionId?: string,
  cacheKey?: string,
): Promise<CommandCenterSnapshot["orchestration"] | undefined> {
  const previewText = String(text || "").trim();
  if (!previewText) {
    return undefined;
  }
  const previewRaw = await withMemoryCache(
    `operator-preview:${cacheKey || sessionId || "latest"}:${previewText}`,
    5000,
    () =>
      safePost<{
        ok?: boolean;
        preview?: Record<string, unknown>;
      }>("/api/v1/operator/preview", {
        text: previewText,
        session_id: sessionId || cacheKey || "desktop-preview",
      }),
  );
  return previewRaw?.ok ? mapOperatorPreview(previewRaw.preview, previewText) : undefined;
}

function toRunSummary(row: {
  run_id?: string;
  id?: string;
  intent?: string;
  status?: string;
  workflow_state?: string;
  tool_call_count?: number;
  tool_calls?: Array<Record<string, unknown>>;
  step_count?: number;
  steps?: Array<Record<string, unknown>>;
  completed_at?: number;
  started_at?: number;
  error_message?: string;
  error?: string;
}): RunSummary {
  return {
    id: row.run_id || row.id || crypto.randomUUID(),
    title: row.intent || "Unnamed run",
    status: toRunStatus(runState(row)),
    toolCount: toolCount(row),
    updatedAt: formatTime(row.completed_at || row.started_at),
    summary: row.error_message || row.error || `${stepCount(row)} steps tracked`,
  };
}

function mapSecuritySummary(payload?: SecurityEnvelope["security"]): SecuritySummary {
  return {
    posture: String(payload?.posture || "balanced"),
    deploymentScope: String(payload?.deployment_scope || "single_user_local_first"),
    dataLocality: String(payload?.data_locality || "local_only"),
    cloudPromptRedaction: Boolean(payload?.cloud_prompt_redaction ?? true),
    allowCloudFallback: Boolean(payload?.allow_cloud_fallback ?? true),
    pendingApprovals: Number(payload?.pending_approvals ?? 0),
    activeSessions: Number(payload?.active_sessions ?? 0),
    sessionPersistence: Boolean(payload?.session_persistence ?? false),
    handoffPending: Number(payload?.handoff_pending ?? 0),
    semanticBackend: String(payload?.semantic_backend || "unknown"),
  };
}

function mapLearningSummary(payload?: LearningEnvelope["summary"]): LearningSummary {
  return {
    userId: String(payload?.user_id || "local"),
    learningMode: String(payload?.learning_mode || "hybrid"),
    retentionPolicy: String(payload?.retention_policy || "long"),
    paused: Boolean(payload?.paused ?? false),
    optOut: Boolean(payload?.opt_out ?? false),
    learningScore: Number(payload?.learning_score ?? 0),
    successRate: Number(payload?.success_rate ?? 0),
    dominantDomain: String(payload?.dominant_domain || "general"),
    topTopics: Array.isArray(payload?.top_topics) ? payload?.top_topics.map((entry) => String(entry)).slice(0, 3) : [],
    recentLessons: Array.isArray(payload?.recent_lessons) ? payload?.recent_lessons.map((entry) => String(entry)).slice(0, 2) : [],
    nextActions: Array.isArray(payload?.next_actions)
      ? payload.next_actions.slice(0, 2).map((item) => ({
          title: String(item?.title || ""),
          reason: String(item?.reason || ""),
          priority: String(item?.priority || ""),
        }))
      : [],
    promptHint: String(payload?.prompt_hint || "").trim(),
    signalCount: Number(payload?.signal_count ?? 0),
    actionCount: Number(payload?.action_count ?? 0),
    agentCount: Number(payload?.agent_count ?? 0),
  };
}

function mapPrivacySummary(payload?: Record<string, unknown>): PrivacySummary {
  const policy = (payload?.policy as Record<string, unknown> | undefined) || {};
  const consent = (payload?.consent as Record<string, unknown> | undefined) || {};
  const recentEntries = Array.isArray(payload?.recent_entries)
    ? payload.recent_entries.map((item): PrivacySummary["recentEntries"][number] => ({
        entryId: String((item as Record<string, unknown>).entry_id || crypto.randomUUID()),
        sourceKind: String((item as Record<string, unknown>).source_kind || "runtime"),
        classification: String((item as Record<string, unknown>).classification || "operational"),
        learningScope: String((item as Record<string, unknown>).learning_scope || "workspace"),
        redacted: Boolean((item as Record<string, unknown>).redacted ?? true),
        text: String((item as Record<string, unknown>).text || ""),
        createdAt: Number((item as Record<string, unknown>).created_at || 0),
      }))
    : [];

  return {
    workspaceId: String(payload?.workspace_id || payload?.workspaceId || "local-workspace"),
    userId: String(payload?.user_id || payload?.userId || "local"),
    policy: {
      allowPersonalDataLearning: Boolean(policy.allow_personal_data_learning ?? false),
      allowWorkspaceDataLearning: Boolean(policy.allow_workspace_data_learning ?? true),
      allowOperationalDataLearning: Boolean(policy.allow_operational_data_learning ?? true),
      allowPublicDataLearning: Boolean(policy.allow_public_data_learning ?? true),
      allowSecretDataLearning: Boolean(policy.allow_secret_data_learning ?? false),
      allowGlobalAggregation: Boolean(policy.allow_global_aggregation ?? true),
      redactPersonalData: Boolean(policy.redact_personal_data ?? true),
      redactSecretData: Boolean(policy.redact_secret_data ?? true),
      learningScope: String(policy.learning_scope || "workspace"),
      retentionPolicy: ((payload?.retention_policy as Record<string, unknown> | undefined) || (policy.retention_policy as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
    },
    consent: {
      consentId: String(consent.consent_id || ""),
      scope: String(consent.scope || "workspace"),
      granted: Boolean(consent.granted ?? false),
      source: String(consent.source || "runtime"),
      expiresAt: Number(consent.expires_at || 0),
    },
    classificationCounts: ((payload?.classification_counts as Record<string, number> | undefined) || {}) as Record<string, number>,
    learningScopeCounts: ((payload?.learning_scope_counts as Record<string, number> | undefined) || {}) as Record<string, number>,
    whatIsLearned: Array.isArray(payload?.what_is_learned) ? payload.what_is_learned.map((item) => String(item)).slice(0, 4) : [],
    whatIsExcluded: Array.isArray(payload?.what_is_excluded) ? payload.what_is_excluded.map((item) => String(item)).slice(0, 4) : [],
    totalEntries: Number(payload?.total_entries ?? 0),
    redactedEntries: Number(payload?.redacted_entries ?? 0),
    sharedLearningEligible: Number(payload?.shared_learning_eligible ?? 0),
    recentEntries,
  };
}

function mapApproval(item: Record<string, unknown>): CoworkApproval {
  const createdAt = Number(item.created_at || 0);
  return {
    id: String(item.approval_id || item.id || crypto.randomUUID()),
    title: String(item.title || item.action || "Approval required"),
    summary: String(item.summary || item.expected_effect || "Approval required"),
    riskLevel: String(item.risk_level || "medium"),
    status: String(item.status || "pending"),
    createdAt: formatDateTime(createdAt),
    rawTimestamp: createdAt,
    missionId: String(item.mission_id || ""),
    nodeId: String(item.node_id || ""),
    note: String((item.metadata as Record<string, unknown> | undefined)?.note || ""),
  };
}

function mapTurn(item: Record<string, unknown>): CoworkTurn {
  const createdAt = Number(item.created_at || 0);
  return {
    turnId: String(item.turn_id || item.id || crypto.randomUUID()),
    role: String(item.role || "operator") === "user" ? "user" : "operator",
    content: String(item.content || ""),
    createdAt: formatDateTime(createdAt),
    rawTimestamp: createdAt,
    mode: (String(item.mode || "cowork") as CoworkTurn["mode"]) || "cowork",
    status: String(item.status || "completed"),
    missionId: String(item.mission_id || ""),
    runId: String(item.run_id || ""),
    metadata: ((item.metadata as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
  };
}

function mapArtifact(item: Record<string, unknown>): CoworkArtifact {
  const createdAt = Number(item.created_at || 0);
  return {
    artifactId: String(item.artifact_id || item.id || item.path || crypto.randomUUID()),
    label: String(item.label || item.path || "artifact"),
    path: String(item.path || ""),
    kind: String(item.kind || "artifact"),
    createdAt: formatDateTime(createdAt),
    rawTimestamp: createdAt,
    runId: String(item.run_id || ""),
    missionId: String(item.mission_id || ""),
  };
}

function mapReview(item?: Record<string, unknown>): ReviewReport | undefined {
  if (!item || typeof item !== "object") {
    return undefined;
  }
  return {
    status:
      item.status === "passed"
        ? "passed"
        : item.status === "needs_revision"
          ? "needs_revision"
          : "failed",
    issues: Array.isArray(item.issues)
      ? item.issues.map((issue) => ({
          severity: issue?.severity === "high" ? "high" : issue?.severity === "medium" ? "medium" : "low",
          message: String(issue?.message || "Review issue"),
        }))
      : [],
    recommendedAction: String(item.recommended_action || item.recommendedAction || ""),
    score: Number(item.score || 0) || undefined,
    checklist: Array.isArray(item.checklist)
      ? item.checklist.map((entry) => ({
          label: String(entry?.label || "review_check"),
          status: entry?.status === "failed" ? "failed" : entry?.status === "warning" ? "warning" : "passed",
        }))
      : [],
  };
}

function mapChannelField(item: Record<string, unknown>) {
  return {
    name: String(item.name || ""),
    label: String(item.label || item.name || ""),
    required: Boolean(item.required),
    secret: Boolean(item.secret),
  };
}

function mapChannelCatalogEntry(item: Record<string, unknown>): ChannelCatalogEntry {
  return {
    type: String(item.type || ""),
    label: String(item.label || item.type || ""),
    fields: Array.isArray(item.fields) ? item.fields.map((entry) => mapChannelField((entry || {}) as Record<string, unknown>)) : [],
    setupMode: String(item.setup_mode || "manual") as ChannelCatalogEntry["setupMode"],
    supportsPairing: Boolean(item.supports_pairing),
    minimalFields: Array.isArray(item.minimal_fields) ? item.minimal_fields.map((entry) => String(entry || "")) : [],
    automationHint: String(item.automation_hint || ""),
    notes: String(item.notes || ""),
  };
}

function mapChannelPairingStatus(item: Record<string, unknown>, fallbackChannel = "whatsapp"): ChannelPairingStatus {
  return {
    channel: String(item.channel || fallbackChannel),
    mode: String(item.mode || "manual") as ChannelPairingStatus["mode"],
    status: String(item.status || "unsupported") as ChannelPairingStatus["status"],
    pending: Boolean(item.pending),
    ready: Boolean(item.ready),
    detail: String(item.detail || ""),
    instructions: Array.isArray(item.instructions) ? item.instructions.map((entry) => String(entry || "")) : [],
    qrText: String(item.qr_text || ""),
    phone: String(item.phone || ""),
    blockingIssue: String(item.blocking_issue || ""),
  };
}

function mapChannelSummary(item: Record<string, unknown>): ChannelSummary {
  const metrics = (item.message_metrics as Record<string, unknown> | undefined) || {};
  return {
    id: String(item.id || item.type || crypto.randomUUID()),
    type: String(item.type || ""),
    enabled: Boolean(item.enabled ?? true),
    mode: String(item.mode || ""),
    status: String(item.status || "disconnected"),
    connected: Boolean(item.connected),
    lastActivity: String(item.last_activity || ""),
    messageMetrics: {
      received: Number(metrics.received || 0),
      sent: Number(metrics.sent || 0),
      sendFailures: Number(metrics.send_failures || 0),
      processingErrors: Number(metrics.processing_errors || 0),
    },
    health: ((item.health as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
  };
}

function mapThreadSummary(item: Record<string, unknown>): CoworkThreadSummary {
  const updatedAt = Number(item.updated_at || item.created_at || 0);
  const pendingApprovals = Array.isArray(item.pending_approvals) ? item.pending_approvals.length : Number(item.pending_approvals || 0);
  const artifactCount = Array.isArray(item.artifacts) ? item.artifacts.length : Number(item.artifact_count || 0);
  return {
    threadId: String(item.thread_id || crypto.randomUUID()),
    workspaceId: String(item.workspace_id || "local-workspace"),
    sessionId: String(item.session_id || "desktop"),
    title: String(item.title || "Cowork thread"),
    currentMode: (String(item.current_mode || "cowork") as CoworkThreadSummary["currentMode"]) || "cowork",
    status: String(item.status || "queued"),
    activeRunId: String(item.active_run_id || ""),
    activeMissionId: String(item.active_mission_id || ""),
    pendingApprovals,
    artifactCount,
    reviewStatus: String(item.review_status || ""),
    lastUserTurn: item.last_user_turn && typeof item.last_user_turn === "object" ? mapTurn(item.last_user_turn as Record<string, unknown>) : undefined,
    lastOperatorTurn:
      item.last_operator_turn && typeof item.last_operator_turn === "object"
        ? mapTurn(item.last_operator_turn as Record<string, unknown>)
        : undefined,
    updatedAt: formatDateTime(updatedAt),
    rawTimestamp: updatedAt,
  };
}

function mapThreadDetail(item: Record<string, unknown>): CoworkThreadDetail {
  const base = mapThreadSummary(item);
  const checkpoint = item.last_successful_checkpoint && typeof item.last_successful_checkpoint === "object"
    ? (item.last_successful_checkpoint as Record<string, unknown>)
    : null;
  return {
    ...base,
    goal: String(item.goal || base.lastUserTurn?.content || ""),
    currentStep: String(item.current_step || ""),
    riskLevel: String(item.risk_level || ""),
    toolsInUse: Array.isArray(item.tools_in_use) ? item.tools_in_use.map((entry) => String(entry)) : [],
    filesTouched: Array.isArray(item.files_touched) ? item.files_touched.map((entry) => String(entry)) : [],
    lastSuccessfulCheckpoint: checkpoint
      ? {
          checkpointId: String(checkpoint.checkpoint_id || ""),
          title: String(checkpoint.title || checkpoint.workflow_state || "checkpoint"),
          workflowState: String(checkpoint.workflow_state || ""),
          createdAt: formatDateTime(Number(checkpoint.created_at || 0)),
          rawTimestamp: Number(checkpoint.created_at || 0),
          summary: (checkpoint.summary as Record<string, unknown> | undefined) || {},
        }
      : undefined,
    controlActions: Array.isArray(item.control_actions)
      ? item.control_actions.map((action) => ({
          id: String((action as Record<string, unknown>).id || crypto.randomUUID()),
          label: String((action as Record<string, unknown>).label || "Action"),
          tone:
            String((action as Record<string, unknown>).tone || "secondary") === "danger"
              ? "danger"
              : String((action as Record<string, unknown>).tone || "secondary") === "primary"
                ? "primary"
                : "secondary",
          enabled: Boolean((action as Record<string, unknown>).enabled ?? true),
        }))
      : [],
    replay:
      item.replay && typeof item.replay === "object"
        ? {
            checkpoints: Array.isArray((item.replay as Record<string, unknown>).checkpoints)
              ? ((item.replay as Record<string, unknown>).checkpoints as Array<Record<string, unknown>>).map((entry) => ({
                  checkpointId: String(entry.checkpoint_id || ""),
                  title: String(((entry.summary as Record<string, unknown> | undefined)?.name as string | undefined) || entry.workflow_state || "checkpoint"),
                  workflowState: String(entry.workflow_state || ""),
                  createdAt: formatDateTime(Number(entry.created_at || 0)),
                  rawTimestamp: Number(entry.created_at || 0),
                  summary: (entry.summary as Record<string, unknown> | undefined) || {},
                }))
              : [],
            verificationResults: Array.isArray((item.replay as Record<string, unknown>).verification_results)
              ? ((item.replay as Record<string, unknown>).verification_results as Array<Record<string, unknown>>).map((entry) => ({
                  id: String(entry.verification_id || crypto.randomUUID()),
                  status: String(entry.status || "pending"),
                  method: String(entry.method || ""),
                  createdAt: formatDateTime(Number(entry.created_at || 0)),
                  rawTimestamp: Number(entry.created_at || 0),
                  payload: (entry.payload as Record<string, unknown> | undefined) || {},
                }))
              : [],
            recoveryActions: Array.isArray((item.replay as Record<string, unknown>).recovery_actions)
              ? ((item.replay as Record<string, unknown>).recovery_actions as Array<Record<string, unknown>>).map((entry) => ({
                  id: String(entry.recovery_id || crypto.randomUUID()),
                  decision: String(entry.decision || "retry"),
                  createdAt: formatDateTime(Number(entry.created_at || 0)),
                  rawTimestamp: Number(entry.created_at || 0),
                  payload: (entry.payload as Record<string, unknown> | undefined) || {},
                }))
              : [],
          }
        : undefined,
    artifactDiffs: Array.isArray(item.artifact_diffs)
      ? item.artifact_diffs.map((diff) => ({
          id: String((diff as Record<string, unknown>).artifact_diff_id || crypto.randomUUID()),
          artifactId: String((diff as Record<string, unknown>).artifact_id || ""),
          beforeHash: String((diff as Record<string, unknown>).before_hash || ""),
          afterHash: String((diff as Record<string, unknown>).after_hash || ""),
          createdAt: formatDateTime(Number((diff as Record<string, unknown>).created_at || 0)),
          rawTimestamp: Number((diff as Record<string, unknown>).created_at || 0),
          summary: (((diff as Record<string, unknown>).summary as Record<string, unknown> | undefined) || {}),
        }))
      : [],
    collaborationTrace: Array.isArray(item.collaboration_trace)
      ? item.collaboration_trace.map((entry) => ({
          id: String((entry as Record<string, unknown>).id || crypto.randomUUID()),
          provider: String((entry as Record<string, unknown>).provider || ""),
          model: String((entry as Record<string, unknown>).model || ""),
          lens: String((entry as Record<string, unknown>).lens || "support"),
          status: String((entry as Record<string, unknown>).status || "planned"),
          strategy: String((entry as Record<string, unknown>).strategy || ""),
          source: String((entry as Record<string, unknown>).source || ""),
          order: Number((entry as Record<string, unknown>).order || 0) || undefined,
          error: String((entry as Record<string, unknown>).error || ""),
        }))
      : [],
    turns: Array.isArray(item.turns) ? item.turns.map((turn) => mapTurn(turn as Record<string, unknown>)) : [],
    approvals: Array.isArray(item.pending_approvals) ? item.pending_approvals.map((approval) => mapApproval(approval as Record<string, unknown>)) : [],
    artifacts: Array.isArray(item.artifacts) ? item.artifacts.map((artifact) => mapArtifact(artifact as Record<string, unknown>)) : [],
    timeline: Array.isArray(item.timeline)
      ? item.timeline.map((entry) => {
          const timestamp = Number((entry as Record<string, unknown>).created_at || 0);
          return {
            id: String((entry as Record<string, unknown>).id || crypto.randomUUID()),
            title: String((entry as Record<string, unknown>).title || "Event"),
            status: String((entry as Record<string, unknown>).status || "unknown"),
            source: String((entry as Record<string, unknown>).source || "run") === "mission" ? "mission" : "run",
            createdAt: formatDateTime(timestamp),
            rawTimestamp: timestamp,
            error: String((entry as Record<string, unknown>).error || ""),
            metadata:
              (entry as Record<string, unknown>).metadata && typeof (entry as Record<string, unknown>).metadata === "object"
                ? ((entry as Record<string, unknown>).metadata as Record<string, unknown>)
                : undefined,
          };
        })
      : [],
    laneSummary:
      item.lane_summary && typeof item.lane_summary === "object"
        ? {
            mode: String((item.lane_summary as Record<string, unknown>).mode || base.currentMode),
            runState: String((item.lane_summary as Record<string, unknown>).run_state || ""),
            missionState: String((item.lane_summary as Record<string, unknown>).mission_state || ""),
            collaborationStrategy: String((item.lane_summary as Record<string, unknown>).collaboration_strategy || ""),
            assignedAgents: Array.isArray((item.lane_summary as Record<string, unknown>).assigned_agents)
              ? ((item.lane_summary as Record<string, unknown>).assigned_agents as unknown[]).map((entry) => String(entry))
              : [],
            review: mapReview(((item.lane_summary as Record<string, unknown>).review as Record<string, unknown>) || undefined),
          }
        : undefined,
  };
}

function mapEntitlements(payload: Record<string, unknown> | undefined) {
  return {
    maxThreads: Number(payload?.max_threads || 0),
    maxConnectors: Number(payload?.max_connectors || 0),
    artifactExports: Number(payload?.artifact_exports || 0),
    premiumModels: Boolean(payload?.premium_models || false),
    teamSeats: Number(payload?.team_seats || 0),
    monthlyUsageBudget: Number(payload?.monthly_usage_budget || 0),
  };
}

function mapUsageEntry(item: Record<string, unknown>): UsageLedgerEntry {
  const createdAt = Number(item.created_at || 0);
  return {
    usageId: String(item.usage_id || crypto.randomUUID()),
    workspaceId: String(item.workspace_id || "local-workspace"),
    metric: String(item.metric || "unknown"),
    amount: Number(item.amount || 0),
    createdAt: formatDateTime(createdAt),
    rawTimestamp: createdAt,
    metadata: ((item.metadata as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
  };
}

function mapSeatSummary(payload: Record<string, unknown>): WorkspaceAdminSummary["seats"] {
  return {
    seatLimit: Number(payload.seat_limit || 0),
    seatsUsed: Number(payload.seats_used || 0),
    seatsAvailable: Number(payload.seats_available || 0),
  };
}

function mapWorkspacePermissions(payload: Record<string, unknown>): WorkspaceAdminSummary["permissions"] {
  return {
    viewWorkspace: Boolean(payload.view_workspace ?? false),
    viewFinancials: Boolean(payload.view_financials ?? false),
    manageMembers: Boolean(payload.manage_members ?? false),
    manageRoles: Boolean(payload.manage_roles ?? false),
    manageSeats: Boolean(payload.manage_seats ?? false),
  };
}

function mapBillingProfile(payload: Record<string, unknown>): BillingProfileSummary {
  const profile = (payload.profile as Record<string, unknown> | undefined) || {};
  return {
    workspaceId: String(payload.workspace_id || "local-workspace"),
    profile: {
      fullName: String(profile.full_name || ""),
      email: String(profile.email || ""),
      phone: String(profile.phone || ""),
      identityNumber: String(profile.identity_number || ""),
      addressLine1: String(profile.address_line1 || ""),
      city: String(profile.city || ""),
      zipCode: String(profile.zip_code || ""),
      country: String(profile.country || ""),
    },
    isComplete: Boolean(payload.is_complete ?? false),
    missingFields: Array.isArray(payload.missing_fields) ? payload.missing_fields.map((entry) => String(entry || "")) : [],
    updatedAt: Number(payload.updated_at || 0) || undefined,
  };
}

function mapBillingCheckoutSession(payload: Record<string, unknown>): BillingCheckoutSessionSummary {
  return {
    referenceId: String(payload.reference_id || ""),
    workspaceId: String(payload.workspace_id || "local-workspace"),
    mode: String(payload.mode || "subscription") === "token_pack" ? "token_pack" : "subscription",
    catalogId: String(payload.catalog_id || ""),
    provider: String(payload.provider || "iyzico"),
    status: String(payload.status || "pending"),
    providerStatus: String(payload.provider_status || payload.status || "pending"),
    launchUrl: String(payload.launch_url || payload.payment_page_url || ""),
    paymentPageUrl: String(payload.payment_page_url || payload.launch_url || ""),
    callbackUrl: String(payload.callback_url || ""),
    providerPaymentId: String(payload.provider_payment_id || ""),
    subscriptionReferenceCode: String(payload.subscription_reference_code || ""),
    createdAt: Number(payload.created_at || 0) || undefined,
    updatedAt: Number(payload.updated_at || 0) || undefined,
    completedAt: Number(payload.completed_at || 0) || undefined,
  };
}

function mapBilling(payload: Record<string, unknown>): WorkspaceBillingSummary {
  const plan = (payload.plan as Record<string, unknown> | undefined) || {};
  const subscriptionState = (payload.subscription_state as Record<string, unknown> | undefined) || {};
  const usage = (payload.usage as Record<string, unknown> | undefined) || {};
  const balance = (payload.credit_balance as Record<string, unknown> | undefined) || {};
  return {
    workspaceId: String(payload.workspace_id || "local-workspace"),
    billingCustomer: String(payload.billing_customer || ""),
    plan: {
      id: String(plan.id || "free"),
      label: String(plan.label || "Free"),
      status: String(plan.status || "inactive"),
    },
    subscriptionState: {
      status: String(subscriptionState.status || "inactive"),
      paymentProvider: String(subscriptionState.payment_provider || "iyzico"),
      providerCustomerId: String(subscriptionState.provider_customer_id || subscriptionState.stripe_customer_id || ""),
      providerSubscriptionId: String(subscriptionState.provider_subscription_id || subscriptionState.stripe_subscription_id || ""),
      currentPeriodEnd: Number(subscriptionState.current_period_end || 0) || undefined,
    },
    entitlements: mapEntitlements((payload.entitlements as Record<string, unknown> | undefined) || {}),
    usage: {
      totals: ((usage.totals as Record<string, number> | undefined) || {}) as Record<string, number>,
      budget: Number(usage.budget || 0),
      items: Array.isArray(usage.items) ? usage.items.map((item) => mapUsageEntry(item as Record<string, unknown>)) : [],
    },
    creditBalance: {
      included: Number(balance.included || 0),
      purchased: Number(balance.purchased || 0),
      total: Number(balance.total || 0),
    },
    billingProfile:
      payload.billing_profile && typeof payload.billing_profile === "object"
        ? mapBillingProfile(payload.billing_profile as Record<string, unknown>)
        : undefined,
    activeCheckout:
      payload.active_checkout && typeof payload.active_checkout === "object"
        ? mapBillingCheckoutSession(payload.active_checkout as Record<string, unknown>)
        : undefined,
    checkoutUrl: String(payload.checkout_url || ""),
    portalUrl: String(payload.portal_url || ""),
    seats: Number(payload.seats || 1),
  };
}

function mapWorkspaceAdminSummary(item: Record<string, unknown>): WorkspaceAdminSummary {
  const billing = item.billing && typeof item.billing === "object" ? (item.billing as Record<string, unknown>) : null;
  return {
    workspaceId: String(item.workspace_id || "local-workspace"),
    displayName: String(item.display_name || item.workspace_id || "Workspace"),
    status: String(item.status || "active"),
    role: String(item.role || "member"),
    seats: mapSeatSummary(((item.seats as Record<string, unknown> | undefined) || {})),
    permissions: mapWorkspacePermissions(((item.permissions as Record<string, unknown> | undefined) || {})),
    billing: billing
      ? {
          planId: String(billing.plan_id || "free"),
          status: String(billing.status || "inactive"),
          creditsTotal: Number(billing.credits_total || 0),
        }
      : undefined,
  };
}

function mapWorkspaceSummary(item: Record<string, unknown>): WorkspaceAdminDetail["workspace"] {
  return {
    id: String(item.workspace_id || item.id || "local-workspace"),
    name: String(item.display_name || item.name || item.workspace_id || "Workspace"),
    status: String(item.status || "connected") as WorkspaceAdminDetail["workspace"]["status"],
    detail: String(item.detail || item.workspace_id || ""),
  };
}

function mapWorkspaceMember(item: Record<string, unknown>): WorkspaceMemberSummary {
  const user = item.user && typeof item.user === "object" ? (item.user as Record<string, unknown>) : null;
  const seatAssignment =
    item.seat_assignment && typeof item.seat_assignment === "object" ? (item.seat_assignment as Record<string, unknown>) : null;
  return {
    actorId: String(item.actor_id || user?.user_id || ""),
    workspaceId: String(item.workspace_id || "local-workspace"),
    role: String(item.role || "member"),
    status: String(item.status || "active"),
    seatAssigned: Boolean(item.seat_assigned ?? false),
    user: user
      ? {
          userId: String(user.user_id || ""),
          email: String(user.email || ""),
          displayName: String(user.display_name || user.email || "Workspace member"),
          status: String(user.status || "active"),
        }
      : undefined,
    seatAssignment: seatAssignment
      ? {
          assignmentId: String(seatAssignment.assignment_id || ""),
          status: String(seatAssignment.status || "active"),
          actorId: String(seatAssignment.actor_id || ""),
          assignedBy: String(seatAssignment.assigned_by || ""),
          updatedAt: Number(seatAssignment.updated_at || 0) || undefined,
        }
      : undefined,
  };
}

function mapWorkspaceInvite(item: Record<string, unknown>): WorkspaceInviteSummary {
  return {
    inviteId: String(item.invite_id || ""),
    workspaceId: String(item.workspace_id || "local-workspace"),
    email: String(item.email || ""),
    role: String(item.role || "member"),
    status: String(item.status || "pending"),
    expiresAt: Number(item.expires_at || 0) || undefined,
  };
}

function mapBillingPlan(item: Record<string, unknown>): BillingPlanSummary {
  return {
    id: String(item.plan_id || item.id || "free"),
    label: String(item.label || item.id || "Plan"),
    status: String(item.status || "inactive"),
    monthlyCredits: Number(item.included_credits || item.monthly_credits || 0),
    seats: Number(item.seat_limit || item.seats || 0),
    maxConnectors: Number(item.connector_limit || item.max_connectors || 0),
  };
}

function mapTokenPack(item: Record<string, unknown>): TokenPackSummary {
  return {
    id: String(item.pack_id || item.id || ""),
    label: String(item.label || item.id || "Token Pack"),
    credits: Number(item.credits || 0) + Number(item.bonus_credits || 0),
    price: Number(item.price_try || item.price || 0),
    currency: String(item.currency || "TRY"),
  };
}

function mapCreditLedgerEntry(item: Record<string, unknown>): CreditLedgerEntrySummary {
  const createdAt = Number(item.created_at || 0);
  return {
    entryId: String(item.entry_id || ""),
    workspaceId: String(item.workspace_id || "local-workspace"),
    bucket: String(item.bucket || "purchased"),
    entryType: String(item.entry_type || "adjustment"),
    deltaCredits: Number(item.delta_credits || 0),
    balanceAfter: Number(item.balance_after || 0),
    referenceId: String(item.reference_id || ""),
    createdAt: formatDateTime(createdAt),
    rawTimestamp: createdAt || undefined,
    metadata: ((item.metadata as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
  };
}

function mapBillingEvent(item: Record<string, unknown>): BillingEventSummary {
  const createdAt = Number(item.created_at || 0);
  return {
    eventId: String(item.event_id || crypto.randomUUID()),
    workspaceId: String(item.workspace_id || "local-workspace"),
    provider: String(item.provider || "internal"),
    eventType: String(item.event_type || "unknown"),
    status: String(item.status || "unknown"),
    referenceId: String(item.reference_id || ""),
    createdAt: formatDateTime(createdAt),
    rawTimestamp: createdAt,
    payload: ((item.payload as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
  };
}

function mapInboxTaskExtraction(item: Record<string, unknown>): InboxTaskExtraction {
  return {
    title: String(item.title || "Inbox task"),
    summary: String(item.summary || ""),
    taskType: String(item.task_type || "cowork") as InboxTaskExtraction["taskType"],
    urgency: String(item.urgency || "low") as InboxTaskExtraction["urgency"],
    approvalRequired: Boolean(item.approval_required ?? false),
    actionItems: Array.isArray(item.action_items) ? item.action_items.map((entry) => String(entry)) : [],
    recommendedPrompt: String(item.recommended_prompt || item.summary || ""),
    confidence: Number(item.confidence || 0),
    sourceType: String(item.source_type || "manual"),
  };
}

function mapInboxEvent(item: Record<string, unknown>): InboxEventSummary {
  const updatedAt = Number(item.updated_at || item.created_at || 0);
  return {
    eventId: String(item.event_id || ""),
    workspaceId: String(item.workspace_id || "local-workspace"),
    sourceType: String(item.source_type || "manual"),
    sourceId: String(item.source_id || ""),
    title: String(item.title || "Inbox event"),
    content: String(item.content || ""),
    contentPreview: String(item.content_preview || item.content || ""),
    status: String(item.status || "received"),
    summary:
      item.summary && typeof item.summary === "object"
        ? mapInboxTaskExtraction(item.summary as Record<string, unknown>)
        : undefined,
    metadata: ((item.metadata as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
    createdAt: formatDateTime(Number(item.created_at || 0)),
    updatedAt: formatDateTime(updatedAt),
    rawTimestamp: updatedAt,
  };
}

function mapConnector(item: Record<string, unknown>): ConnectorDefinition {
  return {
    connector: String(item.connector || ""),
    provider: String(item.provider || ""),
    label: String(item.label || item.connector || "Connector"),
    category: String(item.category || "work_suite"),
    integrationType: String(item.integration_type || "api"),
    capabilities: Array.isArray(item.capabilities) ? item.capabilities.map((entry) => String(entry)) : [],
    scopes: Array.isArray(item.scopes) ? item.scopes.map((entry) => String(entry)) : [],
    status: (String(item.status || "offline") as ConnectorDefinition["status"]) || "offline",
    accountCount: Number(item.account_count || 0),
    traceCount: Number(item.trace_count || 0),
    blockingIssue: String(item.blocking_issue || ""),
    executionMode: String(item.execution_mode || ""),
  };
}

function mapConnectorAccount(item: Record<string, unknown>): ConnectorAccount {
  return {
    accountId: String(item.account_id || crypto.randomUUID()),
    provider: String(item.provider || ""),
    accountAlias: String(item.account_alias || "default"),
    displayName: String(item.display_name || item.provider || "Account"),
    email: String(item.email || ""),
    status: String(item.status || "needs_input"),
    authUrl: String(item.auth_url || ""),
    grantedScopes: Array.isArray(item.granted_scopes) ? item.granted_scopes.map((entry) => String(entry)) : [],
    workspaceId: String(item.workspace_id || "local-workspace"),
    metadata: ((item.metadata as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
  };
}

function mapConnectorTrace(item: Record<string, unknown>): ConnectorActionTrace {
  const createdAt = Number(item.created_at || 0);
  return {
    traceId: String(item.trace_id || crypto.randomUUID()),
    provider: String(item.provider || ""),
    connectorName: String(item.connector_name || ""),
    operation: String(item.operation || "connector"),
    status: String(item.status || "unknown"),
    success: Boolean(item.success || false),
    createdAt: formatDateTime(createdAt),
    rawTimestamp: createdAt,
    metadata: ((item.metadata as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
  };
}

function mapConnectorHealth(item: Record<string, unknown>): ConnectorHealth {
  return {
    connector: String(item.connector || ""),
    provider: String(item.provider || ""),
    status: String(item.status || "offline"),
    accountCount: Number(item.account_count || 0),
    traceCount: Number(item.trace_count || 0),
    blockingIssue: String(item.blocking_issue || ""),
    executionMode: String(item.execution_mode || ""),
  };
}

async function getSecuritySummary(): Promise<SecuritySummary> {
  const securityRaw = await safeRequest<SecurityEnvelope>("/api/v1/security/summary");
  if (!securityRaw?.success) {
    return DEFAULT_SECURITY_SUMMARY;
  }
  return mapSecuritySummary(securityRaw.security);
}

export async function getLearningSummary(): Promise<LearningSummary | null> {
  const raw = await safeRequest<LearningEnvelope>("/api/v1/learning/summary");
  if (!raw?.success || !raw.summary) {
    return null;
  }
  return mapLearningSummary(raw.summary);
}

export async function getPrivacySummary(): Promise<PrivacySummary | null> {
  const raw = await safeRequest<PrivacyEnvelope>("/api/v1/privacy/summary");
  if (!raw?.success || !raw.summary) {
    return null;
  }
  return mapPrivacySummary(raw.summary);
}

export async function exportPrivacyData(): Promise<PrivacyExportBundle | null> {
  const raw = await safeRequest<PrivacyExportEnvelope>("/api/v1/privacy/export");
  const payload = raw?.export;
  const nested = payload?.privacy;
  if (!(raw?.ok ?? raw?.success) || !payload || !nested) {
    return null;
  }
  return {
    userId: String(nested.user_id || "local"),
    workspaceId: String(nested.workspace_id || "local-workspace"),
    audit: ((payload.audit as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
    learningSummary: nested.learning_summary ? mapLearningSummary(nested.learning_summary as LearningEnvelope["summary"]) : null,
    privacy: mapPrivacySummary(nested.privacy || {}),
  };
}

export async function deletePrivacyData(): Promise<boolean> {
  const raw = await apiClient.request<{ ok?: boolean; result?: Record<string, unknown> }>("/api/v1/privacy/delete", {
    method: "POST",
    body: {},
  });
  return Boolean(raw.ok);
}

async function getSecurityEvents(limit = 12): Promise<LogEvent[]> {
  const raw = await safeRequest<SuccessEnvelope<{ events: Array<Record<string, unknown>> }>>(`/api/v1/security/events?limit=${limit}`);
  if (!raw?.success || !Array.isArray(raw.events)) {
    return [];
  }
  return raw.events.map((item): LogEvent => {
    const timestamp = Number(item.timestamp || 0);
    return {
      id: String(item.id || crypto.randomUUID()),
      level:
        item.level === "error"
          ? "error"
          : item.level === "warning"
            ? "warning"
            : item.level === "success"
              ? "success"
              : "info",
      source: "security",
      title: String(item.title || "Security event"),
      detail: String(item.detail || item.event_type || "policy decision"),
      timestamp: formatTimestamp(timestamp),
      category: "security",
      rawTimestamp: timestamp,
      payload: (item.payload as Record<string, unknown>) || {},
    };
  });
}

export async function getCoworkHome(): Promise<CoworkHomeSnapshot> {
  const [homeRaw, security, backendsRaw] = await Promise.all([
    safeRequest<SuccessEnvelope<{
      workspace_id: string;
      recent_threads: Array<Record<string, unknown>>;
      last_thread?: Record<string, unknown>;
      pending_approvals: Array<Record<string, unknown>>;
      background_tasks?: Array<Record<string, unknown>>;
      autopilot?: Record<string, unknown>;
      billing?: Record<string, unknown>;
    }>>("/api/v1/cowork/home"),
    getSecuritySummary(),
    safeRequest<SuccessEnvelope<{ backends: Record<string, unknown> }>>("/api/v1/system/backends"),
  ]);
  const backends = backendsRaw?.success && backendsRaw.backends
    ? Object.entries(backendsRaw.backends)
        .map(([id, value]) => backendSchema.safeParse({ name: id, ...(value as object) }))
        .filter((parsed) => parsed.success)
        .map((parsed): BackendSummary => ({
          id: parsed.data.name,
          label: parsed.data.name.replace(/_/g, " "),
          active: Boolean(parsed.data.active),
          available: Boolean(parsed.data.available),
          detail: String(parsed.data.details?.role || parsed.data.details?.preferred || parsed.data.details?.mode || "Runtime surface"),
        }))
    : [];

  if (!homeRaw?.success) {
    return {
      workspace: {
        id: "local-workspace",
        name: "Local workspace",
        status: "connected",
        detail: "Cowork runtime attached",
      },
      recentThreads: [],
      lastThread: undefined,
      pendingApprovals: [],
      backgroundTasks: [],
      autopilot: undefined,
      security,
      billing: undefined,
      backends,
    };
  }

  return {
    workspace: {
      id: String(homeRaw.workspace_id || "local-workspace"),
      name: "Local workspace",
      status: "connected",
      detail: "Cowork runtime attached",
    },
    recentThreads: Array.isArray(homeRaw.recent_threads) ? homeRaw.recent_threads.map((item) => mapThreadSummary(item)) : [],
    lastThread: homeRaw.last_thread && typeof homeRaw.last_thread === "object" ? mapThreadSummary(homeRaw.last_thread) : undefined,
    pendingApprovals: Array.isArray(homeRaw.pending_approvals) ? homeRaw.pending_approvals.map((item) => mapApproval(item)) : [],
    backgroundTasks: Array.isArray(homeRaw.background_tasks)
      ? homeRaw.background_tasks.map((item) => ({
          taskId: String((item as Record<string, unknown>).task_id || crypto.randomUUID()),
          objective: String((item as Record<string, unknown>).objective || ""),
          summary: String((item as Record<string, unknown>).summary || ""),
          state: String((item as Record<string, unknown>).state || "queued"),
          mode: String((item as Record<string, unknown>).mode || "background"),
          capabilityDomain: String((item as Record<string, unknown>).capability_domain || "general"),
          updatedAt: formatDateTime(Number((item as Record<string, unknown>).updated_at || 0)),
          rawTimestamp: Number((item as Record<string, unknown>).updated_at || 0),
        }))
      : [],
    autopilot:
      homeRaw.autopilot && typeof homeRaw.autopilot === "object"
        ? {
            enabled: Boolean((homeRaw.autopilot as Record<string, unknown>).enabled ?? false),
            running: Boolean((homeRaw.autopilot as Record<string, unknown>).running ?? false),
            lastTickAt: Number((homeRaw.autopilot as Record<string, unknown>).last_tick_at || 0)
              ? formatDateTime(Number((homeRaw.autopilot as Record<string, unknown>).last_tick_at || 0))
              : undefined,
            rawLastTickAt: Number((homeRaw.autopilot as Record<string, unknown>).last_tick_at || 0) || undefined,
            lastTickReason: String((homeRaw.autopilot as Record<string, unknown>).last_tick_reason || ""),
            briefing: String((((homeRaw.autopilot as Record<string, unknown>).last_briefing as Record<string, unknown> | undefined) || {}).briefing || ""),
            suggestions: Array.isArray((homeRaw.autopilot as Record<string, unknown>).last_suggestions)
              ? (((homeRaw.autopilot as Record<string, unknown>).last_suggestions as Array<Record<string, unknown>>) || []).map((item) => ({
                  userId: String(item.user_id || "local"),
                  task: String(item.task || ""),
                  description: String(item.description || ""),
                  priority: String(item.priority || "medium"),
                  reason: String(item.reason || ""),
                  confidence: Number(item.confidence || 0),
                }))
              : [],
            staleTasks: Array.isArray((homeRaw.autopilot as Record<string, unknown>).last_task_review)
              ? (((homeRaw.autopilot as Record<string, unknown>).last_task_review as Array<Record<string, unknown>>) || []).map((item) => ({
                  taskId: String(item.task_id || crypto.randomUUID()),
                  objective: String(item.objective || ""),
                  state: String(item.state || ""),
                  action: String(item.action || ""),
                  ageMinutes: Number(item.age_minutes || 0),
                }))
              : [],
            interventions: Array.isArray((homeRaw.autopilot as Record<string, unknown>).last_interventions)
              ? (((homeRaw.autopilot as Record<string, unknown>).last_interventions as Array<Record<string, unknown>>) || []).map((item) => ({
                  id: String(item.id || crypto.randomUUID()),
                  prompt: String(item.prompt || ""),
                  ageMinutes: Number(item.age_minutes || 0),
                }))
              : [],
          }
        : undefined,
    security,
    billing: homeRaw.billing && typeof homeRaw.billing === "object" ? mapBilling(homeRaw.billing) : undefined,
    backends,
  };
}

export async function getHomeSnapshot(): Promise<HomeSnapshotV2> {
  const [coworkHome, runsRaw, providers, integrations, productHomeRaw, draftQueueRaw] = await Promise.all([
    getCoworkHome(),
    safeRequest<SuccessEnvelope<{ runs: unknown[] }>>("/api/v1/runs?limit=6"),
    getProviders(),
    getIntegrations(),
    safeRequest<Record<string, unknown>>("/api/product/home"),
    safeRequest<Record<string, unknown>>("/api/learning/drafts?limit=6"),
  ]);

  const runs = Array.isArray(runsRaw?.runs)
    ? runsRaw.runs
        .map((item) => runSchema.safeParse(item))
        .filter((parsed) => parsed.success)
        .map((parsed): RunSummary => toRunSummary(parsed.data))
    : [];

  const recentThreads = coworkHome.recentThreads || [];
  const backgroundTasks = coworkHome.backgroundTasks || [];
  const autopilot = coworkHome.autopilot;
  const activeAgents = coworkHome.backends.filter((backend) => backend.active).length;
  const metricCards: MetricSummary[] = [
    {
      label: "Active threads",
      value: `${recentThreads.length}`,
      meta: coworkHome.pendingApprovals.length ? `${coworkHome.pendingApprovals.length} approvals pending` : "Approval queue clear",
      tone: coworkHome.pendingApprovals.length ? "warning" : "success",
    },
    {
      label: "Workspace plan",
      value: coworkHome.billing?.plan.label || "Free",
      meta: coworkHome.billing ? `${coworkHome.billing.entitlements.maxConnectors} connectors` : "Billing offline",
      tone: coworkHome.billing?.plan.status === "active" ? "success" : "neutral",
    },
    {
      label: "Runtime lanes",
      value: `${activeAgents}`,
      meta: "Healthy backend surfaces",
      tone: "neutral",
    },
    {
      label: "Background work",
      value: `${backgroundTasks.filter((task) => !["completed", "failed", "cancelled"].includes(task.state)).length}`,
      meta: autopilot?.running ? "Autopilot active" : "Manual follow-up",
      tone: autopilot?.running ? "success" : "neutral",
    },
    {
      label: "Security posture",
      value: coworkHome.security.posture.replace(/_/g, " "),
      meta: coworkHome.security.dataLocality.replace(/_/g, " "),
      tone: coworkHome.pendingApprovals.length ? "warning" : "success",
    },
  ];

  const trustStrip: TrustStripItem[] = [
    {
      id: "runtime",
      label: "Runtime posture",
      value: coworkHome.security.posture.replace(/_/g, " "),
      tone: coworkHome.pendingApprovals.length ? "warning" : "success",
      detail: coworkHome.security.dataLocality.replace(/_/g, " "),
    },
    {
      id: "approvals",
      label: "Approval queue",
      value: `${coworkHome.pendingApprovals.length}`,
      tone: coworkHome.pendingApprovals.length ? "warning" : "neutral",
      detail: coworkHome.pendingApprovals.length ? "review gates waiting" : "clear",
    },
    {
      id: "billing",
      label: "Workspace plan",
      value: coworkHome.billing?.plan.label || "Free",
      tone: coworkHome.billing?.plan.status === "active" ? "success" : "neutral",
      detail: coworkHome.billing ? `${coworkHome.billing.entitlements.teamSeats} seats` : "billing offline",
    },
    {
      id: "autopilot",
      label: "Operator mode",
      value: autopilot?.running ? "active" : "manual",
      tone: autopilot?.running ? "success" : "neutral",
      detail: autopilot?.lastTickAt || "not started",
    },
  ];

  const activity: ActivityItem[] = [
    ...(autopilot?.briefing
      ? [
          {
            id: "autopilot-briefing",
            title: "Elyan check-in",
            detail: autopilot.briefing,
            source: "autopilot",
            level: "info" as const,
            createdAt: autopilot.lastTickAt || "Now",
          },
        ]
      : []),
    ...(autopilot?.suggestions || []).slice(0, 2).map((suggestion): ActivityItem => ({
      id: `suggestion-${suggestion.task}-${suggestion.userId}`,
      title: suggestion.task || "Next move",
      detail: suggestion.description || suggestion.reason || "Suggested follow-up",
      source: "suggestion",
      level: suggestion.priority === "high" ? "warning" : "info",
      createdAt: autopilot?.lastTickAt || "Now",
    })),
    ...recentThreads.slice(0, 4).map((thread): ActivityItem => ({
      id: `thread-${thread.threadId}`,
      title: thread.title,
      detail: thread.lastOperatorTurn?.content || thread.lastUserTurn?.content || thread.status,
      source: "cowork",
      level: thread.status === "failed" ? "error" : thread.pendingApprovals > 0 ? "warning" : "info",
      createdAt: thread.updatedAt,
    })),
    ...coworkHome.pendingApprovals.slice(0, 2).map((approval): ActivityItem => ({
      id: approval.id,
      title: approval.title,
      detail: approval.summary,
      source: "approval",
      level: "warning" as const,
      createdAt: approval.createdAt,
    })),
  ];

  const workflowCards: WorkflowLaunchCard[] = [
    {
      id: "document",
      title: "Document lane",
      description: "Brief, outline, draft, review, export inside the same cowork thread.",
      actionLabel: "Create document",
      agentLane: "executive → planner → artifact → review",
      status: "ready",
      meta: "DOCX/PDF export lane",
    },
    {
      id: "presentation",
      title: "Presentation lane",
      description: "Audience analysis, slide narrative, visual brief, export in one thread.",
      actionLabel: "Create presentation",
      agentLane: "executive → planner → artifact → review",
      status: "ready",
      meta: "PPTX export lane",
    },
    {
      id: "website",
      title: "Website lane",
      description: "Strategy, sitemap, design spec, scaffold, review from the same workstream.",
      actionLabel: "Create website",
      agentLane: "executive → planner → code → review",
      status: "ready",
      meta: "React/TS scaffold lane",
    },
  ];

  const recentArtifacts: RecentArtifactSummary[] = recentThreads.slice(0, 4).map((thread) => ({
    id: thread.threadId,
    title: thread.title,
    kind: thread.currentMode === "cowork" ? inferTaskTypeFromText(thread.title) : thread.currentMode,
    status: toRunStatus(thread.status),
    updatedAt: thread.updatedAt,
    summary: thread.lastOperatorTurn?.content || thread.lastUserTurn?.content || thread.status,
  }));

  const setupChecklist = Array.isArray(productHomeRaw?.setup)
    ? productHomeRaw.setup
        .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
        .map((item) => ({
          key: String(item.key || crypto.randomUUID()),
          label: String(item.label || "Setup item"),
          ready: Boolean(item.ready),
          detail: String(item.detail || ""),
        }))
    : [];

  const draftSkills = Array.isArray(draftQueueRaw?.skills) ? draftQueueRaw.skills : [];
  const draftRoutines = Array.isArray(draftQueueRaw?.routines) ? draftQueueRaw.routines : [];
  const learningQueue = {
    preferences: Array.isArray(draftQueueRaw?.preferences) ? draftQueueRaw.preferences.length : 0,
    skills: draftSkills.length,
    routines: draftRoutines.length,
    total:
      (Array.isArray(draftQueueRaw?.preferences) ? draftQueueRaw.preferences.length : 0) +
      draftSkills.length +
      draftRoutines.length,
    items: [
      ...draftSkills.slice(0, 3).map((item) => ({
        id: String((item as Record<string, unknown>).draft_id || crypto.randomUUID()),
        type: "skill" as const,
        title: String((item as Record<string, unknown>).name_hint || "skill_draft"),
        detail: String((item as Record<string, unknown>).description || ""),
        status: String((item as Record<string, unknown>).status || "draft"),
        confidence: Number((item as Record<string, unknown>).confidence || 0) || undefined,
      })),
      ...draftRoutines.slice(0, 3).map((item) => ({
        id: String((item as Record<string, unknown>).draft_id || crypto.randomUUID()),
        type: "routine" as const,
        title: String((item as Record<string, unknown>).name_hint || "routine_draft"),
        detail: String((item as Record<string, unknown>).description || ""),
        status: String((item as Record<string, unknown>).status || "draft"),
        confidence: Number((item as Record<string, unknown>).confidence || 0) || undefined,
        deliveryChannel: String((item as Record<string, unknown>).delivery_channel || ""),
        scheduleExpression: String((item as Record<string, unknown>).schedule_expression || ""),
      })),
    ],
  };

  return {
    workspace: coworkHome.workspace,
    providers,
    integrations,
    recentRuns: runs,
    activity: activity.length ? activity : DEFAULT_ACTIVITY,
    metrics: {
      successRate: 0.93,
      avgLatencyMs: 680,
      activeAgents,
      totalActions: recentThreads.length + coworkHome.pendingApprovals.length,
    },
    metricCards,
    backends: coworkHome.backends,
    workflowCards,
    trustStrip,
    recentArtifacts,
    recommendedFlow:
      recentThreads.find((thread) => thread.currentMode !== "cowork")?.currentMode && recentThreads.find((thread) => thread.currentMode !== "cowork")?.currentMode !== "cowork"
        ? (recentThreads.find((thread) => thread.currentMode !== "cowork")?.currentMode as WorkflowTaskType)
        : "document",
    recentThreads,
    lastThread: coworkHome.lastThread,
    pendingApprovals: coworkHome.pendingApprovals,
    backgroundTasks,
    autopilot,
    billing: coworkHome.billing,
    setupChecklist,
    learningQueue,
  };
}

export async function promoteSkillDraft(
  draftId: string,
  payload?: { skillName?: string; description?: string; enabled?: boolean },
): Promise<{ ok: boolean; name: string; message: string }> {
  const raw = await apiClient.request<{ ok?: boolean; skill?: { name?: string }; error?: string }>("/api/skills/from-draft", {
    method: "POST",
    body: {
      draft_id: draftId,
      name: payload?.skillName || "",
      description: payload?.description || "",
      enabled: payload?.enabled ?? true,
    },
  });
  if (raw.ok) {
    invalidateMemoryCache(["home-snapshot"]);
  }
  return {
    ok: Boolean(raw.ok),
    name: String(raw.skill?.name || ""),
    message: String(raw.error || ""),
  };
}

export async function promoteRoutineDraft(
  draftId: string,
  payload?: { name?: string; expression?: string; reportChannel?: string; enabled?: boolean },
): Promise<{ ok: boolean; name: string; message: string }> {
  const raw = await apiClient.request<{ ok?: boolean; routine?: { name?: string }; error?: string }>("/api/routines/from-draft", {
    method: "POST",
    body: {
      draft_id: draftId,
      name: payload?.name || "",
      expression: payload?.expression || "",
      report_channel: payload?.reportChannel || "",
      enabled: payload?.enabled ?? true,
    },
  });
  if (raw.ok) {
    invalidateMemoryCache(["home-snapshot"]);
  }
  return {
    ok: Boolean(raw.ok),
    name: String(raw.routine?.name || ""),
    message: String(raw.error || ""),
  };
}

export async function createRoutineFromText(
  payload: {
    text: string;
    name?: string;
    expression?: string;
    reportChannel?: string;
    reportChatId?: string;
    enabled?: boolean;
    panels?: string[];
  },
): Promise<{ ok: boolean; routineId: string; name: string; message: string }> {
  const raw = await apiClient.request<{ ok?: boolean; routine?: { id?: string; name?: string }; error?: string }>("/api/routines/from-text", {
    method: "POST",
    body: {
      text: payload.text,
      name: payload.name || "",
      expression: payload.expression || "",
      report_channel: payload.reportChannel || "",
      report_chat_id: payload.reportChatId || "",
      enabled: payload.enabled ?? true,
      panels: payload.panels || [],
      created_by: "desktop-command-center",
    },
  });
  if (raw.ok) {
    invalidateMemoryCache(["home-snapshot", "command-center"]);
  }
  return {
    ok: Boolean(raw.ok),
    routineId: String(raw.routine?.id || ""),
    name: String(raw.routine?.name || ""),
    message: String(raw.error || ""),
  };
}

export async function getAutopilotStatus(): Promise<CoworkHomeSnapshot["autopilot"] | null> {
  const raw = await safeRequest<Record<string, unknown>>("/api/autopilot/status");
  if (!raw || typeof raw !== "object") {
    return null;
  }
  return {
    enabled: Boolean(raw.enabled ?? false),
    running: Boolean(raw.running ?? false),
    lastTickAt: Number(raw.last_tick_at || 0) ? formatDateTime(Number(raw.last_tick_at || 0)) : undefined,
    rawLastTickAt: Number(raw.last_tick_at || 0) || undefined,
    lastTickReason: String(raw.last_tick_reason || ""),
    briefing: String(((raw.last_briefing as Record<string, unknown> | undefined) || {}).briefing || ""),
    suggestions: Array.isArray(raw.last_suggestions)
      ? (raw.last_suggestions as Array<Record<string, unknown>>).map((item) => ({
          userId: String(item.user_id || "local"),
          task: String(item.task || ""),
          description: String(item.description || ""),
          priority: String(item.priority || "medium"),
          reason: String(item.reason || ""),
          confidence: Number(item.confidence || 0),
        }))
      : [],
    staleTasks: Array.isArray(raw.last_task_review)
      ? (raw.last_task_review as Array<Record<string, unknown>>).map((item) => ({
          taskId: String(item.task_id || crypto.randomUUID()),
          objective: String(item.objective || ""),
          state: String(item.state || ""),
          action: String(item.action || ""),
          ageMinutes: Number(item.age_minutes || 0),
        }))
      : [],
    interventions: Array.isArray(raw.last_interventions)
      ? (raw.last_interventions as Array<Record<string, unknown>>).map((item) => ({
          id: String(item.id || crypto.randomUUID()),
          prompt: String(item.prompt || ""),
          ageMinutes: Number(item.age_minutes || 0),
        }))
      : [],
  };
}

export async function triggerAutopilotTick(reason = "desktop_checkin"): Promise<CoworkHomeSnapshot["autopilot"] | null> {
  const raw = await apiClient.request<{ ok?: boolean; autopilot?: Record<string, unknown> }>("/api/autopilot/tick", {
    method: "POST",
    body: { reason },
  });
  if (!(raw?.ok ?? false) || !raw.autopilot) {
    return null;
  }
  return {
    enabled: Boolean(raw.autopilot.enabled ?? false),
    running: Boolean(raw.autopilot.running ?? false),
    lastTickAt: Number(raw.autopilot.last_tick_at || 0) ? formatDateTime(Number(raw.autopilot.last_tick_at || 0)) : undefined,
    rawLastTickAt: Number(raw.autopilot.last_tick_at || 0) || undefined,
    lastTickReason: String(raw.autopilot.last_tick_reason || ""),
    briefing: String((((raw.autopilot.last_briefing as Record<string, unknown> | undefined) || {}).briefing) || ""),
    suggestions: Array.isArray(raw.autopilot.last_suggestions)
      ? (raw.autopilot.last_suggestions as Array<Record<string, unknown>>).map((item) => ({
          userId: String(item.user_id || "local"),
          task: String(item.task || ""),
          description: String(item.description || ""),
          priority: String(item.priority || "medium"),
          reason: String(item.reason || ""),
          confidence: Number(item.confidence || 0),
        }))
      : [],
    staleTasks: Array.isArray(raw.autopilot.last_task_review)
      ? (raw.autopilot.last_task_review as Array<Record<string, unknown>>).map((item) => ({
          taskId: String(item.task_id || crypto.randomUUID()),
          objective: String(item.objective || ""),
          state: String(item.state || ""),
          action: String(item.action || ""),
          ageMinutes: Number(item.age_minutes || 0),
        }))
      : [],
    interventions: Array.isArray(raw.autopilot.last_interventions)
      ? (raw.autopilot.last_interventions as Array<Record<string, unknown>>).map((item) => ({
          id: String(item.id || crypto.randomUUID()),
          prompt: String(item.prompt || ""),
          ageMinutes: Number(item.age_minutes || 0),
        }))
      : [],
  };
}

export async function getCoworkThreadDetail(threadId: string): Promise<CoworkThreadDetail | null> {
  const raw = await safeRequest<SuccessEnvelope<{ thread: Record<string, unknown> }>>(`/api/v1/cowork/threads/${threadId}`);
  if (!raw?.success || !raw.thread) {
    return null;
  }
  return mapThreadDetail(raw.thread);
}

export async function getCommandCenterSnapshot(selectedThreadId?: string, selectedRunId?: string): Promise<CommandCenterSnapshot> {
  const [threadsRaw, security, securityEvents, runsRaw] = await Promise.all([
    safeRequest<SuccessEnvelope<{ threads: Array<Record<string, unknown>> }>>("/api/v1/cowork/threads?limit=12"),
    getSecuritySummary(),
    getSecurityEvents(10),
    safeRequest<SuccessEnvelope<{ runs: unknown[] }>>("/api/v1/runs?limit=8"),
  ]);

  const threads = Array.isArray(threadsRaw?.threads) ? threadsRaw.threads.map((item) => mapThreadSummary(item)) : [];
  const resolvedThreadId = selectedThreadId && threads.some((thread) => thread.threadId === selectedThreadId) ? selectedThreadId : threads[0]?.threadId || "";
  const selectedThread = resolvedThreadId ? await getCoworkThreadDetail(resolvedThreadId) : null;
  const approvals = selectedThread?.approvals || [];
  const runs = Array.isArray(runsRaw?.runs)
    ? runsRaw.runs
        .map((item) => runSchema.safeParse(item))
        .filter((parsed) => parsed.success)
        .map((parsed): RunSummary => toRunSummary(parsed.data))
    : [];

  const outputBlocksBase: CommandCenterSnapshot["outputBlocks"] = selectedThread
    ? [
        ...selectedThread.turns.slice(-8).map((turn): CommandCenterSnapshot["outputBlocks"][number] => ({
          id: turn.turnId,
          kind: turn.role === "user" ? "thinking" : turn.status === "failed" ? "warning" : turn.mode === "cowork" ? "action" : "result",
          title: turn.role === "user" ? "User turn" : "Operator turn",
          body: turn.content || (turn.status === "running" ? "Execution in progress" : "No content"),
          meta: `${turn.mode} · ${turn.status} · ${turn.createdAt}`,
        })),
        ...selectedThread.timeline.slice(-6).map((item): CommandCenterSnapshot["outputBlocks"][number] => ({
          id: item.id,
          kind: item.status === "failed" ? "warning" : item.source === "mission" ? "action" : "evidence",
          title: item.title,
          body: item.error || `${item.source} · ${item.status}`,
          meta: item.createdAt,
        })),
      ]
    : [];

  const selectedRunSummary =
    selectedThread?.activeRunId && runs.some((run) => run.id === selectedThread.activeRunId)
      ? {
          id: selectedThread.activeRunId,
          title: selectedThread.title,
          taskType: selectedThread.currentMode === "cowork" ? undefined : selectedThread.currentMode,
          workflowState: selectedThread.status,
          artifactPath: selectedThread.artifacts[0]?.path,
          assignedAgents: selectedThread.laneSummary?.assignedAgents || [],
          launchProfile: undefined,
          planSummary: undefined,
          artifacts: selectedThread.artifacts.map((artifact) => ({
            path: artifact.path,
            label: artifact.label,
            kind: artifact.kind,
            exists: true,
          })),
          review: selectedThread.laneSummary?.review,
          timeline: selectedThread.timeline.map((item) => ({
            id: item.id,
            title: item.title,
            status: item.status,
            startedAt: item.rawTimestamp,
            duration: undefined,
            error: item.error,
          })),
        }
      : undefined;

  const previewText = selectedThread?.goal || selectedThread?.lastUserTurn?.content || "";
  const orchestration = await getOperatorPreview(
    previewText,
    selectedThread?.sessionId || selectedThread?.threadId || "desktop-preview",
    selectedThread?.threadId || "latest",
  );

  const presence = (() => {
    type PresenceNote = NonNullable<CommandCenterSnapshot["presence"]>["operatorNotes"][number];
    const makeNote = (id: string, title: string, body: string, tone: PresenceNote["tone"]): PresenceNote => ({
      id,
      title,
      body,
      tone,
    });
    const quickReplies = orchestration
      ? [
          ...orchestration.taskPlan.steps.slice(0, 2).map((step) => `Şimdi şunu yap: ${step.name}`),
          ...(orchestration.integration.connectorName ? [`${orchestration.integration.connectorName} ile devam et`] : []),
        ].slice(0, 3)
      : ["Buradan devam et", "Durum özeti ver", "Sonraki adımı seç"];
    const baseNotes: PresenceNote[] = [];
    if (selectedThread?.status === "running") {
      baseNotes.push(makeNote("presence-running", "İş bende", selectedThread.currentStep || "Akış ilerliyor; istersen yönü burada değiştirebilirim.", "success"));
    }
    if (selectedThread?.approvals?.length) {
      baseNotes.push(makeNote("presence-approval", "Sende kısa bir onay var", "Riskli bölüme gelince durdum. Onay gelir gelmez devam ederim.", "warning"));
    }
    if ((selectedThread?.collaborationTrace || []).length) {
      const firstModel = (selectedThread?.collaborationTrace || [])[0];
      baseNotes.push(
        makeNote(
          "presence-collaboration",
          "Arka planda birden fazla akıl çalışıyor",
          `${firstModel?.lens || "planner"} hattı ${[firstModel?.provider, firstModel?.model].filter(Boolean).join(" / ") || "model"} ile açıldı.`,
          "info",
        ),
      );
    }
    if (selectedThread?.status === "running") {
      return {
        headline: "Elyan şu an işin içinde",
        status: "active",
        liveNote:
          selectedThread.lastOperatorTurn?.content ||
          selectedThread.currentStep ||
          "Arka planda işi yürütüyorum; yeni bir yön verirsen akışı ona göre çeviririm.",
        nextMove:
          orchestration?.taskPlan.steps[0]?.name ||
          selectedThread.currentStep ||
          "İstersen sıradaki adımı hemen başlatayım.",
        quickReplies,
        operatorNotes: baseNotes,
      };
    }
    if (selectedThread?.status === "failed" || selectedThread?.riskLevel === "high") {
      return {
        headline: "Elyan işi açıkta bırakmıyor",
        status: "blocked",
        liveNote:
          selectedThread.lastOperatorTurn?.content ||
          "Bu akışta sürtünme var. İstersen yön değiştirip daha güvenli bir yöntemden devam ederim.",
        nextMove: "Önce tıkanan yeri netleştirip ikinci yolu kurarım.",
        quickReplies: ["Alternatif yol dene", "Nerede takıldığını söyle", "Önce plan çıkar"],
        operatorNotes: [
          ...baseNotes,
          makeNote("presence-recovery", "Plan B hazır", "Bu yol sürtünüyorsa ikinci bir rota kurup işi tekrar ayağa kaldırırım.", "warning"),
        ],
      };
    }
    return {
      headline: "Elyan hazır ve seni takip ediyor",
      status: "ready",
      liveNote:
        selectedThread?.lastOperatorTurn?.content ||
        orchestration?.preview ||
        "Buradayım. Ne tarafa ağırlık vermem gerektiğini söylemen yeterli.",
      nextMove:
        orchestration?.taskPlan.steps[0]?.name ||
        selectedThread?.goal ||
        "İstersen yeni işi başlatayım ya da mevcut işi derinleştireyim.",
      quickReplies,
      operatorNotes: [
        ...baseNotes,
        makeNote("presence-ready", "Hazırım", "Senden kısa bir yön bile yeter; geri kalanını akışa çeviririm.", "info"),
      ],
    };
  })();
  const outputBlocks: CommandCenterSnapshot["outputBlocks"] = [
    ...(presence?.operatorNotes || []).slice(0, 2).map((note: NonNullable<CommandCenterSnapshot["presence"]>["operatorNotes"][number]): CommandCenterSnapshot["outputBlocks"][number] => ({
      id: `presence:${note.id}`,
      kind: note.tone === "warning" ? "warning" : note.tone === "success" ? "result" : "action",
      title: `Elyan note · ${note.title}`,
      body: note.body,
      meta: presence.headline,
    })),
    ...outputBlocksBase,
  ];

  return {
    threads,
    selectedThread: selectedThread || undefined,
    runs,
    approvals: approvals.map((approval) => ({
      id: approval.id,
      action: approval.title,
      priority: approval.riskLevel === "high" ? "high" : approval.riskLevel === "critical" ? "critical" : "normal",
      confidence: undefined,
    })),
    outputBlocks,
    security,
    securityEvents,
    controlActions: selectedThread?.controlActions || [],
    selectedRun: selectedRunSummary,
    presence,
    orchestration,
  };
}

type StartWorkflowPayload = {
  task_type: "document" | "presentation" | "website";
  brief: string;
  title?: string;
  audience?: string;
  language?: string;
  theme?: string;
  stack?: string;
  preferred_formats?: string[];
  session_id?: string;
  project_template_id?: string;
  project_name?: string;
  routing_profile?: string;
  review_strictness?: string;
  thread_id?: string;
  workspace_id?: string;
};

type StartWorkflowResponse = SuccessEnvelope<{
  accepted: boolean;
  run_id: string;
  task_type: string;
  workflow_state: string;
  run: Record<string, unknown>;
}>;

type LocalLoginResponse = SuccessEnvelope<{
  workspace_id: string;
  bootstrap_required?: boolean;
  session_token?: string;
  user: {
    user_id: string;
    email: string;
    display_name?: string;
    status?: string;
  };
}>;

type BootstrapOwnerResponse = SuccessEnvelope<{
  workspace_id: string;
  session_token?: string;
  user: {
    user_id: string;
    email: string;
    display_name?: string;
    status?: string;
    role?: string;
  };
}>;

type LocalAuthSessionResponse = SuccessEnvelope<{
  workspace_id: string;
  session_token?: string;
  user: {
    user_id: string;
    email: string;
    display_name?: string;
    status?: string;
  };
  session?: {
    session_id?: string;
    expires_at?: number;
  };
}>;

type CoworkThreadPayload = {
  prompt: string;
  current_mode?: "cowork" | "document" | "presentation" | "website";
  session_id?: string;
  project_template_id?: string;
  project_name?: string;
  routing_profile?: string;
  review_strictness?: string;
  workspace_id?: string;
  response_mode?: string;
  provider_strategy?: string;
  privacy_mode?: string;
  automation_level?: string;
  tone?: string;
};

export async function createCoworkThread(payload: CoworkThreadPayload): Promise<CoworkThreadDetail> {
  const raw = await apiClient.request<SuccessEnvelope<{ thread: Record<string, unknown> }>>("/api/v1/cowork/threads", {
    method: "POST",
    body: payload,
  });
  return mapThreadDetail(raw.thread);
}

export async function loginLocalUser(email: string, password: string): Promise<{ email: string; displayName: string }> {
  const raw = await apiClient.request<LocalLoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: { email, password },
  });
  return {
    email: String(raw.user?.email || email).trim().toLowerCase(),
    displayName: String(raw.user?.display_name || "").trim(),
  };
}

export async function bootstrapOwner(payload: {
  email: string;
  password: string;
  displayName?: string;
  workspaceId?: string;
}): Promise<{ email: string; displayName: string; workspaceId: string }> {
  const raw = await apiClient.request<BootstrapOwnerResponse>("/api/v1/auth/bootstrap-owner", {
    method: "POST",
    body: {
      email: payload.email,
      password: payload.password,
      display_name: payload.displayName || payload.email.split("@", 1)[0],
      workspace_id: payload.workspaceId || "local-workspace",
    },
  });
  return {
    email: String(raw.user?.email || payload.email).trim().toLowerCase(),
    displayName: String(raw.user?.display_name || payload.displayName || "").trim(),
    workspaceId: String(raw.workspace_id || payload.workspaceId || "local-workspace"),
  };
}

export async function getCurrentLocalUser(): Promise<{ email: string; displayName: string } | null> {
  const raw = await safeRequest<LocalAuthSessionResponse>("/api/v1/auth/me");
  if (!raw?.success || !raw.user) {
    return null;
  }
  const email = String(raw.user.email || "").trim().toLowerCase();
  if (!email) {
    return null;
  }
  return {
    email,
    displayName: String(raw.user.display_name || "").trim(),
  };
}

export async function logoutLocalUser(): Promise<void> {
  try {
    await apiClient.request("/api/v1/auth/logout", {
      method: "POST",
      body: {},
    });
  } finally {
    apiClient.clearSessionToken();
  }
}

export async function addCoworkTurn(threadId: string, payload: CoworkThreadPayload): Promise<CoworkThreadDetail> {
  const raw = await apiClient.request<SuccessEnvelope<{ thread: Record<string, unknown> }>>(`/api/v1/cowork/threads/${threadId}/turns`, {
    method: "POST",
    body: payload,
  });
  return mapThreadDetail(raw.thread);
}

export async function resolveCoworkApproval(approvalId: string, payload: { approved: boolean; note?: string }): Promise<CoworkThreadDetail | null> {
  const raw = await apiClient.request<SuccessEnvelope<{ thread?: Record<string, unknown> }>>(`/api/v1/cowork/approvals/${approvalId}/resolve`, {
    method: "POST",
    body: payload,
  });
  return raw.thread ? mapThreadDetail(raw.thread) : null;
}

export async function cancelRun(runId: string): Promise<boolean> {
  const raw = await apiClient.request<SuccessEnvelope<{ message?: string; error?: string }>>(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    body: {},
  });
  return Boolean(raw.success);
}

export async function controlCoworkThread(threadId: string, action: "stop" | "resume", note = ""): Promise<CoworkThreadDetail | null> {
  const raw = await apiClient.request<SuccessEnvelope<{ thread?: Record<string, unknown> }>>(`/api/v1/cowork/threads/${encodeURIComponent(threadId)}/actions`, {
    method: "POST",
    body: { action, note },
  });
  return raw.thread ? mapThreadDetail(raw.thread) : null;
}

export async function startWorkflowRun(payload: StartWorkflowPayload): Promise<StartWorkflowResponse> {
  return apiClient.request<StartWorkflowResponse>("/api/v1/workflows/start", {
    method: "POST",
    body: payload,
  });
}

export async function getBillingWorkspace(): Promise<WorkspaceBillingSummary | null> {
  const raw = await safeRequest<SuccessEnvelope<{ workspace: Record<string, unknown> }>>("/api/v1/billing/workspace");
  return raw?.success && raw.workspace ? mapBilling(raw.workspace) : null;
}

export async function getBillingProfile(): Promise<BillingProfileSummary | null> {
  const raw = await safeRequest<SuccessEnvelope<{ profile: Record<string, unknown> }>>("/api/v1/billing/profile");
  return raw?.success && raw.profile ? mapBillingProfile(raw.profile) : null;
}

export async function saveBillingProfile(payload: {
  fullName: string;
  email: string;
  phone: string;
  identityNumber: string;
  addressLine1: string;
  city: string;
  zipCode: string;
  country: string;
}): Promise<BillingProfileSummary | null> {
  const raw = await apiClient.request<SuccessEnvelope<{ profile?: Record<string, unknown> }>>("/api/v1/billing/profile", {
    method: "PUT",
    body: {
      full_name: payload.fullName,
      email: payload.email,
      phone: payload.phone,
      identity_number: payload.identityNumber,
      address_line1: payload.addressLine1,
      city: payload.city,
      zip_code: payload.zipCode,
      country: payload.country,
    },
  });
  return raw.profile ? mapBillingProfile(raw.profile) : null;
}

export async function getBillingCheckout(referenceId: string): Promise<BillingCheckoutSessionSummary | null> {
  if (!referenceId) {
    return null;
  }
  const raw = await safeRequest<SuccessEnvelope<{ checkout: Record<string, unknown> }>>(`/api/v1/billing/checkouts/${encodeURIComponent(referenceId)}`);
  return raw?.success && raw.checkout ? mapBillingCheckoutSession(raw.checkout) : null;
}

export async function createCheckoutSession(planId: string): Promise<BillingCheckoutLaunchSummary> {
  const raw = await apiClient.request<SuccessEnvelope<{ checkout: Record<string, unknown> }>>("/api/v1/billing/checkout/init", {
    method: "POST",
    body: { plan_id: planId },
  });
  const checkoutPayload =
    raw.checkout && typeof raw.checkout.checkout === "object"
      ? (raw.checkout.checkout as Record<string, unknown>)
      : raw.checkout;
  const checkout = checkoutPayload ? mapBillingCheckoutSession(checkoutPayload) : null;
  return {
    launchUrl: checkout?.launchUrl || String((raw.checkout as Record<string, unknown> | undefined)?.launch_url || (raw.checkout as Record<string, unknown> | undefined)?.url || ""),
    referenceId: checkout?.referenceId || String((raw.checkout as Record<string, unknown> | undefined)?.reference_id || ""),
    status: checkout?.status || String((raw.checkout as Record<string, unknown> | undefined)?.status || "pending"),
    mode: checkout?.mode || "subscription",
  };
}

export async function createPortalSession(): Promise<string> {
  const raw = await apiClient.request<SuccessEnvelope<{ portal: { url?: string } }>>("/api/v1/billing/portal-session", {
    method: "POST",
    body: {},
  });
  return String(raw.portal?.url || "");
}

export async function getAdminWorkspaces(): Promise<WorkspaceAdminSummary[]> {
  const raw = await safeRequest<SuccessEnvelope<{ workspaces: Array<Record<string, unknown>> }>>("/api/v1/admin/workspaces");
  if (!raw?.success || !Array.isArray(raw.workspaces)) {
    return [];
  }
  return raw.workspaces.map((item) => mapWorkspaceAdminSummary(item));
}

export async function getAdminWorkspaceDetail(workspaceId: string): Promise<WorkspaceAdminDetail | null> {
  if (!workspaceId) {
    return null;
  }
  const raw = await safeRequest<
    SuccessEnvelope<{
      workspace: Record<string, unknown>;
      seats: Record<string, unknown>;
      permissions: Record<string, unknown>;
      current_role: string;
      billing?: Record<string, unknown>;
    }>
  >(`/api/v1/admin/workspaces/${encodeURIComponent(workspaceId)}`);
  if (!raw?.success || !raw.workspace) {
    return null;
  }
  return {
    workspace: mapWorkspaceSummary(raw.workspace),
    seats: mapSeatSummary((raw.seats as Record<string, unknown> | undefined) || {}),
    permissions: mapWorkspacePermissions((raw.permissions as Record<string, unknown> | undefined) || {}),
    currentRole: String(raw.current_role || "member"),
    billing: raw.billing && typeof raw.billing === "object" ? mapBilling(raw.billing) : undefined,
  };
}

export async function getWorkspaceMembers(workspaceId: string): Promise<WorkspaceMemberSummary[]> {
  if (!workspaceId) {
    return [];
  }
  const raw = await safeRequest<SuccessEnvelope<{ members: Array<Record<string, unknown>> }>>(
    `/api/v1/admin/workspaces/${encodeURIComponent(workspaceId)}/members`,
  );
  if (!raw?.success || !Array.isArray(raw.members)) {
    return [];
  }
  return raw.members.map((item) => mapWorkspaceMember(item));
}

export async function getWorkspaceInvites(workspaceId: string): Promise<WorkspaceInviteSummary[]> {
  if (!workspaceId) {
    return [];
  }
  const raw = await safeRequest<SuccessEnvelope<{ invites: Array<Record<string, unknown>> }>>(
    `/api/v1/admin/workspaces/${encodeURIComponent(workspaceId)}/invites`,
  );
  if (!raw?.success || !Array.isArray(raw.invites)) {
    return [];
  }
  return raw.invites.map((item) => mapWorkspaceInvite(item));
}

export async function createWorkspaceInvite(payload: {
  workspaceId: string;
  email: string;
  role: string;
}): Promise<WorkspaceInviteSummary | null> {
  const raw = await apiClient.request<SuccessEnvelope<{ invite?: Record<string, unknown> }>>(
    `/api/v1/admin/workspaces/${encodeURIComponent(payload.workspaceId)}/invites`,
    {
      method: "POST",
      body: {
        email: payload.email,
        role: payload.role,
      },
    },
  );
  return raw.invite ? mapWorkspaceInvite(raw.invite) : null;
}

export async function updateWorkspaceRole(payload: {
  workspaceId: string;
  actorId: string;
  role: string;
}): Promise<WorkspaceMemberSummary | null> {
  const raw = await apiClient.request<SuccessEnvelope<{ membership?: Record<string, unknown> }>>(
    `/api/v1/admin/workspaces/${encodeURIComponent(payload.workspaceId)}/members/${encodeURIComponent(payload.actorId)}/role`,
    {
      method: "POST",
      body: {
        role: payload.role,
      },
    },
  );
  return raw.membership ? mapWorkspaceMember(raw.membership) : null;
}

export async function assignWorkspaceSeat(payload: {
  workspaceId: string;
  actorId: string;
  action?: "assign" | "release";
}): Promise<{ seats: WorkspaceAdminSummary["seats"] | null }> {
  const raw = await apiClient.request<SuccessEnvelope<{ seats?: Record<string, unknown> }>>(
    `/api/v1/admin/workspaces/${encodeURIComponent(payload.workspaceId)}/seats/assign`,
    {
      method: "POST",
      body: {
        actor_id: payload.actorId,
        action: payload.action || "assign",
      },
    },
  );
  return {
    seats: raw.seats && typeof raw.seats === "object" ? mapSeatSummary(raw.seats) : null,
  };
}

export async function getBillingCatalog(): Promise<{ plans: BillingPlanSummary[]; tokenPacks: TokenPackSummary[] }> {
  const raw = await safeRequest<SuccessEnvelope<{ plans: Array<Record<string, unknown>>; token_packs: Array<Record<string, unknown>> }>>(
    "/api/v1/billing/plans",
  );
  if (!raw?.success) {
    return { plans: [], tokenPacks: [] };
  }
  return {
    plans: Array.isArray(raw.plans) ? raw.plans.map((item) => mapBillingPlan(item)) : [],
    tokenPacks: Array.isArray(raw.token_packs) ? raw.token_packs.map((item) => mapTokenPack(item)) : [],
  };
}

export async function getCreditLedger(limit = 40): Promise<CreditLedgerEntrySummary[]> {
  const raw = await safeRequest<SuccessEnvelope<{ ledger?: { items?: Array<Record<string, unknown>> } }>>(`/api/v1/billing/ledger?limit=${limit}`);
  const items = raw?.success && raw.ledger && typeof raw.ledger === "object" ? raw.ledger.items : [];
  return Array.isArray(items) ? items.map((item) => mapCreditLedgerEntry(item)) : [];
}

export async function getBillingEvents(limit = 24): Promise<BillingEventSummary[]> {
  const raw = await safeRequest<SuccessEnvelope<{ events?: { items?: Array<Record<string, unknown>> } }>>(`/api/v1/billing/events?limit=${limit}`);
  const items = raw?.success && raw.events && typeof raw.events === "object" ? raw.events.items : [];
  return Array.isArray(items) ? items.map((item) => mapBillingEvent(item)) : [];
}

export async function getInboxEvents(workspaceId = "", limit = 8): Promise<InboxEventSummary[]> {
  const query = new URLSearchParams();
  if (workspaceId) {
    query.set("workspace_id", workspaceId);
  }
  query.set("limit", String(limit));
  const raw = await safeRequest<SuccessEnvelope<{ events?: Array<Record<string, unknown>> }>>(`/api/v1/inbox/events?${query.toString()}`);
  const items = raw?.success ? raw.events : [];
  return Array.isArray(items) ? items.map((item) => mapInboxEvent(item)) : [];
}

export async function createInboxEvent(payload: {
  content: string;
  sourceType?: string;
  sourceId?: string;
  title?: string;
  workspaceId?: string;
}): Promise<{ event: InboxEventSummary | null; extraction: InboxTaskExtraction | null; billingWarning: string }> {
  const raw = await apiClient.request<
    SuccessEnvelope<{
      event?: Record<string, unknown>;
      extraction?: Record<string, unknown>;
      billing_warning?: string;
    }>
  >("/api/v1/inbox/events", {
    method: "POST",
    body: {
      content: payload.content,
      source_type: payload.sourceType || "manual",
      source_id: payload.sourceId || "",
      title: payload.title || "",
      workspace_id: payload.workspaceId || "",
      analyze: true,
    },
  });
  return {
    event: raw.event ? mapInboxEvent(raw.event) : null,
    extraction: raw.extraction ? mapInboxTaskExtraction(raw.extraction) : null,
    billingWarning: String(raw.billing_warning || ""),
  };
}

export async function extractInboxTask(payload: {
  content?: string;
  eventId?: string;
  sourceType?: string;
  title?: string;
  workspaceId?: string;
}): Promise<{ extraction: InboxTaskExtraction | null; event: InboxEventSummary | null; billingWarning: string }> {
  const raw = await apiClient.request<
    SuccessEnvelope<{
      summary?: Record<string, unknown>;
      event?: Record<string, unknown>;
      billing_warning?: string;
    }>
  >("/api/v1/tasks/extract", {
    method: "POST",
    body: {
      content: payload.content || "",
      event_id: payload.eventId || "",
      source_type: payload.sourceType || "manual",
      title: payload.title || "",
      workspace_id: payload.workspaceId || "",
    },
  });
  return {
    extraction: raw.summary ? mapInboxTaskExtraction(raw.summary) : null,
    event: raw.event ? mapInboxEvent(raw.event) : null,
    billingWarning: String(raw.billing_warning || ""),
  };
}

export async function purchaseTokenPack(packId: string): Promise<BillingCheckoutLaunchSummary> {
  const raw = await apiClient.request<SuccessEnvelope<{ purchase?: Record<string, unknown> }>>("/api/v1/billing/token-packs/purchase", {
    method: "POST",
    body: { pack_id: packId },
  });
  const purchasePayload =
    raw.purchase && typeof raw.purchase.checkout === "object"
      ? (raw.purchase.checkout as Record<string, unknown>)
      : raw.purchase;
  const purchase = purchasePayload ? mapBillingCheckoutSession(purchasePayload) : null;
  return {
    launchUrl: purchase?.launchUrl || String((raw.purchase as Record<string, unknown> | undefined)?.launch_url || (raw.purchase as Record<string, unknown> | undefined)?.url || ""),
    referenceId: purchase?.referenceId || String((raw.purchase as Record<string, unknown> | undefined)?.reference_id || ""),
    status: purchase?.status || String((raw.purchase as Record<string, unknown> | undefined)?.status || "pending"),
    mode: purchase?.mode || "token_pack",
  };
}

export async function getConnectors(): Promise<ConnectorDefinition[]> {
  return withMemoryCache("connectors", 8000, async () => {
    const raw = await safeRequest<SuccessEnvelope<{ connectors: Array<Record<string, unknown>> }>>("/api/v1/connectors");
    if (!raw?.success) {
      return [];
    }
    return Array.isArray(raw.connectors) ? raw.connectors.map((item) => mapConnector(item)) : [];
  });
}

export async function getConnectorAccounts(provider = ""): Promise<ConnectorAccount[]> {
  const suffix = provider ? `?provider=${encodeURIComponent(provider)}` : "";
  const raw = await safeRequest<SuccessEnvelope<{ accounts: Array<Record<string, unknown>> }>>(`/api/v1/connectors/accounts${suffix}`);
  if (!raw?.success) {
    return [];
  }
  return Array.isArray(raw.accounts) ? raw.accounts.map((item) => mapConnectorAccount(item)) : [];
}

export async function connectConnector(connector: string): Promise<{ launchUrl: string; account?: ConnectorAccount }> {
  const raw = await apiClient.request<SuccessEnvelope<{ launch_url?: string; account?: Record<string, unknown> }>>(`/api/v1/connectors/${connector}/connect`, {
    method: "POST",
    body: {},
  });
  if (raw.success) {
    invalidateMemoryCache(["connectors", "integrations-summary"]);
  }
  return {
    launchUrl: String(raw.launch_url || ""),
    account: raw.account ? mapConnectorAccount(raw.account) : undefined,
  };
}

export async function refreshConnectorAccount(accountId: string): Promise<ConnectorAccount | null> {
  const raw = await apiClient.request<SuccessEnvelope<{ account?: Record<string, unknown> }>>(`/api/v1/connectors/accounts/${encodeURIComponent(accountId)}/refresh`, {
    method: "POST",
    body: {},
  });
  if (raw.success) {
    invalidateMemoryCache(["connectors", "integrations-summary"]);
  }
  return raw.account ? mapConnectorAccount(raw.account) : null;
}

export async function revokeConnectorAccount(accountId: string): Promise<boolean> {
  const raw = await apiClient.request<SuccessEnvelope<{ success: boolean }>>(`/api/v1/connectors/accounts/${encodeURIComponent(accountId)}/revoke`, {
    method: "POST",
    body: {},
  });
  if (raw.success) {
    invalidateMemoryCache(["connectors", "integrations-summary"]);
  }
  return Boolean(raw.success);
}

export async function getConnectorTraces(): Promise<ConnectorActionTrace[]> {
  const raw = await safeRequest<SuccessEnvelope<{ traces: Array<Record<string, unknown>> }>>("/api/v1/connectors/traces");
  if (!raw?.success) {
    return [];
  }
  return Array.isArray(raw.traces) ? raw.traces.map((item) => mapConnectorTrace(item)) : [];
}

export async function getConnectorHealth(): Promise<ConnectorHealth[]> {
  const raw = await safeRequest<SuccessEnvelope<{ health: Array<Record<string, unknown>> }>>("/api/v1/connectors/health");
  if (!raw?.success) {
    return [];
  }
  return Array.isArray(raw.health) ? raw.health.map((item) => mapConnectorHealth(item)) : [];
}

export async function runConnectorQuickAction(
  connector: string,
  action: string,
  payload: Record<string, unknown> = {},
): Promise<ConnectorExecutionResult> {
  const raw = await apiClient.request<{
    ok?: boolean;
    connector?: string;
    action?: string;
    blocking_issue?: string;
    result?: Record<string, unknown>;
  }>(`/api/v1/connectors/${encodeURIComponent(connector)}/quick-action`, {
    method: "POST",
    body: {
      action,
      ...payload,
    },
  });
  return {
    connector: String(raw.connector || connector),
    action: String(raw.action || action),
    blockingIssue: String(raw.blocking_issue || ""),
    result: ((raw.result as Record<string, unknown> | undefined) || {}) as Record<string, unknown>,
  };
}

export async function getChannels(): Promise<ChannelSummary[]> {
  const raw = await safeRequest<{ channels?: Array<Record<string, unknown>> }>("/api/channels");
  if (!raw?.channels || !Array.isArray(raw.channels)) {
    return [];
  }
  return raw.channels.map((item) => mapChannelSummary(item));
}

export async function getChannelsCatalog(): Promise<ChannelCatalogEntry[]> {
  const raw = await safeRequest<{ ok?: boolean; catalog?: Array<Record<string, unknown>> }>("/api/channels/catalog");
  if (!raw?.ok || !Array.isArray(raw.catalog)) {
    return [];
  }
  return raw.catalog.map((item) => mapChannelCatalogEntry(item));
}

export async function getChannelPairingStatus(channel: string): Promise<ChannelPairingStatus> {
  const raw = await safeRequest<Record<string, unknown>>(`/api/channels/pair/status?channel=${encodeURIComponent(channel)}`);
  return mapChannelPairingStatus(raw || {}, channel);
}

export async function startChannelPairing(
  channel: string,
  payload: Record<string, unknown> = {},
): Promise<ChannelPairingStatus> {
  const raw = await apiClient.request<Record<string, unknown>>("/api/channels/pair/start", {
    method: "POST",
    body: {
      channel,
      ...payload,
    },
  });
  invalidateMemoryCache(["channels"]);
  return mapChannelPairingStatus(raw || {}, channel);
}

export async function upsertChannel(channel: Record<string, unknown>): Promise<ChannelSummary | null> {
  const raw = await apiClient.request<{ ok?: boolean; channel?: Record<string, unknown> }>("/api/channels/upsert", {
    method: "POST",
    body: { channel, sync: true },
  });
  return raw.ok && raw.channel ? mapChannelSummary(raw.channel) : null;
}

export async function toggleChannel(id: string, enabled: boolean): Promise<ChannelSummary | null> {
  const raw = await apiClient.request<{ ok?: boolean; channel?: Record<string, unknown> }>("/api/channels/toggle", {
    method: "POST",
    body: { id, enabled },
  });
  return raw.ok && raw.channel ? mapChannelSummary(raw.channel) : null;
}

export async function testChannel(channel: string): Promise<ChannelTestResult> {
  const raw = await apiClient.request<{
    ok?: boolean;
    message?: string;
    result?: Record<string, unknown>;
  }>("/api/channels/test", {
    method: "POST",
    body: { channel },
  });
  const result = (raw.result || {}) as Record<string, unknown>;
  return {
    channel: String(result.channel || channel),
    status: String(result.status || "unknown"),
    connected: Boolean(result.connected),
    message: String(raw.message || ""),
  };
}

export async function getProviders(): Promise<ProviderSummary[]> {
  return withMemoryCache("providers-summary", 8000, async () => {
    const descriptors = await getProviderDescriptors();
    if (!descriptors.length) {
      return [];
    }
    return descriptors.map((provider) => {
      const primaryLane = provider.lanes.find((lane) => lane.lane !== "fallback") || provider.lanes[0];
      const activeModel =
        provider.models.find((model) => model.modelId === primaryLane?.model) ||
        provider.models.find((model) => model.installed) ||
        provider.models[0];
      return {
        id: provider.providerId,
        name: provider.label,
        model: String(activeModel?.displayName || activeModel?.modelId || "Not configured"),
        latencyMs:
          primaryLane?.latencyBucket === "fast"
            ? 450
            : primaryLane?.latencyBucket === "slow"
              ? 3200
              : 1100,
        usageToday: provider.models.filter((model) => model.installed).length,
        status:
          provider.healthState === "available"
            ? "connected"
            : provider.healthState === "degraded" || provider.healthState === "rate_limited"
              ? "degraded"
              : "offline",
        detail: provider.detail,
      };
    });
  });
}

type ModelsEnvelope = {
  ok?: boolean;
  default?: { provider?: string; model?: string };
  fallback?: { provider?: string; model?: string };
  roles?: Record<string, { provider?: string; model?: string }>;
  registry?: Array<Record<string, unknown>>;
  provider_keys?: Record<string, { configured?: boolean }>;
  providers?: Record<string, { status?: string; success_rate?: string; avg_latency?: string; total_calls?: number }>;
};

type LlmSetupStatusEnvelope = {
  ok?: boolean;
  providers?: Array<Record<string, unknown>>;
};

type OllamaStatusEnvelope = {
  ok?: boolean;
  running?: boolean;
  models?: Array<Record<string, unknown>>;
  recommended?: Array<Record<string, unknown>>;
};

type HealthEnvelope = {
  ok?: boolean;
  status?: string;
  readiness?: Record<string, unknown>;
};

function normalizeProviderLabel(providerId: string): string {
  const normalized = providerId.trim().toLowerCase();
  const labels: Record<string, string> = {
    openai: "OpenAI",
    anthropic: "Anthropic",
    google: "Google",
    groq: "Groq",
    ollama: "Ollama",
    deepseek: "DeepSeek",
    mistral: "Mistral",
    together: "Together",
    cohere: "Cohere",
    perplexity: "Perplexity",
    xai: "xAI",
  };
  return labels[normalized] || providerId;
}

function latencyBucket(value: string): ExecutionLaneStatus["latencyBucket"] {
  const seconds = Number(String(value || "").replace(/[^\d.]/g, ""));
  if (!seconds || Number.isNaN(seconds)) {
    return "balanced";
  }
  if (seconds <= 1.2) {
    return "fast";
  }
  if (seconds <= 3.0) {
    return "balanced";
  }
  return "slow";
}

function laneVerificationState(lane: ExecutionLaneStatus["lane"]): ExecutionLaneStatus["verificationState"] {
  return lane === "research" || lane === "fallback" ? "verified" : "standard";
}

function mapRoleToLane(role: string): ExecutionLaneStatus["lane"] {
  const normalized = role.trim().toLowerCase();
  if (normalized === "router" || normalized === "inference" || normalized === "creative") {
    return "chat";
  }
  if (normalized === "reasoning" || normalized === "planning" || normalized === "critic" || normalized === "qa") {
    return "reasoning";
  }
  if (normalized === "research_worker") {
    return "research";
  }
  if (normalized === "fallback") {
    return "fallback";
  }
  return "vision";
}

function buildProviderDescriptors(
  modelsRaw: ModelsEnvelope | null,
  setupRaw: LlmSetupStatusEnvelope | null,
  ollamaRaw: OllamaStatusEnvelope | null,
): ProviderDescriptor[] {
  const setupProviders = Array.isArray(setupRaw?.providers) ? setupRaw.providers : [];
  const setupById = new Map<string, Record<string, unknown>>();
  for (const item of setupProviders) {
    const providerId = String(item.provider || item.id || "").trim().toLowerCase();
    if (providerId) {
      setupById.set(providerId, item);
    }
  }

  const modelHealth = (modelsRaw?.providers || {}) as Record<string, { status?: string; avg_latency?: string }>;
  const roleMap = (modelsRaw?.roles || {}) as Record<string, { provider?: string; model?: string }>;
  const providerKeys = (modelsRaw?.provider_keys || {}) as Record<string, { configured?: boolean }>;
  const registry = Array.isArray(modelsRaw?.registry) ? modelsRaw?.registry : [];

  const providerIds = new Set<string>([
    ...Object.keys(providerKeys),
    ...Object.keys(modelHealth),
    ...Array.from(setupById.keys()),
    ...registry.map((item) => String(item.provider || item.type || "").trim().toLowerCase()).filter(Boolean),
  ]);
  providerIds.add("ollama");

  const ollamaModels = Array.isArray(ollamaRaw?.models) ? ollamaRaw.models : [];
  const ollamaRecommended = Array.isArray(ollamaRaw?.recommended) ? ollamaRaw.recommended : [];

  return Array.from(providerIds)
    .filter(Boolean)
    .sort((a, b) => {
      if (a === "ollama") return -1;
      if (b === "ollama") return 1;
      return a.localeCompare(b);
    })
    .map((providerId) => {
      const setupInfo = setupById.get(providerId) || {};
      const healthInfo = modelHealth[providerId] || {};
      const configInfo = providerKeys[providerId] || {};
      const supportedRoles = Object.entries(roleMap)
        .filter(([, value]) => String(value.provider || "").trim().toLowerCase() === providerId)
        .map(([role]) => role);

      const lanes: ExecutionLaneStatus[] = Object.entries(roleMap)
        .filter(([, value]) => String(value.provider || "").trim().toLowerCase() === providerId)
        .slice(0, 5)
        .map(([role, value]) => ({
          lane: mapRoleToLane(role),
          activeProvider: providerId,
          model: String(value.model || ""),
          fallbackActive: role === "fallback",
          verificationState: laneVerificationState(mapRoleToLane(role)),
          latencyBucket: latencyBucket(healthInfo.avg_latency || ""),
        }));

      const configured = Boolean(configInfo.configured ?? setupInfo.configured ?? providerId === "ollama");
      const isLocal = providerId === "ollama";
      const setupStatus = String(setupInfo.status || "").trim().toLowerCase();
      const healthState: ProviderDescriptor["healthState"] =
        !configured && !isLocal
          ? "unreachable"
          : setupStatus === "degraded" || String(healthInfo.status || "").includes("degraded")
            ? "degraded"
            : setupStatus === "rate_limited"
              ? "rate_limited"
              : setupStatus === "connected" || setupStatus === "available" || providerId === "ollama"
                ? "available"
                : "unreachable";

      const authState: ProviderDescriptor["authState"] = isLocal ? "not_required" : configured ? "ready" : "auth_required";

      const models: ModelDescriptor[] = isLocal
        ? [...ollamaModels, ...ollamaRecommended.filter((item) => !ollamaModels.some((installed) => String(installed.name || "") === String(item.name || "")))]
            .map((item) => {
              const name = String(item.name || "");
              return {
                modelId: name,
                displayName: name,
                providerId,
                installed: Boolean(item.installed ?? ollamaModels.some((installed) => String(installed.name || "") === name)),
                downloadable: true,
                size: String(item.size || ""),
                lastUsedAt: "",
                capabilities: ["chat", "reasoning", "local"],
                digest: String(item.digest || ""),
                modified: String(item.modified || ""),
                roleAssignments: Object.entries(roleMap)
                  .filter(([, value]) => String(value.provider || "").trim().toLowerCase() === providerId && String(value.model || "") === name)
                  .map(([role]) => role),
              };
            })
        : registry
            .filter((item) => String(item.provider || item.type || "").trim().toLowerCase() === providerId)
            .map((item) => ({
              modelId: String(item.id || item.model || crypto.randomUUID()),
              displayName: String(item.alias || item.label || item.model || providerId),
              providerId,
              installed: true,
              downloadable: false,
              size: "",
              lastUsedAt: "",
              capabilities: Array.isArray(item.roles) ? item.roles.map((role) => String(role)) : ["chat"],
              roleAssignments: Array.isArray(item.roles) ? item.roles.map((role) => String(role)) : [],
            }));

      return {
        providerId,
        label: normalizeProviderLabel(providerId),
        kind: isLocal ? "local" : "cloud",
        enabled: configured || isLocal,
        authState,
        healthState,
        supportedRoles,
        models,
        lanes,
        endpoint: String((setupInfo.base_url || setupInfo.endpoint || "")).trim(),
        detail: isLocal
          ? ollamaRaw?.running
            ? `${ollamaModels.length} local models`
            : "Ollama not running"
          : configured
            ? `${supportedRoles.length || 1} active lanes`
            : "API key required",
      };
    });
}

export async function getSystemReadiness(): Promise<SystemReadiness> {
  return withMemoryCache("system-readiness", 2500, async () => {
    const [healthRaw, setupRaw, ollamaRaw, platformsRaw] = await Promise.all([
      safeRequest<HealthEnvelope>("/healthz"),
      safeRequest<LlmSetupStatusEnvelope>("/api/llm/setup/status"),
      safeRequest<OllamaStatusEnvelope>("/api/llm/setup/ollama"),
      safeRequest<SuccessEnvelope<{ summary?: Record<string, unknown> }>>("/api/v1/system/platforms").catch(() => null),
    ]);

    const runtimeReady = Boolean(healthRaw?.ok);
    const ollamaReady = Boolean(ollamaRaw?.running);
    const readiness = (healthRaw?.readiness as Record<string, unknown> | undefined) || {};
    const providers = Array.isArray(setupRaw?.providers) ? setupRaw.providers : [];
    const providerSummary = {
      available: providers.filter((provider) => ["connected", "available", "ready"].includes(String(provider.status || "").toLowerCase())).length,
      authRequired: providers.filter((provider) => String(provider.status || "").toLowerCase().includes("key") || String(provider.status || "").toLowerCase().includes("auth")).length,
      degraded: providers.filter((provider) => ["degraded", "error", "unreachable"].includes(String(provider.status || "").toLowerCase())).length,
    };

    let bootStage: SystemReadiness["bootStage"] = "ready";
    let status: SystemReadiness["status"] = "ready";
    let blockingIssue = "";

    if (!runtimeReady) {
      bootStage = "starting_services";
      status = "booting";
      blockingIssue = "Local services are still starting.";
    } else if (!ollamaReady) {
      bootStage = "loading_local_models";
      status = "needs_attention";
      blockingIssue = "Ollama is unavailable. Local model lanes are limited.";
    } else if (providerSummary.authRequired || providerSummary.degraded) {
      bootStage = "checking_providers";
      status = "needs_attention";
      blockingIssue = providerSummary.authRequired
        ? "Some cloud providers need API keys."
        : "Some providers are degraded right now.";
    }

    return {
      status,
      bootStage,
      runtimeReady,
      setupComplete: Boolean(readiness.setup_complete ?? runtimeReady),
      ollamaReady,
      channelConnected: Boolean(readiness.channel_connected),
      hasRoutine: Boolean(readiness.has_routine),
      hasDailySummaryRun: Boolean(readiness.has_daily_summary_run),
      connectedProvider: String(readiness.connected_provider || ""),
      connectedModel: String(readiness.connected_model || ""),
      productivityAppsReady: Boolean(readiness.productivity_apps_ready ?? runtimeReady),
      bluebubblesReady: Boolean(readiness.bluebubbles_ready),
      whatsappMode: (String(readiness.whatsapp_mode || "unavailable") as SystemReadiness["whatsappMode"]) || "unavailable",
      applePermissions: {
        automation: Boolean((readiness.apple_permissions as Record<string, unknown> | undefined)?.automation),
        screenCapture: Boolean((readiness.apple_permissions as Record<string, unknown> | undefined)?.screen_capture),
      },
      providerSummary,
      platforms: {
        activeSurfaces: Number(platformsRaw?.summary?.active || 0),
        configuredChannels: Number(platformsRaw?.summary?.configured_channels || 0),
        connectedChannels: Number(platformsRaw?.summary?.connected_channels || 0),
        connectedLabels: Array.isArray(platformsRaw?.summary?.connected_labels)
          ? platformsRaw.summary.connected_labels.map((item) => String(item || "").trim()).filter(Boolean)
          : [],
      },
      blockingIssue,
    };
  });
}

export async function getProviderDescriptors(): Promise<ProviderDescriptor[]> {
  return withMemoryCache("provider-descriptors", 8000, async () => {
    const [modelsRaw, setupRaw, ollamaRaw] = await Promise.all([
      safeRequest<ModelsEnvelope>("/api/models"),
      safeRequest<LlmSetupStatusEnvelope>("/api/llm/setup/status"),
      safeRequest<OllamaStatusEnvelope>("/api/llm/setup/ollama"),
    ]);
    return buildProviderDescriptors(modelsRaw, setupRaw, ollamaRaw);
  });
}

export async function saveProviderKey(provider: string, apiKey: string): Promise<{ ok: boolean; message: string }> {
  const raw = await apiClient.request<{ ok?: boolean; message?: string; error?: string }>("/api/llm/setup/save-key", {
    method: "POST",
    body: { provider, api_key: apiKey },
  });
  if (raw.ok) {
    invalidateMemoryCache(["provider-descriptors", "providers-summary", "system-readiness"]);
  }
  return { ok: Boolean(raw.ok), message: String(raw.message || raw.error || "") };
}

export async function removeProviderKey(provider: string): Promise<{ ok: boolean; message: string }> {
  const raw = await apiClient.request<{ ok?: boolean; message?: string; error?: string }>("/api/llm/setup/remove-key", {
    method: "POST",
    body: { provider },
  });
  if (raw.ok) {
    invalidateMemoryCache(["provider-descriptors", "providers-summary", "system-readiness"]);
  }
  return { ok: Boolean(raw.ok), message: String(raw.message || raw.error || "") };
}

export async function pullOllamaModel(model: string): Promise<{ ok: boolean; message: string }> {
  const raw = await apiClient.request<{ ok?: boolean; message?: string; error?: string }>("/api/llm/setup/ollama-pull", {
    method: "POST",
    body: { model },
  });
  if (raw.ok) {
    invalidateMemoryCache(["provider-descriptors", "providers-summary", "system-readiness"]);
  }
  return { ok: Boolean(raw.ok), message: String(raw.message || raw.error || "") };
}

export async function deleteOllamaModel(model: string): Promise<{ ok: boolean; message: string }> {
  const raw = await apiClient.request<{ ok?: boolean; message?: string; error?: string }>("/api/llm/setup/ollama-delete", {
    method: "POST",
    body: { model },
  });
  if (raw.ok) {
    invalidateMemoryCache(["provider-descriptors", "providers-summary", "system-readiness"]);
  }
  return { ok: Boolean(raw.ok), message: String(raw.message || raw.error || "") };
}

export async function updateProviderLanePreferences(payload: {
  defaultProvider: string;
  defaultModel: string;
  fallbackProvider: string;
  fallbackModel: string;
}): Promise<boolean> {
  const raw = await apiClient.request<{ ok?: boolean }>("/api/models", {
    method: "POST",
    body: {
      provider: payload.defaultProvider,
      model: payload.defaultModel,
      fallback_provider: payload.fallbackProvider,
      fallback_model: payload.fallbackModel,
      sync_roles: true,
    },
  });
  if (raw.ok) {
    invalidateMemoryCache(["provider-descriptors", "providers-summary"]);
  }
  return Boolean(raw.ok);
}

export async function getIntegrations(): Promise<IntegrationSummary[]> {
  return withMemoryCache("integrations-summary", 10000, async () => {
    const connectors = await getConnectors();
    if (!connectors.length) {
      return DEFAULT_INTEGRATIONS;
    }
    return connectors.map((connector): IntegrationSummary => ({
      id: connector.connector,
      kind: connector.integrationType === "email" ? "channel" : connector.integrationType === "api" ? "devtool" : "automation",
      name: connector.label,
      status:
        connector.status === "connected"
          ? "connected"
          : connector.status === "pending"
            ? "pending"
            : connector.status === "degraded"
              ? "degraded"
              : "offline",
      detail: `${connector.accountCount} accounts · ${connector.traceCount} traces`,
    }));
  });
}

export async function getLogs(): Promise<LogEvent[]> {
  const [securityEvents, connectorTraces, threadsRaw] = await Promise.all([
    getSecurityEvents(20),
    getConnectorTraces(),
    safeRequest<SuccessEnvelope<{ threads: Array<Record<string, unknown>> }>>("/api/v1/cowork/threads?limit=8"),
  ]);
  const threadEvents: LogEvent[] = Array.isArray(threadsRaw?.threads)
    ? threadsRaw.threads.map((item) => {
        const thread = mapThreadSummary(item);
        return {
          id: thread.threadId,
          level: thread.status === "failed" ? "error" : thread.pendingApprovals > 0 ? "warning" : "info",
          source: "cowork",
          title: thread.title,
          detail: thread.lastOperatorTurn?.content || thread.lastUserTurn?.content || thread.status,
          timestamp: thread.updatedAt,
          category: "runtime",
          rawTimestamp: thread.rawTimestamp,
          payload: { currentMode: thread.currentMode, status: thread.status },
        };
      })
    : [];
  const connectorEvents: LogEvent[] = connectorTraces.map((trace) => ({
    id: trace.traceId,
    level: trace.success ? "success" : "warning",
    source: "connector",
    title: `${trace.connectorName} · ${trace.operation}`,
    detail: trace.status,
    timestamp: trace.createdAt,
    category: "runtime",
    rawTimestamp: trace.rawTimestamp,
    payload: trace.metadata,
  }));
  const merged = [...securityEvents, ...connectorEvents, ...threadEvents].sort((a, b) => (b.rawTimestamp || 0) - (a.rawTimestamp || 0));
  return merged.length ? merged : DEFAULT_LOGS;
}

export { getSecuritySummary };
