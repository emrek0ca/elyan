import { NextRequest, NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { env } from '@/lib/env';
import { consumeFixedWindowRateLimit } from '@/core/security/rate-limit';
import {
  applyCorsHeaders,
  applyHeaderEntries,
  getAllowedApiOrigins,
  getBaseSecurityHeaders,
  isAllowedApiOrigin,
} from '@/lib/security';

const allowedApiOrigins = getAllowedApiOrigins();
const REQUEST_RATE_LIMITS = {
  ip: { limit: 240, windowMs: 60_000 },
  user: { limit: 120, windowMs: 60_000 },
  device: { limit: 120, windowMs: 60_000 },
} as const;

function isProtectedPage(pathname: string) {
  return (
    pathname === '/panel' ||
    pathname.startsWith('/panel/')
  );
}

function isProtectedApi(pathname: string) {
  return (
    pathname === '/api/chat' ||
    pathname === '/api/control-plane/panel' ||
    pathname === '/api/control-plane/auth/me' ||
    pathname === '/api/control-plane/billing/iyzico/initialize' ||
    pathname === '/api/control-plane/devices/link/start' ||
    pathname === '/api/devices/link/start' ||
    pathname.startsWith('/api/control-plane/accounts/') ||
    pathname.startsWith('/api/control-plane/notifications/')
  );
}

async function getHostedSessionToken(request: NextRequest) {
  const secret = env.NEXTAUTH_SECRET ?? env.AUTH_SECRET;
  if (!secret || !env.DATABASE_URL) {
    return null;
  }

  const token = await getToken({ req: request, secret });
  return token?.sub && token?.accountId ? token : null;
}

function readClientIp(request: NextRequest) {
  const forwarded = request.headers.get('x-forwarded-for');
  if (forwarded) {
    const candidate = forwarded.split(',')[0]?.trim();
    if (candidate) {
      return candidate;
    }
  }

  const realIp = request.headers.get('x-real-ip')?.trim();
  if (realIp) {
    return realIp;
  }

  const requestIp = (request as NextRequest & { ip?: string }).ip?.trim();
  return requestIp || 'unknown';
}

function readDeviceToken(request: NextRequest) {
  return (
    request.headers.get('x-elyan-device-token')?.trim() ||
    request.headers.get('authorization')?.replace(/^Bearer\s+/i, '').trim() ||
    undefined
  );
}

function buildRateLimitedResponse(scope: 'ip' | 'user' | 'device', resetAt: string) {
  const denied = NextResponse.json(
    {
      ok: false,
      error: 'Rate limit exceeded',
      code: 'rate_limit_exceeded',
      scope,
      resetAt,
    },
    { status: 429 }
  );

  return denied;
}

function applyRateLimiting(request: NextRequest, token: Awaited<ReturnType<typeof getHostedSessionToken>>) {
  const scopes: Array<{ scope: 'ip' | 'user' | 'device'; key: string; limit: number; windowMs: number }> = [
    {
      scope: 'ip',
      key: readClientIp(request),
      ...REQUEST_RATE_LIMITS.ip,
    },
  ];

  if (token?.sub || token?.accountId) {
    scopes.push({
      scope: 'user',
      key: token.accountId ?? token.sub ?? 'unknown',
      ...REQUEST_RATE_LIMITS.user,
    });
  }

  const deviceToken = readDeviceToken(request);
  if (deviceToken) {
    scopes.push({
      scope: 'device',
      key: deviceToken,
      ...REQUEST_RATE_LIMITS.device,
    });
  }

  for (const scope of scopes) {
    const result = consumeFixedWindowRateLimit(scope);
    if (!result.allowed) {
      return buildRateLimitedResponse(scope.scope, result.resetAt);
    }
  }

  return null;
}

export async function middleware(request: NextRequest) {
  if (!request.nextUrl.pathname.startsWith('/api/')) {
    if (!isProtectedPage(request.nextUrl.pathname)) {
      return NextResponse.next();
    }

    const authed = await getHostedSessionToken(request);
    const isAuthed = Boolean(authed);
    if (isAuthed) {
      return NextResponse.next();
    }

    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = '/auth';
    redirectUrl.searchParams.set('next', `${request.nextUrl.pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(redirectUrl);
  }

  const origin = request.headers.get('origin');

  if (request.method === 'OPTIONS') {
    if (origin && !isAllowedApiOrigin(origin, allowedApiOrigins)) {
      const forbidden = new NextResponse(null, { status: 403 });
      applyHeaderEntries(forbidden.headers, getBaseSecurityHeaders());
      return forbidden;
    }

    const preflight = new NextResponse(null, { status: 204 });
    applyHeaderEntries(preflight.headers, getBaseSecurityHeaders());

    if (origin && isAllowedApiOrigin(origin, allowedApiOrigins)) {
      applyCorsHeaders(preflight.headers, origin.trim());
    }

    return preflight;
  }

  const token = await getHostedSessionToken(request);
  const rateLimited = applyRateLimiting(request, token);
  if (rateLimited) {
    applyHeaderEntries(rateLimited.headers, getBaseSecurityHeaders());
    if (origin && isAllowedApiOrigin(origin, allowedApiOrigins)) {
      applyCorsHeaders(rateLimited.headers, origin.trim());
    }
    return rateLimited;
  }

  if (isProtectedApi(request.nextUrl.pathname)) {
    if (token) {
      const response = NextResponse.next();
      applyHeaderEntries(response.headers, getBaseSecurityHeaders());

      if (origin && isAllowedApiOrigin(origin, allowedApiOrigins)) {
        applyCorsHeaders(response.headers, origin.trim());
      }

      return response;
    }

    const denied = NextResponse.json(
      {
        ok: false,
        error: 'Control-plane session is required',
        code: 'control_plane_session_required',
      },
      { status: 401 }
    );
    applyHeaderEntries(denied.headers, getBaseSecurityHeaders());
    if (origin && isAllowedApiOrigin(origin, allowedApiOrigins)) {
      applyCorsHeaders(denied.headers, origin.trim());
    }
    return denied;
  }

  const response = NextResponse.next();
  applyHeaderEntries(response.headers, getBaseSecurityHeaders());

  if (origin && isAllowedApiOrigin(origin, allowedApiOrigins)) {
    applyCorsHeaders(response.headers, origin.trim());
  }

  return response;
}

export const config = {
  matcher: ['/api/:path*', '/panel/:path*'],
};
