export class FakeCookies {
  values = new Map<string, string>();
  setCalls: Array<{ name: string; value: string; options: Record<string, unknown> }> = [];
  deleteCalls: Array<{ name: string; options: Record<string, unknown> }> = [];

  constructor(initial: Record<string, string> = {}) {
    Object.entries(initial).forEach(([key, value]) => this.values.set(key, value));
  }

  get(name: string) {
    const value = this.values.get(name);
    return value == null ? undefined : { value };
  }

  set(name: string, value: string, options: Record<string, unknown>) {
    this.values.set(name, value);
    this.setCalls.push({ name, value, options });
  }

  delete(name: string, options: Record<string, unknown>) {
    this.values.delete(name);
    this.deleteCalls.push({ name, options });
  }
}

export function jsonResponse(body: unknown, status = 200, headers: HeadersInit = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } });
}

export function csrfRequest(url: string, method: string, csrf: string, body = '{}', extraHeaders: HeadersInit = {}): Request {
  return new Request(url, {
    method,
    headers: { origin: 'http://localhost:4321', 'content-type': 'application/json', 'x-elyan-csrf': csrf, ...extraHeaders },
    body: ['GET', 'HEAD'].includes(method) ? undefined : body,
  });
}
