import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Coins, Ticket, UsersRound } from "@/vendor/lucide-react";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import {
  useAdminWorkspaceDetail,
  useAdminWorkspaces,
  useBillingCatalog,
  useBillingEvents,
  useBillingWorkspace,
  useCreditLedger,
  useLearningSummary,
  useWorkspaceMembers,
} from "@/hooks/use-desktop-data";
import { assignWorkspaceSeat, getBillingCheckout, purchaseTokenPack } from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";

function formatResetLabel(timestamp?: number) {
  if (!timestamp || timestamp <= 0) {
    return "Yok";
  }
  return new Date(timestamp * 1000).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function AdminScreen() {
  const queryClient = useQueryClient();
  const [billingMessage, setBillingMessage] = useState("");
  const [workspaceBusyId, setWorkspaceBusyId] = useState("");
  const { data: billing } = useBillingWorkspace();
  const { data: adminWorkspaces = [] } = useAdminWorkspaces();
  const primaryWorkspaceId = adminWorkspaces[0]?.workspaceId || billing?.workspaceId || "";
  const { data: workspaceDetail } = useAdminWorkspaceDetail(primaryWorkspaceId);
  const { data: workspaceMembers = [] } = useWorkspaceMembers(primaryWorkspaceId);
  const { data: billingCatalog } = useBillingCatalog();
  const { data: creditLedger = [] } = useCreditLedger(10);
  const { data: billingEvents = [] } = useBillingEvents(10);
  const { data: learning } = useLearningSummary();
  const canManageSeats = Boolean(workspaceDetail?.permissions.manageSeats);
  const billingControlsReady = Boolean(
    billing?.checkoutUrl ||
    billing?.portalUrl ||
    billing?.activeCheckout?.launchUrl ||
    billing?.billingCustomer,
  );

  async function invalidateBillingViews() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["billing-workspace"] }),
      queryClient.invalidateQueries({ queryKey: ["billing-profile"] }),
      queryClient.invalidateQueries({ queryKey: ["credit-ledger"] }),
      queryClient.invalidateQueries({ queryKey: ["billing-events"] }),
      queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
      queryClient.invalidateQueries({ queryKey: ["cowork-home"] }),
      queryClient.invalidateQueries({ queryKey: ["admin-workspace", primaryWorkspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["workspace-members", primaryWorkspaceId] }),
      queryClient.invalidateQueries({ queryKey: ["admin-workspaces"] }),
    ]);
  }

  async function handleSeatToggle(actorId: string, assigned: boolean) {
    setWorkspaceBusyId(`seat:${actorId}`);
    setBillingMessage("");
    try {
      await assignWorkspaceSeat({
        workspaceId: primaryWorkspaceId,
        actorId,
        action: assigned ? "release" : "assign",
      });
      await invalidateBillingViews();
      setBillingMessage(assigned ? "Seat birakildi." : "Seat atandi.");
    } catch (error) {
      setBillingMessage(error instanceof Error ? error.message : "Seat islemi basarisiz.");
    } finally {
      setWorkspaceBusyId("");
    }
  }

  async function pollCheckout(referenceId: string) {
    if (!referenceId) {
      return;
    }
    for (let attempt = 0; attempt < 90; attempt += 1) {
      const checkout = await getBillingCheckout(referenceId).catch(() => null);
      if (checkout?.status === "completed") {
        await invalidateBillingViews();
        setBillingMessage("Odeme tamamlandi. Bakiye guncellendi.");
        return;
      }
      if (checkout?.status === "failed") {
        await invalidateBillingViews();
        setBillingMessage("Odeme tamamlanmadi.");
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }
  }

  async function openTokenPack(packId: string) {
    setBillingMessage("");
    try {
      const checkout = await purchaseTokenPack(packId);
      if (checkout.launchUrl) {
        await runtimeManager.openExternalUrl(checkout.launchUrl);
        void pollCheckout(checkout.referenceId);
      }
    } catch (error) {
      setBillingMessage(error instanceof Error ? error.message : "Checkout baslatilamadi.");
    }
  }

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-8 py-10">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="space-y-3">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Admin</div>
            <h1 className="font-display text-[32px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
              Workspace billing control
            </h1>
            <div className="text-[14px] leading-7 text-[var(--text-secondary)]">
              Plan, bakiye, uyeler ve son billing hareketleri tek ekranda.
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Workspace</div>
              <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">
                {workspaceDetail?.workspace.name || adminWorkspaces[0]?.displayName || "Local workspace"}
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{primaryWorkspaceId || "local-workspace"}</div>
            </div>
            <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Plan</div>
              <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">{billing?.plan.label || "Free"}</div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{billing?.subscriptionState.status || "inactive"}</div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">Reset: {formatResetLabel(billing?.resetAt || billing?.creditBalance?.resetAt)}</div>
            </div>
            <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Credits</div>
              <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">
                {(billing?.creditBalance?.total || 0).toLocaleString("tr-TR")}
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                included {(billing?.creditBalance?.included || 0).toLocaleString("tr-TR")} · purchased {(billing?.creditBalance?.purchased || 0).toLocaleString("tr-TR")}
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                recent {(billing?.recentUsageSummary?.requests || billing?.usageSummary?.requests || 0).toLocaleString("tr-TR")} request · top source {billing?.topCostSources?.[0]?.source || "—"}
              </div>
            </div>
            <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Seats</div>
              <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">
                {(workspaceDetail?.seats.seatsUsed || 0).toLocaleString("tr-TR")}/{(workspaceDetail?.seats.seatLimit || billing?.seats || 1).toLocaleString("tr-TR")}
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                available {(workspaceDetail?.seats.seatsAvailable || 0).toLocaleString("tr-TR")} · manage {canManageSeats ? "on" : "off"}
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                {workspaceDetail?.seats.assignments?.length ? `${workspaceDetail.seats.assignments.length} active assignment` : "No active assignment"}
              </div>
            </div>
          </div>
        </div>
      </Surface>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <Surface tone="card" className="p-6">
          <div className="flex items-center gap-2">
            <Coins className="h-4 w-4 text-[var(--accent-primary)]" />
            <div className="text-[13px] font-medium text-[var(--text-primary)]">Learning pulse</div>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Mode</div>
              <div className="mt-2 text-[16px] font-semibold text-[var(--text-primary)]">{learning?.learningMode || "adaptive"}</div>
            </div>
            <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Success rate</div>
              <div className="mt-2 text-[16px] font-semibold text-[var(--text-primary)]">
                {typeof learning?.successRate === "number" ? `${Math.round(learning.successRate * 100)}%` : "-"}
              </div>
            </div>
            <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Signals</div>
              <div className="mt-2 text-[16px] font-semibold text-[var(--text-primary)]">{learning?.signalCount || 0}</div>
            </div>
          </div>
          <div className="mt-4 rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4">
            <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Prompt hint</div>
            <div className="mt-2 text-[13px] leading-6 text-[var(--text-secondary)]">{learning?.promptHint || "Tool ve model basarilari burada birikiyor."}</div>
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <div className="flex items-center gap-2">
            <UsersRound className="h-4 w-4 text-[var(--accent-primary)]" />
            <div className="text-[13px] font-medium text-[var(--text-primary)]">Members</div>
          </div>
          <div className="mt-4 space-y-3">
            {workspaceMembers.length ? (
              workspaceMembers.map((member) => (
                <div key={member.actorId} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">
                        {member.user?.displayName || member.user?.email || member.actorId}
                      </div>
                      <div className="mt-1 text-[11px] text-[var(--text-secondary)]">{member.user?.email || member.actorId}</div>
                    </div>
                    <StatusBadge tone={member.role === "owner" ? "info" : member.role === "operator" ? "success" : "neutral"}>
                      {member.role}
                    </StatusBadge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => void handleSeatToggle(member.actorId, member.seatAssigned)}
                      disabled={!canManageSeats || workspaceBusyId === `seat:${member.actorId}`}
                    >
                      {workspaceBusyId === `seat:${member.actorId}` ? "Bekle..." : member.seatAssigned ? "Birak" : "Ata"}
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                Uye bulunamadi.
              </div>
            )}
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <div className="flex items-center gap-2">
            <Ticket className="h-4 w-4 text-[var(--accent-primary)]" />
            <div className="text-[13px] font-medium text-[var(--text-primary)]">Token packs</div>
          </div>
          {billing?.billingProfile && !billing.billingProfile.isComplete ? (
            <div className="mt-3 rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3 text-[12px] text-[var(--text-secondary)]">
              Billing profile eksik. Once Settings ekranindan profile alanlarini tamamlayin.
            </div>
          ) : null}
          <div className="mt-4 space-y-3">
            {billingControlsReady ? (
              (billingCatalog?.tokenPacks || []).map((pack) => (
                <div key={pack.id} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">{pack.label}</div>
                      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                        {pack.credits.toLocaleString("tr-TR")} credits · {pack.price.toLocaleString("tr-TR")} {pack.currency}
                      </div>
                    </div>
                    <Button variant="secondary" size="sm" onClick={() => void openTokenPack(pack.id)}>
                      Buy
                    </Button>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                Billing aktif değil. Satın alma yüzeyini gizledim.
              </div>
            )}
          </div>
          {billingMessage ? <div className="mt-4 text-[12px] text-[var(--text-secondary)]">{billingMessage}</div> : null}
        </Surface>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <Surface tone="card" className="p-6">
          <div className="flex items-center gap-2">
            <Coins className="h-4 w-4 text-[var(--accent-primary)]" />
            <div className="text-[13px] font-medium text-[var(--text-primary)]">Recent billing events</div>
          </div>
          <div className="mt-4 space-y-3">
            {billingEvents.length ? (
              billingEvents.slice(0, 10).map((event) => (
                <div key={event.eventId} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">{event.eventType}</div>
                      <div className="mt-1 text-[11px] text-[var(--text-secondary)]">{event.createdAt}</div>
                    </div>
                    <div className="text-right text-[12px] text-[var(--text-secondary)]">{event.referenceId || event.provider}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                Billing event yok.
              </div>
            )}
          </div>
        </Surface>

        <Surface tone="card" className="p-6">
          <div className="flex items-center gap-2">
            <Coins className="h-4 w-4 text-[var(--accent-primary)]" />
            <div className="text-[13px] font-medium text-[var(--text-primary)]">Recent credit ledger</div>
          </div>
          <div className="mt-4 space-y-3">
            {creditLedger.length ? (
              creditLedger.slice(0, 10).map((entry) => (
                <div key={entry.entryId} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">{entry.entryType} · {entry.bucket}</div>
                      <div className="mt-1 text-[11px] text-[var(--text-secondary)]">{entry.createdAt}</div>
                    </div>
                    <div className="text-right">
                      <div className={`text-[13px] font-semibold ${entry.deltaCredits >= 0 ? "text-[var(--state-success)]" : "text-[var(--state-warning)]"}`}>
                        {entry.deltaCredits >= 0 ? "+" : ""}{entry.deltaCredits}
                      </div>
                      <div className="text-[11px] text-[var(--text-secondary)]">balance {entry.balanceAfter}</div>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                Credit hareketi yok.
              </div>
            )}
          </div>
        </Surface>
      </div>
    </div>
  );
}
