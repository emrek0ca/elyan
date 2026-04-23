import { NextRequest, NextResponse } from 'next/server';
import {
  applyCorsHeaders,
  applyHeaderEntries,
  getAllowedApiOrigins,
  getBaseSecurityHeaders,
  isAllowedApiOrigin,
} from '@/lib/security';

const allowedApiOrigins = getAllowedApiOrigins();

export function middleware(request: NextRequest) {
  if (!request.nextUrl.pathname.startsWith('/api/')) {
    return NextResponse.next();
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
