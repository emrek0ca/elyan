import { createServer } from 'node:http';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { CapabilityAuditTrail, CapabilityRegistry } from '@/core/capabilities';

describe('Web crawl capability', () => {
  let server: ReturnType<typeof createServer>;
  let baseUrl = '';

  beforeAll(async () => {
    server = createServer((req, res) => {
      const url = req.url || '/';

      if (url === '/alpha') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(`<!doctype html>
          <html><head><title>Alpha</title></head><body><main>Alpha page</main></body></html>`);
        return;
      }

      if (url === '/zeta') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(`<!doctype html>
          <html><head><title>Zeta</title></head><body><main>Zeta page</main></body></html>`);
        return;
      }

      if (url === '/about') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(`<!doctype html>
          <html><head><title>About</title></head><body>
            <main><a href="/team">Team</a></main>
          </body></html>`);
        return;
      }

      if (url === '/team') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end(`<!doctype html>
          <html><head><title>Team</title></head><body><main>Team page</main></body></html>`);
        return;
      }

      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(`<!doctype html>
        <html><head><title>Home</title></head><body>
          <main>
            <a href="/about">About</a>
          </main>
        </body></html>`);
    });

    await new Promise<void>((resolve) => {
      server.listen(0, '127.0.0.1', () => resolve());
    });

    const address = server.address();
    if (!address || typeof address === 'string') {
      throw new Error('Failed to start crawl test server');
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

  it('crawls same-domain pages and follows links up to depth', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const result = await registry.execute('web_crawl', {
      startUrls: [`${baseUrl}/`],
      maxPages: 5,
      maxDepth: 2,
      sameDomainOnly: true,
    });

    const urls = result.pages.map((page) => page.url);

    expect(urls.some((url) => url.endsWith('/'))).toBe(true);
    expect(urls.some((url) => url.endsWith('/about'))).toBe(true);
    expect(urls.some((url) => url.endsWith('/team'))).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('returns crawled pages in a canonical order', async () => {
    const registry = new CapabilityRegistry(new CapabilityAuditTrail());
    const result = await registry.execute('web_crawl', {
      startUrls: [`${baseUrl}/zeta`, `${baseUrl}/alpha`],
      maxPages: 5,
      maxDepth: 0,
      sameDomainOnly: true,
    });

    expect(result.pages.map((page) => page.url)).toEqual([
      `${baseUrl}/alpha`,
      `${baseUrl}/zeta`,
    ]);
    expect(result.errors).toHaveLength(0);
  });
});
