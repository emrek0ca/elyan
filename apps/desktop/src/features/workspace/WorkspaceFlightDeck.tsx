import { MessageSquareShare, ShieldCheck, Sparkles, UsersRound, Wallet } from "@/vendor/lucide-react";

import { StatusBadge } from "@/components/primitives/StatusBadge";
import type { WorkspaceAdminDetail, WorkspaceAdminSummary, WorkspaceBillingSummary } from "@/types/domain";

type Props = {
  workspace?: WorkspaceAdminSummary | WorkspaceAdminDetail["workspace"] | null;
  workspaceRole?: string;
  seats?: WorkspaceAdminSummary["seats"] | null;
  billing?: WorkspaceBillingSummary | null;
  memberCount?: number;
  connectedMessagingCount?: number;
  messagingCatalogCount?: number;
  providerReadyCount?: number;
  runtimeReady?: boolean;
  onPrimaryAction?: () => void;
  onSecondaryAction?: () => void;
  primaryLabel?: string;
  secondaryLabel?: string;
};

export function WorkspaceFlightDeck({
  workspace,
  workspaceRole,
  seats,
  billing,
  memberCount = 0,
  connectedMessagingCount = 0,
  messagingCatalogCount = 0,
  providerReadyCount = 0,
  runtimeReady = false,
}: Props) {
  const label = workspace && "displayName" in workspace ? workspace.displayName : workspace?.name || "Workspace";
  const seatLimit = seats?.seatLimit || billing?.entitlements.teamSeats || 1;
  const seatUsed = seats?.seatsUsed || 0;
  const credits = billing?.creditBalance?.total ?? 0;

  const tiles = [
    { id: "rt", icon: ShieldCheck, label: "Runtime", value: runtimeReady ? "Hazır" : "Bekleniyor", ok: runtimeReady },
    { id: "ml", icon: Sparkles, label: "Modeller", value: providerReadyCount ? `${providerReadyCount}` : "—", ok: providerReadyCount > 0 },
    { id: "ch", icon: MessageSquareShare, label: "Kanallar", value: `${connectedMessagingCount}/${Math.max(messagingCatalogCount, 1)}`, ok: connectedMessagingCount > 0 },
    { id: "ws", icon: UsersRound, label: "Üyeler", value: `${memberCount || seatUsed}/${seatLimit}`, ok: seatUsed > 0 || memberCount > 0 },
  ] as const;

  return (
    <div className="rounded-[24px] border border-[var(--glass-border)] bg-[var(--glass-panel)] p-5 shadow-[var(--shadow-panel)] backdrop-blur-[22px]">
      {/* Header row */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-medium text-[var(--text-primary)]">{label}</span>
          <StatusBadge tone={workspace ? "success" : "warning"}>{workspaceRole || "setup"}</StatusBadge>
        </div>
        <div className="flex items-center gap-2 rounded-[14px] border border-[var(--glass-border-strong)] bg-[var(--glass-elevated)] px-3 py-2">
          <Wallet className="h-3.5 w-3.5 text-[var(--accent-primary)]" />
          <span className="text-[14px] font-semibold text-[var(--text-primary)]">{credits.toLocaleString("tr-TR")}</span>
          <span className="text-[11px] text-[var(--text-tertiary)]">{billing?.plan.label || "Free"}</span>
        </div>
      </div>

      {/* Tiles */}
      <div className="mt-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
        {tiles.map((t) => {
          const Icon = t.icon;
          return (
            <div key={t.id} className="flex items-center gap-3 rounded-[16px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-3 py-3">
              <Icon className="h-4 w-4 shrink-0 text-[var(--accent-primary)]" />
              <div className="min-w-0">
                <div className="text-[11px] text-[var(--text-tertiary)]">{t.label}</div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">{t.value}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
