import type { APIRoute } from 'astro';
import { authenticatedBackendFetch } from '../../../../../lib/server/backend';
import { getApiBaseUrl } from '../../../../../lib/server/config';
import { json, normalizePublicError, readJsonSafe } from '../../../../../lib/server/http';

export const prerender = false;

const uuid = /^[0-9a-fA-F-]{36}$/;

export const GET: APIRoute = async ({ params, cookies, request, clientAddress }) => {
  const referenceId = String(params.referenceId || '');
  if (!uuid.test(referenceId)) return json({ error: 'validation_error', message: 'Invalid checkout reference.' }, 400);
  try {
    const owned = await authenticatedBackendFetch(cookies, {
      path: `/v1/billing/checkouts/${referenceId}`,
      signal: request.signal,
      sourceRequest: request,
      clientAddress,
    });
    if (!owned.ok) return json(normalizePublicError(await readJsonSafe(owned), owned.status), owned.status);
    await owned.body?.cancel();
    const launch = new URL(`/v1/billing/checkouts/${referenceId}/launch`, getApiBaseUrl());
    return new Response(null, { status: 303, headers: { location: launch.href, 'cache-control': 'no-store' } });
  } catch (error) {
    const status = error && typeof error === 'object' && 'status' in error ? Number((error as { status: number }).status) : 503;
    return json(normalizePublicError(error, status), status);
  }
};
