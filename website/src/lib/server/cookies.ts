import type { AstroCookies } from 'astro';
import { isProduction } from './config';

const prodNames = {
  access: '__Host-elyan-access',
  refresh: '__Host-elyan-refresh',
  csrf: '__Host-elyan-csrf',
  appleTransaction: '__Host-elyan-apple-txn',
} as const;

const devNames = {
  access: 'elyan-access',
  refresh: 'elyan-refresh',
  csrf: 'elyan-csrf',
  appleTransaction: 'elyan-apple-txn',
} as const;

export function cookieNames() {
  return isProduction() ? prodNames : devNames;
}

export function parseTokenTtl(value: unknown, fallbackSeconds: number, maxSeconds = Number.MAX_SAFE_INTEGER): number {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    const seconds = Math.floor(value);
    return seconds <= maxSeconds ? seconds : fallbackSeconds;
  }
  const text = String(value ?? '').trim().toLowerCase();
  const match = /^(\d+)(s|m|h|d)?$/.exec(text);
  if (!match) return fallbackSeconds;
  const amount = Number(match[1]);
  const multiplier = match[2] === 'd' ? 86_400 : match[2] === 'h' ? 3_600 : match[2] === 'm' ? 60 : 1;
  const seconds = amount * multiplier;
  return Number.isSafeInteger(seconds) && seconds > 0 && seconds <= maxSeconds ? seconds : fallbackSeconds;
}

function baseCookie(maxAge: number, httpOnly = true) {
  return {
    httpOnly,
    secure: isProduction(),
    sameSite: 'lax' as const,
    path: '/',
    maxAge,
  };
}

export type TokenBundle = {
  accessToken: string;
  refreshToken: string;
  accessTokenTtl?: string | number;
  refreshTokenTtl?: string | number;
};

export function requireTokenBundle(value: unknown): TokenBundle {
  const input = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const accessToken = typeof input.accessToken === 'string' ? input.accessToken.trim() : '';
  const refreshToken = typeof input.refreshToken === 'string' ? input.refreshToken.trim() : '';
  if (!accessToken || !refreshToken || accessToken.length > 32_768 || refreshToken.length > 32_768) {
    throw Object.assign(new Error('invalid_auth_response'), { status: 502, code: 'backend_unavailable' });
  }
  return {
    accessToken,
    refreshToken,
    accessTokenTtl: typeof input.accessTokenTtl === 'string' || typeof input.accessTokenTtl === 'number' ? input.accessTokenTtl : undefined,
    refreshTokenTtl: typeof input.refreshTokenTtl === 'string' || typeof input.refreshTokenTtl === 'number' ? input.refreshTokenTtl : undefined,
  };
}

export function setSessionCookies(cookies: AstroCookies, tokens: TokenBundle): void {
  const safeTokens = requireTokenBundle(tokens);
  const names = cookieNames();
  cookies.set(names.access, safeTokens.accessToken, baseCookie(parseTokenTtl(safeTokens.accessTokenTtl, 15 * 60, 24 * 60 * 60)));
  cookies.set(names.refresh, safeTokens.refreshToken, baseCookie(parseTokenTtl(safeTokens.refreshTokenTtl, 30 * 86_400, 90 * 86_400)));
}

export function clearSessionCookies(cookies: AstroCookies): void {
  const names = cookieNames();
  cookies.delete(names.access, baseCookie(0));
  cookies.delete(names.refresh, baseCookie(0));
  // Remove cookies created by the pre-BFF prototype as well.
  cookies.delete('elyan_access_token', baseCookie(0));
  cookies.delete('elyan_refresh_token', baseCookie(0));
  cookies.delete('elyan_session', baseCookie(0));
}

export function readAccessToken(cookies: AstroCookies): string | null {
  return cookies.get(cookieNames().access)?.value || null;
}

export function readRefreshToken(cookies: AstroCookies): string | null {
  return cookies.get(cookieNames().refresh)?.value || null;
}

export function hasSessionCookie(cookies: AstroCookies): boolean {
  return Boolean(readAccessToken(cookies) || readRefreshToken(cookies));
}

export function setShortLivedHttpOnlyCookie(cookies: AstroCookies, name: string, value: string, maxAge: number): void {
  cookies.set(name, value, baseCookie(maxAge));
}

export function deleteCookie(cookies: AstroCookies, name: string): void {
  cookies.delete(name, baseCookie(0));
}
