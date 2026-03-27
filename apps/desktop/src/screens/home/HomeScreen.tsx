import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot, Cable, Clock3, Command, FileStack, Globe, ShieldCheck, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { ActivityFeed } from "@/features/activity/ActivityFeed";
import { RobotHero } from "@/features/robot/RobotHero";
import { useHomeSnapshot } from "@/hooks/use-desktop-data";
import { createCoworkThread } from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import {
  audienceLabel,
  inferReviewStrictness,
  inferRoutingProfile,
  languageLabel,
  mergeWorkflowPreferences,
  outputModeLabel,
  preferredFormatsForTask,
  projectTemplateSummary,
  resolveProjectTemplate,
  stackLabel,
  toneLabel,
  workflowProfileSummary,
} from "@/utils/workflow-preferences";

export function HomeScreen() {
  const { data, isLoading, error, refetch } = useHomeSnapshot();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [command, setCommand] = useState("");
  const [launchingFlow, setLaunchingFlow] = useState<string | null>(null);
  const [launchError, setLaunchError] = useState("");
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);
  const setSelectedThreadId = useUiStore((state) => state.setSelectedThreadId);
  const setSelectedRunId = useUiStore((state) => state.setSelectedRunId);
  const workflowPreferences = useUiStore((state) => state.workflowPreferences);
  const projectTemplates = useUiStore((state) => state.projectTemplates);
  const activeProjectTemplateId = useUiStore((state) => state.activeProjectTemplateId);

  if (error) {
    return (
      <ErrorState
        title="Runtime snapshot unavailable"
        description="The desktop shell could not assemble a calm runtime overview. The Python operator runtime may still be booting."
        onRetry={() => void refetch()}
      />
    );
  }

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <SkeletonBlock className="h-[360px] w-full rounded-[32px]" />
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <SkeletonBlock key={index} />
          ))}
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

  const recentFocus = data.recentThreads?.slice(0, 3) || [];
  const quickActions = [
    {
      label: "Create document",
      icon: FileStack,
      route: "/command-center" as const,
    },
    {
      label: "Create presentation",
      icon: Sparkles,
      route: "/command-center" as const,
    },
    {
      label: "Create website",
      icon: Globe,
      route: "/command-center" as const,
    },
  ];

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

  const recommendedFlow = data.recommendedFlow || activeProjectTemplate.preferredTaskType;
  const resumeCandidate = data.lastThread || data.recentThreads?.[0];

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

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="overflow-hidden px-8 py-8">
        <div className="grid grid-cols-[1.12fr_0.88fr] gap-8">
          <div className="flex flex-col justify-center gap-6">
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <StatusBadge tone="info">TS desktop shell</StatusBadge>
                <StatusBadge tone={runtimeTone}>
                  {connectionState === "connected" ? "runtime online" : connectionState.replace(/_/g, " ")}
                </StatusBadge>
                <StatusBadge tone="success">{data.workspace.name}</StatusBadge>
              </div>
              <div className="space-y-3">
                <h1 className="max-w-3xl font-display text-[42px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
                  Secure task execution across documents, decks, sites, and real work.
                </h1>
                <p className="max-w-2xl text-[15px] leading-7 text-[var(--text-secondary)]">
                  Elyan is a policy-driven, cross-device agent operating layer. One cowork thread holds context, approvals, verification, and deterministic lanes for personal and team environments.
                </p>
              </div>
            </div>

            <div className="max-w-3xl space-y-3">
              <SearchField
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void launchWorkflow(inferTaskType(command));
                  }
                }}
                placeholder="Start a cowork thread for a document, deck, website, or follow-up"
                className="h-14 rounded-[20px] bg-[color-mix(in_srgb,var(--bg-surface)_92%,transparent)] px-5 text-[14px]"
              />
              <div className="flex flex-wrap gap-3">
                <Button variant="primary" onClick={() => void launchWorkflow(inferTaskType(command))} disabled={launchingFlow !== null}>
                  {launchingFlow ? "Starting thread" : "Start cowork"}
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
                    Continue last thread
                  </Button>
                ) : null}
                <Button variant="secondary" onClick={() => navigate("/providers")}>
                  <Bot className="mr-2 h-4 w-4" />
                  Models
                </Button>
                <Button variant="secondary" onClick={() => navigate("/integrations")}>
                  <Cable className="mr-2 h-4 w-4" />
                  Integrations
                </Button>
                <Button variant="ghost" onClick={() => navigate("/settings")}>
                  Refine defaults
                </Button>
              </div>
              <div className="flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                <span>{workflowProfileSummary(effectivePreferences)}</span>
                <span>·</span>
                <span>{outputModeLabel("document", effectivePreferences)}</span>
                <span>·</span>
                <span>{outputModeLabel("presentation", effectivePreferences)}</span>
              </div>
              {launchError ? <div className="text-[12px] text-[var(--state-warning)]">{launchError}</div> : null}
            </div>

            <div className="grid grid-cols-3 gap-3">
              {data.trustStrip.map((item) => (
                <div key={item.id} className="rounded-[18px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_90%,transparent)] px-4 py-4">
                  <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">{item.label}</div>
                  <div className="mt-2 flex items-center gap-2">
                    <div className="text-[18px] font-semibold text-[var(--text-primary)]">{item.value}</div>
                    <StatusBadge tone={item.tone === "error" ? "error" : item.tone === "warning" ? "warning" : item.tone === "success" ? "success" : "info"}>
                      {item.detail || "stable"}
                    </StatusBadge>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <RobotHero compact title="Elyan" subtitle="Quiet command home" />
        </div>
      </Surface>

      <div className="grid grid-cols-[1.08fr_0.92fr] gap-6">
        <div className="space-y-6">
          <Surface tone="card" className="p-6">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Primary flows</div>
                <h2 className="mt-2 font-display text-[24px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Start from a deterministic lane inside one thread
                </h2>
              </div>
              <Button variant="ghost" onClick={() => navigate("/command-center")}>
                <Command className="mr-2 h-4 w-4" />
                Command center
              </Button>
            </div>
            <div className="grid grid-cols-3 gap-4">
              {data.workflowCards.map((flow, index) => {
                const Icon = quickActions[index]?.icon || FileStack;
                return (
                  <button
                    key={flow.id}
                    type="button"
                    onClick={() => void launchWorkflow(flow.id)}
                    className="group rounded-[22px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-5 text-left transition hover:-translate-y-[1px] hover:border-[color-mix(in_srgb,var(--accent-primary)_24%,var(--border-subtle))] hover:bg-[var(--bg-surface)]"
                    disabled={launchingFlow !== null}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-[var(--accent-soft)] text-[var(--accent-primary)]">
                        <Icon className="h-5 w-5" />
                      </div>
                      <StatusBadge tone={flow.status === "degraded" ? "warning" : flow.status === "active" ? "success" : "info"}>
                        {flow.status}
                      </StatusBadge>
                    </div>
                    <div className="mt-5">
                      <div className="text-[15px] font-medium text-[var(--text-primary)]">{flow.title}</div>
                      <div className="mt-2 text-[13px] leading-6 text-[var(--text-secondary)]">{flow.description}</div>
                      <div className="mt-4 text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{flow.agentLane}</div>
                      <div className="mt-3 text-[12px] text-[var(--text-secondary)]">
                        {flow.id === "website"
                          ? `${stackLabel(effectivePreferences.websiteStack)} scaffold · ${toneLabel(effectivePreferences.tone)} tone`
                          : `${outputModeLabel(flow.id, effectivePreferences)} · ${languageLabel(effectivePreferences.language)} · ${audienceLabel(effectivePreferences.audience)}`}
                      </div>
                    </div>
                    <div className="mt-5 inline-flex items-center text-[12px] font-medium text-[var(--accent-primary)]">
                      {launchingFlow === flow.id ? "Starting…" : flow.actionLabel}
                      <ArrowRight className="ml-2 h-4 w-4 transition group-hover:translate-x-[1px]" />
                    </div>
                  </button>
                );
              })}
            </div>
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Recent cowork</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Resume recent threads
                </h2>
              </div>
              <StatusBadge tone={runtimeTone}>{sidecarHealth.managed ? "managed" : "external"}</StatusBadge>
            </div>
            <div className="space-y-3">
              {recentFocus.map((thread) => (
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
                  className="flex w-full items-start justify-between gap-4 rounded-[20px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-left transition hover:bg-[var(--bg-surface)]"
                >
                  <div>
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">{thread.title}</div>
                    <div className="mt-1 text-[12px] leading-6 text-[var(--text-secondary)]">
                      {thread.lastOperatorTurn?.content || thread.lastUserTurn?.content || thread.status}
                    </div>
                  </div>
                  <div className="text-right">
                    <StatusBadge tone={thread.status === "completed" ? "success" : thread.status === "failed" ? "error" : thread.pendingApprovals > 0 ? "warning" : "info"}>
                      {thread.currentMode}
                    </StatusBadge>
                    <div className="mt-2 text-[11px] text-[var(--text-tertiary)]">{thread.updatedAt}</div>
                  </div>
                </button>
              ))}
            </div>
          </Surface>
        </div>

        <div className="space-y-6">
          <Surface tone="card" className="p-6">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Active project template</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  {activeProjectTemplate.name}
                </h2>
                <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">{activeProjectTemplate.description}</div>
              </div>
              <StatusBadge tone="info">{projectTemplateSummary(activeProjectTemplate)}</StatusBadge>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => void launchWorkflow(recommendedFlow)}
                className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-left transition hover:bg-[var(--bg-surface)]"
                disabled={launchingFlow !== null}
              >
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Recommended next lane</div>
                <div className="mt-3 text-[16px] font-semibold text-[var(--text-primary)]">{recommendedFlow}</div>
                <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                  {recommendedFlow === "website"
                    ? `${stackLabel(effectivePreferences.websiteStack)} scaffold with ${toneLabel(effectivePreferences.tone).toLowerCase()} direction`
                    : `${audienceLabel(effectivePreferences.audience)}-ready ${outputModeLabel(recommendedFlow, effectivePreferences)}`}
                </div>
              </button>
              <button
                type="button"
                onClick={() => {
                  if (!resumeCandidate) {
                    return;
                  }
                  setSelectedThreadId(resumeCandidate.threadId);
                  if (resumeCandidate.activeRunId) {
                    setSelectedRunId(resumeCandidate.activeRunId);
                  }
                  navigate("/command-center");
                }}
                className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-left transition hover:bg-[var(--bg-surface)]"
                disabled={!resumeCandidate}
              >
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Resume lane</div>
                <div className="mt-3 text-[16px] font-semibold text-[var(--text-primary)]">{resumeCandidate?.title || "No resumable thread"}</div>
                <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                  {resumeCandidate ? `${resumeCandidate.status} · ${resumeCandidate.updatedAt}` : "Start a new cowork thread"}
                </div>
              </button>
            </div>
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="mb-4 flex items-center gap-3">
              <ShieldCheck className="h-4 w-4 text-[var(--accent-primary)]" />
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">Trust strip</div>
                <div className="text-[11px] text-[var(--text-tertiary)]">Runtime, approvals, and sidecar health</div>
              </div>
            </div>
            <div className="space-y-3">
              <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">Managed runtime</div>
                    <div className="mt-1 text-[12px] leading-6 text-[var(--text-secondary)]">
                      {sidecarHealth.runtimeUrl} · port {sidecarHealth.port}
                    </div>
                  </div>
                  <StatusBadge tone={runtimeTone}>
                    {connectionState === "connected" ? "healthy" : sidecarHealth.status}
                  </StatusBadge>
                </div>
                {sidecarHealth.lastError ? (
                  <div className="mt-3 text-[12px] leading-6 text-[var(--state-warning)]">{sidecarHealth.lastError}</div>
                ) : null}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                    <Clock3 className="h-3.5 w-3.5" />
                    Recent run
                  </div>
                  <div className="mt-3 text-[16px] font-semibold text-[var(--text-primary)]">
                    {data.recentRuns[0]?.title || "No active run"}
                  </div>
                  <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{data.recentRuns[0]?.updatedAt || "waiting"}</div>
                </div>
                <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                    <Sparkles className="h-3.5 w-3.5" />
                    Active providers
                  </div>
                  <div className="mt-3 text-[16px] font-semibold text-[var(--text-primary)]">
                    {data.providers.filter((provider) => provider.status === "connected").length}
                  </div>
                  <div className="mt-1 text-[12px] text-[var(--text-secondary)]">Ready execution lanes</div>
                </div>
              </div>
            </div>
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="mb-4 flex items-center gap-3">
              <Sparkles className="h-4 w-4 text-[var(--accent-primary)]" />
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">Minimal activity</div>
                <div className="text-[11px] text-[var(--text-tertiary)]">Only the latest operator signals</div>
              </div>
            </div>
            <ActivityFeed items={data.activity.slice(0, 4)} />
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="mb-4 flex items-center gap-3">
              <Globe className="h-4 w-4 text-[var(--accent-primary)]" />
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">Quick surfaces</div>
                <div className="text-[11px] text-[var(--text-tertiary)]">Secondary product areas stay one click away</div>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3">
              <Button variant="secondary" onClick={() => navigate("/providers")} className="justify-between">
                Provider management
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button variant="secondary" onClick={() => navigate("/integrations")} className="justify-between">
                Device and integrations
                <ArrowRight className="h-4 w-4" />
              </Button>
              <Button variant="secondary" onClick={() => navigate("/logs")} className="justify-between">
                Logs and monitoring
                <ArrowRight className="h-4 w-4" />
              </Button>
            </div>
          </Surface>
        </div>
      </div>

    </div>
  );
}
