import { randomBytes } from 'node:crypto';
import type { APIRoute } from 'astro';
import { cookieNames, setShortLivedHttpOnlyCookie } from '../../../../../lib/server/cookies';
import { json, normalizePublicError } from '../../../../../lib/server/http';
import { assertMutationSecurity, RequestSecurityError, signTransaction } from '../../../../../lib/server/security';

export const prerender = false;

export const POST: APIRoute = async ({ request, cookies }) => {
  try {
    assertMutationSecurity(request, cookies);
    const state = randomBytes(24).toString('base64url');
    const nonce = randomBytes(24).toString('base64url');
    const expiresAt = Date.now() + 10 * 60_000;
    setShortLivedHttpOnlyCookie(
      cookies,
      cookieNames().appleTransaction,
      signTransaction({ state, nonce, expiresAt }),
      10 * 60,
    );
    return json({ state, nonce });
  } catch (error) {
    if (error instanceof RequestSecurityError) return json(normalizePublicError({ error: error.code }, error.status), error.status);
    return json(normalizePublicError(error, 503), 503);
  }
};
