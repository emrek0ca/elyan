import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Cloud, Download, KeyRound, RefreshCw, Trash2 } from "@/vendor/lucide-react";

import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Button } from "@/components/primitives/Button";
import { useProviderDescriptors, useSystemReadiness } from "@/hooks/use-desktop-data";
import {
  deleteOllamaModel,
  pullOllamaModel,
  removeProviderKey,
  saveProviderKey,
  updateProviderLanePreferences,
} from "@/services/api/elyan-service";
import type { ProviderDescriptor } from "@/types/domain";

const cloudProviderOrder = ["openai", "anthropic", "google", "groq"];

export function ProvidersScreen() {
  const queryClient = useQueryClient();
  const { data = [], isLoading } = useProviderDescriptors();
  const { data: readiness } = useSystemReadiness();
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [busyAction, setBusyAction] = useState("");
  const [message, setMessage] = useState("");

  const ollama = data.find((provider) => provider.providerId === "ollama");
  const cloudProviders = useMemo<ProviderDescriptor[]>(
    () =>
      cloudProviderOrder
        .map((providerId) => data.find((item) => item.providerId === providerId))
        .filter((provider): provider is ProviderDescriptor => Boolean(provider)),
    [data],
  );
  const primaryLane = ollama?.models.find((model) => model.installed) || cloudProviders[0]?.models[0];
  const fallbackLane =
    cloudProviders.find((provider) => provider.models.length)?.models[0] ||
    ollama?.models.find((model) => model.installed) ||
    primaryLane;

  async function refreshData() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["provider-descriptors"] }),
      queryClient.invalidateQueries({ queryKey: ["system-readiness"] }),
      queryClient.invalidateQueries({ queryKey: ["providers"] }),
    ]);
  }

  async function handleSaveKey(providerId: string) {
    setBusyAction(`save:${providerId}`);
    setMessage("");
    try {
      const result = await saveProviderKey(providerId, apiKeys[providerId] || "");
      setMessage(result.message || (result.ok ? `${providerId} ready.` : `${providerId} failed.`));
      if (result.ok) {
        setApiKeys((current) => ({ ...current, [providerId]: "" }));
        await refreshData();
      }
    } finally {
      setBusyAction("");
    }
  }

  async function handleRemoveKey(providerId: string) {
    setBusyAction(`remove:${providerId}`);
    setMessage("");
    try {
      const result = await removeProviderKey(providerId);
      setMessage(result.message || `${providerId} key removed.`);
      await refreshData();
    } finally {
      setBusyAction("");
    }
  }

  async function handlePull(modelId: string) {
    setBusyAction(`pull:${modelId}`);
    setMessage("");
    try {
      const result = await pullOllamaModel(modelId);
      setMessage(result.message || `${modelId} queued.`);
      await refreshData();
    } finally {
      setBusyAction("");
    }
  }

  async function handleDelete(modelId: string) {
    setBusyAction(`delete:${modelId}`);
    setMessage("");
    try {
      const result = await deleteOllamaModel(modelId);
      setMessage(result.message || `${modelId} removed.`);
      await refreshData();
    } finally {
      setBusyAction("");
    }
  }

  async function handleApplyLaneDefaults() {
    if (!primaryLane || !fallbackLane) {
      return;
    }
    setBusyAction("lane-defaults");
    setMessage("");
    try {
      const ok = await updateProviderLanePreferences({
        defaultProvider: primaryLane.providerId,
        defaultModel: primaryLane.modelId,
        fallbackProvider: fallbackLane.providerId,
        fallbackModel: fallbackLane.modelId,
      });
      setMessage(ok ? "Default and fallback lanes updated." : "Lane defaults could not be updated.");
      await refreshData();
    } finally {
      setBusyAction("");
    }
  }

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-7 py-7">
        <div className="max-w-[780px] space-y-3">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Models</div>
          <h1 className="font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Models & providers
          </h1>
          <div className="text-[14px] text-[var(--text-secondary)]">
            Tek çalışan ürün yolu: local lanes hazır kalsın, cloud lanes gerektiğinde devreye girsin.
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={readiness?.status === "ready" ? "success" : readiness?.status === "booting" ? "warning" : "error"}>
              {readiness?.status || "unknown"}
            </StatusBadge>
            <div className="text-[12px] text-[var(--text-secondary)]">
              {readiness?.providerSummary.available || 0} providers ready · {readiness?.providerSummary.authRequired || 0} auth needed
            </div>
          </div>
        </div>
      </Surface>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-6">
          <Surface tone="card" className="p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Local</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Ollama control center
                </h2>
              </div>
              <StatusBadge tone={ollama?.healthState === "available" ? "success" : "warning"}>
                {ollama?.healthState || "offline"}
              </StatusBadge>
            </div>

            <div className="mt-4 flex items-center justify-between gap-3 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div>
                <div className="text-[14px] font-medium text-[var(--text-primary)]">Host</div>
                <div className="text-[12px] text-[var(--text-secondary)]">{ollama?.detail || "No local model status yet."}</div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => void refreshData()} disabled={busyAction === "refresh"}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Refresh
              </Button>
            </div>

            <div className="mt-4 space-y-3">
              {(ollama?.models || []).map((model) => (
                <div key={model.modelId} className="flex items-center justify-between gap-4 rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-medium text-[var(--text-primary)]">{model.displayName}</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                      {model.size || "size unknown"} {model.roleAssignments?.length ? `· lanes: ${model.roleAssignments.join(", ")}` : ""}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge tone={model.installed ? "success" : "neutral"}>{model.installed ? "installed" : "available"}</StatusBadge>
                    {!model.installed ? (
                      <Button variant="secondary" size="sm" onClick={() => void handlePull(model.modelId)} disabled={busyAction === `pull:${model.modelId}`}>
                        <Download className="mr-2 h-4 w-4" />
                        Pull
                      </Button>
                    ) : (
                      <Button variant="ghost" size="sm" onClick={() => void handleDelete(model.modelId)} disabled={busyAction === `delete:${model.modelId}`}>
                        <Trash2 className="mr-2 h-4 w-4" />
                        Remove
                      </Button>
                    )}
                  </div>
                </div>
              ))}
              {!ollama?.models?.length && !isLoading ? (
                <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[13px] text-[var(--text-secondary)]">
                  No Ollama models discovered yet.
                </div>
              ) : null}
            </div>
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Lanes</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Runtime defaults
                </h2>
              </div>
              <Button variant="secondary" onClick={() => void handleApplyLaneDefaults()} disabled={!primaryLane || !fallbackLane || busyAction === "lane-defaults"}>
                Apply
              </Button>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Primary lane</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">
                  {primaryLane ? `${primaryLane.providerId} / ${primaryLane.displayName}` : "Unavailable"}
                </div>
              </div>
              <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Fallback lane</div>
                <div className="mt-2 text-[14px] font-medium text-[var(--text-primary)]">
                  {fallbackLane ? `${fallbackLane.providerId} / ${fallbackLane.displayName}` : "Unavailable"}
                </div>
              </div>
            </div>
          </Surface>
        </div>

        <div className="space-y-6">
          <Surface tone="card" className="p-6">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Cloud</div>
              <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                Provider access
              </h2>
            </div>

            <div className="mt-4 space-y-3">
              {cloudProviders.map((provider) => (
                <div key={provider.providerId} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 text-[14px] font-medium text-[var(--text-primary)]">
                        <Cloud className="h-4 w-4" />
                        {provider.label}
                      </div>
                      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{provider.detail}</div>
                    </div>
                    <StatusBadge tone={provider.authState === "ready" ? "success" : provider.healthState === "degraded" ? "warning" : "neutral"}>
                      {provider.authState === "ready" ? provider.healthState : provider.authState}
                    </StatusBadge>
                  </div>

                  <div className="mt-4 flex gap-2">
                    <input
                      type="password"
                      value={apiKeys[provider.providerId] || ""}
                      onChange={(event) => setApiKeys((current) => ({ ...current, [provider.providerId]: event.target.value }))}
                      placeholder={`${provider.label} API key`}
                      className="h-[42px] flex-1 rounded-[14px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                    />
                    <Button variant="secondary" size="sm" onClick={() => void handleSaveKey(provider.providerId)} disabled={busyAction === `save:${provider.providerId}`}>
                      <KeyRound className="mr-2 h-4 w-4" />
                      Save
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => void handleRemoveKey(provider.providerId)} disabled={busyAction === `remove:${provider.providerId}`}>
                      Clear
                    </Button>
                  </div>

                  {provider.lanes.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {provider.lanes.map((lane) => (
                        <StatusBadge
                          key={`${provider.providerId}-${lane.lane}-${lane.model}`}
                          tone={lane.fallbackActive ? "warning" : lane.verificationState === "verified" ? "info" : "neutral"}
                        >
                          {`${lane.lane} · ${lane.model || provider.label}`}
                        </StatusBadge>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </Surface>

          {message ? (
            <Surface tone="card" className="p-4">
              <div className="text-[13px] text-[var(--text-secondary)]">{message}</div>
            </Surface>
          ) : null}
        </div>
      </div>
    </div>
  );
}
