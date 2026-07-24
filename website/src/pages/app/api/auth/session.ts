import type { APIRoute } from 'astro';
import { authenticatedBackendFetch } from '../../../../lib/server/backend';
import { json, normalizePublicError, readJsonSafe } from '../../../../lib/server/http';

export const prerender = false;

export const GET: APIRoute = async ({ cookies, request, clientAddress }) => {
  try {
    const response = await authenticatedBackendFetch(cookies, {
      path: '/v1/web/bootstrap',
      signal: request.signal,
      sourceRequest: request,
      clientAddress,
    });
    const data = await readJsonSafe(response);
    return response.ok ? json(data) : json(normalizePublicError(data, response.status), response.status);
  } catch (error) {
    const status = error && typeof error === 'object' && 'status' in error ? Number((error as { status: number }).status) : 503;
    return json(normalizePublicError(error, status), status);
  }
};
