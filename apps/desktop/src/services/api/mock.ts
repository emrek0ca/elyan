import type {
  ActivityItem,
  CommandCenterSnapshot,
  HomeSnapshot,
  IntegrationSummary,
  LogEvent,
  ProviderSummary,
  SecuritySummary,
} from "@/types/domain";

export const mockProviders: ProviderSummary[] = [
  { id: "openai", name: "OpenAI", model: "gpt-5.4", latencyMs: 820, usageToday: 124000, status: "connected", detail: "Primary reasoning lane" },
  { id: "google", name: "Google", model: "gemini-2.0-flash", latencyMs: 610, usageToday: 88000, status: "connected", detail: "Low-latency fallback" },
  { id: "groq", name: "Groq", model: "llama-3.3-70b", latencyMs: 190, usageToday: 52000, status: "connected", detail: "Fast semantic routing" },
  { id: "ollama", name: "Ollama", model: "qwen2.5-vl", latencyMs: 1400, usageToday: 0, status: "degraded", detail: "Local vision lane" },
];

export const mockIntegrations: IntegrationSummary[] = [
  { id: "desktop", kind: "device", name: "Desktop Agent", status: "connected", detail: "Local control plane online" },
  { id: "telegram", kind: "channel", name: "Telegram", status: "connected", detail: "Message ingress active" },
  { id: "github", kind: "devtool", name: "GitHub", status: "pending", detail: "Access review required" },
  { id: "scheduler", kind: "automation", name: "Automation Engine", status: "connected", detail: "Background jobs available" },
];

export const mockActivity: ActivityItem[] = [
  { id: "a1", title: "Task completed", detail: "Research summary delivered", source: "run", level: "success", createdAt: "Now" },
  { id: "a2", title: "Model switched", detail: "Groq selected for semantic routing", source: "system", level: "info", createdAt: "2m ago" },
  { id: "a3", title: "Approval requested", detail: "Terminal write requires confirmation", source: "approval", level: "warning", createdAt: "6m ago" },
];

export const mockLogs: LogEvent[] = [
  { id: "l1", level: "info", source: "runtime", title: "Session resolved", detail: "workspace=local actor=desktop", timestamp: "20:11" },
  { id: "l2", level: "success", source: "tool", title: "Tool succeeded", detail: "browser_navigate latency=842ms", timestamp: "20:12" },
  { id: "l3", level: "warning", source: "security", title: "Secret redacted", detail: "Cloud escalation removed sensitive fragments before provider handoff", timestamp: "20:13", category: "security" },
  { id: "l4", level: "error", source: "security", title: "Prompt blocked", detail: "Ingress firewall blocked a suspicious override attempt", timestamp: "20:14", category: "security" },
];

export const mockSecurity: SecuritySummary = {
  posture: "balanced",
  deploymentScope: "single_user_local_first",
  dataLocality: "local_only",
  cloudPromptRedaction: true,
  allowCloudFallback: true,
  pendingApprovals: 1,
  activeSessions: 3,
  sessionPersistence: true,
  handoffPending: 2,
  semanticBackend: "qdrant",
};

export const mockCommandCenter: CommandCenterSnapshot = {
  runs: [
    { id: "r1", title: "Release notes synthesis", status: "running", toolCount: 6, updatedAt: "Now", summary: "Collecting artifacts and drafting output" },
    { id: "r2", title: "Security log review", status: "completed", toolCount: 4, updatedAt: "12m ago", summary: "No critical findings" },
    { id: "r3", title: "Desktop automation setup", status: "approval", toolCount: 3, updatedAt: "18m ago", summary: "Awaiting filesystem approval" },
  ],
  approvals: [
    { id: "p1", action: "Write config to workspace", priority: "normal", confidence: 0.92 },
  ],
  outputBlocks: [
    { id: "o1", kind: "thinking", title: "Intent analysis", body: "Task normalized into research + verification + delivery.", meta: "Planner · 320 ms" },
    { id: "o2", kind: "action", title: "Tool execution", body: "web_search → summarize → verify_source", meta: "3 tools active" },
    { id: "o3", kind: "evidence", title: "Evidence bundle", body: "2 sources attached, 1 screenshot, 1 timeline snapshot", meta: "Audit ready" },
    { id: "o4", kind: "result", title: "Result draft", body: "Executive summary prepared. Waiting on approval for final write.", meta: "Confidence 0.88" },
  ],
  security: mockSecurity,
  securityEvents: mockLogs.filter((item) => item.category === "security"),
};

export const mockHome = (): HomeSnapshot => ({
  workspace: { id: "local", name: "Local workspace", status: "connected", detail: "Operator runtime healthy" },
  providers: mockProviders,
  integrations: mockIntegrations,
  recentRuns: mockCommandCenter.runs,
  activity: mockActivity,
  metrics: {
    successRate: 0.94,
    avgLatencyMs: 720,
    activeAgents: 4,
    totalActions: 182,
  },
  metricCards: [
    { label: "Success rate", value: "94%", meta: "24h completion quality", tone: "success" },
    { label: "Avg latency", value: "720ms", meta: "Cross-provider median", tone: "neutral" },
    { label: "Active agents", value: "4", meta: "Contract net live workers", tone: "neutral" },
    { label: "Total actions", value: "182", meta: "Today across all runs", tone: "neutral" },
  ],
  backends: [
    { id: "python_core", label: "Python core", active: true, available: true, detail: "Canonical runtime active" },
    { id: "go_gateway", label: "Go gateway", active: false, available: false, detail: "Fallback to Python HTTP bridge" },
  ],
  workflowCards: [
    {
      id: "document",
      title: "Document flow",
      description: "Brief, outline, draft, review, export.",
      actionLabel: "Create document",
      agentLane: "executive → planner → artifact → review",
      status: "ready",
      meta: "Export-ready DOCX/PDF lane",
    },
    {
      id: "presentation",
      title: "Presentation flow",
      description: "Audience analysis, slide narrative, visual brief, export.",
      actionLabel: "Create presentation",
      agentLane: "executive → planner → artifact → review",
      status: "active",
      meta: "4 live agent contracts available",
    },
    {
      id: "website",
      title: "Website flow",
      description: "Strategy spec, design system, component tree, scaffold.",
      actionLabel: "Create website",
      agentLane: "executive → planner → code → review",
      status: "ready",
      meta: "React/TS scaffold output",
    },
  ],
  trustStrip: [
    { id: "runtime", label: "Runtime posture", value: "balanced", tone: "success", detail: "local only" },
    { id: "approvals", label: "Approval queue", value: "1", tone: "warning", detail: "review gate waiting" },
    { id: "memory", label: "Memory backend", value: "qdrant", tone: "success", detail: "persistent sessions" },
  ],
  recentArtifacts: [
    { id: "ra1", title: "Research report", kind: "document", status: "completed", updatedAt: "Now", summary: "Executive export ready" },
    { id: "ra2", title: "Pitch deck", kind: "presentation", status: "running", updatedAt: "12m ago", summary: "Slide outline in review" },
    { id: "ra3", title: "Landing scaffold", kind: "website", status: "approval", updatedAt: "18m ago", summary: "Awaiting filesystem approval" },
  ],
  recommendedFlow: "presentation",
});
