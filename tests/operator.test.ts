import http from 'node:http';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { buildOrchestrationPlan, runOperatorPreflight, type ExecutionSurfaceSnapshot } from '@/core/orchestration';

let server: http.Server;
let baseUrl = '';

function createSurface(): ExecutionSurfaceSnapshot {
  return {
    local: {
      capabilities: [
        {
          id: 'web_read_dynamic',
          title: 'Web Read Dynamic',
          description: 'Loads a rendered page with Playwright and extracts the visible content.',
          library: 'playwright',
          timeoutMs: 12_500,
          enabled: true,
        },
        {
          id: 'web_crawl',
          title: 'Web Crawl',
          description: 'Crawls same-domain pages with Crawlee and extracts readable HTML content.',
          library: 'crawlee',
          timeoutMs: 12_500,
          enabled: true,
        },
      ],
      bridgeTools: [],
    },
    mcp: {
      servers: [],
      tools: [],
      resources: [],
      resourceTemplates: [],
      prompts: [],
    },
  };
}

beforeAll(async () => {
  server = http.createServer((req, res) => {
    if (req.url === '/page-2') {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end('<html><head><title>Second</title></head><body><main><p>Second page text.</p></main></body></html>');
      return;
    }

    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(
      '<html><head><title>First</title></head><body><main><p>First page text.</p><a href="/page-2">Second</a></main></body></html>'
    );
  });

  await new Promise<void>((resolve) => {
    server.listen(0, '127.0.0.1', () => resolve());
  });

  const address = server.address();
  if (!address || typeof address === 'string') {
    throw new Error('Failed to start operator test server');
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

describe('Operator preflight', () => {
  it('chooses browser read for rendered page requests', async () => {
    const query = `Read this page and summarize it: ${baseUrl}`;
    const plan = buildOrchestrationPlan(query, 'speed', createSurface());
    const outcome = await runOperatorPreflight(query, plan.executionPolicy, createSurface());

    expect(plan.executionPolicy.primary.kind).toBe('browser_read');
    expect(outcome.sources).toHaveLength(1);
    expect(outcome.sources[0]?.url).toBe(`${baseUrl}/`);
    expect(outcome.sources[0]?.content).toContain('First page text');
  }, 15_000);

  it('chooses crawl for bounded multi-page coverage', async () => {
    const query = `Crawl this site and collect all page titles: ${baseUrl}`;
    const plan = buildOrchestrationPlan(query, 'research', createSurface());
    const outcome = await runOperatorPreflight(query, plan.executionPolicy, createSurface());

    expect(plan.executionPolicy.primary.kind).toBe('crawl');
    expect(outcome.sources.length).toBeGreaterThanOrEqual(1);
    expect(outcome.sources.some((source) => source.url.endsWith('/page-2'))).toBe(true);
  }, 15_000);
});
