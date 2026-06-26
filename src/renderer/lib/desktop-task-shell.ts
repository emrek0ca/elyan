import type { BootstrapSnapshot } from '../../shared/protocol';
import {
  asArray,
  asBoolean,
  asRecord,
  asString,
  backendRecord,
  backendResultData,
  brainProfileRecord,
  runtimeRecord,
  runtimeSessionConnectionRecord,
  runtimeSessionDeviceRecord,
  runtimeSessionReadinessRecord,
  stateRecord,
} from './data';

export type DesktopTaskShellStatusTone = 'success' | 'warning' | 'danger' | 'neutral';

export interface DesktopTaskShellTask {
  id: string;
  title: string;
  summary: string;
  status: string;
  statusLabel: string;
  statusTone: DesktopTaskShellStatusTone;
  route: string;
  updatedAt: string;
  approvalKind: string;
  requiresApproval: boolean;
  artifactCount: number;
}

export interface DesktopTaskShellView {
  readinessToken: 'ready' | 'connecting' | 'reconnecting' | 'blocked' | 'offline';
  readinessLabel: string;
  readinessDetail: string;
  readinessTone: DesktopTaskShellStatusTone;
  desktopHeadline: string;
  connectionSummary: string;
  modelLabel: string;
  learningLabel: string;
  retrievalLabel: string;
  pendingRemoteTaskCount: number;
  activeRemoteTaskCount: number;
  approvalTasks: DesktopTaskShellTask[];
  recentTasks: DesktopTaskShellTask[];
  canReceiveTasks: boolean;
  canExecuteAssignedTasks: boolean;
  powerCapabilityCount: number;
  blockedCapabilityCount: number;
}

function numberFrom(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const text = asString(value).trim();
    if (text) {
      return text;
    }
  }
  return '';
}

function statusLabel(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'waiting_approval') return 'onay bekliyor';
  if (normalized === 'queued') return 'sırada';
  if (normalized === 'planning') return 'planlanıyor';
  if (normalized === 'running') return 'çalışıyor';
  if (normalized === 'completed' || normalized === 'succeeded') return 'tamamlandı';
  if (normalized === 'failed' || normalized === 'error') return 'başarısız';
  if (normalized === 'canceled' || normalized === 'cancelled') return 'iptal edildi';
  return normalized || 'beklemede';
}

function statusTone(status: string): DesktopTaskShellStatusTone {
  const normalized = status.trim().toLowerCase();
  if (normalized === 'completed' || normalized === 'succeeded') return 'success';
  if (normalized === 'waiting_approval' || normalized === 'queued' || normalized === 'planning') return 'warning';
  if (normalized === 'failed' || normalized === 'error' || normalized === 'canceled' || normalized === 'cancelled') return 'danger';
  return normalized === 'running' ? 'neutral' : 'neutral';
}

function taskFromRecord(value: unknown, index: number): DesktopTaskShellTask | null {
  const task = asRecord(value);
  const id = firstText(task.id, task.taskId);
  if (!id) {
    return null;
  }
  const routeDecision = asRecord(task.routeDecision);
  const approvalRequest = asRecord(task.approvalRequest ?? task.approval);
  const status = firstText(task.status, task.state) || 'queued';
  const artifactCount = numberFrom(task.artifactCount ?? asArray(task.artifacts).length);
  return {
    id,
    title: firstText(task.title, task.intent, task.prompt) || `Görev ${index + 1}`,
    summary: firstText(task.summary, task.error, task.description),
    status,
    statusLabel: statusLabel(status),
    statusTone: statusTone(status),
    route: firstText(routeDecision.route, task.route, task.requiredRuntime),
    updatedAt: firstText(task.updatedAt, task.lastDispatchAttemptAt, task.createdAt),
    approvalKind: firstText(approvalRequest.kind, approvalRequest.type, approvalRequest.capability),
    requiresApproval: Object.keys(approvalRequest).length > 0 && approvalRequest.resolved !== true,
    artifactCount,
  };
}

function taskInbox(snapshot: BootstrapSnapshot | null): Record<string, unknown> {
  const runtime = runtimeRecord(snapshot);
  const state = stateRecord(snapshot);
  const directRuntimeInbox = asRecord(runtime.taskInbox);
  if (Object.keys(directRuntimeInbox).length > 0) {
    return directRuntimeInbox;
  }
  return asRecord(state.taskInbox);
}

function bootstrapRecentTasks(snapshot: BootstrapSnapshot | null): unknown[] {
  const backend = backendRecord(snapshot);
  const bootstrap = backendResultData(backend.mobileBootstrap);
  return asArray(bootstrap.recentTasks ?? bootstrap.historyTasks);
}

function uniqueTasks(tasks: Array<DesktopTaskShellTask | null>): DesktopTaskShellTask[] {
  const byId = new Map<string, DesktopTaskShellTask>();
  for (const task of tasks) {
    if (!task) continue;
    byId.set(task.id, task);
  }
  return [...byId.values()].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)).slice(0, 8);
}

function taskList(snapshot: BootstrapSnapshot | null): DesktopTaskShellTask[] {
  const inbox = taskInbox(snapshot);
  const inboxItems = asArray(inbox.items);
  return uniqueTasks([
    ...inboxItems.map(taskFromRecord),
    ...bootstrapRecentTasks(snapshot).map(taskFromRecord),
  ]);
}

function capabilityCounts(snapshot: BootstrapSnapshot | null): { power: number; blocked: number } {
  const runtime = runtimeRecord(snapshot);
  const metadata = asRecord(runtime.runtimeCapabilityMetadataSummary);
  const groups = asRecord(runtime.runtimeCapabilityGroups);
  const states = asRecord(runtime.runtimeCapabilityStates);
  let power = numberFrom(runtime.runtimeCapabilityCount);
  if (!power) {
    power = asArray(runtime.runtimeCapabilities).length;
  }
  if (!power) {
    power = Object.values(groups).reduce<number>((count, group) => count + asArray(group).length, 0);
  }
  let blocked = numberFrom(metadata.blockedCount ?? metadata.blockedCapabilityCount);
  if (!blocked) {
    blocked = Object.values(states).filter((value) => {
      const state = asRecord(value);
      return asBoolean(state.available) === false || asString(state.status).toLowerCase() === 'blocked';
    }).length;
  }
  return { power, blocked };
}

function runtimeReadiness(snapshot: BootstrapSnapshot | null): Pick<
  DesktopTaskShellView,
  'readinessToken' | 'readinessLabel' | 'readinessDetail' | 'readinessTone' | 'canReceiveTasks'
> {
  const runtime = runtimeRecord(snapshot);
  const readiness = runtimeSessionReadinessRecord(snapshot);
  const connection = runtimeSessionConnectionRecord(snapshot);
  const runtimeLifecycle = firstText(runtime.runtimeLifecycleState, runtime.phase).toLowerCase();
  const targetStatus = firstText(readiness.targetStatus, runtime.targetStatus).toLowerCase();
  const targetError = firstText(readiness.targetErrorCode, runtime.targetErrorCode, runtime.lastErrorCode).toLowerCase();
  const connectionStatus = firstText(connection.status).toLowerCase();
  const websocketConnected = asBoolean(runtime.runtimeWebsocketConnected);
  const canReceiveTasks = readiness.canReceiveTasks === true;
  const runtimeReady = asBoolean(runtime.runtimeReady) || runtimeLifecycle === 'ready' || targetStatus === 'ready';

  if (canReceiveTasks && (runtimeReady || websocketConnected || connectionStatus === 'online')) {
    return {
      readinessToken: 'ready',
      readinessLabel: 'Desktop görev almaya hazır',
      readinessDetail: 'Mobil ve backend üzerinden gelen görevler bu runtime tarafından yürütülebilir.',
      readinessTone: 'success',
      canReceiveTasks: true,
    };
  }
  if (targetError || ['plan_restricted', 'desktop_plan_required', 'desktop_limit_reached'].includes(targetStatus)) {
    return {
      readinessToken: 'blocked',
      readinessLabel: 'Desktop görev alımı kısıtlı',
      readinessDetail: targetError || targetStatus || 'Backend runtime hedefini görev alımına açmadı.',
      readinessTone: 'warning',
      canReceiveTasks: false,
    };
  }
  if (runtimeLifecycle === 'runtime_connecting' || runtimeLifecycle === 'starting' || targetStatus === 'claimed') {
    return {
      readinessToken: 'connecting',
      readinessLabel: 'Runtime bağlanıyor',
      readinessDetail: 'Masaüstü runtime kayıt/heartbeat kanalını açıyor.',
      readinessTone: 'warning',
      canReceiveTasks: false,
    };
  }
  if (runtimeLifecycle === 'reconnecting') {
    return {
      readinessToken: 'reconnecting',
      readinessLabel: 'Yeniden bağlanıyor',
      readinessDetail: 'Görev relay güvenli aralıklarla tekrar denenecek.',
      readinessTone: 'warning',
      canReceiveTasks: false,
    };
  }
  return {
    readinessToken: 'offline',
    readinessLabel: 'Desktop çevrimdışı',
    readinessDetail: 'Mobil görevleri backend kuyruğunda kalır; runtime hazır olunca alınır.',
    readinessTone: 'neutral',
    canReceiveTasks: false,
  };
}

function desktopHeadline(snapshot: BootstrapSnapshot | null): string {
  const device = runtimeSessionDeviceRecord(snapshot);
  return firstText(device.name, device.label, device.hostname, 'Elyan Desktop');
}

function brainLabels(snapshot: BootstrapSnapshot | null): Pick<DesktopTaskShellView, 'modelLabel' | 'learningLabel' | 'retrievalLabel'> {
  const brain = brainProfileRecord(snapshot);
  const chat = asRecord(brain.chat);
  const learning = asRecord(brain.learning);
  const retrieval = asRecord(brain.retrieval);
  const modelLabel = firstText(chat.serverBrainName, asRecord(chat.activeSharedModel).shortLabel, 'Elyan beyni');
  const safeSignals = numberFrom(learning.safeLearningEvents);
  const learningEnabled = learning.personalizationEnabled === true || learning.userUnderstandingEnabled === true;
  const learningLabel = learningEnabled
    ? `Kişiselleştirme açık${safeSignals > 0 ? ` · ${safeSignals} güvenli sinyal` : ''}`
    : 'Öğrenme pasif';
  const retrievalLabel = numberFrom(retrieval.readyDocuments) || numberFrom(retrieval.readyChunks)
    ? `${numberFrom(retrieval.readyDocuments)} belge · ${numberFrom(retrieval.readyChunks)} parça`
    : 'Retrieval bilgisi yok';
  return { modelLabel, learningLabel, retrievalLabel };
}

export function deriveDesktopTaskShell(snapshot: BootstrapSnapshot | null): DesktopTaskShellView {
  const inbox = taskInbox(snapshot);
  const tasks = taskList(snapshot);
  const approvals = tasks.filter((task) => task.requiresApproval || task.status.trim().toLowerCase() === 'waiting_approval');
  const readiness = runtimeReadiness(snapshot);
  const counts = capabilityCounts(snapshot);
  const labels = brainLabels(snapshot);
  const pendingRemoteTaskCount = numberFrom(inbox.pendingCount) || tasks.filter((task) => ['queued', 'planning', 'waiting_approval'].includes(task.status.toLowerCase())).length;
  const activeRemoteTaskCount = numberFrom(inbox.activeCount) || tasks.filter((task) => task.status.toLowerCase() === 'running').length;
  const relay = firstText(runtimeRecord(snapshot).runtimeRelayState);
  return {
    ...readiness,
    ...labels,
    desktopHeadline: desktopHeadline(snapshot),
    connectionSummary: [
      readiness.readinessLabel,
      pendingRemoteTaskCount > 0 ? `${pendingRemoteTaskCount} bekleyen görev` : '',
      activeRemoteTaskCount > 0 ? `${activeRemoteTaskCount} aktif görev` : '',
      relay ? `relay=${relay}` : '',
    ].filter(Boolean).join(' · '),
    pendingRemoteTaskCount,
    activeRemoteTaskCount,
    approvalTasks: approvals.slice(0, 3),
    recentTasks: tasks,
    canExecuteAssignedTasks: readiness.canReceiveTasks || pendingRemoteTaskCount > 0 || activeRemoteTaskCount > 0,
    powerCapabilityCount: counts.power,
    blockedCapabilityCount: counts.blocked,
  };
}
