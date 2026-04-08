import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Clock3, RefreshCw, Sparkles } from "@/vendor/lucide-react";
import { useNavigate } from "react-router-dom";
import { JarvisPanel } from "@/features/jarvis/JarvisPanel";
import { TaskTreePanel } from "@/features/jarvis/TaskTreePanel";
import { ChatView } from "@/features/jarvis/ChatView";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Surface } from "@/components/primitives/Surface";
import {
  useHomeSnapshot,
  useProviderDescriptors,
} from "@/hooks/use-desktop-data";
import { createCoworkThread, triggerAutopilotTick } from "@/services/api/elyan-service";
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
  const [checkInBusy, setCheckInBusy] = useState(false);
  const { data: providers } = useProviderDescriptors();
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

      {/* ─── Elyan Chat ─── */}
      <ChatView className="min-h-[460px]" />

      {/* ─── Jarvis Panel ─── */}
      <JarvisPanel />

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
