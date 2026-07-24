import { describe, expect, it, vi } from 'vitest';
import { POST as proxyPost } from '../src/pages/app/api/backend/[...path]';
import { GET as streamGet } from '../src/pages/app/api/realtime/stream';
import { GET as checkoutGet } from '../src/pages/app/api/billing/checkout/[referenceId]';
import { cookieNames } from '../src/lib/server/cookies';
import { backendFetch } from '../src/lib/server/backend';
import { FakeCookies, csrfRequest, jsonResponse } from './helpers';

describe('same-origin BFF integration', () => {
  it('ignores browser Authorization and injects the HttpOnly session token', async () => {
    const csrf = 'c'.repeat(43); const cookies = new FakeCookies({ [cookieNames().access]: 'cookie-access', [cookieNames().csrf]: csrf });
    let headers = new Headers(); let upstreamUrl = '';
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => { upstreamUrl = String(input); headers = new Headers(init?.headers); return jsonResponse({ ok: true }); }));
    const request = csrfRequest('http://localhost:4321/app/api/backend/tasks/00000000-0000-4000-8000-000000000001/approval', 'POST', csrf, JSON.stringify({ approved: true }), { authorization: 'Bearer attacker', 'idempotency-key': 'web:approval:12345678', 'user-agent': 'Elyan Browser Test' });
    const response = await proxyPost({ request, cookies, params: { path: 'tasks/00000000-0000-4000-8000-000000000001/approval' }, url: new URL(request.url), clientAddress: '203.0.113.8' } as never);
    expect(response.status).toBe(200); expect(upstreamUrl).toContain('/v1/tasks/00000000-0000-4000-8000-000000000001/approval');
    expect(headers.get('authorization')).toBe('Bearer cookie-access'); expect(headers.get('authorization')).not.toContain('attacker');
    expect(headers.get('x-forwarded-for')).toBe('203.0.113.8'); expect(headers.get('user-agent')).toBe('Elyan Browser Test');
  });

  it('forwards SSE cursor and cancel signal to the authenticated upstream', async () => {
    const cookies = new FakeCookies({ [cookieNames().access]: 'cookie-access' }); let headers = new Headers();
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => { headers = new Headers(init?.headers); return new Response('id: 42\nevent: heartbeat\ndata: {}\n\n', { headers: { 'content-type': 'text/event-stream' } }); }));
    const request = new Request('http://localhost:4321/app/api/realtime/stream?cursor=41', { headers: { 'last-event-id': '41' } });
    const response = await streamGet({ request, cookies, url: new URL(request.url) } as never);
    expect(response.status).toBe(200); expect(response.headers.get('content-type')).toContain('text/event-stream'); expect(headers.get('last-event-id')).toBe('41');
  });

  it('keeps caller abort propagation active after streaming response headers arrive', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const upstreamSignal = init?.signal as AbortSignal;
      const body = new ReadableStream<Uint8Array>({ start(controller) { upstreamSignal.addEventListener('abort', () => controller.error(new Error('upstream_aborted')), { once: true }); } });
      return new Response(body, { headers: { 'content-type': 'text/event-stream' } });
    }));
    const caller = new AbortController();
    const response = await backendFetch({ path: '/v1/realtime/stream', signal: caller.signal, stream: true });
    const pendingRead = response.body!.getReader().read(); caller.abort();
    await expect(pendingRead).rejects.toThrow('upstream_aborted');
  });

  it('checks checkout ownership before forwarding a HTTPS launch redirect', async () => {
    const referenceId = '00000000-0000-4000-8000-000000000002'; const cookies = new FakeCookies({ [cookieNames().access]: 'cookie-access' }); let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => { calls += 1; return jsonResponse({ checkout: { referenceId } }); }));
    const request = new Request(`http://localhost:4321/app/api/billing/checkout/${referenceId}`);
    const response = await checkoutGet({ request, cookies, params: { referenceId } } as never);
    expect(calls).toBe(1); expect(response.status).toBe(303); expect(response.headers.get('location')).toBe(`https://api.elyan.dev/v1/billing/checkouts/${referenceId}/launch`);
  });

  it('rejects a chunked body as soon as it crosses the BFF byte limit', async () => {
    const csrf = 'l'.repeat(43); const cookies = new FakeCookies({ [cookieNames().access]: 'cookie-access', [cookieNames().csrf]: csrf });
    const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array(700_000)); controller.enqueue(new Uint8Array(700_000)); controller.close(); } });
    const request = new Request('http://localhost:4321/app/api/backend/chat/messages', { method: 'POST', headers: { origin: 'http://localhost:4321', 'content-type': 'application/json', 'x-elyan-csrf': csrf }, body: stream, duplex: 'half' } as RequestInit & { duplex: 'half' });
    const fetchMock = vi.fn(); vi.stubGlobal('fetch', fetchMock);
    const response = await proxyPost({ request, cookies, params: { path: 'chat/messages' }, url: new URL(request.url) } as never);
    expect(response.status).toBe(413); expect(fetchMock).not.toHaveBeenCalled();
  });
});
