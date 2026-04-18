import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Cable, ExternalLink, Mail, MessageSquare, RefreshCw, ScanQrCode, ShieldCheck, Trash2 } from "@/vendor/lucide-react";

import { Button } from "@/components/primitives/Button";
import { Surface } from "@/components/primitives/Surface";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import {
  useAdminWorkspaces,
  useBillingWorkspace,
  useChannelPairingStatus,
  useChannels,
  useChannelsCatalog,
  useConnectorAccounts,
  useConnectorHealth,
  useConnectorTraces,
  useConnectors,
  useInboxEvents,
  useSystemReadiness,
} from "@/hooks/use-desktop-data";
import { runtimeManager } from "@/runtime/runtime-manager";
import {
  connectConnector,
  refreshConnectorAccount,
  revokeConnectorAccount,
  runConnectorQuickAction,
  startChannelPairing,
  testChannel,
  toggleChannel,
  upsertChannel,
} from "@/services/api/elyan-service";
import { useRuntimeStore } from "@/stores/runtime-store";
import type { ChannelCatalogEntry, ChannelSummary, ConnectorDefinition, ConnectorExecutionResult } from "@/types/domain";
import { getRuntimeGateReason, hasRuntimeWriteAccess } from "@/utils/runtime-access";

const productivityOrder = ["gmail", "google_calendar", "google_drive", "notion", "slack", "github"];
const appleOrder = ["apple_mail", "apple_calendar", "apple_reminders", "apple_notes", "apple_contacts"];
const messagingOrder = ["telegram", "whatsapp", "imessage", "sms"];
const turkeyOrder = ["e_fatura", "e_arsiv", "logo", "netsis", "sgk"];
const secretFieldNames = new Set(["token", "password", "bot_token", "app_token", "bridge_token", "access_token", "verify_token", "auth_token"]);
const turkeySecretFieldNames = new Set(["password", "api_key"]);

const turkeyConnectorCopy: Record<string, { summary: string; detail: string }> = {
  e_fatura: {
    summary: "GIB akışları",
    detail: "Fatura gönderimi, health check ve kimlik doğrulama zemini hazır.",
  },
  e_arsiv: {
    summary: "Arşiv operasyonu",
    detail: "e-Arşiv erişimi ve teslim kayıtları için yerel connector yüzeyi.",
  },
  logo: {
    summary: "Muhasebe senkronu",
    detail: "Logo GO/Tiger tarafına kontrollü veri akışı için hazırlık katmanı.",
  },
  netsis: {
    summary: "ERP bağlantısı",
    detail: "Netsis muhasebe ve operasyon verisini Elyan akışına bağlayan yüzey.",
  },
  sgk: {
    summary: "İşyeri takibi",
    detail: "SGK durum kontrolü ve işyeri odaklı doğrulama hattı.",
  },
};

const turkeyConnectorFields: Record<
  string,
  Array<{ name: string; label: string; secret?: boolean; placeholder?: string }>
> = {
  e_fatura: [
    { name: "username", label: "Kullanıcı adı", placeholder: "gib-demo" },
    { name: "password", label: "Parola", secret: true, placeholder: "Parola" },
    { name: "api_key", label: "API key", secret: true, placeholder: "Opsiyonel" },
    { name: "integrator_alias", label: "Integrator alias", placeholder: "entegrator" },
    { name: "health_path", label: "Health path", placeholder: "/health" },
    { name: "credential_check_path", label: "Kimlik doğrulama path", placeholder: "/auth/check" },
  ],
  e_arsiv: [
    { name: "username", label: "Kullanıcı adı", placeholder: "earsiv-user" },
    { name: "password", label: "Parola", secret: true, placeholder: "Parola" },
    { name: "api_key", label: "API key", secret: true, placeholder: "Opsiyonel" },
    { name: "test_base_url", label: "Test base URL", placeholder: "https://..." },
    { name: "health_path", label: "Health path", placeholder: "/health" },
    { name: "credential_check_path", label: "Kimlik doğrulama path", placeholder: "/auth/check" },
  ],
  logo: [
    { name: "username", label: "Kullanıcı adı", placeholder: "logo-user" },
    { name: "password", label: "Parola", secret: true, placeholder: "Parola" },
    { name: "api_key", label: "API key", secret: true, placeholder: "Opsiyonel" },
    { name: "company_code", label: "Şirket kodu", placeholder: "001" },
    { name: "test_base_url", label: "Test base URL", placeholder: "https://..." },
    { name: "credential_check_path", label: "Kimlik doğrulama path", placeholder: "/auth/check" },
  ],
  netsis: [
    { name: "username", label: "Kullanıcı adı", placeholder: "netsis-user" },
    { name: "password", label: "Parola", secret: true, placeholder: "Parola" },
    { name: "api_key", label: "API key", secret: true, placeholder: "Opsiyonel" },
    { name: "company_code", label: "Şirket kodu", placeholder: "001" },
    { name: "test_base_url", label: "Test base URL", placeholder: "https://..." },
    { name: "credential_check_path", label: "Kimlik doğrulama path", placeholder: "/auth/check" },
  ],
  sgk: [
    { name: "username", label: "Kullanıcı adı", placeholder: "sgk-user" },
    { name: "password", label: "Parola", secret: true, placeholder: "Parola" },
    { name: "api_key", label: "API key", secret: true, placeholder: "Opsiyonel" },
    { name: "workplace_code", label: "İşyeri kodu", placeholder: "34XXXX" },
    { name: "test_base_url", label: "Test base URL", placeholder: "https://..." },
    { name: "credential_check_path", label: "Kimlik doğrulama path", placeholder: "/auth/check" },
  ],
};

function connectorTone(status: string): "success" | "warning" | "neutral" {
  if (status === "connected") {
    return "success";
  }
  if (status === "pending" || status === "degraded") {
    return "warning";
  }
  return "neutral";
}

function channelTone(channel?: ChannelSummary): "success" | "warning" | "info" {
  if (channel?.connected) {
    return "success";
  }
  if (channel?.enabled) {
    return "warning";
  }
  return "info";
}

function orderedConnectors(connectors: ConnectorDefinition[], order: string[]): ConnectorDefinition[] {
  return order
    .map((connectorId) => connectors.find((item) => item.connector === connectorId))
    .filter((item): item is ConnectorDefinition => Boolean(item));
}

function resolveMessagingFields(catalog?: ChannelCatalogEntry, channel?: ChannelSummary, drafts?: Record<string, string>) {
  if (!catalog) {
    return [];
  }
  const mode = String(drafts?.mode || channel?.mode || "bridge").trim().toLowerCase() || "bridge";
  if (catalog.type === "whatsapp") {
    const keep = mode === "cloud"
      ? new Set(["mode", "phone_number_id", "access_token", "verify_token", "webhook_path"])
      : new Set(["mode"]);
    return catalog.fields.filter((field) => keep.has(field.name));
  }
  if (Array.isArray(catalog.minimalFields) && catalog.minimalFields.length) {
    const keep = new Set(catalog.minimalFields);
    const ordered = catalog.minimalFields
      .map((name) => catalog.fields.find((field) => field.name === name))
      .filter((field): field is (typeof catalog.fields)[number] => Boolean(field));
    const remainder = catalog.fields.filter((field) => !keep.has(field.name) && field.name === "id");
    return [...ordered, ...remainder];
  }
  return catalog.fields;
}

export function IntegrationsScreen() {
  const queryClient = useQueryClient();
  const connectionState = useRuntimeStore((state) => state.connectionState);
  const sidecarHealth = useRuntimeStore((state) => state.sidecarHealth);
  const runtimeReady = hasRuntimeWriteAccess(connectionState, sidecarHealth);
  const runtimeGateReason = getRuntimeGateReason(connectionState, sidecarHealth);

  const { data: readiness } = useSystemReadiness();
  const { data: billing } = useBillingWorkspace();
  const { data: adminWorkspaces = [] } = useAdminWorkspaces();
  const { data: connectors = [] } = useConnectors();
  const { data: accounts = [] } = useConnectorAccounts();
  const { data: connectorHealth = [] } = useConnectorHealth();
  const { data: traces = [] } = useConnectorTraces();
  const { data: channels = [] } = useChannels();
  const { data: channelCatalog = [] } = useChannelsCatalog();
  const primaryWorkspaceId = adminWorkspaces[0]?.workspaceId || billing?.workspaceId || "local-workspace";
  const { data: inboxEvents = [] } = useInboxEvents(primaryWorkspaceId, 8);
  const { data: whatsappPairing } = useChannelPairingStatus("whatsapp");

  const [busyId, setBusyId] = useState("");
  const [message, setMessage] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [channelDrafts, setChannelDrafts] = useState<Record<string, Record<string, string>>>({});
  const [turkeyDrafts, setTurkeyDrafts] = useState<Record<string, Record<string, string>>>({});
  const [turkeyConsent, setTurkeyConsent] = useState<Record<string, boolean>>({});
  const [quickResults, setQuickResults] = useState<Record<string, ConnectorExecutionResult>>({});
  const panelClassName = "rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] p-4";
  const fieldClassName =
    "h-[44px] w-full rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 text-[13px] text-[var(--text-primary)] outline-none transition focus:border-[var(--border-focus)]";

  const productivityConnectors = useMemo(() => orderedConnectors(connectors, productivityOrder), [connectors]);
  const appleConnectors = useMemo(() => orderedConnectors(connectors, appleOrder), [connectors]);
  const turkeyConnectors = useMemo(() => orderedConnectors(connectors, turkeyOrder), [connectors]);
  const messagingChannels = useMemo(
    () =>
      messagingOrder
        .map((type) => ({
          type,
          catalog: channelCatalog.find((item) => item.type === type),
          channel: channels.find((item) => item.type === type),
        }))
        .filter((entry) => Boolean(entry.catalog || entry.channel)),
    [channelCatalog, channels],
  );
  const recentTraces = traces.slice(0, 6);
  const connectedMessagingCount = messagingChannels.filter((entry) => entry.channel?.connected).length;
  const recentMobileIntake = inboxEvents.filter((entry) => messagingOrder.includes(entry.sourceType)).slice(0, 6);
  const mobileLaneCards = messagingChannels.map((entry) => ({
    ...entry,
    ready: Boolean(entry.channel?.connected),
    hint:
      entry.type === "whatsapp"
        ? "QR / Cloud"
        : entry.type === "telegram"
          ? "Bot token"
          : entry.type === "imessage"
            ? "BlueBubbles"
            : "Hat hazirla",
  }));

  async function syncViews() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["connectors"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-accounts", "all"] }),
      queryClient.invalidateQueries({ queryKey: ["connector-health"] }),
      queryClient.invalidateQueries({ queryKey: ["channels"] }),
      queryClient.invalidateQueries({ queryKey: ["channel-pairing", "whatsapp"] }),
      queryClient.invalidateQueries({ queryKey: ["system-readiness"] }),
      queryClient.invalidateQueries({ queryKey: ["inbox-events"] }),
      queryClient.invalidateQueries({ queryKey: ["home-snapshot"] }),
      queryClient.invalidateQueries({ queryKey: ["logs"] }),
    ]);
  }

  async function guardRuntime() {
    if (runtimeReady) {
      return true;
    }
    setMessage(runtimeGateReason);
    return false;
  }

  function channelValue(type: string, fieldName: string, channel?: ChannelSummary) {
    const draft = channelDrafts[type]?.[fieldName];
    if (typeof draft === "string") {
      return draft;
    }
    const source = (channel || {}) as unknown as Record<string, unknown>;
    if (secretFieldNames.has(fieldName)) {
      return "";
    }
    return String(source[fieldName] || "");
  }

  function updateChannelDraft(type: string, fieldName: string, value: string) {
    setChannelDrafts((current) => ({
      ...current,
      [type]: {
        ...(current[type] || {}),
        [fieldName]: value,
      },
    }));
  }

  function turkeyDraftValue(connector: string, fieldName: string) {
    return turkeyDrafts[connector]?.[fieldName] || "";
  }

  function updateTurkeyDraft(connector: string, fieldName: string, value: string) {
    setTurkeyDrafts((current) => ({
      ...current,
      [connector]: {
        ...(current[connector] || {}),
        [fieldName]: value,
      },
    }));
  }

  async function handleConnect(connector: ConnectorDefinition) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`connect:${connector.connector}`);
    setMessage("");
    try {
      const result = await connectConnector(connector.connector);
      if (result.launchUrl) {
        await runtimeManager.openExternalUrl(result.launchUrl);
      }
      setMessage(result.launchUrl ? `${connector.label} acildi.` : `${connector.label} hazir.`);
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${connector.label} baglanamadi.`);
    } finally {
      setBusyId("");
    }
  }

  async function handleTurkeySave(connector: ConnectorDefinition) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`turkey-save:${connector.connector}`);
    setMessage("");
    try {
      const draft = turkeyDrafts[connector.connector] || {};
      const payload: Record<string, unknown> = {
        workspace_id: primaryWorkspaceId,
        consent_granted: Boolean(turkeyConsent[connector.connector]),
      };
      for (const field of turkeyConnectorFields[connector.connector] || []) {
        const value = String(draft[field.name] || "").trim();
        if (value) {
          payload[field.name] = value;
        }
      }
      const result = await connectConnector(connector.connector, payload);
      setMessage(String(result.connectResult?.message || `${connector.label} kaydedildi.`));
      setTurkeyDrafts((current) => ({
        ...current,
        [connector.connector]: Object.fromEntries(
          Object.entries(current[connector.connector] || {}).map(([key, value]) => [
            key,
            turkeySecretFieldNames.has(key) ? "" : value,
          ]),
        ),
      }));
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `${connector.label} kaydedilemedi.`);
    } finally {
      setBusyId("");
    }
  }

  async function handleTurkeyQuickAction(connector: ConnectorDefinition, action: "health_check" | "test_credentials") {
    await handleQuickAction(connector.connector, action);
  }

  async function handleRefresh(accountId: string) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`refresh:${accountId}`);
    setMessage("");
    try {
      await refreshConnectorAccount(accountId);
      setMessage("Hesap yenilendi.");
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Yenileme olmadi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleRevoke(accountId: string) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`revoke:${accountId}`);
    setMessage("");
    try {
      const ok = await revokeConnectorAccount(accountId);
      setMessage(ok ? "Hesap kaldirildi." : "Kaldirma olmadi.");
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Kaldirma olmadi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleChannelSave(entry: { type: string; catalog?: ChannelCatalogEntry; channel?: ChannelSummary }) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`channel-save:${entry.type}`);
    setMessage("");
    try {
      const payload: Record<string, unknown> = {
        type: entry.type,
        id: entry.channel?.id || entry.type,
        enabled: true,
        workspace_id: primaryWorkspaceId,
      };
      for (const field of entry.catalog?.fields || []) {
        const value = channelValue(entry.type, field.name, entry.channel).trim();
        if (value) {
          payload[field.name] = value;
        }
      }
      await upsertChannel(payload);
      setMessage(`${entry.catalog?.label || entry.type} kayitli.`);
      setChannelDrafts((current) => ({ ...current, [entry.type]: {} }));
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Kayit olmadi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleChannelPairStart(type: string) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`channel-pair:${type}`);
    setMessage("");
    try {
      const pairing = await startChannelPairing(type, { workspace_id: primaryWorkspaceId });
      setMessage(pairing.detail || `${type} eslesti.`);
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Eslesme olmadi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleChannelToggle(entry: { type: string; channel?: ChannelSummary }, enabled: boolean) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`channel-toggle:${entry.type}`);
    setMessage("");
    try {
      await toggleChannel(entry.channel?.id || entry.type, enabled);
      setMessage(enabled ? `${entry.type} acik.` : `${entry.type} kapali.`);
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Durum olmadi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleChannelTest(type: string) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`channel-test:${type}`);
    setMessage("");
    try {
      const result = await testChannel(type);
      setMessage(result.message || `${type} hazir.`);
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Test olmadi.");
    } finally {
      setBusyId("");
    }
  }

  async function handleQuickAction(connector: string, action: string, payload: Record<string, unknown> = {}) {
    if (!(await guardRuntime())) {
      return;
    }
    setBusyId(`quick:${connector}:${action}`);
    setMessage("");
    try {
      const result = await runConnectorQuickAction(connector, action, payload);
      setQuickResults((current) => ({ ...current, [connector]: result }));
      setMessage(result.blockingIssue ? `${connector}: ${result.blockingIssue}` : `${connector} tamam.`);
      await syncViews();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Hizli islem olmadi.");
    } finally {
      setBusyId("");
    }
  }

  function renderQuickResult(connector: string) {
    const snapshot = quickResults[connector];
    if (!snapshot) {
      return null;
    }
    const items = Array.isArray(snapshot.result.items) ? snapshot.result.items.slice(0, 3) : [];
    return (
      <div className="mt-3 rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3">
        <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{snapshot.action}</div>
        {snapshot.blockingIssue ? <div className="mt-1 text-[12px] text-[var(--accent-amber)]">{snapshot.blockingIssue}</div> : null}
        {items.length ? (
          <div className="mt-2 space-y-1">
            {items.map((item, index) => (
              <div key={`${connector}:${index}`} className="text-[12px] text-[var(--text-secondary)]">
                {String((item as Record<string, unknown>).title || (item as Record<string, unknown>).name || (item as Record<string, unknown>).summary || JSON.stringify(item))}
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-2 text-[12px] text-[var(--text-secondary)]">
            {String(snapshot.result.message || snapshot.result.status || `${Number(snapshot.result.count || 0)} items`)}
          </div>
        )}
      </div>
    );
  }

  function renderConnectorList(title: string, description: string, items: ConnectorDefinition[]) {
    return (
      <Surface tone="card" className="p-5">
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">{title}</div>
          {description ? <div className="mt-2 text-[13px] text-[var(--text-secondary)]">{description}</div> : null}
        </div>

        <div className="mt-4 space-y-3">
          {items.map((connector) => {
            const relatedAccounts = accounts.filter((item) => item.provider === connector.provider || item.provider === connector.connector);
            const relatedHealth = connectorHealth.find((item) => item.connector === connector.connector || item.provider === connector.provider);
            return (
              <div key={connector.connector} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-[15px] font-medium text-[var(--text-primary)]">
                      <Cable className="h-4 w-4" />
                      {connector.label}
                    </div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">
                      {connector.capabilities.slice(0, 4).join(" · ")}
                    </div>
                    <div className="mt-2 text-[11px] text-[var(--text-tertiary)]">
                      {relatedAccounts.length} accounts · {relatedHealth?.traceCount || connector.traceCount} traces
                      {connector.executionMode ? ` · ${connector.executionMode}` : ""}
                    </div>
                    {connector.blockingIssue ? (
                      <div className="mt-2 text-[11px] text-[var(--accent-amber)]">{connector.blockingIssue}</div>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge tone={connectorTone(connector.status)}>{connector.status}</StatusBadge>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => void handleConnect(connector)}
                      disabled={!runtimeReady || busyId === `connect:${connector.connector}`}
                    >
                      <ExternalLink className="mr-2 h-4 w-4" />
                      {busyId === `connect:${connector.connector}` ? "Opening..." : relatedAccounts.length ? "Reconnect" : "Connect"}
                    </Button>
                  </div>
                </div>

                {connector.connector === "apple_notes" ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleQuickAction("apple_notes", "list")}
                      disabled={!runtimeReady || busyId === "quick:apple_notes:list"}
                    >
                      Notlar
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleQuickAction("apple_notes", "search", { query: "meeting" })}
                      disabled={!runtimeReady || busyId === "quick:apple_notes:search"}
                    >
                      Ara
                    </Button>
                  </div>
                ) : null}
                {connector.connector === "apple_calendar" ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleQuickAction("apple_calendar", "today")}
                      disabled={!runtimeReady || busyId === "quick:apple_calendar:today"}
                    >
                      Bugun
                    </Button>
                  </div>
                ) : null}
                {connector.connector === "apple_reminders" ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void handleQuickAction("apple_reminders", "list_due")}
                      disabled={!runtimeReady || busyId === "quick:apple_reminders:list_due"}
                    >
                      Vade
                    </Button>
                  </div>
                ) : null}
                {renderQuickResult(connector.connector)}

                {relatedAccounts.length ? (
                  <div className="mt-4 space-y-2">
                    {relatedAccounts.map((account) => (
                      <div
                        key={account.accountId}
                        className="flex items-center justify-between gap-3 rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3"
                      >
                        <div className="min-w-0">
                          <div className="truncate text-[13px] font-medium text-[var(--text-primary)]">
                            {account.displayName || account.email || account.accountAlias}
                          </div>
                          <div className="truncate text-[11px] text-[var(--text-tertiary)]">
                            {account.email || account.accountAlias} · {account.status}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void handleRefresh(account.accountId)}
                            disabled={!runtimeReady || busyId === `refresh:${account.accountId}`}
                          >
                            <RefreshCw className="mr-2 h-4 w-4" />
                            Yenile
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void handleRevoke(account.accountId)}
                            disabled={!runtimeReady || busyId === `revoke:${account.accountId}`}
                          >
                            <Trash2 className="mr-2 h-4 w-4" />
                            Kaldir
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </Surface>
    );
  }

  function renderTurkeyConnectorList(items: ConnectorDefinition[]) {
    return (
      <Surface tone="card" className="p-5">
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Türkiye Operasyonları</div>
          <div className="mt-2 text-[13px] leading-6 text-[var(--text-secondary)]">
            Elyan’ın asıl iş yüzeyi burada başlıyor: e-Fatura, muhasebe ve SGK akışları local-first ilerleyecek.
          </div>
        </div>

        <div className="mt-4 grid gap-3">
          {items.map((connector) => {
            const copy = turkeyConnectorCopy[connector.connector] || {
              summary: connector.label,
              detail: connector.capabilities.slice(0, 3).join(" · "),
            };
            const relatedHealth = connectorHealth.find((item) => item.connector === connector.connector || item.provider === connector.provider);
            const tone = connector.status === "connected" ? "success" : connector.status === "degraded" ? "warning" : "neutral";
            const statusLabel =
              connector.status === "connected"
                ? "Hazır"
                : connector.status === "degraded"
                  ? "Dikkat"
                  : connector.status === "pending"
                    ? "Kurulum"
                    : "Bekliyor";
            const blocker =
              connector.blockingIssue === "manual_setup_required"
                ? "Manuel kurulum ve KVKK onayı gerekiyor."
                : connector.blockingIssue === "manual_review_required"
                  ? "Son kontrol sonucu gözden geçirilmeli."
                  : relatedHealth?.blockingIssue || "";
            const fields = turkeyConnectorFields[connector.connector] || [];
            const quickResult = quickResults[connector.connector];

            return (
              <div key={connector.connector} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="text-[15px] font-medium text-[var(--text-primary)]">{connector.label}</div>
                      <StatusBadge tone={tone}>{statusLabel}</StatusBadge>
                    </div>
                    <div className="mt-1 text-[12px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">{copy.summary}</div>
                    <div className="mt-2 text-[13px] leading-6 text-[var(--text-secondary)]">{copy.detail}</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {connector.capabilities.slice(0, 3).map((capability) => (
                        <span
                          key={`${connector.connector}:${capability}`}
                          className="rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-1 text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]"
                        >
                          {capability.replaceAll("_", " ")}
                        </span>
                      ))}
                    </div>
                    <div className="mt-3 text-[11px] text-[var(--text-tertiary)]">
                      {connector.executionMode ? `${connector.executionMode} · ` : ""}{relatedHealth?.traceCount || connector.traceCount} trace
                    </div>
                    {blocker ? <div className="mt-2 text-[12px] text-[var(--accent-amber)]">{blocker}</div> : null}
                  </div>
                  <StatusBadge tone={tone}>{statusLabel}</StatusBadge>
                </div>

                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  {fields.map((field) => (
                    <input
                      key={`${connector.connector}:${field.name}`}
                      type={field.secret ? "password" : "text"}
                      value={turkeyDraftValue(connector.connector, field.name)}
                      onChange={(event) => updateTurkeyDraft(connector.connector, field.name, event.target.value)}
                      placeholder={field.placeholder || field.label}
                      className={fieldClassName}
                    />
                  ))}
                </div>

                <label className="mt-4 flex items-center gap-3 rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3 text-[12px] text-[var(--text-secondary)]">
                  <input
                    type="checkbox"
                    checked={Boolean(turkeyConsent[connector.connector])}
                    onChange={(event) =>
                      setTurkeyConsent((current) => ({
                        ...current,
                        [connector.connector]: event.target.checked,
                      }))
                    }
                  />
                  KVKK onayı mevcut. Kimlik doğrulama akışına izin ver.
                </label>

                <div className="mt-4 flex flex-wrap gap-3">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => void handleTurkeySave(connector)}
                    disabled={!runtimeReady || busyId === `turkey-save:${connector.connector}`}
                  >
                    {busyId === `turkey-save:${connector.connector}` ? "Kaydediliyor..." : "Kaydet"}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => void handleTurkeyQuickAction(connector, "health_check")}
                    disabled={!runtimeReady || busyId === `quick:${connector.connector}:health_check`}
                  >
                    Health check
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleTurkeyQuickAction(connector, "test_credentials")}
                    disabled={!runtimeReady || busyId === `quick:${connector.connector}:test_credentials`}
                  >
                    Kimlik testi
                  </Button>
                </div>

                {quickResult ? (
                  <div className="mt-3 rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-[var(--text-tertiary)]">{quickResult.action}</div>
                    <div className="mt-2 text-[12px] text-[var(--text-secondary)]">
                      {String(
                        quickResult.result.error ||
                          quickResult.result.message ||
                          quickResult.result.status ||
                          (quickResult.result.healthy === true ? "healthy" : ""),
                      )}
                    </div>
                    {typeof quickResult.result.latency_ms === "number" ? (
                      <div className="mt-1 text-[11px] text-[var(--text-tertiary)]">{quickResult.result.latency_ms} ms</div>
                    ) : null}
                    {quickResult.blockingIssue ? (
                      <div className="mt-1 text-[11px] text-[var(--accent-amber)]">{quickResult.blockingIssue}</div>
                    ) : null}
                  </div>
                ) : null}

                <div className="mt-4 flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
                  <ArrowRight className="h-4 w-4" />
                  İlk dilim: kurulum, health ve credential doğrulama.
                </div>
              </div>
            );
          })}
        </div>
      </Surface>
    );
  }

  return (
    <div className="space-y-4">
      <Surface tone="hero" className="px-6 py-7">
        <div className="space-y-3">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Baglantilar</div>
          <h1 className="font-display text-[30px] font-semibold tracking-[-0.05em] text-[var(--text-primary)]">Mesaj kanalları</h1>
          <p className="max-w-[680px] text-[13px] leading-6 text-[var(--text-secondary)]">
            İlk kurulum için yalnızca Telegram ve WhatsApp’ı gösteriyorum. Diğer uygulamalar isteğe bağlı.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={runtimeReady ? "success" : "warning"}>{runtimeReady ? "Hazir" : "Kapali"}</StatusBadge>
            <StatusBadge tone={connectedMessagingCount > 0 ? "success" : "info"}>
              {connectedMessagingCount > 0 ? `${connectedMessagingCount} kanal açık` : "ilk kanal"}
            </StatusBadge>
            <div className="text-[12px] text-[var(--text-secondary)]">
              WhatsApp {readiness?.whatsappMode || "yok"} · Telegram {channels.find((item) => item.type === "telegram")?.connected ? "açık" : "bekliyor"}
            </div>
          </div>
        </div>
      </Surface>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Surface tone="card" className="p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Mobil</div>
              <div className="mt-2 text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Kanallar</div>
            </div>
            <StatusBadge tone={connectedMessagingCount > 0 ? "success" : "info"}>
              {connectedMessagingCount > 0 ? `${connectedMessagingCount} acik` : "Ilk kanal"}
            </StatusBadge>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {mobileLaneCards.filter((entry) => entry.type === "telegram" || entry.type === "whatsapp").map((entry) => (
              <div key={entry.type} className={panelClassName}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[14px] font-medium text-[var(--text-primary)]">{entry.catalog?.label || entry.type}</div>
                    <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{entry.hint}</div>
                  </div>
                  <StatusBadge tone={entry.ready ? "success" : entry.channel?.enabled ? "warning" : "info"}>
                    {entry.ready ? "Acik" : entry.channel?.enabled ? "Hazir" : "Kur"}
                  </StatusBadge>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {entry.type === "whatsapp" ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => void handleChannelPairStart("whatsapp")}
                      disabled={!runtimeReady || busyId === "channel-pair:whatsapp"}
                    >
                      <ScanQrCode className="mr-2 h-4 w-4" />
                      {busyId === "channel-pair:whatsapp" ? "Bekle..." : "QR"}
                    </Button>
                  ) : null}
                  <Button variant="ghost" size="sm" onClick={() => setMessage(`${entry.catalog?.label || entry.type}: alanlar aşağıda.`)}>
                    Düzenle
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Surface>

        <Surface tone="card" className="p-5">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Akis</div>
            <div className="mt-2 text-[20px] font-semibold tracking-[-0.04em] text-[var(--text-primary)]">Siralama</div>
          </div>
          <div className="mt-4 space-y-3">
            {["1. Telegram veya WhatsApp kur", "2. Test gönder", "3. Inbox akışını kontrol et"].map((item) => (
              <div key={item} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-3 text-[13px] text-[var(--text-secondary)]">
                {item}
              </div>
            ))}
            {whatsappPairing?.detail ? (
              <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
                <div className="text-[13px] font-medium text-[var(--text-primary)]">WhatsApp</div>
                <div className="mt-1 text-[12px] text-[var(--text-secondary)]">{whatsappPairing.detail}</div>
              </div>
            ) : null}

            <div className="pt-2">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Son akis</div>
                <StatusBadge tone={recentMobileIntake.length ? "success" : "neutral"}>
                  {recentMobileIntake.length ? `${recentMobileIntake.length} kayit` : "Bos"}
                </StatusBadge>
              </div>
              <div className="mt-3 space-y-3">
                {recentMobileIntake.length ? (
                  recentMobileIntake.map((entry) => (
                    <div key={entry.eventId} className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-[13px] font-medium text-[var(--text-primary)]">{entry.title}</div>
                          <div className="mt-1 text-[12px] leading-6 text-[var(--text-secondary)]">
                            {entry.summary?.summary || entry.contentPreview}
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          <StatusBadge tone={entry.summary?.urgency === "high" ? "warning" : entry.summary ? "info" : "neutral"}>
                            {entry.sourceType}
                          </StatusBadge>
                          <span className="text-[11px] text-[var(--text-tertiary)]">{entry.updatedAt}</span>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4 text-[13px] text-[var(--text-secondary)]">
                    Bekliyor.
                  </div>
                )}
              </div>
            </div>
          </div>
        </Surface>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="space-y-6">
          <Surface tone="card" className="p-5">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">Mesaj</div>
              <div className="mt-2 text-[14px] text-[var(--text-secondary)]">Canlı kanallar</div>
            </div>

            <div className="mt-4 space-y-3">
              {messagingChannels.filter((entry) => entry.type === "telegram" || entry.type === "whatsapp").map((entry) => (
                <div key={entry.type} className="rounded-[18px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2 text-[14px] font-medium text-[var(--text-primary)]">
                      <MessageSquare className="h-4 w-4" />
                      {entry.catalog?.label || entry.type}
                    </div>
                    <StatusBadge tone={channelTone(entry.channel)}>
                      {entry.channel?.connected ? "Acik" : entry.channel?.enabled ? "Hazir" : "Kapali"}
                    </StatusBadge>
                  </div>

                  <div className="mt-3 grid gap-3">
                    {resolveMessagingFields(entry.catalog, entry.channel, channelDrafts[entry.type]).map((field) => (
                      <input
                        key={`${entry.type}:${field.name}`}
                        type={field.secret ? "password" : "text"}
                        value={channelValue(entry.type, field.name, entry.channel)}
                        onChange={(event) => updateChannelDraft(entry.type, field.name, event.target.value)}
                        placeholder={field.label}
                        className={fieldClassName}
                      />
                    ))}
                  </div>

                  {entry.type === "whatsapp" && whatsappPairing ? (
                    <div className="mt-3 rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-[12px] font-medium text-[var(--text-primary)]">QR</div>
                        <StatusBadge tone={whatsappPairing.ready ? "success" : whatsappPairing.pending ? "warning" : "info"}>
                          {whatsappPairing.status.replace(/_/g, " ")}
                        </StatusBadge>
                      </div>
                      <div className="mt-2 text-[12px] leading-6 text-[var(--text-secondary)]">{whatsappPairing.detail}</div>
                      {whatsappPairing.qrText ? (
                        <pre className="mt-3 overflow-auto rounded-[14px] border border-[var(--border-subtle)] bg-[var(--bg-shell)] p-3 text-[8px] leading-[1.05] text-[var(--text-primary)]">
                          {whatsappPairing.qrText}
                        </pre>
                      ) : null}
                    </div>
                  ) : null}

                  <div className="mt-4 flex flex-wrap gap-3">
                    {entry.catalog?.supportsPairing ? (
                      <Button
                        variant="primary"
                        onClick={() => void handleChannelPairStart(entry.type)}
                        disabled={!runtimeReady || busyId === `channel-pair:${entry.type}`}
                      >
                        {busyId === `channel-pair:${entry.type}` ? "Bekle..." : "QR baslat"}
                      </Button>
                    ) : null}
                    <Button
                      variant={entry.catalog?.supportsPairing ? "secondary" : "primary"}
                      onClick={() => void handleChannelSave(entry)}
                      disabled={!runtimeReady || busyId === `channel-save:${entry.type}`}
                    >
                      {busyId === `channel-save:${entry.type}` ? "Bekle..." : entry.channel ? "Guncelle" : "Kaydet"}
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => void handleChannelTest(entry.type)}
                      disabled={!runtimeReady || busyId === `channel-test:${entry.type}`}
                    >
                      Test
                    </Button>
                    {entry.type === "whatsapp" ? (
                      <Button
                        variant="ghost"
                        onClick={() => void handleQuickAction(entry.type, "status")}
                        disabled={!runtimeReady || busyId === `quick:${entry.type}:status`}
                      >
                        Status
                      </Button>
                    ) : null}
                    {entry.channel ? (
                      <Button
                        variant="ghost"
                        onClick={() => void handleChannelToggle(entry, !entry.channel?.enabled)}
                        disabled={!runtimeReady || busyId === `channel-toggle:${entry.type}`}
                      >
                        {entry.channel.enabled ? "Kapat" : "Ac"}
                      </Button>
                    ) : null}
                  </div>
                  {renderQuickResult(entry.type)}
                </div>
              ))}
            </div>
          </Surface>

          <Surface tone="card" className="p-5">
            <div className="flex items-center gap-2 text-[14px] font-medium text-[var(--text-primary)]">
              <ShieldCheck className="h-4 w-4" />
              Durum
            </div>
            <div className="mt-3 text-[12px] text-[var(--text-secondary)]">
              {message || (!runtimeReady ? runtimeGateReason : "Hazir.")}
            </div>
          </Surface>
        </div>

        <div className="space-y-6">
          <Surface tone="card" className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[var(--text-tertiary)]">İsteğe bağlı</div>
                <div className="mt-2 text-[14px] text-[var(--text-secondary)]">Google, Apple ve diğer bağlantılar</div>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setShowAdvanced((value) => !value)}>
                {showAdvanced ? "Gizle" : "Göster"}
              </Button>
            </div>
            {!showAdvanced ? (
              <div className="mt-4 rounded-[18px] border border-[var(--glass-border)] bg-[var(--glass-elevated)] px-4 py-4 text-[12px] leading-6 text-[var(--text-secondary)]">
                İlk kullanım için bu alanı gizledim. Mesaj kanalları stabil olduktan sonra diğer uygulamaları bağla.
              </div>
            ) : (
              <div className="mt-4 space-y-6">
                {renderTurkeyConnectorList(turkeyConnectors)}
                {renderConnectorList("Apps", "Google, Notion, Slack", productivityConnectors)}
                {renderConnectorList("Apple", "Mail, Notes, Calendar", appleConnectors)}
                <Surface tone="card" className="p-5">
                  <div className="flex items-center gap-2 text-[14px] font-medium text-[var(--text-primary)]">
                    <Mail className="h-4 w-4" />
                    İzler
                  </div>
                  <div className="mt-4 space-y-2">
                    {recentTraces.length ? (
                      recentTraces.map((trace) => (
                        <div key={trace.traceId} className="rounded-[16px] border border-[var(--border-subtle)] bg-[var(--bg-surface-alt)] px-4 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-[13px] font-medium text-[var(--text-primary)]">
                              {trace.connectorName || trace.provider} · {trace.operation}
                            </div>
                            <StatusBadge tone={trace.success ? "success" : "warning"}>{trace.status}</StatusBadge>
                          </div>
                          <div className="mt-1 text-[11px] text-[var(--text-tertiary)]">{trace.createdAt}</div>
                        </div>
                      ))
                    ) : (
                      <div className="text-[12px] text-[var(--text-secondary)]">Boş</div>
                    )}
                  </div>
                </Surface>
              </div>
            )}
          </Surface>
        </div>
      </div>
    </div>
  );
}
