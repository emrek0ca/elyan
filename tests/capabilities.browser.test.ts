import { createServer } from 'node:http';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('Browser capabilities', () => {
  let server: ReturnType<typeof createServer>;
  let baseUrl = '';

  beforeAll(async () => {
    server = createServer((req, res) => {
      const url = req.url || '/';

      if (url === '/links') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(`<!doctype html>
          <html>
            <head><title>Links</title></head>
            <body>
              <main>
                <a href="/zeta">Zeta</a>
                <a href="/alpha">Alpha</a>
                <a href="/alpha">Alpha</a>
                <a href="/automation">Automation</a>
              </main>
            </body>
          </html>`);
        return;
      }

      if (url === '/automation') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(`<!doctype html>
          <html>
            <head><title>Automation</title></head>
            <body>
              <input id="name" />
              <button id="submit" onclick="document.getElementById('result').textContent = document.getElementById('name').value">Save</button>
              <div id="result"></div>
            </body>
          </html>`);
        return;
      }

      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(`<!doctype html>
        <html>
          <head>
            <title>Dynamic</title>
            <script>
              window.addEventListener('DOMContentLoaded', () => {
                setTimeout(() => {
                  document.getElementById('status').textContent = 'rendered by script';
                }, 120);
              });
            </script>
          </head>
          <body>
            <main>
              <h1>Dynamic page</h1>
              <p id="status">loading</p>
              <a href="/automation">Automation page</a>
            </main>
          </body>
        </html>`);
    });

    await new Promise<void>((resolve) => {
      server.listen(0, '127.0.0.1', () => resolve());
    });

    const address = server.address();
    if (!address || typeof address === 'string') {
      throw new Error('Failed to start browser test server');
    }

    baseUrl = `http://127.0.0.1:${address.port}`;
  });

  afterAll(async () => {
    await new Promise<void>((resolve, reject) => {
      server.close((error) => {
        if (error) {
          reject(error);
          return;
        }

        resolve();
      });
    });
  });

  it('reads rendered browser content', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const result = await registry.execute('web_read_dynamic', {
      url: `${baseUrl}/`,
      settleMs: 250,
    });

    expect(result.title).toBe('Dynamic');
    expect(result.text).toContain('rendered by script');
    expect(result.links.some((link) => link.href.endsWith('/automation'))).toBe(true);
  }, 15_000);

  it('returns browser links in a deterministic order', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const result = await registry.execute('web_read_dynamic', {
      url: `${baseUrl}/links`,
      settleMs: 0,
    });

    expect(result.links.map((link) => link.href)).toEqual([
      `${baseUrl}/alpha`,
      `${baseUrl}/automation`,
      `${baseUrl}/zeta`,
    ]);
  }, 15_000);

  it('runs a short browser automation sequence', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const result = await registry.execute('browser_automation', {
      url: `${baseUrl}/automation`,
      actions: [
        { type: 'fill', selector: '#name', value: 'Elyan' },
        { type: 'click', selector: '#submit' },
        { type: 'waitForText', text: 'Elyan' },
      ],
      settleMs: 100,
    });

    expect(result.title).toBe('Automation');
    expect(result.text).toContain('Elyan');
    expect(result.actionsApplied).toBe(3);
  }, 15_000);
});
