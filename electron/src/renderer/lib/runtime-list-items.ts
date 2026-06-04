import type { BootstrapSnapshot } from '../../shared/protocol';
import type { ListSurfaceItem, ListSurfaceStatusTone } from '../panels/ListSurface';
import { asArray, asRecord, snapshotConversations } from './data';

function asString(value: unknown): string {
  return String(value ?? '').trim();
}

function arrayFrom(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function backendResultData(value: unknown): Record<string, unknown> {
  const record = asRecord(value);
  return asRecord(record.data ?? asRecord(record.result).data);
}

export function operatorErrorMessage(raw: unknown): string {
  const value = asString(raw);
  if (!value) {
    return '';
  }
  if (value === 'DEPENDENCY_UNAVAILABLE') {
    return 'Bağımlılık eksik';
  }
  if (value === 'MCP_SERVER_INVALID') {
    return 'Sunucu yapılandırması geçersiz';
  }
  if (value === 'MCP_SERVER_UNAVAILABLE') {
    return 'Sunucuya ulaşılamıyor';
  }
  if (value === 'MCP_SERVER_DISABLED') {
    return 'Sunucu kapalı';
  }
  if (value === 'MCP_TOOL_TIMEOUT') {
    return 'MCP zaman aşımı';
  }
  if (value === 'SKILL_MANIFEST_INVALID') {
    return 'Skill manifest geçersiz';
  }
  if (value === 'DEPENDENCY_UNAVAILABLE' || value.endsWith('_MISSING')) {
    return 'Gerekli yetenek hazır değil';
  }
  return value;
}

export function mcpStatusSummary(value: unknown): string {
  const status = asRecord(value);
  const parts: string[] = [];
  if (typeof status.available === 'boolean') {
    parts.push(`available=${status.available}`);
  }
  if (typeof status.serverCount === 'number') {
    parts.push(`servers=${status.serverCount}`);
  } else if (Array.isArray(status.servers)) {
    parts.push(`servers=${status.servers.length}`);
  }
  if (typeof status.toolCount === 'number') {
    parts.push(`tools=${status.toolCount}`);
  }
  const errorCode = asString(status.lastErrorCode);
  if (errorCode) {
    parts.push(`error=${errorCode}`);
  }
  return parts.join(' ') || 'missing';
}

export function skillStatusSummary(value: unknown): string {
  const status = asRecord(value);
  const parts: string[] = [];
  if (typeof status.available === 'boolean') {
    parts.push(`available=${status.available}`);
  }
  if (typeof status.manifestCount === 'number') {
    parts.push(`manifests=${status.manifestCount}`);
  }
  if (typeof status.activeSkillCount === 'number') {
    parts.push(`active=${status.activeSkillCount}`);
  }
  if (typeof status.blockedSkillCount === 'number') {
    parts.push(`blocked=${status.blockedSkillCount}`);
  }
  const errorCode = asString(status.lastErrorCode);
  if (errorCode) {
    parts.push(`error=${errorCode}`);
  }
  return parts.join(' ') || 'missing';
}

function mcpServerState(server: Record<string, unknown>): { status: string; tone: ListSurfaceStatusTone; detail: string } {
  const errorCode = asString(server.lastErrorCode);
  if (server.enabled !== true) {
    return { status: 'kapalı', tone: 'neutral', detail: operatorErrorMessage(errorCode) || 'Sunucu kapalı' };
  }
  if (server.connected === true) {
    const toolCount = Number(server.toolCount ?? 0);
    return {
      status: toolCount > 0 ? 'hazır' : 'araç yok',
      tone: toolCount > 0 ? 'success' : 'warning',
      detail: toolCount > 0 ? '' : 'Bu sunucuda görünür araç yok',
    };
  }
  return {
    status: operatorErrorMessage(errorCode) || 'ulaşılamıyor',
    tone: errorCode === 'DEPENDENCY_UNAVAILABLE' ? 'warning' : 'danger',
    detail: asString(server.lastErrorMessage) || operatorErrorMessage(errorCode),
  };
}

function skillState(skill: Record<string, unknown>): { status: string; tone: ListSurfaceStatusTone; detail: string } {
  if (skill.enabled !== true) {
    return { status: 'kapalı', tone: 'neutral', detail: '' };
  }
  if (skill.available === true) {
    return { status: 'hazır', tone: 'success', detail: '' };
  }
  const dependencySummary = asRecord(skill.dependencySummary);
  const blocked = asArray(dependencySummary.blockedCapabilities).map((item) => asString(item)).filter(Boolean);
  return {
    status: 'dependency eksik',
    tone: 'warning',
    detail: blocked.length > 0 ? `Bloke: ${blocked.join(', ')}` : operatorErrorMessage(skill.lastErrorCode) || asString(skill.lastErrorMessage),
  };
}

function taskState(task: Record<string, unknown>): { status: string; tone: ListSurfaceStatusTone; detail: string } {
  const status = asString(task.status).toLowerCase();
  const approval = asRecord(task.approvalRequest);
  const error = asString(task.error);
  if (status === 'completed') {
    return { status: 'tamamlandı', tone: 'success', detail: '' };
  }
  if (status === 'failed') {
    return { status: 'başarısız', tone: 'danger', detail: operatorErrorMessage(error) || error };
  }
  if (status === 'canceled' || status === 'cancelled') {
    return { status: 'iptal edildi', tone: 'neutral', detail: '' };
  }
  if (status === 'waiting_approval') {
    const kind = asString(approval.kind);
    return {
      status: 'onay bekliyor',
      tone: 'warning',
      detail: kind ? `İzin türü: ${kind}` : 'Yerel onay gerekiyor',
    };
  }
  if (status === 'running') {
    return { status: 'çalışıyor', tone: 'warning', detail: '' };
  }
  if (status === 'planning') {
    return { status: 'planlanıyor', tone: 'warning', detail: '' };
  }
  if (status === 'queued') {
    return { status: 'kuyrukta', tone: 'neutral', detail: '' };
  }
  return { status: asString(task.status) || 'bilinmiyor', tone: 'neutral', detail: '' };
}

function taskMeta(task: Record<string, unknown>): string {
  return asString(task.updatedAt) || asString(task.startedAt) || asString(task.createdAt);
}

export function itemsFromRuntimeList(surface: 'apps' | 'skills' | 'history' | 'tasks', payload: unknown, snapshot: BootstrapSnapshot | null): ListSurfaceItem[] {
  if (surface === 'history') {
    const result = asRecord(payload);
    const conversations = Array.isArray(result.conversations) ? result.conversations : snapshotConversations(snapshot);
    return conversations.map((item, index) => {
      const record = asRecord(item);
      return {
        id: String(record.id ?? record.conversationId ?? `conversation_${index}`),
        title: String(record.title ?? `Konuşma ${index + 1}`),
        subtitle: String(record.preview ?? record.lastMessage ?? ''),
        meta: String(record.updatedAt ?? record.createdAt ?? ''),
      };
    });
  }

  const result = asRecord(payload);
  if (surface === 'tasks') {
    const inbox = asRecord(asRecord(snapshot?.state).taskInbox);
    const backendData = backendResultData(payload);
    const rawItems = arrayFrom(backendData.tasks);
    const tasks = rawItems.length > 0 ? rawItems : arrayFrom(inbox.items ?? snapshot?.runtime?.taskInbox);
    return tasks.map((item, index) => {
      const record = asRecord(item);
      const state = taskState(record);
      const routeDecision = asRecord(record.routeDecision);
      const badges = [
        asString(routeDecision.route),
        record.artifactCount ? `${Number(record.artifactCount)} artifact` : '',
        record.approvalRequest && asRecord(record.approvalRequest).kind ? 'onay' : '',
      ].filter(Boolean);
      const subtitle = asString(record.summary) || asString(record.title) || 'Görev güncellemesi';
      return {
        id: asString(record.id) || `task_${index}`,
        title: asString(record.title) || `Görev ${index + 1}`,
        subtitle,
        details: state.detail || asString(record.deliveryState),
        meta: taskMeta(record),
        status: state.status,
        statusTone: state.tone,
        badges,
      };
    });
  }
  if (surface === 'apps') {
    const mcpStatus = asRecord(result.mcpStatus);
    const tools = arrayFrom(result.tools ?? mcpStatus.tools);
    const servers = arrayFrom(mcpStatus.servers);
    const items: ListSurfaceItem[] = tools.map((item, index) => {
      const record = asRecord(item);
      return {
        id: asString(record.serverId) ? `${asString(record.serverId)}:${asString(record.name)}` : `apps_${index}`,
        title: asString(record.name) || `Araç ${index + 1}`,
        subtitle: asString(record.description) || asString(record.serverName) || asString(record.serverId),
        details: '',
        meta: asString(record.serverId),
        status: record.available === false ? operatorErrorMessage(record.availabilityReason) || 'hazır değil' : 'hazır',
        statusTone: record.available === false ? 'warning' : 'success',
        badges: [record.readOnly === true ? 'read-only' : '', asString(record.serverName) || asString(record.serverId)].filter(Boolean),
      };
    });
    const surfacedServers = new Set(items.map((item) => item.meta).filter(Boolean));
    for (const server of servers) {
      const record = asRecord(server);
      const serverId = asString(record.id);
      const state = mcpServerState(record);
      if (!serverId || (state.status === 'hazır' && surfacedServers.has(serverId))) {
        continue;
      }
      items.push({
        id: `server:${serverId}`,
        title: asString(record.name) || serverId,
        subtitle: state.detail || 'MCP sunucu durumu',
        details: '',
        meta: serverId,
        status: state.status,
        statusTone: state.tone,
        badges: ['server'],
      });
    }
    return items;
  }

  const rawItems = arrayFrom(result.skills ?? asRecord(result.skillStatus).skills);
  return rawItems.map((item, index) => {
    const record = asRecord(item);
    const state = skillState(record);
    return {
      id: asString(record.id) || `skill_${index}`,
      title: asString(record.name) || asString(record.id) || `Skill ${index + 1}`,
      subtitle: asString(record.description) || asString(record.path),
      details: state.detail,
      meta: asString(record.path),
      status: state.status,
      statusTone: state.tone,
      badges: [
        asString(record.source) === 'built_in' ? 'built-in' : 'local',
        asString(record.category),
        record.requiresConfirmation === true ? 'onay gerekli' : '',
      ].filter(Boolean),
    };
  });
}
