import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Cable, Clock3, Command, FileStack, Globe, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { RobotHero } from "@/features/robot/RobotHero";
import { WelcomeOverlay } from "@/features/welcome/WelcomeOverlay";
import { useHomeSnapshot } from "@/hooks/use-desktop-data";
import { createCoworkThread } from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import {
  inferReviewStrictness,
  inferRoutingProfile,
  mergeWorkflowPreferences,
  outputModeLabel,
  resolveProjectTemplate,
} from "@/utils/workflow-preferences";

const WELCOME_SESSION_KEY = "elyan-welcome-shown";

export function HomeScreen() {
  const { data, isLoading, error, refetch } = useHomeSnapshot();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [command, setCommand] = useState("");
  const [launchingFlow, setLaunchingFlow] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState("");
  const [showWelcome, setShowWelcome] = useState(false);
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);
  const setSelectedThreadId = useUiStore((state) => state.setSelectedThreadId);
  const setSelectedRunId = useUiStore((state) => state.setSelectedRunId);
  const workflowPreferences = useUiStore((state) => state.workflowPreferences);
  const projectTemplates = useUiStore((state) => state.projectTemplates);
  const activeProjectTemplateId = useUiStore((state) => state.activeProjectTemplateId);
  const reduceMotion = useUiStore((state) => state.reduceMotion);

  useEffect(() => {
    if (window.sessionStorage.getItem(WELCOME_SESSION_KEY) === "1") {
      return;
    }
    setShowWelcome(true);
  }, []);

  const closeWelcome = () => {
    window.sessionStorage.setItem(WELCOME_SESSION_KEY, "1");
    setShowWelcome(false);
  };

  if (error) {
    return (
      <ErrorState
        title="Runtime snapshot unavailable"
        description="Desktop görünümü runtime özetini alamadı."
        onRetry={() => void refetch()}
      />
    );
  }

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <SkeletonBlock className="h-[300px] w-full rounded-[32px]" />
        <div className="grid grid-cols-2 gap-4">
          <SkeletonBlock className="h-[240px]" />
          <SkeletonBlock className="h-[240px]" />
        </div>
      </div>
    );
  }

  const runtimeTone =
    connectionState === "connected"
      ? "success"
      : connectionState === "booting" || connectionState === "reconnecting"
        ? "warning"
        : "error";

  const activeProjectTemplate = resolveProjectTemplate(projectTemplates, activeProjectTemplateId);
  const effectivePreferences = mergeWorkflowPreferences(workflowPreferences, activeProjectTemplate.preferences);
  const recentThreads = data.recentThreads?.slice(0, 4) || [];
  const resumeCandidate = data.lastThread || data.recentThreads?.[0];
  const latestRun = data.recentRuns?.[0];
  const approvalCount = useMemo(
    () => Number(data.trustStrip.find((item) => item.id === "approvals")?.value || 0),
    [data.trustStrip],
  );

  const inferTaskType = (value: string): "document" | "presentation" | "website" => {
    const text = value.toLowerCase();
    if (/(slide|deck|presentation|sunum|ppt)/.test(text)) {
      return "presentation";
    }
    if (/(site|website|landing|web|react|vite)/.test(text)) {
      return "website";
    }
    return "document";
  };

  const launchWorkflow = async (taskType: "document" | "presentation" | "website") => {
    const fallbackBrief =
      taskType === "presentation"
        ? "Prepare a concise presentation with a clear narrative and export-ready slide structure."
        : taskType === "website"
          ? "Create a premium React website scaffold with clear information architecture and implementation notes."
          : "Create a clear, professional document with structure, review, and export-ready output.";

    setLaunchError("");
    setLaunchingFlow(taskType);
    try {
      const routingProfile = inferRoutingProfile(taskType, effectivePreferences, activeProjectTemplate, useUiStore.getState().autoRouting);
      const reviewStrictness = inferReviewStrictness(taskType, effectivePreferences, activeProjectTemplate);
      const thread = await createCoworkThread({
        prompt: command.trim() || fallbackBrief,
        current_mode: taskType,
        session_id: activeProjectTemplate.sessionId,
        project_template_id: activeProjectTemplate.id,
        project_name: activeProjectTemplate.name,
        routing_profile: routingProfile,
        review_strictness: reviewStrictness,
      });
      setSelectedThreadId(thread.threadId);
      if (thread.activeRunId) {
        setSelectedRunId(thread.activeRunId);
      }
      setCommand("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["cowork-home"] }),
        queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
        queryClient.invalidateQueries({ queryKey: ["command-center"] }),
        queryClient.invalidateQueries({ queryKey: ["logs"] }),
      ]);
      navigate("/command-center");
    } catch (launchWorkflowError) {
      setLaunchError(launchWorkflowError instanceof Error ? launchWorkflowError.message : "Workflow start failed");
    } finally {
      setLaunchingFlow(null);
    }
  };

  const quickStarts = [
    { id: "document" as const, title: "Document", detail: outputModeLabel("document", effectivePreferences), icon: FileStack },
    { id: "presentation" as const, title: "Presentation", detail: outputModeLabel("presentation", effectivePreferences), icon: Sparkles },
    { id: "website" as const, title: "Website", detail: `${effectivePreferences.websiteStack} scaffold`, icon: Globe },
  ];

  return (
    <>
      <WelcomeOverlay open={showWelcome} onClose={closeWelcome} reduceMotion={reduceMotion} />

      <div className="space-y-6">
        <Surface tone="hero" className="overflow-hidden px-8 py-8">
          <div className="grid items-center gap-8 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="space-y-5">
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge tone={runtimeTone}>
                  {connectionState === "connected" ? "runtime ready" : connectionState.replace(/_/g, " ")}
                </StatusBadge>
                <StatusBadge tone="info">{data.workspace.name}</StatusBadge>
                {approvalCount > 0 ? <StatusBadge tone="warning">{`${approvalCount} approval`}</StatusBadge> : null}
              </div>

              <div className="space-y-3">
                <h1 className="max-w-[560px] font-display text-[42px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
                  Start a task. Continue a thread. Keep control.
                </h1>
                <p className="max-w-[520px] text-[15px] leading-7 text-[var(--text-secondary)]">
                  Elyan görevleri tek bir workstream içinde planlar, yürütür ve görünür tutar.
                </p>
              </div>

              <div className="space-y-3">
                <SearchField
                  value={command}
                  onChange={(event) => setCommand(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void launchWorkflow(inferTaskType(command));
                    }
                  }}
                  placeholder="Ne yapmamı istiyorsun?"
                  className="h-14 rounded-[20px] px-5 text-[14px]"
                />
                <div className="flex flex-wrap gap-3">
                  <Button variant="primary" onClick={() => void launchWorkflow(inferTaskType(command))} disabled={launchingFlow !== null}>
                    {launchingFlow ? "Starting..." : "Start"}
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                  {resumeCandidate ? (
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setSelectedThreadId(resumeCandidate.threadId);
                        if (resumeCandidate.activeRunId) {
                          setSelectedRunId(resumeCandidate.activeRunId);
                        }
                        navigate("/command-center");
                      }}
                    >
                      <Clock3 className="mr-2 h-4 w-4" />
                      Continue
                    </Button>
                  ) : null}
                  <Button variant="ghost" onClick={() => navigate("/integrations")}>
                    <Cable className="mr-2 h-4 w-4" />
                    Telegram & apps
                  </Button>
                </div>
                {launchError ? <div className="text-[12px] text-[var(--state-warning)]">{launchError}</div> : null}
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_90%,transparent)] px-4 py-4">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Runtime</div>
                  <div className="mt-2 text-[15px] font-semibold text-[var(--text-primary)]">
                    {sidecarHealth.managed ? "Managed" : "External"}
                  </div>
                </div>
                <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_90%,transparent)] px-4 py-4">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Last run</div>
                  <div className="mt-2 text-[15px] font-semibold text-[var(--text-primary)]">{latestRun?.title || "No run yet"}</div>
                </div>
                <button
                  type="button"
                  onClick={() => navigate("/integrations")}
                  className="rounded-[18px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_90%,transparent)] px-4 py-4 text-left transition hover:bg-[var(--bg-surface)]"
                >
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Telegram</div>
                  <div className="mt-2 text-[15px] font-semibold text-[var(--text-primary)]">Open setup</div>
                </button>
              </div>
            </div>

            <RobotHero compact title="Elyan" subtitle="Clean operator shell" />
          </div>
        </Surface>

        <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
          <Surface tone="card" className="p-6">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Quick start</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Choose one lane
                </h2>
              </div>
              <Button variant="ghost" onClick={() => navigate("/command-center")}>
                <Command className="mr-2 h-4 w-4" />
                Command center
              </Button>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              {quickStarts.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => void launchWorkflow(item.id)}
                    className="rounded-[20px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-5 text-left transition hover:border-[color-mix(in_srgb,var(--accent-primary)_24%,var(--border-subtle))] hover:bg-[var(--bg-surface)]"
                  >
                    <div className="flex h-10 w-10 items-center justify-center rounded-[14px] bg-[var(--accent-soft)] text-[var(--accent-primary)]">
                      <Icon className="h-5 w-5" />
                    </div>
                    <div className="mt-4 text-[16px] font-medium text-[var(--text-primary)]">{item.title}</div>
                    <div className="mt-2 text-[12px] text-[var(--text-secondary)]">{item.detail}</div>
                  </button>
                );
              })}
            </div>
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Recent threads</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Continue where you left off
                </h2>
              </div>
              {resumeCandidate ? <StatusBadge tone="info">{resumeCandidate.updatedAt}</StatusBadge> : null}
            </div>

            <div className="space-y-3">
              {recentThreads.length ? (
                recentThreads.map((thread) => (
                  <button
                    key={thread.threadId}
                    type="button"
                    onClick={() => {
                      setSelectedThreadId(thread.threadId);
                      if (thread.activeRunId) {
                        setSelectedRunId(thread.activeRunId);
                      }
                      navigate("/command-center");
                    }}
                    className="flex w-full items-start justify-between gap-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-left transition hover:bg-[var(--bg-surface)]"
                  >
                    <div className="min-w-0">
                      <div className="truncate text-[14px] font-medium text-[var(--text-primary)]">{thread.title}</div>
                      <div className="mt-1 line-clamp-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                        {thread.lastOperatorTurn?.content || thread.lastUserTurn?.content || thread.status}
                      </div>
                    </div>
                    <StatusBadge tone={thread.pendingApprovals > 0 ? "warning" : thread.status === "completed" ? "success" : "info"}>
                      {thread.currentMode}
                    </StatusBadge>
                  </button>
                ))
              ) : (
                <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-5 text-[13px] text-[var(--text-secondary)]">
                  Henüz başlatılmış bir thread yok.
                </div>
              )}
            </div>
          </Surface>
        </div>
      </div>
    </>
  );
}
