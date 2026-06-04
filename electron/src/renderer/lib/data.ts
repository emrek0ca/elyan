import type { BootstrapSnapshot, JsonMap, JsonValue, RuntimeResponse } from '../../shared/protocol';

export interface MessageView {
  id: string;
  role: 'user' | 'assistant' | 'system';
  text: string;
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
  const stateConversation = asRecord(stateRecord(snapshot).conversation);
  const stateItems = asArray(stateConversation.items);
  const rawItems = stateItems.length > 0 ? stateItems : asArray(snapshot?.conversations);
  return rawItems.map((item, index) => conversationFromRecord(asRecord(item), index)).filter((item) => item.id.length > 0);
}

export function activeConversationId(snapshot: BootstrapSnapshot | null): string {
  const stateConversation = asRecord(stateRecord(snapshot).conversation);
  const activeId = asString(stateConversation.activeId);
  if (activeId) {
    return activeId;
  }
  return snapshotConversations(snapshot)[0]?.id ?? '';
}

export function selectedConversation(snapshot: BootstrapSnapshot | null, selectedId: string): ConversationView | null {
  const conversations = snapshotConversations(snapshot);
  return conversations.find((conversation) => conversation.id === selectedId) ?? conversations[0] ?? null;
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
  return asRecord(backend.authMe ?? backend.auth ?? stateRecord(snapshot).auth);
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
  return {
    id: asString(record.id, `message_${index}`),
    role,
    text: asString(record.text ?? record.content ?? record.message),
    meta,
    pendingPlanId: asString(meta.pendingPlanId ?? record.pendingPlanId),
    needsConfirmation: asBoolean(meta.needsConfirmation ?? record.needsConfirmation),
    errorCode: asString(meta.errorCode ?? record.errorCode),
  };
}

export function toJsonMap(value: PlainRecord): JsonMap {
  return value as Record<string, JsonValue>;
}
