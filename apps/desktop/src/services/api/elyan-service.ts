import type {
  ActivityItem,
  BackendSummary,
  CommandCenterSnapshot,
  ConnectorAccount,
  ConnectorActionTrace,
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
  MetricSummary,
  ProviderSummary,
  RecentArtifactSummary,
  ReviewReport,
  RunSummary,
  SecuritySummary,
  TrustStripItem,
  UsageLedgerEntry,
  WorkflowTaskType,
  WorkflowLaunchCard,
  WorkspaceBillingSummary,
} from "@/types/domain";
import { apiClient } from "@/services/api/client";
import { mockCommandCenter, mockHome, mockIntegrations, mockLogs, mockProviders } from "@/services/api/mock";
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
          };
        })
      : [],
    laneSummary:
      item.lane_summary && typeof item.lane_summary === "object"
        ? {
            mode: String((item.lane_summary as Record<string, unknown>).mode || base.currentMode),
            runState: String((item.lane_summary as Record<string, unknown>).run_state || ""),
            missionState: String((item.lane_summary as Record<string, unknown>).mission_state || ""),
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

function mapBilling(payload: Record<string, unknown>): WorkspaceBillingSummary {
  const plan = (payload.plan as Record<string, unknown> | undefined) || {};
  const subscriptionState = (payload.subscription_state as Record<string, unknown> | undefined) || {};
  const usage = (payload.usage as Record<string, unknown> | undefined) || {};
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
      stripeCustomerId: String(subscriptionState.stripe_customer_id || ""),
      stripeSubscriptionId: String(subscriptionState.stripe_subscription_id || ""),
      currentPeriodEnd: Number(subscriptionState.current_period_end || 0) || undefined,
    },
    entitlements: mapEntitlements((payload.entitlements as Record<string, unknown> | undefined) || {}),
    usage: {
      totals: ((usage.totals as Record<string, number> | undefined) || {}) as Record<string, number>,
      budget: Number(usage.budget || 0),
      items: Array.isArray(usage.items) ? usage.items.map((item) => mapUsageEntry(item as Record<string, unknown>)) : [],
    },
    checkoutUrl: String(payload.checkout_url || ""),
    portalUrl: String(payload.portal_url || ""),
    seats: Number(payload.seats || 1),
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
  };
}

async function getSecuritySummary(): Promise<SecuritySummary> {
  const securityRaw = await safeRequest<SecurityEnvelope>("/api/v1/security/summary");
  if (!securityRaw?.success) {
    return mockCommandCenter.security;
  }
  return mapSecuritySummary(securityRaw.security);
}

async function getSecurityEvents(limit = 12): Promise<LogEvent[]> {
  const raw = await safeRequest<SuccessEnvelope<{ events: Array<Record<string, unknown>> }>>(`/api/v1/security/events?limit=${limit}`);
  if (!raw?.success || !Array.isArray(raw.events)) {
    return mockCommandCenter.securityEvents;
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
    : mockHome().backends;

  if (!homeRaw?.success) {
    const fallback = mockHome();
    return {
      workspace: fallback.workspace,
      recentThreads: [],
      lastThread: undefined,
      pendingApprovals: [],
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
    security,
    billing: homeRaw.billing && typeof homeRaw.billing === "object" ? mapBilling(homeRaw.billing) : undefined,
    backends,
  };
}

export async function getHomeSnapshot(): Promise<HomeSnapshotV2> {
  const [coworkHome, runsRaw] = await Promise.all([
    getCoworkHome(),
    safeRequest<SuccessEnvelope<{ runs: unknown[] }>>("/api/v1/runs?limit=6"),
  ]);

  const runs = Array.isArray(runsRaw?.runs)
    ? runsRaw.runs
        .map((item) => runSchema.safeParse(item))
        .filter((parsed) => parsed.success)
        .map((parsed): RunSummary => toRunSummary(parsed.data))
    : mockHome().recentRuns;

  const recentThreads = coworkHome.recentThreads || [];
  const activeAgents = coworkHome.backends.filter((backend) => backend.active).length || mockHome().metrics.activeAgents;
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
  ];

  const activity: ActivityItem[] = [
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

  return {
    workspace: coworkHome.workspace,
    providers: mockProviders,
    integrations: mockIntegrations,
    recentRuns: runs,
    activity: activity.length ? activity : mockHome().activity,
    metrics: {
      successRate: 0.93,
      avgLatencyMs: 680,
      activeAgents,
      totalActions: recentThreads.length + coworkHome.pendingApprovals.length,
    },
    metricCards,
    backends: coworkHome.backends.length ? coworkHome.backends : mockHome().backends,
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
    billing: coworkHome.billing,
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
    : mockCommandCenter.runs;

  const outputBlocks: CommandCenterSnapshot["outputBlocks"] = selectedThread
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
    : mockCommandCenter.outputBlocks;

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

  return {
    threads,
    selectedThread: selectedThread || undefined,
    runs: runs.length ? runs : mockCommandCenter.runs,
    approvals: approvals.map((approval) => ({
      id: approval.id,
      action: approval.title,
      priority: approval.riskLevel === "high" ? "high" : approval.riskLevel === "critical" ? "critical" : "normal",
      confidence: undefined,
    })),
    outputBlocks,
    security,
    securityEvents: securityEvents.length ? securityEvents : mockCommandCenter.securityEvents,
    controlActions: selectedThread?.controlActions || [],
    selectedRun: selectedRunSummary,
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

type CoworkThreadPayload = {
  prompt: string;
  current_mode?: "cowork" | "document" | "presentation" | "website";
  session_id?: string;
  project_template_id?: string;
  project_name?: string;
  routing_profile?: string;
  review_strictness?: string;
  workspace_id?: string;
};

export async function createCoworkThread(payload: CoworkThreadPayload): Promise<CoworkThreadDetail> {
  const raw = await apiClient.request<SuccessEnvelope<{ thread: Record<string, unknown> }>>("/api/v1/cowork/threads", {
    method: "POST",
    body: payload,
  });
  return mapThreadDetail(raw.thread);
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

export async function createCheckoutSession(planId: string): Promise<string> {
  const raw = await apiClient.request<SuccessEnvelope<{ checkout: { url?: string } }>>("/api/v1/billing/checkout-session", {
    method: "POST",
    body: { plan_id: planId },
  });
  return String(raw.checkout?.url || "");
}

export async function createPortalSession(): Promise<string> {
  const raw = await apiClient.request<SuccessEnvelope<{ portal: { url?: string } }>>("/api/v1/billing/portal-session", {
    method: "POST",
    body: {},
  });
  return String(raw.portal?.url || "");
}

export async function getConnectors(): Promise<ConnectorDefinition[]> {
  const raw = await safeRequest<SuccessEnvelope<{ connectors: Array<Record<string, unknown>> }>>("/api/v1/connectors");
  if (!raw?.success) {
    return [];
  }
  return Array.isArray(raw.connectors) ? raw.connectors.map((item) => mapConnector(item)) : [];
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
  return raw.account ? mapConnectorAccount(raw.account) : null;
}

export async function revokeConnectorAccount(accountId: string): Promise<boolean> {
  const raw = await apiClient.request<SuccessEnvelope<{ success: boolean }>>(`/api/v1/connectors/accounts/${encodeURIComponent(accountId)}/revoke`, {
    method: "POST",
    body: {},
  });
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

export async function getProviders(): Promise<ProviderSummary[]> {
  return mockProviders;
}

export async function getIntegrations(): Promise<IntegrationSummary[]> {
  const connectors = await getConnectors();
  if (!connectors.length) {
    return mockIntegrations;
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
  return merged.length ? merged : mockLogs;
}

export { getSecuritySummary };
