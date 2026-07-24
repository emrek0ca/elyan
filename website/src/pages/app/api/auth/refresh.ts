import type { APIRoute } from 'astro';
import { refreshSession } from '../../../../lib/server/backend';
import { json, normalizePublicError } from '../../../../lib/server/http';
import { assertMutationSecurity, RequestSecurityError } from '../../../../lib/server/security';

export const prerender = false;

export const POST: APIRoute = async ({ request, cookies, clientAddress }) => {
  try {
    assertMutationSecurity(request, cookies);
    const tokens = await refreshSession(cookies, { sourceRequest: request, clientAddress });
    return tokens ? json({ ok: true }) : json({ error: 'unauthorized', message: 'Sign in required.' }, 401);
  } catch (error) {
    if (error instanceof RequestSecurityError) return json(normalizePublicError({ error: error.code }, error.status), error.status);
    const status = error && typeof error === 'object' && 'status' in error ? Number((error as { status: number }).status) : 503;
    return json(normalizePublicError(error, status), status);
  }
};
