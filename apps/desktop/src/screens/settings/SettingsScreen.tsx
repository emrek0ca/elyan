import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Coins, CreditCard, MailPlus, RefreshCw, ShieldCheck, Ticket, UsersRound } from "@/vendor/lucide-react";
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
    return "Odeme linki yok.";
  }
  if (raw.startsWith("iyzico_config_missing:")) {
    return "Odeme ayari eksik.";
  }
  if (raw.startsWith("billing_profile_incomplete:")) {
    return "Profil eksik.";
  }
  if (raw.includes("503") || raw.toLowerCase().includes("unavailable")) {
    return "Servis kapali.";
  }
  return raw;
}

const roleOptions = [
  { value: "owner", label: "Sahip" },
  { value: "billing_admin", label: "Fatura" },
  { value: "security_admin", label: "Guvenlik" },
  { value: "operator", label: "Operator" },
  { value: "viewer", label: "Izleyici" },
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
  const summaryCards = [
    {
      label: "Alan",
      value: workspaceDetail?.workspace.name || adminWorkspaces[0]?.displayName || "Local",
      meta: workspaceDetail?.currentRole || adminWorkspaces[0]?.role || "owner",
    },
    {
      label: "Seat",
      value: `${activeSeats}/${seatLimit || billing?.seats || 1}`,
      meta: `${workspaceMembers.length} uye`,
    },
    {
      label: "Kredi",
      value: (billing?.creditBalance?.total || 0).toLocaleString("tr-TR"),
      meta: `${billing?.plan.label || "Free"} · ${billing?.subscriptionState.status || "inactive"}`,
    },
  ];
  const conversationControls = [
    {
      label: "Yanit",
      value: productSettings.responseMode,
      options: responseModeOptions,
      onChange: (value: string) => setProductSettings({ responseMode: value as typeof productSettings.responseMode }),
    },
    {
      label: "Ton",
      value: productSettings.tone,
      options: toneOptions,
      onChange: (value: string) => setProductSettings({ tone: value as typeof productSettings.tone }),
    },
    {
      label: "Model",
      value: productSettings.providerStrategy,
      options: providerStrategyOptions,
      onChange: (value: string) => setProductSettings({ providerStrategy: value as typeof productSettings.providerStrategy }),
    },
    {
      label: "Gizlilik",
      value: productSettings.privacyMode,
      options: privacyModeOptions,
      onChange: (value: string) => setProductSettings({ privacyMode: value as typeof productSettings.privacyMode }),
    },
    {
      label: "Otonomi",
      value: productSettings.automationLevel,
      options: automationLevelOptions,
      onChange: (value: string) => setProductSettings({ automationLevel: value as typeof productSettings.automationLevel }),
    },
  ];
  const inputClassName =
    "h-[44px] w-full rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]";
  const panelClassName = "rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-4";

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
          setBillingMessage("Odeme tamam.");
          return;
        }
        if (checkout?.status === "failed") {
          await invalidateControlPlane();
          setBillingMessage("Odeme basarisiz.");
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
      setBillingMessage("Profil kayitli.");
    } catch (error) {
      setBillingMessage(error instanceof Error ? error.message : "Profil kaydedilemedi.");
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
      const raw = error instanceof Error ? error.message : "Odeme baslamadi.";
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
      const raw = error instanceof Error ? error.message : "Paket acilmadi.";
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
      setWorkspaceMessage("E-posta gerekli.");
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
      setWorkspaceMessage("Davet hazir.");
    } catch (error) {
      setWorkspaceMessage(error instanceof Error ? error.message : "Davet olmadi.");
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
      setWorkspaceMessage("Rol guncel.");
    } catch (error) {
      setWorkspaceMessage(error instanceof Error ? error.message : "Rol olmadi.");
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
      setWorkspaceMessage(error instanceof Error ? error.message : "Seat olmadi.");
    } finally {
      setWorkspaceBusyId("");
    }
  }

  return (
    <div className="space-y-5">
      <Surface tone="hero" className="px-6 py-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Ayarlar</div>
            <h1 className="font-display text-[30px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">Kontrol</h1>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {summaryCards.map((card) => (
              <div key={card.label} className={`${panelClassName} min-w-[170px] px-4 py-3`}>
                <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{card.label}</div>
                <div className="mt-2 text-[18px] font-semibold text-[var(--text-primary)]">{card.value}</div>
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{card.meta}</div>
              </div>
            ))}
          </div>
        </div>
      </Surface>

      <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <div className="space-y-5">
          <Surface tone="card" className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Ekip</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Uyeler</h2>
              </div>
              <StatusBadge tone={permissions?.manageMembers ? "success" : "neutral"}>
                {permissions?.manageMembers ? "Yonetim" : "Salt okur"}
              </StatusBadge>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
              <div className={panelClassName}>
                <div className="flex items-center gap-2">
                  <MailPlus className="h-4 w-4 text-[var(--accent-primary)]" />
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Davet</div>
                </div>
                <div className="mt-3 space-y-3">
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(event) => setInviteEmail(event.target.value)}
                    placeholder="mail@firma.com"
                    className={inputClassName}
                    disabled={!canManageMembers}
                  />
                  <SegmentedControl
                    value={inviteRole}
                    onChange={setInviteRole}
                    options={roleOptions.filter((item) => item.value !== "owner")}
                  />
                  <Button variant="primary" onClick={() => void handleInviteCreate()} disabled={!canManageMembers || workspaceBusyId === "invite"}>
                    {workspaceBusyId === "invite" ? "Bekle..." : "Gonder"}
                  </Button>
                </div>
              </div>

              <div className={panelClassName}>
                <div className="flex items-center gap-2">
                  <UsersRound className="h-4 w-4 text-[var(--accent-primary)]" />
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Bekleyen</div>
                </div>
                <div className="mt-3 space-y-3">
                  {workspaceInvites.length ? (
                    workspaceInvites.slice(0, 5).map((invite) => (
                      <div key={invite.inviteId} className="rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-[13px] font-medium text-[var(--text-primary)]">{invite.email}</div>
                            <div className="mt-1 text-[11px] text-[var(--text-secondary)]">{invite.role} · {invite.status}</div>
                          </div>
                          <StatusBadge tone={invite.status === "pending" ? "warning" : "neutral"}>{invite.status}</StatusBadge>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                      Bos
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-4">
              <SearchField
                value={memberFilter}
                onChange={(event) => setMemberFilter(event.target.value)}
                placeholder="Ara"
                className="h-11 border-[var(--glass-border)] bg-[var(--glass-elevated)] shadow-none"
              />
            </div>

            <div className="mt-4 space-y-3">
              {filteredMembers.length ? (
                filteredMembers.map((member) => (
                  <div key={member.actorId} className={panelClassName}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
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
                          {member.seatAssigned ? "Seat var" : "Seat yok"}
                        </StatusBadge>
                        <StatusBadge tone={member.role === "owner" ? "info" : member.role === "operator" ? "success" : "neutral"}>
                          {member.role}
                        </StatusBadge>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
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
                        {workspaceBusyId === `seat:${member.actorId}` ? "Bekle..." : member.seatAssigned ? "Birak" : "Ata"}
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <div className={`${panelClassName} text-[13px] text-[var(--text-secondary)]`}>Uye yok.</div>
              )}
            </div>

            {workspaceMessage ? <div className="mt-4 text-[12px] text-[var(--text-secondary)]">{workspaceMessage}</div> : null}
          </Surface>

          <Surface tone="card" className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Fatura</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Plan</h2>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge tone={billing?.plan.status === "active" ? "success" : "neutral"}>{billing?.plan.label || "Free"}</StatusBadge>
                <Button variant="secondary" size="sm" onClick={() => void openPortal()} disabled={billingBusy !== null}>
                  <CreditCard className="mr-2 h-4 w-4" />
                  Portal
                </Button>
              </div>
            </div>

            <div className="mt-4 space-y-4">
              <div className={panelClassName}>
                <div className="flex items-start justify-between gap-4">
                  <div className="text-[13px] font-medium text-[var(--text-primary)]">Profil</div>
                  <StatusBadge tone={billingProfile?.isComplete ? "success" : "warning"}>
                    {billingProfile?.isComplete ? "Hazir" : "Eksik"}
                  </StatusBadge>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <input
                    type="text"
                    value={billingProfileForm.fullName}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, fullName: event.target.value }))}
                    placeholder="Ad"
                    className={inputClassName}
                  />
                  <input
                    type="email"
                    value={billingProfileForm.email}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, email: event.target.value }))}
                    placeholder="Mail"
                    className={inputClassName}
                  />
                  <input
                    type="text"
                    value={billingProfileForm.phone}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, phone: event.target.value }))}
                    placeholder="+90"
                    className={inputClassName}
                  />
                  <input
                    type="text"
                    value={billingProfileForm.identityNumber}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, identityNumber: event.target.value }))}
                    placeholder="No"
                    className={inputClassName}
                  />
                  <input
                    type="text"
                    value={billingProfileForm.addressLine1}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, addressLine1: event.target.value }))}
                    placeholder="Adres"
                    className={`${inputClassName} md:col-span-2`}
                  />
                  <input
                    type="text"
                    value={billingProfileForm.city}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, city: event.target.value }))}
                    placeholder="Sehir"
                    className={inputClassName}
                  />
                  <input
                    type="text"
                    value={billingProfileForm.zipCode}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, zipCode: event.target.value }))}
                    placeholder="Posta"
                    className={inputClassName}
                  />
                  <input
                    type="text"
                    value={billingProfileForm.country}
                    onChange={(event) => setBillingProfileForm((current) => ({ ...current, country: event.target.value }))}
                    placeholder="Ulke"
                    className={`${inputClassName} md:col-span-2`}
                  />
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                  <div className="text-[12px] text-[var(--text-secondary)]">
                    {billingProfile?.missingFields?.length ? `Eksik: ${billingProfile.missingFields.join(", ")}` : "Hazir."}
                  </div>
                  <Button variant="secondary" size="sm" onClick={() => void handleBillingProfileSave()} disabled={billingProfileBusy}>
                    {billingProfileBusy ? "Bekle..." : "Kaydet"}
                  </Button>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                {(billingCatalog?.plans || []).map((plan) => (
                  <div key={plan.id} className={panelClassName}>
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-[14px] font-medium text-[var(--text-primary)]">{plan.label}</div>
                        <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{plan.monthlyCredits.toLocaleString("tr-TR")} kredi</div>
                      </div>
                      <StatusBadge tone={billing?.plan.id === plan.id ? "success" : "neutral"}>
                        {billing?.plan.id === plan.id ? "Aktif" : `${plan.seats} seat`}
                      </StatusBadge>
                    </div>
                    <div className="mt-3 text-[12px] text-[var(--text-secondary)]">
                      {plan.maxConnectors} baglanti · {plan.seats} seat
                    </div>
                    <div className="mt-3">
                      <Button variant={billing?.plan.id === plan.id ? "secondary" : "primary"} size="sm" onClick={() => void openCheckout(plan.id)} disabled={billingBusy !== null}>
                        {billing?.plan.id === plan.id ? "Degistir" : "Yukselt"}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="grid gap-4 lg:grid-cols-[0.95fr_1.05fr]">
                <div className={panelClassName}>
                  <div className="flex items-center gap-2">
                    <Ticket className="h-4 w-4 text-[var(--accent-primary)]" />
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">Paket</div>
                  </div>
                  <div className="mt-3 space-y-3">
                    {(billingCatalog?.tokenPacks || []).map((pack) => (
                      <div key={pack.id} className="rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-[13px] font-medium text-[var(--text-primary)]">{pack.label}</div>
                            <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                              {pack.credits.toLocaleString("tr-TR")} kredi · {pack.price.toLocaleString("tr-TR")} {pack.currency}
                            </div>
                          </div>
                          <Button variant="secondary" size="sm" onClick={() => void openTokenPack(pack.id)} disabled={billingBusy !== null}>
                            Al
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={panelClassName}>
                  <div className="flex items-center gap-2">
                    <Coins className="h-4 w-4 text-[var(--accent-primary)]" />
                    <div className="text-[13px] font-medium text-[var(--text-primary)]">Hareket</div>
                  </div>
                  <div className="mt-3 space-y-3">
                    {creditLedger.length ? (
                      creditLedger.slice(0, 8).map((entry) => (
                        <div key={entry.entryId} className="rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <div className="text-[13px] font-medium text-[var(--text-primary)]">
                                {entry.entryType} · {entry.bucket}
                              </div>
                              <div className="mt-1 text-[11px] text-[var(--text-secondary)]">{entry.createdAt}</div>
                            </div>
                            <div className="text-right">
                              <div className={`text-[13px] font-semibold ${entry.deltaCredits >= 0 ? "text-[var(--state-success)]" : "text-[var(--state-warning)]"}`}>
                                {entry.deltaCredits >= 0 ? "+" : ""}
                                {entry.deltaCredits}
                              </div>
                              <div className="text-[11px] text-[var(--text-secondary)]">bakiye {entry.balanceAfter}</div>
                            </div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                        Bos
                      </div>
                    )}
                  </div>

                  <div className="mt-4 border-t border-[var(--glass-border)] pt-4">
                    <div className="flex items-center gap-2">
                      <RefreshCw className="h-4 w-4 text-[var(--accent-primary)]" />
                      <div className="text-[13px] font-medium text-[var(--text-primary)]">Olay</div>
                    </div>
                    <div className="mt-3 space-y-3">
                      {billingEvents.length ? (
                        billingEvents.slice(0, 6).map((event) => (
                          <div key={event.eventId} className="rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-3">
                            <div className="flex items-start justify-between gap-3">
                              <div>
                                <div className="text-[13px] font-medium text-[var(--text-primary)]">{event.eventType}</div>
                                <div className="mt-1 text-[11px] text-[var(--text-secondary)]">
                                  {event.provider} · {event.referenceId || "ref yok"} · {event.createdAt}
                                </div>
                              </div>
                              <StatusBadge tone={event.status === "applied" || event.status === "active" ? "success" : event.status === "pending" ? "warning" : "neutral"}>
                                {event.status}
                              </StatusBadge>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-[16px] border border-[var(--glass-border)] bg-[var(--bg-surface)] px-4 py-4 text-[12px] text-[var(--text-secondary)]">
                          Bos
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {billingMessage ? <div className="mt-4 text-[12px] text-[var(--text-secondary)]">{billingMessage}</div> : null}
          </Surface>
        </div>

        <div className="space-y-5">
          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Davranis</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Akis</h2>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setProductSettings(defaultProductSettings)}>
                Sifirla
              </Button>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {conversationControls.map((control, index) => (
                <div key={control.label} className={`${panelClassName} ${index === conversationControls.length - 1 ? "md:col-span-2" : ""}`}>
                  <div className="mb-3 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">{control.label}</div>
                  <SegmentedControl value={control.value} onChange={control.onChange} options={control.options} />
                </div>
              ))}
            </div>
          </Surface>

          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Masaustu</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Runtime</h2>
              </div>
              <StatusBadge tone={readiness?.status === "ready" ? "success" : readiness?.status === "booting" ? "warning" : "error"}>
                {readiness?.status || connectionState}
              </StatusBadge>
            </div>

            <div className="mt-4 grid gap-3">
              <div className={panelClassName}>
                <div className="mb-3 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Tema</div>
                <SegmentedControl
                  value={themeMode}
                  onChange={(value) => setThemeMode(value as typeof themeMode)}
                  options={[
                    { value: "system", label: "Sistem" },
                    { value: "light", label: "Acik" },
                    { value: "dark", label: "Koyu" },
                  ]}
                />
              </div>

              <div className={panelClassName}>
                <div className="mb-3 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">Gorunum</div>
                <div className="space-y-3">
                  <ToggleSwitch label="Kompakt" checked={compactLogs} onChange={setCompactLogs} />
                  <ToggleSwitch label="Az hareket" checked={reduceMotion} onChange={setReduceMotion} />
                </div>
              </div>

              <div className={`${panelClassName} flex flex-wrap items-center justify-between gap-3`}>
                <div className="text-[12px] text-[var(--text-secondary)]">
                  {sidecarHealth.runtimeVersion || "runtime"} · {readiness?.blockingIssue || "Hazir"}
                </div>
                <Button variant="secondary" onClick={() => void restartRuntime()} disabled={runtimeBusy !== null}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  {runtimeBusy === "restart" ? "Bekle..." : "Yeniden baslat"}
                </Button>
              </div>
            </div>
          </Surface>

          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Gizlilik</div>
                <h2 className="mt-2 font-display text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Veri</h2>
              </div>
              {learning ? (
                <StatusBadge tone={learning.paused ? "warning" : learning.optOut ? "neutral" : "success"}>
                  {learning.paused ? "Durak" : learning.optOut ? "Kapali" : "Acik"}
                </StatusBadge>
              ) : null}
            </div>

            <div className={`${panelClassName} mt-4`}>
              <div className="flex items-center gap-2 text-[14px] font-medium text-[var(--text-primary)]">
                <ShieldCheck className="h-4 w-4 text-[var(--accent-primary)]" />
                {learning?.learningMode || "local"} · {privacy?.policy.learningScope || "workspace"}
              </div>
              <div className="mt-3 grid gap-2 text-[12px] text-[var(--text-secondary)]">
                <div>{privacy ? `${privacy.totalEntries} kayit` : "Kayit yok"}</div>
                <div>{privacy ? `${privacy.redactedEntries} redakte` : "Redakte yok"}</div>
                <div>{privacy?.whatIsLearned?.length ? privacy.whatIsLearned.join(", ") : "Operasyon"}</div>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-3">
              <Button variant="secondary" onClick={() => void handleExportPrivacy()} disabled={privacyBusy !== null}>
                {privacyBusy === "export" ? "Bekle..." : "Disa aktar"}
              </Button>
              <Button variant="ghost" onClick={() => void handleDeletePrivacy()} disabled={privacyBusy !== null}>
                {privacyBusy === "delete" ? "Bekle..." : "Sil"}
              </Button>
            </div>
          </Surface>

          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Hesap</div>
                <div className="mt-2 truncate text-[14px] font-medium text-[var(--text-primary)]">
                  {authenticatedEmail || "Oturum"}
                </div>
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                  {workspaceDetail?.workspace.name || "Local"} · {billing?.plan.label || "Free"}
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => void openPortal()} disabled={billingBusy !== null}>
                  <ArrowUpRight className="mr-2 h-4 w-4" />
                  Portal
                </Button>
                <Button variant="ghost" onClick={() => void finalizeLocalSessionExit()}>
                  Cikis
                </Button>
              </div>
            </div>
          </Surface>
        </div>
      </div>
    </div>
  );
}
