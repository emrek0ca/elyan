import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/primitives/Button";
import { SegmentedControl } from "@/components/primitives/SegmentedControl";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useConnectorAccounts, useConnectorHealth, useConnectorTraces, useConnectors } from "@/hooks/use-desktop-data";
import { connectConnector, refreshConnectorAccount, revokeConnectorAccount } from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";

export function IntegrationsScreen() {
  const queryClient = useQueryClient();
  const { data: connectors = [] } = useConnectors();
  const { data: accounts = [] } = useConnectorAccounts();
  const { data: health = [] } = useConnectorHealth();
  const { data: traces = [] } = useConnectorTraces();
  const [filter, setFilter] = useState("all");
  const [busyId, setBusyId] = useState("");

  const filtered = useMemo(() => {
    if (filter === "all") {
      return connectors;
    }
    return connectors.filter((item) => item.connector === filter);
  }, [connectors, filter]);

  async function syncViews() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["connectors"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-health"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-traces"] }),
      queryClient.invalidateQueries({ queryKey: ["logs"] }),
    ]);
  }

  async function handleConnect(connector: string) {
    setBusyId(`connect:${connector}`);
    try {
      const result = await connectConnector(connector);
      if (result.launchUrl) {
        await runtimeManager.openExternalUrl(result.launchUrl);
      }
      await syncViews();
    } finally {
      setBusyId("");
    }
  }

  async function handleRefresh(accountId: string) {
    setBusyId(`refresh:${accountId}`);
    try {
      await refreshConnectorAccount(accountId);
      await syncViews();
    } finally {
      setBusyId("");
    }
  }

  async function handleRevoke(accountId: string) {
    setBusyId(`revoke:${accountId}`);
    try {
      await revokeConnectorAccount(accountId);
      await syncViews();
    } finally {
      setBusyId("");
    }
  }

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-6 py-6">
        <div className="flex items-center justify-between gap-6">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Connector platform</div>
            <h1 className="mt-2 font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
              Workspace-owned app connectivity
            </h1>
            <p className="mt-3 max-w-3xl text-[14px] leading-7 text-[var(--text-secondary)]">
              Google Drive, Gmail, Calendar, Slack, and GitHub stay explicit. Scope, health, traces, and reconnect actions are visible in one clean surface.
            </p>
          </div>
          <SegmentedControl
            value={filter}
            onChange={setFilter}
            options={[
              { label: "All", value: "all" },
              ...connectors.map((connector) => ({ label: connector.label, value: connector.connector })),
            ]}
          />
        </div>
      </Surface>

      <div className="grid grid-cols-[1.1fr_0.9fr] gap-6">
        <div className="space-y-4">
          {filtered.map((connector) => {
            const connectorAccounts = accounts.filter((account) => account.provider === connector.provider);
            const connectorHealth = health.find((entry) => entry.connector === connector.connector);
            return (
              <Surface key={connector.connector} tone="card" className="p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-[16px] font-semibold text-[var(--text-primary)]">{connector.label}</div>
                    <div className="mt-2 text-[12px] text-[var(--text-secondary)]">
                      {connector.capabilities.join(" · ")}
                    </div>
                  </div>
                  <StatusBadge tone={connector.status === "connected" ? "success" : connector.status === "pending" ? "warning" : "info"}>
                    {connector.status}
                  </StatusBadge>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <StatusBadge tone="info">{`${connector.accountCount} accounts`}</StatusBadge>
                  <StatusBadge tone="info">{`${connector.traceCount} traces`}</StatusBadge>
                  {connectorHealth ? <StatusBadge tone={connectorHealth.status === "connected" ? "success" : "warning"}>{connectorHealth.status}</StatusBadge> : null}
                </div>
                <div className="mt-5 flex gap-3">
                  <Button variant="primary" size="sm" onClick={() => void handleConnect(connector.connector)} disabled={busyId === `connect:${connector.connector}`}>
                    {busyId === `connect:${connector.connector}` ? "Connecting…" : "Connect"}
                  </Button>
                </div>
                {connectorAccounts.length ? (
                  <div className="mt-5 space-y-3">
                    {connectorAccounts.map((account) => (
                      <div key={account.accountId} className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-[13px] font-medium text-[var(--text-primary)]">{account.displayName || account.provider}</div>
                            <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{account.email || account.accountAlias}</div>
                          </div>
                          <StatusBadge tone={account.status === "ready" ? "success" : account.status === "needs_input" ? "warning" : "info"}>
                            {account.status}
                          </StatusBadge>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {account.grantedScopes.slice(0, 3).map((scope) => (
                            <StatusBadge key={scope} tone="info">
                              {scope}
                            </StatusBadge>
                          ))}
                        </div>
                        <div className="mt-4 flex gap-2">
                          <Button variant="secondary" size="sm" onClick={() => void handleRefresh(account.accountId)} disabled={busyId === `refresh:${account.accountId}`}>
                            Refresh
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => void handleRevoke(account.accountId)} disabled={busyId === `revoke:${account.accountId}`}>
                            Revoke
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </Surface>
            );
          })}
        </div>

        <div className="space-y-4">
          <Surface tone="card" className="p-5">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Connector traces</div>
            <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
              Recent external actions
            </h2>
            <div className="mt-4 space-y-3">
              {traces.slice(0, 10).map((trace) => (
                <div key={trace.traceId} className="rounded-md border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">{trace.connectorName}</div>
                      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{trace.operation}</div>
                    </div>
                    <StatusBadge tone={trace.success ? "success" : "warning"}>{trace.status}</StatusBadge>
                  </div>
                  <div className="mt-2 text-[11px] text-[var(--text-tertiary)]">{trace.createdAt}</div>
                </div>
              ))}
            </div>
          </Surface>
        </div>
      </div>
    </div>
  );
}
