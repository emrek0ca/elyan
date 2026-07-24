export type RealtimeMessage = Record<string, unknown> & { id?: string; content?: string; blocks?: unknown[]; status?: string };

export type RealtimeState = {
  messages: Map<string, RealtimeMessage>;
  terminalMessageIds: Set<string>;
  seenEventIds: Set<string>;
  messageSessionIds: Map<string, string>;
};

export function createRealtimeState(): RealtimeState {
  return { messages: new Map(), terminalMessageIds: new Set(), seenEventIds: new Set(), messageSessionIds: new Map() };
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function firstString(...values: unknown[]): string {
  return values.find((value) => typeof value === 'string' && value.trim()) as string || '';
}

type MergeResult = { changedId: string | null; terminal: boolean; resync: boolean; sessionId: string | null };

export function mergeMessageSnapshot(state: RealtimeState, message: RealtimeMessage, sessionId?: string | null): RealtimeMessage {
  const messageId = firstString(message.id);
  if (!messageId) return message;
  const current = state.messages.get(messageId) || { id: messageId };
  const incomingCompleted = firstString(message.status) === 'completed';
  if (state.terminalMessageIds.has(messageId) && !incomingCompleted) return current;
  const merged = { ...current, ...message, id: messageId };
  state.messages.set(messageId, merged);
  const resolvedSessionId = firstString(sessionId, message.sessionId, current.sessionId);
  if (resolvedSessionId) state.messageSessionIds.set(messageId, resolvedSessionId);
  if (incomingCompleted) state.terminalMessageIds.add(messageId);
  return merged;
}

export function mergeRealtimeEvent(state: RealtimeState, event: Record<string, unknown>): MergeResult {
  const eventId = firstString(event.eventId, event.cursor, event.id);
  if (eventId && state.seenEventIds.has(eventId)) return { changedId: null, terminal: false, resync: false, sessionId: null };
  if (eventId) {
    state.seenEventIds.add(eventId);
    if (state.seenEventIds.size > 1000) state.seenEventIds.delete(state.seenEventIds.values().next().value as string);
  }

  const type = firstString(event.type, event.topic);
  if (type === 'resync_required' || type.endsWith('.resync_required')) return { changedId: null, terminal: false, resync: true, sessionId: null };
  const payload = object(event.payload);
  const nestedMessage = object(payload.assistantMessage || payload.message);
  const messageId = firstString(payload.assistantMessageId, payload.messageId, nestedMessage.id, event.aggregateId);
  if (!messageId) return { changedId: null, terminal: false, resync: false, sessionId: null };
  const sessionId = firstString(payload.sessionId, nestedMessage.sessionId, state.messageSessionIds.get(messageId));
  if (sessionId) state.messageSessionIds.set(messageId, sessionId);

  const completed = type === 'message.completed' || type.endsWith('.message.completed');
  if (completed) {
    const current = state.messages.get(messageId) || { id: messageId };
    state.messages.set(messageId, { ...current, ...nestedMessage, id: messageId, content: firstString(nestedMessage.content, payload.content, current.content), blocks: Array.isArray(nestedMessage.blocks) ? nestedMessage.blocks : Array.isArray(payload.blocks) ? payload.blocks : current.blocks, status: 'completed' });
    state.terminalMessageIds.add(messageId);
    return { changedId: messageId, terminal: true, resync: false, sessionId: sessionId || null };
  }

  if (state.terminalMessageIds.has(messageId)) return { changedId: null, terminal: false, resync: false, sessionId: sessionId || null };
  const current = state.messages.get(messageId) || { id: messageId };
  const delta = firstString(payload.delta, nestedMessage.delta);
  const fullContent = firstString(nestedMessage.content, payload.content);
  const content = fullContent || (delta ? `${firstString(current.content)}${delta}` : firstString(current.content));
  const blocks = Array.isArray(nestedMessage.blocks) ? nestedMessage.blocks : Array.isArray(payload.blocks) ? payload.blocks : current.blocks;
  state.messages.set(messageId, { ...current, ...nestedMessage, id: messageId, content, blocks, status: firstString(payload.status, nestedMessage.status, current.status, 'running'), ...(sessionId ? { sessionId } : {}) });
  return { changedId: messageId, terminal: false, resync: false, sessionId: sessionId || null };
}
