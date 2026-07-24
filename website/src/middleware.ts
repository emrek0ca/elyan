import { defineMiddleware } from 'astro:middleware';
import { hasSessionCookie } from './lib/server/cookies';
import { ensureCsrfToken, safeReturnTo } from './lib/server/security';

const PUBLIC_APP_PATHS = new Set(['/app/login', '/app/register']);

function contentSecurityPolicy(pathname: string): string {
  const authRoute = PUBLIC_APP_PATHS.has(pathname);
  const google = 'https://accounts.google.com';
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    `img-src 'self' data: blob:${authRoute ? ' https://*.googleusercontent.com' : ''}`,
    "font-src 'self' data:",
    `style-src 'self' 'unsafe-inline'${authRoute ? ` ${google} https://appleid.cdn-apple.com` : ''}`,
    `script-src 'self' 'unsafe-inline'${authRoute ? ` ${google} https://appleid.cdn-apple.com` : ''}`,
    `connect-src 'self'${authRoute ? ` ${google} https://appleid.apple.com` : ''}`,
    `frame-src${authRoute ? ` ${google} https://appleid.apple.com` : " 'none'"}`,
    `form-action 'self'${authRoute ? ' https://appleid.apple.com' : ''}`,
  ].join('; ');
}

export const onRequest = defineMiddleware(async (context, next) => {
  const pathname = context.url.pathname;
  const isApp = pathname === '/app' || pathname.startsWith('/app/');

  if (isApp) ensureCsrfToken(context.cookies);

  const isApi = pathname.startsWith('/app/api/');
  if (isApp && !isApi && !PUBLIC_APP_PATHS.has(pathname) && !hasSessionCookie(context.cookies)) {
    const returnTo = safeReturnTo(`${pathname}${context.url.search}`);
    return context.redirect(`/app/login?returnTo=${encodeURIComponent(returnTo)}`, 303);
  }

  if (PUBLIC_APP_PATHS.has(pathname) && hasSessionCookie(context.cookies)) {
    return context.redirect('/app', 303);
  }

  const response = await next();
  if (!isApp) return response;

  response.headers.set('cache-control', 'no-store, max-age=0');
  response.headers.set('pragma', 'no-cache');
  response.headers.set('referrer-policy', 'strict-origin-when-cross-origin');
  response.headers.set('x-content-type-options', 'nosniff');
  response.headers.set('x-frame-options', 'DENY');
  response.headers.set('permissions-policy', 'camera=(), geolocation=(), microphone=(), payment=(self)');
  response.headers.set('cross-origin-opener-policy', 'same-origin-allow-popups');
  response.headers.set('content-security-policy', contentSecurityPolicy(pathname));
  return response;
});
