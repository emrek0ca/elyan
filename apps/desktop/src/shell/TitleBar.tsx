import { Search } from "@/vendor/lucide-react";
import { useLocation } from "react-router-dom";

import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useSystemReadiness } from "@/hooks/use-desktop-data";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";

const routeLabels: Record<string, string> = {
  "/home": "Elyan",
  "/stack": "Stack",
  "/swarm": "Swarm",
  "/command-center": "İşler",
  "/providers": "Modeller",
  "/integrations": "Bağlantılar",
  "/admin": "Yönetim",
  "/settings": "Ayarlar",
  "/logs": "Loglar",
};

export function TitleBar() {
  const location = useLocation();
  const { data: readiness } = useSystemReadiness();
  const openCommandPalette = useUiStore((s) => s.openCommandPalette);
  const authenticatedEmail = useUiStore((s) => s.authenticatedEmail);
  const connectionState = useRuntimeStore((s) => s.connectionState);
  const routeLabel = routeLabels[location.pathname] || "Elyan";
  const isReady = readiness?.status === "ready";

  return (
    <header className="eylan-titlebar flex items-center justify-between gap-4">
      <div className="eylan-mac-offset flex items-center gap-3">
        <span className="text-[14px] font-medium text-[var(--text-primary)]">{routeLabel}</span>
        <StatusBadge tone={isReady ? "success" : connectionState === "connected" ? "info" : "warning"}>
          {isReady ? "ready" : connectionState === "connected" ? "booting" : "offline"}
        </StatusBadge>
      </div>

      <button
        type="button"
        onClick={() => openCommandPalette()}
        className="hidden min-w-[260px] items-center gap-3 rounded-[10px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-2 text-left text-[13px] text-[var(--text-tertiary)] transition hover:border-[var(--glass-border-strong)] hover:bg-[var(--bg-surface)] xl:flex"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="flex-1">Ara</span>
        <kbd className="rounded-[6px] border border-[var(--glass-border)] px-1.5 py-0.5 text-[10px]">⌘K</kbd>
      </button>

      <div className="flex items-center gap-2">
        <span className="max-w-[160px] truncate text-[12px] text-[var(--text-secondary)]">
          {authenticatedEmail || "local"}
        </span>
      </div>
    </header>
  );
}
