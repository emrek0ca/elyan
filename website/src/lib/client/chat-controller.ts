import { apiFetch, backendApi, idempotentBackendApi, messageFor, payloadFingerprint, persistentIdempotencyKey } from './api';
import { attachmentPromptLabel, buildAttachmentPayload, buildComposerAttachments, type ComposerAttachment } from './attachments';
import { ASSISTANT_BLOCK_SCHEMA_DIGEST, ASSISTANT_BLOCK_ENVELOPE_VERSION } from './block-contract';
import { renderMessageContent } from './block-registry';
import { createRealtimeState, mergeMessageSnapshot, mergeRealtimeEvent, type RealtimeMessage } from './realtime-merge';

type Session = { id: string; title?: string; status?: string; updatedAt?: string; createdAt?: string };
type SessionList = { sessions?: Session[]; nextCursor?: string | null; hasMore?: boolean };
type MessageList = { messages?: RealtimeMessage[]; nextCursor?: string | null; hasMore?: boolean; session?: Session };

const realtime = createRealtimeState();
const messageNodes = new Map<string, HTMLElement>();
const state = {
  sessionId: null as string | null,
  sessionCursor: null as string | null,
  reconnectAttempt: 0,
  reconnectTimer: 0 as number,
  eventSource: null as EventSource | null,
  disposed: false,
  timelineGeneration: 0,
  attachments: [] as ComposerAttachment[],
  requestedCapabilities: [] as string[],
  capabilityLabels: new Map<string, string>(),
  userName: 'Elyan user',
  contextMenu: null as HTMLElement | null,
};
const CLIP_LIMIT = 280;

function byId<T extends HTMLElement>(id: string): T | null { return document.getElementById(id) as T | null; }
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function string(value: unknown): string { return typeof value === 'string' ? value : ''; }
function firstText(value: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const candidate = string(value[key]);
    if (candidate) return candidate;
  }
  return '';
}
function visibleMessageText(message: RealtimeMessage): string {
  const content = string(message.content);
  if (content) return content;
  if (!Array.isArray(message.blocks)) return '';
  for (const raw of message.blocks) {
    const block = record(raw);
    if (string(block.type) !== 'text') continue;
    const value = record(block.data);
    const markdown = string(block.markdown) || string(value.markdown) || string(value.content);
    if (markdown) return markdown;
  }
  return '';
}
function clip(value: string, max = CLIP_LIMIT): string {
  return value.replace(/\s+/g, ' ').trim().slice(0, max);
}
function messageRole(message: RealtimeMessage): 'user' | 'assistant' | '' {
  const role = string(message.role) || string(message.authorRole) || string(message.sender);
  return role === 'user' || role === 'assistant' ? role : '';
}
function activeSessionMessages(sessionId: string | null): RealtimeMessage[] {
  if (!sessionId) return [];
  return [...realtime.messages.values()]
    .filter((message) => realtime.messageSessionIds.get(string(message.id)) === sessionId)
    .sort((a, b) => {
      const left = Date.parse(string(a.createdAt) || string(a.updatedAt));
      const right = Date.parse(string(b.createdAt) || string(b.updatedAt));
      if (Number.isFinite(left) && Number.isFinite(right) && left !== right) return left - right;
      return 0;
    });
}
export function buildWebCompactContext(messages: RealtimeMessage[], sessionId: string | null, prompt: string, attachmentCount = 0): Record<string, unknown> | null {
  if (!sessionId) return null;
  const visible = messages
    .map((message) => ({ role: messageRole(message), content: clip(visibleMessageText(message), 240) }))
    .filter((message) => message.role && message.content);
  const recentMessages = visible.slice(-6);
  const lastAssistant = [...visible].reverse().find((message) => message.role === 'assistant')?.content || '';
  const compactContext: Record<string, unknown> = {
    mode: 'complete_adaptive',
    source: 'web',
    responseVerbosityHint: prompt.length > 180 || /rapor|detay|ayrıntı|uzun|belge|tablo|grafik|analiz/i.test(prompt) ? 'expanded_when_needed' : 'concise_but_complete',
    wantsLongForm: prompt.length > 180 || /rapor|detay|ayrıntı|uzun|belge|tablo|grafik|analiz/i.test(prompt),
    requireCompleteResponse: true,
    recentMessages,
    sessionScope: { sessionId },
    ...(lastAssistant ? { lastAssistantBlocksDigest: lastAssistant } : {}),
    ...(attachmentCount > 0 ? { attachmentDigest: { attachmentCount } } : {}),
  };
  return recentMessages.length || lastAssistant || attachmentCount > 0 ? compactContext : null;
}

function scrollToBottom(): void {
  const container = byId('messages-container');
  if (container) requestAnimationFrame(() => { container.scrollTop = container.scrollHeight; });
}

function showNotice(message: string, tone: 'error' | 'info' = 'info'): void {
  const notice = byId('app-notice');
  if (!notice) return;
  notice.textContent = message;
  notice.dataset.tone = tone;
  notice.classList.remove('hidden');
  window.setTimeout(() => notice.classList.add('hidden'), 5000);
}

function closeSessionContextMenu(): void {
  state.contextMenu?.remove();
  state.contextMenu = null;
}

async function performSessionAction(session: Session, action: 'rename' | 'archive' | 'restore' | 'delete'): Promise<void> {
  if (action === 'rename') {
    const title = window.prompt('Conversation name', session.title || '');
    if (!title?.trim()) return;
    await backendApi(`chat/sessions/${session.id}`, { method: 'PATCH', body: JSON.stringify({ title: title.trim() }) });
  } else if (action === 'delete') {
    if (!window.confirm('Delete this conversation permanently?')) return;
    await backendApi(`chat/sessions/${session.id}`, { method: 'DELETE' });
    if (state.sessionId === session.id) newChat();
  } else {
    await backendApi(`chat/sessions/${session.id}`, { method: 'PATCH', body: JSON.stringify({ status: action === 'restore' ? 'active' : 'archived' }) });
  }
  await loadSessions();
}

function showSessionContextMenu(session: Session, x: number, y: number): void {
  closeSessionContextMenu();
  const panel = document.createElement('div');
  panel.className = 'fixed z-50 w-40 rounded-[18px] border border-[var(--color-elyan-outline)] bg-[var(--color-elyan-surface)] p-1 shadow-[0_14px_42px_rgba(23,23,23,0.12)]';
  panel.setAttribute('role', 'menu');
  panel.dataset.sessionContextMenu = '1';
  const archiveAction = session.status === 'archived' ? 'restore' : 'archive';
  for (const [label, action] of [['Rename', 'rename'], [session.status === 'archived' ? 'Restore' : 'Archive', archiveAction], ['Delete', 'delete']] as const) {
    const item = document.createElement('button');
    item.type = 'button';
    item.setAttribute('role', 'menuitem');
    item.className = `block w-full rounded-[14px] px-3 py-2 text-left text-xs hover:bg-[var(--color-elyan-surface-muted)] ${action === 'delete' ? 'text-red-600' : 'text-[var(--color-elyan-text)]'}`;
    item.textContent = label;
    item.addEventListener('click', () => {
      closeSessionContextMenu();
      void performSessionAction(session, action).catch((error) => showNotice(messageFor(error), 'error'));
    });
    panel.append(item);
  }
  document.body.append(panel);
  const rect = panel.getBoundingClientRect();
  panel.style.left = `${Math.min(x, window.innerWidth - rect.width - 8)}px`;
  panel.style.top = `${Math.min(y, window.innerHeight - rect.height - 8)}px`;
  state.contextMenu = panel;
}

function assistantShell(id: string): HTMLElement {
  const row = document.createElement('div');
  row.className = 'flex w-full justify-start';
  row.dataset.messageId = id;
  const body = document.createElement('div');
  body.className = 'w-full max-w-none text-[15px] text-[var(--color-elyan-text)] leading-relaxed space-y-4 overflow-hidden';
  body.dataset.messageBody = '1';
  row.append(body);
  return row;
}

function removeEmptyState(): void {
  byId('messages-list')?.querySelector('[data-empty-state]')?.remove();
}

function renderUser(message: RealtimeMessage): void {
  const list = byId('messages-list');
  if (!list) return;
  removeEmptyState();
  const id = string(message.id) || crypto.randomUUID();
  if (messageNodes.has(id)) return;
  const row = document.createElement('div'); row.className = 'flex justify-end'; row.dataset.messageId = id;
  const bubble = document.createElement('div');
  bubble.className = 'bg-[var(--color-elyan-surface-muted)] text-[var(--color-elyan-text)] rounded-[24px] rounded-tr-lg px-5 py-3 max-w-[92%] md:max-w-[78%] lg:max-w-[68%] text-[15px] leading-relaxed whitespace-pre-wrap';
  bubble.textContent = visibleMessageText(message);
  row.append(bubble); list.append(row); messageNodes.set(id, row); scrollToBottom();
}

function attachmentChip(attachment: ComposerAttachment): HTMLElement {
  const chip = document.createElement('div');
  chip.className = 'inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--color-elyan-outline)] bg-[var(--color-elyan-surface)] px-2.5 py-1 text-xs text-[var(--color-elyan-text)]';
  chip.dataset.attachmentId = attachment.id;
  const label = document.createElement('span');
  label.className = 'max-w-[180px] truncate';
  label.textContent = attachment.fileName;
  const meta = document.createElement('span');
  meta.className = 'text-[var(--color-elyan-text-muted)]';
  meta.textContent = attachment.kind === 'text' ? 'text ready' : attachment.kind === 'image' ? 'image metadata' : 'metadata';
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'rounded-full px-1 text-[var(--color-elyan-text-muted)] hover:bg-[var(--color-elyan-surface-muted)] hover:text-[var(--color-elyan-text)] active:scale-95';
  remove.setAttribute('aria-label', `Remove ${attachment.fileName}`);
  remove.textContent = '×';
  remove.addEventListener('click', () => {
    state.attachments = state.attachments.filter((item) => item.id !== attachment.id);
    renderAttachmentTray();
  });
  chip.append(label, meta, remove);
  return chip;
}

function renderAttachmentTray(): void {
  const tray = byId('attachment-tray');
  if (!tray) return;
  tray.replaceChildren();
  tray.classList.toggle('hidden', state.attachments.length === 0);
  if (!state.attachments.length) return;
  const wrap = document.createElement('div');
  wrap.className = 'flex flex-wrap gap-1.5';
  state.attachments.forEach((attachment) => wrap.append(attachmentChip(attachment)));
  tray.append(wrap);
}

function renderCapabilityTray(): void {
  const tray = byId('capability-tray');
  if (!tray) return;
  tray.replaceChildren();
  tray.classList.toggle('hidden', state.requestedCapabilities.length === 0);
  if (!state.requestedCapabilities.length) return;
  const wrap = document.createElement('div');
  wrap.className = 'flex flex-wrap gap-1.5';
  state.requestedCapabilities.forEach((capability) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'rounded-full border border-[var(--color-elyan-outline)] bg-[var(--color-elyan-surface)] px-2.5 py-1 text-xs text-[var(--color-elyan-text)] hover:bg-[var(--color-elyan-surface-muted)] active:scale-95';
    chip.textContent = `${state.capabilityLabels.get(capability) || capability.replace(/_/g, ' ')} ×`;
    chip.addEventListener('click', () => {
      state.requestedCapabilities = state.requestedCapabilities.filter((item) => item !== capability);
      renderCapabilityTray();
    });
    wrap.append(chip);
  });
  tray.append(wrap);
}

function normalizeCapability(value: unknown): string {
  return typeof value === 'string' ? value.trim().slice(0, 80) : '';
}

function addComposerCapabilityOption(id: string, label: string, description = ''): void {
  const normalized = normalizeCapability(id);
  if (!normalized || state.capabilityLabels.has(normalized)) return;
  state.capabilityLabels.set(normalized, label || normalized);
  const list = byId('composer-dynamic-capability-list');
  const shell = byId('composer-dynamic-capabilities');
  if (!list || !shell) return;
  shell.classList.remove('hidden');
  const button = document.createElement('button');
  button.type = 'button';
  button.setAttribute('role', 'menuitem');
  button.dataset.composerCapability = normalized;
  button.className = 'rounded-[16px] px-2.5 py-1.5 text-left text-[13px] text-[var(--color-elyan-text)] hover:bg-[var(--color-elyan-surface-muted)] active:scale-95';
  const title = document.createElement('div');
  title.className = 'truncate';
  title.textContent = label || normalized;
  button.append(title);
  if (description) {
    const sub = document.createElement('div');
    sub.className = 'mt-0.5 truncate text-[11px] text-[var(--color-elyan-text-muted)]';
    sub.textContent = description;
    button.append(sub);
  }
  button.addEventListener('click', () => {
    if (!state.requestedCapabilities.includes(normalized)) state.requestedCapabilities.push(normalized);
    byId('composer-menu')?.classList.add('hidden'); byId('composer-menu-button')?.setAttribute('aria-expanded', 'false');
    renderCapabilityTray();
    byId<HTMLTextAreaElement>('chat-input')?.focus();
  });
  list.append(button);
}

function addCapabilityList(source: unknown, prefix = ''): void {
  const values = Array.isArray(source) ? source : [];
  values.map(normalizeCapability).filter(Boolean).slice(0, 80).forEach((capability) => {
    addComposerCapabilityOption(capability, prefix ? `${prefix}: ${capability}` : capability);
  });
}

async function hydrateDynamicComposerOptions(bootstrap: Record<string, unknown>): Promise<void> {
  const devices = Array.isArray(bootstrap.devices) ? bootstrap.devices : [];
  devices.forEach((raw) => {
    const device = record(raw);
    const runtime = record(device.runtime);
    addCapabilityList(runtime.capabilities, string(device.label) || string(device.name) || 'Desktop');
  });
  const skills = Array.isArray(bootstrap.skills) ? bootstrap.skills : Array.isArray(record(bootstrap.brain).skills) ? record(bootstrap.brain).skills as unknown[] : [];
  skills.slice(0, 80).forEach((raw) => {
    const skill = record(raw);
    const id = normalizeCapability(skill.id) || normalizeCapability(skill.name);
    if (id) addComposerCapabilityOption(id, firstText(skill, ['title', 'displayName', 'name']) || id, 'Elyan skill');
  });
  try {
    const response = await fetch('/app/api/backend/integrations/apps', { credentials: 'same-origin', headers: { accept: 'application/json' }, redirect: 'manual' });
    if (!response.ok) return;
    const result = await response.json().catch(() => ({})) as { apps?: Array<Record<string, unknown>> };
    (Array.isArray(result.apps) ? result.apps : []).forEach((app) => {
      const id = normalizeCapability(app.id);
      const name = string(app.displayName) || id;
      addCapabilityList(app.capabilities, name);
      if (id) addComposerCapabilityOption(id, name);
      if (app.toolCount != null && id) addComposerCapabilityOption(`${id}.tools`, `${name} tools`);
    });
  } catch {
    // Integrations can be temporarily unavailable; bootstrap/default routes remain usable.
  }
  try {
    const response = await fetch('/app/api/backend/mcp/servers', { credentials: 'same-origin', headers: { accept: 'application/json' }, redirect: 'manual' });
    if (!response.ok) return;
    const result = await response.json().catch(() => ({})) as { servers?: Array<Record<string, unknown>> };
    (Array.isArray(result.servers) ? result.servers : []).forEach((server) => {
      const name = firstText(server, ['name', 'displayName', 'id']) || 'MCP';
      const id = normalizeCapability(server.id) || normalizeCapability(name);
      addCapabilityList(server.capabilities, name);
      if (id) addComposerCapabilityOption(`mcp.${id}`, name);
    });
  } catch {
    // Optional MCP discovery must not block chat startup.
  }
}

async function handleAttachmentSelection(input: HTMLInputElement): Promise<void> {
  if (!input.files?.length) return;
  try {
    const next = await buildComposerAttachments(input.files);
    const merged = new Map(state.attachments.map((attachment) => [attachment.sha256, attachment]));
    next.forEach((attachment) => merged.set(attachment.sha256, attachment));
    state.attachments = [...merged.values()].slice(0, 8);
    renderAttachmentTray();
    const skipped = input.files.length > next.length ? input.files.length - next.length : 0;
    if (skipped > 0) showNotice(`${skipped} file skipped. Elyan accepts up to 8 files per message.`, 'info');
  } catch {
    showNotice('Attachment could not be prepared in the browser.', 'error');
  } finally {
    input.value = '';
  }
}

function selectedCapabilityMetadata(capabilities: string[], attachmentCount: number): Record<string, unknown> {
  return {
    requestedCapabilities: capabilities,
    composer: {
      mode: 'web',
      capabilityHints: capabilities,
      attachmentCount,
    },
  };
}

function renderAssistant(message: RealtimeMessage): void {
  const list = byId('messages-list');
  if (!list) return;
  removeEmptyState();
  const id = string(message.id) || crypto.randomUUID();
  let row = messageNodes.get(id);
  if (!row) { row = assistantShell(id); list.append(row); messageNodes.set(id, row); }
  const body = row.querySelector<HTMLElement>('[data-message-body]');
  if (!body) return;
  if (!string(message.content) && !Array.isArray(message.blocks)) {
    body.innerHTML = '<span class="inline-flex items-center gap-1.5 text-[var(--color-elyan-text-muted)]"><span class="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--color-elyan-primary)]"></span><span>Thinking…</span></span>';
  } else {
    renderMessageContent(message, body);
  }
  scrollToBottom();
}

function renderMessage(message: RealtimeMessage): void {
  const role = string(message.role) || string(message.authorRole) || string(message.sender);
  if (role === 'user') renderUser(message); else renderAssistant(message);
}

function resetTimeline(): void {
  byId('messages-list')?.replaceChildren();
  messageNodes.clear(); realtime.messages.clear(); realtime.terminalMessageIds.clear(); realtime.messageSessionIds.clear();
}

function addEmptyState(): void {
  const list = byId('messages-list');
  if (!list || list.childNodes.length) return;
  const empty = document.createElement('div');
  empty.className = 'flex min-h-[52vh] flex-col items-center justify-center px-4 text-center';
  empty.dataset.emptyState = '1';
  const title = document.createElement('div');
  title.className = 'text-[28px] font-semibold tracking-[-0.035em] text-[var(--color-elyan-text)] sm:text-[36px]';
  title.textContent = `merhaba ${state.userName}`;
  const subtitle = document.createElement('div');
  subtitle.className = 'mt-3 min-h-[1.8em] text-[17px] font-medium text-[var(--color-elyan-text-muted)] sm:text-[20px]';
  subtitle.setAttribute('aria-label', 'Nasıl yardımcı olabilirim?');
  const sentence = 'Nasıl yardımcı olabilirim?';
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  if (reducedMotion) {
    subtitle.textContent = sentence;
  } else {
    let index = 0;
    const cursor = document.createElement('span');
    cursor.className = 'ml-0.5 inline-block h-[1em] w-px translate-y-0.5 bg-[var(--color-elyan-primary)] align-baseline animate-pulse';
    subtitle.append(cursor);
    const timer = window.setInterval(() => {
      index += 1;
      subtitle.textContent = sentence.slice(0, index);
      if (index < sentence.length) subtitle.append(cursor);
      else window.clearInterval(timer);
    }, 38);
  }
  empty.append(title, subtitle);
  list.append(empty);
}

async function loadMessages(sessionId: string, cursor?: string, prepend = false): Promise<void> {
  const generation = state.timelineGeneration;
  const query = new URLSearchParams({ limit: '50' });
  if (cursor) query.set('cursor', cursor);
  const response = await backendApi<MessageList>(`chat/sessions/${sessionId}/messages?${query}`);
  if (state.sessionId !== sessionId || generation !== state.timelineGeneration) return;
  const messages = Array.isArray(response.messages) ? response.messages : [];
  if (!prepend) resetTimeline();
  const list = byId('messages-list');
  const scrollContainer = byId('messages-container');
  const previousScrollHeight = scrollContainer?.scrollHeight || 0;
  const existingNodes = prepend && list ? new Set([...list.children]) : new Set<Element>();
  const firstExistingMessage = prepend && list ? list.querySelector('[data-message-id]') : null;
  list?.querySelector('[data-load-older]')?.remove();
  for (const message of messages) {
    const id = string(message.id);
    if (id) {
      mergeMessageSnapshot(realtime, message, sessionId);
    }
    renderMessage(message);
  }
  if (prepend && list) {
    const added = [...list.children].filter((node) => !existingNodes.has(node) && node.hasAttribute('data-message-id'));
    added.forEach((node) => list.insertBefore(node, firstExistingMessage));
    if (scrollContainer) {
      requestAnimationFrame(() => {
        scrollContainer.scrollTop += Math.max(0, scrollContainer.scrollHeight - previousScrollHeight);
      });
    }
  }
  state.sessionCursor = response.nextCursor || null;
  if (response.hasMore && response.nextCursor && list) {
    const button = document.createElement('button');
    button.type = 'button'; button.dataset.loadOlder = '1'; button.className = 'mx-auto block rounded-full px-3 py-2 text-xs text-[var(--color-elyan-text-muted)] hover:bg-[var(--color-elyan-surface-muted)]'; button.textContent = 'Load previous messages';
    button.addEventListener('click', () => void loadMessages(sessionId, response.nextCursor || undefined, true).catch((error) => showNotice(messageFor(error), 'error')));
    list.prepend(button);
  }
  addEmptyState();
}

async function openSession(sessionId: string): Promise<void> {
  state.sessionId = sessionId;
  state.timelineGeneration += 1;
  history.replaceState(null, '', `/app?session=${encodeURIComponent(sessionId)}`);
  document.querySelectorAll('[data-session-id]').forEach((node) => node.classList.toggle('bg-[var(--color-elyan-surface-muted)]', (node as HTMLElement).dataset.sessionId === sessionId));
  await loadMessages(sessionId);
}

function sessionRow(session: Session): HTMLElement {
  const row = document.createElement('div'); row.className = 'group';
  const button = document.createElement('button');
  button.type = 'button'; button.dataset.sessionId = session.id; button.className = 'block w-full min-w-0 truncate rounded-[18px] px-3 py-2.5 text-left text-[14px] text-[var(--color-elyan-text)] hover:bg-[var(--color-elyan-surface-muted)]'; button.textContent = session.title || 'New conversation';
  button.addEventListener('click', () => void openSession(session.id).catch((error) => showNotice(messageFor(error), 'error')));
  button.addEventListener('contextmenu', (event) => {
    event.preventDefault();
    showSessionContextMenu(session, event.clientX, event.clientY);
  });
  button.addEventListener('keydown', (event) => {
    if ((event.key === 'F10' && event.shiftKey) || event.key === 'ContextMenu') {
      event.preventDefault();
      const rect = button.getBoundingClientRect();
      showSessionContextMenu(session, rect.left + 16, rect.top + rect.height - 2);
    }
  });
  row.append(button); return row;
}

async function loadSessions(): Promise<Session[]> {
  const [active, archived] = await Promise.all([loadSessionPage('active'), loadSessionPage('archived')]);
  byId('archived-heading')?.classList.toggle('hidden', !(archived.sessions || []).length);
  return active.sessions || [];
}

async function loadSessionPage(status: 'active' | 'archived', cursor?: string): Promise<SessionList> {
  const query = new URLSearchParams({ status, limit: '20' });
  if (cursor) query.set('cursor', cursor);
  const response = await backendApi<SessionList>(`chat/sessions?${query}`);
  const list = byId(status === 'active' ? 'session-list-active' : 'session-list-archived');
  if (!list) return response;
  list.querySelector('[data-load-more-sessions]')?.remove();
  const rows = (response.sessions || []).map(sessionRow);
  if (cursor) list.append(...rows); else list.replaceChildren(...rows);
  if (response.hasMore && response.nextCursor) {
    const button = document.createElement('button');
    button.type = 'button'; button.dataset.loadMoreSessions = status; button.className = 'mx-auto mt-2 block rounded-full px-3 py-2 text-xs text-[var(--color-elyan-text-muted)] hover:bg-[var(--color-elyan-surface-muted)]'; button.textContent = 'Load more';
    button.addEventListener('click', () => void loadSessionPage(status, response.nextCursor || undefined).catch((error) => showNotice(messageFor(error), 'error')));
    list.append(button);
  }
  if (status === 'archived') byId('archived-heading')?.classList.toggle('hidden', !list.querySelector('[data-session-id]'));
  return response;
}

function newChat(): void {
  closeSessionContextMenu();
  state.sessionId = null; state.sessionCursor = null; state.timelineGeneration += 1; state.attachments = []; state.requestedCapabilities = []; renderAttachmentTray(); renderCapabilityTray(); history.replaceState(null, '', '/app'); resetTimeline(); addEmptyState(); byId<HTMLTextAreaElement>('chat-input')?.focus();
}

function updateProfile(bootstrap: Record<string, unknown>): void {
  const user = record(bootstrap.user); const subscription = record(bootstrap.subscription || bootstrap.billingState);
  const name = string(user.displayName) || string(user.name) || string(user.email) || 'Elyan user';
  state.userName = name.split('@')[0] || name;
  const plan = string(subscription.planCode) || string(subscription.plan) || string(subscription.status) || 'Free';
  const nameNode = byId('sidebar-user-name'); if (nameNode) nameNode.textContent = name;
  const planNode = byId('sidebar-user-plan'); if (planNode) planNode.textContent = `Settings · ${plan}`;
  const initials = byId('sidebar-user-initials'); if (initials) initials.textContent = name.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'E';
  const brain = record(bootstrap.brain); const header = byId('brain-state');
  if (header) header.textContent = brain.ready === false ? 'connecting' : 'ready';
}

function rememberCursor(event: MessageEvent): void {
  const cursor = event.lastEventId || '';
  if (/^\d+$/.test(cursor)) sessionStorage.setItem('elyan:realtime:cursor', cursor);
}

async function resync(): Promise<void> {
  if (state.sessionId) await loadMessages(state.sessionId);
  await loadSessions();
}

function handleEvent(event: MessageEvent): void {
  rememberCursor(event);
  let parsed: Record<string, unknown>;
  try { parsed = record(JSON.parse(event.data)); } catch { return; }
  const envelope = { ...parsed, eventId: event.lastEventId || parsed.eventId, type: event.type === 'message' ? parsed.type : event.type };
  const result = mergeRealtimeEvent(realtime, envelope);
  if (result.resync) { void resync().catch(() => undefined); return; }
  if (result.changedId) {
    const message = realtime.messages.get(result.changedId);
    if (message && result.sessionId && result.sessionId === state.sessionId) renderAssistant(message);
    if (result.terminal && (!message?.content && !Array.isArray(message?.blocks))) window.setTimeout(() => void resync(), 250);
  }
  const type = string(envelope.type);
  if (type.startsWith('task.') || type.startsWith('approval.')) void resync().catch(() => undefined);
}

const realtimeEvents = ['connected', 'heartbeat', 'resync_required', 'message.created', 'message.accepted', 'message.delta', 'message.running', 'message.completed', 'message.error', 'block.preview', 'chat.message.created', 'chat.message.updated', 'task.created', 'task.updated', 'task.status', 'task.approval_required', 'task.completed', 'task.failed', 'approval.required', 'approval.resolved'];

function connectRealtime(): void {
  if (state.disposed) return;
  state.eventSource?.close();
  const cursor = sessionStorage.getItem('elyan:realtime:cursor');
  const source = new EventSource(`/app/api/realtime/stream${cursor && /^\d+$/.test(cursor) ? `?cursor=${cursor}` : ''}`, { withCredentials: true });
  state.eventSource = source;
  source.onopen = () => { state.reconnectAttempt = 0; };
  source.onmessage = handleEvent;
  realtimeEvents.forEach((name) => source.addEventListener(name, handleEvent as EventListener));
  source.onerror = () => {
    source.close();
    if (state.disposed) return;
    state.reconnectAttempt += 1;
    const base = Math.min(20_000, 500 * (2 ** Math.min(state.reconnectAttempt, 5)));
    const delay = Math.floor(base * (0.7 + Math.random() * 0.6));
    window.clearTimeout(state.reconnectTimer);
    state.reconnectTimer = window.setTimeout(connectRealtime, delay);
  };
}

function wireChatSurfaceScroll(): void {
  const container = byId('messages-container');
  const main = container?.closest('main');
  if (!container || !main) return;
  main.addEventListener('wheel', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target || target.closest('textarea, input, button, a, [role="menu"], #composer-menu, #app-sidebar')) return;
    if (!event.deltaY) return;
    const before = container.scrollTop;
    container.scrollTop += event.deltaY;
    if (container.scrollTop !== before) event.preventDefault();
  }, { passive: false });
}

async function submitMessage(event: SubmitEvent): Promise<void> {
  event.preventDefault();
  const input = byId<HTMLTextAreaElement>('chat-input'); const submit = byId<HTMLButtonElement>('chat-submit');
  const content = input?.value.trim() || '';
  if ((!content && state.attachments.length === 0) || !input || !submit) return;
  const attachmentsAtSubmit = [...state.attachments];
  const capabilitiesAtSubmit = [...state.requestedCapabilities];
  const attachmentPayload = buildAttachmentPayload(attachmentsAtSubmit);
  const prompt = `${content || 'Review the attached file.'}${attachmentPayload.promptSuffix}`;
  const localContent = attachmentsAtSubmit.length ? `${content || 'Attached file'}\n\n${attachmentPromptLabel(attachmentsAtSubmit)}` : content;
  input.value = ''; input.style.height = 'auto'; submit.disabled = true;
  state.attachments = []; state.requestedCapabilities = []; renderAttachmentTray(); renderCapabilityTray();
  const localId = `local:${crypto.randomUUID()}`; renderUser({ id: localId, role: 'user', content: localContent });
  const pendingId = `pending:${crypto.randomUUID()}`; renderAssistant({ id: pendingId, role: 'assistant' });
	  const fingerprint = await payloadFingerprint(`${state.sessionId || 'new'}\0${prompt}\0${JSON.stringify(capabilitiesAtSubmit)}`);
	  const submitSessionId = state.sessionId;
	  const submitGeneration = state.timelineGeneration;
	  const compactContext = buildWebCompactContext(activeSessionMessages(submitSessionId), submitSessionId, prompt, attachmentsAtSubmit.length);
	  const idempotency = persistentIdempotencyKey(`chat:${submitSessionId || 'new'}:${fingerprint}`);
  try {
    const blockId = `web_text_${crypto.randomUUID()}`;
    const response = await backendApi<Record<string, unknown>>('chat/messages', {
      method: 'POST',
      headers: { 'idempotency-key': idempotency.key },
      body: JSON.stringify({
	        ...(submitSessionId ? { sessionId: submitSessionId } : {}),
        source: 'web',
        requestedCapabilities: capabilitiesAtSubmit,
        blocks: [{
          type: 'text',
          markdown: prompt,
          version: 1,
          blockId,
          source: 'web',
          visibility: 'user_visible',
          renderHints: {},
          data: { markdown: prompt },
        }],
        metadata: {
          blockProtocol: ASSISTANT_BLOCK_ENVELOPE_VERSION,
          contractVersion: ASSISTANT_BLOCK_ENVELOPE_VERSION,
          blockSchemaDigest: ASSISTANT_BLOCK_SCHEMA_DIGEST,
	          client: 'web',
	          source: 'web',
	          ...(submitSessionId ? { sessionId: submitSessionId, chat: { sessionId: submitSessionId } } : {}),
	          ...(compactContext ? { compactContext } : {}),
	          renderContract: {
            version: ASSISTANT_BLOCK_ENVELOPE_VERSION,
            mode: 'block_first',
            canonicalSurface: 'blocks',
            legacyContent: 'none',
          },
          userBlocks: [{
            type: 'text',
            markdown: prompt,
            visibility: 'user_visible',
          }],
          ...selectedCapabilityMetadata(capabilitiesAtSubmit, attachmentsAtSubmit.length),
          requestedCapabilities: capabilitiesAtSubmit,
          attachments: attachmentPayload.attachments,
          raw_file_uploaded: false,
          data_origin: attachmentPayload.attachments.length ? 'local_derived' : undefined,
          privacy_level: attachmentPayload.attachments.length ? 'local_derived' : undefined,
        },
      }),
    });
    idempotency.clear(); messageNodes.get(pendingId)?.remove(); messageNodes.delete(pendingId);
    if (state.sessionId !== submitSessionId || state.timelineGeneration !== submitGeneration) return;
	    const session = record(response.session); const userMessage = record(response.userMessage) as RealtimeMessage; const assistantMessage = record(response.assistantMessage) as RealtimeMessage; const task = record(response.task);
	    if (string(session.id)) state.sessionId = string(session.id);
	    if (string(userMessage.id)) {
	      messageNodes.get(localId)?.remove(); messageNodes.delete(localId);
	      mergeMessageSnapshot(realtime, userMessage, state.sessionId);
	      renderUser(userMessage);
	    }
    if (string(assistantMessage.id)) {
      if (!assistantMessage.taskId && string(task.id)) assistantMessage.taskId = string(task.id);
      const merged = mergeMessageSnapshot(realtime, assistantMessage, state.sessionId);
      renderAssistant(merged);
    }
    if (state.sessionId) history.replaceState(null, '', `/app?session=${state.sessionId}`);
    await loadSessions();
  } catch (error) {
    state.attachments = attachmentsAtSubmit; state.requestedCapabilities = capabilitiesAtSubmit; renderAttachmentTray(); renderCapabilityTray();
    messageNodes.get(pendingId)?.remove(); messageNodes.delete(pendingId); showNotice(messageFor(error), 'error');
  } finally { submit.disabled = false; input.focus(); }
}

async function handleTaskAction(button: HTMLButtonElement): Promise<void> {
  const taskId = button.dataset.taskId; const action = button.dataset.taskAction;
  if (!taskId || !action) return;
  button.disabled = true;
  try {
    if (action === 'cancel') await idempotentBackendApi(`tasks/${taskId}/cancel`, `task:${taskId}:cancel`, { method: 'POST', body: '{}' });
    else if (action === 'thumbs_up' || action === 'thumbs_down') await idempotentBackendApi(`tasks/${taskId}/feedback`, `task:${taskId}:feedback:${action}`, { method: 'POST', body: JSON.stringify({ type: action }) });
    else await idempotentBackendApi(`tasks/${taskId}/approval`, `task:${taskId}:approval:${action}`, { method: 'POST', body: JSON.stringify({ approved: action === 'approve' }) });
    await resync();
  } catch (error) { showNotice(messageFor(error), 'error'); } finally { button.disabled = false; }
}

export async function initChatApp(): Promise<void> {
  const form = byId<HTMLFormElement>('chat-form'); const input = byId<HTMLTextAreaElement>('chat-input');
  if (!form || !input || form.dataset.initialized) return;
  form.dataset.initialized = '1';
  form.addEventListener('submit', submitMessage);
  const attachmentInput = byId<HTMLInputElement>('attachment-input');
  attachmentInput?.addEventListener('change', () => void handleAttachmentSelection(attachmentInput));
  byId('composer-menu-button')?.addEventListener('click', () => {
    const menu = byId('composer-menu'); const button = byId('composer-menu-button');
    if (!menu || !button) return;
    const hidden = menu.classList.toggle('hidden');
    button.setAttribute('aria-expanded', hidden ? 'false' : 'true');
  });
  byId('composer-attach-menu-button')?.addEventListener('click', () => {
    byId('composer-menu')?.classList.add('hidden');
    byId('composer-menu-button')?.setAttribute('aria-expanded', 'false');
    attachmentInput?.click();
  });
  document.querySelectorAll<HTMLElement>('[data-composer-capability]').forEach((button) => {
    const capability = button.dataset.composerCapability || '';
    if (capability) state.capabilityLabels.set(capability, button.textContent?.trim() || capability);
    button.addEventListener('click', () => {
      const capability = button.dataset.composerCapability || '';
      if (capability && !state.requestedCapabilities.includes(capability)) state.requestedCapabilities.push(capability);
      byId('composer-menu')?.classList.add('hidden'); byId('composer-menu-button')?.setAttribute('aria-expanded', 'false');
      renderCapabilityTray();
      input.focus();
    });
  });
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); } });
  input.addEventListener('input', () => { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 200)}px`; });
  byId('new-chat')?.addEventListener('click', newChat);
  byId('sidebar-profile')?.addEventListener('click', () => location.assign('/app/settings'));
  byId('mobile-menu')?.addEventListener('click', () => byId('app-sidebar')?.classList.toggle('max-md:hidden'));
  wireChatSurfaceScroll();
  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target?.closest('[data-session-context-menu]')) closeSessionContextMenu();
    const button = target?.closest<HTMLButtonElement>('[data-task-action]');
    if (button) void handleTaskAction(button);
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeSessionContextMenu(); });
  window.addEventListener('resize', closeSessionContextMenu);

  try {
    const bootstrap = await apiFetch<Record<string, unknown>>('/app/api/auth/session');
    updateProfile(bootstrap);
    void hydrateDynamicComposerOptions(bootstrap);
    void backendApi('web/warmup', { method: 'POST', body: '{}' }).catch(() => undefined);
	    await loadSessions();
	    const requested = new URL(location.href).searchParams.get('session');
	    const initial = requested && /^[0-9a-fA-F-]{36}$/.test(requested) ? requested : '';
	    if (initial) await openSession(initial); else { state.sessionId = null; resetTimeline(); addEmptyState(); }
	    connectRealtime();
  } catch (error) { showNotice(messageFor(error), 'error'); addEmptyState(); }

  window.addEventListener('pagehide', () => { state.disposed = true; state.eventSource?.close(); window.clearTimeout(state.reconnectTimer); }, { once: true });
}
