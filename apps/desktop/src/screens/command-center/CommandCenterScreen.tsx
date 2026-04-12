import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ShieldAlert } from "@/vendor/lucide-react";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useCommandCenterSnapshot } from "@/hooks/use-desktop-data";
import { addCoworkTurn, createRoutineFromText, resolveCoworkApproval } from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import { getRuntimeGateReason, hasRuntimeWriteAccess } from "@/utils/runtime-access";

function orchestrationTone(mode?: string): "success" | "info" | "warning" {
  switch ((mode || "").toLowerCase()) {
    case "multi_agent":
    case "team":
      return "info";
    case "verified":
    case "reviewed":
      return "success";
    default:
      return "warning";
  }
}

function yesNoTone(value: boolean): "success" | "neutral" {
  return value ? "success" : "neutral";
}

function collaborationStatusTone(status?: string): "success" | "info" | "warning" | "neutral" {
  switch ((status || "").toLowerCase()) {
    case "success":
    case "verified":
    case "completed":
      return "success";
    case "failed":
    case "blocked":
      return "warning";
    case "planned":
    case "running":
      return "info";
    default:
      return "neutral";
  }
}

export function CommandCenterScreen() {
  const queryClient = useQueryClient();
  const selectedThreadId = useUiStore((state) => state.selectedThreadId);
  const selectedRunId = useUiStore((state) => state.selectedRunId);
  const setSelectedThreadId = useUiStore((state) => state.setSelectedThreadId);
  const setSelectedRunId = useUiStore((state) => state.setSelectedRunId);
  const { data, isLoading, error, refetch } = useCommandCenterSnapshot(selectedThreadId, selectedRunId);
  const [followUp, setFollowUp] = useState("");
  const [turnBusy, setTurnBusy] = useState(false);
  const [approvalBusyId, setApprovalBusyId] = useState("");
  const [automationBusy, setAutomationBusy] = useState(false);
  const [actionMessage, setActionMessage] = useState("");
  const [actionMessageTone, setActionMessageTone] = useState<"success" | "warning">("warning");
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);

  if (error) {
    return (
      <ErrorState
        title="Command center unavailable"
        description="Seçili workstream yüklenemedi."
        onRetry={() => void refetch()}
      />
    );
  }

  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-[260px_1fr] gap-6">
        <SkeletonBlock className="h-[560px] rounded-[24px]" />
        <SkeletonBlock className="h-[560px] rounded-[24px]" />
      </div>
    );
  }

  const selectedThread = data.selectedThread;
  const runtimeReady = hasRuntimeWriteAccess(connectionState, sidecarHealth);
  const runtimeGateReason = getRuntimeGateReason(connectionState, sidecarHealth);
  const lastCheckpoint = selectedThread?.lastSuccessfulCheckpoint;
  const replay = selectedThread?.replay;
  const verificationCount = replay?.verificationResults?.length ?? 0;
  const recoveryCount = replay?.recoveryActions?.length ?? 0;
  const artifactDiffCount = selectedThread?.artifactDiffs?.length ?? 0;
  const timelinePreview = selectedThread?.timeline?.slice(-3) ?? [];
  const collaborationTrace = selectedThread?.collaborationTrace ?? [];
  const orchestration = data.orchestration;
  const presence = data.presence;
  const operatorMessage = presence?.liveNote
    || (orchestration
      ? orchestration.autonomy.shouldAsk
        ? `Önce güvenli yolu kuracağım, sonra gerekli yerde senden onay isteyeceğim. İlk rota: ${orchestration.preview || orchestration.primaryAction || "analyze"}.`
        : `Bunu adım adım ben yürüteceğim. İlk rota: ${orchestration.preview || orchestration.primaryAction || "analyze"}.`
      : selectedThread?.lastOperatorTurn?.content || "Hazırım. İstersen sıradaki adımı netleştireyim.");
  const suggestedFollowUps = presence?.quickReplies?.length
    ? presence.quickReplies
    : orchestration
      ? [
          ...orchestration.taskPlan.steps.slice(0, 3).map((step) => `Şimdi şu adımı uygula: ${step.name}`),
          ...(orchestration.integration.connectorName ? [`${orchestration.integration.connectorName} bağlantısını kullanarak ilerle`] : []),
        ].slice(0, 4)
      : ["Bunu devam ettir", "Bir sonraki adımı öner", "Kısa durum özeti ver"];

  async function invalidateAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["cowork-home"] }),
      queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
      queryClient.invalidateQueries({ queryKey: ["command-center"] }),
      queryClient.invalidateQueries({ queryKey: ["logs"] }),
    ]);
  }

  function guardRuntimeWrite() {
    if (runtimeReady) {
      return true;
    }
    setActionMessageTone("warning");
    setActionMessage(runtimeGateReason);
    return false;
  }

  async function handleFollowUp(promptOverride?: string) {
    const prompt = promptOverride ?? followUp;
    if (!selectedThread || !prompt.trim() || !guardRuntimeWrite()) {
      return;
    }
    setActionMessage("");
    setTurnBusy(true);
    try {
      const updated = await addCoworkTurn(selectedThread.threadId, {
        prompt: prompt.trim(),
        current_mode: selectedThread.currentMode,
      });
      setSelectedThreadId(updated.threadId);
      if (updated.activeRunId) {
        setSelectedRunId(updated.activeRunId);
      }
      setFollowUp("");
      await invalidateAll();
    } finally {
      setTurnBusy(false);
    }
  }

  async function handleApproval(approvalId: string, approved: boolean) {
    if (!guardRuntimeWrite()) {
      return;
    }
    setApprovalBusyId(approvalId);
    setActionMessage("");
    try {
      const updated = await resolveCoworkApproval(approvalId, { approved });
      if (updated?.threadId) {
        setSelectedThreadId(updated.threadId);
        if (updated.activeRunId) {
          setSelectedRunId(updated.activeRunId);
        }
      }
      await invalidateAll();
    } finally {
      setApprovalBusyId("");
    }
  }

  async function handleCreateAutomation() {
    if (!selectedThread || !orchestration?.goalGraph?.automationCandidate || !guardRuntimeWrite()) {
      return;
    }
    setAutomationBusy(true);
    setActionMessage("");
    try {
      const automation = orchestration.goalGraph.automationCandidate;
      const result = await createRoutineFromText({
        text: `${automation.task} ${automation.cron ? `(${automation.cron})` : ""}`.trim(),
        name: automation.task,
        expression: automation.cron || orchestration.goalGraph.constraints.scheduleExpression || "",
        reportChannel: "telegram",
        enabled: true,
      });
      if (!result.ok) {
        setActionMessageTone("warning");
        setActionMessage(result.message || "Automation oluşturulamadı.");
        return;
      }
      setActionMessageTone("success");
      setActionMessage(`Automation hazır: ${result.name || result.routineId}`);
      await invalidateAll();
    } finally {
      setAutomationBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
      <Surface tone="card" className="p-4">
        <div className="mb-4">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Threads</div>
          <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Work
          </h2>
        </div>
        <div className="space-y-2">
          {(data.threads || []).map((thread) => (
            <button
              key={thread.threadId}
              type="button"
              onClick={() => {
                setSelectedThreadId(thread.threadId);
                if (thread.activeRunId) {
                  setSelectedRunId(thread.activeRunId);
                }
              }}
              className={`w-full rounded-[14px] border px-3 py-3 text-left transition ${
                selectedThread?.threadId === thread.threadId
                  ? "border-[var(--border-focus)] bg-[var(--accent-soft)]"
                  : "border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] hover:bg-[var(--bg-surface)]"
              }`}
            >
              <div className="text-[13px] font-medium text-[var(--text-primary)]">{thread.title}</div>
              <div className="mt-1 text-[11px] text-[var(--text-tertiary)]">{thread.updatedAt}</div>
            </button>
          ))}
        </div>
      </Surface>

      <div className="space-y-6">
        <Surface tone="hero" className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Command center</div>
              <h1 className="mt-2 font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                {selectedThread?.title || "No thread selected"}
              </h1>
            </div>
            <div className="flex flex-wrap gap-2" />
          </div>
        </Surface>
        {selectedThread ? (
          <Surface tone="card" className="p-5">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Goal</div>
            <div className="mt-3 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[13px] leading-6 text-[var(--text-secondary)]">
              {selectedThread.goal || selectedThread.lastUserTurn?.content || "No goal set for this thread yet."}
            </div>
          </Surface>
        ) : null}

        {selectedThread ? (
          <Surface tone="card" className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Operator voice</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  {presence?.headline || "Elyan bunu sana böyle söyler"}
                </h2>
              </div>
              {orchestration ? (
                <StatusBadge tone={orchestration.autonomy.shouldAsk ? "warning" : "success"}>
                  {orchestration.autonomy.shouldAsk ? "approval-aware" : "self-driven"}
                </StatusBadge>
              ) : null}
            </div>
            <div className="mt-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[14px] leading-7 text-[var(--text-primary)]">
              {operatorMessage}
            </div>
            {presence?.nextMove ? (
              <div className="mt-3 text-[12px] text-[var(--text-secondary)]">
                Sonraki doğal hareket: {presence.nextMove}
              </div>
            ) : null}
            {presence?.operatorNotes?.length ? (
              <div className="mt-4 grid gap-2">
                {presence.operatorNotes.slice(0, 3).map((note) => (
                  <div
                    key={note.id}
                    className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-3"
                  >
                    <div className="text-[12px] font-medium text-[var(--text-primary)]">{note.title}</div>
                    <div className="mt-1 text-[12px] leading-6 text-[var(--text-secondary)]">{note.body}</div>
                  </div>
                ))}
              </div>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              {suggestedFollowUps.map((suggestion) => (
                <Button
                  key={suggestion}
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleFollowUp(suggestion)}
                  disabled={!selectedThread || turnBusy || !runtimeReady}
                >
                  {suggestion}
                </Button>
              ))}
            </div>
          </Surface>
        ) : null}

        {selectedThread && orchestration ? (
          <Surface tone="card" className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Operator preview</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  {orchestration.preview || orchestration.objective || "Execution preview"}
                </h2>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusBadge tone="info">{orchestration.domain || "general"}</StatusBadge>
                <StatusBadge tone={orchestrationTone(orchestration.orchestrationMode)}>
                  {orchestration.orchestrationMode.replaceAll("_", " ")}
                </StatusBadge>
                <StatusBadge tone={yesNoTone(orchestration.fastPath)}>
                  {orchestration.fastPath ? "fast path" : "full path"}
                </StatusBadge>
                <StatusBadge tone={yesNoTone(orchestration.realTimeRequired)}>
                  {orchestration.realTimeRequired ? "real time" : "deferred ok"}
                </StatusBadge>
              </div>
            </div>

            <div className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
              <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[12px] font-medium text-[var(--text-primary)]">Execution route</div>
                <div className="mt-3 grid gap-3 text-[12px] text-[var(--text-secondary)] md:grid-cols-2">
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Primary action</div>
                    <div className="mt-1 text-[13px] text-[var(--text-primary)]">{orchestration.primaryAction || "analyze"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Request class</div>
                    <div className="mt-1 text-[13px] text-[var(--text-primary)]">{orchestration.requestClass || "general"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Model lane</div>
                    <div className="mt-1 text-[13px] text-[var(--text-primary)]">
                      {orchestration.modelSelection.provider || "local"} / {orchestration.modelSelection.model || "default"}
                    </div>
                    <div className="mt-1 text-[11px] text-[var(--text-tertiary)]">{orchestration.modelSelection.role || "operator"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Connector</div>
                    <div className="mt-1 text-[13px] text-[var(--text-primary)]">
                      {orchestration.integration.connectorName || orchestration.integration.provider || "none"}
                    </div>
                    <div className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                      {orchestration.integration.integrationType || "local"} · {orchestration.integration.authStrategy || "session"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Autonomy</div>
                    <div className="mt-1 text-[13px] text-[var(--text-primary)]">{orchestration.autonomy.mode || "assisted"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Fallback</div>
                    <div className="mt-1 text-[13px] text-[var(--text-primary)]">
                      {orchestration.modelSelection.fallback ? "provider fallback ready" : orchestration.integration.fallbackPolicy || "none"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">LLM collaboration</div>
                    <div className="mt-1 text-[13px] text-[var(--text-primary)]">
                      {orchestration.collaboration.enabled
                        ? `${orchestration.collaboration.maxModels} models · ${orchestration.collaboration.strategy || "parallel_synthesis"}`
                        : "single model"}
                    </div>
                    <div className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                      {orchestration.collaboration.synthesisRole || orchestration.modelSelection.role || "operator"}
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[12px] font-medium text-[var(--text-primary)]">Safety</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <StatusBadge tone={yesNoTone(orchestration.autonomy.shouldAsk)}>
                    {orchestration.autonomy.shouldAsk ? "approval aware" : "no approval expected"}
                  </StatusBadge>
                  <StatusBadge tone={yesNoTone(orchestration.autonomy.shouldResume)}>
                    {orchestration.autonomy.shouldResume ? "resume capable" : "single pass"}
                  </StatusBadge>
                </div>
                {orchestration.taskPlan.constraints.length ? (
                  <div className="mt-4">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Constraints</div>
                    <div className="mt-2 space-y-2 text-[12px] text-[var(--text-secondary)]">
                      {orchestration.taskPlan.constraints.slice(0, 3).map((item) => (
                        <div key={item} className="rounded-[14px] border border-[var(--border-subtle)] px-3 py-2">
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            {orchestration.taskPlan.steps.length ? (
              <div className="mt-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="text-[12px] font-medium text-[var(--text-primary)]">
                    Plan steps
                  </div>
                  <div className="text-[11px] text-[var(--text-tertiary)]">
                    {orchestration.taskPlan.name || orchestration.taskPlan.goal || "planned execution"}
                  </div>
                </div>
                <div className="mt-3 space-y-2">
                  {orchestration.taskPlan.steps.map((step, index) => (
                    <div
                      key={`${step.name}-${index}`}
                      className="flex items-start justify-between gap-4 rounded-[16px] border border-[var(--border-subtle)] px-3 py-3"
                    >
                      <div className="min-w-0">
                        <div className="text-[13px] font-medium text-[var(--text-primary)]">
                          {index + 1}. {step.name || "step"}
                        </div>
                        <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                          {step.kind || "task"}{step.tool ? ` · ${step.tool}` : ""}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {step.tool ? <StatusBadge tone="neutral">{step.tool}</StatusBadge> : null}
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => void handleFollowUp(`Şimdi şu adımı uygula: ${step.name}`)}
                          disabled={turnBusy || !runtimeReady}
                        >
                          Run
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {orchestration.goalGraph ? (
              <div className="mt-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="text-[12px] font-medium text-[var(--text-primary)]">Goal analysis</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                      {orchestration.goalGraph.stageCount} stage · {orchestration.goalGraph.primaryDeliveryDomain || "general"} · complexity {orchestration.goalGraph.complexityScore}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {orchestration.goalGraph.workflowChain.slice(0, 4).map((item) => (
                      <StatusBadge key={item} tone="neutral">{item}</StatusBadge>
                    ))}
                    {orchestration.goalGraph.constraints.requiresEvidence ? <StatusBadge tone="warning">evidence required</StatusBadge> : null}
                    {orchestration.goalGraph.constraints.autonomyPreference ? (
                      <StatusBadge tone="info">{orchestration.goalGraph.constraints.autonomyPreference}</StatusBadge>
                    ) : null}
                  </div>
                </div>

                {orchestration.goalGraph.automationCandidate ? (
                  <div className="mt-4 rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-4">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Automation candidate</div>
                    <div className="mt-2 text-[13px] font-medium text-[var(--text-primary)]">
                      {orchestration.goalGraph.automationCandidate.task || "Scheduled automation"}
                    </div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                      {orchestration.goalGraph.automationCandidate.cron || orchestration.goalGraph.constraints.scheduleExpression || "schedule not detected"}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => void handleCreateAutomation()}
                        disabled={turnBusy || automationBusy || !runtimeReady}
                      >
                        {automationBusy ? "Scheduling…" : "Schedule this"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void handleFollowUp(`Bu hedef için cron ifadesini ve rutin planını netleştir: ${orchestration.goalGraph?.automationCandidate?.task || selectedThread.goal}`)}
                        disabled={turnBusy || !runtimeReady}
                      >
                        Refine automation
                      </Button>
                    </div>
                  </div>
                ) : null}

                {orchestration.goalGraph.nodes.length ? (
                  <div className="mt-4 space-y-2">
                    {orchestration.goalGraph.nodes.slice(0, 4).map((node, index) => (
                      <div key={`${node.id}-${index}`} className="rounded-[14px] border border-[var(--border-subtle)] px-3 py-3">
                        <div className="flex items-center justify-between gap-3">
                          <div className="text-[13px] font-medium text-[var(--text-primary)]">
                            {index + 1}. {node.text}
                          </div>
                          <StatusBadge tone="neutral">{node.domain || "general"}</StatusBadge>
                        </div>
                        <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{node.objective}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {orchestration.collaboration.enabled && orchestration.collaboration.lenses.length ? (
              <div className="mt-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-center justify-between gap-4">
                  <div className="text-[12px] font-medium text-[var(--text-primary)]">Model collaboration</div>
                  <div className="text-[11px] text-[var(--text-tertiary)]">
                    {orchestration.collaboration.executionStyle.replaceAll("_", " ")}
                  </div>
                </div>
                <div className="mt-3 grid gap-2">
                  {orchestration.collaboration.lenses.map((lens) => (
                    <div key={lens.name} className="rounded-[14px] border border-[var(--border-subtle)] px-3 py-3">
                      <div className="text-[13px] font-medium capitalize text-[var(--text-primary)]">{lens.name}</div>
                      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{lens.instruction}</div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </Surface>
        ) : null}

        {selectedThread ? (
          <Surface tone="card" className="p-5">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Replay</div>
            <div className="mt-3 flex flex-wrap items-center gap-3 text-[13px] text-[var(--text-secondary)]">
              <span className="rounded-[999px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-3 py-1">
                {lastCheckpoint?.title || "No checkpoint"}
              </span>
              <span>V {verificationCount}</span>
              <span>R {recoveryCount}</span>
              <span>D {artifactDiffCount}</span>
              {selectedThread.laneSummary?.collaborationStrategy ? <span>M {selectedThread.laneSummary.collaborationStrategy}</span> : null}
            </div>
            {collaborationTrace.length ? (
              <div className="mt-4 space-y-2">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Execution trace</div>
                {collaborationTrace.slice(0, 4).map((entry) => (
                  <div
                    key={entry.id}
                    className="flex items-center justify-between gap-3 rounded-[14px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-3 py-3"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-[13px] font-medium capitalize text-[var(--text-primary)]">
                        {entry.lens} · {[entry.provider, entry.model].filter(Boolean).join(" / ") || "model"}
                      </div>
                      <div className="mt-1 text-[11px] text-[var(--text-tertiary)]">
                        {entry.strategy || selectedThread.laneSummary?.collaborationStrategy || "adaptive"}
                      </div>
                    </div>
                    <StatusBadge tone={collaborationStatusTone(entry.status)}>{entry.status}</StatusBadge>
                  </div>
                ))}
              </div>
            ) : null}
            {timelinePreview.length ? (
              <div className="mt-3 space-y-1">
                {timelinePreview.map((item) => (
                  <div key={item.id} className="flex items-center justify-between gap-3 text-[12px] text-[var(--text-secondary)]">
                    <span className="truncate">
                      {item.metadata?.timeline_kind === "model_collaboration"
                        ? `${String(item.metadata?.lens || "model")} · ${String(item.metadata?.provider || "")}/${String(item.metadata?.model || "")}`
                        : item.title}
                    </span>
                    <span className="text-[var(--text-tertiary)]">{item.status}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </Surface>
        ) : null}

        {selectedThread?.approvals.length ? (
          <Surface tone="card" className="p-5">
            <div className="flex items-center gap-3">
              <ShieldAlert className="h-4 w-4 text-[var(--state-warning)]" />
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">Pending approvals</div>
                <div className="text-[11px] text-[var(--text-tertiary)]">Nothing runs hidden</div>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {selectedThread.approvals.map((approval) => (
                <div key={approval.id} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">{approval.title}</div>
                      <div className="mt-1 text-[12px] leading-6 text-[var(--text-secondary)]">{approval.summary}</div>
                    </div>
                    <StatusBadge tone={approval.riskLevel === "high" ? "warning" : "info"}>{approval.riskLevel}</StatusBadge>
                  </div>
                  <div className="mt-4 flex gap-2">
                    <Button variant="secondary" size="sm" onClick={() => void handleApproval(approval.id, true)} disabled={approvalBusyId === approval.id}>
                      Approve
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => void handleApproval(approval.id, false)} disabled={approvalBusyId === approval.id}>
                      Deny
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Surface>
        ) : null}

        <Surface tone="card" className="p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Follow-up</div>
              <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Continue</h2>
            </div>
            {selectedThread?.updatedAt ? <div className="text-[12px] text-[var(--text-secondary)]">{selectedThread.updatedAt}</div> : null}
          </div>
          <div className="mt-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
            <textarea
              value={followUp}
              onChange={(event) => setFollowUp(event.target.value)}
              placeholder={presence?.nextMove || "Write the next instruction"}
              className="min-h-[120px] w-full resize-none bg-transparent text-[14px] leading-7 text-[var(--text-primary)] outline-none"
            />
            <div className="mt-4 flex justify-end">
              <Button variant="primary" onClick={() => void handleFollowUp()} disabled={!selectedThread || turnBusy || !followUp.trim() || !runtimeReady}>
                {turnBusy ? "Sending..." : "Send"}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </div>
          {actionMessage ? (
            <div className={`mt-3 text-[12px] ${actionMessageTone === "success" ? "text-[var(--state-success)]" : "text-[var(--state-warning)]"}`}>
              {actionMessage}
            </div>
          ) : null}
          {!actionMessage && !runtimeReady ? <div className="mt-3 text-[12px] text-[var(--text-secondary)]">{runtimeGateReason}</div> : null}
        </Surface>
      </div>
    </div>
  );
}
