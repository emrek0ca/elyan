import type { APIRoute } from 'astro';
import { authenticatedBackendFetch, generatedIdempotencyKey, validIdempotencyKey } from '../../../../lib/server/backend';
import { matchBffRule } from '../../../../lib/server/bff-allowlist';
import { readLimitedBody } from '../../../../lib/server/body';
import { json, normalizePublicError, readJsonSafe } from '../../../../lib/server/http';
import { assertMutationSecurity, RequestSecurityError } from '../../../../lib/server/security';

export const prerender = false;

const BODY_LIMIT = 1_048_576;

async function handle({ request, cookies, params, url, clientAddress }: Parameters<APIRoute>[0]): Promise<Response> {
  const path = String(params.path || '').replace(/^\/+|\/+$/g, '');
  const method = request.method.toUpperCase();
  const rule = matchBffRule(method, path);
  if (!rule) return json({ error: 'route_not_allowed', message: 'This operation is not available.' }, 404);

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) assertMutationSecurity(request, cookies);

  let body: ArrayBuffer | undefined;
  if (!['GET', 'HEAD'].includes(method)) {
    const bytes = await readLimitedBody(request, BODY_LIMIT);
    if (bytes.byteLength > 0) body = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  }

  const search = url.searchParams.toString();
  const upstreamPath = `/v1/${path}${search ? `?${search}` : ''}`;
  const idempotencyKey = rule.idempotent
    ? validIdempotencyKey(request.headers.get('idempotency-key')) || generatedIdempotencyKey(path.replace(/\W+/g, '-'))
    : null;
  const response = await authenticatedBackendFetch(cookies, {
    path: upstreamPath,
    method,
    contentType: request.headers.get('content-type')?.split(';', 1)[0] || (body ? 'application/json' : null),
    body,
    idempotencyKey,
    signal: request.signal,
    sourceRequest: request,
    clientAddress,
  });

  const contentType = response.headers.get('content-type') || 'application/json; charset=utf-8';
  if (!response.ok && contentType.includes('json')) {
    const error = normalizePublicError(await readJsonSafe(response), response.status);
    return json(error, response.status);
  }
  const headers = new Headers({
    'content-type': contentType,
    'cache-control': 'no-store, max-age=0',
    pragma: 'no-cache',
  });
  const disposition = response.headers.get('content-disposition');
  if (disposition) headers.set('content-disposition', disposition);
  return new Response(response.body, { status: response.status, headers });
}

const route: APIRoute = async (context) => {
  try {
    return await handle(context);
  } catch (error) {
    if (error instanceof RequestSecurityError) return json(normalizePublicError({ error: error.code }, error.status), error.status);
    const status = error && typeof error === 'object' && 'status' in error ? Number((error as { status: number }).status) : 503;
    return json(normalizePublicError(error, status), status);
  }
};

export const GET = route;
export const POST = route;
export const PUT = route;
export const PATCH = route;
export const DELETE = route;
