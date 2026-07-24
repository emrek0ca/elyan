import type { APIRoute } from 'astro';
import { backendFetch } from '../../../../lib/server/backend';
import { setSessionCookies, type TokenBundle } from '../../../../lib/server/cookies';
import { normalizePublicError, readJsonSafe } from '../../../../lib/server/http';
import { readLimitedFormData } from '../../../../lib/server/body';
import { assertMutationSecurity, safeReturnTo } from '../../../../lib/server/security';

export const prerender = false;

export const POST: APIRoute = async ({ request, cookies, redirect, clientAddress }) => {
  try {
    const formData = await readLimitedFormData(request);
    assertMutationSecurity(request, cookies, formData.get('_csrf')?.toString());
    const email = formData.get('email')?.toString() || '';
    const password = formData.get('password')?.toString() || '';
    const twoFactorCode = formData.get('twoFactorCode')?.toString().trim() || undefined;
    const returnTo = safeReturnTo(formData.get('returnTo'));

    const response = await backendFetch({
      path: '/v1/auth/login',
      method: 'POST',
      contentType: 'application/json',
      body: JSON.stringify({ email, password, ...(twoFactorCode ? { twoFactorCode } : {}) }),
      signal: request.signal,
      sourceRequest: request,
      clientAddress,
    });
    const data = await readJsonSafe(response) as Record<string, unknown>;

    if (!response.ok) {
      const error = normalizePublicError(data, response.status);
      const query = new URLSearchParams({ error: error.error, returnTo });
      if (error.error === 'two_factor_required' || error.error === 'two_factor_invalid') query.set('twoFactor', '1');
      return redirect(`/app/login?${query}`, 303);
    }

    setSessionCookies(cookies, data.tokens as TokenBundle);
    return redirect(returnTo, 303);
  } catch (error) {
    const status = error && typeof error === 'object' && 'status' in error ? Number((error as { status: number }).status) : 503;
    const normalized = normalizePublicError(error, status);
    return redirect(`/app/login?error=${encodeURIComponent(normalized.error)}`, 303);
  }
};
