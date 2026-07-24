import type { APIRoute } from 'astro';
import { backendFetch } from '../../../../../lib/server/backend';
import { cookieNames, deleteCookie, setSessionCookies, type TokenBundle } from '../../../../../lib/server/cookies';
import { json, normalizePublicError, readJsonSafe } from '../../../../../lib/server/http';
import { assertMutationSecurity, RequestSecurityError, verifyTransaction } from '../../../../../lib/server/security';
import { readLimitedJson } from '../../../../../lib/server/body';

export const prerender = false;

type AppleTransaction = { state: string; nonce: string; expiresAt: number };

function tokenNonce(idToken: string): string | null {
  try {
    const payload = JSON.parse(Buffer.from(idToken.split('.')[1] || '', 'base64url').toString('utf8')) as Record<string, unknown>;
    return typeof payload.nonce === 'string' ? payload.nonce : null;
  } catch {
    return null;
  }
}

export const POST: APIRoute = async ({ request, cookies, clientAddress }) => {
  try {
    assertMutationSecurity(request, cookies);
    const body = await readLimitedJson(request);
    const transaction = verifyTransaction<AppleTransaction>(cookies.get(cookieNames().appleTransaction)?.value);
    deleteCookie(cookies, cookieNames().appleTransaction);
    const state = String(body.state || '');
    const idToken = String(body.idToken || '').trim();
    if (!transaction || !state || state !== transaction.state || !idToken) {
      return json({ error: 'apple_transaction_invalid', message: 'Apple sign-in could not be verified.' }, 403);
    }
    const nonce = tokenNonce(idToken);
    if (!nonce || nonce !== transaction.nonce) {
      return json({ error: 'apple_nonce_invalid', message: 'Apple sign-in could not be verified.' }, 403);
    }

    const response = await backendFetch({
      path: '/v1/auth/oauth/apple',
      method: 'POST',
      contentType: 'application/json',
      body: JSON.stringify({
        idToken,
        authorizationCode: String(body.authorizationCode || '').trim() || undefined,
        displayName: String(body.displayName || '').trim() || undefined,
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
