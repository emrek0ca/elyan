import type { APIRoute } from 'astro';
import { backendFetch } from '../../../../../lib/server/backend';
import { setSessionCookies, type TokenBundle } from '../../../../../lib/server/cookies';
import { json, normalizePublicError, readJsonSafe } from '../../../../../lib/server/http';
import { assertMutationSecurity, RequestSecurityError } from '../../../../../lib/server/security';
import { readLimitedJson } from '../../../../../lib/server/body';

export const prerender = false;

function equalCsrf(left: string, right: string): boolean {
  if (!left || left.length !== right.length) return false;
  let result = 0;
  for (let index = 0; index < left.length; index += 1) result |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return result === 0;
}

export const POST: APIRoute = async ({ request, cookies, clientAddress }) => {
  try {
    assertMutationSecurity(request, cookies);
    const body = await readLimitedJson(request);
    const googleCookie = cookies.get('g_csrf_token')?.value || '';
    const googleBody = String(body.gCsrfToken || '');
    if (!equalCsrf(googleCookie, googleBody)) return json({ error: 'google_csrf_invalid', message: 'Google sign-in could not be verified.' }, 403);
    const idToken = String(body.credential || '').trim();
    if (!idToken) return json({ error: 'invalid_google_token', message: 'Google sign-in did not return a credential.' }, 400);

    const response = await backendFetch({
      path: '/v1/auth/oauth/google',
      method: 'POST',
      contentType: 'application/json',
      body: JSON.stringify({
        idToken,
        ...(body.register === true ? {
          legalAcceptance: {
            termsAccepted: body.termsAccepted === true,
            privacyAccepted: body.privacyAccepted === true,
            aiDataSharingAccepted: body.aiDataSharingAccepted === true,
          },
        } : {}),
      }),
      signal: request.signal,
      sourceRequest: request,
      clientAddress,
    });
    const data = await readJsonSafe(response) as Record<string, unknown>;
    if (!response.ok) return json(normalizePublicError(data, response.status), response.status);
    setSessionCookies(cookies, data.tokens as TokenBundle);
    return json({ ok: true, user: data.user, subscription: data.subscription });
  } catch (error) {
    if (error instanceof RequestSecurityError) return json(normalizePublicError({ error: error.code }, error.status), error.status);
    const status = error && typeof error === 'object' && 'status' in error ? Number((error as { status: number }).status) : 503;
    return json(normalizePublicError(error, status), status);
  }
};
