import { backendApi, idempotentBackendApi, messageFor, persistentIdempotencyKey } from './api';

type AnyRecord = Record<string, unknown>;
function byId(id: string): HTMLElement | null { return document.getElementById(id); }
function object(value: unknown): AnyRecord { return value && typeof value === 'object' && !Array.isArray(value) ? value as AnyRecord : {}; }
function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
function status(message: string, error = false): void { const node = byId('integrations-status'); if (!node) return; node.textContent = message; node.classList.remove('hidden'); node.classList.toggle('text-red-700', error); node.classList.toggle('text-[var(--color-elyan-success)]', !error); }
function array(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function firstText(value: AnyRecord, keys: string[]): string {
  for (const key of keys) {
    const candidate = text(value[key]);
    if (candidate) return candidate;
  }
  return '';
}

function wait(delay: number): Promise<void> { return new Promise((resolve) => window.setTimeout(resolve, delay)); }

async function waitForConnection(appId: string, popup: Window): Promise<void> {
  const deadline = Date.now() + 2 * 60_000;
  while (Date.now() < deadline) {
    if (popup.closed) throw new Error('Connection window was closed before the integration completed.');
    try {
      const apps = await loadApps();
      if (apps.some((app) => text(app.id) === appId && app.connected === true)) {
        popup.close();
        status('Integration connected.');
        return;
      }
    } catch {
      // A transient BFF/control-plane failure should not abandon an active provider popup.
    }
    await wait(1500);
  }
  popup.close();
  throw new Error('The integration connection timed out. Please try again.');
}

function appCard(app: AnyRecord): HTMLElement {
  const id = text(app.id); const connected = app.connected === true; const available = app.available !== false;
  const card = document.createElement('section'); card.className = 'rounded-[22px] bg-[#f7f7f5] p-5 shadow-none';
  const top = document.createElement('div'); top.className = 'flex items-start justify-between gap-4';
  const copy = document.createElement('div'); copy.className = 'min-w-0'; const title = document.createElement('h2'); title.className = 'text-sm font-semibold'; title.textContent = text(app.displayName) || id;
  copy.append(title);
  if (text(app.description)) { const description = document.createElement('p'); description.className = 'mt-1 text-[13px] leading-relaxed text-[var(--color-elyan-text-muted)]'; description.textContent = text(app.description); copy.append(description); }
  const badge = document.createElement('span'); badge.className = `flex-none rounded-full px-2.5 py-1 text-[11px] font-semibold ${connected ? 'bg-[var(--color-elyan-primary-soft)] text-[var(--color-elyan-primary-dark)]' : 'bg-[var(--color-elyan-bg-deep)] text-[var(--color-elyan-text-muted)]'}`; badge.textContent = connected ? 'Connected' : available ? 'Available' : 'Unavailable'; top.append(copy, badge); card.append(top);
  if (connected && text(app.accountLabel)) { const account = document.createElement('p'); account.className = 'mt-3 text-xs text-[var(--color-elyan-text-muted)]'; account.textContent = text(app.accountLabel); card.append(account); }
  const actions = document.createElement('div'); actions.className = 'mt-4 flex flex-wrap gap-2';
  if (!connected && available) {
    const connect = document.createElement('button'); connect.type = 'button'; connect.className = 'rounded-lg bg-[var(--color-elyan-primary)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50'; connect.textContent = 'Connect';
    connect.addEventListener('click', async () => {
      connect.disabled = true; const idem = persistentIdempotencyKey(`integration:${id}`);
      try {
        const result = await backendApi<AnyRecord>(`integrations/apps/${id}/oauth/start`, { method: 'POST', headers: { 'idempotency-key': idem.key }, body: '{}' });
        const authorizationUrl = text(result.authUrl) || text(result.authorizationUrl) || text(object(result.oauth).authorizationUrl) || text(result.url);
        if (!authorizationUrl) throw new Error('Connection could not be started.');
        const target = new URL(authorizationUrl); if (target.protocol !== 'https:') throw new Error('Connection URL is invalid.');
        const popup = window.open(target.href, `elyan-oauth-${id}`, 'popup,width=560,height=720');
        if (!popup) throw new Error('Allow popups to connect this integration.');
        idem.clear();
        await waitForConnection(id, popup);
      } catch (error) { status(messageFor(error), true); connect.disabled = false; }
    }); actions.append(connect);
  }
  if (connected) {
    if (app.probeStatus != null) { const probe = document.createElement('button'); probe.type = 'button'; probe.className = 'rounded-lg border border-[var(--color-elyan-outline)] px-4 py-2 text-sm font-medium'; probe.textContent = 'Test connection'; probe.addEventListener('click', async () => { probe.disabled = true; try { await idempotentBackendApi(`integrations/apps/${id}/probe`, `integration:${id}:probe`, { method: 'POST', body: '{}' }); status(`${title.textContent} connection is ready.`); await loadApps(); } catch (error) { status(messageFor(error), true); } finally { probe.disabled = false; } }); actions.append(probe); }
    const disconnect = document.createElement('button'); disconnect.type = 'button'; disconnect.className = 'rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-700'; disconnect.textContent = 'Disconnect'; disconnect.addEventListener('click', async () => { if (!confirm(`Disconnect ${title.textContent}?`)) return; disconnect.disabled = true; try { await idempotentBackendApi(`integrations/apps/${id}`, `integration:${id}:disconnect`, { method: 'DELETE' }); status(`${title.textContent} disconnected.`); await loadApps(); } catch (error) { status(messageFor(error), true); } finally { disconnect.disabled = false; } }); actions.append(disconnect);
  }
  card.append(actions); return card;
}

function mcpServerCard(server: AnyRecord): HTMLElement {
  const card = document.createElement('section'); card.className = 'rounded-[22px] bg-[#f7f7f5] p-5 shadow-none';
  const top = document.createElement('div'); top.className = 'flex items-start justify-between gap-4';
  const copy = document.createElement('div'); copy.className = 'min-w-0';
  const title = document.createElement('h2'); title.className = 'truncate text-sm font-semibold'; title.textContent = firstText(server, ['name', 'displayName', 'id']) || 'MCP server';
  copy.append(title);
  const capabilities = array(server.capabilities).map(text).filter(Boolean);
  if (capabilities.length) {
    const meta = document.createElement('p'); meta.className = 'mt-1 truncate text-[13px] text-[var(--color-elyan-text-muted)]'; meta.textContent = capabilities.slice(0, 4).join(' · ');
    copy.append(meta);
  }
  const badge = document.createElement('span'); badge.className = 'flex-none rounded-full bg-[var(--color-elyan-bg-deep)] px-2.5 py-1 text-[11px] font-semibold text-[var(--color-elyan-text-muted)]'; badge.textContent = text(server.status) || 'MCP';
  top.append(copy, badge); card.append(top);
  return card;
}

async function loadMcpServers(): Promise<AnyRecord[]> {
  try {
    const response = await fetch('/app/api/backend/mcp/servers', { credentials: 'same-origin', headers: { accept: 'application/json' }, redirect: 'manual' });
    if (!response.ok) return [];
    const result = await response.json().catch(() => ({})) as { servers?: AnyRecord[] };
    return Array.isArray(result.servers) ? result.servers.map(object) : [];
  } catch {
    return [];
  }
}

async function loadApps(): Promise<AnyRecord[]> {
  const result = await backendApi<{ apps?: AnyRecord[] }>('integrations/apps'); const list = byId('integrations-list'); if (!list) return [];
  const apps = Array.isArray(result.apps) ? result.apps.map(object) : [];
  const servers = await loadMcpServers();
  const cards = [...apps.map((app) => appCard(app)), ...servers.map((server) => mcpServerCard(server))];
  list.replaceChildren(...cards);
  return apps;
}

export async function initIntegrations(): Promise<void> {
  const query = new URL(location.href).searchParams; if (query.get('status') === 'connected') status('Integration connected.'); if (query.get('error')) status('Integration could not be connected.', true);
  try { await loadApps(); } catch (error) { status(messageFor(error), true); }
}
