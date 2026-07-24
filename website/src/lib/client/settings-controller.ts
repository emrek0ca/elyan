import { apiFetch, backendApi, idempotentBackendApi, messageFor, payloadFingerprint } from './api';

function byId<T extends HTMLElement>(id: string): T | null { return document.getElementById(id) as T | null; }
function object(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function text(value: unknown): string { return typeof value === 'string' ? value : ''; }

function status(message: string, error = false): void {
  const node = byId('settings-status');
  if (!node) return;
  node.textContent = message; node.classList.remove('hidden');
  node.classList.toggle('text-red-700', error); node.classList.toggle('text-[var(--color-elyan-success)]', !error);
}

async function bootstrap(): Promise<Record<string, unknown>> {
  return apiFetch('/app/api/auth/session');
}

function bindForm(id: string, action: (form: HTMLFormElement) => Promise<void>): void {
  const form = byId<HTMLFormElement>(id);
  if (!form) return;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = form.querySelector<HTMLButtonElement>('button[type="submit"]'); if (submit) submit.disabled = true;
    try { await action(form); } catch (error) { status(messageFor(error), true); } finally { if (submit) submit.disabled = false; }
  });
}

async function initProfile(): Promise<void> {
  const data = await bootstrap(); const user = object(data.user);
  const displayName = byId<HTMLInputElement>('display-name'); const email = byId<HTMLInputElement>('profile-email');
  if (displayName) displayName.value = text(user.displayName);
  if (email) email.value = text(user.email);

  bindForm('profile-form', async (form) => {
    const value = new FormData(form).get('displayName')?.toString().trim() || '';
    await backendApi('auth/me', { method: 'PATCH', body: JSON.stringify({ displayName: value }) });
    status('Profile updated.');
  });
  bindForm('password-form', async (form) => {
    const values = new FormData(form);
    await backendApi('auth/password', { method: 'POST', body: JSON.stringify({ currentPassword: values.get('currentPassword'), nextPassword: values.get('nextPassword') }) });
    form.reset(); status('Password changed.');
  });

  const twoFactor = await backendApi<{ twoFactor?: Record<string, unknown> }>('auth/2fa/status');
  renderTwoFactor(object(twoFactor.twoFactor));
  byId('two-factor-setup')?.addEventListener('click', async () => {
    try {
      const result = await backendApi<{ twoFactor?: Record<string, unknown> }>('auth/2fa/setup', { method: 'POST', body: '{}' });
      const value = object(result.twoFactor); const details = byId('two-factor-details');
      if (details) { details.classList.remove('hidden'); details.textContent = text(value.secret) ? `Secret: ${text(value.secret)}` : text(value.otpauthUri) || 'Scan the setup code in your authenticator, then enter a code below.'; }
      renderTwoFactor(value);
    } catch (error) { status(messageFor(error), true); }
  });
  bindForm('two-factor-form', async (form) => {
    const code = new FormData(form).get('code')?.toString() || '';
    const enabled = byId('two-factor-state')?.dataset.enabled === 'true';
    const result = await backendApi<{ twoFactor?: Record<string, unknown> }>(`auth/2fa/${enabled ? 'disable' : 'enable'}`, { method: 'POST', body: JSON.stringify({ code }) });
    form.reset(); renderTwoFactor(object(result.twoFactor)); status(enabled ? 'Two-factor authentication disabled.' : 'Two-factor authentication enabled.');
  });

  byId('logout-button')?.addEventListener('click', async () => {
    try { await apiFetch('/app/api/auth/logout', { method: 'POST', body: '{}' }); } finally { location.assign('/app/login'); }
  });
  byId('delete-account')?.addEventListener('click', async () => {
    if (!window.confirm('Permanently delete your Elyan account and its server data? This cannot be undone.')) return;
    try {
      await backendApi('auth/me', { method: 'DELETE' });
      try { await apiFetch('/app/api/auth/logout', { method: 'POST', body: '{}' }); } catch { /* account deletion invalidates the session */ }
      location.assign('/app/register');
    } catch (error) { status(messageFor(error), true); }
  });
}

function renderTwoFactor(value: Record<string, unknown>): void {
  const enabled = value.enabled === true || value.status === 'enabled';
  const state = byId('two-factor-state');
  if (state) { state.dataset.enabled = String(enabled); state.textContent = enabled ? 'Enabled' : 'Not enabled'; }
  const submit = byId<HTMLButtonElement>('two-factor-submit');
  if (submit) submit.textContent = enabled ? 'Disable 2FA' : 'Enable 2FA';
  byId('two-factor-setup')?.classList.toggle('hidden', enabled);
}

function deviceRow(device: Record<string, unknown>): HTMLElement {
  const row = document.createElement('div'); row.className = 'flex items-center justify-between gap-4 border-b border-[var(--color-elyan-outline)] py-4 last:border-0';
  const copy = document.createElement('div'); copy.className = 'min-w-0';
  const title = document.createElement('div'); title.className = 'truncate text-sm font-semibold'; title.textContent = text(device.label) || text(device.name) || 'Elyan device';
  const runtime = object(device.runtime); const detail = document.createElement('div'); detail.className = 'mt-1 text-xs text-[var(--color-elyan-text-muted)]';
  detail.textContent = `${text(device.type) || text(device.platform) || 'device'} · ${runtime.isConnected === true ? 'Connected' : text(device.status) || 'Offline'}`; copy.append(title, detail); row.append(copy);
  if (text(device.id) && device.isActive !== false && device.active !== false) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'flex-none rounded-lg border border-red-200 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-50'; button.textContent = 'Deactivate';
    button.addEventListener('click', async () => {
      if (!confirm(`Deactivate ${title.textContent}?`)) return;
      button.disabled = true;
      try { await idempotentBackendApi(`devices/${text(device.id)}/deactivate`, `device:${text(device.id)}:deactivate`, { method: 'POST', body: '{}' }); await loadDevices(); status('Device deactivated.'); }
      catch (error) { status(messageFor(error), true); } finally { button.disabled = false; }
    });
    row.append(button);
  }
  return row;
}

async function loadDevices(): Promise<void> {
  const result = await backendApi<{ devices?: Record<string, unknown>[] }>('devices');
  const list = byId('devices-list'); if (!list) return;
  const devices = Array.isArray(result.devices) ? result.devices : [];
  list.replaceChildren(...devices.map((device) => deviceRow(object(device))));
  if (!devices.length) { const empty = document.createElement('p'); empty.className = 'py-6 text-sm text-[var(--color-elyan-text-muted)]'; empty.textContent = 'No paired devices yet.'; list.append(empty); }
}

async function initDevices(): Promise<void> {
  await loadDevices();
  bindForm('pairing-form', async (form) => {
    const code = new FormData(form).get('pairingCode')?.toString().trim() || '';
    const fingerprint = await payloadFingerprint(code.toUpperCase());
    await idempotentBackendApi('pairing/sessions/claim-by-code', `pairing:claim:${fingerprint}`, { method: 'POST', body: JSON.stringify({ pairingCode: code }) });
    form.reset(); await loadDevices(); status('Desktop paired successfully.');
  });
}

export async function initSettings(): Promise<void> {
  const page = document.body.dataset.settingsPage;
  try {
    if (page === 'profile') await initProfile();
    if (page === 'devices') await initDevices();
  } catch (error) { status(messageFor(error), true); }
}
