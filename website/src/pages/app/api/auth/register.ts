import type { APIRoute } from 'astro';
import { backendFetch } from '../../../../lib/server/backend';
import { setSessionCookies, type TokenBundle } from '../../../../lib/server/cookies';
import { normalizePublicError, readJsonSafe } from '../../../../lib/server/http';
import { readLimitedFormData } from '../../../../lib/server/body';
import { assertMutationSecurity } from '../../../../lib/server/security';

export const prerender = false;

export const POST: APIRoute = async ({ request, cookies, redirect, clientAddress }) => {
  try {
    const formData = await readLimitedFormData(request);
    assertMutationSecurity(request, cookies, formData.get('_csrf')?.toString());
    const email = formData.get('email')?.toString() || '';
    const password = formData.get('password')?.toString() || '';
    const displayName = formData.get('displayName')?.toString() || '';
    const termsAccepted = formData.get('termsAccepted') === 'on';
    const privacyAccepted = formData.get('privacyAccepted') === 'on';
    const aiDataSharingAccepted = formData.get('aiDataSharingAccepted') === 'on';
    if (!termsAccepted || !privacyAccepted) {
      return redirect('/app/register?error=legal_acceptance_required', 303);
    }

    const payload = {
      email,
      password,
      ...(displayName ? { displayName } : {}),
      legalAcceptance: { termsAccepted, privacyAccepted, aiDataSharingAccepted },
    };

    const response = await backendFetch({
      path: '/v1/auth/register',
      method: 'POST',
      contentType: 'application/json',
      body: JSON.stringify(payload),
      signal: request.signal,
      sourceRequest: request,
      clientAddress,
    });
    const data = await readJsonSafe(response) as Record<string, unknown>;

    if (!response.ok) {
      const error = normalizePublicError(data, response.status);
      return redirect(`/app/register?error=${encodeURIComponent(error.error)}`, 303);
    }

    setSessionCookies(cookies, data.tokens as TokenBundle);
    return redirect('/app', 303);
  } catch (error) {
    const status = error && typeof error === 'object' && 'status' in error ? Number((error as { status: number }).status) : 503;
    const normalized = normalizePublicError(error, status);
    return redirect(`/app/register?error=${encodeURIComponent(normalized.error)}`, 303);
  }
};
