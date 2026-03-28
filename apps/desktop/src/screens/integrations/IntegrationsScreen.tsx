import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, MessageCircle, RefreshCw } from "lucide-react";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useChannels, useChannelsCatalog, useConnectorAccounts, useConnectorTraces, useConnectors } from "@/hooks/use-desktop-data";
import {
  connectConnector,
  refreshConnectorAccount,
  revokeConnectorAccount,
  testChannel,
  toggleChannel,
  upsertChannel,
} from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";

const PRIMARY_CONNECTORS = ["github", "slack", "google_drive", "gmail"];

export function IntegrationsScreen() {
  const queryClient = useQueryClient();
  const { data: connectors = [] } = useConnectors();
  const { data: accounts = [] } = useConnectorAccounts();
  const { data: traces = [] } = useConnectorTraces();
  const { data: channels = [] } = useChannels();
  const { data: channelCatalog = [] } = useChannelsCatalog();
  const [busyId, setBusyId] = useState("");
  const [telegramToken, setTelegramToken] = useState("");
  const [telegramMessage, setTelegramMessage] = useState("");

  const telegramChannel = channels.find((item) => item.type === "telegram");
  const telegramCatalogEntry = channelCatalog.find((item) => item.type === "telegram");
  const primaryConnectors = useMemo(
    () => connectors.filter((item) => PRIMARY_CONNECTORS.includes(item.connector)).sort((left, right) => PRIMARY_CONNECTORS.indexOf(left.connector) - PRIMARY_CONNECTORS.indexOf(right.connector)),
    [connectors],
  );

  async function syncViews() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["channels"] }),
      queryClient.invalidateQueries({ queryKey: ["channels-catalog"] }),
      queryClient.invalidateQueries({ queryKey: ["connectors"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-accounts"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-traces"] }),
      queryClient.invalidateQueries({ queryKey: ["logs"] }),
      queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
    ]);
  }

  async function handleTelegramSave() {
    setBusyId("telegram-save");
    setTelegramMessage("");
    try {
      if (!telegramToken.trim() && !telegramChannel) {
        setTelegramMessage("Telegram bot token gerekli.");
        return;
      }
      await upsertChannel({
        type: "telegram",
        id: telegramChannel?.id || "telegram",
        token: telegramToken.trim() || undefined,
        enabled: true,
      });
      setTelegramToken("");
      setTelegramMessage("Telegram yapılandırması kaydedildi.");
      await syncViews();
    } catch (error) {
      setTelegramMessage(error instanceof Error ? error.message : "Telegram kaydedilemedi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleTelegramToggle(enabled: boolean) {
    setBusyId("telegram-toggle");
    setTelegramMessage("");
    try {
      await toggleChannel(telegramChannel?.id || "telegram", enabled);
      setTelegramMessage(enabled ? "Telegram açıldı." : "Telegram kapatıldı.");
      await syncViews();
    } catch (error) {
      setTelegramMessage(error instanceof Error ? error.message : "Telegram durumu değiştirilemedi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleTelegramTest() {
    setBusyId("telegram-test");
    setTelegramMessage("");
    try {
      const result = await testChannel("telegram");
      setTelegramMessage(result.message || (result.connected ? "Telegram bağlı." : "Telegram henüz bağlı değil."));
      await syncViews();
    } catch (error) {
      setTelegramMessage(error instanceof Error ? error.message : "Telegram test edilemedi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleConnect(connector: string) {
    setBusyId(`connect:${connector}`);
    setTelegramMessage("");
    try {
      const result = await connectConnector(connector);
      if (result.launchUrl) {
        await runtimeManager.openExternalUrl(result.launchUrl);
      } else {
        setTelegramMessage("Bağlantı isteği gönderildi. Gerekliyse sağlayıcı tarafında oturum açmayı tamamla.");
      }
      await syncViews();
    } catch (error) {
      setTelegramMessage(error instanceof Error ? error.message : "Bağlantı başlatılamadı.");
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
        <div className="max-w-[760px]">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Integrations</div>
          <h1 className="mt-2 font-display text-[30px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Simple, working connections
          </h1>
          <p className="mt-3 text-[14px] leading-7 text-[var(--text-secondary)]">
            Telegram görev girişini ve çıktı teslimini taşısın. Diğer uygulamalar da tek tek, görünür şekilde bağlansın.
          </p>
        </div>
      </Surface>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <Surface tone="card" className="p-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-[16px] bg-[var(--accent-soft)] text-[var(--accent-primary)]">
                <MessageCircle className="h-5 w-5" />
              </div>
              <div>
                <div className="text-[16px] font-semibold text-[var(--text-primary)]">Telegram</div>
                <div className="text-[12px] text-[var(--text-secondary)]">
                  Elyan görevleri Telegram üzerinden alıp aynı runtime ile çalıştırır.
                </div>
              </div>
            </div>
            <StatusBadge tone={telegramChannel?.connected ? "success" : telegramChannel?.enabled ? "warning" : "info"}>
              {telegramChannel?.connected ? "connected" : telegramChannel?.enabled ? "configured" : "not connected"}
            </StatusBadge>
          </div>

          <div className="mt-5 space-y-4">
            <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Bot token</div>
              <input
                type="password"
                value={telegramToken}
                onChange={(event) => setTelegramToken(event.target.value)}
                placeholder={telegramCatalogEntry?.fields.find((field) => field.name === "token")?.label || "Telegram Bot Token"}
                className="mt-3 h-12 w-full rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 text-[14px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
              />
              <div className="mt-2 text-[12px] text-[var(--text-secondary)]">
                {telegramChannel ? "Kaydedilmiş token güvenli şekilde tutuluyor. Yeni token girersen değiştirilir." : "BotFather’dan aldığın token’ı buraya ekle."}
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button variant="primary" onClick={() => void handleTelegramSave()} disabled={busyId === "telegram-save"}>
                {busyId === "telegram-save" ? "Saving..." : telegramChannel ? "Update Telegram" : "Connect Telegram"}
              </Button>
              <Button variant="secondary" onClick={() => void handleTelegramTest()} disabled={busyId === "telegram-test"}>
                {busyId === "telegram-test" ? "Testing..." : "Test connection"}
              </Button>
              {telegramChannel ? (
                <Button
                  variant="ghost"
                  onClick={() => void handleTelegramToggle(!telegramChannel.enabled)}
                  disabled={busyId === "telegram-toggle"}
                >
                  {telegramChannel.enabled ? "Disable" : "Enable"}
                </Button>
              ) : null}
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Status</div>
                <div className="mt-2 text-[15px] font-semibold text-[var(--text-primary)]">{telegramChannel?.status || "disconnected"}</div>
              </div>
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Received</div>
                <div className="mt-2 text-[15px] font-semibold text-[var(--text-primary)]">{telegramChannel?.messageMetrics?.received || 0}</div>
              </div>
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Sent</div>
                <div className="mt-2 text-[15px] font-semibold text-[var(--text-primary)]">{telegramChannel?.messageMetrics?.sent || 0}</div>
              </div>
            </div>

            {telegramMessage ? (
              <div className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-3 text-[13px] text-[var(--text-secondary)]">
                {telegramMessage}
              </div>
            ) : null}
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Other apps</div>
          <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
            Secondary connections
          </h2>
          <div className="mt-4 space-y-3">
            {primaryConnectors.map((connector) => {
              const connectorAccounts = accounts.filter((account) => account.provider === connector.provider).slice(0, 1);
              return (
                <div key={connector.connector} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-[14px] font-medium text-[var(--text-primary)]">{connector.label}</div>
                      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                        {connectorAccounts[0]?.displayName || connector.capabilities.slice(0, 2).join(" · ")}
                      </div>
                    </div>
                    <StatusBadge tone={connector.status === "connected" ? "success" : connector.status === "pending" ? "warning" : "info"}>
                      {connector.status}
                    </StatusBadge>
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" onClick={() => void handleConnect(connector.connector)} disabled={busyId === `connect:${connector.connector}`}>
                      {busyId === `connect:${connector.connector}` ? "Opening..." : connector.status === "connected" ? "Reconnect" : "Connect"}
                    </Button>
                    {connectorAccounts[0] ? (
                      <>
                        <Button variant="ghost" size="sm" onClick={() => void handleRefresh(connectorAccounts[0].accountId)} disabled={busyId === `refresh:${connectorAccounts[0].accountId}`}>
                          Refresh
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => void handleRevoke(connectorAccounts[0].accountId)} disabled={busyId === `revoke:${connectorAccounts[0].accountId}`}>
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
      </div>

      <Surface tone="card" className="p-6">
        <div className="flex items-center gap-3">
          <RefreshCw className="h-4 w-4 text-[var(--accent-primary)]" />
          <div>
            <div className="text-[13px] font-medium text-[var(--text-primary)]">Recent external actions</div>
            <div className="text-[11px] text-[var(--text-tertiary)]">Only the latest items stay visible</div>
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {traces.slice(0, 4).map((trace) => (
            <div key={trace.traceId} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[13px] font-medium text-[var(--text-primary)]">{trace.connectorName}</div>
                <StatusBadge tone={trace.success ? "success" : "warning"}>{trace.status}</StatusBadge>
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{trace.operation}</div>
            </div>
          ))}
          {!traces.length ? (
            <div className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4 text-[13px] text-[var(--text-secondary)]">
              Henüz kayıtlı harici işlem yok.
            </div>
          ) : null}
        </div>
        {telegramChannel?.connected ? (
          <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-[var(--accent-soft)] px-3 py-2 text-[12px] font-medium text-[var(--accent-primary)]">
            <CheckCircle2 className="h-4 w-4" />
            Telegram runtime ile aktif
          </div>
        ) : null}
      </Surface>
    </div>
  );
}
