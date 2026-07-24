import type { APIRoute } from 'astro';
import { authenticatedBackendFetch } from '../../../../lib/server/backend';
import { clearSessionCookies } from '../../../../lib/server/cookies';
import { json, normalizePublicError } from '../../../../lib/server/http';
import { readLimitedFormData } from '../../../../lib/server/body';
import { assertCsrf, assertSameOrigin, RequestSecurityError } from '../../../../lib/server/security';

export const prerender = false;

export const POST: APIRoute = async ({ request, cookies, redirect, clientAddress }) => {
  const formRequest = request.headers.get('content-type')?.includes('form') === true;
  let sameOrigin = false;
  try {
    assertSameOrigin(request);
    sameOrigin = true;
    let form: FormData | null = null;
    try {
      form = formRequest ? await readLimitedFormData(request) : null;
      assertCsrf(request, cookies, form?.get('_csrf')?.toString());
      try {
        await authenticatedBackendFetch(cookies, { path: '/v1/auth/logout', method: 'POST', signal: request.signal, retryAuth: false, sourceRequest: request, clientAddress });
      } catch {
        // Logout is local-first: cookies are always removed even if the control-plane is temporarily down.
      }
    } finally {
      clearSessionCookies(cookies);
    }
    return formRequest ? redirect('/app/login', 303) : json({ ok: true });
  } catch (error) {
    if (error instanceof RequestSecurityError && !sameOrigin) return json(normalizePublicError({ error: error.code }, error.status), error.status);
    // Same-origin logout remains local-first even when a stale CSRF token or malformed body prevents upstream revocation.
    return formRequest ? redirect('/app/login', 303) : json({ ok: true });
  }
};
