import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Clock3, RefreshCw, Sparkles } from "@/vendor/lucide-react";
import { useNavigate } from "react-router-dom";
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

function formatBillingResetLabel(timestamp?: number) {
  if (!timestamp || timestamp <= 0) {
    return "Yok";
  }
  return new Date(timestamp * 1000).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function HomeScreen() {
  const { data, isLoading, error, refetch } = useHomeSnapshot();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [command, setCommand] = useState("");
  const [launchingFlow, setLaunchingFlow] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState("");
  const [draftActionId, setDraftActionId] = useState<string | null>(null);
  const [draftActionError, setDraftActionError] = useState("");
  const [automationBusy, setAutomationBusy] = useState(false);
  const [automationMessage, setAutomationMessage] = useState("");
  const [automationMessageTone, setAutomationMessageTone] = useState<"success" | "warning">("warning");
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
  const billing = data.billing;
  const runtimeReady = hasRuntimeWriteAccess(connectionState, sidecarHealth);
  const runtimeGateReason = getRuntimeGateReason(connectionState, sidecarHealth);
  const backgroundTasks = (data.backgroundTasks || []).filter((t) => !["completed", "failed", "cancelled"].includes(t.state)).slice(0, 3);
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
  const readinessTone: "success" | "warning" | "neutral" =
    readiness?.status === "ready" ? "success" : readiness?.status === "needs_attention" ? "warning" : "neutral";
  const readinessLabel =
    readiness?.status === "ready" ? "Hazır" : readiness?.status === "needs_attention" ? "Dikkat gerekiyor" : "Başlatılıyor";
  const connectedChannelSummary = useMemo(() => {
    if (readiness?.platforms?.connectedLabels?.length) {
      return readiness.platforms.connectedLabels.join(", ");
    }
    if (readiness?.channelConnected) {
      return "Bağlı";
    }
    return "Bekliyor";
  }, [readiness]);
  const visibleDrafts = (learningQueue?.items || []).slice(0, 2);
  const keyStats: Array<{ label: string; value: string; tone: "success" | "warning" | "info" | "neutral" }> = [
    { label: "Runtime", value: runtimeReady ? "Canlı" : "Bekliyor", tone: runtimeReady ? "success" : "warning" as const },
    {
      label: "Model",
      value: readiness?.connectedModel || readiness?.connectedProvider || "Yok",
      tone: readiness?.modelLaneReady ? "success" : "warning" as const,
    },
    {
      label: "Kanallar",
      value: connectedChannelSummary,
      tone: readiness?.channelConnected ? "success" : "neutral" as const,
    },
  ];
  const topCostSource = billing?.topCostSources?.[0];
  const triggeredLimit = billing?.triggeredLimits?.[0];
  const upgradeHint = billing?.upgradeHint || billing?.usageSummary?.upgradeHint;
  const resetLabel = formatBillingResetLabel(billing?.resetAt || billing?.creditBalance?.resetAt || billing?.usageSummary?.period?.resetAt);
  const quickPrompts = [
    "bugünkü işleri özetle",
    "telegram bağlantısını kontrol et",
    "şu an sistemde ne çalışıyor",
  ];

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
    await triggerAutopilotTick("desktop_checkin");
    void queryClient.invalidateQueries({ queryKey: ["home-snapshot"] });
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
    <div className="space-y-4">
      <Surface tone="hero" className="px-6 py-6 lg:px-7 lg:py-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-[720px]">
            <div className="flex items-center gap-2.5">
              <Sparkles className="h-4 w-4 text-[var(--accent-primary)]" />
              <span className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Operator runtime</span>
            </div>
            <h1 className="mt-3 font-display text-[28px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
              Tek komutla başla, gerisini Elyan toparlasın.
            </h1>
            <p className="mt-3 max-w-[620px] text-[13px] leading-6 text-[var(--text-secondary)]">
              Sade akış: komutu ver, workstream aç, gerekiyorsa Telegram rutinine dönüştür.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge tone={readinessTone}>{readinessLabel}</StatusBadge>
            {resumeCandidate ? <StatusBadge tone="info">aktif thread var</StatusBadge> : null}
          </div>
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

        {readiness?.status === "needs_attention" && readiness?.blockingIssue ? (
          <p className="mt-3 text-[12px] leading-5 text-[var(--state-warning)]">{readiness.blockingIssue}</p>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-2">
          {quickPrompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => setCommand(prompt)}
              className="rounded-full border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-3 py-1.5 text-[12px] text-[var(--text-secondary)] transition hover:border-[var(--glass-border-strong)] hover:text-[var(--text-primary)]"
            >
              {prompt}
            </button>
          ))}
        </div>

        {billing ? (
          <div className="mt-4 rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Billing</div>
                <h2 className="mt-2 text-[17px] font-medium text-[var(--text-primary)]">Plan ve kullanım</h2>
              </div>
              <StatusBadge tone={billing.plan.status === "active" ? "success" : "neutral"}>{billing.plan.label}</StatusBadge>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <ReadinessItem
                label="Credits"
                value={(billing.creditBalance?.total || 0).toLocaleString("tr-TR")}
                meta={`included ${(billing.creditBalance?.included || 0).toLocaleString("tr-TR")} · purchased ${(billing.creditBalance?.purchased || 0).toLocaleString("tr-TR")}`}
              />
              <ReadinessItem
                label="Reset"
                value={resetLabel}
                meta={billing.creditBalance?.rolloverPolicy === "none" ? "No rollover" : "Carry policy"}
              />
              <ReadinessItem
                label="Top source"
                value={topCostSource?.source || "Yok"}
                meta={topCostSource ? `${topCostSource.credits.toLocaleString("tr-TR")} kredi` : "Henüz harcama yok"}
              />
              <ReadinessItem
                label="Limits"
                value={triggeredLimit ? triggeredLimit.status : "clear"}
                meta={triggeredLimit ? triggeredLimit.reason || "limit triggered" : "Hard cap yok"}
              />
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[12px] text-[var(--text-secondary)]">
              <span>
                Recent usage: {(billing.recentUsageSummary?.requests || billing.usageSummary?.requests || 0).toLocaleString("tr-TR")} request · {(billing.recentUsageSummary?.estimatedCredits || billing.usageSummary?.estimatedCredits || 0).toLocaleString("tr-TR")} credit
              </span>
              {upgradeHint ? <span>{upgradeHint.message}</span> : null}
            </div>
          </div>
        ) : null}

        {launchError ? <p className="mt-3 text-[12px] text-[var(--state-warning)]">{launchError}</p> : null}
        {!launchError && !runtimeReady ? <p className="mt-3 text-[12px] text-[var(--text-tertiary)]">{runtimeGateReason}</p> : null}
      </Surface>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
            {keyStats.map((item) => (
              <StatusTile key={item.label} label={item.label} value={item.value} tone={item.tone} />
            ))}
          </div>

          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Hızlı durum</div>
                <h2 className="mt-2 text-[17px] font-medium text-[var(--text-primary)]">Bağlantılar ve kritik adımlar</h2>
              </div>
              <Button variant="ghost" className="h-8 px-3 text-[11px]" onClick={() => void checkIn()}>
                Yenile
              </Button>
            </div>
            <div className="mt-4 space-y-3">
              <ReadinessItem
                label="Provider"
                value={readiness?.connectedProvider || "Local"}
                meta={readiness?.connectedModel || "Model seçilmedi"}
              />
              <ReadinessItem
                label="Channel"
                value={connectedChannelSummary}
                meta={readiness?.whatsappMode === "unavailable" ? "Bridge kapalı" : `WhatsApp ${readiness?.whatsappMode || "bekliyor"}`}
              />
              <ReadinessItem
                label="Automation"
                value={readiness?.hasRoutine ? "Hazır" : "Henüz yok"}
                meta={readiness?.skills?.issues ? `${readiness.skills.issues} dikkat istiyor` : "Runtime stabil"}
              />
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {!readiness?.channelConnected ? (
                <Button variant="secondary" onClick={() => navigate("/integrations")}>
                  Kanalları bağla
                </Button>
              ) : null}
              {readiness?.providerSummary.authRequired || readiness?.providerSummary.degraded ? (
                <Button variant="ghost" onClick={() => navigate("/providers")}>
                  Modelleri gözden geçir
                </Button>
              ) : null}
              {setupChecklist.length ? (
                <Button variant="ghost" onClick={() => navigate("/settings")}>
                  Kurulumu tamamla
                </Button>
              ) : null}
            </div>
          </Surface>

          {resumeCandidate ? (
            <Surface tone="card" className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Son workstream</div>
                  <h2 className="mt-2 text-[16px] font-medium text-[var(--text-primary)]">{resumeCandidate.title || "Son thread"}</h2>
                  <p className="mt-2 line-clamp-3 text-[12px] leading-6 text-[var(--text-secondary)]">
                    {resumeCandidate.lastUserTurn?.content || "Bu thread içinden devam edebilirsin."}
                  </p>
                </div>
                <StatusBadge tone="info">{resumeCandidate.currentMode || "cowork"}</StatusBadge>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSelectedThreadId(resumeCandidate.threadId);
                    if (resumeCandidate.activeRunId) setSelectedRunId(resumeCandidate.activeRunId);
                    navigate("/command-center");
                  }}
                >
                  Devam et
                </Button>
                <Button variant="ghost" onClick={() => navigate("/stack")}>
                  Stack aç
                </Button>
              </div>
            </Surface>
          ) : null}

          {resumeCandidate && automationCandidate ? (
            <Surface tone="card" className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Önerilen rutin</div>
                  <h2 className="mt-2 text-[16px] font-medium text-[var(--text-primary)]">{automationCandidate.task || "Scheduled routine"}</h2>
                  <p className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                    {automationCandidate.cron || resumePreview?.goalGraph?.constraints.scheduleExpression || "schedule not detected"}
                  </p>
                </div>
                {resumePreview?.goalGraph?.primaryDeliveryDomain ? (
                  <StatusBadge tone="info">{resumePreview.goalGraph.primaryDeliveryDomain}</StatusBadge>
                ) : null}
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => void handleCreateAutomation()} disabled={automationBusy || !runtimeReady}>
                  {automationBusy ? "Hazırlanıyor…" : "Routine oluştur"}
                </Button>
                <Button variant="ghost" onClick={() => navigate("/integrations")}>
                  Telegram aç
                </Button>
              </div>
              {automationMessage ? (
                <p className={`mt-3 text-[12px] ${automationMessageTone === "success" ? "text-[var(--state-success)]" : "text-[var(--state-warning)]"}`}>
                  {automationMessage}
                </p>
              ) : null}
            </Surface>
          ) : null}

          {visibleDrafts.length ? (
            <Surface tone="card" className="p-5">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Bekleyen öneriler</div>
                  <h2 className="mt-2 text-[16px] font-medium text-[var(--text-primary)]">{learningQueue?.total || 0} draft</h2>
                </div>
                <StatusBadge tone="warning">review</StatusBadge>
              </div>
              <div className="mt-4 space-y-3">
                {visibleDrafts.map((draft) => (
                  <div key={draft.id} className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium text-[var(--text-primary)]">{draft.title}</div>
                        <div className="mt-1 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">{draft.type}</div>
                      </div>
                      <Button variant="ghost" onClick={() => void handlePromoteDraft(draft)} disabled={draftActionId === draft.id}>
                        {draftActionId === draft.id ? "…" : "Uygula"}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
              {draftActionError ? <p className="mt-3 text-[12px] text-[var(--state-warning)]">{draftActionError}</p> : null}
            </Surface>
          ) : null}

          {backgroundTasks.length ? (
            <Surface tone="card" className="p-5">
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Arka plan</div>
              <div className="mt-4 space-y-2">
                {backgroundTasks.map((task) => (
                  <div key={task.taskId} className="flex items-center justify-between gap-3 rounded-[14px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-3">
                    <span className="truncate text-[13px] text-[var(--text-primary)]">{task.objective || "Görev"}</span>
                    <StatusBadge tone={task.state === "running" ? "success" : "info"}>{task.state}</StatusBadge>
                  </div>
                ))}
              </div>
            </Surface>
          ) : null}
        </div>

        <div className="min-w-0">
          <ChatView className="min-h-[720px]" />
        </div>
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
