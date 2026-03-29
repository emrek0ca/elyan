import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, MessageCircle } from "lucide-react";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useChannels, useChannelsCatalog } from "@/hooks/use-desktop-data";
import { runtimeManager } from "@/runtime/runtime-manager";
import { testChannel, toggleChannel, upsertChannel } from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import { getRuntimeGateReason, hasRuntimeWriteAccess } from "@/utils/runtime-access";

export function IntegrationsScreen() {
  const queryClient = useQueryClient();
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);
  const runtimeReady = hasRuntimeWriteAccess(connectionState, sidecarHealth);
  const runtimeGateReason = getRuntimeGateReason(connectionState, sidecarHealth);
  const { data: channels = [] } = useChannels();
  const { data: channelCatalog = [] } = useChannelsCatalog();
  const [busyId, setBusyId] = useState("");
  const [telegramToken, setTelegramToken] = useState("");
  const [message, setMessage] = useState("");

  const telegramChannel = channels.find((item) => item.type === "telegram");
  const telegramCatalogEntry = channelCatalog.find((item) => item.type === "telegram");

  async function syncViews() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["channels"] }),
      queryClient.invalidateQueries({ queryKey: ["channels-catalog"] }),
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

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="max-w-[760px] px-8 py-10">
        <div className="max-w-[560px] space-y-2">
          <h1 className="font-display text-[38px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">Telegram</h1>
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

          <div className="text-[13px] text-[var(--text-secondary)]">Status: {telegramChannel?.status || "disconnected"}</div>

          {message ? <div className="text-[12px] text-[var(--text-secondary)]">{message}</div> : null}
          {!message && !runtimeReady ? <div className="text-[12px] text-[var(--text-secondary)]">{runtimeGateReason}</div> : null}
        </div>
      </Surface>

      <Button variant="ghost" onClick={() => void runtimeManager.openExternalUrl("https://elyan.dev")} disabled={busyId !== ""}>
        elyan.dev
        <ExternalLink className="ml-2 h-4 w-4" />
      </Button>
    </div>
  );
}
