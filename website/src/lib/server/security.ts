import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import type { AstroCookies } from 'astro';
import { cookieNames } from './cookies';
import { getWebOrigin, getWebSessionSecret, isProduction } from './config';

const CSRF_MAX_AGE = 12 * 60 * 60;

export class RequestSecurityError extends Error {
  status = 403;
  code = 'request_rejected';
}

export function ensureCsrfToken(cookies: AstroCookies): string {
  const name = cookieNames().csrf;
  const existing = cookies.get(name)?.value;
  if (existing && /^[A-Za-z0-9_-]{32,128}$/.test(existing)) return existing;
  const token = randomBytes(32).toString('base64url');
  cookies.set(name, token, {
    httpOnly: false,
    secure: isProduction(),
    sameSite: 'lax',
    path: '/',
    maxAge: CSRF_MAX_AGE,
  });
  return token;
}

function constantTimeEqual(left: string, right: string): boolean {
  const a = Buffer.from(left);
  const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

export function assertSameOrigin(request: Request): void {
  const origin = request.headers.get('origin');
  if (!origin) throw new RequestSecurityError('origin_mismatch');
  if (origin === getWebOrigin()) return;
  try {
    const requestOrigin = new URL(request.url).origin;
    if (origin === requestOrigin) return;
  } catch {
    // Fall through to the strict rejection below.
  }
  throw new RequestSecurityError('origin_mismatch');
}

export function assertCsrf(request: Request, cookies: AstroCookies, submitted?: string | null): void {
  const cookie = cookies.get(cookieNames().csrf)?.value || '';
  const header = request.headers.get('x-elyan-csrf') || '';
  const candidate = String(submitted || header).trim();
  if (!cookie || !candidate || !constantTimeEqual(cookie, candidate)) {
    throw new RequestSecurityError('csrf_mismatch');
  }
}

export function assertMutationSecurity(request: Request, cookies: AstroCookies, submitted?: string | null): void {
  assertSameOrigin(request);
  assertCsrf(request, cookies, submitted);
}

export function safeReturnTo(value: unknown, fallback = '/app'): string {
  const path = String(value ?? '').trim();
  if (!path.startsWith('/app') || path.startsWith('//') || path.includes('\\') || /[\r\n]/.test(path)) return fallback;
  try {
    const parsed = new URL(path, 'https://elyan.invalid');
    if (parsed.origin !== 'https://elyan.invalid') return fallback;
    if (parsed.pathname === '/app/login' || parsed.pathname === '/app/register') return fallback;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}

export function signTransaction(payload: Record<string, unknown>): string {
  const encoded = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const signature = createHmac('sha256', getWebSessionSecret()).update(encoded).digest('base64url');
  return `${encoded}.${signature}`;
}

export function verifyTransaction<T extends Record<string, unknown>>(value: string | undefined): T | null {
  if (!value) return null;
  const [encoded, signature, extra] = value.split('.');
  if (!encoded || !signature || extra) return null;
  const expected = createHmac('sha256', getWebSessionSecret()).update(encoded).digest('base64url');
  if (!constantTimeEqual(signature, expected)) return null;
  try {
    const payload = JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8')) as T;
    const expiresAt = Number(payload.expiresAt || 0);
    return Number.isFinite(expiresAt) && expiresAt > Date.now() ? payload : null;
  } catch {
    return null;
  }
}
