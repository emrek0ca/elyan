import { NextRequest, NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { env } from '@/lib/env';
import {
  applyCorsHeaders,
  applyHeaderEntries,
  getAllowedApiOrigins,
  getBaseSecurityHeaders,
  isAllowedApiOrigin,
} from '@/lib/security';

const allowedApiOrigins = getAllowedApiOrigins();

function isProtectedPage(pathname: string) {
  return (
    pathname === '/chat' ||
    pathname.startsWith('/chat/') ||
    pathname === '/manage' ||
    pathname.startsWith('/manage/') ||
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
    pathname.startsWith('/api/control-plane/accounts/') ||
    pathname.startsWith('/api/control-plane/notifications/')
  );
}

async function hasHostedSession(request: NextRequest) {
  if (!env.NEXTAUTH_SECRET || !env.DATABASE_URL) {
    return true;
  }

  const token = await getToken({ req: request, secret: env.NEXTAUTH_SECRET });
  return Boolean(token?.sub && token?.accountId);
}

export async function middleware(request: NextRequest) {
  if (!request.nextUrl.pathname.startsWith('/api/')) {
    if (!isProtectedPage(request.nextUrl.pathname)) {
      return NextResponse.next();
    }

    const authed = await hasHostedSession(request);
    if (authed) {
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

  if (isProtectedApi(request.nextUrl.pathname)) {
    const authed = await hasHostedSession(request);
    if (authed) {
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
  matcher: ['/api/:path*'],
};
