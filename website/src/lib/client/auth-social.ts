import { apiFetch, csrfToken, messageFor } from './api';

declare global {
  interface Window {
    google?: { accounts: { id: { initialize(config: Record<string, unknown>): void; renderButton(node: HTMLElement, config: Record<string, unknown>): void } } };
    AppleID?: { auth: { init(config: Record<string, unknown>): void; signIn(): Promise<Record<string, unknown>> } };
  }
}

function cookie(name: string): string {
  const entry = document.cookie.split(';').map((value) => value.trim()).find((value) => value.startsWith(`${name}=`));
  return entry ? decodeURIComponent(entry.slice(name.length + 1)) : '';
}

function legal(root: HTMLElement): Record<string, boolean> {
  const checked = (name: string) => Boolean(document.querySelector<HTMLInputElement>(`[name="${name}"]`)?.checked);
  return root.dataset.authMode === 'register' ? {
    register: true,
    termsAccepted: checked('termsAccepted'),
    privacyAccepted: checked('privacyAccepted'),
    aiDataSharingAccepted: checked('aiDataSharingAccepted'),
  } : { register: false };
}

function setStatus(message: string, error = false): void {
  const node = document.getElementById('social-auth-status');
  if (!node) return;
  node.textContent = message;
  node.classList.remove('hidden');
  node.classList.toggle('text-red-700', error);
  node.classList.toggle('text-[var(--color-elyan-text-muted)]', !error);
}

function legalReady(root: HTMLElement): boolean {
  if (root.dataset.authMode !== 'register') return true;
  const ready = Boolean(document.querySelector<HTMLInputElement>('[name="termsAccepted"]')?.checked && document.querySelector<HTMLInputElement>('[name="privacyAccepted"]')?.checked);
  if (!ready) setStatus('Accept the Terms of Use and Privacy Policy to continue.', true);
  return ready;
}

export function validGoogleClientId(value: string | undefined): string {
  const clientId = String(value || '').trim();
  return /^[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com$/.test(clientId) ? clientId : '';
}

export function validAppleServiceId(value: string | undefined): string {
  const serviceId = String(value || '').trim();
  return /^[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z0-9.-]+$/.test(serviceId) && !/apple-service-id|placeholder|example/i.test(serviceId) ? serviceId : '';
}

export function validHttpsUrl(value: string | undefined): string {
  try {
    const url = new URL(String(value || '').trim());
    return url.protocol === 'https:' ? url.toString() : '';
  } catch {
    return '';
  }
}

async function complete(path: string, body: Record<string, unknown>): Promise<void> {
  const result = await apiFetch<{ ok?: boolean }>(path, { method: 'POST', body: JSON.stringify(body) });
  if (result.ok) location.assign('/app');
}

function setupGoogle(root: HTMLElement): boolean {
  const container = document.getElementById('google-signin');
  const clientId = validGoogleClientId(root.dataset.googleClientId);
  if (!container || !clientId) { container?.classList.add('hidden'); return true; }
  if (!window.google) return false;
  if (container.dataset.initialized === 'true') return true;
  container.dataset.initialized = 'true';
  container.classList.remove('hidden');
  if (!cookie('g_csrf_token')) {
    const token = crypto.randomUUID().replaceAll('-', '') + crypto.randomUUID().replaceAll('-', '');
    document.cookie = `g_csrf_token=${encodeURIComponent(token)}; Path=/; SameSite=Lax${location.protocol === 'https:' ? '; Secure' : ''}`;
  }
  window.google.accounts.id.initialize({
    client_id: clientId,
    ux_mode: 'popup',
    callback: async (response: Record<string, unknown>) => {
      if (!legalReady(root)) return;
      setStatus('Completing Google sign-in…');
      try {
        await complete('/app/api/auth/oauth/google', {
          credential: response.credential,
          gCsrfToken: cookie('g_csrf_token'),
          ...legal(root),
        });
      } catch (error) { setStatus(messageFor(error), true); }
    },
  });
  window.google.accounts.id.renderButton(container, { type: 'standard', theme: 'outline', size: 'large', shape: 'pill', width: 366, text: root.dataset.authMode === 'register' ? 'signup_with' : 'signin_with' });
  return true;
}

function setupApple(root: HTMLElement): boolean {
  const button = document.getElementById('apple-signin') as HTMLButtonElement | null;
  const clientId = validAppleServiceId(root.dataset.appleServiceId);
  const redirectURI = validHttpsUrl(root.dataset.appleRedirectUri);
  if (!button || !clientId || !redirectURI) { button?.classList.add('hidden'); return true; }
  if (!window.AppleID) return false;
  if (button.dataset.initialized === 'true') return true;
  button.dataset.initialized = 'true';
  button.classList.remove('hidden');
  button.addEventListener('click', async () => {
    if (!legalReady(root)) return;
    button.disabled = true; setStatus('Opening Apple sign-in…');
    try {
      const transaction = await apiFetch<{ state: string; nonce: string }>('/app/api/auth/oauth/apple-transaction', { method: 'POST', body: '{}' });
      window.AppleID?.auth.init({ clientId, scope: 'name email', redirectURI, state: transaction.state, nonce: transaction.nonce, usePopup: true });
      const response = await window.AppleID!.auth.signIn();
      const authorization = response.authorization && typeof response.authorization === 'object' ? response.authorization as Record<string, unknown> : {};
      const user = response.user && typeof response.user === 'object' ? response.user as Record<string, unknown> : {};
      const name = user.name && typeof user.name === 'object' ? user.name as Record<string, unknown> : {};
      await complete('/app/api/auth/oauth/apple', {
        idToken: authorization.id_token,
        authorizationCode: authorization.code,
        state: authorization.state,
        displayName: [name.firstName, name.lastName].filter(Boolean).join(' ') || undefined,
        ...legal(root),
      });
    } catch (error) { setStatus(messageFor(error), true); }
    finally { button.disabled = false; }
  });
  return true;
}

export function initSocialAuth(): void {
  const root = document.querySelector<HTMLElement>('[data-auth-mode]');
  if (!root) return;
  const hasGoogle = Boolean(validGoogleClientId(root.dataset.googleClientId));
  const hasApple = Boolean(validAppleServiceId(root.dataset.appleServiceId) && validHttpsUrl(root.dataset.appleRedirectUri));
  if (!hasGoogle && !hasApple) {
    document.getElementById('google-signin')?.classList.add('hidden');
    document.getElementById('apple-signin')?.classList.add('hidden');
    setStatus('Google and Apple sign-in are not configured for this environment.', true);
    return;
  }

  let attempts = 0;
  const waitForProviders = () => {
    attempts += 1;
    const googleReady = setupGoogle(root);
    const appleReady = setupApple(root);
    if (googleReady && appleReady) {
      setStatus('');
      document.getElementById('social-auth-status')?.classList.add('hidden');
      return;
    }
    if (attempts < 20) {
      window.setTimeout(waitForProviders, 200);
      return;
    }
    setStatus('Social sign-in could not be loaded. Check the provider configuration and network access.', true);
  };
  if (document.readyState === 'complete') waitForProviders(); else window.addEventListener('load', waitForProviders, { once: true });
  // Ensure the Elyan CSRF cookie exists before a provider callback is submitted.
  void csrfToken();
}
