import { describe, expect, it } from 'vitest';
import { clearSessionCookies, cookieNames, parseTokenTtl, requireTokenBundle, setSessionCookies } from '../src/lib/server/cookies';
import { assertMutationSecurity, ensureCsrfToken, safeReturnTo, signTransaction, verifyTransaction } from '../src/lib/server/security';
import { normalizePublicError } from '../src/lib/server/http';
import { FakeCookies } from './helpers';

describe('session cookie and CSRF contract', () => {
  it('parses backend token TTLs without extending invalid values', () => {
    expect(parseTokenTtl('15m', 10)).toBe(900);
    expect(parseTokenTtl('2h', 10)).toBe(7200);
    expect(parseTokenTtl('30d', 10)).toBe(2_592_000);
    expect(parseTokenTtl('nope', 600)).toBe(600);
    expect(parseTokenTtl('365d', 600, 90 * 86_400)).toBe(600);
    expect(() => requireTokenBundle({ accessToken: 'access-only' })).toThrow('invalid_auth_response');
  });

  it('rotates both session cookies and removes prototype cookie names', () => {
    const cookies = new FakeCookies();
    setSessionCookies(cookies as never, { accessToken: 'access-2', refreshToken: 'refresh-2', accessTokenTtl: '15m', refreshTokenTtl: '30d' });
    expect(cookies.values.get(cookieNames().access)).toBe('access-2');
    expect(cookies.setCalls[0]?.options).toMatchObject({ httpOnly: true, sameSite: 'lax', path: '/', maxAge: 900 });
    clearSessionCookies(cookies as never);
    expect(cookies.deleteCalls.map((call) => call.name)).toEqual(expect.arrayContaining(['elyan_access_token', 'elyan_refresh_token', cookieNames().access, cookieNames().refresh]));
  });

  it('requires same-origin and a matching double-submit token', () => {
    const cookies = new FakeCookies({ [cookieNames().csrf]: 'a'.repeat(43) });
    const request = new Request('http://localhost:4321/app/api/test', { method: 'POST', headers: { origin: 'http://localhost:4321', 'x-elyan-csrf': 'a'.repeat(43) } });
    expect(() => assertMutationSecurity(request, cookies as never)).not.toThrow();
    expect(() => assertMutationSecurity(new Request(request.url, { method: 'POST', headers: { origin: 'https://evil.invalid', 'x-elyan-csrf': 'a'.repeat(43) } }), cookies as never)).toThrow('origin_mismatch');
  });

  it('accepts the actual dev server origin for 127.0.0.1 browser testing', () => {
    const cookies = new FakeCookies({ [cookieNames().csrf]: 'd'.repeat(43) });
    const request = new Request('http://127.0.0.1:4321/app/api/auth/login', { method: 'POST', headers: { origin: 'http://127.0.0.1:4321', 'x-elyan-csrf': 'd'.repeat(43) } });
    expect(() => assertMutationSecurity(request, cookies as never)).not.toThrow();
  });

  it('accepts the deployed browser origin even when it differs from configured canonical origin', () => {
    const cookies = new FakeCookies({ [cookieNames().csrf]: 'p'.repeat(43) });
    const request = new Request('https://www.elyan.dev/app/api/auth/login', { method: 'POST', headers: { origin: 'https://www.elyan.dev', 'x-elyan-csrf': 'p'.repeat(43) } });
    expect(() => assertMutationSecurity(request, cookies as never)).not.toThrow();
    expect(() => assertMutationSecurity(new Request(request.url, { method: 'POST', headers: { origin: 'https://evil.invalid', 'x-elyan-csrf': 'p'.repeat(43) } }), cookies as never)).toThrow('origin_mismatch');
  });

  it('issues CSRF tokens and validates signed short-lived transactions', () => {
    const cookies = new FakeCookies();
    expect(ensureCsrfToken(cookies as never)).toMatch(/^[A-Za-z0-9_-]{32,}$/);
    const token = signTransaction({ state: 'state-1', expiresAt: Date.now() + 60_000 });
    expect(verifyTransaction<{ state: string; expiresAt: number }>(token)?.state).toBe('state-1');
    expect(verifyTransaction(`${token}x`)).toBeNull();
  });
});

describe('redirect and error hygiene', () => {
  it('accepts only local app return paths', () => {
    expect(safeReturnTo('/app/settings?tab=devices')).toBe('/app/settings?tab=devices');
    expect(safeReturnTo('//evil.invalid')).toBe('/app');
    expect(safeReturnTo('/app/login')).toBe('/app');
    expect(safeReturnTo('https://evil.invalid/app')).toBe('/app');
  });

  it('does not expose upstream 5xx messages', () => {
    const value = normalizePublicError({ error: 'db_failed', message: 'password=secret stack trace' }, 500, 'req-1');
    expect(value.message).toBe('Elyan is temporarily unavailable. Please try again.');
    expect(JSON.stringify(value)).not.toContain('secret');
  });
});
