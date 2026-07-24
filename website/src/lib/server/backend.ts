import { createHash, randomUUID } from 'node:crypto';
import { isIP } from 'node:net';
import type { AstroCookies } from 'astro';
import { getApiBaseUrl, UPSTREAM_TIMEOUT_MS } from './config';
import { clearSessionCookies, readAccessToken, readRefreshToken, requireTokenBundle, setSessionCookies, type TokenBundle } from './cookies';
import { normalizePublicError, readJsonSafe, requestId } from './http';

export class BackendUnavailableError extends Error {
  status = 503;
  code = 'backend_unavailable';
}

type BackendRequest = {
  path: string;
  method?: string;
  token?: string | null;
  body?: BodyInit | null;
  contentType?: string | null;
  idempotencyKey?: string | null;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  timeoutMs?: number;
  stream?: boolean;
  sourceRequest?: Request;
  clientAddress?: string;
};

function trustedClientHeaders(request?: Request, clientAddress?: string): Record<string, string> {
  const headers: Record<string, string> = {};
  const address = String(clientAddress || '').trim();
  if (isIP(address)) headers['x-forwarded-for'] = address;
  const userAgent = String(request?.headers.get('user-agent') || '').replace(/[\r\n]/g, '').trim().slice(0, 512);
  if (userAgent) headers['user-agent'] = userAgent;
  return headers;
}

export async function backendFetch(input: BackendRequest): Promise<Response> {
  if (!input.path.startsWith('/v1/')) throw new Error('invalid_backend_path');
  const url = new URL(input.path, getApiBaseUrl());
  const controller = new AbortController();
  let cleaned = false;
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const abort = () => controller.abort('caller_aborted');
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    if (timeout) clearTimeout(timeout);
    input.signal?.removeEventListener('abort', abort);
  };
  timeout = setTimeout(() => {
    controller.abort('timeout');
    cleanup();
  }, input.timeoutMs ?? UPSTREAM_TIMEOUT_MS);
  input.signal?.addEventListener('abort', abort, { once: true });
  if (input.signal?.aborted) abort();
  const upstreamRequestId = requestId();

  try {
    const response = await fetch(url, {
      method: input.method || 'GET',
      headers: {
        accept: 'application/json',
        ...trustedClientHeaders(input.sourceRequest, input.clientAddress),
        ...input.headers,
        'x-request-id': upstreamRequestId,
        'x-elyan-client': 'web',
        ...(input.contentType ? { 'content-type': input.contentType } : {}),
        ...(input.token ? { authorization: `Bearer ${input.token}` } : {}),
        ...(input.idempotencyKey ? { 'idempotency-key': input.idempotencyKey } : {}),
      },
      body: input.body,
      signal: controller.signal,
      redirect: 'manual',
    });
    if (input.stream) clearTimeout(timeout);
    if (!response.body) {
      cleanup();
      return response;
    }

    const reader = response.body.getReader();
    const body = new ReadableStream<Uint8Array>({
      async pull(streamController) {
        try {
          const next = await reader.read();
          if (next.done) {
            cleanup();
            streamController.close();
          } else {
            streamController.enqueue(next.value);
          }
        } catch (error) {
          cleanup();
          streamController.error(error);
        }
      },
      async cancel(reason) {
        controller.abort('downstream_cancelled');
        cleanup();
        await reader.cancel(reason).catch(() => undefined);
      },
    });
    return new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers });
  } catch (error) {
    cleanup();
    if (input.signal?.aborted) throw error;
    throw new BackendUnavailableError('backend_request_failed');
  }
}

const refreshFlights = new Map<string, Promise<TokenBundle>>();

function refreshKey(token: string): string {
  return createHash('sha256').update(token).digest('hex');
}

async function performRefresh(refreshToken: string, context?: Pick<BackendRequest, 'sourceRequest' | 'clientAddress'>): Promise<TokenBundle> {
  const response = await backendFetch({
    path: '/v1/auth/refresh',
    method: 'POST',
    contentType: 'application/json',
    body: JSON.stringify({ refreshToken }),
    ...context,
  });
  const data = await readJsonSafe(response) as Record<string, unknown>;
  if (!response.ok) {
    const error = Object.assign(new Error('refresh_failed'), {
      status: response.status,
      definitive: [400, 401, 403].includes(response.status),
      publicError: normalizePublicError(data, response.status),
    });
    throw error;
  }
  return requireTokenBundle(data.tokens);
}

export async function refreshSession(cookies: AstroCookies, context?: Pick<BackendRequest, 'sourceRequest' | 'clientAddress'>): Promise<TokenBundle | null> {
  const refreshToken = readRefreshToken(cookies);
  if (!refreshToken) return null;
  const key = refreshKey(refreshToken);
  let flight = refreshFlights.get(key);
  if (!flight) {
    flight = performRefresh(refreshToken, context).finally(() => refreshFlights.delete(key));
    refreshFlights.set(key, flight);
  }
  try {
    const tokens = await flight;
    setSessionCookies(cookies, tokens);
    return tokens;
  } catch (error) {
    if (error && typeof error === 'object' && (error as { definitive?: boolean }).definitive) {
      clearSessionCookies(cookies);
    }
    throw error;
  }
}

type AuthenticatedRequest = Omit<BackendRequest, 'token'> & { retryAuth?: boolean };

export async function authenticatedBackendFetch(cookies: AstroCookies, input: AuthenticatedRequest): Promise<Response> {
  let accessToken = readAccessToken(cookies);
  if (!accessToken && readRefreshToken(cookies)) {
    const refreshed = await refreshSession(cookies, { sourceRequest: input.sourceRequest, clientAddress: input.clientAddress });
    accessToken = refreshed?.accessToken || null;
  }
  if (!accessToken) {
    return new Response(JSON.stringify({ error: 'unauthorized', message: 'Sign in required.' }), {
      status: 401,
      headers: { 'content-type': 'application/json' },
    });
  }

  const first = await backendFetch({ ...input, token: accessToken });
  if (first.status !== 401 || input.retryAuth === false) return first;
  if (!readRefreshToken(cookies)) {
    clearSessionCookies(cookies);
    return first;
  }
  first.body?.cancel().catch(() => undefined);
  const refreshed = await refreshSession(cookies, { sourceRequest: input.sourceRequest, clientAddress: input.clientAddress });
  if (!refreshed) {
    return new Response(JSON.stringify({ error: 'unauthorized', message: 'Sign in required.' }), {
      status: 401,
      headers: { 'content-type': 'application/json' },
    });
  }
  const retried = await backendFetch({ ...input, token: refreshed.accessToken });
  if (retried.status === 401) clearSessionCookies(cookies);
  return retried;
}

export function validIdempotencyKey(value: string | null): string | null {
  const candidate = String(value || '').trim();
  return /^[A-Za-z0-9:_-]{8,200}$/.test(candidate) ? candidate : null;
}

export function generatedIdempotencyKey(scope: string): string {
  return `web:${scope}:${randomUUID()}`;
}
