import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Coins, Crown, CreditCard, MailPlus, RefreshCw, ShieldCheck, Sparkles, Ticket, UsersRound } from "@/vendor/lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/primitives/Button";
import { SearchField } from "@/components/primitives/SearchField";
import { SegmentedControl } from "@/components/primitives/SegmentedControl";
import { ToggleSwitch } from "@/components/primitives/ToggleSwitch";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import {
  useAdminWorkspaceDetail,
  useAdminWorkspaces,
  useBillingCatalog,
  useBillingEvents,
  useBillingProfile,
  useBillingWorkspace,
  useCreditLedger,
  useLearningSummary,
  usePrivacySummary,
  useSystemReadiness,
  useWorkspaceInvites,
  useWorkspaceMembers,
} from "@/hooks/use-desktop-data";
import {
  assignWorkspaceSeat,
  createCheckoutSession,
  createPortalSession,
  createWorkspaceInvite,
  deletePrivacyData,
  exportPrivacyData,
  getBillingCheckout,
  logoutLocalUser,
  purchaseTokenPack,
  saveBillingProfile,
  updateWorkspaceRole,
} from "@/services/api/elyan-service";
import { runtimeManager } from "@/runtime/runtime-manager";
import { useRuntimeStore } from "@/stores/runtime-store";
import { useUiStore } from "@/stores/ui-store";
import {
  automationLevelOptions,
  defaultProductSettings,
  privacyModeOptions,
  providerStrategyOptions,
  responseModeOptions,
  toneOptions,
} from "@/utils/product-settings";

function translateBillingError(raw: string): string {
  if (raw.startsWith("iyzico_plan_checkout_missing:") || raw.startsWith("iyzico_token_pack_checkout_missing:")) {
    return "Ödeme bağlantısı yapılandırılmamış. Lütfen sistem yöneticinize başvurun.";
  }
  if (raw.startsWith("iyzico_config_missing:")) {
    return "Ödeme sağlayıcısı yapılandırılmamış (API anahtarları eksik).";
  }
  if (raw.startsWith("billing_profile_incomplete:")) {
    return "Fatura profili tamamlanmamış. Lütfen fatura bilgilerini doldurun.";
  }
  if (raw.includes("503") || raw.toLowerCase().includes("unavailable")) {
    return "Ödeme servisi şu an kullanılamıyor. Lütfen tekrar deneyin.";
  }
  return raw;
}

const roleOptions = [
  { value: "owner", label: "Owner" },
  { value: "billing_admin", label: "Billing" },
  { value: "security_admin", label: "Security" },
  { value: "operator", label: "Operator" },
  { value: "viewer", label: "Viewer" },
];

export function SettingsScreen() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [runtimeBusy, setRuntimeBusy] = useState<"restart" | null>(null);
  const [billingBusy, setBillingBusy] = useState<"checkout" | "portal" | "pack" | null>(null);
  const [billingProfileBusy, setBillingProfileBusy] = useState(false);
  const [billingMessage, setBillingMessage] = useState("");
  const [privacyBusy, setPrivacyBusy] = useState<"export" | "delete" | null>(null);
  const [workspaceBusyId, setWorkspaceBusyId] = useState("");
  const [workspaceMessage, setWorkspaceMessage] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("operator");
  const [memberFilter, setMemberFilter] = useState("");
  const { data: learning } = useLearningSummary();
  const { data: privacy } = usePrivacySummary();
  const { data: billing } = useBillingWorkspace();
  const { data: billingProfile } = useBillingProfile();
  const { data: readiness } = useSystemReadiness();
  const { data: adminWorkspaces = [] } = useAdminWorkspaces();
  const primaryWorkspaceId = adminWorkspaces[0]?.workspaceId || billing?.workspaceId || "";
  const { data: workspaceDetail } = useAdminWorkspaceDetail(primaryWorkspaceId);
  const { data: workspaceMembers = [] } = useWorkspaceMembers(primaryWorkspaceId);
  const { data: workspaceInvites = [] } = useWorkspaceInvites(primaryWorkspaceId);
  const { data: billingCatalog } = useBillingCatalog();
  const { data: creditLedger = [] } = useCreditLedger(24);
  const { data: billingEvents = [] } = useBillingEvents(16);
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);
  const themeMode = useUiStore((state) => state.themeMode);
  const setThemeMode = useUiStore((state) => state.setThemeMode);
  const compactLogs = useUiStore((state) => state.compactLogs);
  const setCompactLogs = useUiStore((state) => state.setCompactLogs);
  const reduceMotion = useUiStore((state) => state.reduceMotion);
  const setReduceMotion = useUiStore((state) => state.setReduceMotion);
  const productSettings = useUiStore((state) => state.productSettings);
  const setProductSettings = useUiStore((state) => state.setProductSettings);
  const authenticatedEmail = useUiStore((state) => state.authenticatedEmail);
  const signOut = useUiStore((state) => state.signOut);
  const clearSelectedThreadId = useUiStore((state) => state.clearSelectedThreadId);
  const clearSelectedRunId = useUiStore((state) => state.clearSelectedRunId);
  const [billingProfileForm, setBillingProfileForm] = useState({
    fullName: "",
    email: "",
    phone: "",
    identityNumber: "",
    addressLine1: "",
    city: "",
    zipCode: "",
    country: "",
  });
  const pollingRef = useRef<boolean>(false);

  useEffect(() => {
    if (!billingProfile) {
      return;
    }
    setBillingProfileForm({
      fullName: billingProfile.profile.fullName,
      email: billingProfile.profile.email,
      phone: billingProfile.profile.phone,
      identityNumber: billingProfile.profile.identityNumber,
      addressLine1: billingProfile.profile.addressLine1,
      city: billingProfile.profile.city,
      zipCode: billingProfile.profile.zipCode,
      country: billingProfile.profile.country,
    });
  }, [billingProfile?.updatedAt]);

  const filteredMembers = useMemo(() => {
    const needle = memberFilter.trim().toLowerCase();
    if (!needle) {
      return workspaceMembers;
    }
    return workspaceMembers.filter((member) =>
      [member.user?.displayName || "", member.user?.email || "", member.role].some((value) => value.toLowerCase().includes(needle)),
    );
  }, [memberFilter, workspaceMembers]);

  const permissions = workspaceDetail?.permissions;
  const canManageMembers = Boolean(permissions?.manageMembers);
  const canManageRoles = Boolean(permissions?.manageRoles);
  const canManageSeats = Boolean(permissions?.manageSeats);
  const activeSeats = workspaceDetail?.seats.seatsUsed || 0;
  const seatLimit = workspaceDetail?.seats.seatLimit || billing?.entitlements.teamSeats || 0;

  async function invalidateControlPlane() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["admin-workspaces"] }),
      queryClient.invalidateQueries({ queryKey: ["admin-workspace"] }),
      queryClient.invalidateQueries({ queryKey: ["workspace-members"] }),
      queryClient.invalidateQueries({ queryKey: ["workspace-invites"] }),
      queryClient.invalidateQueries({ queryKey: ["billing-workspace"] }),
      queryClient.invalidateQueries({ queryKey: ["billing-profile"] }),
      queryClient.invalidateQueries({ queryKey: ["billing-catalog"] }),
      queryClient.invalidateQueries({ queryKey: ["credit-ledger"] }),
      queryClient.invalidateQueries({ queryKey: ["billing-events"] }),
      queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
      queryClient.invalidateQueries({ queryKey: ["cowork-home"] }),
    ]);
  }

  async function restartRuntime() {
    setRuntimeBusy("restart");
    try {
      await runtimeManager.restartRuntime();
    } finally {
      setRuntimeBusy(null);
    }
  }

  async function pollCheckout(referenceId: string) {
    if (!referenceId) {
      return;
    }
    if (pollingRef.current) {
      return;
    }
    pollingRef.current = true;
    try {
      for (let attempt = 0; attempt < 90; attempt += 1) {
        const checkout = await getBillingCheckout(referenceId).catch(() => null);
        if (checkout?.status === "completed") {
          await invalidateControlPlane();
          setBillingMessage("Odeme tamamlandi. Bakiye guncellendi.");
          return;
        }
        if (checkout?.status === "failed") {
          await invalidateControlPlane();
          setBillingMessage("Odeme tamamlanmadi.");
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
    } finally {
      pollingRef.current = false;
    }
  }

  async function handleBillingProfileSave() {
    setBillingProfileBusy(true);
    setBillingMessage("");
    try {
      await saveBillingProfile(billingProfileForm);
      await invalidateControlPlane();
      setBillingMessage("Billing profile kaydedildi.");
    } catch (error) {
      setBillingMessage(error instanceof Error ? error.message : "Billing profile kaydedilemedi.");
    } finally {
      setBillingProfileBusy(false);
    }
  }

  async function openCheckout(planId: string) {
    setBillingBusy("checkout");
    setBillingMessage("");
    try {
      const checkout = await createCheckoutSession(planId);
      if (checkout.launchUrl) {
        await runtimeManager.openExternalUrl(checkout.launchUrl);
        void pollCheckout(checkout.referenceId);
      }
    } catch (error) {
      const raw = error instanceof Error ? error.message : "Checkout baslatilamadi.";
      setBillingMessage(translateBillingError(raw));
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

  async function openTokenPack(packId: string) {
    setBillingBusy("pack");
    setBillingMessage("");
    try {
      const checkout = await purchaseTokenPack(packId);
      if (checkout.launchUrl) {
        await runtimeManager.openExternalUrl(checkout.launchUrl);
        void pollCheckout(checkout.referenceId);
      }
    } catch (error) {
      const raw = error instanceof Error ? error.message : "Token pack checkout baslatilamadi.";
      setBillingMessage(translateBillingError(raw));
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

  async function handleInviteCreate() {
    if (!primaryWorkspaceId || !inviteEmail.trim()) {
      setWorkspaceMessage("Davet icin e-posta gerekli.");
      return;
    }
    setWorkspaceBusyId("invite");
    setWorkspaceMessage("");
    try {
      await createWorkspaceInvite({
        workspaceId: primaryWorkspaceId,
        email: inviteEmail.trim().toLowerCase(),
        role: inviteRole,
      });
      setInviteEmail("");
      await invalidateControlPlane();
      setWorkspaceMessage("Invite olusturuldu.");
    } catch (error) {
      setWorkspaceMessage(error instanceof Error ? error.message : "Invite olusturulamadi.");
    } finally {
      setWorkspaceBusyId("");
    }
  }

  async function handleRoleUpdate(actorId: string, role: string) {
    setWorkspaceBusyId(`role:${actorId}`);
    setWorkspaceMessage("");
    try {
      await updateWorkspaceRole({ workspaceId: primaryWorkspaceId, actorId, role });
      await invalidateControlPlane();
      setWorkspaceMessage("Rol guncellendi.");
    } catch (error) {
      setWorkspaceMessage(error instanceof Error ? error.message : "Rol guncellenemedi.");
    } finally {
      setWorkspaceBusyId("");
    }
  }

  async function handleSeatToggle(actorId: string, assigned: boolean) {
    setWorkspaceBusyId(`seat:${actorId}`);
    setWorkspaceMessage("");
    try {
      await assignWorkspaceSeat({
        workspaceId: primaryWorkspaceId,
        actorId,
        action: assigned ? "release" : "assign",
      });
      await invalidateControlPlane();
      setWorkspaceMessage(assigned ? "Seat birakildi." : "Seat atandi.");
    } catch (error) {
      setWorkspaceMessage(error instanceof Error ? error.message : "Seat durumu guncellenemedi.");
    } finally {
      setWorkspaceBusyId("");
    }
  }

  return (
    <div className="space-y-6">
      <Surface tone="hero" className="px-8 py-10">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <div className="max-w-[760px] space-y-3">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Control plane</div>
            <h1 className="font-display text-[32px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">
              Workspace, billing ve operator ayarlari ayni panelde
            </h1>
            <div className="text-[14px] leading-7 text-[var(--text-secondary)]">
              Elyan’in satilabilir olmasi icin owner’in ekip, seat, kredi ve davranis ayarlarini yardimsiz yonetebilmesi gerekiyor.
              Bu ekran desktop icindeki ilk ticari control plane.
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Workspace</div>
              <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">
                {workspaceDetail?.workspace.name || adminWorkspaces[0]?.displayName || "Local workspace"}
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{workspaceDetail?.currentRole || adminWorkspaces[0]?.role || "owner"}</div>
            </div>
            <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Seats</div>
              <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">
                {activeSeats}/{seatLimit || billing?.seats || 1}
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{workspaceMembers.length} members visible</div>
            </div>
            <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">Credits</div>
              <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">
                {(billing?.creditBalance?.total || 0).toLocaleString("tr-TR")}
              </div>
              <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{billing?.plan.label || "Free"} · {billing?.subscriptionState.status || "inactive"}</div>
            </div>
          </div>
        </div>
      </Surface>

      <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
        <div className="space-y-6">
          <Surface tone="card" className="p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Workspace admin</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Team, roles and seats
                </h2>
              </div>
              <StatusBadge tone={permissions?.manageMembers ? "success" : "neutral"}>
                {permissions?.manageMembers ? "owner controls" : "read only"}
              </StatusBadge>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
              <div className="rounded-[22px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-5">
                <div className="flex items-center gap-2">
                  <MailPlus className="h-4 w-4 text-[var(--accent-primary)]" />
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Invite teammate</div>
                </div>
                <div className="mt-4 space-y-3">
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                    placeholder="teammate@company.com"
                    className="h-[48px] w-full rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                    disabled={!canManageMembers}
                  />
                  <SegmentedControl
                    value={inviteRole}
                    onChange={setInviteRole}
                    options={roleOptions.filter((item) => item.value !== "owner")}
                  />
                  <Button variant="primary" onClick={() => void handleInviteCreate()} disabled={!canManageMembers || workspaceBusyId === "invite"}>
                    {workspaceBusyId === "invite" ? "Sending..." : "Create invite"}
                  </Button>
                </div>
              </div>

              <div className="rounded-[22px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-5">
                <div className="flex items-center gap-2">
                  <UsersRound className="h-4 w-4 text-[var(--accent-primary)]" />
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Pending invites</div>
                </div>
                <div className="mt-4 space-y-3">
                  {workspaceInvites.length ? (
                    workspaceInvites.slice(0, 5).map((invite) => (
                      <div key={invite.inviteId} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-[13px] font-medium text-[var(--text-primary)]">{invite.email}</div>
                            <div className="mt-1 text-[11px] text-[var(--text-secondary)]">{invite.role} · {invite.status}</div>
                          </div>
                          <StatusBadge tone={invite.status === "pending" ? "warning" : "neutral"}>{invite.status}</StatusBadge>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                      Henuz bekleyen invite yok.
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-5">
              <SearchField
                value={memberFilter}
                onChange={(event) => setMemberFilter(event.target.value)}
                placeholder="Filter members by email, name or role"
                className="h-12 border-[var(--glass-border)] bg-[var(--glass-elevated)] shadow-none"
              />
            </div>

            <div className="mt-4 space-y-3">
              {filteredMembers.length ? (
                filteredMembers.map((member) => (
                  <div key={member.actorId} className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-4">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="truncate text-[14px] font-medium text-[var(--text-primary)]">
                          {member.user?.displayName || member.user?.email || member.actorId}
                        </div>
                        <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                          {member.user?.email || member.actorId} · {member.status}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge tone={member.seatAssigned ? "success" : "neutral"}>
                          {member.seatAssigned ? "seat assigned" : "no seat"}
                        </StatusBadge>
                        <StatusBadge tone={member.role === "owner" ? "info" : member.role === "operator" ? "success" : "neutral"}>
                          {member.role}
                        </StatusBadge>
                      </div>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      {roleOptions.map((option) => (
                        <Button
                          key={`${member.actorId}:${option.value}`}
                          variant={member.role === option.value ? "primary" : "ghost"}
                          size="sm"
                          onClick={() => void handleRoleUpdate(member.actorId, option.value)}
                          disabled={!canManageRoles || workspaceBusyId === `role:${member.actorId}` || member.role === option.value}
                        >
                          {option.label}
                        </Button>
                      ))}
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => void handleSeatToggle(member.actorId, member.seatAssigned)}
                        disabled={!canManageSeats || workspaceBusyId === `seat:${member.actorId}`}
                      >
                        {workspaceBusyId === `seat:${member.actorId}` ? "Updating..." : member.seatAssigned ? "Release seat" : "Assign seat"}
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-[20px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4 text-[13px] text-[var(--text-secondary)]">
                  Uygun uye bulunamadi.
                </div>
              )}
            </div>

            {workspaceMessage ? <div className="mt-4 text-[12px] text-[var(--text-secondary)]">{workspaceMessage}</div> : null}
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Commercial</div>
                <h2 className="mt-2 font-display text-[22px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Plans, token packs and credit ledger
                </h2>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge tone={billing?.plan.status === "active" ? "success" : "neutral"}>{billing?.plan.label || "Free"}</StatusBadge>
                <Button variant="secondary" size="sm" onClick={() => void openPortal()} disabled={billingBusy !== null}>
                  <CreditCard className="mr-2 h-4 w-4" />
                  Billing portal
                </Button>
              </div>
            </div>

            <div className="mt-5 grid gap-4 lg:grid-cols-3">
              <div className="rounded-[22px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-5 lg:col-span-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">Billing profile</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                      Gercek Iyzipay checkout icin bireysel fatura bilgileri gerekli.
                    </div>
                  </div>
                  <StatusBadge tone={billingProfile?.isComplete ? "success" : "warning"}>
                    {billingProfile?.isComplete ? "ready" : "required"}
                  </StatusBadge>
                </div>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <input
                    type="text"
                    value={billingProfileForm.fullName}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, fullName: event.target.value }))}
                    placeholder="Full name"
                    className="h-[48px] rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                  />
                  <input
                    type="email"
                    value={billingProfileForm.email}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, email: event.target.value }))}
                    placeholder="Email"
                    className="h-[48px] rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                  />
                  <input
                    type="text"
                    value={billingProfileForm.phone}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, phone: event.target.value }))}
                    placeholder="+90..."
                    className="h-[48px] rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                  />
                  <input
                    type="text"
                    value={billingProfileForm.identityNumber}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, identityNumber: event.target.value }))}
                    placeholder="Identity number"
                    className="h-[48px] rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                  />
                  <input
                    type="text"
                    value={billingProfileForm.addressLine1}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, addressLine1: event.target.value }))}
                    placeholder="Address"
                    className="h-[48px] rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)] md:col-span-2"
                  />
                  <input
                    type="text"
                    value={billingProfileForm.city}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, city: event.target.value }))}
                    placeholder="City"
                    className="h-[48px] rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                  />
                  <input
                    type="text"
                    value={billingProfileForm.zipCode}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, zipCode: event.target.value }))}
                    placeholder="ZIP code"
                    className="h-[48px] rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]"
                  />
                  <input
                    type="text"
                    value={billingProfileForm.country}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, country: event.target.value }))}
                    placeholder="Country"
                    className="h-[48px] rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)] md:col-span-2"
                  />
                </div>
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <div className="text-[12px] text-[var(--text-secondary)]">
                    {billingProfile?.missingFields?.length
                      ? `Eksik alanlar: ${billingProfile.missingFields.join(", ")}`
                      : "Profile checkout icin hazir."}
                  </div>
                  <Button variant="secondary" size="sm" onClick={() => void handleBillingProfileSave()} disabled={billingProfileBusy}>
                    {billingProfileBusy ? "Saving..." : "Save profile"}
                  </Button>
                </div>
              </div>

              {(billingCatalog?.plans || []).map((plan) => (
                <div
                  key={plan.id}
                  className="rounded-[22px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-5"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-[14px] font-medium text-[var(--text-primary)]">{plan.label}</div>
                      <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{plan.monthlyCredits.toLocaleString("tr-TR")} monthly credits</div>
                    </div>
                    <StatusBadge tone={billing?.plan.id === plan.id ? "success" : "neutral"}>
                      {billing?.plan.id === plan.id ? "current" : `${plan.seats} seats`}
                    </StatusBadge>
                  </div>
                  <div className="mt-4 text-[12px] leading-6 text-[var(--text-secondary)]">
                    {plan.maxConnectors} connectors · {plan.seats} seats
                  </div>
                  <div className="mt-4">
                    <Button variant={billing?.plan.id === plan.id ? "secondary" : "primary"} size="sm" onClick={() => void openCheckout(plan.id)} disabled={billingBusy !== null}>
                      {billing?.plan.id === plan.id ? "Change plan" : "Upgrade"}
                    </Button>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-6 grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
              <div className="rounded-[22px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-5">
                <div className="flex items-center gap-2">
                  <Ticket className="h-4 w-4 text-[var(--accent-primary)]" />
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Top-up packs</div>
                </div>
                <div className="mt-4 space-y-3">
                  {(billingCatalog?.tokenPacks || []).map((pack) => (
                    <div key={pack.id} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[13px] font-medium text-[var(--text-primary)]">{pack.label}</div>
                          <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                            {pack.credits.toLocaleString("tr-TR")} credits · {pack.price.toLocaleString("tr-TR")} {pack.currency}
                          </div>
                        </div>
                        <Button variant="secondary" size="sm" onClick={() => void openTokenPack(pack.id)} disabled={billingBusy !== null}>
                          Buy
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-[22px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-5">
                <div className="flex items-center gap-2">
                  <Coins className="h-4 w-4 text-[var(--accent-primary)]" />
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Credit ledger</div>
                </div>
                <div className="mt-4 space-y-3">
                  {creditLedger.length ? (
                    creditLedger.slice(0, 8).map((entry) => (
                      <div key={entry.entryId} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="text-[13px] font-medium text-[var(--text-primary)]">
                              {entry.entryType} · {entry.bucket}
                            </div>
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
                      Henuz credit ledger hareketi yok.
                    </div>
                  )}
                </div>

                <div className="mt-5 border-t border-[var(--glass-border)] pt-5">
                  <div className="flex items-center gap-2">
                    <RefreshCw className="h-4 w-4 text-[var(--accent-primary)]" />
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">Billing events</div>
                  </div>
                  <div className="mt-4 space-y-3">
                    {billingEvents.length ? (
                      billingEvents.slice(0, 6).map((event) => (
                        <div key={event.eventId} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="text-[13px] font-medium text-[var(--text-primary)]">{event.eventType}</div>
                              <div className="mt-1 text-[11px] text-[var(--text-secondary)]">
                                {event.provider} · {event.referenceId || "no reference"} · {event.createdAt}
                              </div>
                            </div>
                            <StatusBadge tone={event.status === "applied" || event.status === "active" ? "success" : event.status === "pending" ? "warning" : "neutral"}>
                              {event.status}
                            </StatusBadge>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                        Henuz billing event akisi yok.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
            {billingMessage ? <div className="mt-4 text-[12px] text-[var(--text-secondary)]">{billingMessage}</div> : null}
          </Surface>
        </div>

        <div className="space-y-6">
          <Surface tone="card" className="p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Conversation</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  User-facing behavior
                </h2>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setProductSettings(defaultProductSettings)}>
                Reset
              </Button>
            </div>

            <div className="mt-5 space-y-5">
              <div className="space-y-2">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Response mode</div>
                <SegmentedControl
                  value={productSettings.responseMode}
                  onChange={(value) => setProductSettings({ responseMode: value as typeof productSettings.responseMode })}
                  options={responseModeOptions}
                />
              </div>
              <div className="space-y-2">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Tone</div>
                <SegmentedControl
                  value={productSettings.tone}
                  onChange={(value) => setProductSettings({ tone: value as typeof productSettings.tone })}
                  options={toneOptions}
                />
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Provider strategy</div>
                  <SegmentedControl
                    value={productSettings.providerStrategy}
                    onChange={(value) => setProductSettings({ providerStrategy: value as typeof productSettings.providerStrategy })}
                    options={providerStrategyOptions}
                  />
                </div>
                <div className="space-y-2">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Privacy mode</div>
                  <SegmentedControl
                    value={productSettings.privacyMode}
                    onChange={(value) => setProductSettings({ privacyMode: value as typeof productSettings.privacyMode })}
                    options={privacyModeOptions}
                  />
                </div>
                <div className="space-y-2">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Automation level</div>
                  <SegmentedControl
                    value={productSettings.automationLevel}
                    onChange={(value) => setProductSettings({ automationLevel: value as typeof productSettings.automationLevel })}
                    options={automationLevelOptions}
                  />
                </div>
              </div>
            </div>
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Desktop</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Shell and diagnostics
                </h2>
              </div>
              <StatusBadge tone={readiness?.status === "ready" ? "success" : readiness?.status === "booting" ? "warning" : "error"}>
                {readiness?.status || connectionState}
              </StatusBadge>
            </div>

            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-4">
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
              <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-4">
                <div className="text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Behavior</div>
                <div className="mt-4 space-y-3">
                  <ToggleSwitch label="Compact logs" checked={compactLogs} onChange={setCompactLogs} />
                  <ToggleSwitch label="Reduce motion" checked={reduceMotion} onChange={setReduceMotion} />
                </div>
              </div>
            </div>

            <div className="mt-5 flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => void restartRuntime()} disabled={runtimeBusy !== null}>
                <RefreshCw className="mr-2 h-4 w-4" />
                {runtimeBusy === "restart" ? "Restarting..." : "Restart local services"}
              </Button>
              <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-3 text-[12px] text-[var(--text-secondary)]">
                {sidecarHealth.runtimeVersion || "runtime"} · {readiness?.blockingIssue || "Ready for operator work"}
              </div>
            </div>
          </Surface>

          <Surface tone="card" className="p-6">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Privacy</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">
                  Data and learning
                </h2>
              </div>
              {learning ? (
                <StatusBadge tone={learning.paused ? "warning" : learning.optOut ? "neutral" : "success"}>
                  {learning.paused ? "paused" : learning.optOut ? "off" : "learning"}
                </StatusBadge>
              ) : null}
            </div>
            <div className="mt-5 rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-4 text-[13px] leading-6 text-[var(--text-secondary)]">
              <div className="flex items-center gap-2 text-[14px] font-medium text-[var(--text-primary)]">
                <ShieldCheck className="h-4 w-4 text-[var(--accent-primary)]" />
                {learning?.learningMode || "local"} · {privacy?.policy.learningScope || "workspace"}
              </div>
              <div className="mt-2">
                {privacy ? `${privacy.totalEntries} entries · ${privacy.redactedEntries} redacted` : "Privacy summary unavailable."}
              </div>
              <div>{privacy?.whatIsLearned?.length ? `Learns: ${privacy.whatIsLearned.join(", ")}` : "Learns redacted operational signals."}</div>
            </div>
            <div className="mt-4 flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => void handleExportPrivacy()} disabled={privacyBusy !== null}>
                {privacyBusy === "export" ? "Exporting..." : "Export data"}
              </Button>
              <Button variant="ghost" onClick={() => void handleDeletePrivacy()} disabled={privacyBusy !== null}>
                {privacyBusy === "delete" ? "Deleting..." : "Delete data"}
              </Button>
            </div>
          </Surface>

          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Account</div>
                <div className="mt-2 truncate text-[14px] font-medium text-[var(--text-primary)]">
                  {authenticatedEmail || "Signed in"}
                </div>
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                  {workspaceDetail?.workspace.name || "Local workspace"} · {billing?.plan.label || "Free plan"}
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => void openPortal()} disabled={billingBusy !== null}>
                  <ArrowUpRight className="mr-2 h-4 w-4" />
                  Billing
                </Button>
                <Button variant="ghost" onClick={() => void finalizeLocalSessionExit()}>
                  Sign out
                </Button>
              </div>
            </div>
          </Surface>
        </div>
      </div>
    </div>
  );
}
