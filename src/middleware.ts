import { NextRequest, NextResponse } from 'next/server';

const ALLOWED_ORIGIN = 'https://elyan.dev';

function applyCorsHeaders(response: NextResponse) {
  response.headers.set('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
  response.headers.set('Access-Control-Allow-Credentials', 'true');
  response.headers.set(
    'Access-Control-Allow-Methods',
    'GET,POST,PUT,PATCH,DELETE,OPTIONS'
  );
  response.headers.set(
    'Access-Control-Allow-Headers',
    'Content-Type, Authorization, X-Requested-With, X-CSRF-Token, X-IYZ-SIGNATURE-V3, x-elyan-device-token, x-elyan-device-id, next-auth.csrf-token, next-auth.callback-url'
  );
  response.headers.set('Access-Control-Max-Age', '86400');
  response.headers.set('Vary', 'Origin');
  return response;
}

export function middleware(request: NextRequest) {
  if (!request.nextUrl.pathname.startsWith('/api/')) {
    return NextResponse.next();
  }

  const origin = request.headers.get('origin');

  if (request.method === 'OPTIONS') {
    if (origin && origin !== ALLOWED_ORIGIN) {
      return new NextResponse(null, { status: 403 });
    }

    return applyCorsHeaders(new NextResponse(null, { status: 204 }));
  }

  const response = NextResponse.next();

  if (origin === ALLOWED_ORIGIN) {
    applyCorsHeaders(response);
  }

  return response;
}

export const config = {
  matcher: ['/api/:path*'],
};
