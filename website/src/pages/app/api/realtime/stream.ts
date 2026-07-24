import type { APIRoute } from 'astro';
import { authenticatedBackendFetch } from '../../../../lib/server/backend';
import { json, normalizePublicError, readJsonSafe } from '../../../../lib/server/http';

export const prerender = false;

const uuid = /^[0-9a-fA-F-]{36}$/;

export const GET: APIRoute = async ({ request, cookies, url, clientAddress }) => {
  const upstreamQuery = new URLSearchParams();
  for (const key of ['taskId', 'deviceId'] as const) {
    const value = url.searchParams.get(key);
    if (value) {
      if (!uuid.test(value)) return json({ error: 'validation_error', message: `Invalid ${key}.` }, 400);
      upstreamQuery.set(key, value);
    }
  }
  if (upstreamQuery.has('taskId') && upstreamQuery.has('deviceId')) {
    return json({ error: 'validation_error', message: 'Only one stream filter may be used.' }, 400);
  }
  const cursor = url.searchParams.get('cursor');
  if (cursor) {
    if (!/^\d+$/.test(cursor) || Number(cursor) <= 0) return json({ error: 'validation_error', message: 'Invalid stream cursor.' }, 400);
    upstreamQuery.set('cursor', cursor);
  }
  const lastEventId = request.headers.get('last-event-id');
  if (lastEventId && !/^\d+$/.test(lastEventId)) return json({ error: 'validation_error', message: 'Invalid event cursor.' }, 400);

  try {
    const query = upstreamQuery.toString();
    const response = await authenticatedBackendFetch(cookies, {
      path: `/v1/realtime/stream${query ? `?${query}` : ''}`,
      headers: lastEventId ? { 'last-event-id': lastEventId } : undefined,
      signal: request.signal,
      stream: true,
      sourceRequest: request,
      clientAddress,
    });
    if (!response.ok) return json(normalizePublicError(await readJsonSafe(response), response.status), response.status);
    return new Response(response.body, {
      status: 200,
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache, no-transform',
        connection: 'keep-alive',
        'x-accel-buffering': 'no',
      },
    });
  } catch (error) {
    if (request.signal.aborted) return new Response(null, { status: 499 });
    const status = error && typeof error === 'object' && 'status' in error ? Number((error as { status: number }).status) : 503;
    return json(normalizePublicError(error, status), status);
  }
};
