import { useState } from "react";

import { Button } from "@/components/primitives/Button";
import { SegmentedControl } from "@/components/primitives/SegmentedControl";
import { ToggleSwitch } from "@/components/primitives/ToggleSwitch";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useBillingWorkspace, useLearningSummary, useSecuritySummary } from "@/hooks/use-desktop-data";
import { createCheckoutSession, createPortalSession } from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import {
  defaultWorkflowPreferences,
  documentOutputOptions,
  presentationOutputOptions,
  projectTemplateSummary,
  reviewStrictnessLabel,
  routingProfileLabel,
  workflowProfileSummary,
  websiteStackOptions,
  workflowAudienceOptions,
  workflowLanguageOptions,
  workflowToneOptions,
} from "@/utils/workflow-preferences";

const categories = ["General", "Workflows", "Appearance", "Models", "Security", "Integrations", "Shortcuts", "Advanced"] as const;

export function SettingsScreen() {
  const [category, setCategory] = useState<(typeof categories)[number]>("General");
  const [runtimeBusy, setRuntimeBusy] = useState<"restart" | "stop" | null>(null);
  const [billingBusy, setBillingBusy] = useState<"checkout" | "portal" | null>(null);
  const { data: security } = useSecuritySummary();
  const { data: learning } = useLearningSummary();
  const { data: billing } = useBillingWorkspace();
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);
  const setSidecarHealth = useRuntimeStore((state) => state.setSidecarHealth);
  const themeMode = useUiStore((state) => state.themeMode);
  const setThemeMode = useUiStore((state) => state.setThemeMode);
  const autoRouting = useUiStore((state) => state.autoRouting);
  const setAutoRouting = useUiStore((state) => state.setAutoRouting);
  const compactLogs = useUiStore((state) => state.compactLogs);
  const setCompactLogs = useUiStore((state) => state.setCompactLogs);
  const reduceMotion = useUiStore((state) => state.reduceMotion);
  const setReduceMotion = useUiStore((state) => state.setReduceMotion);
  const workflowPreferences = useUiStore((state) => state.workflowPreferences);
  const setWorkflowPreferences = useUiStore((state) => state.setWorkflowPreferences);
  const projectTemplates = useUiStore((state) => state.projectTemplates);
  const activeProjectTemplateId = useUiStore((state) => state.activeProjectTemplateId);
  const setActiveProjectTemplateId = useUiStore((state) => state.setActiveProjectTemplateId);

  async function restartRuntime() {
    setRuntimeBusy("restart");
    try {
      setSidecarHealth(await runtimeManager.restartRuntime());
    } finally {
      setRuntimeBusy(null);
    }
  }

  async function stopRuntime() {
    setRuntimeBusy("stop");
    try {
      setSidecarHealth(await runtimeManager.stopRuntime());
    } finally {
      setRuntimeBusy(null);
    }
  }

  async function openCheckout(planId: string) {
    setBillingBusy("checkout");
    try {
      const url = await createCheckoutSession(planId);
      if (url) {
        await runtimeManager.openExternalUrl(url);
      }
    } finally {
      setBillingBusy(null);
    }
  }

  async function openPortal() {
    setBillingBusy("portal");
    try {
      const url = await createPortalSession();
      if (url) {
        await runtimeManager.openExternalUrl(url);
      }
    } finally {
      setBillingBusy(null);
    }
  }

  return (
    <div className="grid grid-cols-[220px_1fr] gap-6">
      <Surface tone="card" className="p-4">
        <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Settings</div>
        <div className="mt-4 space-y-2">
          {categories.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setCategory(item)}
              className={`w-full rounded-md px-3 py-3 text-left text-[13px] font-medium transition ${
                item === category
                  ? "bg-[var(--accent-soft)] text-[var(--accent-primary)]"
                  : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-alt)] hover:text-[var(--text-primary)]"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </Surface>

      <Surface tone="card" className="p-6">
        <div className="mb-6">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">{category}</div>
          <h1 className="mt-2 font-display text-[28px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Defaults stay light.
          </h1>
          <p className="mt-3 max-w-3xl text-[14px] leading-7 text-[var(--text-secondary)]">
            Keep only the controls that change behavior.
          </p>
        </div>

        {learning ? (
          <Surface tone="panel" className="mb-6 rounded-[20px] border border-[var(--border-subtle)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Adaptive posture</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">
                  {learning.dominantDomain} · {Math.round(learning.learningScore * 100)}% · {learning.learningMode}
                </div>
              </div>
              <StatusBadge tone={learning.paused ? "warning" : learning.optOut ? "neutral" : "success"}>
                {learning.paused ? "paused" : learning.optOut ? "off" : "learning"}
              </StatusBadge>
            </div>
          </Surface>
        ) : null}

        <div className="grid gap-4">
          {(category === "General" || category === "Workflows") && (
            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Workflow launch profile</div>
                  <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                    Defaults for new document, presentation, and website flows.
                  </div>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setWorkflowPreferences(defaultWorkflowPreferences)}>
                  Reset
                </Button>
              </div>

              <div className="mt-5 grid gap-5">
                <div className="space-y-2">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Language</div>
                  <SegmentedControl
                    value={workflowPreferences.language}
                    onChange={(value) => setWorkflowPreferences({ language: value as typeof workflowPreferences.language })}
                    options={workflowLanguageOptions}
                  />
                </div>
                <div className="space-y-2">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Audience</div>
                  <SegmentedControl
                    value={workflowPreferences.audience}
                    onChange={(value) => setWorkflowPreferences({ audience: value as typeof workflowPreferences.audience })}
                    options={workflowAudienceOptions}
                  />
                </div>
                <div className="space-y-2">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Design tone</div>
                  <SegmentedControl
                    value={workflowPreferences.tone}
                    onChange={(value) => setWorkflowPreferences({ tone: value as typeof workflowPreferences.tone })}
                    options={workflowToneOptions}
                  />
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Document export</div>
                    <SegmentedControl
                      value={workflowPreferences.documentOutput}
                      onChange={(value) => setWorkflowPreferences({ documentOutput: value as typeof workflowPreferences.documentOutput })}
                      options={documentOutputOptions}
                    />
                  </div>
                  <div className="space-y-2">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Presentation export</div>
                    <SegmentedControl
                      value={workflowPreferences.presentationOutput}
                      onChange={(value) => setWorkflowPreferences({ presentationOutput: value as typeof workflowPreferences.presentationOutput })}
                      options={presentationOutputOptions}
                    />
                  </div>
                  <div className="space-y-2">
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Website stack</div>
                    <SegmentedControl
                      value={workflowPreferences.websiteStack}
                      onChange={(value) => setWorkflowPreferences({ websiteStack: value as typeof workflowPreferences.websiteStack })}
                      options={websiteStackOptions}
                    />
                  </div>
                </div>
              </div>
            </div>
          )}

          {(category === "General" || category === "Workflows") && (
            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Project templates</div>
                  <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                    Pick the default lane and review posture for a project family.
                  </div>
                </div>
                <StatusBadge tone="info">{workflowProfileSummary(workflowPreferences)}</StatusBadge>
              </div>

              <div className="mt-5 grid gap-3">
                {projectTemplates.map((template) => {
                  const active = template.id === activeProjectTemplateId;
                  return (
                    <button
                      key={template.id}
                      type="button"
                      onClick={() => setActiveProjectTemplateId(template.id)}
                      className={`rounded-[18px] border p-4 text-left transition ${
                        active
                          ? "border-[var(--border-focus)] bg-[var(--accent-soft)]"
                          : "border-[var(--border-subtle)] bg-[var(--bg-surface)] hover:bg-[var(--bg-shell)]"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[14px] font-medium text-[var(--text-primary)]">{template.name}</div>
                          <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">{template.description}</div>
                        </div>
                        <StatusBadge tone={active ? "success" : "info"}>{active ? "active" : "template"}</StatusBadge>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <StatusBadge tone="info">{template.preferredTaskType}</StatusBadge>
                        <StatusBadge tone="info">{routingProfileLabel(template.routingProfile)}</StatusBadge>
                        <StatusBadge tone={template.reviewStrictness === "strict" ? "warning" : "success"}>
                          {reviewStrictnessLabel(template.reviewStrictness)}
                        </StatusBadge>
                      </div>
                      <div className="mt-3 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                        {projectTemplateSummary(template)}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {(category === "Appearance" || category === "General") && (
            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-5">
              <div className="text-[13px] font-medium text-[var(--text-primary)]">Desktop surface behavior</div>
              <div className="mt-5 space-y-4">
                <div className="space-y-2">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Theme</div>
                  <SegmentedControl
                    value={themeMode}
                    onChange={(value) => setThemeMode(value as typeof themeMode)}
                    options={[
                      { label: "System", value: "system" },
                      { label: "Light", value: "light" },
                      { label: "Dark", value: "dark" },
                    ]}
                  />
                </div>
                <ToggleSwitch
                  checked={compactLogs}
                  onChange={setCompactLogs}
                  label="Compact monitoring surfaces"
                  description="Keep diagnostics visible but visually quiet."
                />
                <ToggleSwitch
                  checked={reduceMotion}
                  onChange={setReduceMotion}
                  label="Reduce motion"
                  description="Prefer minimal fades and static surfaces where possible."
                />
              </div>
            </div>
          )}

          {(category === "Models" || category === "General") && (
            <ToggleSwitch
              checked={autoRouting}
              onChange={setAutoRouting}
              label="Automatic model routing"
              description="Select the best lane based on task category, latency, and confidence."
            />
          )}

          {(category === "General" || category === "Advanced") && (
            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Managed runtime sidecar</div>
                  <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                    Desktop shell owns runtime launch, reconnect, and restart. Execution truth still stays inside the Python operator runtime.
                  </div>
                  <div className="mt-3 text-[12px] text-[var(--text-secondary)]">
                    {sidecarHealth.runtimeUrl} · port {sidecarHealth.port}
                  </div>
                  {sidecarHealth.lastError ? (
                    <div className="mt-2 text-[12px] text-[var(--state-warning)]">{sidecarHealth.lastError}</div>
                  ) : null}
                </div>
                <StatusBadge
                  tone={
                    connectionState === "connected"
                      ? "success"
                      : connectionState === "booting" || connectionState === "reconnecting"
                        ? "warning"
                        : "error"
                  }
                >
                  {connectionState}
                </StatusBadge>
              </div>
              <div className="mt-4 flex flex-wrap gap-3">
                <Button variant="secondary" onClick={() => void restartRuntime()} disabled={runtimeBusy !== null}>
                  {runtimeBusy === "restart" ? "Restarting..." : "Restart runtime"}
                </Button>
                <Button variant="ghost" onClick={() => void stopRuntime()} disabled={runtimeBusy !== null}>
                  {runtimeBusy === "stop" ? "Stopping..." : "Stop runtime"}
                </Button>
              </div>
            </div>
          )}

          {(category === "General" || category === "Advanced") && billing ? (
            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Workspace billing</div>
                  <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                    Hybrid billing stays workspace-owned. Entitlements gate threads, connectors, exports, premium models, and seats.
                  </div>
                </div>
                <StatusBadge tone={billing.plan.status === "active" ? "success" : "warning"}>
                  {billing.plan.label}
                </StatusBadge>
              </div>
              <div className="mt-5 grid grid-cols-3 gap-3">
                <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Threads</div>
                  <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">{billing.entitlements.maxThreads}</div>
                </div>
                <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Connectors</div>
                  <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">{billing.entitlements.maxConnectors}</div>
                </div>
                <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Usage budget</div>
                  <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">{billing.entitlements.monthlyUsageBudget}</div>
                </div>
              </div>
              <div className="mt-4 text-[12px] text-[var(--text-secondary)]">
                Seats {billing.entitlements.teamSeats} · Premium models {billing.entitlements.premiumModels ? "enabled" : "disabled"} · Budget used {Object.values(billing.usage.totals || {}).reduce((sum, value) => sum + Number(value || 0), 0)}
              </div>
              <div className="mt-4 flex gap-3">
                <Button variant="primary" onClick={() => void openCheckout("pro")} disabled={billingBusy !== null}>
                  {billingBusy === "checkout" ? "Opening..." : "Upgrade"}
                </Button>
                <Button variant="secondary" onClick={() => void openPortal()} disabled={billingBusy !== null}>
                  {billingBusy === "portal" ? "Opening..." : "Billing portal"}
                </Button>
              </div>
            </div>
          ) : null}

          {category === "Security" && security ? (
            <>
              <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">Runtime-owned posture</div>
                    <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                      Security policy is enforced by the operator runtime, not by local UI toggles.
                    </div>
                  </div>
                  <StatusBadge tone={security.pendingApprovals > 0 ? "warning" : "success"}>
                    {security.posture.replace(/_/g, " ")}
                  </StatusBadge>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Data locality</div>
                  <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">{security.dataLocality.replace(/_/g, " ")}</div>
                  <div className="mt-1 text-[12px] leading-6 text-[var(--text-secondary)]">
                    {security.cloudPromptRedaction ? "Cloud paths are redacted before escalation." : "Cloud redaction is disabled."}
                  </div>
                </div>
                <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Session security</div>
                  <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">
                    {security.sessionPersistence ? "Persistent" : "Ephemeral"}
                  </div>
                  <div className="mt-1 text-[12px] leading-6 text-[var(--text-secondary)]">
                    {security.activeSessions} active sessions · {security.handoffPending} handoffs pending
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="text-[13px] font-medium text-[var(--text-primary)]">Security posture</div>
              <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">
                Approval-first autonomy remains active. Sensitive writes, system-critical commands, and secret-adjacent tasks stay behind explicit gates.
              </div>
            </div>
          )}
        </div>
      </Surface>
    </div>
  );
}
