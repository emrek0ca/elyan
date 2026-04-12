import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Layers3, RefreshCw, Zap } from "@/vendor/lucide-react";

import { ErrorState } from "@/components/feedback/ErrorState";
import { SkeletonBlock } from "@/components/feedback/SkeletonBlock";
import { Button } from "@/components/primitives/Button";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Surface } from "@/components/primitives/Surface";
import { useOperatorStack, useSystemReadiness } from "@/hooks/use-desktop-data";
import { runRoutineNow, setRoutineEnabled, setSkillEnabled, setWorkflowEnabled } from "@/services/api/elyan-service";
import type { OperatorRoutine, OperatorStackSkill, OperatorWorkflow } from "@/types/domain";

export function OperatorStackScreen() {
  const queryClient = useQueryClient();
  const { data, isLoading, error, refetch } = useOperatorStack();
  const { data: readiness } = useSystemReadiness();
  const [busyAction, setBusyAction] = useState("");
  const [message, setMessage] = useState("");

  async function refreshAll() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["operator-stack"] }),
      queryClient.invalidateQueries({ queryKey: ["system-readiness"] }),
      queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
    ]);
  }

  async function handleSkillToggle(skill: OperatorStackSkill) {
    setBusyAction(`skill:${skill.name}`);
    setMessage("");
    try {
      const result = await setSkillEnabled(skill.name, !skill.enabled);
      setMessage(result.ok ? `${skill.name} ${skill.enabled ? "paused" : "enabled"}.` : result.message || "Skill güncellenemedi.");
      await refreshAll();
    } finally {
      setBusyAction("");
    }
  }

  async function handleWorkflowToggle(workflow: OperatorWorkflow) {
    setBusyAction(`workflow:${workflow.id}`);
    setMessage("");
    try {
      const result = await setWorkflowEnabled(workflow.id, !workflow.enabled);
      setMessage(result.ok ? `${workflow.name} ${workflow.enabled ? "paused" : "enabled"}.` : result.message || "Workflow güncellenemedi.");
      await refreshAll();
    } finally {
      setBusyAction("");
    }
  }

  async function handleRoutineToggle(routine: OperatorRoutine) {
    setBusyAction(`routine:${routine.id}`);
    setMessage("");
    try {
      const result = await setRoutineEnabled(routine.id, !routine.enabled);
      setMessage(result.ok ? `${routine.name} ${routine.enabled ? "paused" : "enabled"}.` : result.message || "Routine güncellenemedi.");
      await refreshAll();
    } finally {
      setBusyAction("");
    }
  }

  async function handleRoutineRun(routine: OperatorRoutine) {
    setBusyAction(`run:${routine.id}`);
    setMessage("");
    try {
      const result = await runRoutineNow(routine.id);
      setMessage(result.ok ? `${routine.name} çalıştırıldı.` : result.message || "Routine çalıştırılamadı.");
      await refreshAll();
    } finally {
      setBusyAction("");
    }
  }

  if (error) {
    return <ErrorState title="Operator stack yüklenemedi" description="Skills, workflows ve routines alınamadı." onRetry={() => void refetch()} />;
  }
  if (isLoading || !data) {
    return <SkeletonBlock className="h-[320px] w-full rounded-[32px]" />;
  }

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-7 py-7">
        <div className="max-w-[780px] space-y-3">
          <div className="flex items-center gap-3">
            <Layers3 className="h-5 w-5 text-[var(--accent-primary)]" />
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Operator stack</div>
          </div>
          <h1 className="font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Skills, workflows, routines
          </h1>
          <div className="text-[14px] text-[var(--text-secondary)]">
            Elyan’ın sürekli çalışan operator yüzeyleri tek yerde. Çalışan parçaları koru, sorunlu olanları burada gör ve düzelt.
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge tone={readiness?.status === "ready" ? "success" : readiness?.status === "booting" ? "warning" : "error"}>
              {readiness?.status || "unknown"}
            </StatusBadge>
            <StatusBadge tone={data.summary.skillsIssues ? "warning" : "success"}>
              {data.summary.skillsEnabled} skills live
            </StatusBadge>
            <StatusBadge tone={data.summary.workflowsEnabled ? "success" : "neutral"}>
              {data.summary.workflowsEnabled} workflows enabled
            </StatusBadge>
            <StatusBadge tone={data.summary.routinesEnabled ? "success" : "neutral"}>
              {data.summary.routinesEnabled}/{data.summary.routinesTotal} routines active
            </StatusBadge>
          </div>
        </div>
      </Surface>

      {message ? (
        <div className="text-[12px] text-[var(--text-secondary)]">{message}</div>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-3">
        <Surface tone="card" className="p-6">
          <SectionHeader title="Skills" detail="Installed operator skills" />
          <div className="mt-4 space-y-3">
            {data.skills.map((skill) => (
              <div key={skill.name} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-medium text-[var(--text-primary)]">{skill.name}</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{skill.description || "No description"}</div>
                  </div>
                  <StatusBadge tone={skill.healthOk ? "success" : "warning"}>
                    {skill.healthOk ? "healthy" : "needs attention"}
                  </StatusBadge>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <StatusBadge tone={skill.enabled ? "success" : "neutral"}>{skill.enabled ? "enabled" : "disabled"}</StatusBadge>
                  <StatusBadge tone={skill.runtimeReady ? "success" : "neutral"}>{skill.runtimeReady ? "runtime ready" : "runtime pending"}</StatusBadge>
                </div>
                <div className="mt-4 flex justify-end">
                  <Button
                    variant={skill.enabled ? "ghost" : "secondary"}
                    size="sm"
                    onClick={() => void handleSkillToggle(skill)}
                    disabled={busyAction === `skill:${skill.name}`}
                  >
                    {skill.enabled ? "Pause" : "Enable"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <SectionHeader title="Workflows" detail="Intent-driven execution packs" />
          <div className="mt-4 space-y-3">
            {data.workflows.map((workflow) => (
              <div key={workflow.id} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-medium text-[var(--text-primary)]">{workflow.name}</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{workflow.description || "Workflow surface"}</div>
                  </div>
                  <StatusBadge tone={workflow.runtimeReady ? "success" : "neutral"}>
                    {workflow.runtimeReady ? "ready" : "pending"}
                  </StatusBadge>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <StatusBadge tone={workflow.enabled ? "success" : "neutral"}>{workflow.enabled ? "enabled" : "disabled"}</StatusBadge>
                  <StatusBadge tone={workflow.executable ? "info" : "neutral"}>{workflow.executable ? "executable" : "catalog only"}</StatusBadge>
                  {workflow.autoIntent ? <StatusBadge tone="info">auto-intent</StatusBadge> : null}
                </div>
                <div className="mt-4 flex justify-end">
                  <Button
                    variant={workflow.enabled ? "ghost" : "secondary"}
                    size="sm"
                    onClick={() => void handleWorkflowToggle(workflow)}
                    disabled={busyAction === `workflow:${workflow.id}`}
                  >
                    {workflow.enabled ? "Pause" : "Enable"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <SectionHeader title="Routines" detail="Scheduled operator automations" />
          <div className="mt-4 space-y-3">
            {data.routines.map((routine) => (
              <div key={routine.id} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-medium text-[var(--text-primary)]">{routine.name}</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{routine.expression || "No schedule"}</div>
                  </div>
                  <StatusBadge tone={routine.enabled ? "success" : "neutral"}>{routine.enabled ? "active" : "paused"}</StatusBadge>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {routine.nextRun ? <StatusBadge tone="info">next {formatCompactTime(routine.nextRun)}</StatusBadge> : null}
                  {routine.reportChannel ? <StatusBadge tone="neutral">{routine.reportChannel}</StatusBadge> : null}
                  <StatusBadge tone={routine.runCount > 0 ? "success" : "neutral"}>{routine.runCount} runs</StatusBadge>
                </div>
                <div className="mt-4 flex justify-end gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleRoutineRun(routine)}
                    disabled={busyAction === `run:${routine.id}`}
                  >
                    <Zap className="mr-2 h-3.5 w-3.5" />
                    Run now
                  </Button>
                  <Button
                    variant={routine.enabled ? "ghost" : "secondary"}
                    size="sm"
                    onClick={() => void handleRoutineToggle(routine)}
                    disabled={busyAction === `routine:${routine.id}`}
                  >
                    {routine.enabled ? "Pause" : "Enable"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Surface>
      </div>

      <div className="flex justify-end">
        <Button variant="ghost" onClick={() => void refreshAll()} disabled={busyAction === "refresh"}>
          <RefreshCw className="mr-2 h-4 w-4" />
          Refresh stack
        </Button>
      </div>
    </div>
  );
}

function SectionHeader({ title, detail }: { title: string; detail: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">{title}</div>
      <div className="mt-2 text-[13px] text-[var(--text-secondary)]">{detail}</div>
    </div>
  );
}

function formatCompactTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("tr-TR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
