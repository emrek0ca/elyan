import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Clock3, RefreshCw, Sparkles } from "@/vendor/lucide-react";
import { useNavigate } from "react-router-dom";
import { ElyanPanel } from "@/features/elyan/ElyanPanel";
import { TaskTreePanel } from "@/features/elyan/TaskTreePanel";
import { ChatView } from "@/features/elyan/ChatView";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Surface } from "@/components/primitives/Surface";
import {
  useHomeSnapshot,
  useOperatorPreview,
  useProviderDescriptors,
  useSystemReadiness,
} from "@/hooks/use-desktop-data";
import { createCoworkThread, createRoutineFromText, promoteRoutineDraft, promoteSkillDraft, triggerAutopilotTick } from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import type { CoworkMode } from "@/types/domain";
import { getRuntimeGateReason, hasRuntimeWriteAccess } from "@/utils/runtime-access";
import {
  inferReviewStrictness,
  inferRoutingProfile,
  mergeWorkflowPreferences,
  resolveProjectTemplate,
} from "@/utils/workflow-preferences";

export function HomeScreen() {
  const { data, isLoading, error, refetch } = useHomeSnapshot();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [command, setCommand] = useState("");
  const [launchingFlow, setLaunchingFlow] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState("");
  const [draftActionId, setDraftActionId] = useState<string | null>(null);
  const [draftActionError, setDraftActionError] = useState("");
  const [checkInBusy, setCheckInBusy] = useState(false);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [automationMessage, setAutomationMessage] = useState("");
  const [automationMessageTone, setAutomationMessageTone] = useState<"success" | "warning">("warning");
  const { data: providers } = useProviderDescriptors();
  const { data: readiness } = useSystemReadiness();
  const connectionState = useRuntimeStore((s) => s.connectionState);
  const sidecarHealth = useRuntimeStore((s) => s.sidecarHealth);
  const setSelectedThreadId = useUiStore((s) => s.setSelectedThreadId);
  const setSelectedRunId = useUiStore((s) => s.setSelectedRunId);
  const workflowPreferences = useUiStore((s) => s.workflowPreferences);
  const productSettings = useUiStore((s) => s.productSettings);
  const projectTemplates = useUiStore((s) => s.projectTemplates);
  const activeProjectTemplateId = useUiStore((s) => s.activeProjectTemplateId);

  if (error) {
    return <ErrorState title="Bağlantı kurulamadı" description="Runtime erişilemiyor." onRetry={() => void refetch()} />;
  }
  if (isLoading || !data) {
    return <SkeletonBlock className="h-[320px] w-full rounded-[32px]" />;
  }

  const activeProjectTemplate = resolveProjectTemplate(projectTemplates, activeProjectTemplateId);
  const effectivePreferences = mergeWorkflowPreferences(workflowPreferences, activeProjectTemplate.preferences);
  const resumeCandidate = data.lastThread || data.recentThreads?.[0];
  const runtimeReady = hasRuntimeWriteAccess(connectionState, sidecarHealth);
  const runtimeGateReason = getRuntimeGateReason(connectionState, sidecarHealth);
  const autopilot = data.autopilot;
  const backgroundTasks = (data.backgroundTasks || []).filter((t) => !["completed", "failed", "cancelled"].includes(t.state)).slice(0, 3);
  const suggestions = (autopilot?.suggestions || []).slice(0, 3);
  const providerCount = (providers || []).filter((p) => p.enabled && p.healthState === "available").length;
  const learningQueue = data.learningQueue;
  const resumePreviewText = resumeCandidate?.lastUserTurn?.content || resumeCandidate?.title || "";
  const { data: resumePreview } = useOperatorPreview(
    resumePreviewText,
    resumeCandidate?.sessionId || resumeCandidate?.threadId || "home-preview",
    resumeCandidate?.threadId || "home-latest",
  );
  const automationCandidate = resumePreview?.goalGraph?.automationCandidate;
  const setupPriority = ["provider_model", "channel_connection", "first_routine", "first_daily_summary", "learning_queue"];
  const setupChecklist = (data.setupChecklist || [])
    .filter((item) => !item.ready)
    .sort((left, right) => {
      const leftIndex = setupPriority.indexOf(left.key);
      const rightIndex = setupPriority.indexOf(right.key);
      const a = leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex;
      const b = rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex;
      return a - b;
    })
    .slice(0, 5);
  const readinessTone: "success" | "warning" | "neutral" = readiness
    ? readiness.status === "ready"
      ? "success"
      : readiness.status === "needs_attention"
        ? "warning"
        : "neutral"
    : "neutral";
  const readinessLabel = readiness
    ? readiness.status === "ready"
      ? "Hazır"
      : readiness.status === "needs_attention"
        ? "Dikkat gerekiyor"
        : "Başlatılıyor"
    : "Bilinmiyor";
  const connectedChannelSummary = readiness?.platforms?.connectedLabels?.length
    ? readiness.platforms.connectedLabels.join(", ")
    : readiness?.channelConnected
      ? "Connected"
      : readiness?.whatsappMode === "bridge"
        ? "Bridge mode"
        : "Pending";

  function inferTaskType(value: string): "document" | "presentation" | "website" {
    const t = value.toLowerCase();
    if (/(slide|deck|sunum|ppt)/.test(t)) return "presentation";
    if (/(site|website|landing|web|react)/.test(t)) return "website";
    return "document";
  }

  async function launch(taskType: CoworkMode, brief: string) {
    if (!runtimeReady) { setLaunchError(runtimeGateReason); return; }
    setLaunchError("");
    setLaunchingFlow(taskType);
    try {
      const profile = taskType === "cowork" ? inferTaskType(brief) : taskType;
      const thread = await createCoworkThread({
        prompt: brief.trim() || "Start a new task.",
        current_mode: taskType,
        session_id: activeProjectTemplate.sessionId,
        project_template_id: activeProjectTemplate.id,
        project_name: activeProjectTemplate.name,
        routing_profile: inferRoutingProfile(profile, effectivePreferences, activeProjectTemplate, useUiStore.getState().autoRouting),
        review_strictness: inferReviewStrictness(profile, effectivePreferences, activeProjectTemplate),
        response_mode: productSettings.responseMode,
        provider_strategy: productSettings.providerStrategy,
        privacy_mode: productSettings.privacyMode,
        automation_level: productSettings.automationLevel,
        tone: productSettings.tone,
      });
      setSelectedThreadId(thread.threadId);
      if (thread.activeRunId) setSelectedRunId(thread.activeRunId);
      setCommand("");
      void queryClient.invalidateQueries({ queryKey: ["home-snapshot"] });
      navigate("/command-center");
    } catch (e) {
      setLaunchError(e instanceof Error ? e.message : "Başlatılamadı");
    } finally {
      setLaunchingFlow(null);
    }
  }

  async function checkIn() {
    setCheckInBusy(true);
    try {
      await triggerAutopilotTick("desktop_checkin");
      void queryClient.invalidateQueries({ queryKey: ["home-snapshot"] });
    } finally {
      setCheckInBusy(false);
    }
  }

  async function handlePromoteDraft(draft: NonNullable<HomeSnapshotLike["learningQueue"]>["items"][number]) {
    setDraftActionError("");
    setDraftActionId(draft.id);
    try {
      if (draft.type === "skill") {
        const result = await promoteSkillDraft(draft.id, { skillName: draft.title });
        if (!result.ok) {
          setDraftActionError(result.message || "Skill draft promote edilemedi.");
          return;
        }
      } else {
        const result = await promoteRoutineDraft(draft.id, {
          name: draft.title,
          reportChannel: draft.deliveryChannel,
        });
        if (!result.ok) {
          setDraftActionError(result.message || "Routine draft promote edilemedi.");
          return;
        }
      }
      await queryClient.invalidateQueries({ queryKey: ["home-snapshot"] });
    } finally {
      setDraftActionId(null);
    }
  }

  async function handleCreateAutomation() {
    if (!automationCandidate) {
      return;
    }
    if (!runtimeReady) {
      setAutomationMessageTone("warning");
      setAutomationMessage(runtimeGateReason);
      return;
    }
    setAutomationBusy(true);
    setAutomationMessage("");
    try {
      const result = await createRoutineFromText({
        text: `${automationCandidate.task} ${automationCandidate.cron ? `(${automationCandidate.cron})` : ""}`.trim(),
        name: automationCandidate.task,
        expression: automationCandidate.cron || resumePreview?.goalGraph?.constraints.scheduleExpression || "",
        reportChannel: "telegram",
        enabled: true,
      });
      if (!result.ok) {
        setAutomationMessageTone("warning");
        setAutomationMessage(result.message || "Routine oluşturulamadı.");
        return;
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
        queryClient.invalidateQueries({ queryKey: ["command-center"] }),
      ]);
      setAutomationMessageTone("success");
      setAutomationMessage(`Automation hazır: ${result.name || result.routineId}`);
    } finally {
      setAutomationBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      {/* ─── Command ─── */}
      <Surface tone="hero" className="px-8 py-8 lg:px-10 lg:py-10">
        <div className="flex items-center gap-3">
          <Sparkles className="h-5 w-5 text-[var(--accent-primary)]" />
          <h1 className="font-display text-[28px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Elyan</h1>
        </div>

        <div className="mt-5">
          <SearchField
            value={command}
            onChange={(e) => { setCommand(e.target.value); setLaunchError(""); }}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void launch(inferTaskType(command), command); } }}
            placeholder="Ne yapayım?"
            className="h-14 rounded-[20px] px-5 text-[15px] shadow-none"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={() => void launch(inferTaskType(command), command)} disabled={!runtimeReady || !!launchingFlow}>
            {launchingFlow ? "Başlatılıyor…" : "Başlat"}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
          {resumeCandidate ? (
            <Button variant="secondary" onClick={() => { setSelectedThreadId(resumeCandidate.threadId); if (resumeCandidate.activeRunId) setSelectedRunId(resumeCandidate.activeRunId); navigate("/command-center"); }}>
              <Clock3 className="mr-2 h-4 w-4" />
              Devam et
            </Button>
          ) : null}
          {!runtimeReady ? (
            <Button variant="ghost" onClick={() => void refetch()}>
              <RefreshCw className="mr-2 h-4 w-4" />
              Yeniden dene
            </Button>
          ) : null}
        </div>

        {launchError ? <p className="mt-3 text-[12px] text-[var(--state-warning)]">{launchError}</p> : null}
        {!launchError && !runtimeReady ? <p className="mt-3 text-[12px] text-[var(--text-tertiary)]">{runtimeGateReason}</p> : null}
      </Surface>

      {/* ─── Status Tiles ─── */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatusTile label="Runtime" value={runtimeReady ? "Hazır" : "Bekleniyor"} tone={runtimeReady ? "success" : "warning"} />
        <StatusTile label="Modeller" value={providerCount ? `${providerCount} aktif` : "Yok"} tone={providerCount ? "success" : "warning"} />
        <StatusTile label="Autopilot" value={autopilot?.running ? "Aktif" : "Pasif"} tone={autopilot?.running ? "success" : "neutral"} />
        <StatusTile label="Arka plan" value={backgroundTasks.length ? `${backgroundTasks.length} iş` : "Boş"} tone={backgroundTasks.length ? "info" : "neutral"} />
      </div>

      {readiness ? (
        <Surface tone="card" className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Operator readiness</div>
              <h2 className="mt-2 text-[18px] font-medium text-[var(--text-primary)]">
                {readiness.connectedProvider || "local"}{readiness.connectedModel ? ` / ${readiness.connectedModel}` : ""}
              </h2>
              <p className="mt-2 text-[12px] text-[var(--text-secondary)]">
                {readiness.blockingIssue || "Runtime, provider ve automations hizalanmış görünüyor."}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge tone={readinessTone}>{readinessLabel}</StatusBadge>
              <StatusBadge tone={readiness.runtimeReady ? "success" : "warning"}>
                {readiness.runtimeReady ? "runtime live" : "runtime waiting"}
              </StatusBadge>
              <StatusBadge tone={readiness.channelConnected ? "success" : "neutral"}>
                {readiness.channelConnected ? "channel connected" : "channel pending"}
              </StatusBadge>
              <StatusBadge tone={readiness.hasRoutine ? "success" : "neutral"}>
                {readiness.hasRoutine ? "automation ready" : "no routine yet"}
              </StatusBadge>
            </div>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <ReadinessItem
              label="Providers"
              value={`${readiness.providerSummary.available} ready`}
              meta={
                readiness.providerSummary.authRequired
                  ? `${readiness.providerSummary.authRequired} auth gerekiyor`
                  : readiness.providerSummary.degraded
                    ? `${readiness.providerSummary.degraded} degraded`
                    : "Tüm lane'ler temiz"
              }
            />
            <ReadinessItem
              label="Channels"
              value={`${readiness.platforms?.connectedChannels || 0} live / ${readiness.platforms?.configuredChannels || 0} configured`}
              meta={
                readiness.whatsappMode === "unavailable"
                  ? `Channels: ${connectedChannelSummary}`
                  : `${connectedChannelSummary} · WhatsApp: ${readiness.whatsappMode}`
              }
            />
            <ReadinessItem
              label="Permissions"
              value={readiness.applePermissions.automation ? "Automation ok" : "Permission needed"}
              meta={readiness.applePermissions.screenCapture ? "Screen capture ready" : "Screen capture pending"}
            />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {!readiness.runtimeReady || readiness.blockingIssue ? (
              <Button variant="secondary" onClick={() => navigate("/settings")}>
                Fix readiness
              </Button>
            ) : null}
            {!readiness.channelConnected ? (
              <Button variant="ghost" onClick={() => navigate("/integrations")}>
                Connect channels
              </Button>
            ) : null}
            {readiness.providerSummary.authRequired || readiness.providerSummary.degraded ? (
              <Button variant="ghost" onClick={() => navigate("/providers")}>
                Review providers
              </Button>
            ) : null}
          </div>
        </Surface>
      ) : null}

      {resumeCandidate && automationCandidate ? (
        <Surface tone="card" className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Suggested automation</div>
              <h2 className="mt-2 text-[18px] font-medium text-[var(--text-primary)]">
                {automationCandidate.task || "Scheduled routine"}
              </h2>
              <p className="mt-2 text-[12px] text-[var(--text-secondary)]">
                {automationCandidate.cron || resumePreview?.goalGraph?.constraints.scheduleExpression || "schedule not detected"}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {resumePreview?.goalGraph?.primaryDeliveryDomain ? (
                <StatusBadge tone="info">{resumePreview.goalGraph.primaryDeliveryDomain}</StatusBadge>
              ) : null}
              {resumePreview?.goalGraph?.stageCount ? (
                <StatusBadge tone="neutral">{resumePreview.goalGraph.stageCount} stage</StatusBadge>
              ) : null}
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => void handleCreateAutomation()} disabled={automationBusy || !runtimeReady}>
              {automationBusy ? "Scheduling…" : "Create routine"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setSelectedThreadId(resumeCandidate.threadId);
                if (resumeCandidate.activeRunId) {
                  setSelectedRunId(resumeCandidate.activeRunId);
                }
                navigate("/command-center");
              }}
            >
              Open thread
            </Button>
          </div>
          {automationMessage ? (
            <p className={`mt-3 text-[12px] ${automationMessageTone === "success" ? "text-[var(--state-success)]" : "text-[var(--state-warning)]"}`}>
              {automationMessage}
            </p>
          ) : null}
        </Surface>
      ) : null}

      {learningQueue && learningQueue.total > 0 ? (
        <Surface tone="card" className="p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-[13px] font-medium text-[var(--text-primary)]">Learned drafts</h2>
              <p className="mt-1 text-[12px] text-[var(--text-secondary)]">
                {learningQueue.skills} skill, {learningQueue.routines} routine, {learningQueue.preferences} preference draft review bekliyor.
              </p>
            </div>
            <StatusBadge tone="warning">{`${learningQueue.total} pending`}</StatusBadge>
          </div>
          <div className="mt-4 grid gap-3 xl:grid-cols-2">
            {learningQueue.items.map((draft) => (
              <div key={draft.id} className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">{draft.title}</div>
                    <div className="mt-1 text-[12px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">{draft.type}</div>
                  </div>
                  <StatusBadge tone="warning">{draft.status}</StatusBadge>
                </div>
                <p className="mt-3 text-[12px] leading-6 text-[var(--text-secondary)]">{draft.detail || "Açıklama yok."}</p>
                {draft.type === "routine" && draft.scheduleExpression ? (
                  <p className="mt-2 text-[11px] text-[var(--text-tertiary)]">
                    {draft.scheduleExpression}{draft.deliveryChannel ? ` · ${draft.deliveryChannel}` : ""}
                  </p>
                ) : null}
                <div className="mt-4 flex items-center gap-2">
                  <Button variant="secondary" onClick={() => void handlePromoteDraft(draft)} disabled={draftActionId === draft.id}>
                    {draftActionId === draft.id ? "Promoting…" : draft.type === "skill" ? "Promote skill" : "Promote routine"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
          {draftActionError ? <p className="mt-3 text-[12px] text-[var(--state-warning)]">{draftActionError}</p> : null}
        </Surface>
      ) : null}

      {setupChecklist.length ? (
        <Surface tone="card" className="p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-[13px] font-medium text-[var(--text-primary)]">Release path</h2>
              <p className="mt-1 text-[12px] text-[var(--text-secondary)]">Kalan kritik setup adımları.</p>
            </div>
          </div>
          <div className="mt-4 space-y-2">
            {setupChecklist.map((item) => (
              <div key={item.key} className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[13px] text-[var(--text-primary)]">{item.label}</span>
                  <StatusBadge tone="warning">pending</StatusBadge>
                </div>
                {item.detail ? <p className="mt-1 text-[12px] text-[var(--text-secondary)]">{item.detail}</p> : null}
              </div>
            ))}
          </div>
        </Surface>
      ) : null}

      {/* ─── Elyan Chat ─── */}
      <ChatView className="min-h-[460px]" />

      {/* ─── Elyan Panel ─── */}
      <ElyanPanel />

      {/* ─── Task Tree ─── */}
      <TaskTreePanel />

      {/* ─── Suggestions + Tasks ─── */}
      <div className="grid gap-5 xl:grid-cols-2">
        {/* Suggestions */}
        <Surface tone="card" className="p-5">
          <div className="flex items-center justify-between">
            <h2 className="text-[13px] font-medium text-[var(--text-primary)]">Öneriler</h2>
            <Button variant="ghost" className="h-8 px-3 text-[11px]" onClick={() => void checkIn()} disabled={checkInBusy}>
              {checkInBusy ? "…" : "Check-in"}
            </Button>
          </div>
          <div className="mt-3 space-y-2">
            {suggestions.length ? suggestions.map((s, i) => (
              <button
                key={`${s.task}-${i}`}
                type="button"
                onClick={() => setCommand(s.description || s.task)}
                className="w-full rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-3 text-left transition hover:bg-[var(--bg-surface)]"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-[13px] text-[var(--text-primary)]">{s.task}</span>
                  <StatusBadge tone={s.priority === "high" ? "warning" : "neutral"}>{s.priority}</StatusBadge>
                </div>
              </button>
            )) : (
              <p className="py-4 text-center text-[12px] text-[var(--text-tertiary)]">Henüz öneri yok</p>
            )}
          </div>
        </Surface>

        {/* Active tasks */}
        <Surface tone="card" className="p-5">
          <h2 className="text-[13px] font-medium text-[var(--text-primary)]">Aktif işler</h2>
          <div className="mt-3 space-y-2">
            {backgroundTasks.length ? backgroundTasks.map((task) => (
              <div key={task.taskId} className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-[13px] text-[var(--text-primary)]">{task.objective || "Görev"}</span>
                  <StatusBadge tone={task.state === "running" ? "success" : "info"}>{task.state}</StatusBadge>
                </div>
              </div>
            )) : (
              <p className="py-4 text-center text-[12px] text-[var(--text-tertiary)]">Arka planda iş yok</p>
            )}
          </div>
        </Surface>
      </div>
    </div>
  );
}

type HomeSnapshotLike = {
  learningQueue?: {
    items: Array<{
      id: string;
      type: "skill" | "routine";
      title: string;
      detail: string;
      status: string;
      deliveryChannel?: string;
      scheduleExpression?: string;
    }>;
  };
};

/* ─── Compact status tile ─── */
function StatusTile({ label, value, tone }: { label: string; value: string; tone: "success" | "warning" | "info" | "neutral" }) {
  return (
    <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4 shadow-[var(--shadow-soft-inset)]">
      <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{label}</div>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-[15px] font-medium text-[var(--text-primary)]">{value}</span>
        <StatusBadge tone={tone}>{value}</StatusBadge>
      </div>
    </div>
  );
}

function ReadinessItem({ label, value, meta }: { label: string; value: string; meta: string }) {
  return (
    <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-4">
      <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{label}</div>
      <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">{value}</div>
      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{meta}</div>
    </div>
  );
}
