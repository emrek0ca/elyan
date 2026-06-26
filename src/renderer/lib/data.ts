import type { BootstrapSnapshot, JsonMap, JsonValue, RuntimeResponse } from '../../shared/protocol';

export interface MessageView {
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
  blocks: PlainRecord[];
  meta: Record<string, unknown>;
  pendingPlanId: string;
  needsConfirmation: boolean;
  errorCode: string;
}

export interface AgentStatusView {
  active: boolean;
  displayStage: string;
  displayAction: string;
  verificationUsed: boolean;
  executionStrategy: string;
}

export interface ConversationView {
  id: string;
  title: string;
  preview: string;
  updatedAt: string;
  messages: MessageView[];
}

export interface HydrationState {
  phase: 'idle' | 'hydrating' | 'ready' | 'retrying' | 'degraded';
  attempt: number;
  lastHydratedAt: string;
  nextRetryInMs: number;
  lastErrorCode: string;
}

export type PlainRecord = Record<string, unknown>;

export function asRecord(value: unknown): PlainRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as PlainRecord) : {};
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : value === null || value === undefined ? fallback : String(value);
}

export function asBoolean(value: unknown): boolean {
  return value === true;
}

export function stateRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  return asRecord(snapshot?.state);
}

export function runtimeRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  return asRecord(snapshot?.runtime);
}

export function backendRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  return asRecord(snapshot?.backend);
}

export function controlPlaneRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const runtime = runtimeRecord(snapshot);
  const backend = backendRecord(snapshot);
  const state = stateRecord(snapshot);
  return asRecord(runtime.controlPlane ?? backend.controlPlane ?? state.controlPlane);
}

export function runtimeTransportRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const runtime = runtimeRecord(snapshot);
  return asRecord(runtime.runtimeTransport);
}

export function backendHealthRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const controlPlane = controlPlaneRecord(snapshot);
  const backend = backendRecord(snapshot);
  return asRecord(controlPlane.health ?? backendResultData(backend.health));
}

export function brainProfileRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const controlPlane = controlPlaneRecord(snapshot);
  const backend = backendRecord(snapshot);
  return asRecord(controlPlane.brainProfile ?? backendResultData(backend.brainProfile));
}

export function localModelsRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const runtime = runtimeRecord(snapshot);
  const controlPlane = controlPlaneRecord(snapshot);
  return asRecord(runtime.localModels ?? controlPlane.localModels ?? snapshot?.localModels);
}

export function runtimeSessionRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const controlPlane = controlPlaneRecord(snapshot);
  const session = asRecord(controlPlane.runtimeSession);
  return asRecord(session.data ?? asRecord(session.result).data ?? session);
}

export function runtimeSessionReadinessRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  return asRecord(runtimeSessionRecord(snapshot).readiness);
}

export function runtimeSessionConnectionRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  return asRecord(runtimeSessionRecord(snapshot).connection);
}

export function runtimeSessionDeviceRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  return asRecord(runtimeSessionRecord(snapshot).device);
}

export function runtimeSessionCapabilitySummaryRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  return asRecord(runtimeSessionRecord(snapshot).capabilitySummary);
}

export function agentStatusRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const runtime = runtimeRecord(snapshot);
  const direct = asRecord(runtime.agentStatus);
  if (Object.keys(direct).length > 0) {
    return direct;
  }
  return asRecord(asRecord(runtime.executorStatus).agentStatus);
}

export function snapshotConversations(snapshot: BootstrapSnapshot | null): ConversationView[] {
  return conversationItemsFromSnapshot(snapshot, false);
}

export function snapshotArchivedConversations(snapshot: BootstrapSnapshot | null): ConversationView[] {
  return conversationItemsFromSnapshot(snapshot, true);
}

export function activeConversationId(snapshot: BootstrapSnapshot | null): string {
  const stateConversation = asRecord(stateRecord(snapshot).conversation);
  const activeId = asString(stateConversation.activeId);
  if (activeId) {
    return activeId;
  }
  return snapshotConversations(snapshot)[0]?.id ?? snapshotArchivedConversations(snapshot)[0]?.id ?? '';
}

export function selectedConversation(snapshot: BootstrapSnapshot | null, selectedId: string): ConversationView | null {
  const conversations = conversationItemsFromSnapshot(snapshot, null);
  if (selectedId) {
    return conversations.find((conversation) => conversation.id === selectedId) ?? null;
  }
  return conversations[0] ?? null;
}

export function applyRuntimeResult(snapshot: BootstrapSnapshot, response: RuntimeResponse): BootstrapSnapshot {
  const result = asRecord(response.result);
  let next = snapshot;
  if (Object.keys(asRecord(result.state)).length > 0) {
    next = {
      ...next,
      state: asRecord(result.state) as JsonMap,
    };
  }
  if (Array.isArray(result.conversations)) {
    next = {
      ...next,
      conversations: result.conversations as JsonMap[],
    };
  }
  if (Object.keys(asRecord(result.runtime)).length > 0) {
    next = {
      ...next,
      runtime: asRecord(result.runtime) as JsonMap,
    };
  }
  if (Object.keys(asRecord(result.backend)).length > 0) {
    next = {
      ...next,
      backend: asRecord(result.backend) as JsonMap,
    };
  }
  return next;
}

export function withRuntime(snapshot: BootstrapSnapshot, runtime: unknown): BootstrapSnapshot {
  return {
    ...snapshot,
    runtime: asRecord(runtime) as JsonMap,
  };
}

export function withBackend(snapshot: BootstrapSnapshot, backendPatch: unknown): BootstrapSnapshot {
  return {
    ...snapshot,
    backend: {
      ...asRecord(snapshot.backend),
      ...asRecord(backendPatch),
    } as JsonMap,
  };
}

export function runtimeReady(snapshot: BootstrapSnapshot | null): boolean {
  const runtime = runtimeRecord(snapshot);
  return asBoolean(runtime.runtimeReady) || asString(runtime.phase) === 'ready' || asString(runtime.runtimeLifecycleState) === 'ready';
}

export function runtimePhase(snapshot: BootstrapSnapshot | null): string {
  const runtime = runtimeRecord(snapshot);
  return asString(runtime.phase) || asString(runtime.runtimeLifecycleState) || 'degraded';
}

export function backendReady(snapshot: BootstrapSnapshot | null): boolean {
  const backend = backendRecord(snapshot);
  const health = backendHealthRecord(snapshot);
  return (
    asBoolean(backend.ok) ||
    asBoolean(asRecord(backend.auth).ok) ||
    asBoolean(asRecord(backend.authMe).ok) ||
    asBoolean(health.ok)
  );
}

export function backendResultData(value: unknown): PlainRecord {
  const payload = asRecord(value);
  return asRecord(payload.data ?? asRecord(payload.result).data);
}

export function authMeRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const backend = backendRecord(snapshot);
  const controlPlane = controlPlaneRecord(snapshot);
  return asRecord(backend.authMe ?? backend.auth ?? controlPlane.authMe ?? stateRecord(snapshot).auth);
}

export function accountRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const stateAccount = asRecord(stateRecord(snapshot).account);
  const authMe = authMeRecord(snapshot);
  const authData = backendResultData(authMe);
  const user = asRecord(authData.user ?? authData.account ?? authData.profile ?? authMe.user ?? authMe.account);
  return {
    ...stateAccount,
    ...user,
  };
}

export function accountDisplayName(snapshot: BootstrapSnapshot | null): string {
  const account = accountRecord(snapshot);
  const email = accountEmail(snapshot);
  const displayName = asString(account.displayName ?? account.display_name ?? account.name ?? account.fullName);
  if (displayName) {
    return displayName;
  }
  return email ? email.split('@').at(0) || 'Elyan' : 'Elyan';
}

export function accountEmail(snapshot: BootstrapSnapshot | null): string {
  const account = accountRecord(snapshot);
  return asString(account.email ?? account.userEmail ?? account.mail);
}

export function accountId(snapshot: BootstrapSnapshot | null): string {
  const account = accountRecord(snapshot);
  return asString(account.id ?? account.userId ?? account.sub);
}

export function subscriptionRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const authData = backendResultData(authMeRecord(snapshot));
  const backend = backendRecord(snapshot);
  const mobileData = backendResultData(backend.mobileBootstrap);
  return asRecord(authData.subscription ?? mobileData.subscription);
}

export function usageRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const authData = backendResultData(authMeRecord(snapshot));
  const backend = backendRecord(snapshot);
  const mobileData = backendResultData(backend.mobileBootstrap);
  return asRecord(authData.usage ?? mobileData.usage);
}

export type QuotaWindowSummary = {
  title: string;
  limit: number;
  used: number;
  remaining: number;
  remainingFraction: number | null;
  remainingPercent: number | null;
  resetAt: string;
  resetAtLabel: string;
  remainingLabel: string;
  remainingPercentLabel: string;
};

function readQuotaWindow(window: unknown): QuotaWindowSummary | null {
  const record = asRecord(window);
  const title = asString(record.title).trim();
  if (!title) {
    return null;
  }
  const limit = numberOrNull(record.limit) ?? 0;
  const used = numberOrNull(record.used) ?? 0;
  const remaining = numberOrNull(record.remaining) ?? 0;
  const remainingFraction = numberOrNull(record.remainingFraction);
  const remainingPercent = numberOrNull(record.remainingPercent);
  const resetAt = asString(record.resetAt);
  return {
    title,
    limit,
    used,
    remaining,
    remainingFraction,
    remainingPercent,
    resetAt,
    resetAtLabel: formatQuotaResetAt(resetAt),
    remainingLabel: remaining > 0 ? `${remaining} kaldı` : '0 kaldı',
    remainingPercentLabel: remainingPercent !== null ? `%${Math.max(0, Math.trunc(remainingPercent))} kaldı` : limit > 0 ? `${Math.max(0, Math.trunc((remaining / limit) * 100))}% kaldı` : 'Hazır',
  };
}

function formatQuotaResetAt(value: string): string {
  const parsed = safeDate(value);
  if (!parsed) {
    return 'Belirlenmedi';
  }
  return new Intl.DateTimeFormat('tr-TR', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed);
}

function quotaWindowsRecord(snapshot: BootstrapSnapshot | null): QuotaWindowSummary[] {
  const usage = usageRecord(snapshot);
  const provided = asArray(usage.quotaWindows)
    .map(readQuotaWindow)
    .filter((value): value is QuotaWindowSummary => value != null);
  if (provided.length > 0) {
    return provided;
  }

  const dailyRemaining = numberOrNull(usage.dailyRemaining);
  const weeklyRemaining = numberOrNull(usage.weeklyRemaining);
  const windows: QuotaWindowSummary[] = [];
  if (
    numberOrNull(usage.dailyLimit) !== null ||
    numberOrNull(usage.dailyUsed) !== null ||
    dailyRemaining !== null ||
    asString(usage.dailyResetAt).trim()
  ) {
    const limit = numberOrNull(usage.dailyLimit) ?? 0;
    const used = numberOrNull(usage.dailyUsed) ?? Math.max(0, limit - (dailyRemaining ?? 0));
    const remaining = dailyRemaining ?? Math.max(0, limit - used);
    const remainingPercent = numberOrNull(usage.dailyProgressPercent);
    windows.push({
      title: 'Günlük',
      limit,
      used,
      remaining,
      remainingFraction: limit > 0 ? remaining / limit : null,
      remainingPercent,
      resetAt: asString(usage.dailyResetAt),
      resetAtLabel: formatQuotaResetAt(asString(usage.dailyResetAt)),
      remainingLabel: `${remaining} kaldı`,
      remainingPercentLabel: remainingPercent !== null ? `%${Math.max(0, Math.trunc(remainingPercent))} kaldı` : limit > 0 ? `${Math.max(0, Math.trunc((remaining / limit) * 100))}% kaldı` : 'Hazır',
    });
  }
  if (
    numberOrNull(usage.weeklyLimit) !== null ||
    numberOrNull(usage.weeklyUsed) !== null ||
    weeklyRemaining !== null ||
    asString(usage.weeklyResetAt).trim()
  ) {
    const limit = numberOrNull(usage.weeklyLimit) ?? 0;
    const used = numberOrNull(usage.weeklyUsed) ?? Math.max(0, limit - (weeklyRemaining ?? 0));
    const remaining = weeklyRemaining ?? Math.max(0, limit - used);
    const remainingPercent = numberOrNull(usage.weeklyProgressPercent);
    windows.push({
      title: 'Haftalık',
      limit,
      used,
      remaining,
      remainingFraction: limit > 0 ? remaining / limit : null,
      remainingPercent,
      resetAt: asString(usage.weeklyResetAt),
      resetAtLabel: formatQuotaResetAt(asString(usage.weeklyResetAt)),
      remainingLabel: `${remaining} kaldı`,
      remainingPercentLabel: remainingPercent !== null ? `%${Math.max(0, Math.trunc(remainingPercent))} kaldı` : limit > 0 ? `${Math.max(0, Math.trunc((remaining / limit) * 100))}% kaldı` : 'Hazır',
    });
  }
  return windows;
}

function preferredQuotaWindow(snapshot: BootstrapSnapshot | null): QuotaWindowSummary | null {
  const windows = quotaWindowsRecord(snapshot);
  if (windows.length === 0) {
    return null;
  }
  if (windows.length === 1) {
    return windows[0] ?? null;
  }
  const daily = windows.find((window) => window.title.toLowerCase().includes('günlük')) ?? null;
  const weekly = windows.find((window) => window.title.toLowerCase().includes('haftalık')) ?? null;
  if (!daily) {
    return weekly;
  }
  if (!weekly) {
    return daily;
  }
  const dailyFraction = daily.remainingFraction ?? 1;
  const weeklyFraction = weekly.remainingFraction ?? 1;
  return dailyFraction <= weeklyFraction ? daily : weekly;
}

function numberOrNull(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export type ChatAccessState = {
  locked: boolean;
  trialActive: boolean;
  dailyRemaining: number | null;
  weeklyRemaining: number | null;
  trialEndsAt: string;
  title: string;
  detail: string;
};

export type AccountUsageSummary = {
  mode: 'trial' | 'paid' | 'free';
  quotaTitle: string;
  quotaStatusLabel: string;
  planLabel: string;
  billingStatusLabel: string;
  tokenSummaryLabel: string;
  planLabelSource: 'trial' | 'subscription';
  statusLabel: string;
  daysRemaining: string;
  endsAtLabel: string;
  dailyRemaining: string;
  weeklyRemaining: string;
  showQuotaCounters: boolean;
  endsAt: string;
  quotaWindows: QuotaWindowSummary[];
};

function accessModeRecord(snapshot: BootstrapSnapshot | null): 'trial' | 'paid' | 'free' {
  const usage = usageRecord(snapshot);
  const rawMode = asString(usage.accessMode).trim().toLowerCase();
  if (rawMode === 'trial' || rawMode === 'paid' || rawMode === 'free') {
    return rawMode;
  }
  if (asBoolean(usage.trialActive)) {
    return 'trial';
  }
  if (asBoolean(usage.serverBrainAllowed) && asString(subscriptionRecord(snapshot).planCode).trim().toLowerCase() !== 'free') {
    return 'paid';
  }
  return 'free';
}

function planLabelSource(snapshot: BootstrapSnapshot | null, mode: 'trial' | 'paid' | 'free'): 'trial' | 'subscription' {
  const usage = usageRecord(snapshot);
  const rawSource = asString(usage.planLabelSource).trim().toLowerCase();
  if (rawSource === 'trial' || rawSource === 'subscription') {
    return rawSource;
  }
  return mode === 'trial' ? 'trial' : 'subscription';
}

function subscriptionPlanLabel(snapshot: BootstrapSnapshot | null): string {
  const rawPlanCode = asString(subscriptionRecord(snapshot).planCode).trim().toLowerCase();
  const planCode = rawPlanCode === 'team' ? 'pro' : rawPlanCode;
  switch (planCode) {
    case 'solo':
      return 'Solo';
    case 'pro':
      return 'Pro';
    case 'free':
      return 'Ücretsiz';
    default:
      return 'Elyan';
  }
}

function subscriptionBillingStatusLabel(snapshot: BootstrapSnapshot | null): string {
  const status = asString(subscriptionRecord(snapshot).status);
  switch (status.trim().toLowerCase().replace(/\s+/g, '_')) {
    case 'active':
      return 'Aktif';
    case 'trial':
    case 'trialing':
      return 'Deneme';
    case 'past_due':
      return 'Ödeme bekleniyor';
    case 'canceled':
    case 'cancelled':
      return 'İptal';
    case 'paused':
      return 'Duraklatıldı';
    case 'free':
      return 'Ücretsiz';
    default:
      return status.trim().length > 0 ? status.trim() : 'Bilinmiyor';
  }
}

function formatCount(value: number): string {
  const raw = Math.max(0, Math.trunc(value)).toString();
  if (raw.length <= 3) {
    return raw;
  }

  const parts: string[] = [];
  let cursor = raw.length;
  while (cursor > 3) {
    parts.unshift(raw.slice(cursor - 3, cursor));
    cursor -= 3;
  }
  parts.unshift(raw.slice(0, cursor));
  return parts.join(',');
}

function subscriptionTokenSummaryLabel(snapshot: BootstrapSnapshot | null): string {
  const subscription = subscriptionRecord(snapshot);
  const usage = usageRecord(snapshot);
  const value = numberOrNull(usage.creditBalance ?? subscription.creditBalance ?? subscription.aiCreditsMonthly);
  if (value === null) {
    return 'Token dahil';
  }
  return `${formatCount(value)} token bakiye`;
}

function safeDate(value: string): Date | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDateLabel(value: string): string {
  const parsed = safeDate(value);
  if (!parsed) {
    return 'Belirlenmedi';
  }
  return new Intl.DateTimeFormat('tr-TR', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(parsed);
}

function remainingDaysLabel(value: string): string {
  const parsed = safeDate(value);
  if (!parsed) {
    return 'Belirlenmedi';
  }
  const now = new Date();
  const nowStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const endStart = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
  const diffMs = endStart.getTime() - nowStart.getTime();
  const days = Math.floor(diffMs / (24 * 60 * 60 * 1000));
  if (days < 0) {
    return '0 gün';
  }
  if (days === 0) {
    return 'Bugün bitiyor';
  }
  return `${days} gün`;
}

function countLabel(value: unknown): string {
  const numeric = numberOrNull(value);
  if (numeric === null) {
    return 'Belirlenmedi';
  }
  return `${Math.max(0, Math.trunc(numeric))} kaldı`;
}

export function accountUsageSummary(snapshot: BootstrapSnapshot | null): AccountUsageSummary {
  const mode = accessModeRecord(snapshot);
  const source = planLabelSource(snapshot, mode);
  const usage = usageRecord(snapshot);
  const windows = quotaWindowsRecord(snapshot);
  const preferredWindow = preferredQuotaWindow(snapshot);
  const subscription = subscriptionRecord(snapshot);
  const planLabel = subscriptionPlanLabel(snapshot);
  const billingStatusLabel = subscriptionBillingStatusLabel(snapshot);
  const tokenSummaryLabel = subscriptionTokenSummaryLabel(snapshot);
  const hasQuotaCounters = windows.length > 0;
  const endsAt =
    mode === 'trial'
      ? asString(usage.trialEndsAt || subscription.periodEndsAt || usage.windowEndsAt)
      : asString(subscription.periodEndsAt || usage.trialEndsAt || usage.windowEndsAt);
  const quotaStatusLabel = preferredWindow
    ? `${preferredWindow.title} ${preferredWindow.remainingLabel}`
    : 'Hazır';

  return {
    mode,
    quotaTitle: 'Limit',
    quotaStatusLabel,
    planLabel,
    billingStatusLabel,
    tokenSummaryLabel,
    planLabelSource: source,
    statusLabel: billingStatusLabel,
    daysRemaining: remainingDaysLabel(endsAt),
    endsAtLabel: formatDateLabel(endsAt),
    dailyRemaining: windows.find((window) => window.title === 'Günlük')?.remainingLabel ?? countLabel(usage.dailyRemaining),
    weeklyRemaining: windows.find((window) => window.title === 'Haftalık')?.remainingLabel ?? countLabel(usage.weeklyRemaining),
    showQuotaCounters: hasQuotaCounters,
    endsAt,
    quotaWindows: windows,
  };
}

export function chatAccessState(snapshot: BootstrapSnapshot | null): ChatAccessState {
  const usage = usageRecord(snapshot);
  const summary = accountUsageSummary(snapshot);
  const trialActive = summary.mode === 'trial';
  const serverBrainAllowed =
    typeof usage.serverBrainAllowed === 'boolean' ? usage.serverBrainAllowed : true;
  const upgradeRequired = asBoolean(usage.upgradeRequiredForServerBrain);
  const dailyRemaining = numberOrNull(usage.dailyRemaining);
  const weeklyRemaining = numberOrNull(usage.weeklyRemaining);
  const aiCreditsTracked = asBoolean(usage.aiCreditsTracked);
  const aiCreditsRemaining = numberOrNull(usage.aiCreditsRemaining);
  const dailyExhausted = dailyRemaining !== null && dailyRemaining <= 0;
  const weeklyExhausted = weeklyRemaining !== null && weeklyRemaining <= 0;
  const aiExhausted = aiCreditsTracked && aiCreditsRemaining !== null && aiCreditsRemaining <= 0;
  const trialEndsAt = summary.endsAt;

  if (dailyExhausted) {
    return {
      locked: true,
      trialActive,
      dailyRemaining,
      weeklyRemaining,
      trialEndsAt,
      title: 'Günlük limit doldu',
      detail: 'Yeni mesaj göndermek için günlük limitin yenilenmesini bekle.',
    };
  }

  if (weeklyExhausted) {
    return {
      locked: true,
      trialActive,
      dailyRemaining,
      weeklyRemaining,
      trialEndsAt,
      title: 'Haftalık limit doldu',
      detail: 'Yeni mesaj göndermek için haftalık limitin yenilenmesini bekle.',
    };
  }

  if (!serverBrainAllowed || upgradeRequired) {
    return {
      locked: true,
      trialActive,
      dailyRemaining,
      weeklyRemaining,
      trialEndsAt,
      title: 'Limit doldu',
      detail: 'Devam etmek için planını yükselt veya yerel model kurulumunu kullan.',
    };
  }

  if (aiExhausted) {
    return {
      locked: true,
      trialActive,
      dailyRemaining,
      weeklyRemaining,
      trialEndsAt,
      title: 'Token hakkın bitti',
      detail: 'Yeni mesaj göndermek için token yenilenmesini bekle veya planını güncelle.',
    };
  }

  return {
    locked: false,
    trialActive,
    dailyRemaining,
    weeklyRemaining,
    trialEndsAt,
    title: '',
    detail: '',
  };
}

export function authReady(snapshot: BootstrapSnapshot | null): boolean {
  const authMe = authMeRecord(snapshot);
  const stateAccount = asRecord(stateRecord(snapshot).account);
  return (
    asBoolean(authMe.ok) ||
    Boolean(asString(stateAccount.accessToken ?? stateAccount.userAccessToken ?? stateAccount.refreshToken))
  );
}

export function capabilityState(snapshot: BootstrapSnapshot | null, name: string): PlainRecord {
  const runtime = runtimeRecord(snapshot);
  const states = asRecord(runtime.runtimeCapabilityStates ?? runtime.capabilityStates);
  return asRecord(states[name]);
}

export function operatorCapabilityStatesRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const connection = runtimeSessionConnectionRecord(snapshot);
  const sessionStates = asRecord(connection.capabilityStates);
  if (Object.keys(sessionStates).length > 0) {
    return sessionStates;
  }
  const runtime = runtimeRecord(snapshot);
  return asRecord(runtime.runtimeCapabilityStates ?? runtime.capabilityStates);
}

export function operatorCapabilityCount(snapshot: BootstrapSnapshot | null): number {
  const summary = runtimeSessionCapabilitySummaryRecord(snapshot);
  const total = Number(summary.total);
  if (Number.isFinite(total) && total >= 0) {
    return total;
  }
  const connection = runtimeSessionConnectionRecord(snapshot);
  const connectionCapabilities = asArray(connection.capabilities);
  if (connectionCapabilities.length > 0) {
    return connectionCapabilities.length;
  }
  const runtime = runtimeRecord(snapshot);
  const runtimeCount = Number(runtime.runtimeCapabilityCount);
  if (Number.isFinite(runtimeCount) && runtimeCount >= 0) {
    return runtimeCount;
  }
  return asArray(runtime.runtimeCapabilities ?? runtime.capabilities).length;
}

export function operatorCapabilityCategoriesRecord(snapshot: BootstrapSnapshot | null): PlainRecord {
  const summary = runtimeSessionCapabilitySummaryRecord(snapshot);
  const categories = asRecord(summary.categories);
  if (Object.keys(categories).length > 0) {
    return categories;
  }
  return {};
}

export function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return '{}';
  }
}

export function formatTimestamp(value: string): string {
  if (!value) {
    return 'yok';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat('tr-TR', {
    hour: '2-digit',
    minute: '2-digit',
    day: '2-digit',
    month: 'short',
  }).format(date);
}

export function runtimePayloadReady(value: unknown): boolean {
  const runtime = asRecord(value);
  return asBoolean(runtime.runtimeReady) || asString(runtime.phase) === 'ready' || asString(runtime.runtimeLifecycleState) === 'ready';
}

export function runtimeResponseErrorCode(response: RuntimeResponse | null): string {
  const result = asRecord(response?.result);
  const resultError = asRecord(result.error);
  return asString(response?.error?.code ?? resultError.code ?? result.error ?? result.reason);
}

function scalarText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = scalarText(value).trim();
    if (text) return text;
  }
  return '';
}

const ASSISTANT_BLOCK_TYPE_ALIASES: Record<string, string> = {
  colored_table: 'table',
  data_table: 'table',
  dynamic_chart: 'chart',
  echarts: 'chart',
  formula: 'math',
  graph: 'chart',
  latex: 'math',
};

function normalizeAssistantBlockType(value: unknown): string {
  const type = asString(value).trim().toLowerCase();
  return ASSISTANT_BLOCK_TYPE_ALIASES[type] ?? type;
}

function blockDataRecord(block: PlainRecord): PlainRecord {
  return asRecord(block.data ?? block.raw);
}

function cleanStructuredText(value: unknown): string {
  const record = asRecord(value);
  const raw = Object.keys(record).length > 0
    ? firstText(record.value, record.label, record.title, record.text, record.content, record.name, record.key, record.id)
    : scalarText(value);
  return raw
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p\s*>/gi, '\n')
    .replace(/<\/?[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function numberFrom(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value.replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function messageBlocksFromRecord(record: PlainRecord, meta: PlainRecord): PlainRecord[] {
  const contentBlob = asRecord(record.contentBlob ?? record.content_blob);
  const contentRecord = asRecord(record.content);
  const messageRecord = asRecord(record.message);
  const candidates = [
    record.blocks,
    meta.blocks,
    contentBlob.blocks,
    contentRecord.blocks,
    messageRecord.blocks,
  ];
  for (const candidate of candidates) {
    const blocks = asArray(candidate)
      .map((item): PlainRecord => {
        if (typeof item === 'string') {
          return { type: 'text', markdown: item };
        }
        const block = asRecord(item);
        const type = normalizeAssistantBlockType(block.type ?? block.kind);
        return type ? { ...block, type } : block;
      })
      .filter((item) => (
        Object.keys(item).length > 0 &&
        asString(item.visibility).trim().toLowerCase() !== 'assistant_internal_by_default'
      ));
    if (blocks.length > 0) {
      return blocks;
    }
  }
  return [];
}

function tableTextFromBlock(block: PlainRecord, data: PlainRecord): string {
  const rawColumns = asArray(block.columns).length > 0
    ? asArray(block.columns)
    : asArray(block.headers).length > 0
      ? asArray(block.headers)
      : asArray(data.columns).length > 0
        ? asArray(data.columns)
        : asArray(data.headers);
  const rawRows = asArray(block.rows).length > 0
    ? asArray(block.rows)
    : asArray(block.items).length > 0
      ? asArray(block.items)
      : asArray(block.data).length > 0
        ? asArray(block.data)
        : asArray(data.rows).length > 0
          ? asArray(data.rows)
          : asArray(data.data).length > 0
            ? asArray(data.data)
            : asArray(data.items);
  const columns = rawColumns.map(cleanStructuredText).filter(Boolean);
  const inferredColumns = columns.length > 0
    ? columns
    : rawRows.reduce<string[]>((acc, row) => {
      if (acc.length > 0) return acc;
      const record = asRecord(row);
      if (Object.keys(record).length > 0) {
        return Object.keys(record).map(cleanStructuredText).filter(Boolean);
      }
      if (Array.isArray(row)) {
        return Array.from({ length: row.length }, (_, index) => `Sütun ${index + 1}`);
      }
      return acc;
    }, []);
  const rows = rawRows
    .map((row) => {
      if (Array.isArray(row)) {
        return row.map(cleanStructuredText).filter(Boolean).join(' | ');
      }
      const record = asRecord(row);
      if (Object.keys(record).length === 0) {
        return cleanStructuredText(row);
      }
      if (inferredColumns.length > 0) {
        const ordered = inferredColumns.map((column) => cleanStructuredText(record[column] ?? record[column.toLowerCase()])).filter(Boolean);
        if (ordered.length > 0) return ordered.join(' | ');
      }
      return Object.values(record).map(cleanStructuredText).filter(Boolean).join(' | ');
    })
    .filter(Boolean);
  return [inferredColumns.join(' | '), ...rows].filter(Boolean).join('\n');
}

function chartTextFromBlock(block: PlainRecord, data: PlainRecord): string {
  const rawPoints = asArray(block.points).length > 0
    ? asArray(block.points)
    : asArray(block.values).length > 0
      ? asArray(block.values)
      : asArray(block.items).length > 0
        ? asArray(block.items)
        : asArray(block.data).length > 0
          ? asArray(block.data)
          : asArray(data.points).length > 0
            ? asArray(data.points)
            : asArray(data.data).length > 0
              ? asArray(data.data)
              : asArray(data.items);
  return rawPoints
    .map((point) => {
      const record = asRecord(point);
      const value = numberFrom(record.value ?? record.y ?? record.v ?? record.count ?? record.total);
      const label = firstText(record.label, record.x, record.name, record.key);
      return label && value !== null ? `${label}: ${value}` : '';
    })
    .filter(Boolean)
    .join('\n');
}

function taskTraceTextFromBlock(block: PlainRecord, data: PlainRecord): string {
  const trace = asRecord(block.trace ?? data);
  const rawSteps = asArray(block.steps).length > 0
    ? asArray(block.steps)
    : asArray(block.items).length > 0
      ? asArray(block.items)
      : asArray(trace.steps).length > 0
        ? asArray(trace.steps)
        : asArray(trace.items);
  const steps = rawSteps
    .map((step) => {
      const record = asRecord(step);
      const label = firstText(record.label, record.title, record.capability, record.value);
      const status = firstText(record.status, record.state);
      return [label, status].filter(Boolean).join(' - ');
    })
    .filter(Boolean);
  return [firstText(block.title, trace.title), firstText(block.summary, trace.summary, trace.description), ...steps]
    .filter(Boolean)
    .join('\n');
}

function messageTextFromBlock(block: PlainRecord): string {
  const data = blockDataRecord(block);
  const direct = firstText(
    block.markdown,
    block.content,
    block.text,
    block.body,
    block.message,
    block.summary,
    block.value,
    block.description,
    data.markdown,
    data.content,
    data.text,
    data.body,
    data.message,
    data.summary,
    data.value,
    data.description,
  );
  if (direct) return direct;
  const type = normalizeAssistantBlockType(block.type);
  if (type === 'code') {
    return firstText(block.code, data.code);
  }
  if (type === 'table') {
    return tableTextFromBlock(block, data);
  }
  if (type === 'chart') {
    return chartTextFromBlock(block, data);
  }
  if (type === 'file') {
    return [
      firstText(block.name, block.filename, block.fileName, data.name, data.filename, data.fileName),
      firstText(block.preview, block.previewText, data.preview, data.previewText),
    ].filter(Boolean).join('\n');
  }
  if (type === 'task_trace') {
    return taskTraceTextFromBlock(block, data);
  }
  if (type === 'math') {
    return firstText(block.content, block.latex, block.markdown, data.content, data.latex, data.markdown);
  }
  if (type === 'artifact') {
    return [
      firstText(block.title, data.title),
      firstText(block.mime, block.mimeType, data.mime, data.mimeType),
      firstText(block.url, block.uri, data.url, data.uri),
    ].filter(Boolean).join('\n');
  }
  return '';
}

function compactForCompletenessCompare(value: string): string {
  return value.replace(/\s+/g, ' ').trim().toLowerCase();
}

function hasOddTokenCount(value: string, token: string): boolean {
  let count = 0;
  let start = 0;
  while (true) {
    const index = value.indexOf(token, start);
    if (index < 0) return count % 2 === 1;
    count += 1;
    start = index + token.length;
  }
}

function looksLikeIncompleteAssistantTail(value: string): boolean {
  const text = value.trimEnd();
  if (!text) return true;
  if (hasOddTokenCount(text, '```') || hasOddTokenCount(text, '~~~') || hasOddTokenCount(text, '**') || hasOddTokenCount(text, '__')) {
    return true;
  }
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  const lastLine = lines.at(-1) ?? '';
  const startsListItem = /^(?:[-*+]|\d+[.)])\s+/.test(lastLine);
  const hasTerminalPunctuation = /[.!?:;,\)\]}'">]$/.test(lastLine);
  return startsListItem && !hasTerminalPunctuation && lastLine.length <= 80;
}

function completeMessageText(blockText: string, directText: string): string {
  const current = blockText.trim();
  const fallback = directText.trim();
  if (!fallback) return current;
  if (!current) return fallback;
  const compactCurrent = compactForCompletenessCompare(current);
  const compactFallback = compactForCompletenessCompare(fallback);
  if (!compactCurrent || !compactFallback || compactCurrent === compactFallback || compactCurrent.includes(compactFallback)) {
    return current;
  }
  if (compactFallback.includes(compactCurrent) && compactFallback.length > compactCurrent.length) {
    return fallback;
  }
  if (looksLikeIncompleteAssistantTail(current) && compactFallback.length > compactCurrent.length) {
    return fallback;
  }
  if (compactFallback.length >= compactCurrent.length + 32) {
    return fallback;
  }
  return current;
}

function conversationFromRecord(record: PlainRecord, index: number): ConversationView {
  const id = asString(record.id ?? record.conversationId, `conversation_${index}`);
  const messages = asArray(record.messages).map((message, messageIndex) => messageFromRecord(asRecord(message), messageIndex));
  const preview = asString(record.preview) || messages.at(-1)?.text || 'Yeni konuşma';
  return {
    id,
    title: asString(record.title, `Konuşma ${index + 1}`),
    preview,
    updatedAt: asString(record.updatedAt ?? record.createdAt),
    messages,
  };
}

function messageFromRecord(record: PlainRecord, index: number): MessageView {
  const roleValue = asString(record.role, 'assistant');
  const role = roleValue === 'user' || roleValue === 'system' ? roleValue : 'assistant';
  const meta = asRecord(record.meta ?? record.extra);
  const blocks = messageBlocksFromRecord(record, meta);
  const textFromBlocks = blocks
    .map((block) => messageTextFromBlock(block).trim())
    .filter(Boolean)
    .join('\n\n');
  const directText = firstText(record.text, record.content, record.message, record.delta, meta.text, meta.delta);
  const completeText = completeMessageText(textFromBlocks, directText);
  return {
    id: asString(record.id, `message_${index}`),
    role,
    text: completeText || directText,
    blocks,
    meta,
    pendingPlanId: asString(meta.pendingPlanId ?? record.pendingPlanId),
    needsConfirmation: asBoolean(meta.needsConfirmation ?? record.needsConfirmation),
    errorCode: asString(meta.errorCode ?? record.errorCode),
  };
}

function conversationItemsFromSnapshot(snapshot: BootstrapSnapshot | null, archived: boolean | null): ConversationView[] {
  const stateConversation = asRecord(stateRecord(snapshot).conversation);
  const stateItems = asArray(stateConversation.items);
  const rawItems = stateItems.length > 0 ? stateItems : asArray(snapshot?.conversations);
  return rawItems
    .map((item, index) => ({ item: asRecord(item), conversation: conversationFromRecord(asRecord(item), index) }))
    .filter(({ item, conversation }) => {
      if (!conversation.id.length) {
        return false;
      }
      if (archived === null) {
        return true;
      }
      return archived ? item.archived === true : item.archived !== true;
    })
    .map(({ conversation }) => conversation);
}

export function toJsonMap(value: PlainRecord): JsonMap {
  return value as Record<string, JsonValue>;
}
