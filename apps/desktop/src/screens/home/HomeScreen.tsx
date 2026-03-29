import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Cable, Clock3, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { Surface } from "@/components/primitives/Surface";
import { useHomeSnapshot } from "@/hooks/use-desktop-data";
import { runtimeManager } from "@/runtime/runtime-manager";
import { createCoworkThread } from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
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
  const [runtimeMessage, setRuntimeMessage] = useState("");
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
        description="Desktop runtime özetini alamadı."
        onRetry={() => void refetch()}
      />
    );
  }

  if (isLoading || !data) {
    return <SkeletonBlock className="h-[420px] w-full rounded-[32px]" />;
  }

  const activeProjectTemplate = resolveProjectTemplate(projectTemplates, activeProjectTemplateId);
  const effectivePreferences = mergeWorkflowPreferences(workflowPreferences, activeProjectTemplate.preferences);
  const resumeCandidate = data.lastThread || data.recentThreads?.[0];
  const runtimeReady = hasRuntimeWriteAccess(connectionState, sidecarHealth);
  const runtimeGateReason = getRuntimeGateReason(connectionState, sidecarHealth);

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

  async function launchWorkflow(taskType: "document" | "presentation" | "website") {
    if (!runtimeReady) {
      setLaunchError(runtimeGateReason);
      return;
    }

    const fallbackBrief =
      taskType === "presentation"
        ? "Prepare a concise presentation with a clear narrative and export-ready slide structure."
        : taskType === "website"
          ? "Create a premium React website scaffold with clear information architecture and implementation notes."
          : "Create a clear, professional document with structure, review, and export-ready output.";

    setLaunchError("");
    setRuntimeMessage("");
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
  }

  async function handleRestartRuntime() {
    setRuntimeMessage("");
    try {
      await runtimeManager.restartRuntime();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
        queryClient.invalidateQueries({ queryKey: ["cowork-home"] }),
      ]);
      setRuntimeMessage("Runtime yeniden başlatılıyor.");
    } catch (restartError) {
      setRuntimeMessage(restartError instanceof Error ? restartError.message : "Runtime yeniden başlatılamadı.");
    }
  }

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-8 py-10 lg:px-12 lg:py-12">
        <div className="max-w-[720px] space-y-6">
          <div className="space-y-1">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Home</div>
            <h1 className="font-display text-[36px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
              Start
            </h1>
          </div>

          <div className="space-y-3">
            <SearchField
              value={command}
              onChange={(event) => {
                setCommand(event.target.value);
                if (launchError) {
                  setLaunchError("");
                }
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void launchWorkflow(inferTaskType(command));
                }
              }}
              placeholder="Ne yapmamı istiyorsun?"
              className="h-14 rounded-[20px] px-5 text-[14px] shadow-none"
            />

            <div className="flex flex-wrap gap-3">
              <Button variant="primary" onClick={() => void launchWorkflow(inferTaskType(command))} disabled={!runtimeReady || launchingFlow !== null}>
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
                Telegram
              </Button>

              {!runtimeReady ? (
                <Button variant="ghost" onClick={() => void handleRestartRuntime()}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Retry runtime
                </Button>
              ) : null}
            </div>

            {launchError ? <div className="text-[12px] text-[var(--state-warning)]">{launchError}</div> : null}
            {!launchError && !runtimeReady ? <div className="text-[12px] text-[var(--text-secondary)]">{runtimeGateReason}</div> : null}
            {!launchError && runtimeMessage ? <div className="text-[12px] text-[var(--text-secondary)]">{runtimeMessage}</div> : null}
          </div>
        </div>
      </Surface>
    </div>
  );
}
