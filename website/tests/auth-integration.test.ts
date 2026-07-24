import { describe, expect, it, vi } from 'vitest';
import { POST as loginPost } from '../src/pages/app/api/auth/login';
import { POST as registerPost } from '../src/pages/app/api/auth/register';
import { POST as applePost } from '../src/pages/app/api/auth/oauth/apple';
import { POST as logoutPost } from '../src/pages/app/api/auth/logout';
import { authenticatedBackendFetch, refreshSession } from '../src/lib/server/backend';
import { cookieNames } from '../src/lib/server/cookies';
import { signTransaction } from '../src/lib/server/security';
import { FakeCookies, csrfRequest, jsonResponse } from './helpers';

function formRequest(path: string, fields: Record<string, string>): Request {
  const body = new FormData(); Object.entries(fields).forEach(([key, value]) => body.set(key, value));
  return new Request(`http://localhost:4321${path}`, { method: 'POST', headers: { origin: 'http://localhost:4321' }, body });
}

function redirect(location: string, status = 303): Response {
  return new Response(null, { status, headers: { location } });
}

const tokens = { accessToken: 'access-next', refreshToken: 'refresh-next', accessTokenTtl: '15m', refreshTokenTtl: '30d' };

describe('auth endpoints', () => {
  it('logs in, rotates HttpOnly cookies, and honors safe returnTo', async () => {
    const csrf = 'x'.repeat(43); const cookies = new FakeCookies({ [cookieNames().csrf]: csrf });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ user: { id: 'u1' }, tokens })));
    const request = formRequest('/app/api/auth/login', { _csrf: csrf, email: 'user@example.com', password: 'password123', returnTo: '/app/settings' });
    const response = await loginPost({ request, cookies, redirect } as never);
    expect(response.status).toBe(303); expect(response.headers.get('location')).toBe('/app/settings');
    expect(cookies.values.get(cookieNames().access)).toBe('access-next'); expect(cookies.values.get(cookieNames().refresh)).toBe('refresh-next');
  });

  it('returns to the real 2FA screen when the backend requires a code', async () => {
    const csrf = 'y'.repeat(43); const cookies = new FakeCookies({ [cookieNames().csrf]: csrf });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: 'two_factor_required', message: 'required' }, 401)));
    const request = formRequest('/app/api/auth/login', { _csrf: csrf, email: 'user@example.com', password: 'password123' });
    const response = await loginPost({ request, cookies, redirect } as never);
    expect(response.headers.get('location')).toContain('twoFactor=1');
    expect(cookies.values.get(cookieNames().access)).toBeUndefined();
  });

  it('does not manufacture legal acceptance during registration', async () => {
    const csrf = 'z'.repeat(43); const cookies = new FakeCookies({ [cookieNames().csrf]: csrf }); const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    const request = formRequest('/app/api/auth/register', { _csrf: csrf, displayName: 'User', email: 'user@example.com', password: 'password123' });
    const response = await registerPost({ request, cookies, redirect } as never);
    expect(response.headers.get('location')).toBe('/app/register?error=legal_acceptance_required'); expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects an Apple response whose ID token does not carry the transaction nonce', async () => {
    const csrf = 'n'.repeat(43); const state = 'apple-state'; const nonce = 'apple-nonce';
    const transaction = signTransaction({ state, nonce, expiresAt: Date.now() + 60_000 });
    const cookies = new FakeCookies({ [cookieNames().csrf]: csrf, [cookieNames().appleTransaction]: transaction });
    const payload = Buffer.from(JSON.stringify({ sub: 'apple-user' })).toString('base64url');
    const request = csrfRequest('http://localhost:4321/app/api/auth/oauth/apple', 'POST', csrf, JSON.stringify({ state, idToken: `header.${payload}.signature` }));
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    const response = await applePost({ request, cookies } as never);
    expect(response.status).toBe(403); expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects an Apple response that does not echo the provider state', async () => {
    const csrf = 's'.repeat(43); const nonce = 'apple-nonce';
    const transaction = signTransaction({ state: 'expected-state', nonce, expiresAt: Date.now() + 60_000 });
    const cookies = new FakeCookies({ [cookieNames().csrf]: csrf, [cookieNames().appleTransaction]: transaction });
    const payload = Buffer.from(JSON.stringify({ sub: 'apple-user', nonce })).toString('base64url');
    const request = csrfRequest('http://localhost:4321/app/api/auth/oauth/apple', 'POST', csrf, JSON.stringify({ idToken: `header.${payload}.signature` }));
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    const response = await applePost({ request, cookies } as never);
    expect(response.status).toBe(403); expect(fetchMock).not.toHaveBeenCalled();
  });

  it('clears local session cookies when same-origin logout has a stale CSRF token', async () => {
    const cookies = new FakeCookies({ [cookieNames().access]: 'access', [cookieNames().refresh]: 'refresh', [cookieNames().csrf]: 'a'.repeat(43) });
    const request = csrfRequest('http://localhost:4321/app/api/auth/logout', 'POST', 'b'.repeat(43));
    const response = await logoutPost({ request, cookies, redirect } as never);
    expect(response.status).toBe(200); expect(cookies.values.get(cookieNames().access)).toBeUndefined(); expect(cookies.values.get(cookieNames().refresh)).toBeUndefined();
  });
});

describe('refresh rotation', () => {
  it('deduplicates concurrent refreshes for the same token', async () => {
    const first = new FakeCookies({ [cookieNames().refresh]: 'shared-refresh' }); const second = new FakeCookies({ [cookieNames().refresh]: 'shared-refresh' });
    const fetchMock = vi.fn(async () => { await Promise.resolve(); return jsonResponse({ tokens }); }); vi.stubGlobal('fetch', fetchMock);
    await Promise.all([refreshSession(first as never), refreshSession(second as never)]);
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(first.values.get(cookieNames().access)).toBe('access-next'); expect(second.values.get(cookieNames().access)).toBe('access-next');
  });

  it('clears the session only for definitive refresh rejection', async () => {
    const rejected = new FakeCookies({ [cookieNames().access]: 'old', [cookieNames().refresh]: 'rejected-refresh' });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: 'invalid_refresh' }, 401)));
    await expect(refreshSession(rejected as never)).rejects.toMatchObject({ definitive: true });
    expect(rejected.values.get(cookieNames().refresh)).toBeUndefined();

    const transient = new FakeCookies({ [cookieNames().access]: 'old', [cookieNames().refresh]: 'transient-refresh' });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network'); }));
    await expect(refreshSession(transient as never)).rejects.toThrow('backend_request_failed');
    expect(transient.values.get(cookieNames().refresh)).toBe('transient-refresh');
  });

  it('clears stale cookies after a definitive final authenticated 401', async () => {
    const cookies = new FakeCookies({ [cookieNames().access]: 'stale-access' });
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: 'unauthorized' }, 401)));
    const response = await authenticatedBackendFetch(cookies as never, { path: '/v1/web/bootstrap' });
    expect(response.status).toBe(401); expect(cookies.values.get(cookieNames().access)).toBeUndefined();
  });
});
