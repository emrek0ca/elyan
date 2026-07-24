export type ApiError = Error & { status?: number; code?: string; details?: unknown };

function readCookie(suffix: string): string {
  const match = document.cookie
    .split(';')
    .map((entry) => entry.trim())
    .find((entry) => entry.split('=', 1)[0]?.endsWith(suffix));
  return match ? decodeURIComponent(match.slice(match.indexOf('=') + 1)) : '';
}

export function csrfToken(): string {
  return readCookie('elyan-csrf');
}

export function persistentIdempotencyKey(scope: string): { key: string; clear: () => void } {
  const storageKey = `elyan:idempotency:${scope}`;
  let key = sessionStorage.getItem(storageKey);
  if (!key) {
    key = `web:${scope}:${crypto.randomUUID()}`;
    sessionStorage.setItem(storageKey, key);
  }
  return { key, clear: () => sessionStorage.removeItem(storageKey) };
}

export async function payloadFingerprint(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].slice(0, 12).map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function apiFetch<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  if (!path.startsWith('/app/api/')) throw new Error('invalid_api_path');
  const method = String(init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  headers.set('accept', 'application/json');
  if (init.body && !headers.has('content-type')) headers.set('content-type', 'application/json');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('x-elyan-csrf', csrfToken());
  const response = await fetch(path, { ...init, method, headers, credentials: 'same-origin' });
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('json') ? await response.json().catch(() => ({})) : await response.text();
  if (!response.ok) {
    const value = data && typeof data === 'object' ? data as Record<string, unknown> : {};
    const error = new Error(String(value.message || 'The request could not be completed.')) as ApiError;
    error.status = response.status;
    error.code = String(value.error || 'request_failed');
    error.details = value;
    if (response.status === 401 && !location.pathname.startsWith('/app/login')) {
      location.assign(`/app/login?returnTo=${encodeURIComponent(location.pathname + location.search)}`);
    }
    throw error;
  }
  return data as T;
}

export function backendApi<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const safePath = path.replace(/^\/+/, '');
  return apiFetch<T>(`/app/api/backend/${safePath}`, init);
}

export async function idempotentBackendApi<T = unknown>(path: string, scope: string, init: RequestInit = {}): Promise<T> {
  const idempotency = persistentIdempotencyKey(scope);
  const headers = new Headers(init.headers);
  headers.set('idempotency-key', idempotency.key);
  const result = await backendApi<T>(path, { ...init, headers });
  idempotency.clear();
  return result;
}

export function messageFor(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'The request could not be completed.';
}
