import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/primitives/Button";
import { SegmentedControl } from "@/components/primitives/SegmentedControl";
import { ToggleSwitch } from "@/components/primitives/ToggleSwitch";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useBillingWorkspace, useLearningSummary, usePrivacySummary } from "@/hooks/use-desktop-data";
import { createCheckoutSession, createPortalSession, deletePrivacyData, exportPrivacyData, logoutLocalUser } from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import {
  defaultWorkflowPreferences,
  documentOutputOptions,
  presentationOutputOptions,
  websiteStackOptions,
  workflowAudienceOptions,
  workflowLanguageOptions,
  workflowToneOptions,
} from "@/utils/workflow-preferences";

export function SettingsScreen() {
  const navigate = useNavigate();
  const [runtimeBusy, setRuntimeBusy] = useState<"restart" | "stop" | null>(null);
  const [billingBusy, setBillingBusy] = useState<"checkout" | "portal" | null>(null);
  const [privacyBusy, setPrivacyBusy] = useState<"export" | "delete" | null>(null);
  const { data: learning } = useLearningSummary();
  const { data: privacy } = usePrivacySummary();
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
  const authenticatedEmail = useUiStore((state) => state.authenticatedEmail);
  const signOut = useUiStore((state) => state.signOut);
  const clearSelectedThreadId = useUiStore((state) => state.clearSelectedThreadId);
  const clearSelectedRunId = useUiStore((state) => state.clearSelectedRunId);

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

  async function finalizeLocalSessionExit() {
    await logoutLocalUser().catch(() => undefined);
    signOut();
    clearSelectedThreadId();
    clearSelectedRunId();
    navigate("/login", { replace: true });
  }

  async function handleSignOut() {
    await finalizeLocalSessionExit();
  }

  async function handleExportPrivacy() {
    setPrivacyBusy("export");
    try {
      const payload = await exportPrivacyData();
      if (!payload) {
        return;
      }
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `elyan-privacy-${payload.userId || "user"}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } finally {
      setPrivacyBusy(null);
    }
  }

  async function handleDeletePrivacy() {
    setPrivacyBusy("delete");
    try {
      const deleted = await deletePrivacyData();
      if (deleted) {
        await finalizeLocalSessionExit();
      }
    } finally {
      setPrivacyBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="max-w-[900px] px-8 py-10">
        <div className="max-w-[640px] space-y-2">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Settings</div>
          <h1 className="font-display text-[32px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
            Defaults
          </h1>
        </div>
      </Surface>

      <div className="grid gap-6 lg:grid-cols-2">
        <Surface tone="card" className="p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Workflow defaults</div>
              <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Launch profile
              </h2>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setWorkflowPreferences(defaultWorkflowPreferences)}>
              Reset
            </Button>
          </div>

          <div className="mt-5 space-y-5">
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
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Tone</div>
              <SegmentedControl
                value={workflowPreferences.tone}
                onChange={(value) => setWorkflowPreferences({ tone: value as typeof workflowPreferences.tone })}
                options={workflowToneOptions}
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-2">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Doc export</div>
                <SegmentedControl
                  value={workflowPreferences.documentOutput}
                  onChange={(value) => setWorkflowPreferences({ documentOutput: value as typeof workflowPreferences.documentOutput })}
                  options={documentOutputOptions}
                />
              </div>
              <div className="space-y-2">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Slide export</div>
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
        </Surface>

        <Surface tone="card" className="p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Runtime</div>
              <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Local control
              </h2>
            </div>
            <StatusBadge tone={connectionState === "connected" ? "success" : connectionState === "booting" || connectionState === "reconnecting" ? "warning" : "error"}>
              {sidecarHealth.managed ? "managed" : "local"}
            </StatusBadge>
          </div>

          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Theme</div>
              <div className="mt-3">
                <SegmentedControl
                  value={themeMode}
                  onChange={(value) => setThemeMode(value as typeof themeMode)}
                  options={[
                    { value: "system", label: "System" },
                    { value: "light", label: "Light" },
                    { value: "dark", label: "Dark" },
                  ]}
                />
              </div>
            </div>
            <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Behavior</div>
              <div className="mt-4 space-y-3">
                <ToggleSwitch label="Auto routing" checked={autoRouting} onChange={setAutoRouting} />
                <ToggleSwitch label="Compact logs" checked={compactLogs} onChange={setCompactLogs} />
                <ToggleSwitch label="Reduce motion" checked={reduceMotion} onChange={setReduceMotion} />
              </div>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => void restartRuntime()} disabled={runtimeBusy !== null}>
              {runtimeBusy === "restart" ? "Restarting…" : "Restart"}
            </Button>
            <Button variant="ghost" onClick={() => void stopRuntime()} disabled={runtimeBusy !== null}>
              {runtimeBusy === "stop" ? "Stopping…" : "Stop"}
            </Button>
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Privacy</div>
              <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Data & learning
              </h2>
            </div>
            {learning ? (
              <StatusBadge tone={learning.paused ? "warning" : learning.optOut ? "neutral" : "success"}>
                {learning.paused ? "paused" : learning.optOut ? "off" : "learning"}
              </StatusBadge>
            ) : null}
          </div>

          <div className="mt-5 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
            <div className="space-y-2 text-[13px] leading-6 text-[var(--text-secondary)]">
              <div className="text-[14px] font-medium text-[var(--text-primary)]">
                {learning?.learningMode || "local"} · {learning ? Math.round(learning.learningScore * 100) : 0}%
              </div>
              <div>
                {privacy ? `${privacy.totalEntries} entries · ${privacy.redactedEntries} redacted · ${privacy.policy.learningScope}` : "Privacy summary unavailable."}
              </div>
              <div>
                {privacy?.whatIsLearned?.length ? `Learns: ${privacy.whatIsLearned.join(", ")}` : "Learns: redacted operational signals"}
              </div>
              <div>
                {privacy?.whatIsExcluded?.length ? `Excludes: ${privacy.whatIsExcluded.join(", ")}` : "Excludes: personal data, secrets"}
              </div>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => void handleExportPrivacy()} disabled={privacyBusy !== null}>
              {privacyBusy === "export" ? "Exporting…" : "Export data"}
            </Button>
            <Button variant="ghost" onClick={() => void handleDeletePrivacy()} disabled={privacyBusy !== null}>
              {privacyBusy === "delete" ? "Deleting…" : "Delete data"}
            </Button>
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Billing</div>
              <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Workspace plan
              </h2>
            </div>
            <StatusBadge tone={billing?.plan.status === "active" ? "success" : "neutral"}>{billing?.plan.label || "Free"}</StatusBadge>
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            <Button variant="primary" onClick={() => void openCheckout(billing?.plan.id || "pro")} disabled={billingBusy !== null}>
              Upgrade
            </Button>
            <Button variant="secondary" onClick={() => void openPortal()} disabled={billingBusy !== null}>
              Manage billing
            </Button>
          </div>
        </Surface>
      </div>

      <Surface tone="card" className="max-w-[900px] p-5">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Account</div>
            <div className="mt-2 truncate text-[14px] font-medium text-[var(--text-primary)]">
              {authenticatedEmail || "Signed in"}
            </div>
          </div>
          <Button variant="ghost" onClick={() => void handleSignOut()}>
            Sign out
          </Button>
        </div>
      </Surface>
    </div>
  );
}
