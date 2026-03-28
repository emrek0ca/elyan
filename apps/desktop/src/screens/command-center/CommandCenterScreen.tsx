import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Clock3, ShieldAlert } from "lucide-react";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { OutputStream } from "@/features/run/OutputStream";
import { useCommandCenterSnapshot } from "@/hooks/use-desktop-data";
import { runtimeManager } from "@/runtime/runtime-manager";
import { addCoworkTurn, cancelRun, controlCoworkThread, resolveCoworkApproval } from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import { getRuntimeGateReason, hasRuntimeWriteAccess } from "@/utils/runtime-access";

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
  const [actionMessage, setActionMessage] = useState("");
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
  const latestTimelineEntry = selectedThread?.timeline.at(-1);
  const lastCheckpoint = selectedThread?.lastSuccessfulCheckpoint;
  const riskLabel = selectedThread?.riskLevel || selectedThread?.approvals[0]?.riskLevel || "medium";
  const controlActions = selectedThread?.controlActions || data.controlActions || [];
  const runtimeReady = hasRuntimeWriteAccess(connectionState, sidecarHealth);
  const runtimeGateReason = getRuntimeGateReason(connectionState, sidecarHealth);

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

  async function handleControlAction(actionId: string) {
    if (!selectedThread || !guardRuntimeWrite()) {
      return;
    }
    setActionMessage("");
    if (actionId === "stop" && (selectedThread.activeRunId || selectedThread.activeMissionId)) {
      setTurnBusy(true);
      try {
        if (selectedThread.activeRunId) {
          await cancelRun(selectedThread.activeRunId);
        } else {
          await controlCoworkThread(selectedThread.threadId, "stop");
        }
        await invalidateAll();
      } finally {
        setTurnBusy(false);
      }
      return;
    }
    if (actionId === "resume") {
      setTurnBusy(true);
      try {
        await controlCoworkThread(selectedThread.threadId, "resume");
        await invalidateAll();
      } finally {
        setTurnBusy(false);
      }
      return;
    }
    if (actionId === "retry") {
      await handleFollowUp("Retry from the last successful checkpoint, verify each step, and keep the scope narrow.");
      return;
    }
    if (actionId === "observe_only") {
      await handleFollowUp("Stay in observe-only mode. Show the exact plan before acting.");
      return;
    }
    if (actionId === "draft_first") {
      await handleFollowUp("Draft the plan first, list risks, and wait before making any change.");
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <Surface tone="card" className="p-5">
        <div className="mb-4">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Threads</div>
          <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Workstreams
          </h2>
        </div>
        <div className="space-y-3">
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
              className={`w-full rounded-[18px] border p-4 text-left transition ${
                selectedThread?.threadId === thread.threadId
                  ? "border-[var(--border-focus)] bg-[var(--accent-soft)]"
                  : "border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] hover:bg-[var(--bg-surface)]"
              }`}
            >
              <div className="text-[13px] font-medium text-[var(--text-primary)]">{thread.title}</div>
              <div className="mt-1 line-clamp-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                {thread.lastOperatorTurn?.content || thread.lastUserTurn?.content || thread.status}
              </div>
              <div className="mt-3 flex items-center justify-between gap-3">
                <StatusBadge tone={thread.pendingApprovals > 0 ? "warning" : thread.status === "completed" ? "success" : "info"}>
                  {thread.currentMode}
                </StatusBadge>
                <div className="text-[11px] text-[var(--text-tertiary)]">{thread.updatedAt}</div>
              </div>
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
            <div className="flex flex-wrap gap-2">
              {selectedThread?.currentMode ? <StatusBadge tone="info">{selectedThread.currentMode}</StatusBadge> : null}
              {selectedThread?.status ? (
                <StatusBadge tone={selectedThread.status === "completed" ? "success" : selectedThread.status === "failed" ? "error" : "info"}>
                  {selectedThread.status}
                </StatusBadge>
              ) : null}
              <StatusBadge tone={riskLabel === "high" ? "warning" : riskLabel === "low" ? "success" : "info"}>{`risk ${riskLabel}`}</StatusBadge>
            </div>
          </div>

          {selectedThread ? (
            <div className="mt-5 grid gap-3 md:grid-cols-4">
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Current step</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">
                  {selectedThread.currentStep || latestTimelineEntry?.title || selectedThread.status}
                </div>
              </div>
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Checkpoint</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">{lastCheckpoint?.title || "None"}</div>
              </div>
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Files</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">{selectedThread.filesTouched?.length || 0}</div>
              </div>
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Approvals</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">{selectedThread.approvals.length}</div>
              </div>
            </div>
          ) : null}
        </Surface>

        {selectedThread ? (
          <Surface tone="card" className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Control</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Visible runtime actions
                </h2>
              </div>
              <div className="flex flex-wrap gap-2">
                {controlActions.map((action) => (
                  <Button
                    key={action.id}
                    variant={action.tone === "primary" ? "primary" : action.tone === "danger" ? "ghost" : "secondary"}
                    size="sm"
                    disabled={!action.enabled || turnBusy || (action.id === "stop" && !selectedThread.activeRunId && !selectedThread.activeMissionId)}
                    onClick={() => void handleControlAction(action.id)}
                  >
                    {action.label}
                  </Button>
                ))}
              </div>
            </div>
            <div className="mt-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[13px] leading-6 text-[var(--text-secondary)]">
              {selectedThread.goal || selectedThread.lastUserTurn?.content || "No goal set for this thread yet."}
            </div>
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
                    <Button variant="primary" size="sm" onClick={() => void handleApproval(approval.id, true)} disabled={approvalBusyId === approval.id}>
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

        <OutputStream outputBlocks={data.outputBlocks} />

        {selectedThread?.artifacts.length ? (
          <Surface tone="card" className="p-5">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Artifacts</div>
            <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
              Outputs
            </h2>
            <div className="mt-4 space-y-3">
              {selectedThread.artifacts.map((artifact) => (
                <div key={artifact.artifactId} className="flex flex-wrap items-center justify-between gap-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">{artifact.label}</div>
                    <div className="mt-1 truncate text-[12px] text-[var(--text-secondary)]">{artifact.path}</div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="secondary" size="sm" onClick={() => void runtimeManager.openArtifact(artifact.path)}>
                      Open
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => void runtimeManager.revealInFolder(artifact.path)}>
                      Reveal
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </Surface>
        ) : null}

        {selectedThread ? (
          <div className="grid gap-6 lg:grid-cols-2">
            <Surface tone="card" className="p-5">
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Replay</div>
              <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Checkpoints
              </h2>
              <div className="mt-4 space-y-3">
                {selectedThread.replay?.checkpoints?.length ? (
                  selectedThread.replay.checkpoints.slice(-3).map((checkpoint) => (
                    <div key={checkpoint.checkpointId} className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">{checkpoint.title}</div>
                      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{checkpoint.createdAt}</div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[12px] text-[var(--text-secondary)]">
                    No checkpoint yet.
                  </div>
                )}
              </div>
            </Surface>

            <Surface tone="card" className="p-5">
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Changes</div>
              <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Artifact diff
              </h2>
              <div className="mt-4 space-y-3">
                {selectedThread.artifactDiffs?.length ? (
                  selectedThread.artifactDiffs.slice(-3).map((diff) => (
                    <div key={diff.id} className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">{diff.artifactId || "artifact change"}</div>
                      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                        {diff.beforeHash || "before"} → {diff.afterHash || "after"}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[12px] text-[var(--text-secondary)]">
                    No diff yet.
                  </div>
                )}
              </div>
            </Surface>
          </div>
        ) : null}

        <Surface tone="card" className="p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Follow-up</div>
              <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Continue this thread
              </h2>
            </div>
            {selectedThread?.updatedAt ? (
              <div className="flex items-center gap-2 text-[12px] text-[var(--text-secondary)]">
                <Clock3 className="h-4 w-4" />
                {selectedThread.updatedAt}
              </div>
            ) : null}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => setFollowUp("Stay in observe-only mode and tell me the next safest step.")} disabled={!runtimeReady}>
              Observe only
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setFollowUp("Draft the plan first and wait for approval before acting.")} disabled={!runtimeReady}>
              Draft first
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setFollowUp("Retry from the last successful checkpoint and keep the scope narrow.")} disabled={!runtimeReady}>
              Retry safely
            </Button>
          </div>
          <div className="mt-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
            <textarea
              value={followUp}
              onChange={(event) => setFollowUp(event.target.value)}
              placeholder="Write the next instruction"
              className="min-h-[120px] w-full resize-none bg-transparent text-[14px] leading-7 text-[var(--text-primary)] outline-none"
            />
            <div className="mt-4 flex justify-end">
              <Button variant="primary" onClick={() => void handleFollowUp()} disabled={!selectedThread || turnBusy || !followUp.trim() || !runtimeReady}>
                {turnBusy ? "Sending..." : "Send"}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </div>
          {actionMessage ? <div className="mt-3 text-[12px] text-[var(--state-warning)]">{actionMessage}</div> : null}
          {!actionMessage && !runtimeReady ? <div className="mt-3 text-[12px] text-[var(--text-secondary)]">{runtimeGateReason}</div> : null}
        </Surface>
      </div>
    </div>
  );
}
