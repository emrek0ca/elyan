import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, MessageCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import {
  useChannels,
  useChannelsCatalog,
  useConnectorAccounts,
  useConnectorTraces,
  useConnectors,
} from "@/hooks/use-desktop-data";
import { runtimeManager } from "@/runtime/runtime-manager";
import {
  connectConnector,
  refreshConnectorAccount,
  revokeConnectorAccount,
  testChannel,
  toggleChannel,
  upsertChannel,
} from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import { getRuntimeGateReason, hasRuntimeWriteAccess } from "@/utils/runtime-access";

const PRIMARY_CONNECTORS = ["github", "slack", "google_drive"];

export function IntegrationsScreen() {
  const queryClient = useQueryClient();
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);
  const runtimeReady = hasRuntimeWriteAccess(connectionState, sidecarHealth);
  const runtimeGateReason = getRuntimeGateReason(connectionState, sidecarHealth);
  const { data: connectors = [] } = useConnectors();
  const { data: accounts = [] } = useConnectorAccounts();
  const { data: traces = [] } = useConnectorTraces();
  const { data: channels = [] } = useChannels();
  const { data: channelCatalog = [] } = useChannelsCatalog();
  const [busyId, setBusyId] = useState("");
  const [telegramToken, setTelegramToken] = useState("");
  const [message, setMessage] = useState("");

  const telegramChannel = channels.find((item) => item.type === "telegram");
  const telegramCatalogEntry = channelCatalog.find((item) => item.type === "telegram");
  const primaryConnectors = useMemo(
    () =>
      connectors
        .filter((item) => PRIMARY_CONNECTORS.includes(item.connector))
        .sort((left, right) => PRIMARY_CONNECTORS.indexOf(left.connector) - PRIMARY_CONNECTORS.indexOf(right.connector)),
    [connectors],
  );
  const latestTrace = traces[0];

  async function syncViews() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["channels"] }),
      queryClient.invalidateQueries({ queryKey: ["channels-catalog"] }),
      queryClient.invalidateQueries({ queryKey: ["connectors"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-traces"] }),
      queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
    ]);
  }

  async function guardRuntime() {
    if (runtimeReady) {
      return true;
    }
    setMessage(runtimeGateReason);
    return false;
  }

  async function handleTelegramSave() {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId("telegram-save");
    setMessage("");
    try {
      if (!telegramToken.trim() && !telegramChannel) {
        setMessage("Telegram bot token gerekli.");
        return;
      }
      await upsertChannel({
        type: "telegram",
        id: telegramChannel?.id || "telegram",
        token: telegramToken.trim() || undefined,
        enabled: true,
      });
      setTelegramToken("");
      setMessage("Telegram kaydedildi.");
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Telegram kaydedilemedi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleTelegramToggle(enabled: boolean) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId("telegram-toggle");
    setMessage("");
    try {
      await toggleChannel(telegramChannel?.id || "telegram", enabled);
      setMessage(enabled ? "Telegram açıldı." : "Telegram kapatıldı.");
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Telegram durumu değiştirilemedi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleTelegramTest() {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId("telegram-test");
    setMessage("");
    try {
      const result = await testChannel("telegram");
      setMessage(result.message || (result.connected ? "Telegram bağlı." : "Telegram henüz bağlı değil."));
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Telegram test edilemedi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleConnect(connector: string) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`connect:${connector}`);
    setMessage("");
    try {
      const result = await connectConnector(connector);
      if (result.launchUrl) {
        await runtimeManager.openExternalUrl(result.launchUrl);
      } else {
        setMessage("Bağlantı isteği gönderildi.");
      }
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Bağlantı başlatılamadı.");
    } finally {
      setBusyId("");
    }
  }

  async function handleRefresh(accountId: string) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`refresh:${accountId}`);
    try {
      await refreshConnectorAccount(accountId);
      await syncViews();
    } finally {
      setBusyId("");
    }
  }

  async function handleRevoke(accountId: string) {
    if (!(await guardRuntime())) {
      return;
    }
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
      <Surface tone="hero" className="px-8 py-8 lg:px-10">
        <div className="max-w-[720px] space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone={telegramChannel?.connected ? "success" : runtimeReady ? "info" : "warning"}>
              {telegramChannel?.connected ? "telegram connected" : runtimeReady ? "telegram ready" : "runtime locked"}
            </StatusBadge>
            <StatusBadge tone="info">Apps</StatusBadge>
          </div>
          <h1 className="font-display text-[38px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
            Telegram’ı bağla.
          </h1>
          <p className="max-w-[620px] text-[14px] leading-7 text-[var(--text-secondary)]">
            Elyan görevleri Telegram’dan alıp aynı runtime içinde yürütür.
          </p>
        </div>
      </Surface>

      <Surface tone="card" className="max-w-[760px] p-6">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-[var(--accent-soft)] text-[var(--accent-primary)]">
              <MessageCircle className="h-5 w-5" />
            </div>
            <div>
              <div className="text-[16px] font-semibold text-[var(--text-primary)]">Telegram bot</div>
              <div className="text-[12px] text-[var(--text-secondary)]">Tek gerekli channel setup</div>
            </div>
          </div>
          <StatusBadge tone={telegramChannel?.connected ? "success" : telegramChannel?.enabled ? "warning" : "info"}>
            {telegramChannel?.connected ? "connected" : telegramChannel?.enabled ? "configured" : "not connected"}
          </StatusBadge>
        </div>

        <div className="mt-5 space-y-4">
          <input
            type="password"
            value={telegramToken}
            onChange={(event) => setTelegramToken(event.target.value)}
            placeholder={telegramCatalogEntry?.fields.find((field) => field.name === "token")?.label || "Telegram bot token"}
            className="h-[52px] w-full rounded-[20px] border border-[var(--border-subtle)] bg-[color-mix(in_srgb,var(--bg-surface)_94%,var(--bg-surface-raised))] px-5 text-[14px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
          />

          <div className="flex flex-wrap gap-3">
            <Button variant="primary" onClick={() => void handleTelegramSave()} disabled={!runtimeReady || busyId === "telegram-save"}>
              {busyId === "telegram-save" ? "Saving..." : telegramChannel ? "Update" : "Connect"}
            </Button>
            <Button variant="secondary" onClick={() => void handleTelegramTest()} disabled={!runtimeReady || busyId === "telegram-test"}>
              {busyId === "telegram-test" ? "Testing..." : "Test"}
            </Button>
            {telegramChannel ? (
              <Button variant="ghost" onClick={() => void handleTelegramToggle(!telegramChannel.enabled)} disabled={!runtimeReady || busyId === "telegram-toggle"}>
                {telegramChannel.enabled ? "Disable" : "Enable"}
              </Button>
            ) : null}
          </div>

          <div className="flex flex-wrap gap-6 text-[13px] text-[var(--text-secondary)]">
            <span>Status: {telegramChannel?.status || "disconnected"}</span>
            <span>Received: {telegramChannel?.messageMetrics?.received || 0}</span>
            <span>Sent: {telegramChannel?.messageMetrics?.sent || 0}</span>
          </div>

          {message ? <div className="text-[12px] text-[var(--text-secondary)]">{message}</div> : null}
          {!message && !runtimeReady ? <div className="text-[12px] text-[var(--text-secondary)]">{runtimeGateReason}</div> : null}
        </div>
      </Surface>

      <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
        <Surface tone="card" className="p-6">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Other apps</div>
          <div className="mt-4 flex flex-wrap gap-3">
            {primaryConnectors.map((connector) => {
              const account = accounts.find((item) => item.provider === connector.provider);
              return (
                <div key={connector.connector} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-4">
                  <div className="flex items-center gap-3">
                    <div className="text-[14px] font-medium text-[var(--text-primary)]">{connector.label}</div>
                    <StatusBadge tone={connector.status === "connected" ? "success" : connector.status === "pending" ? "warning" : "info"}>
                      {connector.status}
                    </StatusBadge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" onClick={() => void handleConnect(connector.connector)} disabled={!runtimeReady || busyId === `connect:${connector.connector}`}>
                      {connector.status === "connected" ? "Reconnect" : "Connect"}
                    </Button>
                    {account ? (
                      <>
                        <Button variant="ghost" size="sm" onClick={() => void handleRefresh(account.accountId)} disabled={!runtimeReady || busyId === `refresh:${account.accountId}`}>
                          <RefreshCw className="mr-2 h-3.5 w-3.5" />
                          Refresh
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => void handleRevoke(account.accountId)} disabled={!runtimeReady || busyId === `revoke:${account.accountId}`}>
                          Remove
                        </Button>
                      </>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Latest trace</div>
          <div className="mt-3 space-y-2">
            {latestTrace ? (
              <>
                <div className="text-[18px] font-semibold text-[var(--text-primary)]">{latestTrace.connectorName}</div>
                <div className="text-[13px] text-[var(--text-secondary)]">{latestTrace.operation}</div>
                <div className="text-[12px] text-[var(--text-tertiary)]">{latestTrace.createdAt}</div>
              </>
            ) : (
              <div className="text-[13px] text-[var(--text-secondary)]">Henüz dış aksiyon yok.</div>
            )}
          </div>
          <div className="mt-5">
            <Button variant="ghost" onClick={() => void runtimeManager.openExternalUrl("https://elyan.dev")} disabled={busyId !== ""}>
              elyan.dev
              <ExternalLink className="ml-2 h-4 w-4" />
            </Button>
          </div>
        </Surface>
      </div>
    </div>
  );
}
