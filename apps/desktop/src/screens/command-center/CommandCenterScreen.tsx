import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, ShieldAlert } from "lucide-react";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useCommandCenterSnapshot } from "@/hooks/use-desktop-data";
import { addCoworkTurn, resolveCoworkApproval } from "@/services/api/elyan-service";
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
