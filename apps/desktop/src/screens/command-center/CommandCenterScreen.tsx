import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FolderSearch, ShieldAlert } from "lucide-react";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { OutputStream } from "@/features/run/OutputStream";
import { useCommandCenterSnapshot } from "@/hooks/use-desktop-data";
import { addCoworkTurn, resolveCoworkApproval } from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";
import { useUiStore } from "@/stores/ui-store";

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

  if (error) {
    return (
      <ErrorState
        title="Command center unavailable"
        description="The shell could not build the current cowork stream from the operator runtime."
        onRetry={() => void refetch()}
      />
    );
  }

  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-[280px_1fr] gap-6">
        <SkeletonBlock className="h-[560px] rounded-[24px]" />
        <SkeletonBlock className="h-[560px] rounded-[24px]" />
      </div>
    );
  }

  const selectedThread = data.selectedThread;
  const latestTimelineEntry = selectedThread?.timeline.at(-1);
  const lastCheckpoint = selectedThread?.timeline
    ?.slice()
    .reverse()
    .find((item) => ["completed", "success", "succeeded", "done"].includes(item.status));
  const touchedFiles = (selectedThread?.artifacts || []).map((artifact) => artifact.path);
  const workersInUse = selectedThread?.laneSummary?.assignedAgents || data.selectedRun?.assignedAgents || [];
  const riskLabel =
    selectedThread?.approvals[0]?.riskLevel ||
    (selectedThread?.currentMode === "cowork" ? "low" : selectedThread?.status === "failed" ? "high" : "medium");

  function setSuggestedFollowUp(template: string) {
    setFollowUp(template);
  }

  async function handleFollowUp() {
    if (!selectedThread || !followUp.trim()) {
      return;
    }
    setTurnBusy(true);
    try {
      const updated = await addCoworkTurn(selectedThread.threadId, {
        prompt: followUp.trim(),
        current_mode: selectedThread.currentMode,
      });
      setSelectedThreadId(updated.threadId);
      if (updated.activeRunId) {
        setSelectedRunId(updated.activeRunId);
      }
      setFollowUp("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["cowork-home"] }),
        queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
        queryClient.invalidateQueries({ queryKey: ["command-center"] }),
        queryClient.invalidateQueries({ queryKey: ["logs"] }),
      ]);
    } finally {
      setTurnBusy(false);
    }
  }

  async function handleApproval(approvalId: string, approved: boolean) {
    setApprovalBusyId(approvalId);
    try {
      const updated = await resolveCoworkApproval(approvalId, { approved });
      if (updated?.threadId) {
        setSelectedThreadId(updated.threadId);
        if (updated.activeRunId) {
          setSelectedRunId(updated.activeRunId);
        }
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["cowork-home"] }),
        queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
        queryClient.invalidateQueries({ queryKey: ["command-center"] }),
        queryClient.invalidateQueries({ queryKey: ["logs"] }),
      ]);
    } finally {
      setApprovalBusyId("");
    }
  }

  return (
    <div className="grid grid-cols-[280px_minmax(0,1fr)_320px] gap-6">
      <Surface tone="card" className="p-5">
        <div className="mb-4">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Cowork threads</div>
          <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Active workstreams
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
              className={`w-full rounded-md border p-4 text-left transition ${
                selectedThread?.threadId === thread.threadId
                  ? "border-[var(--border-focus)] bg-[var(--accent-soft)]"
                  : "border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] hover:bg-[var(--bg-surface)]"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">{thread.title}</div>
                  <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                    {thread.lastOperatorTurn?.content || thread.lastUserTurn?.content || thread.status}
                  </div>
                </div>
                <StatusBadge tone={thread.status === "completed" ? "success" : thread.status === "failed" ? "error" : thread.pendingApprovals > 0 ? "warning" : "info"}>
                  {thread.currentMode}
                </StatusBadge>
              </div>
            </button>
          ))}
        </div>
      </Surface>

      <div className="space-y-6">
        <Surface tone="hero" className="p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Cowork command center</div>
              <h1 className="mt-2 font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                {selectedThread?.title || "No thread selected"}
              </h1>
              <p className="mt-3 max-w-3xl text-[14px] leading-7 text-[var(--text-secondary)]">
                One thread holds messages, execution, review, artifacts, and approvals. Deterministic lanes stay inside the same workstream.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <StatusBadge tone="info">{selectedThread?.currentMode || "cowork"}</StatusBadge>
                <StatusBadge tone={selectedThread?.status === "completed" ? "success" : selectedThread?.status === "failed" ? "error" : selectedThread?.approvals.length ? "warning" : "info"}>
                  {selectedThread?.status || "idle"}
                </StatusBadge>
                {selectedThread?.reviewStatus ? (
                  <StatusBadge tone={selectedThread.reviewStatus === "passed" ? "success" : "warning"}>
                    {`review ${selectedThread.reviewStatus.replace(/_/g, " ")}`}
                  </StatusBadge>
                ) : null}
              </div>
            </div>
            {selectedThread?.approvals[0] ? (
              <div className="rounded-md border border-[color-mix(in_srgb,var(--state-warning)_24%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_12%,transparent)] px-4 py-3">
                <div className="flex items-center gap-2 text-[12px] font-medium text-[var(--state-warning)]">
                  <ShieldAlert className="h-4 w-4" />
                  Approval queued
                </div>
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{selectedThread.approvals[0].title}</div>
              </div>
            ) : null}
          </div>
        </Surface>

        {selectedThread ? (
          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Execution brief</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Clear operator state
                </h2>
              </div>
              <StatusBadge tone={riskLabel === "high" ? "warning" : riskLabel === "low" ? "success" : "info"}>
                {`risk ${riskLabel}`}
              </StatusBadge>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Goal</div>
                <div className="mt-2 text-[13px] leading-6 text-[var(--text-primary)]">
                  {selectedThread.lastUserTurn?.content || "Waiting for the next user turn."}
                </div>
              </div>
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Current step</div>
                <div className="mt-2 text-[13px] font-medium text-[var(--text-primary)]">
                  {latestTimelineEntry?.title || data.selectedRun?.workflowState || selectedThread.status}
                </div>
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                  {latestTimelineEntry?.status || "queued"}
                </div>
              </div>
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Workers in use</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {workersInUse.length ? (
                    workersInUse.map((worker) => (
                      <StatusBadge key={worker} tone="info">
                        {worker}
                      </StatusBadge>
                    ))
                  ) : (
                    <span className="text-[12px] text-[var(--text-secondary)]">No worker assignment recorded yet.</span>
                  )}
                </div>
              </div>
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Last successful checkpoint</div>
                <div className="mt-2 text-[13px] font-medium text-[var(--text-primary)]">
                  {lastCheckpoint?.title || "No verified checkpoint yet"}
                </div>
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                  {lastCheckpoint?.createdAt || "Execution has not crossed a reversible checkpoint."}
                </div>
              </div>
            </div>
            <div className="mt-3 rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Files touched</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {touchedFiles.length ? (
                  touchedFiles.slice(0, 4).map((path) => (
                    <StatusBadge key={path} tone="info">
                      {path.split("/").pop() || path}
                    </StatusBadge>
                  ))
                ) : (
                  <span className="text-[12px] text-[var(--text-secondary)]">No persisted file mutations recorded for this thread.</span>
                )}
              </div>
            </div>
          </Surface>
        ) : null}

        <OutputStream outputBlocks={data.outputBlocks} />

        {selectedThread?.artifacts.length ? (
          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Artifacts</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Produced outputs
                </h2>
              </div>
            </div>
            <div className="mt-4 space-y-3">
              {selectedThread.artifacts.map((artifact) => (
                <div key={artifact.artifactId} className="flex items-center justify-between gap-4 rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div>
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">{artifact.label}</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{artifact.path}</div>
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

        <Surface tone="card" className="p-5">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Follow-up</div>
          <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Continue the same thread
          </h2>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => setSuggestedFollowUp("Before acting, stay in observe-only mode and tell me what you would do.")}>
              Observe only
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setSuggestedFollowUp("Draft the plan first, do not make changes yet, and show me the safest next step.")}>
              Draft first
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setSuggestedFollowUp("Retry from the last successful checkpoint and keep the scope narrow.")}>
              Retry safely
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSuggestedFollowUp("Narrow the scope, explain the exact permissions you need, and wait for approval before acting.")}>
              Narrow scope
            </Button>
          </div>
          <div className="mt-4 rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
            <textarea
              value={followUp}
              onChange={(event) => setFollowUp(event.target.value)}
              placeholder="Ask Elyan to revise, continue, or branch inside this thread"
              className="min-h-[120px] w-full resize-none bg-transparent text-[14px] leading-7 text-[var(--text-primary)] outline-none"
            />
            <div className="mt-3 text-[12px] text-[var(--text-secondary)]">
              These controls do not execute immediately. They shape the next turn so the runtime stays legible, reversible, and scoped.
            </div>
            <div className="mt-4 flex justify-end">
              <Button variant="primary" onClick={() => void handleFollowUp()} disabled={!selectedThread || turnBusy || !followUp.trim()}>
                {turnBusy ? "Submitting…" : "Send follow-up"}
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </div>
          </div>
        </Surface>
      </div>

      <div className="space-y-6">
        <Surface tone="card" className="p-5">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Approvals</div>
          <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            In-pane queue
          </h2>
          <div className="mt-4 space-y-3">
            {(selectedThread?.approvals || []).length ? (
              selectedThread?.approvals.map((approval) => (
                <div key={approval.id} className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
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
              ))
            ) : (
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[12px] text-[var(--text-secondary)]">
                No pending approvals for the selected thread.
              </div>
            )}
          </div>
        </Surface>

        <Surface tone="card" className="p-5">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Security inspection</div>
          <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Runtime trust boundaries
          </h2>
          <div className="mt-4 space-y-3 text-[13px] text-[var(--text-secondary)]">
            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="text-[12px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Cloud path</div>
              <div className="mt-2 text-[13px] font-medium text-[var(--text-primary)]">
                {data.security.allowCloudFallback ? "Fallback allowed with policy" : "Local-only enforced"}
              </div>
              <div className="mt-1 text-[12px] leading-6 text-[var(--text-secondary)]">
                {data.security.cloudPromptRedaction ? "Prompt redaction stays active before cloud escalation." : "Prompt redaction is disabled."}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Sessions</div>
                <div className="mt-2 text-[20px] font-semibold text-[var(--text-primary)]">{data.security.activeSessions}</div>
              </div>
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Approvals</div>
                <div className="mt-2 text-[20px] font-semibold text-[var(--text-primary)]">{data.security.pendingApprovals}</div>
              </div>
            </div>
          </div>
        </Surface>

        {selectedThread?.laneSummary ? (
          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Lane summary</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Current execution contract
                </h2>
              </div>
              {selectedThread.activeRunId ? (
                <Button variant="ghost" size="sm" onClick={() => setSelectedRunId(selectedThread.activeRunId || "")}>
                  <FolderSearch className="mr-2 h-4 w-4" />
                  Bind run
                </Button>
              ) : null}
            </div>
            <div className="mt-4 space-y-3">
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[12px] text-[var(--text-secondary)]">
                {selectedThread.laneSummary.runState || selectedThread.laneSummary.missionState || selectedThread.status}
              </div>
              {selectedThread.laneSummary.assignedAgents?.length ? (
                <div className="flex flex-wrap gap-2">
                  {selectedThread.laneSummary.assignedAgents.map((agent) => (
                    <StatusBadge key={agent} tone="info">
                      {agent}
                    </StatusBadge>
                  ))}
                </div>
              ) : null}
            </div>
          </Surface>
        ) : null}
      </div>
    </div>
  );
}
