import type { BootstrapSnapshot } from '../../shared/protocol';
import type { ListSurfaceItem, ListSurfaceStatusTone } from '../panels/ListSurface';
import { asArray, asRecord } from './data';

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

export function itemsFromRuntimeList(surface: 'apps' | 'skills' | 'archives' | 'tasks', payload: unknown, _snapshot: BootstrapSnapshot | null): ListSurfaceItem[] {
  const result = asRecord(payload);
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

  if (surface === 'tasks') {
    const rawItems = arrayFrom(result.tasks ?? asRecord(result.data).tasks);
    return rawItems.map((item, index) => {
      const record = asRecord(item);
      const routeDecision = asRecord(record.routeDecision);
      const approvalRequest = asRecord(record.approvalRequest);
      const status = asString(record.status);
      const statusLabel =
        status === 'waiting_approval'
          ? 'onay bekliyor'
          : status === 'running'
            ? 'çalışıyor'
            : status === 'completed'
              ? 'tamamlandı'
              : status || 'beklemede';
      const artifactCount = Number(record.artifactCount ?? 0);
      const details = [approvalRequest.kind ? `İzin türü: ${asString(approvalRequest.kind)}` : '', asString(record.summary)].filter(Boolean).join(' · ');
      return {
        id: asString(record.id) || `task_${index}`,
        title: asString(record.title) || `Görev ${index + 1}`,
        subtitle: asString(record.summary) || 'Görev kaydı',
        details,
        meta: asString(routeDecision.route),
        status: statusLabel,
        statusTone: status === 'waiting_approval' ? 'warning' : status === 'completed' ? 'success' : 'neutral',
        badges: [artifactCount > 0 ? `${artifactCount} artifact` : '', asString(record.route), asString(record.intent)].filter(Boolean),
      };
    });
  }

  if (surface === 'archives') {
    const rawItems = arrayFrom(result.conversations ?? result.archivedConversations ?? result.items ?? result.archives);
    return rawItems.map((item, index) => {
      const record = asRecord(item);
      const messageCount = Number(record.messageCount ?? asArray(record.messages).length ?? 0);
      return {
        id: asString(record.id) || `archive_${index}`,
        title: asString(record.title) || `Sohbet ${index + 1}`,
        subtitle: asString(record.preview) || 'Arşivlenmiş sohbet',
        details: messageCount > 0 ? `${messageCount} mesaj` : '',
        meta: asString(record.updatedAt),
        status: 'arşiv',
        statusTone: 'neutral',
        badges: ['conversation', 'archive'].filter(Boolean),
      };
    });
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
        asString(record.adapter),
        ...arrayFrom(record.libraries).map((item) => asString(item)).filter(Boolean).slice(0, 3),
        record.requiresConfirmation === true ? 'onay gerekli' : '',
      ].filter(Boolean),
    };
  });
}
